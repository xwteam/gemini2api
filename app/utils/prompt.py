import base64
import json
import re

_DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;,]+)(?:;[^,]*)?;base64,(?P<b64>.+)$", re.DOTALL)

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
    "application/pdf": "pdf",
    "text/plain": "txt",
}


def _flatten_tool_result_content(content) -> str:
    """tool_result 的 content 支持字符串或文本块数组两种形态，统一展平成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return "" if content is None else str(content)


def last_user_text(messages: list[dict]) -> str:
    """取最后一条 ``role == "user"`` 消息里的纯文本。

    专供「生图意图」判断使用。判断绝不能用 build_prompt_from_messages 拍平后的整段
    prompt：那里面还有 system 提示词、历史轮次以及 tool_result 正文（如某个工具返回
    "an image of a cat is stored at /tmp"），这些文本里的图片字样并不是用户在要图。
    一旦误判，调用方会把 has_tools 置 False —— 客户端声明的 tools 被静默丢弃。

    content 为数组时，取 type=="text" 的块；另外镜像 build_prompt_from_messages 里的
    兜底——block 带字符串 "text" 字段但 type 不是 tool_use / tool_result / image 时也纳入
    （例如某些客户端发送 {"text": "..."} 而不带 type）。刻意跳过 tool_use / tool_result /
    image 块：user 轮里的 tool_result 是工具输出，不是用户诉求；image 块正常没有 "text"，
    若出现也不该被当成正文。
    没有 user 消息时返回 ""（意图判断随即为 False，即保留 tools，安全的一侧）。
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                text = b.get("text")
                if b.get("type") == "text" and isinstance(text, str):
                    parts.append(text)
                elif b.get("type") not in ("tool_use", "tool_result", "image") and isinstance(text, str):
                    parts.append(text)
            return "\n".join(parts)
        return "" if content is None else str(content)
    return ""


def build_prompt_from_messages(messages: list[dict], system: str | None = None,
                               tool_prompt: str | None = None) -> str:
    parts = []
    if system:
        parts.append(f"System: {system}")

    for msg in messages:
        role = msg.get("role", "user")
        # content 显式为 None（OpenAI 的 assistant + tool_calls 消息常见形态）此前落入
        # f-string 直接渲染出 Python 字面量 "None"；改为 or "" 兜底成空串。
        content = msg.get("content") or ""

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    if isinstance(block.get("text"), str):
                        text_parts.append(block["text"])
                elif btype == "tool_use":
                    args = block.get("input")
                    try:
                        args_str = "" if args is None else json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_str = str(args)
                    # name 显式为 None 时也要落成空串，否则会渲染出 Python 字面量 "None"
                    text_parts.append(f"[Tool call: {block.get('name') or ''}({args_str})]")
                elif btype == "tool_result":
                    text_parts.append(f"[Tool result: {_flatten_tool_result_content(block.get('content'))}]")
                elif isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
            content = "\n".join(text_parts)
        elif not isinstance(content, str):
            # R5 硬化：content 目前各协议模型都只产出 str/list（这里理论上不可达），但一次
            # 模型放宽（如放宽成 dict/number）就会让 content 原样带着非 str 值往下走——下面
            # tool_calls 分支的 "\n".join([content, *call_parts]) 会直接 TypeError 变成 500。
            # 安全归一化成 str；不改变既有 str/list 输入的输出（本分支只在两者都不是时触发）。
            content = str(content)

        # OpenAI 的 assistant 消息把工具调用放在同级 tool_calls 字段（而非 content 块里），
        # 此前完全没有被渲染——模型看到一个 tool 结果却不知道是哪个工具调用产生的。
        # 渲染格式与上面 Anthropic 的 tool_use 分支保持字面一致：[Tool call: NAME(ARGS_JSON)]。
        # 注意 OpenAI 的 function.arguments 本身已经是 JSON 字符串，不能再 json.dumps 一次。
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            call_parts = []
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function")
                if not isinstance(fn, dict):
                    fn = {}
                name = fn.get("name") or ""
                args = fn.get("arguments")
                args_str = args if isinstance(args, str) else ("" if args is None else str(args))
                call_parts.append(f"[Tool call: {name}({args_str})]")
            if call_parts:
                content = "\n".join([content, *call_parts]) if content else "\n".join(call_parts)

        # developer：OpenAI 新版 SDK / Codex 用它代替 system 发说明（Codex 的权限、沙箱规则就在里面），
        # 过去没有这个分支、整段被丢掉。function：旧版 OpenAI 的工具结果角色。
        if role in ("system", "developer"):
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"Human: {content}")
        elif role in ("assistant", "model"):
            parts.append(f"Assistant: {content}")
        elif role in ("tool", "function"):
            parts.append(f"Tool result: {content}")

    if tool_prompt:
        parts.append(tool_prompt)

    return "\n\n".join(parts)


def _ext_for_mime(mime: str) -> str:
    return _MIME_EXT.get((mime or "").lower(), "bin")


def _parse_image_url(url: str, index: int) -> dict | None:
    """把一个 image_url 解析成 attachment 描述。
    data URI -> {data: bytes, filename, mime}
    http(s)  -> {url, filename, mime}
    其它忽略。
    """
    if not isinstance(url, str) or not url:
        return None
    m = _DATA_URI_RE.match(url.strip())
    if m:
        mime = m.group("mime").strip()
        try:
            data = base64.b64decode(m.group("b64"))
        except Exception:
            return None
        return {"data": data, "filename": f"image_{index}.{_ext_for_mime(mime)}", "mime": mime}
    if url.startswith("http://") or url.startswith("https://"):
        return {"url": url, "filename": f"image_{index}", "mime": ""}
    return None


def extract_attachments(messages: list[dict]) -> list[dict]:
    """从 messages 的 content 数组里提取图片/文件附件。
    支持 OpenAI（image_url）和 Claude（image.source）两种格式。
    返回 [{data|url, filename, mime}, ...]，无附件返回 []。
    纯文本路径不受影响（content 为 str 时直接跳过）。
    """
    attachments: list[dict] = []
    idx = 0
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            # OpenAI: {"type":"image_url","image_url":{"url":...}}
            if btype == "image_url":
                url = block.get("image_url", {})
                url = url.get("url") if isinstance(url, dict) else url
                att = _parse_image_url(url, idx)
                if att:
                    attachments.append(att)
                    idx += 1
            # Claude: {"type":"image","source":{"type":"base64","media_type":...,"data":...}}
            #         {"type":"image","source":{"type":"url","url":...}}
            elif btype == "image":
                src = block.get("source", {})
                if not isinstance(src, dict):
                    continue
                if src.get("type") == "base64":
                    mime = src.get("media_type", "image/png")
                    try:
                        data = base64.b64decode(src.get("data", ""))
                    except Exception:
                        continue
                    attachments.append({"data": data, "filename": f"image_{idx}.{_ext_for_mime(mime)}", "mime": mime})
                    idx += 1
                elif src.get("type") == "url":
                    att = _parse_image_url(src.get("url", ""), idx)
                    if att:
                        attachments.append(att)
                        idx += 1
    return attachments
