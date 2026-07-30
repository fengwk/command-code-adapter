from cc_adapter.providers.shared.web_search import (
    WEB_SEARCH_TOOL_DEFINITION,
    WEB_FETCH_TOOL_DEFINITION,
    is_anthropic_web_tool,
    anthropic_web_tool_to_function,
)


class DummyTool:
    def __init__(self, name, type=None, input_schema=None):
        self.name = name
        self.type = type
        self.input_schema = input_schema


class TestWebSearchToolDefinition:
    def test_has_required_structure(self):
        assert WEB_SEARCH_TOOL_DEFINITION["name"] == "web_search"
        assert "description" in WEB_SEARCH_TOOL_DEFINITION
        schema = WEB_SEARCH_TOOL_DEFINITION["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["required"]
        assert "numResults" in schema["properties"]
        assert "allowedDomains" in schema["properties"]
        assert "blockedDomains" in schema["properties"]

    def test_numResults_has_default(self):
        assert WEB_SEARCH_TOOL_DEFINITION["input_schema"]["properties"]["numResults"]["default"] == 5

    def test_query_is_required_only(self):
        assert WEB_SEARCH_TOOL_DEFINITION["input_schema"]["required"] == ["query"]


class TestWebFetchToolDefinition:
    def test_has_required_structure(self):
        assert WEB_FETCH_TOOL_DEFINITION["name"] == "web_fetch"
        assert "description" in WEB_FETCH_TOOL_DEFINITION
        schema = WEB_FETCH_TOOL_DEFINITION["input_schema"]
        assert schema["type"] == "object"
        assert "url" in schema["required"]
        assert "format" in schema["properties"]
        assert "startIndex" in schema["properties"]
        assert "timeout" in schema["properties"]

    def test_format_has_enum(self):
        fmt = WEB_FETCH_TOOL_DEFINITION["input_schema"]["properties"]["format"]
        assert fmt["enum"] == ["markdown", "text", "html"]

    def test_url_is_required_only(self):
        assert WEB_FETCH_TOOL_DEFINITION["input_schema"]["required"] == ["url"]


class TestIsAnthropicWebTool:
    def test_detects_web_search_server_tool_object(self):
        tool = DummyTool(name="web_search", type="web_search_20250305")
        assert is_anthropic_web_tool(tool) is True

    def test_detects_web_fetch_server_tool_object(self):
        tool = DummyTool(name="web_fetch", type="web_search_20250305")
        assert is_anthropic_web_tool(tool) is True

    def test_detects_dict_tool(self):
        tool = {"type": "web_search_20250101", "name": "web_search"}
        assert is_anthropic_web_tool(tool) is True

    def test_ignores_regular_function_tool_named_web_search(self):
        tool = DummyTool(name="web_search", input_schema={"type": "object"})
        assert is_anthropic_web_tool(tool) is False

    def test_ignores_tool_without_type(self):
        tool = DummyTool(name="web_search")
        assert is_anthropic_web_tool(tool) is False

    def test_ignores_unknown_server_tool(self):
        tool = DummyTool(name="code_execution", type="code_execution_20250522")
        assert is_anthropic_web_tool(tool) is False

    def test_ignores_none(self):
        assert is_anthropic_web_tool(None) is False

    def test_ignores_empty_dict(self):
        assert is_anthropic_web_tool({}) is False


class TestAnthropicWebToolToFunction:
    def test_converts_web_search_object(self):
        tool = DummyTool(name="web_search", type="web_search_20250305")
        result = anthropic_web_tool_to_function(tool)
        assert result["name"] == "web_search"
        assert "query" in result["input_schema"]["properties"]

    def test_converts_web_fetch_object(self):
        tool = DummyTool(name="web_fetch", type="web_search_20250305")
        result = anthropic_web_tool_to_function(tool)
        assert result["name"] == "web_fetch"
        assert "url" in result["input_schema"]["required"]

    def test_converts_dict_tool(self):
        tool = {"type": "web_search_20250101", "name": "web_search"}
        result = anthropic_web_tool_to_function(tool)
        assert result["name"] == "web_search"

    def test_raises_for_unknown_tool_name(self):
        import pytest

        tool = DummyTool(name="unknown_tool", type="web_search_20250305")
        with pytest.raises(ValueError):
            anthropic_web_tool_to_function(tool)
