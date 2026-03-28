"""Convert Anthropic message format to OpenAI-compatible training format.

The OpenAI format is what Unsloth/transformers expects for chat fine-tuning
with tool calling. vLLM's qwen3_coder parser handles the native token mapping.
"""

from __future__ import annotations

import json
import uuid


def _extract_text(content: str | list[dict]) -> str:
    """Extract plain text from Anthropic content (string or content blocks)."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts)


def _extract_tool_uses(content: list[dict]) -> list[dict]:
    """Extract tool_use blocks from Anthropic content blocks."""
    if isinstance(content, str):
        return []
    return [block for block in content if block.get("type") == "tool_use"]


def _extract_tool_results(content: list[dict]) -> list[dict]:
    """Extract tool_result blocks from Anthropic content blocks."""
    if isinstance(content, str):
        return []
    return [block for block in content if block.get("type") == "tool_result"]


def convert_conversation(
    system_prompt: str,
    anthropic_messages: list[dict],
) -> list[dict]:
    """Convert an Anthropic-format conversation to OpenAI messages format.

    Input (Anthropic format):
        - User: {"role": "user", "content": "text"} or {"role": "user", "content": [blocks...]}
        - Assistant: {"role": "assistant", "content": [{"type": "text", ...}, {"type": "tool_use", ...}]}
        - Tool result: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}

    Output (OpenAI format):
        - System: {"role": "system", "content": "..."}
        - User: {"role": "user", "content": "..."}
        - Assistant text: {"role": "assistant", "content": "..."}
        - Assistant tool call: {"role": "assistant", "content": null, "tool_calls": [...]}
        - Tool result: {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
    """
    openai_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Build a lookup from tool_use id -> tool name so tool_result messages
    # can reference the correct function name.
    tool_id_to_name: dict[str, str] = {}
    for msg in anthropic_messages:
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "tool_use":
                    tool_id_to_name[block["id"]] = block["name"]

    for msg in anthropic_messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "user":
            # Check if this is a tool_result message
            tool_results = _extract_tool_results(content) if isinstance(content, list) else []

            if tool_results:
                # Emit one {"role": "tool", ...} per tool_result block
                for tr in tool_results:
                    tool_call_id = tr.get("tool_use_id", str(uuid.uuid4()))
                    tool_name = tool_id_to_name.get(tool_call_id, "unknown")
                    # Content may be a string or nested content blocks
                    tr_content = tr.get("content", "")
                    if isinstance(tr_content, list):
                        tr_content = _extract_text(tr_content)
                    elif not isinstance(tr_content, str):
                        tr_content = json.dumps(tr_content)
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": tr_content,
                    })

                # If there are also plain text blocks alongside tool_results,
                # emit them as a separate user message.
                text = _extract_text(content)
                if text.strip():
                    openai_messages.append({"role": "user", "content": text})
            else:
                # Plain user message
                text = _extract_text(content)
                openai_messages.append({"role": "user", "content": text})

        elif role == "assistant":
            tool_uses = _extract_tool_uses(content) if isinstance(content, list) else []
            text = _extract_text(content)

            if tool_uses:
                # Build OpenAI-format tool_calls list
                tool_calls = []
                for tu in tool_uses:
                    args = tu.get("input", {})
                    if isinstance(args, dict):
                        args_str = json.dumps(args)
                    else:
                        args_str = str(args)
                    tool_calls.append({
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": args_str,
                        },
                    })

                assistant_msg: dict = {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                }
                # If there is text alongside tool calls, include it;
                # otherwise set content to null.
                if text.strip():
                    assistant_msg["content"] = text
                else:
                    assistant_msg["content"] = None

                openai_messages.append(assistant_msg)
            else:
                # Text-only assistant message
                openai_messages.append({"role": "assistant", "content": text})

    return openai_messages


def format_training_example(system_prompt: str, anthropic_messages: list[dict]) -> dict:
    """Format a complete training example as a dict with 'messages' key."""
    return {"messages": convert_conversation(system_prompt, anthropic_messages)}
