from __future__ import annotations

import asyncio
import json
import structlog
from typing import AsyncGenerator, Any

import httpx

from cc_adapter.core.constants import (
    CLIENT_CLOSE_GRACE_SECONDS,
    KEY_COOLDOWN_BASE,
    KEY_COOLDOWN_MAX,
    KEY_CREDIT_COOLDOWN,
)
from cc_adapter.core.errors import AdapterError, map_upstream_error, AuthenticationError, TimeoutError_, UpstreamError
from cc_adapter.command_code.body import bind_workspace
from cc_adapter.command_code.headers import make_cc_headers
from cc_adapter.providers.shared.session_extractor import SessionSignal, get_session_extractor

logger = structlog.get_logger(__name__)


def _parse_sse_line(raw: str) -> dict[str, Any] | None:
    """Parse a single SSE line. Returns None for lines to skip."""
    line = raw.strip()
    if not line:
        return None
    if line.startswith("data:"):
        line = line[5:].lstrip()
    if line == "[DONE]":
        return None
    try:
        parsed = json.loads(line)
    except ValueError as e:
        preview = raw[:60]
        logger.debug("sse.parse_error", preview=preview, error=str(e))
        return None
    if not isinstance(parsed, dict):
        preview = raw[:60]
        logger.debug("sse.parse_error", preview=preview, error="not_a_json_object")
        return None
    et = parsed.get("type", "?")
    if et in ("start", "finish", "provider-metadata"):
        logger.info("sse.event_detail", event_type=et, body=parsed)
    logger.debug("sse.raw_event", event_type=et)
    return parsed


_INSUFFICIENT_CREDITS_PHRASES = (
    "insufficient credits",
    "insufficient_credits",
)

_ZDR_ERROR_PHRASES = (
    "zero-data-retention",
    "disable cmd_zdr",
    "cmd_zdr_no_providers",
    "cmd_zdr_no-providers",
    "cmd zdr no providers",
)


def _is_retryable_error(status_code: int, body_text: str) -> bool:
    if status_code in (402, 429):
        return True
    if status_code == 400:
        lowered = body_text.lower()
        return any(phrase in lowered for phrase in _INSUFFICIENT_CREDITS_PHRASES)
    return False


def _is_key_error(status_code: int) -> bool:
    """An upstream 401/403 means this CC key is invalid, not the request."""
    return status_code in (401, 403)


def _is_zdr_error(status_code: int, body_text: str) -> bool:
    if status_code != 400:
        return False
    lowered = body_text.lower()
    return any(phrase in lowered for phrase in _ZDR_ERROR_PHRASES)


def _make_http2_safe(http2: bool) -> bool:
    if not http2:
        return False
    try:
        import h2  # noqa: F401
    except ImportError:
        logger.warning("http2=True configured but 'h2' package is not installed. Falling back to HTTP/1.1.")
        return False
    return http2


class CommandCodeClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
        max_connections: int = 200,
        max_keepalive_connections: int = 50,
        http2: bool = False,
        api_keys: list[str] | None = None,
        key_cooldown_base: float = KEY_COOLDOWN_BASE,
        key_cooldown_max: float = KEY_COOLDOWN_MAX,
        key_credit_cooldown: float = KEY_CREDIT_COOLDOWN,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._max_connections = max_connections
        self._max_keepalive_connections = max_keepalive_connections
        self._http2 = _make_http2_safe(http2)
        # Streams currently being consumed: a retiring client keeps its pool open for them.
        self._inflight = 0
        self._idle = asyncio.Event()
        self._close_tasks: set[asyncio.Task[None]] = set()

        if api_keys and len(api_keys) > 1:
            from cc_adapter.core.key_scheduler import KeyScheduler

            self.scheduler: KeyScheduler | None = KeyScheduler(
                api_keys,
                self.base_url,
                cooldown_base=key_cooldown_base,
                cooldown_max=key_cooldown_max,
                credit_cooldown=key_credit_cooldown,
            )
        else:
            self.scheduler = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(
                    max_connections=self._max_connections,
                    max_keepalive_connections=self._max_keepalive_connections,
                ),
                http2=self._http2,
            )
            self._owns_http_client = True
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()

    @property
    def inflight(self) -> int:
        """Number of `generate()` streams currently being consumed."""
        return self._inflight

    def schedule_close_when_idle(self, *, timeout: float = CLIENT_CLOSE_GRACE_SECONDS) -> asyncio.Task[None]:
        """Close the pool once every in-flight stream finished, or after ``timeout`` seconds.

        The admin panel rebuilds the client on every save (key add/remove, base URL change),
        and a stream that is being read at that moment still holds this client: closing the
        pool underneath it surfaces as a ReadError mid-response. Retire it in the background
        instead. The returned task is awaited by tests; the set keeps it alive until it ends.
        """
        task = asyncio.get_running_loop().create_task(self._close_when_idle(timeout))
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)
        return task

    async def _close_when_idle(self, timeout: float) -> None:
        if self._inflight:
            try:
                await asyncio.wait_for(self._idle.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("client.close_timeout", timeout=timeout, inflight=self._inflight)
        await self.aclose()

    async def generate(
        self,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
        session: SessionSignal | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield the parsed CC SSE events of one request.

        Counting the stream as in-flight keeps a retiring client usable for it: the panel
        closes the old pool via `schedule_close_when_idle()` after a client rebuild.
        """
        self._inflight += 1
        self._idle.clear()
        stream = self._stream(body, extra_headers, session)
        try:
            async for event in stream:
                yield event
        finally:
            self._inflight -= 1
            if not self._inflight:
                self._idle.set()
            await stream.aclose()

    async def _stream(
        self,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
        session: SessionSignal | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        tried_keys: set[str] = set()
        last_error: Exception | None = None
        zdr_downgraded: bool = False
        extractor = get_session_extractor()
        # extra_headers may contain client-authored values (X-Session-ID etc.)
        # for session extraction but must not leak to the CC upstream. Routers
        # pass an already-resolved signal; when they do not, fall back to
        # extracting from the headers and the CC body alone.
        signal = session or extractor.extract(extra_headers, None, body)

        while True:
            if self.scheduler is not None:
                # Explicit client session identities stick to their key (round robin
                # for new ones); requests without one go to the first usable key.
                key = await self.scheduler.select(signal.flag, explicit=signal.explicit, exclude=tried_keys)
            else:
                key = self.api_key

            if not key:
                if last_error is not None:
                    raise last_error
                raise self._no_key_error()

            if key in tried_keys:
                if last_error is not None:
                    raise last_error
                raise self._no_key_error()

            tried_keys.add(key)

            session_id, project_slug = extractor.derive(signal.flag, key)
            # Keep the forged cwd consistent with the slug sent as x-project-slug.
            config = body.get("config")
            if isinstance(config, dict):
                bind_workspace(config, project_slug)

            headers = make_cc_headers(key)
            if zdr_downgraded:
                headers.pop("x-cmd-zdr", None)
            headers["x-session-id"] = session_id
            headers["x-project-slug"] = project_slug

            url = f"{self.base_url}/alpha/generate"

            client = self._client()
            try:
                async with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.is_error:
                        error_body = await response.aread()
                        text = error_body.decode() if error_body else response.reason_phrase or "Unknown error"
                        logger.warning("upstream.error", status_code=response.status_code, error_type="cc_api_error")
                        mapped = map_upstream_error(response.status_code, text)

                        if _is_retryable_error(response.status_code, text) or _is_key_error(response.status_code):
                            last_error = mapped
                            self._report_key_failure(key, response.status_code, text, signal)
                            continue

                        if _is_zdr_error(response.status_code, text) and not zdr_downgraded:
                            zdr_downgraded = True
                            tried_keys.discard(key)
                            logger.info("zdr.downgrade", key_last4=key[-4:])
                            continue

                        raise mapped

                    async for line in response.aiter_lines():
                        parsed = _parse_sse_line(line)
                        if parsed is not None:
                            yield parsed
                    if self.scheduler is not None:
                        self.scheduler.report(key, ok=True, session_flag=signal.flag)
                    return

            except httpx.TimeoutException:
                logger.warning("upstream.error", error_type="timeout", url=url)
                raise TimeoutError_("Command Code API request timed out")
            except httpx.RequestError as e:
                logger.warning("upstream.error", error_type=e.__class__.__name__, url=url)
                raise UpstreamError(f"Command Code API request failed: {e.__class__.__name__}")

    def _report_key_failure(self, key: str, status_code: int, body_text: str, signal: SessionSignal) -> None:
        """Feed a key-level upstream failure back to the scheduler."""
        if self.scheduler is None:
            return
        reason: str | None = None
        if status_code == 429:
            reason = "rate_limited"
        elif status_code == 400 and any(p in body_text.lower() for p in _INSUFFICIENT_CREDITS_PHRASES):
            reason = "insufficient_credits"
        self.scheduler.report(
            key,
            ok=False,
            status=status_code,
            reason=reason,
            session_flag=signal.flag,
            detail=body_text,
        )

    def _no_key_error(self) -> AdapterError:
        """Error for a request the scheduler cannot route: report the last failure."""
        if self.scheduler is None:
            return AuthenticationError("CC_ADAPTER_CC_API_KEY is not configured")
        message = self.scheduler.unavailable_summary()
        last = self.scheduler.last_failure()
        if last and last.get("detail"):
            message += f"; last upstream error ({last['status']}): {last['detail']}"
        if last and last.get("status"):
            return map_upstream_error(int(last["status"]), message)
        return AdapterError(message, status_code=503, original_status=503)
