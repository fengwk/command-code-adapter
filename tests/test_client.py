import asyncio
import time

import httpx
import pytest
from cc_adapter.command_code.body import make_cc_body, make_config
from cc_adapter.command_code.client import CommandCodeClient, _parse_sse_line
from cc_adapter.core.errors import AuthenticationError, UpstreamError


@pytest.mark.asyncio
async def test_client_requires_api_key():
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="")
    with pytest.raises(AuthenticationError, match="CC_ADAPTER_CC_API_KEY is not configured"):
        async for _ in client.generate({"params": {"model": "test", "messages": []}}):
            pass


@pytest.mark.parametrize(
    "raw_line, expected_type",
    [
        ('{"type":"text-delta","text":"hi"}', "text-delta"),
        ('data: {"type":"text-delta","text":"hi"}', "text-delta"),
        ('data:{"type":"text-delta","text":"hi"}', "text-delta"),
        ('{"type":"tool-call","toolName":"read","input":{}}', "tool-call"),
        ('data: {"type":"finish","finishReason":"end_turn"}', "finish"),
    ],
)
def test_client_bare_json_and_sse_lines(raw_line, expected_type):
    """Both bare JSON lines and 'data: {...}' lines are parsed."""
    parsed = _parse_sse_line(raw_line)
    assert parsed is not None
    assert parsed["type"] == expected_type


def test_client_ignores_done_and_empty_lines():
    """'data: [DONE]' and empty lines are ignored."""
    lines = [
        "",
        "   ",
        "data: [DONE]",
        "data:[DONE]",
        '{"type":"text-delta","text":"hello"}',
        "",
        "data: [DONE]",
    ]
    events = [_parse_sse_line(raw) for raw in lines]

    assert [event["type"] for event in events if event is not None] == ["text-delta"]


def test_client_logs_invalid_lines():
    """Invalid lines are skipped silently (logged at debug level)."""
    lines = [
        "not json at all",
        'data: {"type":"valid"}',
        "{broken",
    ]

    results = [_parse_sse_line(raw) for raw in lines]
    # non-json lines return None; valid line returns parsed dict
    assert results[0] is None
    assert results[1] is not None
    assert results[2] is None


def test_client_rejects_non_object_json():
    """A valid JSON value that is not an event object is ignored."""
    assert _parse_sse_line('data: ["not", "an", "event"]') is None


@pytest.mark.asyncio
async def test_client_reuses_injected_http_client():
    injected = httpx.AsyncClient()
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test", http_client=injected)
    # An injected client is shared by every key and bypasses the per-key isolation.
    assert client._client("key-a") is injected
    assert client._client("key-b") is injected
    assert client._pools == {}
    await injected.aclose()


@pytest.mark.asyncio
async def test_client_keeps_one_pool_per_key():
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="key-a", api_keys=["key-a", "key-b"])
    pool = client._client("key-a")
    assert client._client("key-a") is pool  # one key always reuses its own pool
    assert client._client("key-b") is not pool
    assert set(client._pools) == {"key-a", "key-b"}
    assert client._http2 is False  # per-key pools stay HTTP/1.1 by default
    await client.aclose()


@pytest.mark.asyncio
async def test_client_connect_error_maps_to_upstream_error():
    from unittest.mock import patch

    with patch.object(httpx.AsyncClient, "stream") as mock_stream:
        mock_stream.side_effect = httpx.ConnectError("Connection refused")
        client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
        with pytest.raises(UpstreamError, match="Command Code API request failed: ConnectError"):
            async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                pass


@pytest.mark.asyncio
async def test_client_aclose_cleans_up_owned_client():
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
    http_client = client._client("test")
    assert not http_client.is_closed
    await client.aclose()
    assert http_client.is_closed


@pytest.mark.asyncio
async def test_client_aclose_closes_every_key_pool():
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="key-a", api_keys=["key-a", "key-b"])
    pools = [client._client("key-a"), client._client("key-b")]
    await client.aclose()
    assert [pool.is_closed for pool in pools] == [True, True]
    assert client._pools == {}


@pytest.mark.asyncio
async def test_client_aclose_does_not_close_injected_client():
    injected = httpx.AsyncClient()
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test", http_client=injected)
    await client.aclose()
    assert not injected.is_closed


def test_client_has_no_session_id_instance_attr():
    """Session id is no longer stored on the client: it is derived per request
    from (stable_flag, cmd_key) so multi-key and per-request behavior stay
    stateless and aligned with cmd CLI semantics.
    """
    client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
    assert not hasattr(client, "_session_id")


