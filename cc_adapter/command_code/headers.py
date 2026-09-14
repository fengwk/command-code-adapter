from __future__ import annotations

import os


def _make_traceparent() -> str:
    trace_id = os.urandom(16).hex()
    span_id = os.urandom(8).hex()
    return f"00-{trace_id}-{span_id}-01"


def make_cc_headers(api_key: str | None = None) -> dict[str, str]:
    from cc_adapter.core.runtime import get_version_checker

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "cli",
        "x-command-code-version": get_version_checker().get_version(),
        "x-cli-environment": "production",
        "x-taste-learning": "false",
        "traceparent": _make_traceparent(),
        # undici (Node) defaults sent by the real cmd CLI. Setting
        # accept-encoding explicitly stops httpx from sending its own
        # "gzip, deflate, br, zstd" value.
        "accept-language": "*",
        "sec-fetch-mode": "cors",
        "accept-encoding": "gzip, deflate",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    from cc_adapter.core.runtime import get_config

    config = get_config()
    if config is None or config.zdr:
        headers["x-cmd-zdr"] = "1"

    oss_provider = config.oss_primary_provider if config else ""
    if oss_provider:
        headers["x-oss-primary-provider"] = oss_provider

    return headers
