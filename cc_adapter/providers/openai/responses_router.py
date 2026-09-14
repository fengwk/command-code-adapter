from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cc_adapter.core.errors import AdapterError
from cc_adapter.core.retry import stream_with_retry
from cc_adapter.core.runtime import get_config, get_or_create_client, get_responses_translator
from cc_adapter.core.constants import STREAMING_HEADERS
from cc_adapter.providers.openai.responses_models import ResponseCreateRequest
from cc_adapter.providers.openai.responses_response import (
    translate_responses_stream,
    collect_and_translate_responses_nonstream,
    _sse,
)
from cc_adapter.providers.shared.session_extractor import get_session_extractor

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/v1/responses")
async def create_response(req: ResponseCreateRequest, request: Request):
    structlog.contextvars.bind_contextvars(protocol="responses")

    logger.info(
        "responses.request",
        model=req.model,
        stream=str(req.stream),
        input_type="string" if isinstance(req.input, str) else "list",
        tools="yes" if req.tools else "no",
    )

    try:
        translator = get_responses_translator()
        cc_body = translator.translate(req)
        cc_body["params"]["stream"] = True

        logger.info(
            "responses.request.cc",
            model=req.model,
            reasoning_effort=req.reasoning.get("effort") if req.reasoning else None,
            cc_reasoning_effort=cc_body.get("params", {}).get("reasoning_effort"),
        )

        current_client = get_or_create_client()

        client_headers = {k.lower(): v for k, v in request.headers.items()}
        # Resolve the session identity once per request; the upstream session
        # id is derived per key from it (and retries keep the same identity).
        session = get_session_extractor().extract(client_headers, req, cc_body)

        if req.stream:
            return StreamingResponse(
                stream_with_retry(
                    lambda: current_client.generate(cc_body, client_headers, session=session),
                    lambda stream: translate_responses_stream(stream, req.model),
                    logger,
                    "responses.stream",
                    error_fn=lambda msg: _sse("error", {"code": 502, "message": msg}),
                ),
                media_type="text/event-stream",
                headers=STREAMING_HEADERS,
            )
        else:
            result = await collect_and_translate_responses_nonstream(
                current_client.generate(cc_body, client_headers, session=session), req.model
            )
            return result
    except AdapterError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"type": "api_error", "message": e.message}},
        )
