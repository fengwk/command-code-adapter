import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cc_adapter.command_code.client import CommandCodeClient
from cc_adapter.core.errors import AdapterError, AuthenticationError, UpstreamError


@pytest.fixture
def sse_stream():
    def _stream(*args, **kwargs):
        class FakeResponse:
            is_error = False
            status_code = None

            async def aiter_lines(self):
                yield '{"type":"text-delta","text":"hi"}'
                yield "data: [DONE]"

            async def aread(self):
                return b""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        return FakeResponse()

    return _stream


@pytest.fixture
def error_response_402():
    class FakeResponse:
        is_error = True
        status_code = 402

        async def aread(self):
            return b'{"error":"insufficient_credits"}'

        async def aiter_lines(self):
            yield ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


@pytest.fixture
def error_response_429():
    class FakeResponse:
        is_error = True
        status_code = 429

        async def aread(self):
            return b'{"error":"rate_limited"}'

        async def aiter_lines(self):
            yield ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


@pytest.fixture
def error_response_500():
    class FakeResponse:
        is_error = True
        status_code = 500

        async def aread(self):
            return b'{"error":"internal_error"}'

        async def aiter_lines(self):
            yield ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


@pytest.fixture
def error_response_400_insufficient_credits():
    class FakeResponse:
        is_error = True
        status_code = 400

        async def aread(self):
            return b'{"success":false,"error":{"message":"You have insufficient credits to make this request."}}'

        async def aiter_lines(self):
            yield ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


