"""Thin Anthropic SDK wrapper for Goldman.

Phase 1 only needs structured extraction via tool use; later phases will
add conversation routing, streaming, and prompt caching. The wrapper keeps
that future surface area minimal.
"""

from __future__ import annotations

import os
from typing import Optional

import anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096


class LLMConfigError(RuntimeError):
    """Raised when the Anthropic API key is missing or unusable."""


class GoldmanLLM:
    def __init__(self, *, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. Goldman needs it for the onboarding "
                "extractor (same key as HQ Hub uses for Atlas)."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def extract_with_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Send the prompt; force the model to call the given tool; return its input."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[{
                "name": tool_name,
                "description": "Submit the structured extraction.",
                "input_schema": tool_schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return dict(block.input)

        raise RuntimeError(
            f"Claude did not call the tool {tool_name!r}; "
            f"stop_reason={response.stop_reason!r}"
        )
