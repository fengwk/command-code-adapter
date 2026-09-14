from __future__ import annotations

import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    zdr: bool = True

    oss_primary_provider: str = ""

    @field_validator("cc_api_key", mode="before")
    @classmethod
    def coerce_api_key(cls, v):
        return normalize_api_keys(v)


def get_config_or_default() -> AppConfig:
    from cc_adapter.core.runtime import get_config

    cfg = get_config()
    return cfg if cfg else AppConfig()