class TestMultiKeyClient:
    @pytest.mark.asyncio
    async def test_single_key_behavior_unchanged(self, sse_stream):
        """Single-key mode: scheduler is None, behavior identical to original."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="single_key",
            api_keys=None,
        )
        assert client.scheduler is None

        with patch.object(httpx.AsyncClient, "stream", side_effect=sse_stream):
            events = [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert len(events) == 1
        assert events[0] == {"type": "text-delta", "text": "hi"}

    @pytest.mark.asyncio
    async def test_scheduler_created_with_multiple_keys(self):
        """When 2+ keys are provided, scheduler is created."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2", "key3"],
        )
        assert client.scheduler is not None
        assert client.scheduler._keys == ["key1", "key2", "key3"]

    @pytest.mark.asyncio
    async def test_scheduler_not_created_with_one_key(self):
        """When only 1 key in api_keys, scheduler stays None."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1"],
        )
        assert client.scheduler is None

    @pytest.mark.asyncio
    async def test_first_key_used_by_default(self, sse_stream):
        """Multi-key: first key with credits should be selected."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        captured_headers = []

        def capture_stream(method, url, json, headers, **kwargs):
            captured_headers.append(headers)
            return sse_stream()

        with patch.object(httpx.AsyncClient, "stream", side_effect=capture_stream):
            events = [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert len(events) == 1
        assert "Authorization" in captured_headers[0]
        assert "key1" in captured_headers[0]["Authorization"]

    @pytest.mark.asyncio
    async def test_402_retries_next_key(self, error_response_402, sse_stream):
        """402 on first key triggers retry with second key."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_response_402
            return sse_stream()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            events = [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert call_count == 2
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_429_retries_next_key(self, error_response_429, sse_stream):
        """429 on first key triggers retry with second key."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_response_429
            return sse_stream()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            events = [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert call_count == 2
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_non_retryable_errors_not_retried(self, error_response_500):
        """500 errors are not retried — raised immediately."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            return error_response_500

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            with pytest.raises(UpstreamError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_all_keys_exhausted_raises_last_error(self, error_response_402):
        """When all keys return 402, the last error is raised."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 0, "key2": 0}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            return error_response_402

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            with pytest.raises(AdapterError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_order_follows_key_priority(self, sse_stream):
        """Keys are tried in the order they appear in api_keys."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["keyA", "keyB", "keyC"],
        )
        client.scheduler._credits = {"keyA": 100, "keyB": 200, "keyC": 300}
        client.scheduler._last_fetch = time.monotonic()

        used_keys = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return sse_stream()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert used_keys == ["keyA"]

    @pytest.mark.asyncio
    async def test_400_insufficient_credits_retries_next_key(self, error_response_400_insufficient_credits, sse_stream):
        """400 with 'insufficient credits' triggers retry with second key."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_response_400_insufficient_credits
            return sse_stream()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            events = [e async for e in client.generate({"params": {"model": "test", "messages": []}})]

        assert call_count == 2
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_400_without_credits_phrase_not_retried(self):
        class Fake400:
            is_error = True
            status_code = 400

            async def aread(self):
                return b'{"error":"bad_request_other_reason"}'

            async def aiter_lines(self):
                yield ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 200}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            return Fake400()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            with pytest.raises(AdapterError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert call_count == 1


@pytest.fixture
def error_response_401():
    class FakeResponse:
        is_error = True
        status_code = 401

        async def aread(self):
            return b'{"error":"invalid api key"}'

        async def aiter_lines(self):
            yield ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


def _sse_ok():
    class FakeResponse:
        is_error = False
        status_code = None

        async def aiter_lines(self):
            yield '{"type":"text-delta","text":"hi"}'
            yield "data: [DONE]"

        async def aread(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeResponse()


class TestSessionAffinityRouting:
    """Session-sticky routing and key failover behaviour added by the scheduler."""

    def _client(self):
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 100}
        client.scheduler._last_fetch = time.monotonic()
        return client

    @pytest.mark.asyncio
    async def test_explicit_session_is_sticky_and_new_sessions_rotate(self):
        """One conversation keeps its key; a second conversation moves to the next."""
        client = self._client()
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            for session_id in ("s1", "s2", "s1", "s2"):
                async for _ in client.generate(
                    {"params": {"model": "test", "messages": []}},
                    {"x-claude-code-session-id": session_id},
                ):
                    pass

        # s1 binds key1 (cold round robin), s2 rotates to key2, both stay sticky.
        assert used_keys == ["key1", "key2", "key1", "key2"]

    @pytest.mark.asyncio
    async def test_no_session_requests_use_first_usable_key(self):
        """Requests without a session identity always go to the first usable key."""
        client = self._client()
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            # two explicit sessions move the round-robin cursor to key2 ...
            for session_id in ("s1", "s2"):
                async for _ in client.generate(
                    {"params": {"model": "test", "messages": []}},
                    {"x-claude-code-session-id": session_id},
                ):
                    pass
            # ... yet a session-less request still lands on the first usable key
            async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                pass

        assert used_keys == ["key1", "key2", "key1"]

    @pytest.mark.asyncio
    async def test_session_rebinds_after_key_failure(self, error_response_402):
        """A 402 unbinds the session and the retry rebinds it to the healthy key."""
        client = self._client()
        used_keys: list[str] = []
        fail_first = True

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal fail_first
            key = headers["Authorization"].split()[1]
            used_keys.append(key)
            if fail_first:
                fail_first = False
                return error_response_402
            return _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            for _ in range(2):
                async for _ in client.generate(
                    {"params": {"model": "test", "messages": []}},
                    {"x-claude-code-session-id": "s1"},
                ):
                    pass

        # first request: key1 402 -> key2; second request sticks to key2
        assert used_keys == ["key1", "key2", "key2"]

    @pytest.mark.asyncio
    async def test_401_disables_key_and_fails_over(self, error_response_401):
        """A 401 marks the key disabled and later requests skip it entirely."""
        client = self._client()
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            key = headers["Authorization"].split()[1]
            used_keys.append(key)
            return error_response_401 if key == "key1" else _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            for _ in range(2):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert used_keys == ["key1", "key2", "key2"]
        assert client.scheduler.key_state("key1")["state"] == "disabled"

    @pytest.mark.asyncio
    async def test_forged_cwd_matches_project_slug_header(self):
        """The forged workingDir basename equals the x-project-slug header value."""
        client = self._client()
        captured: list[tuple[dict, dict]] = []

        def mock_stream(method, url, json, headers, **kwargs):
            captured.append((json, headers))
            return _sse_ok()

        body = {"config": {"workingDir": "/app"}, "params": {"model": "test", "messages": []}}
        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            async for _ in client.generate(body):
                pass

        sent_body, sent_headers = captured[0]
        assert sent_headers["x-project-slug"] == sent_body["config"]["workingDir"].rsplit("/", 1)[-1]
        assert sent_body["config"]["recentCommits"]
