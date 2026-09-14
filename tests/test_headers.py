"""Header contract of the CC upstream requests.

The expected set, order and casing mirror a real cmd CLI request measured on the wire
(Node v24 `fetch`/undici), and the wire test at the bottom re-measures the bytes this
adapter actually puts on a socket.
"""

import asyncio
import json
import time

import pytest

import cc_adapter.core.runtime as runtime
from cc_adapter.command_code.client import CommandCodeClient
from cc_adapter.command_code.headers import make_cc_headers, _make_traceparent
from cc_adapter.core.config import AppConfig
from cc_adapter.core.runtime import get_version_checker, reset_version_checker
from cc_adapter.providers.shared.session_extractor import SessionIdentity, get_session_extractor

_KEY = "cc-key-wire-0001"


@pytest.fixture(autouse=True)
def no_npm_fetch():
    """Keep the header tests off the network: a stale version checker fetches npm in the background."""
    reset_version_checker()
    checker = get_version_checker()
    checker._last_fetch_time = time.monotonic()  # fresh snapshot: no fetch is scheduled
    yield
    reset_version_checker()


# Full request line order, as undici emits it: Host/connection first (both written by
# the HTTP layer of the CLI), the CLI's own headers, then the undici defaults, then
# Content-Length. `content-length` is appended by httpx itself and is the only name we
# do not write ourselves (`Host` too, unless a base URL is passed).
EXPECTED_WIRE_HEADERS = [
    "host",
    "connection",
    "Content-Type",
    "User-Agent",
    "x-command-code-version",
    "x-cli-environment",
    "x-project-slug",
    "x-taste-learning",
    "traceparent",
    "x-session-id",
    "Authorization",
    "x-oss-primary-provider",
    "x-cmd-zdr",
    "accept",
    "accept-language",
    "sec-fetch-mode",
    "accept-encoding",
    "Content-Length",
]


class TestMakeCcHeaders:
    def test_base_headers(self):
        headers = make_cc_headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["x-cli-environment"] == "production"
        assert headers["x-taste-learning"] == "false"
        # cmd CLI never sends x-co-flag
        assert "x-co-flag" not in headers
        # session-scoped headers come from the identity, not from thin air
        assert "x-project-slug" not in headers
        assert "x-session-id" not in headers
        assert "Authorization" not in headers
        # no base URL -> the transport picks Host itself
        assert "host" not in headers

    def test_undici_default_headers(self):
        """Headers Node/undici adds on top of the cmd CLI harness headers."""
        headers = make_cc_headers()
        assert headers["User-Agent"] == "cli"
        assert headers["accept"] == "*/*"
        assert headers["accept-language"] == "*"
        assert headers["sec-fetch-mode"] == "cors"
        assert headers["accept-encoding"] == "gzip, deflate"
        assert headers["connection"] == "keep-alive"

    def test_header_order_is_locked(self, monkeypatch):
        """The byte order of the request line: identity and optional headers included."""
        monkeypatch.setattr(runtime, "_config", AppConfig(oss_primary_provider="deepseek"))
        identity = SessionIdentity(session_id="sess_0123456789abcdef", project_slug="core-api", home_login="mchen")
        headers = make_cc_headers("sk-test", identity=identity, base_url="https://api.commandcode.ai")
        assert list(headers) == [name for name in EXPECTED_WIRE_HEADERS if name != "Content-Length"]

    def test_with_api_key(self):
        headers = make_cc_headers("sk-test")
        assert headers["Authorization"] == "Bearer sk-test"

    def test_identity_fills_the_session_headers(self):
        identity = SessionIdentity(session_id="sess_0123456789abcdef", project_slug="core-api", home_login="mchen")
        headers = make_cc_headers("sk-test", identity=identity)
        assert headers["x-session-id"] == "sess_0123456789abcdef"
        assert headers["x-project-slug"] == "core-api"

    def test_base_url_makes_the_host_header_explicit(self):
        headers = make_cc_headers("sk-test", base_url="https://api.commandcode.ai")
        assert headers["host"] == "api.commandcode.ai"
        assert list(headers)[0] == "host"
        assert make_cc_headers("sk-test", base_url="http://127.0.0.1:9000")["host"] == "127.0.0.1:9000"
        assert "host" not in make_cc_headers("sk-test")  # unusable base URL -> leave it to the transport

    def test_traceparent_format(self):
        headers = make_cc_headers()
        tp = headers["traceparent"]
        parts = tp.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32
        assert len(parts[2]) == 16
        assert parts[3] == "01"

    def test_traceparent_unique(self):
        tp1 = make_cc_headers()["traceparent"]
        tp2 = make_cc_headers()["traceparent"]
        assert tp1 != tp2

    def test_oss_provider_not_included_when_empty(self, monkeypatch):
        monkeypatch.setattr(runtime, "_config", AppConfig(oss_primary_provider=""))
        headers = make_cc_headers()
        assert "x-oss-primary-provider" not in headers

    def test_oss_provider_included_when_set(self, monkeypatch):
        monkeypatch.setattr(runtime, "_config", AppConfig(oss_primary_provider="deepseek"))
        headers = make_cc_headers()
        assert headers["x-oss-primary-provider"] == "deepseek"
        # ordered before x-cmd-zdr, like the CLI sends it
        names = list(headers)
        assert names.index("x-oss-primary-provider") < names.index("x-cmd-zdr")


