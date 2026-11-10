"""One place to call Claude for structured output through a tool."""

import logging

import anthropic

log = logging.getLogger(__name__)

# Models that rejected a forced tool_choice in this process. Some newer models only accept
# tool_choice "auto", so for those we ask for the tool in the prompt instead.
_FORCED_TOOL_UNSUPPORTED: set[str] = set()


def call_with_tool(
    client, *, model: str, system: str, tool: dict, messages: list, max_tokens: int
):
    """Ask Claude to answer by calling `tool`, using a forced tool_choice where supported."""
    base = {
        "model": model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "messages": messages,
    }
    if model not in _FORCED_TOOL_UNSUPPORTED:
        try:
            return client.messages.create(
                **base,
                system=system,
                tool_choice={"type": "tool", "name": tool["name"]},
            )
        except anthropic.BadRequestError as exc:
            if "tool_choice" not in str(exc):
                raise
            log.info("%s does not support a forced tool_choice; using auto", model)
            _FORCED_TOOL_UNSUPPORTED.add(model)
    return client.messages.create(
        **base,
        system=f"{system}\n\nRespond only by calling the {tool['name']} tool, exactly once.",
        tool_choice={"type": "auto"},
    )
