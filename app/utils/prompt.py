def build_prompt_from_messages(messages: list[dict], system: str | None = None) -> str:
    parts = []
    if system:
        parts.append(f"System: {system}")

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif "text" in block:
                        text_parts.append(block["text"])
            content = "\n".join(text_parts)

        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"Human: {content}")
        elif role in ("assistant", "model"):
            parts.append(f"Assistant: {content}")
        elif role == "tool":
            parts.append(f"Tool result: {content}")

    return "\n\n".join(parts)
