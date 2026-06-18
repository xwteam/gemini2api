import time
import uuid
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.account_pool import account_pool as gemini_client
from app.core.stream import split_into_chunks, format_sse
from app.models.claude import (
    ClaudeRequest, ClaudeResponse, ContentBlock, ClaudeUsage,
    ClaudeModelInfo, ClaudeModelList,
)
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages, extract_attachments
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)
# router：对话主入口（messages），同时挂在 /claude/v1 和裸 /v1（开箱即用）
router = APIRouter(tags=["Claude"])
# models_router：模型列表/详情，仅挂在 /claude/v1，避免裸 /v1/models 与 OpenAI 撞车
models_router = APIRouter(tags=["Claude"])


@models_router.get("/models")
async def list_models():
    models = gemini_client.models
    data = [
        ClaudeModelInfo(
            id=m,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            display_name=m,
        )
        for m in models
    ]
    return ClaudeModelList(data=data)


@models_router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    if model_id not in gemini_client.models:
        return JSONResponse(
            status_code=404,
            content={"type": "error", "error": {"type": "not_found", "message": f"Model {model_id} not found"}},
        )
    return ClaudeModelInfo(
        id=model_id,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        display_name=model_id,
    )


@router.post("/messages")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def create_message(req: ClaudeRequest, request: Request):
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    attachments = extract_attachments(messages_raw)

    has_tools = bool(req.tools)
    # 生图意图优先：带 tools 但明确生图意图时跳过工具模拟，直接生图（否则生图被压制）
    if has_tools and is_image_generation_intent(prompt):
        has_tools = False
        logger.info("检测到生图意图，跳过工具调用模拟，直接生图")
    if has_tools:
        tools_raw = [
            {"name": t.name, "description": t.description, "parameters": t.input_schema}
            for t in req.tools
        ]
        choice = None
        if req.tool_choice:
            tc_type = req.tool_choice.get("type", "auto")
            if tc_type == "any":
                choice = "required"
            elif tc_type == "tool":
                choice = {"function": {"name": req.tool_choice.get("name", "")}}
            else:
                choice = tc_type
        prompt = build_tool_prompt(prompt, tools_raw, choice)

    if req.stream:
        return StreamingResponse(
            _stream_claude(prompt, req.model, has_tools, attachments),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, req.model, "", attachments)
    except (RuntimeError, ValueError) as e:
        return JSONResponse(
            status_code=500 if "retry" in str(e).lower() else 400,
            content={"type": "error", "error": {"type": "api_error", "message": str(e)}},
        )

    text = result.get("text", "")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    if has_tools:
        parsed = parse_tool_response(text)
        if parsed["type"] == "tool_calls":
            blocks = []
            for tc in parsed["tool_calls"]:
                blocks.append(ContentBlock(
                    type="tool_use",
                    id=f"toolu_{uuid.uuid4().hex[:8]}",
                    name=tc["name"],
                    input=tc.get("arguments", {}),
                ))
            return ClaudeResponse(
                id=msg_id,
                model=req.model,
                content=blocks,
                stop_reason="tool_use",
                usage=ClaudeUsage(
                    input_tokens=estimate_tokens(prompt),
                    output_tokens=estimate_tokens(text),
                ),
            )
        text = parsed.get("content", text)

    # AI 生成图片：作为 Claude 原生 image block。图片块排在文字块前面（图在前）。
    # 优先 url source（本地托管，客户端可渲染），无 id 时降级 base64 source。
    base = str(request.base_url).rstrip("/")
    image_blocks = []
    for im in (result.get("images") or []):
        if im.get("id") and base:
            image_blocks.append(ContentBlock(type="image", source={
                "type": "url", "url": f"{base}/images/{im['id']}",
            }))
        else:
            image_blocks.append(ContentBlock(type="image", source={
                "type": "base64", "media_type": im.get("mime", "image/png"), "data": im["b64"],
            }))
    blocks = list(image_blocks)
    # 有文字才加文字块（图在前，文字在后；纯生图无描述时不加空块）
    if text.strip() or not image_blocks:
        blocks.append(ContentBlock(type="text", text=text))

    return ClaudeResponse(
        id=msg_id,
        model=req.model,
        content=blocks,
        stop_reason="end_turn",
        usage=ClaudeUsage(
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
        ),
    )


@router.post("/messages/count_tokens")
async def count_tokens(req: ClaudeRequest):
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    count = estimate_tokens(prompt)
    return {"input_tokens": count}


async def _stream_claude(prompt: str, model: str, has_tools: bool, attachments=None) -> AsyncGenerator[str, None]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    # 有工具/附件：需完整文本，走非流式收集后切片（零回归）
    if has_tools or attachments:
        async for sse in _stream_claude_buffered(prompt, model, has_tools, attachments, msg_id):
            yield sse
        return

    # === 真流式路径（纯文本）===
    yield format_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "usage": {"input_tokens": estimate_tokens(prompt), "output_tokens": 0},
        },
    })
    yield format_sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    full_text = ""
    try:
        async for evt in gemini_client.generate_stream(prompt, model, "", attachments):
            if evt.get("type") == "delta":
                delta = evt.get("text", "")
                if evt.get("_replace"):
                    full_text = delta
                else:
                    full_text += delta
                if delta:
                    yield format_sse({
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": delta},
                    })
            elif evt.get("type") == "final":
                full_text = evt.get("text", full_text)
    except Exception as e:
        yield format_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": f"Error: {e}"},
        })

    yield format_sse({"type": "content_block_stop", "index": 0})
    yield format_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": estimate_tokens(full_text)},
    })
    yield format_sse({"type": "message_stop"})


async def _stream_claude_buffered(prompt: str, model: str, has_tools: bool, attachments, msg_id: str) -> AsyncGenerator[str, None]:
    """非流式收集 + 切片：用于有工具调用/附件的场景。"""
    try:
        result = await gemini_client.generate(prompt, model, "", attachments)
    except Exception as e:
        yield format_sse({"type": "error", "error": {"type": "api_error", "message": str(e)}})
        return

    text = result.get("text", "")

    yield format_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "usage": {"input_tokens": estimate_tokens(prompt), "output_tokens": 0},
        },
    })

    if has_tools:
        parsed = parse_tool_response(text)
        if parsed["type"] == "tool_calls":
            for i, tc in enumerate(parsed["tool_calls"]):
                block_id = f"toolu_{uuid.uuid4().hex[:8]}"
                yield format_sse({
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {"type": "tool_use", "id": block_id, "name": tc["name"], "input": {}},
                })
                args_str = json.dumps(tc.get("arguments", {}))
                yield format_sse({
                    "type": "content_block_delta",
                    "index": i,
                    "delta": {"type": "input_json_delta", "partial_json": args_str},
                })
                yield format_sse({"type": "content_block_stop", "index": i})

            yield format_sse({
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": estimate_tokens(text)},
            })
            yield format_sse({"type": "message_stop"})
            return
        text = parsed.get("content", text)

    yield format_sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    async for word in split_into_chunks(text):
        yield format_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": word},
        })

    yield format_sse({"type": "content_block_stop", "index": 0})

    yield format_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": estimate_tokens(text)},
    })

    yield format_sse({"type": "message_stop"})

