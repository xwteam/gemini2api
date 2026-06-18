import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.account_pool import account_pool as gemini_client
from app.core.stream import split_into_chunks
from app.models.gemini import (
    GeminiRequest,
    GeminiResponse,
    GeminiCandidate,
    GeminiContent,
    GeminiPart,
    GeminiUsageMetadata,
    GeminiModelInfo,
    GeminiModelList,
)
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gemini"])


def _parse_system(system_instruction) -> str | None:
    """system_instruction 可能是 str 或 GeminiContent，统一取文本。"""
    if system_instruction is None:
        return None
    if isinstance(system_instruction, str):
        return system_instruction or None
    parts = getattr(system_instruction, "parts", None)
    if parts:
        texts = [p.text for p in parts if getattr(p, "text", None)]
        if texts:
            return " ".join(texts)
    return None


def _parse_contents(contents):
    """从 Gemini contents 解析出 messages 和 attachments（inline_data）。"""
    messages = []
    attachments = []
    idx = 0
    for content in contents:
        role = content.role
        text_parts = [part.text for part in content.parts if part.text]
        if text_parts:
            messages.append({"role": role, "content": " ".join(text_parts)})
        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and isinstance(inline, dict):
                import base64
                mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                raw = inline.get("data", "")
                try:
                    data = base64.b64decode(raw) if isinstance(raw, str) else raw
                except Exception:
                    continue
                ext = mime.split("/")[-1] if "/" in mime else "bin"
                attachments.append({"data": data, "filename": f"image_{idx}.{ext}", "mime": mime})
                idx += 1
    return messages, attachments


@router.get("/models")
async def list_models():
    """List available Gemini models."""
    models = [
        GeminiModelInfo(
            name="models/gemini-2.0-flash-exp",
            display_name="Gemini 2.0 Flash Experimental",
            description="Fast and efficient model for general tasks",
        ),
        GeminiModelInfo(
            name="models/gemini-1.5-pro",
            display_name="Gemini 1.5 Pro",
            description="Advanced model for complex reasoning",
        ),
        GeminiModelInfo(
            name="models/gemini-1.5-flash",
            display_name="Gemini 1.5 Flash",
            description="Fast model for quick responses",
        ),
    ]
    return JSONResponse(content=GeminiModelList(models=models).model_dump())


@router.post("/models/{model}:generateContent")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def generate_content(model: str, req: GeminiRequest, request: Request):
    """Generate content using Gemini API (non-streaming)."""
    if model.startswith("models/"):
        model = model[7:]

    messages, attachments = _parse_contents(req.contents)
    system = _parse_system(req.system_instruction)
    prompt = build_prompt_from_messages(messages, system=system)

    has_tools = False
    if req.tools and not is_image_generation_intent(prompt):
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend([fd.model_dump() for fd in tool.function_declarations])
        if function_declarations:
            has_tools = True
            prompt = build_tool_prompt(prompt, function_declarations)

    try:
        result = await gemini_client.generate(prompt, model, "", attachments)
    except (RuntimeError, ValueError) as e:
        return JSONResponse(
            status_code=500 if "retry" in str(e).lower() else 400,
            content={"error": {"message": str(e), "type": "api_error"}},
        )

    response_text = result.get("text", "")

    # 工具调用：解析成 Gemini 原生 functionCall part（而非把工具 JSON 当文本塞回去）
    tool_parts = []
    if has_tools:
        parsed = parse_tool_response(response_text)
        if isinstance(parsed, dict):
            if parsed.get("type") == "tool_calls":
                for tc in parsed["tool_calls"]:
                    tool_parts.append({"functionCall": {
                        "name": tc["name"],
                        "args": tc.get("arguments", {}),
                    }})
                response_text = ""  # 工具调用时不再带文本
            else:
                response_text = parsed.get("content", response_text)

    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(response_text)

    # parts：图片在前 + 文本。inlineData（Gemini 原生 base64）给能解析的客户端，
    # 同时图片本地托管 URL 排在文字前面（图在前），方便不渲染 inlineData 的客户端拿到可点链接。
    gen_images = result.get("images") or []
    base = str(request.base_url).rstrip("/")
    text_part = response_text
    if gen_images and base:
        urls = "\n".join(f"![generated image]({base}/images/{im['id']})"
                         for im in gen_images if im.get("id"))
        if urls:
            text_part = (urls + "\n" + response_text.strip()) if response_text.strip() else urls
    # 工具调用 part 优先；否则文本 part + 图片
    if tool_parts:
        parts = tool_parts
        finish = "STOP"
    else:
        parts = [{"text": text_part}]
        for im in gen_images:
            parts.append({"inlineData": {"mimeType": im.get("mime", "image/png"), "data": im["b64"]}})
        finish = "STOP"

    gemini_response = {
        "candidates": [{
            "content": {"parts": parts, "role": "model"},
            "finishReason": finish,
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": prompt_tokens + completion_tokens,
        },
    }

    return JSONResponse(content=gemini_response)


@router.post("/models/{model}:streamGenerateContent")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def stream_generate_content(model: str, req: GeminiRequest, request: Request):
    """Generate content using Gemini API (streaming with chunked JSON)."""
    if model.startswith("models/"):
        model = model[7:]

    messages, attachments = _parse_contents(req.contents)
    system = _parse_system(req.system_instruction)
    prompt = build_prompt_from_messages(messages, system=system)

    has_tools = False
    if req.tools and not is_image_generation_intent(prompt):
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend([fd.model_dump() for fd in tool.function_declarations])
        if function_declarations:
            has_tools = True
            prompt = build_tool_prompt(prompt, function_declarations)

    async def stream_generator() -> AsyncGenerator[str, None]:
        def _chunk(text: str) -> str:
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "index": 0,
                }]
            }) + "\n"

        prompt_tokens = estimate_tokens(prompt)
        response_text = ""

        # 有工具/附件：需完整文本，走非流式收集后切片（零回归）
        if has_tools or attachments:
            try:
                result = await gemini_client.generate(prompt, model, "", attachments)
            except Exception as e:
                yield json.dumps({"error": {"message": str(e), "type": "api_error"}}) + "\n"
                return
            response_text = result.get("text", "")
            if has_tools:
                parsed = parse_tool_response(response_text)
                if isinstance(parsed, dict):
                    response_text = parsed.get("content", response_text)
            async for chunk in split_into_chunks(response_text):
                yield _chunk(chunk)
        else:
            # === 真流式路径（纯文本）===
            try:
                async for evt in gemini_client.generate_stream(prompt, model, "", attachments):
                    if evt.get("type") == "delta":
                        delta = evt.get("text", "")
                        if evt.get("_replace"):
                            response_text = delta
                        else:
                            response_text += delta
                        if delta:
                            yield _chunk(delta)
                    elif evt.get("type") == "final":
                        response_text = evt.get("text", response_text)
            except Exception as e:
                # generate_stream 在 HTTP>=400 时抛 HTTPStatusError（非 RuntimeError/ValueError 子类），
                # 故这里捕获 Exception，与 openai/claude 真流式路径一致，避免击穿生成器
                yield json.dumps({"error": {"message": str(e), "type": "api_error"}}) + "\n"
                return

        completion_tokens = estimate_tokens(response_text)

        final_chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": ""}],
                        "role": "model",
                    },
                    "finish_reason": "STOP",
                    "index": 0,
                }
            ],
            "usage_metadata": {
                "prompt_token_count": prompt_tokens,
                "candidates_token_count": completion_tokens,
                "total_token_count": prompt_tokens + completion_tokens,
            },
        }
        yield json.dumps(final_chunk) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/json")
