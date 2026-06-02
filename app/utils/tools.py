import json
import re
import logging

logger = logging.getLogger(__name__)


# 明确的图像生成意图关键词。收窄到「确实在要图」的表达，避免误判
# （如"生成一份报告""create a plan"不该触发生图）。
# 中文：必须是画图/生成图片类；英文：必须含 image/picture/photo/drawing 等图像词。
_IMAGE_INTENT_PATTERNS = (
    "画一", "画个", "画张", "画幅", "画副", "帮我画", "给我画", "画图", "画一张", "画一幅",
    "画个图", "画张图", "画幅图", "画一只", "画只", "画头", "画条",
    "生成图片", "生成一张图", "生成图像", "生成一幅", "生成一张照片", "生成张图", "生成个图",
    "生成海报", "生成插画", "生成一张海报",
    "做一张图", "做个图", "做张图", "做一张海报", "做个海报", "做张海报", "做一张照片",
    "设计一张海报", "设计海报", "设计一张图", "设计张海报", "设计个海报", "设计一幅",
    "画一张海报", "画张海报", "画个海报", "画海报",
    "绘制", "绘一", "画出", "出一张图", "出张图", "p一张", "p个图", "做幅",
    "一张海报", "张海报", "幅海报", "来张图", "来一张图", "来个图",
    "draw a", "draw an", "draw me", "generate an image", "generate a picture",
    "generate an picture", "generate a poster", "create an image", "create a picture",
    "create a photo", "create a poster", "design a poster", "make an image",
    "make a picture", "make a poster", "an image of", "a picture of", "a photo of",
    "a poster of", "image of a", "picture of a", "poster of",
)


def is_image_generation_intent(text: str) -> bool:
    """判断用户消息是否是明确的「生成图片」意图。
    用于：即使请求带 tools（agent 场景），只要是生图意图就跳过工具模拟、直接走生图。
    收窄匹配避免误判：单独的"生成/create/generate"不算，必须是明确的画图/生成图片表达。
    """
    if not text:
        return False
    low = text.lower()
    return any(p in low for p in _IMAGE_INTENT_PATTERNS)


# 宽松版：图像名词 + 产出动词的组合。用于「流式分流」兜底——
# 误判只是让该请求走非流式 buffered（慢一点点），代价极小；
# 但能兜住关键词没精确覆盖的生图表达，避免漏网走真流式导致图在文字后。
_IMG_NOUNS = ("图", "图片", "图像", "海报", "插画", "照片", "壁纸", "logo", "头像", "封面",
              "image", "picture", "poster", "photo", "drawing", "illustration", "wallpaper", "avatar")
_IMG_VERBS = ("画", "生成", "绘", "做", "设计", "出", "整", "来", "搞", "弄", "制作", "帮我", "给我",
              "想要", "要", "想", "需要", "求", "来一", "来个", "来张",
              "draw", "generate", "create", "make", "design", "render", "want", "need")


def maybe_image_generation_intent(text: str) -> bool:
    """宽松判断是否可能是生图意图（用于流式分流兜底，宁可多走 buffered 不漏网）。"""
    if not text:
        return False
    if is_image_generation_intent(text):
        return True
    low = text.lower()
    has_noun = any(n in low for n in _IMG_NOUNS)
    has_verb = any(v in low for v in _IMG_VERBS)
    return has_noun and has_verb


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
                f"- {name}: {desc}\n  Parameters: {json.dumps(params, ensure_ascii=False)}"
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
        f"You have access to the following tools:\n{tools_text}\n\n"
        f"{choice_instruction}\n"
        "To CALL a tool, output a JSON object EXACTLY like this (tool_calls MUST be an array):\n"
        '{"status": "tool_use", "tool_calls": [{"name": "<tool_name>", "arguments": {<args>}}]}\n\n'
        "To reply with plain text instead, output:\n"
        '{"status": "text", "content": "<your reply>"}\n\n'
        "STRICT JSON RULES (follow exactly, or the call fails):\n"
        '1. Use double quotes for all keys and string values. Escape inner quotes as \\" and newlines as \\n.\n'
        "2. \"tool_calls\" is ALWAYS a JSON array [ ... ], even for a single call.\n"
        "3. \"arguments\" is a JSON object with the tool's parameters.\n"
        "4. Output ONLY the JSON (a ```json code block is allowed, nothing else).\n\n"
        "Example (calling a tool named run with a command argument):\n"
        '{"status": "tool_use", "tool_calls": [{"name": "run", "arguments": {"command": "ls -la"}}]}\n\n'
        "Example (plain text reply):\n"
        '{"status": "text", "content": "Hello, how can I help?"}'
    )

    return f"{system_block}\n\nUser message: {prompt}"


