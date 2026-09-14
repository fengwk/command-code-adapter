from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle at runtime
    from cc_adapter.providers.shared.session_extractor import SessionIdentity


def _make_traceparent() -> str:
    trace_id = os.urandom(16).hex()
    span_id = os.urandom(8).hex()
    return f"00-{trace_id}-{span_id}-01"


def _url_host(base_url: str | None) -> str:
    """``host[:port]`` of a base URL, exactly as httpx derives its own Host header."""
    if not base_url:
        return ""
    try:
        return httpx.URL(base_url).netloc.decode("ascii")
    except Exception:  # pragma: no cover - defensive: unparsable base URL
        return ""


def make_cc_headers(
    api_key: str | None = None,
    *,
    identity: SessionIdentity | None = None,
    base_url: str | None = None,
) -> dict[str, str]:
    """Build the CC request headers in the exact order Node/undici emits for the CLI.

    Measured reference of a real cmd CLI request (Node v24 ``fetch``/undici)::

        host, connection, Content-Type, User-Agent, x-command-code-version,
        x-cli-environment, x-project-slug, x-taste-learning, [traceparent],
        x-session-id, Authorization, [x-oss-primary-provider], x-cmd-zdr,
        accept, accept-language, sec-fetch-mode, accept-encoding, content-length

    The dict is built in that order on purpose: httpx only prepends a header list of
    its own defaults, and the four names below *replace* (never duplicate) them
    whenever a request carries this set, so the wire order is ours - ``Host`` stays
    first and ``Content-Length`` (added by httpx) stays last. ``traceparent`` rides
    with the explicit CLI headers and ``x-oss-primary-provider`` precedes ``x-cmd-zdr``.

    ``identity`` fills the two session-scoped headers (per conversation for
    ``/alpha/generate``, per process for billing/usage calls); ``base_url`` makes the
    ``host`` header explicit instead of leaving it to the HTTP library.
    """
    headers: dict[str, str] = {}
    host = _url_host(base_url)
    if host:
        headers["host"] = host
    headers["connection"] = "keep-alive"
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = "cli"

    from cc_adapter.core.runtime import get_version_checker

    headers["x-command-code-version"] = get_version_checker().get_version()
    headers["x-cli-environment"] = "production"
    if identity is not None:
        headers["x-project-slug"] = identity.project_slug
    headers["x-taste-learning"] = "false"
    headers["traceparent"] = _make_traceparent()
    if identity is not None:
        headers["x-session-id"] = identity.session_id
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    from cc_adapter.core.runtime import get_config

    config = get_config()
    oss_provider = config.oss_primary_provider if config else ""
    if oss_provider:
        headers["x-oss-primary-provider"] = oss_provider
    if config is None or config.zdr:
        headers["x-cmd-zdr"] = "1"

    # undici (Node) defaults sent by the real cmd CLI. Setting them explicitly keeps
    # httpx from prepending its own values ("python-httpx/...", "gzip, deflate, br, zstd").
    headers["accept"] = "*/*"
    headers["accept-language"] = "*"
    headers["sec-fetch-mode"] = "cors"
    headers["accept-encoding"] = "gzip, deflate"

    return headers
