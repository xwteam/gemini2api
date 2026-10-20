import time
import uuid
import json
import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.account_pool import account_pool as gemini_client
from app.core.access_context import ensure_model_allowed, filter_models_for_access_key
from app.core.gemini_client import HTTPStatusError, classify_error
from app.core.stream import split_into_chunks, iter_with_keepalive, SSE_KEEPALIVE_FRAME, sse_keepalive_during
from app.models.claude import (
    ClaudeRequest, ClaudeResponse, ContentBlock, ClaudeUsage,
    ClaudeModelInfo, ClaudeModelList,
)
from app.routers.openai import _images_to_markdown
from app.utils.tools import build_tool_prompt, parse_tool_response_with_retry, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages, extract_attachments, last_user_text
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)


def _claude_sse(data: dict) -> str:
    """Anthropic 流式是 event+data 两行制（官方 SDK 按 event 字段分发），与 OpenAI 的纯 data 帧不同。"""
    return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"


def _apply_model_whitelist(models: list[str]) -> list[str]:
    """按 MODEL_WHITELIST（逗号分隔）过滤模型列表；为空表示不过滤（放行全部）。
    让文档化的 MODEL_WHITELIST 真正生效——只暴露白名单内的模型。"""
    raw = (settings.model_whitelist or "").strip()
    if not raw:
        return models
    allowed = {m.strip() for m in raw.split(",") if m.strip()}
    if not allowed:
        return models
    return [m for m in models if m in allowed]


# router：对话主入口（messages），同时挂在 /claude/v1 和裸 /v1（开箱即用）
router = APIRouter(tags=["Claude"])
# models_router：模型列表/详情，仅挂在 /claude/v1，避免裸 /v1/models 与 OpenAI 撞车
models_router = APIRouter(tags=["Claude"])


@models_router.get("/models")
async def list_models():
    models = filter_models_for_access_key(_apply_model_whitelist(list(gemini_client.models)))
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
    # 与 /models 列表保持一致：被白名单挡掉的模型也视为 not found
    if model_id not in filter_models_for_access_key(_apply_model_whitelist(list(gemini_client.models))):
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

    # gem 模型解析：命中则取出 gem_id/account_id，并把对话模型换成 base_model
    resolved_model = req.model
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(resolved_model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            resolved_model = gem_info.get("base_model") or "gemini-pro"

    ensure_model_allowed(req.model, resolved_model)

    has_tools = bool(req.tools)
    # 生图意图优先：带 tools 但明确生图意图时跳过工具模拟，直接生图（否则生图被压制）。
    # 只看最后一轮用户消息：整段 prompt 含 system 提示词与 tool_result 正文，
    # 拿它判断会把引用到的图片字样当成用户要图，从而静默丢掉客户端 tools 并改走真流式。
    if has_tools and is_image_generation_intent(last_user_text(messages_raw)):
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
            _stream_claude(prompt, resolved_model, has_tools, attachments, req.model, gem_id, gem_account_id,
                          request=request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                              gem_id=gem_id, account_id=gem_account_id)
    except (RuntimeError, ValueError, HTTPStatusError) as e:
        status, err_type, retry_after = classify_error(e)
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        return JSONResponse(
            status_code=status,
            content={"type": "error", "error": {"type": err_type, "message": str(e)}},
            headers=headers,
        )

    text = result.get("text", "")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    if has_tools:
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                             gem_id=gem_id, account_id=gem_account_id)
            return r.get("text", "")

        parsed = await parse_tool_response_with_retry(text, _regenerate_for_tools)
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

    # AI 生成图片：Anthropic assistant 侧 content-block union 没有 image 成员——真实 SDK
    # 严格校验会直接报 35 个错误，宽松路径会把它默默转成 text=None 的 TextBlock，
    # isinstance(block, TextBlock) 的客户端直接崩，按 type 过滤的客户端整块丢弃，两种情况
    # 下图片都到不了用户手里（defect ⑥）。改用 openai.py 既有做法：图片渲染成 markdown
    # 嵌进文字块（图在前，文字在后），不单开 image 块。
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md
    # 上游回答是空字符串且无图时，不能发一个 text:"" 的空文本块，也不能让 content
    # 整体变成 []（defect ⑩）——两者都有客户端会踩坑（遍历 content 假设至少一块非空）。
    # 用单空格占位，恰好一块，不改变非空/纯空白文本的既有行为。
    blocks = [ContentBlock(type="text", text=text if text else " ")]

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
    ensure_model_allowed(req.model)
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    count = estimate_tokens(prompt)
    return {"input_tokens": count}


