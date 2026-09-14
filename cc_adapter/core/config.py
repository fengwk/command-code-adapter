from __future__ import annotations

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cc_adapter.core.constants import (
    DEFAULT_DISTRIBUTION,
    KEY_COOLDOWN_BASE,
    KEY_COOLDOWN_MAX,
    KEY_CREDIT_COOLDOWN,
    normalize_distribution,
)
from cc_adapter.core.utils import normalize_api_keys


DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

ENV_FILE_ENV_VAR = "CC_ADAPTER_ENV_FILE"


def env_file_path() -> str:
    """Dotenv file read at startup and rewritten by the admin panel.

    Defaults to ``.env`` in the working directory. Point it at a mounted volume
    (e.g. ``/app/data/.env``) to persist panel-managed config: a single-file bind
    mount of ``/app/.env`` would break the atomic rewrite in ``update_env_file``.
    """
    return os.environ.get(ENV_FILE_ENV_VAR) or ".env"


def data_dir() -> Path:
    """Directory that holds runtime data files (token usage, model cache).

    They live next to the dotenv file so panel-written config and the artefacts
    that go with it share the mounted volume and survive a container recreate
    (``docker compose up --force-recreate``) instead of vanishing with the CWD.
    """
    return Path(env_file_path()).parent


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_ADAPTER_", env_file=env_file_path(), extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    log_format: str = "console"

    cc_api_key: str | list[str] = []
    cc_base_url: str = "https://api.commandcode.ai"
    admin_password: str = ""
    access_key: str = ""
    default_model: str = DEFAULT_MODEL

    http_max_connections: int = 200
    http_max_keepalive_connections: int = 50
    http2: bool = False

    # Key-scheduler cooldowns (seconds). Defaults mirror core/constants.py so the
    # values can be tuned from the environment without touching the code.
    key_cooldown_base: float = KEY_COOLDOWN_BASE
    key_cooldown_max: float = KEY_COOLDOWN_MAX
    key_credit_cooldown: float = KEY_CREDIT_COOLDOWN

    # First-sight distribution of new sessions over the key pool: "round-robin" or
    # "fill-first". Switchable at runtime from the admin panel; the value here is what a
    # client rebuild starts from.
    distribution: str = DEFAULT_DISTRIBUTION

    zdr: bool = True

    oss_primary_provider: str = ""

    @field_validator("cc_api_key", mode="before")
    @classmethod
    def coerce_api_key(cls, v):
        return normalize_api_keys(v)

    @field_validator("distribution", mode="before")
    @classmethod
    def coerce_distribution(cls, v):
        # Unknown/odd spellings fall back to the default instead of failing startup.
        return normalize_distribution(v)


def get_config_or_default() -> AppConfig:
    from cc_adapter.core.runtime import get_config

    cfg = get_config()
    return cfg if cfg else AppConfig()
