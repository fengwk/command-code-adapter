from __future__ import annotations

from typing import Any

WEB_SEARCH_TOOL_DEFINITION: dict[str, Any] = {
    "name": "web_search",
    "description": (
        "Search the web for current information. "
        "Returns a list of results with title, URL, and description. "
        "Always include a 'Sources:' section at the end of your response citing the URLs used."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query (min 2 characters)",
            },
            "numResults": {
                "type": "integer",
                "description": "Number of results to return (1-10), default 5",
                "default": 5,
            },
            "allowedDomains": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Only return results from these domains (subdomains are auto-matched). "
                    "Cannot be used together with blockedDomains."
                ),
            },
            "blockedDomains": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("Exclude results from these domains. " "Cannot be used together with allowedDomains."),
            },
        },
        "required": ["query"],
    },
}

WEB_FETCH_TOOL_DEFINITION: dict[str, Any] = {
    "name": "web_fetch",
    "description": (
        "Fetch and read the content of a URL. "
        "Results are cached for 15 minutes. "
        "Supports pagination via startIndex for large pages."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch (http is auto-upgraded to https)",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "text", "html"],
                "description": "Output format, default markdown",
                "default": "markdown",
            },
            "startIndex": {
                "type": "integer",
                "description": "Character offset for paginated reading from previous truncation point",
                "default": 0,
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (1-120), default 60",
                "default": 60,
            },
        },
        "required": ["url"],
    },
}

_WEB_TOOL_MAP: dict[str, dict[str, Any]] = {
    "web_search": WEB_SEARCH_TOOL_DEFINITION,
    "web_fetch": WEB_FETCH_TOOL_DEFINITION,
}


def is_anthropic_web_tool(tool: Any) -> bool:
    if tool is None:
        return False
    tool_type = getattr(tool, "type", None) or (tool.get("type") if isinstance(tool, dict) else None)
    if not isinstance(tool_type, str) or not tool_type.startswith("web_search"):
        return False
    tool_name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
    return tool_name in _WEB_TOOL_MAP


def anthropic_web_tool_to_function(tool: Any) -> dict[str, Any]:
    tool_name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
    definition = _WEB_TOOL_MAP.get(tool_name)
    if definition is None:
        raise ValueError(f"Unknown web tool: {tool_name}")
    return definition
