"""Lifecycle of a client the admin panel rebuilds while requests are in flight.

`ConfigManager.apply_config_update()` replaces the runtime client on every save of a
client field and retires the old one via `schedule_close_when_idle()`. Streams that the
routers captured before the rebuild keep reading from the old pool, so it may only be
closed after the last stream ends. These tests drive a real loopback SSE upstream, so
the whole HTTP path (httpx pool included) is exercised without network access.
"""

import asyncio
import time

import httpx
import pytest
import pytest_asyncio

from cc_adapter.admin.config_manager import ConfigManager
from cc_adapter.command_code.body import make_cc_body, make_config
from cc_adapter.command_code.client import CommandCodeClient
from cc_adapter.core import runtime
from cc_adapter.core.config import AppConfig
from cc_adapter.core.errors import AdapterError

FRAME_COUNT = 6


def _frame(index: int) -> bytes:
    return f'data: {{"type":"text-delta","text":"f{index}"}}\n'.encode()


async def _aclose_quietly(gen) -> None:
    """Close a stream generator; a pool that was already retired may surface AdapterError."""
    try:
        await gen.aclose()
    except AdapterError:
        pass


class _FakeSSEUpstream:
    """Loopback chunked-SSE server; the test decides when each frame is sent."""

    def __init__(self):
        self.port = 0
        self.aborted = False
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        # Python 3.12.1+ wait_closed() also waits for live connections, so unblock the handlers
        # parked on the queue first (an extra sentinel is harmless).
        for _ in range(len(self._connections) + 1):
            self._queue.put_nowait(None)
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
        await self._server.wait_closed()

    async def push(self, item: bytes | None) -> None:
        await self._queue.put(item)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._connections.add(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
            await writer.drain()
            while True:
                item = await self._queue.get()
                if item is None:
                    writer.write(b"0\r\n\r\n")
                    await writer.drain()
                    break
                writer.write(b"%X\r\n" % len(item) + item + b"\r\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self.aborted = True
        finally:
            self._connections.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass  # the peer may already have torn the connection down during teardown


@pytest_asyncio.fixture
async def upstream():
    server = _FakeSSEUpstream()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def _client(upstream: _FakeSSEUpstream) -> CommandCodeClient:
    return CommandCodeClient(base_url=f"http://127.0.0.1:{upstream.port}", api_key="key")


def _single_pool(client: CommandCodeClient) -> httpx.AsyncClient:
    """The one per-key pool a single-key client created on its first request."""
    (pool,) = client._pools.values()
    return pool


def _body() -> dict:
    return make_cc_body(config=make_config(), params={"model": "test", "messages": []})


async def _read_frames(upstream: _FakeSSEUpstream, gen, start: int, stop: int) -> list[dict]:
    frames = []
    for index in range(start, stop):
        await upstream.push(_frame(index))
        frames.append(await anext(gen))
    return frames


async def _end_stream(upstream: _FakeSSEUpstream, gen) -> None:
    await upstream.push(None)
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


@pytest.mark.asyncio
async def test_stream_survives_scheduled_close_mid_stream(upstream):
    # Intent: a close scheduled mid-stream must wait for the stream, then close the pool.
    client = _client(upstream)
    gen = client.generate(_body())
    close_task: asyncio.Task | None = None
    try:
        received = []
        for index in range(FRAME_COUNT):
            await upstream.push(_frame(index))
            received.append(await anext(gen))
            if index == 1:
                # Two of six frames consumed: schedule the panel-style retirement on a live stream.
                assert client.inflight == 1
                pool = _single_pool(client)
                close_task = client.schedule_close_when_idle()
                assert pool.is_closed is False

        assert [event["text"] for event in received] == [f"f{index}" for index in range(FRAME_COUNT)]
        assert upstream.aborted is False  # nothing cut the response short
        assert client.inflight == 1

        await _end_stream(upstream, gen)
        assert client.inflight == 0  # the finished stream released its slot

        assert close_task is not None
        await asyncio.wait_for(close_task, timeout=5)
        assert pool.is_closed is True  # the pool closes, just later
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_idle_client_closes_promptly(upstream):
    # Intent: with no stream in flight, the default grace window must not delay the close.
    client = _client(upstream)
    gen = client.generate(_body())
    try:
        received = await _read_frames(upstream, gen, 0, 1)
        assert received[0]["text"] == "f0"
        await _end_stream(upstream, gen)
        assert client.inflight == 0
        pool = _single_pool(client)
        assert pool.is_closed is False

        task = client.schedule_close_when_idle()
        await asyncio.wait_for(task, timeout=2)
        assert pool.is_closed is True
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_scheduled_close_closes_every_key_pool(upstream):
    # Intent: retirement closes each key's pool, not only the one that served the stream.
    client = _client(upstream)
    gen = client.generate(_body())
    try:
        await _read_frames(upstream, gen, 0, 1)
        # In production a second pool exists because another key served a request;
        # materialise it directly so the close path covers more than one pool.
        client._client("second-key")
        pools = dict(client._pools)
        assert len(pools) == 2

        await _end_stream(upstream, gen)
        task = client.schedule_close_when_idle()
        await asyncio.wait_for(task, timeout=2)

        assert [pool.is_closed for pool in pools.values()] == [True, True]
        assert client._pools == {}
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_stream_remains_open_indefinitely_while_active_and_closes_on_completion(upstream):
    # Intent: a retiring client must never force-close an active stream; the pool remains open until completion.
    client = _client(upstream)
    gen = client.generate(_body())
    try:
        received = await _read_frames(upstream, gen, 0, 1)
        assert received[0]["text"] == "f0"
        assert client.inflight == 1
        pool = _single_pool(client)

        task = client.schedule_close_when_idle()
        # Even after a delay, the retirement task must not close the pool while the stream is running.
        await asyncio.sleep(0.1)
        assert task.done() is False
        assert pool.is_closed is False
        assert client.inflight == 1

        # The stream continues to consume frames normally through the open pool.
        received += await _read_frames(upstream, gen, 1, FRAME_COUNT)
        assert [event["text"] for event in received] == [f"f{index}" for index in range(FRAME_COUNT)]
        assert pool.is_closed is False

        await _end_stream(upstream, gen)
        assert client.inflight == 0

        # Now that the stream is finished, the pool closes promptly.
        await asyncio.wait_for(task, timeout=5)
        assert pool.is_closed is True
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_apply_config_update_keeps_inflight_stream(upstream):
    # Intent: the panel rebuild path must keep the old pool alive for a stream captured before the save.
    cfg = AppConfig(cc_base_url=f"http://127.0.0.1:{upstream.port}", cc_api_key=["test-key-aaaa1111"])
    client = CommandCodeClient(base_url=cfg.cc_base_url, api_key=cfg.cc_api_key[0])
    gen = client.generate(_body())
    previous = (runtime.get_config(), runtime.get_client())
    runtime.init(cfg, client)
    rebuilt: CommandCodeClient | None = None
    try:
        received = await _read_frames(upstream, gen, 0, 2)
        assert client.inflight == 1
        pool = _single_pool(client)

        await ConfigManager.apply_config_update({"cc_base_url": cfg.cc_base_url})
        rebuilt = runtime.get_client()
        assert rebuilt is not None and rebuilt is not client
        close_tasks = list(client._close_tasks)
        assert len(close_tasks) == 1  # the panel scheduled the retirement, it did not close the pool
        assert pool.is_closed is False

        received += await _read_frames(upstream, gen, 2, FRAME_COUNT)
        assert [event["text"] for event in received] == [f"f{index}" for index in range(FRAME_COUNT)]

        await _end_stream(upstream, gen)
        assert client.inflight == 0

        await asyncio.wait_for(asyncio.gather(*close_tasks), timeout=5)
        assert pool.is_closed is True
    finally:
        runtime.init(*previous)  # restore the global runtime state for other tests
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()
        if rebuilt is not None:
            await rebuilt.aclose()


@pytest.mark.asyncio
async def test_immediate_aclose_mid_stream_truncates(upstream):
    """Negative control for `test_stream_survives_scheduled_close_mid_stream`.

    The old panel behaviour (`await client.aclose()` mid-stream) is the defect itself:
    the pool vanishes under the live stream, so an AdapterError surfaces or frames are
    lost. This is the evidence that the guarded test above would catch a regression.
    """
    client = _client(upstream)
    gen = client.generate(_body())
    received: list[dict] = []
    error: AdapterError | None = None
    try:
        for index in range(FRAME_COUNT):
            await upstream.push(_frame(index))
            received.append(await anext(gen))
            if index == 1:
                await client.aclose()  # immediate close: the pool goes away under the live stream
    except AdapterError as exc:
        error = exc
    finally:
        await upstream.push(None)
        await _aclose_quietly(gen)

    # Whatever the failure mode, the stream cannot complete: an error surfaced or frames were lost.
    assert [event["text"] for event in received] == [f"f{index}" for index in range(len(received))]
    assert error is not None or len(received) < FRAME_COUNT
    assert client.inflight == 0


@pytest.mark.asyncio
async def test_capture_start_race_completes_and_closes_pool(upstream):
    # Intent: a request capturing the client right before retirement but only iterating afterward
    # must still complete, and any pool it creates must close when its final stream finishes.
    client = _client(upstream)
    # The client is retired while idle (inflight == 0).
    close_task = client.schedule_close_when_idle()
    await asyncio.wait_for(close_task, timeout=5)
    assert client._retiring is True
    assert client.inflight == 0

    # Captured request starts iterating after the client was already marked retiring.
    gen = client.generate(_body())
    try:
        received = await _read_frames(upstream, gen, 0, FRAME_COUNT)
        assert [event["text"] for event in received] == [f"f{index}" for index in range(FRAME_COUNT)]
        assert client.inflight == 1

        pool = _single_pool(client)
        assert pool.is_closed is False

        await _end_stream(upstream, gen)
        assert client.inflight == 0
        # When inflight drops to 0 on a retired client, the created pool must be closed.
        assert pool.is_closed is True
        assert client._pools == {}
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_retiring_client_cancels_scheduler_background_refresh_immediately(upstream, monkeypatch):
    # Intent: retiring a client immediately cancels background refresh tasks and avoids delayed billing probes,
    # while active generate streams remain unaffected and complete normally.
    keys = ["key-alpha-1111", "key-beta-2222"]
    client = CommandCodeClient(
        base_url=f"http://127.0.0.1:{upstream.port}",
        api_key=keys[0],
        api_keys=keys,
    )
    assert client.scheduler is not None

    probed_keys: list[str] = []

    async def delayed_probe(api_key: str, *, stagger: bool = False) -> int | None:
        if api_key == keys[1]:
            await asyncio.sleep(60.0)  # simulate long staggered delay
        probed_keys.append(api_key)
        return 100

    monkeypatch.setattr(client.scheduler, "_probe", delayed_probe)
    client.scheduler._last_fetch = time.monotonic() - 3600.0  # stale
    client.scheduler._trigger_refresh(stagger=True)
    assert client.scheduler._fetch_task is not None
    assert not client.scheduler._fetch_task.done()

    # Start an active stream
    gen = client.generate(_body())
    try:
        received = await _read_frames(upstream, gen, 0, 1)
        assert received[0]["text"] == "f0"
        assert client.inflight == 1
        pool = client._client(keys[0])
        assert pool.is_closed is False

        # Retire the client while stream is active
        close_task = client.schedule_close_when_idle()
        # Scheduler's background refresh must be cancelled immediately
        assert client.scheduler.is_closed is True
        await asyncio.sleep(0.02)
        assert client.scheduler._fetch_task.done() is True
        assert keys[1] not in probed_keys  # delayed probe never fired

        # The active stream is NOT closed and can continue
        assert pool.is_closed is False
        received += await _read_frames(upstream, gen, 1, FRAME_COUNT)
        assert [event["text"] for event in received] == [f"f{index}" for index in range(FRAME_COUNT)]

        # Finish stream
        await _end_stream(upstream, gen)
        assert client.inflight == 0

        # Pool is closed after completion
        await asyncio.wait_for(close_task, timeout=5)
        assert pool.is_closed is True
    finally:
        await _aclose_quietly(gen)
        await asyncio.gather(*client._close_tasks, return_exceptions=True)
        await client.aclose()


@pytest.mark.asyncio
async def test_outer_generator_early_close_finishes_inner_cleanup_before_pool_closes(monkeypatch):
    client = CommandCodeClient(base_url="http://127.0.0.1:9999", api_key="key-test")
    pool = client._client("key-test")

    events: list[str] = []

    orig_pool_aclose = pool.aclose

    async def instrumented_pool_aclose():
        events.append("pool_close")
        await orig_pool_aclose()

    pool.aclose = instrumented_pool_aclose

    async def instrumented_stream(body, extra_headers=None, session=None):
        try:
            events.append("inner_yield")
            yield {"type": "text-delta", "text": "f0"}
            yield {"type": "text-delta", "text": "f1"}
        finally:
            events.append("inner_cleanup_start")
            await asyncio.sleep(0.05)  # Simulate non-trivial cleanup in inner stream
            events.append("inner_cleanup_done")

    monkeypatch.setattr(client, "_stream", instrumented_stream)

    gen = client.generate({"prompt": "hello"})
    first = await anext(gen)
    assert first["text"] == "f0"
    assert client.inflight == 1

    # Retire client while stream is active
    close_task = client.schedule_close_when_idle()
    assert client._retiring is True

    # Early close outer generator
    await gen.aclose()
    await asyncio.wait_for(close_task, timeout=2.0)

    assert client.inflight == 0
    assert pool.is_closed is True
    assert events == [
        "inner_yield",
        "inner_cleanup_start",
        "inner_cleanup_done",
        "pool_close",
    ]


@pytest.mark.asyncio
async def test_outer_generator_counter_cleanup_unconditional_on_stream_aclose_error(monkeypatch):
    client = CommandCodeClient(base_url="http://127.0.0.1:9999", api_key="key-test")

    async def failing_stream(body, extra_headers=None, session=None):
        try:
            yield {"type": "text-delta", "text": "f0"}
        finally:
            raise RuntimeError("inner stream aclose error")

    monkeypatch.setattr(client, "_stream", failing_stream)

    gen = client.generate({"prompt": "hello"})
    first = await anext(gen)
    assert first["text"] == "f0"
    assert client.inflight == 1

    close_task = client.schedule_close_when_idle()

    with pytest.raises(RuntimeError, match="inner stream aclose error"):
        await gen.aclose()

    await asyncio.wait_for(close_task, timeout=2.0)
    assert client.inflight == 0
