"""Anthropic client wrapper with prompt caching support."""
from __future__ import annotations
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def cached_system(text: str) -> dict:
    """Wrap a system prompt string with cache_control for prompt caching."""
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }


def call_structured(
    *,
    model: str,
    system: str,
    messages: list[dict],
    tool_schema: dict,
    tool_name: str,
    cache_system: bool = False,
    thinking: bool = False,
    thinking_budget: int = 8000,
) -> dict:
    """
    Call Claude and return the typed tool-use result as a plain dict.

    Uses a single tool definition so Claude always returns structured JSON.
    When cache_system=True, marks the system prompt for prompt caching.
    When thinking=True, enables extended thinking (Sonnet 4.6 only).
    """
    client = get_client()

    system_content: str | list = (
        [cached_system(system)] if cache_system else system
    )

    kwargs: dict = dict(
        model=model,
        max_tokens=thinking_budget + 4096 if thinking else 4096,
        system=system_content,
        messages=messages,
        tools=[
            {
                "name": tool_name,
                "description": f"Return a {tool_name} result.",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )

    if thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    response = client.messages.create(**kwargs)

    thinking_text = ""
    result_block = None
    for block in response.content:
        if block.type == "thinking":
            thinking_text = block.thinking
        elif block.type == "tool_use":
            result_block = block

    if result_block is None:
        raise ValueError(f"No tool_use block in Claude response for {tool_name}")

    data = dict(result_block.input)
    if thinking_text:
        data["__thinking__"] = thinking_text

    data["__usage__"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
    }

    return data
