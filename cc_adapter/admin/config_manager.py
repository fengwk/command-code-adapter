from __future__ import annotations

import json
import os
import structlog
import tempfile
from pathlib import Path
from typing import Any

from cc_adapter.core.config import AppConfig, env_file_path
from cc_adapter.core.constants import normalize_distribution
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
    "distribution": "CC_ADAPTER_DISTRIBUTION",
    "zdr": "CC_ADAPTER_ZDR",
}

logger = structlog.get_logger(__name__)

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


def _normalize_bool(value: Any) -> bool:
    """Normalize one panel-managed boolean or reject it before memory and disk diverge."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _apply_config_fields(cfg: AppConfig, updates: dict[str, Any]) -> bool:
    changed_client = False
    for field, value in updates.items():
        if field == "cc_api_key":
            value = normalize_api_keys(value)
        elif field == "distribution":
            # Store the canonical mode, so a later client rebuild and the panel's GET
            # report the same value the live scheduler already runs.
            value = normalize_distribution(value)
        elif field == "zdr":
            value = _normalize_bool(value)
        setattr(cfg, field, value)
        if field in _CONFIG_CLIENT_FIELDS:
            changed_client = True
    return changed_client


def _apply_live_distribution(value: Any) -> None:
    """Point the running scheduler at the new mode (no client rebuild, no binding loss).

    A single-key pool has no scheduler, so there the mode only takes effect once a
    client is created with the updated config (adding a key rebuilds it anyway).
    """
    from cc_adapter.core.runtime import get_client

    scheduler = getattr(get_client(), "scheduler", None)
    if scheduler is None:
        return
    effective = scheduler.set_distribution(value)
    logger.info("admin.config.distribution", distribution=effective)


def _recreate_client(cfg: AppConfig) -> CommandCodeClient | None:
    from cc_adapter.core.runtime import get_client, init as state_init, create_client

    old = get_client()
    new = create_client(cfg)
    # The rebuilt client gets a fresh scheduler, so carry runtime scheduler state over:
    # manual off-switch, session affinity, health states, cooldowns, credits, etc.
    # A panel save must neither re-enable a disabled/cooling key nor drag running conversations
    # to another account. Removed keys leave no state or binding.
    new_scheduler = getattr(new, "scheduler", None)
    old_scheduler = getattr(old, "scheduler", None)
    if new_scheduler is not None and old_scheduler is not None:
        new_scheduler.import_state(old_scheduler.export_state())
    state_init(cfg, new)
    return old


def _env_line(field: str, value: Any) -> str:
    """Render one ``KEY=value`` dotenv line, with the field's own normalization.

    The file is what an operator reads and what ``AppConfig`` reloads, so a field that
    is validated in memory (the key pool, the distribution mode) is stored in the same
    canonical form instead of the raw panel input.
    """
    if field == "cc_api_key":
        return f"{FIELD_MAP[field]}={json.dumps(normalize_api_keys(value))}\n"
    if field == "distribution":
        return f"{FIELD_MAP[field]}={normalize_distribution(value)}\n"
    if field == "zdr":
        canonical = "true" if _normalize_bool(value) else "false"
        return f"{FIELD_MAP[field]}={canonical}\n"
    return f"{FIELD_MAP[field]}={value}\n"


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
                    lines[i] = _env_line(field_name, updates[field_name])
                    existing_keys.add(field_name)

        for field_name in FIELD_MAP:
            if field_name in updates and field_name not in existing_keys:
                lines.append(_env_line(field_name, updates[field_name]))

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
        if "distribution" in updates:
            # Applied in place: switching the mode must not rebuild the client, because a
            # rebuild would re-deal the bindings of every running conversation.
            _apply_live_distribution(updates["distribution"])
        if changed_client:
            old = _recreate_client(cfg)
            if old is not None:
                # The old client may still be serving streams the routers captured per request;
                # close its pool only once they finish so a panel save cannot cut a response short.
                old.schedule_close_when_idle()
                logger.info("admin.config.client_rebuilt", inflight=old.inflight)
        logger.info("admin.config.updated", fields=list(updates.keys()))
