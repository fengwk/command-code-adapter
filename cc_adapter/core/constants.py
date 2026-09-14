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

# Upper bound (seconds) of the per-key delay applied to *background* balance
# probes. Every key is refreshed on the same cadence; firing those probes in the
# same instant from one IP is a multi-account signature, so the arrivals are
# spread over this window instead (deterministically per key).
KEY_CREDITS_PROBE_SPREAD: float = 240.0

KEY_COOLDOWN_BASE: float = 60.0
KEY_COOLDOWN_MAX: float = 1800.0
# Flat cooldown for a key the upstream reported as out of credits: the balance
# cannot recover by itself, so short retries only waste upstream calls.
KEY_CREDIT_COOLDOWN: float = 1800.0
# Flat cooldown for a bare 403 (policy/region/abuse denial). Such a denial is not a
# revoked key, so it must not disable the key forever - but retrying it right away
# is just as wrong, hence one long window instead.
KEY_FORBIDDEN_COOLDOWN: float = 7200.0
# Upper bound of concurrent streams one upstream account may serve. One account that
# answers an unbounded number of simultaneous requests looks like a relay, not like a
# developer's CLI; the scheduler spreads the excess over the other usable keys.
KEY_MAX_CONCURRENT_STREAMS: int = 4
SESSION_AFFINITY_TTL: float = 3600.0
SESSION_AFFINITY_MAX_ENTRIES: int = 4096

# One upstream account is one forged machine, and a real dev machine only ever
# works in a handful of repositories. Every key therefore derives its own small
# palette of project slugs (a pure function of the key, so restarts, rebuilds and
# rejoins never move a session to another project), and keeps recycling the same
# few projects instead of reporting a brand-new one per session.
PROJECT_SLUGS_PER_ACCOUNT_MIN: int = 4
PROJECT_SLUGS_PER_ACCOUNT_MAX: int = 8

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

# The npm registry fetches are not the disguised upstream, but the registry should
# still not see httpx's own defaults (a "python-httpx/..." user agent): these four
# keys replace exactly the headers httpx would otherwise prepend to a request that
# carries no CC header set.
NPM_FETCH_HEADERS: dict[str, str] = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate",
    "connection": "keep-alive",
    "user-agent": f"cc-adapter/{VERSION}",
}
