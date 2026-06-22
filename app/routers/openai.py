import json
import time
import uuid
import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.account_pool import account_pool as gemini_client
from app.core.api_forwarder import forward_to_provider, open_stream
from app.core.fallback import fallback_enabled, is_empty_result, get_fallback_entries, openai_data_is_empty
from app.core.conversation_store import conversation_store
from app.core.gemini_client import GEMINI_MODELS, MODEL_ALIASES, _resolve_model
from app.core.stream import split_into_chunks, format_sse
from app.models.openai import (
    ChatRequest, ChatResponse, Choice, ChoiceMessage,
    StreamChunk, StreamChoice, StreamDelta,
    ModelList, ModelInfo, UsageInfo,
    ImageGenerationRequest, ImageData, ImageResponse,
)
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens, is_image_generation_intent, maybe_image_generation_intent
from app.utils.prompt import build_prompt_from_messages, extract_attachments
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)
router = APIRouter(tags=["OpenAI"])


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


def _image_base(request) -> str:
    """从请求推断中转站对外地址（不写死，适配任意部署）。"""
    try:
        base = str(request.base_url).rstrip("/")
        return base
    except Exception:
        return ""


def _images_md_from_base(images: list, base: str) -> str:
    """生成图片转 markdown。优先用本地托管 URL（客户端可渲染），无 id 降级 data URI。"""
    lines = []
    for im in images:
        if im.get("id") and base:
            lines.append(f"![generated image]({base}/images/{im['id']})")
        elif im.get("b64"):
            lines.append(f"![generated image](data:{im['mime']};base64,{im['b64']})")
        elif im.get("fallback"):
            lines.append("*(Generated image could not be downloaded in time; please retry.)*")
    return "\n".join(lines)


_SSE_KEEPALIVE_INTERVAL = 10.0  # 刷新前置代理 idle/read 计时器（pro 生图链路更长，缩短间隔）


async def _sse_keepalive_during(task: asyncio.Task, interval: float = _SSE_KEEPALIVE_INTERVAL):
    """在后台 task 完成前周期 yield SSE comment ping，防止网关首字节/读超时。

    关键：task 在某个 interval 窗口内【抛异常】完成时，wait_for 会原样重抛该异常而非
    TimeoutError。绝不能让它逃出本生成器——否则会击穿调用方的 try/except（重试 + _err_chunk
    映射全成死代码），并把已发首帧的响应中途 abort。故非超时的完成（成功或异常）一律 return，
    让控制权落回调用方的 task.result()，由那里统一做重试/错误映射。"""
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval)
        except asyncio.TimeoutError:
            yield ": ping\n\n"
        except Exception:
            # task 已以异常完成：停止 ping，让调用方 task.result() 重抛并走既有错误处理
            return


async def _sse_stream_chunks(text: str, completion_id: str, model_name: str, *, fast: bool = False):
    """伪流式切片输出，切片间隔期间也发 keepalive ping。"""
    chunk_delay = 0.0 if fast else 0.03
    chunk_iter = split_into_chunks(text, delay=chunk_delay).__aiter__()
    while True:
        try:
            word = await asyncio.wait_for(
                chunk_iter.__anext__(), timeout=_SSE_KEEPALIVE_INTERVAL,
            )
        except asyncio.TimeoutError:
            yield ": ping\n\n"
            continue
        except StopAsyncIteration:
            break
        chunk = StreamChunk(
            id=completion_id, model=model_name,
            choices=[StreamChoice(delta=StreamDelta(content=word))],
        )
        yield format_sse(chunk.model_dump())


def _images_to_markdown(images: list, request) -> str:
    """生成图片转 markdown。优先用本地托管 URL（客户端可渲染），无 id 降级 data URI。"""
    return _images_md_from_base(images, _image_base(request))


def _json_body(resp) -> dict | None:
    """把 forward_to_provider 的 JSONResponse body 解析成 dict（失败返回 None）。"""
    try:
        body = getattr(resp, "body", None)
        if body is None:
            return None
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", "replace")
        return json.loads(body)
    except Exception:
        return None


