import pytest
from cc_adapter.core.utils import api_key_id, generate_id, mask_api_key, normalize_api_keys, scrub_pii


class TestNormalizeApiKeys:
    def test_empty_string_returns_empty(self):
        assert normalize_api_keys("") == []

    def test_single_key_string_returns_list(self):
        assert normalize_api_keys("key1") == ["key1"]

    def test_json_array_string(self):
        assert normalize_api_keys('["k1","k2"]') == ["k1", "k2"]

    def test_list_input(self):
        assert normalize_api_keys(["k1", "k2"]) == ["k1", "k2"]

    def test_list_filters_empty(self):
        assert normalize_api_keys(["k1", "", "k2"]) == ["k1", "k2"]

    def test_none_returns_empty(self):
        assert normalize_api_keys(None) == []

    def test_invalid_json_falls_back_to_single(self):
        assert normalize_api_keys("{bad") == ["{bad"]


class TestGenerateId:
    def test_defaults_to_12_char_hex(self):
        result = generate_id()
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    def test_with_prefix(self):
        result = generate_id("chatcmpl-")
        assert result.startswith("chatcmpl-")
        assert len(result) == 21  # 9 prefix + 12 hex

    def test_custom_length(self):
        result = generate_id("msg_", 16)
        assert result.startswith("msg_")
        assert len(result) == 20  # 4 prefix + 16 hex

    def test_zero_length(self):
        result = generate_id("test", 0)
        assert result == "test"

    def test_no_prefix(self):
        result = generate_id(length=8)
        assert len(result) == 8

    def test_unique_values(self):
        results = {generate_id() for _ in range(100)}
        assert len(results) == 100  # all unique


class TestApiKeyId:
    def test_format_and_length(self):
        # 16 hex chars prefix 'key_' => 20 chars total (64 bits of digest)
        res = api_key_id("secret-key")
        assert res.startswith("key_")
        assert len(res) == 20
        assert all(c in "0123456789abcdef" for c in res[4:])

    def test_deterministic(self):
        assert api_key_id("key-1234") == api_key_id("key-1234")
        assert api_key_id("key-1234") != api_key_id("key-5678")

    def test_short_key_reveals_no_substring(self):
        res = api_key_id("abc")
        assert "abc" not in res
        assert res == "key_ba7816bf8f01cfea"


class TestMaskApiKey:
    def test_short_keys_masked_fully(self):
        assert mask_api_key("a") == "****"
        assert mask_api_key("ab") == "****"
        assert mask_api_key("abc") == "****"

    def test_medium_keys_keep_last4(self):
        assert mask_api_key("abcd") == "****abcd"
        assert mask_api_key("key-alpha-1111") == "****1111"
        assert mask_api_key("12345678901234567890") == "****7890"  # 20 chars

    def test_long_keys_keep_first10_and_last6(self):
        long_key = "sk-123456789012345678901"  # 23 chars
        assert mask_api_key(long_key) == "sk-1234567…678901"
        assert mask_api_key(long_key).startswith("sk-1234567")
        assert mask_api_key(long_key).endswith("678901")
        assert "…" in mask_api_key(long_key)


def test_scrub_pii_keeps_normal_model_response_text_unchanged():
    assert scrub_pii("The answer is 42") == "The answer is 42"


def test_get_or_create_client_fallback():
    from cc_adapter.core.runtime import _config, _cc_client, get_or_create_client

    saved_config = _config
    saved_client = _cc_client
    try:
        import cc_adapter.core.runtime as rt

        rt._config = None
        rt._cc_client = None
        client = get_or_create_client()
        assert client is not None
    finally:
        import cc_adapter.core.runtime as rt

        rt._config = saved_config
        rt._cc_client = saved_client
