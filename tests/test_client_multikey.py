import asyncio
import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cc_adapter.command_code.client import CommandCodeClient
from cc_adapter.core.constants import KEY_MAX_CONCURRENT_STREAMS
from cc_adapter.core.errors import AdapterError, AuthenticationError, UpstreamError
from cc_adapter.providers.shared.session_extractor import SessionSignal


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
    async def test_keys_without_credits_fail_fast_without_upstream_call(self, error_response_402):
        """Known-broke keys are never tried: the error explains every key's state."""
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
            with pytest.raises(AdapterError) as excinfo:
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert call_count == 0
        message = str(excinfo.value)
        assert "no usable CC key" in message
        assert "out of credits" in message

    @pytest.mark.asyncio
    async def test_all_keys_parked_reports_the_last_upstream_failure(self, error_response_400_insufficient_credits):
        """Once every key is parked the next request fails with the last upstream error."""
        client = CommandCodeClient(
            base_url="https://api.example.com",
            api_key="key1",
            api_keys=["key1", "key2"],
        )
        client.scheduler._credits = {"key1": 100, "key2": 100}
        client.scheduler._last_fetch = time.monotonic()

        call_count = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal call_count
            call_count += 1
            return error_response_400_insufficient_credits

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            with pytest.raises(AdapterError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass
            assert call_count == 2  # both keys parked on the first request
            assert client.scheduler.last_failure()["status"] == 400

            with pytest.raises(AdapterError) as excinfo:
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert call_count == 2  # fail-fast: no further upstream call
        message = str(excinfo.value)
        assert "insufficient credits" in message
        assert "****key1" in message or "****key2" in message
        assert client.scheduler.last_failure()["detail"].startswith('{"success":false')

    @pytest.mark.asyncio
    async def test_cooldowns_come_from_the_config(self, error_response_400_insufficient_credits):
        """CC_ADAPTER_KEY_CREDIT_COOLDOWN reaches the scheduler through create_client()."""
        from cc_adapter.core.config import AppConfig
        from cc_adapter.core.runtime import create_client

        cfg = AppConfig(cc_api_key=["key1", "key2"], key_credit_cooldown=90)
        client = create_client(cfg)
        client.scheduler._credits = {"key1": 100, "key2": 100}
        client.scheduler._last_fetch = time.monotonic()

        with patch.object(
            httpx.AsyncClient, "stream", side_effect=lambda *a, **kw: error_response_400_insufficient_credits
        ):
            with pytest.raises(AdapterError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        state = client.scheduler.key_state("key1")
        assert state["reason"] == "insufficient_credits"
        assert state["until"] - time.monotonic() == pytest.approx(90, abs=2.0)

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
    async def test_round_robin_rotates_requests_without_a_session_identity_too(self):
        """An unidentified request is a new conversation as well, so the mode rotates it.

        A body the adapter cannot identify gets a content anchor: a *different* body is
        a new conversation and takes the next ring slot, while repeating one of the
        bodies is the same conversation again and stays on the key it was bound to.
        """
        client = self._client()
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return _sse_ok()

        def body(text: str) -> dict:
            return {"params": {"model": "test", "messages": [{"role": "user", "content": text}]}}

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            # three distinct conversations, none of them carrying a client identity ...
            for text in ("first", "second", "third"):
                async for _ in client.generate(body(text)):
                    pass
            assert used_keys == ["key1", "key2", "key1"]  # ... rotate over the ring
            # ... and the conversation that already ran comes back to its own key
            async for _ in client.generate(body("second")):
                pass

        assert used_keys == ["key1", "key2", "key1", "key2"]

    @pytest.mark.asyncio
    async def test_fill_first_keeps_new_sessions_on_the_head_key(self):
        """CC_ADAPTER_DISTRIBUTION reaches the scheduler through create_client()."""
        from cc_adapter.core.config import AppConfig
        from cc_adapter.core.runtime import create_client

        cfg = AppConfig(cc_api_key=["key1", "key2"], distribution="fill-first")
        client = create_client(cfg)
        assert client.scheduler.distribution == "fill-first"
        client.scheduler._credits = {"key1": 100, "key2": 100}
        client.scheduler._last_fetch = time.monotonic()
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            for session_id in ("s1", "s2"):  # two *different* conversations
                async for _ in client.generate(
                    {"params": {"model": "test", "messages": []}},
                    {"x-claude-code-session-id": session_id},
                ):
                    pass

        assert used_keys == ["key1", "key1"]  # both start on the head account
        await client.aclose()

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


def _blocking_stream(gate: asyncio.Event, started: asyncio.Event | None = None, *, on_start=None):
    """`httpx.AsyncClient.stream` stand-in that holds the response open until `gate` is set."""

    class BlockingResponse:
        is_error = False
        status_code = None

        async def aiter_lines(self):
            if started is not None:
                started.set()
            if on_start is not None:
                on_start()
            await gate.wait()
            yield '{"type":"finish","finishReason":"end_turn"}'

        async def aread(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    def _stream(method, url, json, headers, **kwargs):
        return BlockingResponse()

    return _stream


async def _drain(client, body: dict, headers: dict | None = None, session=None) -> None:
    async for _ in client.generate(body, headers, session):
        pass


class TestPerKeyConcurrency:
    """In-flight streams are counted per key, and the scheduler caps one account's load."""

    def _client(self, keys: list[str] | None = None):
        keys = keys or ["key1", "key2"]
        client = CommandCodeClient(base_url="https://api.example.com", api_key=keys[0], api_keys=keys)
        client.scheduler._credits = {key: 100 for key in keys}
        client.scheduler._last_fetch = time.monotonic()
        return client

    @pytest.mark.asyncio
    async def test_key_load_counts_the_stream_that_is_being_consumed(self):
        client = self._client()
        gate, started = asyncio.Event(), asyncio.Event()

        with patch.object(httpx.AsyncClient, "stream", side_effect=_blocking_stream(gate, started)):
            task = asyncio.create_task(_drain(client, {"params": {"model": "test", "messages": []}}))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert client.key_load("key1") == 1
            assert client.key_load("key2") == 0
            gate.set()
            await asyncio.wait_for(task, timeout=5)

        assert client.key_load("key1") == 0
        assert client.inflight == 0

    @pytest.mark.asyncio
    async def test_key_load_is_released_when_a_stream_fails_mid_way(self):
        client = self._client()

        class ExplodingResponse:
            is_error = False
            status_code = None

            async def aiter_lines(self):
                yield '{"type":"text-delta","text":"hi"}'
                raise RuntimeError("stream broke")

            async def aread(self):
                return b""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch.object(httpx.AsyncClient, "stream", side_effect=lambda *a, **kw: ExplodingResponse()):
            with pytest.raises(RuntimeError):
                async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                    pass

        assert client.key_load("key1") == 0
        assert client.inflight == 0

    @pytest.mark.asyncio
    async def test_a_retry_charges_only_the_key_it_moved_to(self, error_response_402):
        client = self._client()
        gate, started = asyncio.Event(), asyncio.Event()
        calls = 0

        def mock_stream(method, url, json, headers, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return error_response_402
            return _blocking_stream(gate, started)(method, url, json, headers, **kwargs)

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            task = asyncio.create_task(_drain(client, {"params": {"model": "test", "messages": []}}))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert client.key_load("key1") == 0  # the failed attempt released its key
            assert client.key_load("key2") == 1
            gate.set()
            await asyncio.wait_for(task, timeout=5)

        assert client.key_load("key2") == 0

    @pytest.mark.asyncio
    async def test_a_key_at_the_cap_hands_new_streams_to_another_key(self):
        """KEY_MAX_CONCURRENT_STREAMS in action: a *new* conversation leaves a full key."""
        client = self._client()
        gate = asyncio.Event()
        all_busy = asyncio.Event()
        overflow_routed = asyncio.Event()
        started = 0
        used_keys: list[str] = []

        def on_start():
            nonlocal started
            started += 1
            if started == KEY_MAX_CONCURRENT_STREAMS:
                all_busy.set()

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            if len(used_keys) > KEY_MAX_CONCURRENT_STREAMS:
                overflow_routed.set()
            return _blocking_stream(gate, on_start=on_start)(method, url, json, headers, **kwargs)

        body = {"params": {"model": "test", "messages": []}}
        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            tasks = [
                asyncio.create_task(_drain(client, body, session=SessionSignal(flag="msg:busy", explicit=False)))
                for _ in range(KEY_MAX_CONCURRENT_STREAMS)
            ]
            await asyncio.wait_for(all_busy.wait(), timeout=5)
            assert client.key_load("key1") == KEY_MAX_CONCURRENT_STREAMS
            # the saturated key is skipped: the next *new* conversation goes to the other account
            overflow = asyncio.create_task(
                _drain(client, body, session=SessionSignal(flag="msg:overflow", explicit=False))
            )
            await asyncio.wait_for(overflow_routed.wait(), timeout=5)
            assert used_keys == ["key1"] * KEY_MAX_CONCURRENT_STREAMS + ["key2"]
            gate.set()
            await asyncio.wait_for(asyncio.gather(*tasks, overflow), timeout=5)

        assert client.key_load("key1") == 0
        assert client.key_load("key2") == 0

    @pytest.mark.asyncio
    async def test_every_key_saturated_still_serves_the_request(self):
        """The cap must never turn into a failure: the least loaded key takes one more."""
        client = self._client(keys=["key1", "key2"])
        # Both keys are above the cap already (as if four long streams each were running).
        client._key_inflight = {"key1": KEY_MAX_CONCURRENT_STREAMS + 3, "key2": KEY_MAX_CONCURRENT_STREAMS}
        used_keys: list[str] = []

        def mock_stream(method, url, json, headers, **kwargs):
            used_keys.append(headers["Authorization"].split()[1])
            return _sse_ok()

        with patch.object(httpx.AsyncClient, "stream", side_effect=mock_stream):
            async for _ in client.generate({"params": {"model": "test", "messages": []}}):
                pass

        assert used_keys == ["key2"]  # least loaded, even though both are at the cap