async def _fallback_result(request, req: ChatRequest, messages_raw: list, exclude_model: str = "") -> dict | None:
    """Gemini 失败/空响应时的统一兜底：在候选第三方里按序（自动随机/或指定顺序）逐个
    用【非流式】探测，跳过报错或返回空的候选，直到拿到一个“有内容/有工具调用”的好结果。

    返回 OpenAI 风格响应 dict；未开启 / 无可用候选 / 全部失败时返回 None（调用方维持原有错误返回，零回归）。
    用非流式探测的好处：能在“真正发给客户端之前”验证候选是否可用，从而真正做到“一个不行换一个”，
    既不会把报错也不会把空响应当成功（流式直接转发无法回退，故统一走探测）。
    """
    if request is None or req is None or not fallback_enabled():
        return None
    pool = getattr(request.app.state, "api_key_pool", None)
    # 强制非流式探测（不改原 req 的 stream 语义）
    probe_req = req.model_copy(update={"stream": False})
    for entry in get_fallback_entries(request.app.state, exclude_model=exclude_model):
        try:
            resp = await forward_to_provider(entry, messages_raw, probe_req)
        except Exception as e:  # noqa: BLE001 — 单个候选失败不中断，换下一个
            logger.warning(f"[fallback] 第三方 {entry.model} 失败: {e}")
            continue
        if isinstance(resp, JSONResponse) and getattr(resp, "status_code", 200) >= 400:
            logger.warning(f"[fallback] 第三方 {entry.model} 返回 {getattr(resp, 'status_code', '?')}，换下一个")
            continue
        data = _json_body(resp)
        if data is None or openai_data_is_empty(data):
            logger.warning(f"[fallback] 第三方 {entry.model} 返回空/不可解析，换下一个")
            continue
        if pool:
            pool.update_last_used(entry.id)
        logger.info(f"[fallback] 已由第三方模型 {entry.model} 兜底")
        return data
    return None


async def _emit_openai_data_sse(data: dict, completion_id: str, model_name: str) -> AsyncGenerator[str, None]:
    """把第三方非流式 OpenAI 响应 dict 转成 SSE 帧（role 首帧已由调用方发出）。
    含工具调用则发原生 tool_calls 帧；否则把文本切片伪流式输出。"""
    message = {}
    try:
        message = (data.get("choices") or [{}])[0].get("message") or {}
    except Exception:
        message = {}
    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            clean_tc = {
                "id": tc.get("id"),
                "type": tc.get("type", "function"),
                "function": tc.get("function", {}),
            }
            chunk = StreamChunk(
                id=completion_id, model=model_name,
                choices=[StreamChoice(delta=StreamDelta(tool_calls=[clean_tc]))],
            )
            yield format_sse(chunk.model_dump())
        final = StreamChunk(
            id=completion_id, model=model_name,
            choices=[StreamChoice(delta=StreamDelta(), finish_reason="tool_calls")],
        )
        yield format_sse(final.model_dump())
        yield "data: [DONE]\n\n"
        return
    text = message.get("content") or ""
    async for sse in _sse_stream_chunks(text, completion_id, model_name, fast=True):
        yield sse
    done = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")],
    )
    yield format_sse(done.model_dump())
    yield "data: [DONE]\n\n"


async def _maybe_fallback_stream(request, req: ChatRequest, messages_raw: list, exclude_model: str, completion_id: str, model_name: str) -> AsyncGenerator[str, None]:
    """流式路径的兜底：探到好结果就转成 SSE 发出；没有则不产出任何 chunk。"""
    data = await _fallback_result(request, req, messages_raw, exclude_model)
    if data is None:
        return
    async for sse in _emit_openai_data_sse(data, completion_id, model_name):
        yield sse


def _thirdparty_ok(resp) -> bool:
    """非流式第三方 JSONResponse 成功判定：状态<400 且 body 非空（有 content 或 tool_calls）。"""
    if not isinstance(resp, JSONResponse):
        return True
    if getattr(resp, "status_code", 200) >= 400:
        return False
    return not openai_data_is_empty(_json_body(resp))


