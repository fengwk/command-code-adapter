from __future__ import annotations

import json
import os
import structlog
import tempfile
from pathlib import Path
from typing import Any

from cc_adapter.core.config import AppConfig, env_file_path
from cc_adapter.core.utils import normalize_api_keys
from cc_adapter.command_code.client import CommandCodeClient


_CONFIG_CLIENT_FIELDS = {"cc_api_key", "cc_base_url"}

FIELD_MAP = {
    "cc_api_key": "CC_ADAPTER_CC_API_KEY",
    "cc_base_url": "CC_ADAPTER_CC_BASE_URL",
    "host": "CC_ADAPTER_HOST",
    "port": "CC_ADAPTER_PORT",
    "log_level": "CC_ADAPTER_LOG_LEVEL",
    "log_format": "CC_ADAPTER_LOG_FORMAT",
    "default_model": "CC_ADAPTER_DEFAULT_MODEL",
    "zdr": "CC_ADAPTER_ZDR",
}

logger = structlog.get_logger(__name__)


def _apply_config_fields(cfg: AppConfig, updates: dict[str, Any]) -> bool:
    changed_client = False
    for field, value in updates.items():
        if field == "cc_api_key":
            value = normalize_api_keys(value)
        setattr(cfg, field, value)
        if field in _CONFIG_CLIENT_FIELDS:
            changed_client = True
    return changed_client


def _recreate_client(cfg: AppConfig) -> CommandCodeClient | None:
    from cc_adapter.core.runtime import get_client, init as state_init, create_client

    old = get_client()
    new = create_client(cfg)
    # The rebuilt client gets a fresh scheduler, so carry the operator's manual off-switch over:
    # a panel save (adding a key, editing the base URL) must not re-enable a key turned off on purpose.
    new_scheduler = getattr(new, "scheduler", None)
    old_scheduler = getattr(old, "scheduler", None)
    if new_scheduler is not None and old_scheduler is not None:
        for key in old_scheduler.manual_disabled_keys():
            if key in cfg.cc_api_key:
                new_scheduler.disable(key)
    state_init(cfg, new)
    return old


class ConfigManager:
    @staticmethod
    def update_env_file(updates: dict[str, Any], env_path: str | Path | None = None) -> None:
        env_path = Path(env_path or env_file_path())
        env_path.parent.mkdir(parents=True, exist_ok=True)
        if not env_path.exists():
            # The file holds API keys: create it private instead of world-readable (umask).
            env_path.touch(mode=0o600)

        lines = env_path.read_text().splitlines(keepends=True)
        existing_keys = set()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "=" not in stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            for field_name, env_key in FIELD_MAP.items():
                if key == env_key and field_name in updates:
                    value = (
                        normalize_api_keys(updates[field_name]) if field_name == "cc_api_key" else updates[field_name]
                    )
                    if field_name == "cc_api_key":
                        lines[i] = f"{env_key}={json.dumps(value)}\n"
                    else:
                        lines[i] = f"{env_key}={value}\n"
                    existing_keys.add(field_name)

        for field_name, env_key in FIELD_MAP.items():
            if field_name in updates and field_name not in existing_keys:
                value = normalize_api_keys(updates[field_name]) if field_name == "cc_api_key" else updates[field_name]
                if field_name == "cc_api_key":
                    lines.append(f"{env_key}={json.dumps(value)}\n")
                else:
                    lines.append(f"{env_key}={updates[field_name]}\n")

        content = "".join(lines)
        try:
            mode = env_path.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
        # Keep the temp file next to the target: the config file may live on a mounted
        # volume, where renaming from /tmp would fail with EXDEV (cross-device link).
        fd, tmp_path = tempfile.mkstemp(suffix=".env", prefix=".env_", text=True, dir=str(env_path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.chmod(tmp_path, mode)
            os.replace(tmp_path, str(env_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    async def apply_config_update(updates: dict[str, Any]) -> None:
        from cc_adapter.core.runtime import get_config

        cfg = get_config()
        if cfg is None:
            return
        changed_client = _apply_config_fields(cfg, updates)
        if changed_client:
            old = _recreate_client(cfg)
            if old is not None:
                # The old client may still be serving streams the routers captured per request;
                # close its pool only once they finish so a panel save cannot cut a response short.
                old.schedule_close_when_idle()
                logger.info("admin.config.client_rebuilt", inflight=old.inflight)
        logger.info("admin.config.updated", fields=list(updates.keys()))