class TestVersionHeader:
    def test_x_command_code_version_reflects_checker(self, monkeypatch):
        reset_version_checker()
        checker = get_version_checker()
        monkeypatch.setattr(checker, "get_version", lambda: "9.99.9")
        headers = make_cc_headers()
        assert headers["x-command-code-version"] == "9.99.9"

    def test_x_command_code_version_is_always_present(self):
        reset_version_checker()
        version = make_cc_headers()["x-command-code-version"]
        assert isinstance(version, str) and version


async def _capture_post(build_headers, body: dict) -> tuple[list[tuple[str, str]], str, bytes, bytes]:
    """Send one real POST to a local socket; return (header pairs, raw head, body, netloc).

    A raw socket server is the only way to observe what actually reaches the wire: a
    mocked transport (respx) never serialises the headers. `build_headers` receives the
    base URL of the capture server, like the client does in production.
    """
    captured: dict[str, bytes] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        captured["head"] = head
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        captured["body"] = await reader.readexactly(length)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    client = CommandCodeClient(base_url=base_url, api_key=_KEY)
    try:
        # The per-key pool is the transport every /alpha/generate request uses.
        pool = client._client(_KEY)
        async with pool.stream(
            "POST", f"{base_url}/alpha/generate", json=body, headers=build_headers(base_url)
        ) as response:
            await response.aread()
    finally:
        await client.aclose()
        server.close()
        await server.wait_closed()

    head = captured["head"].decode("utf-8")
    lines = head.split("\r\n")
    pairs = [tuple(line.split(": ", 1)) for line in lines[1:] if ": " in line]
    return pairs, head, captured["body"], f"127.0.0.1:{port}"


def _header_names(pairs: list[tuple[str, str]]) -> list[str]:
    return [name for name, _ in pairs]


class TestWireHeaders:
    @pytest.mark.asyncio
    async def test_wire_headers_match_undici_order_and_casing(self, monkeypatch):
        """No httpx default leaks in, Host stays first and Content-Length stays last."""
        monkeypatch.setattr(runtime, "_config", AppConfig(oss_primary_provider="deepseek"))
        identity = get_session_extractor().derive("header:wire-test", _KEY)
        body = {"params": {"model": "deepseek/deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}]}}

        pairs, head, raw_body, netloc = await _capture_post(
            lambda base_url: make_cc_headers(_KEY, identity=identity, base_url=base_url), body
        )

        assert head.startswith("POST /alpha/generate HTTP/1.1\r\n")
        assert _header_names(pairs) == EXPECTED_WIRE_HEADERS
        values = dict(pairs)
        assert values["host"] == netloc
        assert values["connection"] == "keep-alive"
        assert values["Content-Type"] == "application/json"
        assert values["User-Agent"] == "cli"
        assert values["x-session-id"] == identity.session_id
        assert values["x-project-slug"] == identity.project_slug
        assert values["Authorization"] == f"Bearer {_KEY}"
        assert values["x-oss-primary-provider"] == "deepseek"
        assert values["x-cmd-zdr"] == "1"
        assert values["accept"] == "*/*"
        assert values["accept-language"] == "*"
        assert values["sec-fetch-mode"] == "cors"
        assert values["accept-encoding"] == "gzip, deflate"
        # Content-Length matches the bytes on the wire and the body survived the trip
        assert int(values["Content-Length"]) == len(raw_body)
        assert json.loads(raw_body) == body
        # Nothing may advertise the HTTP library the adapter is written in
        assert "python-httpx" not in head.lower()

    @pytest.mark.asyncio
    async def test_wire_headers_carry_no_httpx_defaults_for_a_non_generate_call(self):
        """A credits/usage call (no identity headers) still replaces every httpx default."""
        pairs, head, _, netloc = await _capture_post(
            lambda base_url: make_cc_headers(_KEY, base_url=base_url), {"a": 1}
        )
        assert _header_names(pairs) == [
            "host",
            "connection",
            "Content-Type",
            "User-Agent",
            "x-command-code-version",
            "x-cli-environment",
            "x-taste-learning",
            "traceparent",
            "Authorization",
            "x-cmd-zdr",
            "accept",
            "accept-language",
            "sec-fetch-mode",
            "accept-encoding",
            "Content-Length",
        ]
        assert dict(pairs)["host"] == netloc
        assert "python-httpx" not in head.lower()