async def _dispatch_thirdparty(request, req: ChatRequest, resolved_model: str):
    """直连第三方故障切换：固定优先第一家，失败即冷却换下一家，全败返回最后错误。
    返回 None 表示该 model 非第三方/无候选 —— 落回 Gemini 路径，零回归。"""
    pool = getattr(request.app.state, "api_key_pool", None)
    if not pool:
        return None
    candidates = pool.get_entries_for_model(resolved_model)
    if not candidates:
        return None
    messages_raw = [m.model_dump() for m in req.messages]
    cooldown = settings.thirdparty_failover_cooldown
    last_error = None
    for entry in candidates:
        if req.stream:
            stream_resp, err = await open_stream(entry, messages_raw, req)
            if stream_resp is not None:
                pool.update_last_used(entry.id)
                return stream_resp
            last_error = err
        else:
            resp = await forward_to_provider(entry, messages_raw, req)
            if _thirdparty_ok(resp):
                pool.update_last_used(entry.id)
                return resp
            last_error = resp
        pool.mark_unhealthy(entry.id, cooldown)
    return last_error


@router.get("/models")
async def list_models(request: Request):
    models = list(gemini_client.models)
    # Also include models from API key pool
    pool = getattr(request.app.state, 'api_key_pool', None)
    if pool:
        for entry in pool.entries.values():
            if entry.status == 'active' and entry.model not in models:
                models.append(entry.model)
    # MODEL_WHITELIST 过滤（为空则放行全部）
    models = _apply_model_whitelist(models)
    now = int(time.time())
    data = [ModelInfo(id=m, created=now) for m in models]
    return ModelList(data=data)


@router.post("/chat/completions")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def chat_completions(req: ChatRequest, request: Request):
    model_mapping = request.app.state.model_mapping
    resolved_model = model_mapping.resolve(req.model)

    if resolved_model not in gemini_client.models and _resolve_model(resolved_model) not in GEMINI_MODELS:
        tp = await _dispatch_thirdparty(request, req, resolved_model)
        if tp is not None:
            return tp

    messages_raw = [m.model_dump() for m in req.messages]

    # 对话上下文持久化：检查是否有 conversation_id
    gemini_conv_id = ""
    conv = None
    if req.conversation_id:
        conv = await conversation_store.get(req.conversation_id)
        if conv and conv.gemini_conv_id:
            gemini_conv_id = conv.gemini_conv_id

    # 如果有有效的 gemini_conv_id，只发最新一条用户消息
    if gemini_conv_id and messages_raw:
        last_user_msg = ""
        for msg in reversed(messages_raw):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
                last_user_msg = content
                break
        prompt = last_user_msg if last_user_msg else build_prompt_from_messages(messages_raw)
    else:
        prompt = build_prompt_from_messages(messages_raw)

    has_tools = bool(req.tools)
    # 生图意图优先：即使带 tools（agent 每请求都带），只要是明确生图意图就跳过工具模拟，
    # 直接走生图，否则工具 prompt 会压制 Gemini 的图片生成能力。
    if has_tools and is_image_generation_intent(prompt):
        has_tools = False
        logger.info("检测到生图意图，跳过工具调用模拟，直接生图")
    if has_tools:
        tools_raw = [t.model_dump() for t in req.tools]
        prompt = build_tool_prompt(prompt, tools_raw, req.tool_choice)

    # 提取图片/文件附件（多模态），纯文本时为空列表
    attachments = extract_attachments(messages_raw)

    if req.stream:
        return StreamingResponse(
            _stream_response(prompt, resolved_model, has_tools, gemini_conv_id, conv, messages_raw, req.model, attachments, _image_base(request), request, req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, resolved_model, gemini_conv_id, attachments)
    except (RuntimeError, ValueError) as e:
        # Fallback: 如果 conversation_id 过期，用完整 prompt 重试
        if gemini_conv_id:
            prompt = build_prompt_from_messages(messages_raw)
            if has_tools:
                tools_raw = [t.model_dump() for t in req.tools]
                prompt = build_tool_prompt(prompt, tools_raw, req.tool_choice)
            try:
                result = await gemini_client.generate(prompt, resolved_model)
                gemini_conv_id = ""
            except Exception:
                fb = await _fallback_result(request, req, messages_raw, resolved_model)
                if fb is not None:
                    return JSONResponse(content=fb)
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": str(e), "type": "api_error"}},
                )
        else:
            fb = await _fallback_result(request, req, messages_raw, resolved_model)
            if fb is not None:
                return JSONResponse(content=fb)
            return JSONResponse(
                status_code=500 if "retry" in str(e).lower() else 400,
                content={"error": {"message": str(e), "type": "api_error"}},
            )

    # Gemini 返回空响应（无文本、无图）→ 第三方兜底（开关关闭/无候选时返回 None，零回归）
    if is_empty_result(result):
        fb = await _fallback_result(request, req, messages_raw, resolved_model)
        if fb is not None:
            return JSONResponse(content=fb)

    text = result.get("text", "")
    # AI 生成图片：图片在前，紧跟文字描述（单换行，不留多余空行）
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md
    new_conv_id = result.get("conversation_id", "")
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # 持久化对话
    if new_conv_id:
        if not conv:
            conv_store_id = req.conversation_id or completion_id
            conv = await conversation_store.create(conv_store_id, resolved_model)
        conv.gemini_conv_id = new_conv_id
        last_user = messages_raw[-1].get("content", "") if messages_raw else ""
        if isinstance(last_user, list):
            last_user = str(last_user)
        conv.add_message("user", last_user)
        conv.add_message("assistant", text)
        await conversation_store.update(conv)

    if has_tools:
        parsed = parse_tool_response(text)
        if parsed["type"] == "tool_calls":
            tool_calls = []
            for i, tc in enumerate(parsed["tool_calls"]):
                call_id = f"call_{uuid.uuid4().hex[:8]}"
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                })
            return ChatResponse(
                id=completion_id,
                model=req.model,
                choices=[Choice(
                    message=ChoiceMessage(role="assistant", tool_calls=tool_calls),
                    finish_reason="tool_calls",
                )],
                usage=UsageInfo(
                    prompt_tokens=estimate_tokens(prompt),
                    completion_tokens=estimate_tokens(text),
                    total_tokens=estimate_tokens(prompt) + estimate_tokens(text),
                ),
                conversation_id=conv.id if conv else None,
            )
        text = parsed.get("content", text)

    return ChatResponse(
        id=completion_id,
        model=req.model,
        choices=[Choice(
            message=ChoiceMessage(role="assistant", content=text),
            finish_reason="stop",
        )],
        usage=UsageInfo(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(text),
            total_tokens=estimate_tokens(prompt) + estimate_tokens(text),
        ),
        conversation_id=conv.id if conv else None,
    )


