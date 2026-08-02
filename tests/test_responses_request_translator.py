from __future__ import annotations

import pytest
from cc_adapter.core.errors import AdapterError
from cc_adapter.providers.openai.responses_request import ResponsesRequestTranslator
from cc_adapter.providers.openai.responses_models import ResponseCreateRequest


@pytest.fixture
def translator():
    return ResponsesRequestTranslator()


@pytest.mark.asyncio
async def test_simple_string_input(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hello")
    body = translator.translate(req)
    params = body["params"]
    assert params["model"] == "deepseek/deepseek-v4-flash"
    assert len(params["messages"]) == 1
    assert params["messages"][0]["role"] == "user"
    assert params["messages"][0]["content"][0]["text"] == "Hello"
    assert params["stream"] is True
    assert params["max_tokens"] == 64000


@pytest.mark.asyncio
async def test_instructions_mapped_to_system(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", instructions="Be concise")
    body = translator.translate(req)
    assert body["params"]["system"] == "Be concise"


@pytest.mark.asyncio
async def test_temperature_passthrough(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", temperature=0.7)
    body = translator.translate(req)
    assert body["params"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_max_output_tokens_mapped(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", max_output_tokens=100)
    body = translator.translate(req)
    assert body["params"]["max_tokens"] == 100


@pytest.mark.asyncio
async def test_reasoning_effort_mapped(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", reasoning={"effort": "high"})
    body = translator.translate(req)
    assert body["params"]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_reasoning_effort_xhigh_clamps_for_deepseek(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", reasoning={"effort": "xhigh"})
    body = translator.translate(req)
    assert body["params"]["reasoning_effort"] == "max"


@pytest.mark.asyncio
async def test_tools(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="Read the file",
        tools=[
            {
                "name": "Read",
                "description": "Read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            }
        ],
    )
    body = translator.translate(req)
    assert len(body["params"]["tools"]) == 1
    assert body["params"]["tools"][0]["name"] == "Read"


@pytest.mark.asyncio
async def test_tool_choice_auto(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash", input="Hi", tools=[{"name": "Read", "input_schema": {}}], tool_choice="auto"
    )
    body = translator.translate(req)
    assert body["params"]["tool_choice"] == {"type": "auto"}


@pytest.mark.asyncio
async def test_tool_choice_none(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", tool_choice="none")
    body = translator.translate(req)
    assert body["params"]["tool_choice"] == {"type": "none"}


@pytest.mark.asyncio
async def test_multi_turn_input_list(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "input_text", "text": "Hi there"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "How are you?"}]},
        ],
    )
    body = translator.translate(req)
    assert len(body["params"]["messages"]) == 3
    assert body["params"]["messages"][0]["role"] == "user"
    assert body["params"]["messages"][1]["role"] == "assistant"
    assert body["params"]["messages"][2]["role"] == "user"


@pytest.mark.asyncio
async def test_function_call_output_in_input(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[
            {"type": "function_call", "call_id": "call_1", "name": "Read", "arguments": '{"path": "/tmp/test.txt"}'},
            {"type": "function_call_output", "call_id": "call_1", "output": "file content"},
        ],
    )
    body = translator.translate(req)
    assert len(body["params"]["messages"]) == 2
    assert body["params"]["messages"][0]["role"] == "assistant"
    assert body["params"]["messages"][0]["content"][0]["type"] == "tool-call"
    assert body["params"]["messages"][1]["role"] == "tool"
    assert body["params"]["messages"][1]["content"][0]["type"] == "tool-result"


@pytest.mark.asyncio
async def test_unknown_model_passthrough(translator):
    req = ResponseCreateRequest(model="unknown-model-42", input="Hi")
    body = translator.translate(req)
    assert body["params"]["model"] == "unknown-model-42"


@pytest.mark.asyncio
async def test_output_text_content_block_not_stringified(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Previous answer"}],
            },
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Tell me more"}]},
        ],
    )
    body = translator.translate(req)
    msgs = body["params"]["messages"]
    assert len(msgs) == 2
    assert msgs[0]["content"][0]["type"] == "text"
    assert msgs[0]["content"][0]["text"] == "Previous answer"


@pytest.mark.asyncio
async def test_previous_response_id_raises_400(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", previous_response_id="resp_prev")
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_response_format_raises_400(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", response_format={"type": "json_object"})
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_built_in_tool_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="search",
        tools=[{"type": "web_search_preview"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_function_tool_passes_validation(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="do it",
        tools=[{"name": "my_func", "input_schema": {"type": "object", "properties": {}}}],
    )
    body = translator.translate(req)
    assert len(body["params"]["tools"]) == 1
    assert body["params"]["tools"][0]["name"] == "my_func"


@pytest.mark.asyncio
async def test_function_tool_missing_name_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="do it",
        tools=[{"type": "function", "input_schema": {"type": "object"}}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "name" in exc.value.message


@pytest.mark.asyncio
async def test_function_tool_missing_input_schema_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="do it",
        tools=[{"name": "my_func"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "input_schema" in exc.value.message


@pytest.mark.asyncio
async def test_unsupported_input_item_type_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "web_search_call", "id": "ws_1"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "web_search_call" in exc.value.message


@pytest.mark.asyncio
async def test_tool_choice_standard_dict_passthrough(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", tool_choice={"type": "none"})
    body = translator.translate(req)
    assert body["params"]["tool_choice"] == {"type": "none"}


@pytest.mark.asyncio
async def test_tool_choice_function_dict_translates(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="Hi",
        tools=[{"name": "Read", "input_schema": {"type": "object", "properties": {}}}],
        tool_choice={"type": "function", "name": "Read"},
    )
    body = translator.translate(req)
    assert body["params"]["tool_choice"] == {"type": "tool", "name": "Read"}


@pytest.mark.asyncio
async def test_tool_choice_nonstandard_dict_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash", input="Hi", tool_choice={"type": "function", "function": {"name": "Read"}}
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reasoning_input_item_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "reasoning", "id": "rs_1", "content": [{"type": "reasoning_text", "text": "Let me think"}]}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "reasoning" in exc.value.message


@pytest.mark.asyncio
async def test_item_reference_input_item_raises_400(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input=[{"type": "item_reference", "id": "resp_ref"}])
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "item_reference" in exc.value.message


@pytest.mark.asyncio
async def test_tool_non_dict_schema_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="do it",
        tools=[{"name": "my_func", "parameters": "not-a-schema"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "JSON Schema" in exc.value.message


@pytest.mark.asyncio
async def test_input_image_content_block_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": "http://example.com/img.png"}],
            }
        ],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "input_image" in exc.value.message


@pytest.mark.asyncio
async def test_empty_message_content_list_raises_400(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input=[{"type": "message", "role": "user", "content": []}])
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "empty" in exc.value.message


@pytest.mark.asyncio
async def test_empty_message_content_str_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash", input=[{"type": "message", "role": "user", "content": "   "}]
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "empty" in exc.value.message


@pytest.mark.asyncio
async def test_function_call_missing_call_id_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "function_call", "name": "Read", "arguments": "{}"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "call_id" in exc.value.message


@pytest.mark.asyncio
async def test_function_call_missing_name_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "function_call", "call_id": "call_1", "arguments": "{}"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "name" in exc.value.message


@pytest.mark.asyncio
async def test_function_call_output_unmatched_call_id_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "function_call_output", "call_id": "orphan_id", "output": "result"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "orphan_id" in exc.value.message


@pytest.mark.asyncio
async def test_tool_choice_function_without_tools_raises_400(translator):
    req = ResponseCreateRequest(model="deepseek-v4-flash", input="Hi", tool_choice={"type": "function", "name": "Read"})
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "no tools" in exc.value.message


@pytest.mark.asyncio
async def test_tool_choice_name_not_in_tools_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input="Hi",
        tools=[{"name": "Bash", "input_schema": {"type": "object", "properties": {}}}],
        tool_choice={"type": "function", "name": "Read"},
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "does not match" in exc.value.message


@pytest.mark.asyncio
async def test_unknown_message_role_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "message", "role": "narrator", "content": [{"type": "input_text", "text": "hi"}]}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "role" in exc.value.message


@pytest.mark.asyncio
async def test_input_file_content_block_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "message", "role": "user", "content": [{"type": "input_file", "file_id": "file_123"}]}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "input_file" in exc.value.message


@pytest.mark.asyncio
async def test_function_call_invalid_arguments_raises_400(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[{"type": "function_call", "call_id": "call_1", "name": "Read", "arguments": "not-json"}],
    )
    with pytest.raises(AdapterError) as exc:
        translator.translate(req)
    assert exc.value.status_code == 400
    assert "arguments" in exc.value.message


@pytest.mark.asyncio
async def test_assistant_tool_calls_without_text_content_translates(translator):
    req = ResponseCreateRequest(
        model="deepseek-v4-flash",
        input=[
            {
                "type": "message",
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "Read", "arguments": '{"path": "/tmp/test.txt"}'}}
                ],
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "file content"},
        ],
    )
    body = translator.translate(req)
    messages = body["params"]["messages"]
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == [
        {"type": "tool-call", "toolCallId": "call_1", "toolName": "Read", "input": {"path": "/tmp/test.txt"}}
    ]
    assert messages[1]["role"] == "tool"
    assert messages[1]["content"][0]["toolName"] == "Read"
