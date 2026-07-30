import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response as HttpxResponse

from cc_adapter.main import app
from cc_adapter.core.config import AppConfig
from cc_adapter.core import runtime


@pytest.fixture(autouse=True)
def _clean_runtime():
    saved_config = runtime._config
    saved_client = runtime._cc_client
    yield
    runtime._config = saved_config
    runtime._cc_client = saved_client


CC_SSE_RESPONSE = (
    b'data: {"type":"text-delta","text":"Hello from CC"}\n\n'
    b'data: {"type":"finish","finishReason":"end_turn","totalUsage":{"inputTokens":10,"outputTokens":5}}\n\n'
)


@pytest.mark.asyncio
async def test_web_search_tool_goes_to_cc_not_deepseek():
    """Anthropic web_search server tool goes to CC, never the removed DeepSeek route."""
    cfg = AppConfig(cc_api_key="test-key")
    runtime._config = cfg
    runtime._cc_client = None

    async with respx.mock(assert_all_called=False) as respx_mock:
        cc_route = respx_mock.post("https://api.commandcode.ai/alpha/generate").mock(
            return_value=HttpxResponse(200, content=CC_SSE_RESPONSE)
        )
        deepseek_route = respx_mock.post("https://api.deepseek.com/anthropic/v1/messages").mock(
            return_value=HttpxResponse(200, content=b"should not be called")
        )
        respx_mock.get("https://registry.npmjs.org/command-code/latest").mock(
            return_value=HttpxResponse(200, json={"version": "0.25.2"})
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "search the web"}],
                    "stream": True,
                    "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                },
            )

    assert resp.status_code == 200
    assert "Hello from CC" in resp.text
    assert cc_route.called
    assert not deepseek_route.called


@pytest.mark.asyncio
async def test_regular_request_still_works():
    cfg = AppConfig(cc_api_key="test-key")
    runtime._config = cfg
    runtime._cc_client = None

    async with respx.mock(assert_all_called=False) as respx_mock:
        cc_route = respx_mock.post("https://api.commandcode.ai/alpha/generate").mock(
            return_value=HttpxResponse(200, content=CC_SSE_RESPONSE)
        )
        respx_mock.get("https://registry.npmjs.org/command-code/latest").mock(
            return_value=HttpxResponse(200, json={"version": "0.25.2"})
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

    assert resp.status_code == 200
    assert cc_route.called


@pytest.mark.asyncio
async def test_unknown_server_tool_returns_400():
    cfg = AppConfig(cc_api_key="test-key")
    runtime._config = cfg
    runtime._cc_client = None

    async with respx.mock(assert_all_called=False) as respx_mock:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "test"}],
                    "stream": False,
                    "tools": [{"type": "code_execution_20250522", "name": "code_execution"}],
                },
            )

    assert resp.status_code == 400
    assert "not supported" in resp.json()["error"]["message"]