async def _stream_response(prompt: str, model: str, has_tools: bool, gemini_conv_id: str = "", conv=None, messages_raw=None, display_model: str = "", attachments=None, base_url: str = "", request=None, req=None) -> AsyncGenerator[str, None]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    model_name = display_model or model

    # 有工具调用或附件：需要完整文本才能解析 tool_calls / 处理上传，走非流式收集后再切片（零回归）。
    # 生图意图（宽松判断兜底）：图片在生成的最后才拿到，真流式会"文字先流、图最后补"导致割裂；
    #          走 buffered 收集完整结果，才能让图片排在文字前面。宽松判断宁可多走 buffered 不漏网。
    if has_tools or attachments or maybe_image_generation_intent(prompt):
        async for sse in _stream_response_buffered(
            prompt, model, has_tools, gemini_conv_id, conv, messages_raw,
            model_name, completion_id, attachments, base_url, request, req
        ):
            yield sse
        return

    # === 真流式路径 ===
    first = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(role="assistant"))],
    )
    yield format_sse(first.model_dump())

    full_text = ""
    new_conv_id = ""
    final_images = []
    streamed_any = False
    try:
        async for evt in gemini_client.generate_stream(prompt, model, gemini_conv_id, attachments):
            if evt.get("type") == "delta":
                # generate_stream 现在是严格 append-only（不再发 _replace），delta 总是新增尾部
                delta = evt.get("text", "")
                full_text += delta
                if delta:
                    streamed_any = True
                    chunk = StreamChunk(
                        id=completion_id, model=model_name,
                        choices=[StreamChoice(delta=StreamDelta(content=delta))],
                    )
                    yield format_sse(chunk.model_dump())
            elif evt.get("type") == "final":
                # final.text 是过滤完占位串的完整文本，可能比已流出的 full_text 多出
                # （流式时被 hold 住的尾部）。补发缺失尾部，保证客户端拿到完整内容。
                final_text = evt.get("text", full_text)
                if final_text.startswith(full_text) and len(final_text) > len(full_text):
                    tail = final_text[len(full_text):]
                    full_text = final_text
                    if tail:
                        chunk = StreamChunk(
                            id=completion_id, model=model_name,
                            choices=[StreamChoice(delta=StreamDelta(content=tail))],
                        )
                        yield format_sse(chunk.model_dump())
                else:
                    full_text = final_text
                new_conv_id = evt.get("conversation_id", "")
                final_images = evt.get("images") or []
    except Exception as e:
        # 流式失败：会话ID 过期等场景，用完整 prompt 非流式重试一次
        if gemini_conv_id and messages_raw and not streamed_any:
            try:
                retry_prompt = build_prompt_from_messages(messages_raw)
                result = await gemini_client.generate(retry_prompt, model, "", attachments)
                full_text = result.get("text", "")
                new_conv_id = result.get("conversation_id", "")
                final_images = result.get("images") or []
            except Exception as e2:
                # 尚未流出任何内容（只发过 role 首帧）→ 可安全改用第三方兜底（流式）
                if not streamed_any:
                    emitted = False
                    async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                        emitted = True
                        yield chunk
                    if emitted:
                        return
                yield _err_chunk(completion_id, model_name, str(e2))
                return
        else:
            if not streamed_any:
                emitted = False
                async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                    emitted = True
                    yield chunk
                if emitted:
                    return
            yield _err_chunk(completion_id, model_name, str(e))
            return

    # Gemini 真流式整条为空（只发过 role 首帧，未流出任何内容）→ 第三方兜底
    if not streamed_any and not (full_text or "").strip() and not final_images:
        emitted = False
        async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
            emitted = True
            yield chunk
        if emitted:
            return

    # 生图兜底：极少数生图意图未被识别而走了真流式（文字已先流出，无法把图收回到最前）。
    # 此时图片在最后帧拿到，补发图片增量；用单换行紧凑拼接，保证图能独立成行正常显示。
    if final_images:
        md = _images_md_from_base(final_images, base_url)
        tail = ("\n" + md) if full_text.strip() else md
        full_text += tail
        chunk = StreamChunk(
            id=completion_id, model=model_name,
            choices=[StreamChoice(delta=StreamDelta(content=tail))],
        )
        yield format_sse(chunk.model_dump())

    # 持久化对话（与 buffered 子路径一致：流式只存 assistant，
    # 多轮续接靠 gemini_conv_id，user 消息已在请求里）
    if new_conv_id and conv:
        conv.gemini_conv_id = new_conv_id
        conv.add_message("assistant", full_text)
        await conversation_store.update(conv)

    done_chunk = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")],
    )
    yield format_sse(done_chunk.model_dump())
    yield "data: [DONE]\n\n"


