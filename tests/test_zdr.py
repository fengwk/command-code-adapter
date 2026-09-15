import pytest

import httpx
import respx

from cc_adapter.command_code.headers import make_cc_headers
from cc_adapter.command_code.client import _is_zdr_error, CommandCodeClient
from cc_adapter.core.config import AppConfig
from cc_adapter.core.errors import AdapterError


class TestZdrHeaders:
    def test_zdr_header_present_when_config_is_none(self, monkeypatch):
        import cc_adapter.core.runtime as runtime

        monkeypatch.setattr(runtime, "_config", None)

        headers = make_cc_headers(api_key="test-key")
        assert headers["x-cmd-zdr"] == "1"

    def test_zdr_header_present_when_zdr_true(self, monkeypatch):
        import cc_adapter.core.runtime as runtime

        cfg = AppConfig(zdr=True)
        monkeypatch.setattr(runtime, "_config", cfg)

        headers = make_cc_headers(api_key="test-key")
        assert headers["x-cmd-zdr"] == "1"

    def test_zdr_header_absent_when_zdr_false(self, monkeypatch):
        import cc_adapter.core.runtime as runtime

        cfg = AppConfig(zdr=False)
        monkeypatch.setattr(runtime, "_config", cfg)

        headers = make_cc_headers(api_key="test-key")
        assert "x-cmd-zdr" not in headers

    def test_zdr_default_appconfig_has_zdr_true(self):
        cfg = AppConfig()
        assert cfg.zdr is True


class TestZdrErrorDetection:
    def test_detects_zero_data_retention_phrase(self):
        text = '{"error":{"message":"This model has no zero-data-retention upstream. Disable CMD_ZDR or pick a different model.","type":"invalid_request_error","code":400}}'
        assert _is_zdr_error(400, text) is True

    def test_detects_disable_cmd_zdr(self):
        text = '{"error":{"message":"Disable CMD_ZDR for this model"}}'
        assert _is_zdr_error(400, text) is True

    @pytest.mark.parametrize("marker", ["CMD_ZDR_NO_PROVIDERS", "cmd_zdr_no_providers"])
    def test_detects_no_provider_marker(self, marker):
        assert _is_zdr_error(400, f'{{"error":{{"code":"{marker}"}}}}') is True

    def test_ignores_other_400_errors(self):
        text = '{"error":{"message":"Bad request: invalid model"}}'
        assert _is_zdr_error(400, text) is False

    def test_ignores_non_400_status(self):
        text = '{"error":{"message":"zero-data-retention error"}}'
        assert _is_zdr_error(500, text) is False


@pytest.mark.asyncio
class TestZdrFailClosed:
    async def test_fails_closed_without_downgrade_when_zdr_unsupported(self, monkeypatch):
        """When zdr=True and upstream rejects with no-ZDR 400, fail closed without retry or header stripping."""
        config = AppConfig(zdr=True, cc_api_key="sk-test-key")
        monkeypatch.setattr("cc_adapter.core.runtime._config", config)
        monkeypatch.setattr("cc_adapter.core.runtime._cc_client", None)

        zdr_error_body = '{"error":{"message":"This model has no zero-data-retention upstream. Disable CMD_ZDR or pick a different model.","type":"invalid_request_error","code":400}}'

        async with respx.mock as mock:
            route = mock.post("https://api.example.com/alpha/generate").respond(400, content=zdr_error_body)

            client = CommandCodeClient(base_url="https://api.example.com", api_key="sk-test-key")
            with pytest.raises(AdapterError) as excinfo:
                async for _ in client.generate({"params": {"model": "test-model", "messages": []}}):
                    pass

            assert route.call_count == 1  # strictly no retry
            sent_headers = route.calls[0].request.headers
            assert sent_headers.get("x-cmd-zdr") == "1"
            assert "zero-data-retention" in str(excinfo.value)

    async def test_zdr_false_omits_header_and_allows_generation(self, monkeypatch):
        """When user explicitly sets zdr=False, x-cmd-zdr is omitted and requests succeed."""
        config = AppConfig(zdr=False, cc_api_key="sk-test-key")
        monkeypatch.setattr("cc_adapter.core.runtime._config", config)
        monkeypatch.setattr("cc_adapter.core.runtime._cc_client", None)

        async with respx.mock as mock:
            route = mock.post("https://api.example.com/alpha/generate").respond(
                200,
                content='data: {"type":"result","subtype":"success"}\n\ndata: [DONE]\n',
            )

            client = CommandCodeClient(base_url="https://api.example.com", api_key="sk-test-key")
            results = [event async for event in client.generate({"params": {"model": "test-model", "messages": []}})]
            assert len(results) == 1
            assert results[0]["type"] == "result"
            assert route.call_count == 1
            assert "x-cmd-zdr" not in route.calls[0].request.headers
