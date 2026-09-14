from __future__ import annotations

import structlog

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cc_adapter.providers.anthropic.models import (
    AnthropicRequest,
    normalize_system_messages,
)
from cc_adapter.providers.anthropic.response import (
    translate_anthropic_stream,
    collect_and_translate_anthropic_nonstream,
)
from cc_adapter.command_code.client import CommandCodeClient
from cc_adapter.core.retry import stream_with_retry
from cc_adapter.core.runtime import get_anthropic_translator
from cc_adapter.core.constants import STREAMING_HEADERS
from cc_adapter.core.errors import AdapterError
from cc_adapter.core.utils import format_sse
from cc_adapter.providers.shared.session_extractor import get_session_extractor

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_client() -> CommandCodeClient:
    from cc_adapter.core.runtime import get_or_create_client

    return get_or_create_client()


def _anthropic_sse_error(message: str) -> str:
    return format_sse("error", {"type": "error", "error": {"type": "api_error", "message": message}})


@router.post("/v1/messages")
async def anthropic_chat(req: AnthropicRequest, request: Request):
    structlog.contextvars.bind_contextvars(protocol="anthropic")
    req = normalize_system_messages(req)

    logger.info(
        "anthropic.request",
        model=req.model,
        stream=str(req.stream),
        message_count=len(req.messages),
        tools="yes" if req.tools else "no",
    )

    try:
        translator = get_anthropic_translator()
        cc_body = translator.translate(req)
        cc_body["params"]["stream"] = True

        logger.info(
            "anthropic.request.cc",
            model=req.model,
            cc_reasoning_effort=cc_body.get("params", {}).get("reasoning_effort"),
            thinking_budget=req.thinking.budget_tokens if req.thinking else None,
        )

        current_client = _get_client()

        client_headers = {k.lower(): v for k, v in request.headers.items()}
        # Resolve the session identity once per request; the upstream session
        # id is derived per key from it (and retries keep the same identity).
        session = get_session_extractor().extract(client_headers, req, cc_body)

        if req.stream:
            return StreamingResponse(
                stream_with_retry(
                    lambda: current_client.generate(cc_body, client_headers, session=session),
                    lambda stream: translate_anthropic_stream(stream, req.model),
                    logger,
                    "anthropic.stream",
                    error_fn=lambda msg: _anthropic_sse_error(msg),
                ),
                media_type="text/event-stream",
                headers=STREAMING_HEADERS,
            )
        return await collect_and_translate_anthropic_nonstream(
            current_client.generate(cc_body, client_headers, session=session), req.model
        )
    except AdapterError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"type": "api_error", "message": e.message}},
        )
