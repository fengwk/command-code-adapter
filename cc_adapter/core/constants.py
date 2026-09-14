from __future__ import annotations

import tomllib
from pathlib import Path

STREAMING_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

NPM_URL: str = "https://registry.npmjs.org/command-code/latest"
NPM_CACHE_TTL: int = 1800
NPM_ERROR_BACKOFF: int = 60

KEY_CREDITS_CACHE_TTL: int = 1800
KEY_CREDITS_ERROR_BACKOFF: int = 60

KEY_COOLDOWN_BASE: float = 60.0
KEY_COOLDOWN_MAX: float = 1800.0
# Flat cooldown for a key the upstream reported as out of credits: the balance
# cannot recover by itself, so short retries only waste upstream calls.
KEY_CREDIT_COOLDOWN: float = 1800.0
SESSION_AFFINITY_TTL: float = 3600.0
SESSION_AFFINITY_MAX_ENTRIES: int = 4096

# How long a rebuilt client may keep serving in-flight streams before its pool is closed anyway.
CLIENT_CLOSE_GRACE_SECONDS: float = 120.0


def _load_version() -> str:
    _pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    try:
        with open(_pyproject, "rb") as f:
            return tomllib.load(f)["tool"]["poetry"]["version"]
    except (FileNotFoundError, KeyError):
        return "0.7.0"


VERSION: str = _load_version()