def _err_chunk(completion_id: str, model_name: str, msg: str) -> str:
    chunk = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(content=f"Error: {msg}"), finish_reason="stop")],
    )
    return format_sse(chunk.model_dump()) + "data: [DONE]\n\n"


async def _stream_response_buffered(prompt: str, model: str, has_tools: bool, gemini_conv_id: str = "", conv=None, messages_raw=None, model_name: str = "", completion_id: str = "", attachments=None, base_url: str = "", request=None, req=None) -> AsyncGenerator[str, None]:
    """非流式收集 + 切片伪流式：用于有工具调用/附件、需要完整文本的场景。"""
    # 立即发出首帧 SSE，避免生图/工具路径在 generate() 阻塞期间零字节导致前置代理超时。
    first = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(role="assistant"))],
    )
    yield format_sse(first.model_dump())

    async def _run_generate():
        return await gemini_client.generate(prompt, model, gemini_conv_id, attachments)

    gen_task = asyncio.create_task(_run_generate())
    async for ping in _sse_keepalive_during(gen_task):
        yield ping

    try:
        result = gen_task.result()
    except Exception as e:
        if gemini_conv_id and messages_raw:
            full_prompt = build_prompt_from_messages(messages_raw)
            retry_task = asyncio.create_task(
                gemini_client.generate(full_prompt, model, "", attachments)
            )
            async for ping in _sse_keepalive_during(retry_task):
                yield ping
            try:
                result = retry_task.result()
            except Exception as e2:
                emitted = False
                async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                    emitted = True
                    yield chunk
                if emitted:
                    return
                yield _err_chunk(completion_id, model_name, str(e2))
                return
        else:
            emitted = False
            async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                emitted = True
                yield chunk
            if emitted:
                return
            yield _err_chunk(completion_id, model_name, str(e))
            return

    # Gemini 返回空响应（无文本、无图）→ 第三方兜底（此前只发过 role 首帧 + keepalive，可安全改流）
    if is_empty_result(result):
        emitted = False
        async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
            emitted = True
            yield chunk
        if emitted:
            return

    text = result.get("text", "")
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_md_from_base(gen_images, base_url)
        text = (md + "\n" + text.strip()) if text.strip() else md
    new_conv_id = result.get("conversation_id", "")

    if new_conv_id and conv:
        conv.gemini_conv_id = new_conv_id
        conv.add_message("assistant", text)
        await conversation_store.update(conv)

    if has_tools:
        parsed = parse_tool_response(text)
        if parsed["type"] == "tool_calls":
            for tc in parsed["tool_calls"]:
                call_id = f"call_{uuid.uuid4().hex[:8]}"
                tool_call_data = {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                }
                chunk = StreamChunk(
                    id=completion_id, model=model_name,
                    choices=[StreamChoice(delta=StreamDelta(tool_calls=[tool_call_data]))],
                )
                yield format_sse(chunk.model_dump())

            final = StreamChunk(
                id=completion_id, model=model_name,
                choices=[StreamChoice(delta=StreamDelta(), finish_reason="tool_calls")],
            )
            yield format_sse(final.model_dump())
            yield "data: [DONE]\n\n"
            return
        text = parsed.get("content", text)

    async for sse in _sse_stream_chunks(
        text, completion_id, model_name, fast=bool(gen_images),
    ):
        yield sse

    done_chunk = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")],
    )
    yield format_sse(done_chunk.model_dump())
    yield "data: [DONE]\n\n"