def _strip_code_fence(text: str) -> str:
    """剥离 markdown 代码块包裹：```json ... ``` 或 ``` ... ```。"""
    s = text.strip()
    if s.startswith("```"):
        # 去掉首行 ``` 或 ```json
        s = re.sub(r"^```[a-zA-Z0-9]*\s*\n?", "", s)
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _extract_json_object(text: str) -> str | None:
    """从文本中提取第一个完整的 JSON 对象子串（括号深度扫描，处理字符串与转义）。
    用于模型在 JSON 前后夹带了解释文字的情况。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _normalize_tool_calls(tc) -> list | None:
    """把 tool_calls 归一成 [{"name","arguments"}] 列表；容忍单对象、容忍 arguments 是字符串。"""
    if isinstance(tc, dict):
        tc = [tc]
    if not isinstance(tc, list):
        return None
    out = []
    for item in tc:
        if not isinstance(item, dict):
            continue
        # 兼容 OpenAI 风格 {"function":{"name","arguments"}} 和简单 {"name","arguments"}
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        out.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
    return out or None


def _try_parse(text: str) -> dict | None:
    """尝试把一段文本解析成工具/文本结构，失败返回 None。"""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status", "")
    # 有 tool_calls 即视为工具调用（容忍缺 status）
    if "tool_calls" in parsed or status == "tool_use":
        calls = _normalize_tool_calls(parsed.get("tool_calls"))
        if calls:
            return {"type": "tool_calls", "tool_calls": calls}
    if status == "text" and "content" in parsed:
        return {"type": "text", "content": parsed["content"]}
    # 整段就是一个工具调用对象 {"name":...,"arguments":...}
    if "name" in parsed and ("arguments" in parsed or "function" in parsed):
        calls = _normalize_tool_calls(parsed)
        if calls:
            return {"type": "tool_calls", "tool_calls": calls}
    return None


def parse_tool_response(text: str) -> dict:
    """解析模型返回的（提示词模拟的）工具调用文本，多层容错。
    Gemini Web 非原生工具模型，常输出被 markdown 包裹/夹带文字/轻微畸形的 JSON，
    逐层尝试挽救；都失败时不把畸形 JSON 当正常文本透传。"""
    if not isinstance(text, str) or not text.strip():
        return {"type": "text", "content": text or ""}

    # 1. 直接解析
    r = _try_parse(text)
    if r:
        return r
    # 2. 剥离 markdown 代码块后解析
    stripped = _strip_code_fence(text)
    if stripped != text:
        r = _try_parse(stripped)
        if r:
            return r
    # 3. 从文本中提取第一个完整 JSON 对象后解析
    candidate = _extract_json_object(stripped)
    if candidate:
        r = _try_parse(candidate)
        if r:
            return r

    # 4. 都失败：判断是否是「残缺/畸形的工具调用 JSON」——若是，不把垃圾透传给客户端
    looks_like_tool = ('"tool_use"' in text or '"tool_calls"' in text
                       or ('"name"' in text and '"arguments"' in text))
    if looks_like_tool:
        logger.warning(f"工具调用 JSON 解析失败，畸形片段不透传: {text[:120]!r}")
        return {"type": "text",
                "content": "（模型返回的工具调用格式有误，已忽略。请重试或换用 gemini-flash。）"}

    # 普通文本（非工具意图）原样返回
    return {"type": "text", "content": text}


def estimate_tokens(text: str) -> int:
    return len(text) // 4