@pytest.mark.asyncio
async def test_generate_injects_derived_session_id_in_headers():
    """generate() injects x-session-id derived from the request and key."""
    from unittest.mock import patch, AsyncMock

    from cc_adapter.command_code.body import make_cc_body, make_config
    from cc_adapter.providers.shared.session_extractor import get_session_extractor

    async def fake_lines():
        yield '{"type":"finish","finishReason":"end_turn"}'

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.is_error = False
    mock_ctx.status_code = 200
    mock_ctx.aiter_lines = fake_lines

    body = make_cc_body(
        config=make_config(),
        params={
            "model": "test",
            "system": "you are helpful",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    with patch.object(httpx.AsyncClient, "stream", return_value=mock_ctx) as mock_stream:
        client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
        async for _ in client.generate(body):
            pass
        _, kwargs = mock_stream.call_args
        extractor = get_session_extractor()
        flag = extractor.extract({}, None, body).flag
        identity = extractor.derive(flag, "test")
        assert kwargs["headers"]["x-session-id"] == identity.session_id
        assert kwargs["headers"]["x-project-slug"] == identity.project_slug
        # The forged cwd agrees with the slug header and lives in the key's home.
        assert kwargs["json"]["config"]["workingDir"] == f"/home/{identity.home_login}/proj/{identity.project_slug}"


@pytest.mark.asyncio
async def test_generate_uses_provided_session_signal():
    """An explicit SessionSignal from the router wins over local extraction."""
    from unittest.mock import patch, AsyncMock

    from cc_adapter.command_code.body import make_cc_body, make_config
    from cc_adapter.providers.shared.session_extractor import SessionSignal, get_session_extractor

    async def fake_lines():
        yield '{"type":"finish","finishReason":"end_turn"}'

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.is_error = False
    mock_ctx.status_code = 200
    mock_ctx.aiter_lines = fake_lines

    body = make_cc_body(config=make_config(), params={"model": "test", "messages": []})
    signal = SessionSignal("claude:abc-123", True)
    with patch.object(httpx.AsyncClient, "stream", return_value=mock_ctx) as mock_stream:
        client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
        async for _ in client.generate(body, {}, session=signal):
            pass
        _, kwargs = mock_stream.call_args
        expected = get_session_extractor().derive(signal.flag, "test")
        assert kwargs["headers"]["x-session-id"] == expected.session_id


@pytest.mark.asyncio
async def test_generate_falls_back_to_header_extraction():
    """Without a signal, generate() extracts the session flag from headers."""
    from unittest.mock import patch, AsyncMock

    from cc_adapter.command_code.body import make_cc_body, make_config
    from cc_adapter.providers.shared.session_extractor import get_session_extractor

    async def fake_lines():
        yield '{"type":"finish","finishReason":"end_turn"}'

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.is_error = False
    mock_ctx.status_code = 200
    mock_ctx.aiter_lines = fake_lines

    body = make_cc_body(config=make_config(), params={"model": "test", "messages": []})
    with patch.object(httpx.AsyncClient, "stream", return_value=mock_ctx) as mock_stream:
        client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="test")
        async for _ in client.generate(body, {"X-Session-ID": "abc-123"}):
            pass
        _, kwargs = mock_stream.call_args
        expected = get_session_extractor().derive("header:abc-123", "test")
        assert kwargs["headers"]["x-session-id"] == expected.session_id


class TestClientEdgeCases:
    @pytest.mark.asyncio
    async def test_all_keys_exhausted_raises_last_error(self):
        """When every configured key returns a retryable error, the last
        error is propagated (not AuthenticationError)."""
        from unittest.mock import patch

        class Fake402:
            is_error = True
            status_code = 402

            async def aread(self):
                return b'{"error":"insufficient_credits"}'

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch.object(httpx.AsyncClient, "stream", return_value=Fake402()):
            client = CommandCodeClient(
                base_url="https://api.commandcode.ai",
                api_key="k1",
                api_keys=["k1", "k2", "k3"],
            )
            # Pretend all keys have plenty of credits so select_key keeps
            # cycling through them.
            client.scheduler._credits = {"k1": 100, "k2": 100, "k3": 100}
            client.scheduler._last_fetch = 1e18
            with pytest.raises(Exception) as exc:
                async for _ in client.generate({"params": {"model": "m", "messages": []}}):
                    pass
            # Should be the mapped 402 error, not AuthenticationError.
            assert "402" in str(exc.value) or "credits" in str(exc.value).lower()
            # Every retry used the pool of the key that served it.
            assert set(client._pools) == {"k1", "k2", "k3"}

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self):
        """httpx.TimeoutException is mapped to TimeoutError_."""
        from unittest.mock import patch

        from cc_adapter.core.errors import TimeoutError_

        with patch.object(httpx.AsyncClient, "stream") as mock_stream:
            mock_stream.side_effect = httpx.TimeoutException("timed out")
            client = CommandCodeClient(base_url="https://api.commandcode.ai", api_key="k1")
            with pytest.raises(TimeoutError_, match="timed out"):
                async for _ in client.generate({"params": {"model": "m", "messages": []}}):
                    pass

    def test_http2_disabled_when_h2_missing(self, monkeypatch):
        """If h2 is not installed, http2=True silently downgrades to HTTP/1.1."""
        import builtins

        from cc_adapter.command_code import client as client_module

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "h2":
                raise ImportError("simulated: h2 not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert client_module._make_http2_safe(True) is False
        assert client_module._make_http2_safe(False) is False

    def test_http2_enabled_when_h2_installed(self, monkeypatch):
        """If h2 is installed, http2=True is honored."""
        import sys
        import types

        from cc_adapter.command_code import client as client_module

        monkeypatch.setitem(sys.modules, "h2", types.ModuleType("h2"))
        assert client_module._make_http2_safe(True) is True
        assert client_module._make_http2_safe(False) is False

    @pytest.mark.asyncio
    async def test_no_available_key_raises_auth_error(self):
        """Defensive: if select_key returns None (e.g. empty key list),
        generate() raises AuthenticationError rather than looping forever.
        """
        from unittest.mock import patch

        client = CommandCodeClient(
            base_url="https://api.commandcode.ai",
            api_key="",
            api_keys=None,
        )
        # No scheduler, api_key empty -> select path returns "" -> auth error.
        with pytest.raises(Exception) as exc:
            async for _ in client.generate({"params": {"model": "m", "messages": []}}):
                pass
        assert "CC_ADAPTER_CC_API_KEY" in str(exc.value)


def _request_fields(head: bytes) -> dict[str, str]:
    """Lowercased header map of a raw HTTP request head (request line skipped)."""
    fields: dict[str, str] = {}
    for line in head.decode("latin-1").split("\r\n")[1:]:
        name, separator, value = line.partition(":")
        if separator:
            fields[name.strip().lower()] = value.strip()
    return fields


class _KeepAliveSSEUpstream:
    """Loopback HTTP/1.1 server that serves several SSE streams per connection.

    Every request is recorded as (Authorization token, client peer address), so a
    test can tell whether two requests travelled over the same TCP connection.
    """

    def __init__(self):
        self.port = 0
        self.requests: list[tuple[str, tuple]] = []
        self._server: asyncio.AbstractServer | None = None
        self._handlers: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        for handler in list(self._handlers):  # handlers parked on read() end only on cancel
            handler.cancel()
        if self._handlers:
            await asyncio.gather(*self._handlers, return_exceptions=True)
        await self._server.wait_closed()

    def tokens(self) -> list[str]:
        return [token for token, _ in self.requests]

    def ports(self, token: str) -> set[int]:
        """Client source ports the given key's requests arrived on."""
        return {peer[1] for recorded, peer in self.requests if recorded == token}

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handler = asyncio.current_task()
        self._handlers.add(handler)
        try:
            # Keep-alive loop: the connection stays open after each SSE stream so a
            # client pool can serve its next request over the same socket.
            while True:
                try:
                    head = await reader.readuntil(b"\r\n\r\n")
                except asyncio.IncompleteReadError:
                    return  # peer closed its idle connection
                fields = _request_fields(head)
                await reader.readexactly(int(fields.get("content-length", "0")))
                token = fields.get("authorization", "").removeprefix("Bearer ")
                self.requests.append((token, writer.get_extra_info("peername")))

                frame = b'data: {"type":"text-delta","text":"ok"}\n'
                head = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
                chunk = b"%X\r\n" % len(frame) + frame + b"\r\n"
                writer.write(head + chunk + b"0\r\n\r\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._handlers.discard(handler)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def _cc_body() -> dict:
    return make_cc_body(config=make_config(), params={"model": "test", "messages": []})


@pytest.mark.asyncio
async def test_keys_never_share_a_keep_alive_connection():
    """Each key owns its pool: no TCP connection carries two keys' headers.

    Two requests on one key must arrive on one connection (same client source
    port), while the other key's request must arrive on a different connection.
    That is only possible if every key pools its own sockets.
    """
    upstream = _KeepAliveSSEUpstream()
    await upstream.start()
    client = CommandCodeClient(
        base_url=f"http://127.0.0.1:{upstream.port}",
        api_key="key-aaaa",
        api_keys=["key-aaaa", "key-bbbb"],
    )
    client.scheduler._credits = {"key-aaaa": 100, "key-bbbb": 100}
    client.scheduler._last_fetch = time.monotonic()
    try:
        # s1 binds the first key, s2 the second one; the last request is s1 again.
        for session_id in ("s1", "s2", "s1"):
            async for _ in client.generate(_cc_body(), {"x-claude-code-session-id": session_id}):
                pass

        assert upstream.tokens() == ["key-aaaa", "key-bbbb", "key-aaaa"]
        assert len(upstream.ports("key-aaaa")) == 1  # keep-alive connection reused
        assert upstream.ports("key-bbbb") != upstream.ports("key-aaaa")  # never shared across keys
        assert len(client._pools) == 2
    finally:
        await client.aclose()
        await upstream.stop()