async def _stream_claude(prompt: str, model: str, has_tools: bool, attachments=None, display_model: str = "", gem_id=None, account_id=None, request=None) -> AsyncGenerator[str, None]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    model_name = display_model or model

    # 有工具/附件：需完整文本，走非流式收集后切片（零回归）
    if has_tools or attachments:
        async for sse in _stream_claude_buffered(prompt, model, has_tools, attachments, msg_id, model_name, gem_id, account_id,
                                                 request=request):
            yield sse
        return

    # === 真流式路径（纯文本）===
    yield _claude_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model_name,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": estimate_tokens(prompt), "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "service_tier": "standard",
            },
        },
    })
    yield _claude_sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": "", "citations": None},
    })

    full_text = ""
    final_images = []
    try:
        async for _kind, evt in iter_with_keepalive(
            gemini_client.generate_stream(prompt, model, "", attachments,
                                          gem_id=gem_id, account_id=account_id)):
            if _kind == "ping":
                yield SSE_KEEPALIVE_FRAME
                continue
            if evt.get("type") == "delta":
                # generate_stream 现在是严格 append-only（不再发 _replace），delta 总是新增尾部
                delta = evt.get("text", "")
                full_text += delta
                if delta:
                    yield _claude_sse({
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": delta},
                    })
            elif evt.get("type") == "final":
                # final.text 是过滤完占位串的完整文本，可能比已流出的 full_text 多出
                # （流式时被 hold 住的尾部）。补发缺失尾部，保证客户端拿到完整内容。
                final_text = evt.get("text", full_text)
                if final_text.startswith(full_text) and len(final_text) > len(full_text):
                    tail = final_text[len(full_text):]
                    full_text = final_text
                    if tail:
                        yield _claude_sse({
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": tail},
                        })
                else:
                    full_text = final_text
                final_images = evt.get("images") or []
    except Exception as e:
        # 真实上游失败绝不能伪装成正常回答：不能落回下面的
        # content_block_stop/message_delta(stop_reason=end_turn)/message_stop 正常收尾——
        # 否则官方 SDK 会看到 stop_reason='end_turn' 且没有异常，client 的重试/故障转移/退避
        # 永远不会触发，错误文本还会被当成模型说的话存进对话历史。改发标准 Anthropic error
        # 事件并直接结束流，与下面 _stream_claude_buffered 的既有正确写法（第 289-293 行左右）对齐。
        _, err_type, _retry_after = classify_error(e)
        yield _claude_sse({"type": "content_block_stop", "index": 0})
        yield _claude_sse({"type": "error", "error": {"type": err_type, "message": str(e)}})
        return

    if final_images:
        # 生成图片只在 final 事件才知道，此时文字已经流出去了，只能追加一条 delta
        # 补进同一个文本块（index 0）——绝不能单开 image 块把文字块挤出 index 0，
        # 否则 SDK 客户端会拿到未知 discriminator（defect ⑥）。
        md = _images_to_markdown(final_images, request)
        if full_text.strip():
            appended = "\n" + md
            full_text = full_text + appended
        else:
            appended = md
            full_text = md
        yield _claude_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": appended},
        })
    elif not full_text:
        # 上游回答真的是空字符串、也没有生图时，此前不发一个 delta——content_block_start
        # (text:"") 之后直接 content_block_stop，零个 delta。buffered 路径（同一个
        # defect ⑩）已经用单空格占位补上了这个缺口；这里是真流式侧的对称缺口，客户端遍历
        # delta 流、假设至少收到一块非空内容的假设一样会被打破。补发一个单空格 delta，
        # 不改变非空回答/有生图场景（上面 if 分支已经保证非空）的既有行为。
        full_text = " "
        yield _claude_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": full_text},
        })

    yield _claude_sse({"type": "content_block_stop", "index": 0})
    yield _claude_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {
            "output_tokens": estimate_tokens(full_text),
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "service_tier": "standard",
        },
    })
    yield _claude_sse({"type": "message_stop"})


