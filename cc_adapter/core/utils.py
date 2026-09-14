from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any


_PII_PATTERNS = (
    (re.compile(r"(?<![A-Za-z0-9])(?:/home|/Users|/root)/[^\s\"'`<>]+"), "<path>"),
    (re.compile(r"(?<![A-Za-z0-9])~[\\/][^\s\"'`<>]+"), "<path>"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\"'`<>]+", re.I), "<path>"),
    (re.compile(r"\b(?:sk-|key-|ghp_)[A-Za-z0-9_-]+\b"), "<secret>"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])"), "<secret>"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])"), "<secret>"),
    (re.compile(r"(?i)(\b(?:bearer|token|secret|api[_ -]?key)\s*[:=]\s*)[^\s,;]+"), r"\1<secret>"),
)


def scrub_pii(value: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def generate_id(prefix: str = "", length: int = 12) -> str:
    return f"{prefix}{uuid.uuid4().hex[:length]}"


def api_key_id(key: str) -> str:
    """Opaque, deterministic identifier for an upstream API key."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"key_{digest}"


def mask_api_key(key: str) -> str:
    """Display form of an upstream key: the panel never receives the full value.

    ``>20`` characters keep the first 10 and the last 6 (enough for an operator to tell
    accounts apart), shorter keys keep only the last 4. The admin UI mirrors this rule
    (``maskToken`` in ``admin/static/admin.js``) for values it never sends to the server.
    """
    if len(key) > 20:
        return f"{key[:10]}…{key[-6:]}"
    if len(key) >= 4:
        return f"****{key[-4:]}"
    return "****"


def normalize_api_keys(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [k for k in value if k]
    if isinstance(value, str):
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [k for k in parsed if k]
        except (json.JSONDecodeError, TypeError):
            pass
        return [value]
    return []


def parse_usage(raw_usage: dict | None) -> dict | None:
    if not raw_usage:
        return None
    input_t = raw_usage.get("inputTokens", 0)
    output_t = raw_usage.get("outputTokens", 0)
    result = {
        "input_tokens": input_t,
        "output_tokens": output_t,
        "total_tokens": input_t + output_t,
    }
    reasoning_tokens = raw_usage.get("reasoningTokens")
    if reasoning_tokens:
        result["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return result


def format_sse(event: str | None, data: dict[str, Any] | str) -> str:
    if isinstance(data, dict):
        json_data = json.dumps(data, ensure_ascii=False, default=str)
    else:
        json_data = data
    if event:
        return f"event: {event}\ndata: {json_data}\n\n"
    return f"data: {json_data}\n\n"


def parse_tool_arguments(raw: Any, label: str = "arguments") -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
