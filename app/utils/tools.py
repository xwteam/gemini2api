import json
import logging

logger = logging.getLogger(__name__)


def build_tool_prompt(prompt: str, tools: list[dict], tool_choice=None) -> str:
    if not tools:
        return prompt

    tool_descriptions = []
    for tool in tools:
        if isinstance(tool, dict):
            func = tool.get("function", tool)
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", func.get("input_schema", {}))
            tool_descriptions.append(
                f"- {name}: {desc}\n  Parameters: {json.dumps(params)}"
            )

    tools_text = "\n".join(tool_descriptions)

    choice_instruction = ""
    if tool_choice == "required":
        choice_instruction = "You MUST use one of the available tools. "
    elif tool_choice == "none":
        choice_instruction = "Do NOT use any tools. Respond with text only. "
    elif isinstance(tool_choice, dict):
        forced_name = tool_choice.get("function", {}).get("name", "")
        choice_instruction = f"You MUST use the tool: {forced_name}. "

    system_block = (
        f"Available tools:\n{tools_text}\n\n"
        f"{choice_instruction}"
        "When you need to use a tool, respond with ONLY a JSON object in this exact format:\n"
        '{"status": "tool_use", "tool_calls": [{"name": "tool_name", "arguments": {...}}]}\n\n'
        "When you want to respond with text, use this format:\n"
        '{"status": "text", "content": "your response here"}\n\n'
        "Respond with valid JSON only. No markdown, no extra text."
    )

    return f"{system_block}\n\nUser message: {prompt}"


def parse_tool_response(text: str) -> dict:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            status = parsed.get("status", "")
            if status == "tool_use" and "tool_calls" in parsed:
                return {"type": "tool_calls", "tool_calls": parsed["tool_calls"]}
            elif status == "text" and "content" in parsed:
                return {"type": "text", "content": parsed["content"]}
    except json.JSONDecodeError:
        pass

    return {"type": "text", "content": text}


def estimate_tokens(text: str) -> int:
    return len(text) // 4
