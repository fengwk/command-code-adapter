from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import cc_adapter.core.token_recorder as token_recorder


@pytest.mark.asyncio
async def test_schedule_token_record_consumes_background_errors(monkeypatch):
    async def fail(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(token_recorder, "record_daily_tokens", fail)
    warning = MagicMock()
    monkeypatch.setattr(token_recorder.logger, "warning", warning)

    task = token_recorder.schedule_token_record(1, 2, model="test-model")
    assert task is not None
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    warning.assert_called_once()
    assert warning.call_args.args[0] == "token_recorder.record_failed"
