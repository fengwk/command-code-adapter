from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger(__name__)

from cc_adapter.core.config import data_dir
from cc_adapter.core.constants import NPM_URL, NPM_CACHE_TTL, NPM_ERROR_BACKOFF, NPM_FETCH_HEADERS

DEFAULT_VERSION = os.environ.get("CC_ADAPTER_DEFAULT_VERSION", "1.54.0")

DEFAULT_VERSION_FILE = "cli_version.json"


class VersionChecker:
    def __init__(self, version_path: str | Path | None = None) -> None:
        self._path = Path(version_path) if version_path else data_dir() / DEFAULT_VERSION_FILE
        # A restart must not fall back to the built-in constant once a fetch has
        # succeeded: the last persisted version is read back before any fetch runs.
        self._cached_version: str = self._load_persisted_version() or DEFAULT_VERSION
        self._last_fetch_time: float | None = None
        self._last_error: str | None = None
        self._fetch_task: asyncio.Task[None] | None = None

    def get_version(self) -> str:
        if self._is_stale():
            try:
                loop = asyncio.get_running_loop()
                if not self._fetch_task or self._fetch_task.done():
                    self._fetch_task = loop.create_task(self._fetch_and_update())
            except RuntimeError:
                logger.debug("version.no_running_loop")
        return self._cached_version

    async def refresh(self) -> None:
        await self._fetch_and_update()

    @property
    def last_fetch_time(self) -> float | None:
        return self._last_fetch_time

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _is_stale(self) -> bool:
        if self._last_fetch_time is None:
            return True
        ttl = NPM_ERROR_BACKOFF if self._last_error else NPM_CACHE_TTL
        return time.monotonic() - self._last_fetch_time > ttl

    def _load_persisted_version(self) -> str | None:
        """Last successfully fetched version, or None when there is nothing usable on disk."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            version = data.get("version") if isinstance(data, dict) else None
            if isinstance(version, str) and version:
                logger.info("version.persisted_loaded", path=str(self._path), version=version)
                return version
            logger.warning("version.persisted_invalid", path=str(self._path))
        except Exception as e:
            logger.warning("version.persisted_read_failed", path=str(self._path), error=str(e))
        return None

    def _persist_version(self, version: str) -> None:
        """Store the fetched version; a broken data directory only warns, it never
        breaks the fetch path (the caller keeps the value in memory)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Keep the temp file next to the target: the data directory may live on a mounted
            # volume, where renaming from /tmp would fail with EXDEV (cross-device link).
            fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="cli_version_", dir=str(self._path.parent))
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump({"version": version}, f)
                os.replace(tmp_path, str(self._path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.warning("version.persist_failed", path=str(self._path), error=str(e))

    async def _fetch_and_update(self) -> None:
        self._last_error = None
        try:
            # NPM_FETCH_HEADERS replaces httpx's own defaults (a "python-httpx/..." user agent).
            async with httpx.AsyncClient(timeout=5.0, headers=NPM_FETCH_HEADERS) as client:
                response = await client.get(NPM_URL)
                response.raise_for_status()
                data = response.json()
                version = data.get("version", "")
                if version:
                    logger.info("version.updated", old=self._cached_version, new=version)
                    self._cached_version = version
                    self._persist_version(version)
                else:
                    logger.warning("version.missing_field", url=NPM_URL)
                self._last_fetch_time = time.monotonic()
        except Exception as e:
            self._last_error = str(e)
            self._last_fetch_time = time.monotonic()
            logger.warning("version.fetch_failed", error=str(e), url=NPM_URL)