async def _stream_claude_buffered(prompt: str, model: str, has_tools: bool, attachments, msg_id: str, display_model: str = "", gem_id=None, account_id=None, request=None) -> AsyncGenerator[str, None]:
    """非流式收集 + 切片：用于有工具调用/附件的场景。"""
    model_name = display_model or model
    gen_task = asyncio.create_task(gemini_client.generate(prompt, model, "", attachments,
                                                          gem_id=gem_id, account_id=account_id))
    try:
        async for ping in sse_keepalive_during(gen_task):
            yield ping
    except BaseException:          # GeneratorExit / CancelledError on client disconnect
        gen_task.cancel()
        if gen_task.done() and not gen_task.cancelled():
            gen_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
        raise
    try:
        result = gen_task.result()
    except Exception as e:
        # 硬编码 "api_error" 会绕开 classify_error 的统一映射（929a049），buffered 流式路径
        # （Claude Code 走的这条）跟非流式/真流式给出不一致的 error type——同一个 pool-busy
        # 失败，非流式吐 overloaded_error，这里却吐 api_error，客户端的重试/故障转移策略
        # 因 type 不同而表现不一致。
        _, err_type, _retry_after = classify_error(e)
        yield _claude_sse({"type": "error", "error": {"type": err_type, "message": str(e)}})
        return

    text = result.get("text", "")

    yield _claude_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model_name,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": estimate_tokens(prompt), "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "service_tier": "standard",
            },
        },
    })

    if has_tools:
        # message_start 已发出，但还没发任何 content 块，此处重试是安全的。
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, model, "", attachments,
                                             gem_id=gem_id, account_id=account_id)
            return r.get("text", "")

        # 畸形工具 JSON 的重试要再跑一整轮上游 generate()——message_start 已经发出、
        # 这条流早就开了，裸 await 会在已开的连接上制造一次远超单个 keepalive 间隔的
        # 死寂（issue #10 followup F2）。用与上面 gen_task 相同的 task + keepalive 套路续心跳。
        parse_task = asyncio.create_task(parse_tool_response_with_retry(text, _regenerate_for_tools))
        try:
            async for ping in sse_keepalive_during(parse_task):
                yield ping
        except BaseException:          # GeneratorExit / CancelledError on client disconnect
            parse_task.cancel()
            if parse_task.done() and not parse_task.cancelled():
                parse_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
            raise
        parsed = parse_task.result()
        if parsed["type"] == "tool_calls":
            for i, tc in enumerate(parsed["tool_calls"]):
                block_id = f"toolu_{uuid.uuid4().hex[:8]}"
                yield _claude_sse({
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {"type": "tool_use", "id": block_id, "name": tc["name"], "input": {}},
                })
                args_str = json.dumps(tc.get("arguments", {}))
                yield _claude_sse({
                    "type": "content_block_delta",
                    "index": i,
                    "delta": {"type": "input_json_delta", "partial_json": args_str},
                })
                yield _claude_sse({"type": "content_block_stop", "index": i})

            yield _claude_sse({
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {
                    "output_tokens": estimate_tokens(text),
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                    "service_tier": "standard",
                },
            })
            yield _claude_sse({"type": "message_stop"})
            return
        text = parsed.get("content", text)

    # AI 生成图片：同非流式路径，折进文字块的 markdown，不单开 image 块（defect ⑥）。
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md

    # 上游回答真的是空字符串时，非流式路径（6cf8ca0）已经改发单空格占位文本块，不再吐
    # text:"" 的空块；这里是同一个 defect 在流式侧留下的对称缺口——不补的话客户端会拿到
    # content_block_start(text:"") -> content_block_stop 之间零个 delta，同样违反"遍历
    # content/delta 假设至少一块非空"的客户端假设。用单空格占位，不改变非空文本的既有行为。
    if not text:
        text = " "

    yield _claude_sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": "", "citations": None},
    })

    async for word in split_into_chunks(text):
        # split_into_chunks("") 因 "".split(" ") == [""] 会吐出一个空字符串块；
        # 没有这道防线就会发出零长度的 content_block_delta（defect ⑩）。
        if word:
            yield _claude_sse({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": word},
            })

    yield _claude_sse({"type": "content_block_stop", "index": 0})

    yield _claude_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {
            "output_tokens": estimate_tokens(text),
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "service_tier": "standard",
        },
    })

    yield _claude_sse({"type": "message_stop"})

