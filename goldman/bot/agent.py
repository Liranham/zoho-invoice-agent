"""Multi-turn Claude tool-loop for the Goldman bot."""

from __future__ import annotations

from goldman.bot.tools import TOOL_SCHEMAS, execute_tool


def run_agent(
    *,
    claude,
    model: str,
    system: str,
    messages: list,
    ctx,
    max_iterations: int = 5,
    max_tokens: int = 2048,
) -> str:
    """Run a tool-using conversation until Claude returns plain text.

    messages is the running conversation (assistant + user blocks).
    Returns the final assistant text. Caller appends both directions to
    their own log.
    """
    working = list(messages)

    for _ in range(max_iterations):
        resp = claude.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=working,
            tools=TOOL_SCHEMAS,
        )

        # Did Claude finish with text?
        if resp.stop_reason != "tool_use":
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""

        # Tool use — append Claude's request, execute, append tool_result.
        working.append({
            "role": "assistant",
            "content": [
                {"type": b.type,
                 **({"text": b.text} if b.type == "text" else {}),
                 **({"id": b.id, "name": b.name, "input": b.input}
                    if b.type == "tool_use" else {})}
                for b in resp.content
            ],
        })

        tool_results = []
        for b in resp.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            try:
                result_text = execute_tool(
                    ctx=ctx, name=b.name, arguments=dict(b.input),
                )
            except Exception as e:
                result_text = f"Tool error: {e}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": result_text,
            })

        working.append({"role": "user", "content": tool_results})

    return "(Goldman: hit the tool-iteration cap; please try again.)"