@router.post("/images/generations")
async def images_generations(req: ImageGenerationRequest):
    """OpenAI 兼容的图片生成接口。靠 prompt 触发 Gemini Web 生图，
    服务端代下载图片转 base64 返回（lh3 URL 客户端直接访问会 403）。"""
    raw_prompt = (req.prompt or "").strip()
    if not raw_prompt:
        return JSONResponse(status_code=400,
            content={"error": {"message": "prompt is required", "type": "invalid_request_error"}})

    # 确保 prompt 含生图意图，否则加前缀（复用公共意图检测）
    if not is_image_generation_intent(raw_prompt):
        prompt = f"Generate an image of {raw_prompt}"
    else:
        prompt = raw_prompt

    model = _resolve_model(req.model or "gemini-pro")
    try:
        result = await gemini_client.generate(prompt, req.model or "gemini-pro")
    except (RuntimeError, ValueError) as e:
        return JSONResponse(status_code=500,
            content={"error": {"message": str(e), "type": "api_error"}})

    images = result.get("images") or []
    if not images:
        return JSONResponse(status_code=502, content={"error": {
            "message": "未生成图片。可能账号无生图权限（地区/年龄限制），或 prompt 未触发生图。",
            "type": "image_generation_failed"}})

    n = max(1, min(req.n or 1, len(images)))
    fmt = (req.response_format or "b64_json").lower()
    data = []
    for img in images[:n]:
        if fmt == "url":
            # 无本地存储时降级为 data URI（保证可用）
            data.append(ImageData(url=f"data:{img['mime']};base64,{img['b64']}"))
        else:
            data.append(ImageData(b64_json=img["b64"]))
    return ImageResponse(data=data)
