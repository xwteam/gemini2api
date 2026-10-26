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
from app.core.access_context import (
    ensure_model_allowed, filter_models_for_access_key, record_token_usage,
    with_retired_models_for_access_key,
    scoped_conversation_id,
)
from app.core.api_forwarder import empty_upstream_error, forward_to_provider, open_stream, run_failover
from app.core.fallback import fallback_enabled, is_empty_result, get_fallback_entries, openai_data_is_empty
from app.core.conversation_store import conversation_store
from app.core.gemini_client import (GEMINI_MODELS, GENERATION_ERRORS, MODEL_ALIASES, _resolve_model,
                                    classify_error, encode_conversation_metadata,
                                    generate_with_thinking_fallback, is_timeout_error,
                                    parse_conversation_metadata, parse_effort_request,
                                    resolve_thinking, should_retry_without_thinking)
from app.core.thinking_stream import HiddenThoughts, drop_thought_events
from app.core.stream import split_into_chunks, format_sse, iter_with_keepalive, SSE_KEEPALIVE_INTERVAL, SSE_KEEPALIVE_FRAME, sse_keepalive_during
from app.models.openai import (
    ChatRequest, ChatResponse, Choice, ChoiceMessage,
    StreamChunk, StreamChoice, StreamDelta,
    ModelList, ModelInfo, UsageInfo,
    ImageGenerationRequest, ImageData, ImageResponse,
)
from app.utils.tools import build_tool_prompt, parse_tool_response_with_retry, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages, extract_attachments, last_user_text
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


_SSE_KEEPALIVE_INTERVAL = SSE_KEEPALIVE_INTERVAL  # 单一来源见 app/core/stream.py


_sse_keepalive_during = sse_keepalive_during  # 实现下沉至 app/core/stream.py（供 claude 侧复用）


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
    """直连第三方故障切换：固定优先第一家，失败换下一家；冷却与"全败回哪个错误"的规则见
    api_forwarder.run_failover（与 /v1/responses 共用）。
    返回 None 表示该 model 非第三方/无候选 —— 落回 Gemini 路径，零回归。"""
    pool = getattr(request.app.state, "api_key_pool", None)
    if not pool:
        return None
    candidates = pool.get_entries_for_model(resolved_model)
    if not candidates:
        return None
    messages_raw = [m.model_dump() for m in req.messages]

    async def attempt(entry):
        if req.stream:
            return await open_stream(entry, messages_raw, req)
        resp = await forward_to_provider(entry, messages_raw, req)
        if _thirdparty_ok(resp):
            return resp, None
        if getattr(resp, "status_code", 500) < 400:
            return None, empty_upstream_error()
        return None, resp

    ok, error = await run_failover(candidates, attempt, pool, settings.thirdparty_failover_cooldown)
    return ok if ok is not None else error


def _resume_target(conv, gem_account_id: str | None) -> tuple[str, str | None]:
    """这一轮续不续接上一轮的 Gemini 会话 → (续接参数, 这一轮钉的账号)。

    只有「存储里解析得出有效 cid」并且「能钉回记录的那个账号」才续接：返回
    (encode_conversation_metadata 编好的 [cid, rid, rcid], 会话的账号)，调用方只发最后一条
    用户消息。会话 id 是账号私有的，换个账号就接不上 —— v1.6.44 及以前第二轮按轮询落到哪个
    账号算哪个。
    否则返回 ("", gem_account_id)：调用方用 build_prompt_from_messages 发完整历史、不带续接
    参数（等于新开一个会话），拿到结果后照常把新的 cid 与账号存回去。接不上的时候绝不只发
    最后一句 —— 那等于静默丢掉整段上下文。

    Gem 自带的账号绑定优先：Gem 钉的账号与会话记录的账号不一致时不续接（以 Gem 为准）。
    """
    if conv is None:
        return "", gem_account_id
    meta = parse_conversation_metadata(getattr(conv, "gemini_conv_id", ""))
    if meta is None:
        return "", gem_account_id
    conv_account = getattr(conv, "account_id", "") or ""
    if not conv_account:
        reason = "no recorded account"
    elif gem_account_id and gem_account_id != conv_account:
        reason = f"the gem is bound to {gem_account_id}, the conversation lives on {conv_account}"
    elif not gemini_client.account_pinnable(conv_account):
        reason = f"account {conv_account} is unavailable"
    else:
        return encode_conversation_metadata(meta), conv_account
    logger.info(f"Conversation {getattr(conv, 'id', '?')}: not resuming ({reason}); "
                f"resending the full history as a new conversation")
    return "", gem_account_id


@router.get("/models")
async def list_models(request: Request):
    models = with_retired_models_for_access_key(gemini_client.models)
    # Also include models from API key pool
    pool = getattr(request.app.state, 'api_key_pool', None)
    if pool:
        for entry in pool.entries.values():
            if entry.status == 'active' and entry.model not in models:
                models.append(entry.model)
    # 把已暴露的 gem 模型名并进列表
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    if gem_mapping:
        for gem_model_name in gem_mapping.get_all().keys():
            if gem_model_name not in models:
                models.append(gem_model_name)
    # MODEL_WHITELIST 过滤（为空则放行全部）
    models = _apply_model_whitelist(models)
    # 再叠一层访问密钥的 allowed_models（未限定则原样返回）
    models = filter_models_for_access_key(models)
    now = int(time.time())
    data = [ModelInfo(id=m, created=now) for m in models]
    return ModelList(data=data)


@router.post("/chat/completions")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def chat_completions(req: ChatRequest, request: Request):
    model_mapping = request.app.state.model_mapping
    resolved_model = model_mapping.resolve(req.model)

    # gem 模型解析：命中则取出 gem_id/account_id，并把对话模型换成 base_model
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(resolved_model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            resolved_model = gem_info.get("base_model") or "gemini-pro"

    # 访问密钥限定模型时在此闸断（原名/解析后名任一命中即放行）；未限定则零开销返回。
    ensure_model_allowed(req.model, resolved_model)

    if resolved_model not in gemini_client.models and _resolve_model(resolved_model) not in GEMINI_MODELS:
        tp = await _dispatch_thirdparty(request, req, resolved_model)
        if tp is not None:
            return tp

    messages_raw = [m.model_dump() for m in req.messages]

    # 对话上下文持久化：检查是否有 conversation_id
    conv = None
    if req.conversation_id:
        # 存储键按访问密钥隔离；回给客户端的仍是它自己给的那个 id（见 _conv_echo_id）
        conv = await conversation_store.get(scoped_conversation_id(req.conversation_id))
    # 续接（只发最后一句）的前提：存储里有有效的 [cid, rid, rcid]，且钉得回记录的那个账号。
    # 否则 gemini_conv_id 为空、发完整历史；account_id 是这一轮钉的账号（续接 = 会话的账号，
    # 否则 = Gem 绑定的账号，没有就不钉）。完整历史重试一律只钉 Gem 的账号（gem_account_id）。
    gemini_conv_id, account_id = _resume_target(conv, gem_account_id)

    # 如果有有效的 gemini_conv_id，只发最新一条用户消息
    if gemini_conv_id and messages_raw:
        last_user_msg = ""
        for msg in reversed(messages_raw):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # 注意：这里对"没有可用 text 的 dict 块"（如纯图片块）刻意保留一个空串贡献，
                    # 与 app/utils/prompt.py 里直接跳过该类块的做法不同 —— 不是笔误。原因是下一行的
                    # 分支选择逻辑依赖此结果的真假值：纯图片消息展平后是 "\n"（非空即真），仍走
                    # continuation 分支只发最新一条；若改成跳过就会变成 ""（假），错误落回
                    # build_prompt_from_messages 把整段历史重发一遍。保留空串 = 保持既有行为逐字节不变。
                    content = "\n".join(b.get("text", "") if isinstance(b.get("text", ""), str) else ""
                                        for b in content if isinstance(b, dict))
                last_user_msg = content
                break
        prompt = last_user_msg if last_user_msg else build_prompt_from_messages(messages_raw)
    else:
        prompt = build_prompt_from_messages(messages_raw)

    has_tools = bool(req.tools)
    # 生图意图优先：即使带 tools（agent 每请求都带），只要是明确生图意图就跳过工具模拟，
    # 直接走生图，否则工具 prompt 会压制 Gemini 的图片生成能力。
    # 只看最后一轮用户消息：prompt 可能是整段历史（含 system 与 tool_result 正文），
    # 拿它判断会误判成生图并静默丢掉客户端 tools。
    if has_tools and is_image_generation_intent(last_user_text(messages_raw)):
        has_tools = False
        logger.info("检测到生图意图，跳过工具调用模拟，直接生图")
    if has_tools:
        tools_raw = [t.model_dump() for t in req.tools]
        prompt = build_tool_prompt(prompt, tools_raw, req.tool_choice)

    # 提取图片/文件附件（多模态），纯文本时为空列表
    attachments = extract_attachments(messages_raw)

    # reasoning_effort → 思考档位：low/medium/high 各走各的档，minimal 夹到 low、xhigh 夹到
    # high，none = 不思考，认不出的非空值 → 跟随"默认思考档位"；
    # **不传 → "默认思考档位"设置**（出厂 low）。
    # 见 gemini_client.resolve_thinking。决策拆成两个量：
    #   extended_thinking —— 发给上游的档位（False = 不思考旧路径；1/2/4 = 档位）
    #   show_thinking     —— 回不回传 reasoning_content。只有客户端明确传了才回传：
    #                        按默认档替它开的思考只用于上游生成，响应结构与不思考时一致。
    _plan = resolve_thinking(parse_effort_request(req.reasoning_effort))
    extended_thinking = _plan.upstream
    show_thinking = _plan.show

    if req.stream:
        return StreamingResponse(
            _stream_response(prompt, resolved_model, has_tools, gemini_conv_id, conv, messages_raw, req.model, attachments, _image_base(request), request, req, gem_id, account_id, extended_thinking=extended_thinking, show_thinking=show_thinking, gem_account_id=gem_account_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, resolved_model, gemini_conv_id, attachments,
                                              gem_id=gem_id, account_id=account_id,
                                              extended_thinking=extended_thinking)
    except GENERATION_ERRORS as e:
        err = e
        result = None
        # 扩展思维链路径失败：先原样退回非思维链重试一次，再走既有兜底（会话过期/第三方）。
        # 超时不退回（THINKING_RETRYABLE_ERRORS 刻意不含超时：这一轮的预算已经花完）。
        if should_retry_without_thinking(e, extended_thinking):
            logger.warning(f"extended-thinking request failed, retrying normal: {e}")
            show_thinking = False   # 这一轮确实没思考
            try:
                result = await gemini_client.generate(prompt, resolved_model, gemini_conv_id, attachments,
                                                      gem_id=gem_id, account_id=account_id,
                                                      extended_thinking=False)
            except GENERATION_ERRORS as e2:
                err = e2

        if result is None:
            # Fallback: 如果 conversation_id 过期，用完整 prompt 重试。超时不走这一步：再试会
            # 让客户端再等一整轮；直接兜底（如开）→ 否则 504。
            # 这一步是新开会话：不带续接参数、不钉会话的账号（钉住的账号可能正是失败的原因），
            # 只钉 Gem 的账号。也接住「钉的账号真发时才报 unavailable」的竞态（见 _resume_target）。
            if gemini_conv_id and not is_timeout_error(err):
                prompt = build_prompt_from_messages(messages_raw)
                if has_tools:
                    tools_raw = [t.model_dump() for t in req.tools]
                    prompt = build_tool_prompt(prompt, tools_raw, req.tool_choice)
                try:
                    result = await gemini_client.generate(prompt, resolved_model,
                                                           gem_id=gem_id, account_id=gem_account_id,
                                                           extended_thinking=False)
                    gemini_conv_id = ""
                    account_id = gem_account_id
                except Exception:
                    fb = await _fallback_result(request, req, messages_raw, resolved_model)
                    if fb is not None:
                        return JSONResponse(content=fb)
                    status, err_type, retry_after = classify_error(err)
                    headers = {"Retry-After": str(retry_after)} if retry_after else None
                    return JSONResponse(
                        status_code=status,
                        content={"error": {"message": str(err), "type": err_type}},
                        headers=headers,
                    )
            else:
                fb = await _fallback_result(request, req, messages_raw, resolved_model)
                if fb is not None:
                    return JSONResponse(content=fb)
                status, err_type, retry_after = classify_error(err)
                headers = {"Retry-After": str(retry_after)} if retry_after else None
                return JSONResponse(
                    status_code=status,
                    content={"error": {"message": str(err), "type": err_type}},
                    headers=headers,
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
            conv_store_id = scoped_conversation_id(req.conversation_id or completion_id)
            conv = await conversation_store.create(conv_store_id, resolved_model)
        conv.gemini_conv_id = new_conv_id
        # 记下服务这一轮的账号：下一轮要钉回它才接得上这个会话
        conv.account_id = result.get("account_id") or ""
        last_user = messages_raw[-1].get("content", "") if messages_raw else ""
        if isinstance(last_user, list):
            last_user = str(last_user)
        conv.add_message("user", last_user)
        conv.add_message("assistant", text)
        await conversation_store.update(conv)

    if has_tools:
        async def _regenerate_for_tools() -> str:
            # 续接时同样钉会话的账号：带着续接参数落到别的账号就接不上
            r = await gemini_client.generate(prompt, resolved_model, gemini_conv_id, attachments,
                                             gem_id=gem_id, account_id=account_id,
                                             extended_thinking=extended_thinking)
            return r.get("text", "")

        parsed = await parse_tool_response_with_retry(text, _regenerate_for_tools)
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
                usage=_usage_and_record(resolved_model, prompt, text, result),
                conversation_id=(req.conversation_id or completion_id) if conv else None,
            )
        text = parsed.get("content", text)

    return ChatResponse(
        id=completion_id,
        model=req.model,
        choices=[Choice(
            message=ChoiceMessage(role="assistant", content=text,
                                  reasoning_content=((result.get("thoughts") or None)
                                                     if show_thinking else None)),
            finish_reason="stop",
        )],
        usage=_usage_and_record(resolved_model, prompt, text, result),
        conversation_id=(req.conversation_id or completion_id) if conv else None,
    )


def _record_usage(model: str, prompt: str, text: str, thoughts: str = "") -> None:
    """按-key 用量落账（只统计、不限额）。

    思考链计进 output：官方 API 对 thinking token 按 output 计费，这里跟着官方口径走
    （所以面板上的 output 可能比协议里回给客户端的 completion_tokens 大）。
    幂等（首次调用生效）由 record_token_usage 自己保证。
    ⚠️ 必须留在生成器自己的函数体里，不能挪进 asyncio.create_task 的协程 —— 见
    access_context.record_token_usage 的说明。
    """
    record_token_usage(model, estimate_tokens(prompt),
                       estimate_tokens(text or "") + estimate_tokens(thoughts or ""))


def _usage_and_record(model: str, prompt: str, text: str, result: dict | None = None) -> UsageInfo:
    """算出协议要回的 UsageInfo，同时把这一次的用量记到访问密钥上。

    协议里的 completion_tokens 口径一个字不改（仍只算正文），落账那份另算思考链。
    """
    _record_usage(model, prompt, text, (result or {}).get("thoughts") or "")
    return UsageInfo(
        prompt_tokens=estimate_tokens(prompt),
        completion_tokens=estimate_tokens(text),
        total_tokens=estimate_tokens(prompt) + estimate_tokens(text),
    )


async def _stream_response(prompt: str, model: str, has_tools: bool, gemini_conv_id: str = "", conv=None, messages_raw=None, display_model: str = "", attachments=None, base_url: str = "", request=None, req=None, gem_id=None, account_id=None, extended_thinking=False, show_thinking: bool = False, gem_account_id=None) -> AsyncGenerator[str, None]:
    """account_id = 这一轮钉的账号（续接 = 会话的账号）；gem_account_id = 改发完整历史时还要钉的
    账号（只有 Gem 绑定，没有就不钉）。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    model_name = display_model or model

    # 只有「工具调用」才强制走 buffered：tool_calls 必须拿到完整 JSON 才能解析，
    # 这条门禁是对的，保留。
    #
    # 另外两条已经摘掉：
    # - attachments：附件在 generate_stream 里照样会先上传完再开始对话（底层支持），
    #   把它挡在 buffered 里只是让所有带图/带文件的请求都"等全文生成完才吐第一个字"。
    #   参考实现 refs/gemini-web2api 也是附件上传完照常流式。
    # - 生图意图：那是个关键词猜测（maybe_image_generation_intent），误判面很大，
    #   把一堆普通对话也拖进 buffered。它现在只用来决定 POST 超时（见
    #   gemini_client._generate_timeout），不再参与分流。真的返回了图片时，真流式路径
    #   会在收到 final 帧后补发图片增量（见下方"生图兜底"分支），图片不会丢，
    #   只是排在文字后面。
    if has_tools:
        async for sse in _stream_response_buffered(
            prompt, model, has_tools, gemini_conv_id, conv, messages_raw,
            model_name, completion_id, attachments, base_url, request, req, gem_id, account_id,
            extended_thinking=extended_thinking, gem_account_id=gem_account_id,
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
    new_account_id = ""
    final_images = []
    streamed_any = False
    emitted_thoughts = ""  # 已发出的思维链前缀，用于跟已知累积 thoughts 做前缀 diff 只发增量
    # 不回传时（客户端没要求思考、是按默认档开的）思考只进内部记账，一个字都不进 SSE。
    # 过滤放在 iter_with_keepalive 之前：思考期间对保活计时器来说就是静默，到点照发保活帧
    # （见 app/core/thinking_stream.py）。
    hidden = HiddenThoughts()
    upstream = gemini_client.generate_stream(prompt, model, gemini_conv_id, attachments,
                                             gem_id=gem_id, account_id=account_id,
                                             extended_thinking=extended_thinking)
    if not show_thinking:
        upstream = drop_thought_events(upstream, hidden)
    try:
        async for _kind, evt in iter_with_keepalive(upstream):
            if _kind == "ping":
                yield SSE_KEEPALIVE_FRAME
                continue
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
            elif evt.get("type") == "thoughts":
                # 只有 show_thinking 时才会到这里（不回传的已在上游一侧被滤掉）
                t_delta = evt.get("text", "")
                if t_delta:
                    emitted_thoughts += t_delta
                    chunk = StreamChunk(
                        id=completion_id, model=model_name,
                        choices=[StreamChoice(delta=StreamDelta(reasoning_content=t_delta))],
                    )
                    yield format_sse(chunk.model_dump())
            elif evt.get("type") == "final":
                # 思维链目前只在 final 帧一次性拿到完整累积 thoughts（底层暂不逐帧增量），
                # 这里仍按「已发出前缀 diff」的方式只发新增部分，为未来逐帧增量留好口子；
                # 在文本尾部补发之前先发，保证客户端先看到 reasoning 再看到最终回答。
                final_thoughts = evt.get("thoughts", "") or ""
                if not show_thinking:
                    hidden.text = final_thoughts or hidden.text
                elif final_thoughts != emitted_thoughts and final_thoughts.startswith(emitted_thoughts):
                    thoughts_delta = final_thoughts[len(emitted_thoughts):]
                    emitted_thoughts = final_thoughts
                    if thoughts_delta:
                        chunk = StreamChunk(
                            id=completion_id, model=model_name,
                            choices=[StreamChoice(delta=StreamDelta(reasoning_content=thoughts_delta))],
                        )
                        yield format_sse(chunk.model_dump())
                # else: divergent/shrunk final thoughts — reasoning already streamed; do NOT re-emit whole (avoid duplicate)
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
                new_account_id = evt.get("account_id") or ""
                final_images = evt.get("images") or []
    except Exception as e:
        # 尚未流出任何正文时，非流式不思考重试一次：
        #   - 会话ID 过期等场景：用完整 prompt、开新会话重试（原有逻辑）；
        #   - 思考路径失败（默认档上线后几乎每个请求都走思考路径）：原样退回不思考重试，
        #     与非流式 / buffered（generate_with_thinking_fallback）、Responses 真流式同口径。
        #     没有这一退回，上游拒收思考 payload 时，v1.6.42 能答的不传参流式请求会变成硬失败。
        retry_args = None
        if not streamed_any:
            # 超时两种重试都不做（预算已经花完，再试会让客户端再等一整轮）：直接兜底 / 报错。
            # 会话重试是新开会话：完整历史、不带续接参数、不钉会话的账号（只钉 Gem 的）。
            if gemini_conv_id and messages_raw and not is_timeout_error(e):
                retry_args = (build_prompt_from_messages(messages_raw), "", gem_account_id)
            elif should_retry_without_thinking(e, extended_thinking):
                logger.warning(f"extended-thinking stream failed, retrying normal: {e}")
                retry_args = (prompt, gemini_conv_id, account_id)
        if retry_args is not None:
            # 重试是一整轮非流式生成：用 task + keepalive 续心跳，别制造一段远超保活间隔的死寂
            retry_task = asyncio.create_task(gemini_client.generate(
                retry_args[0], model, retry_args[1], attachments,
                gem_id=gem_id, account_id=retry_args[2], extended_thinking=False))
            try:
                async for ping in _sse_keepalive_during(retry_task):
                    yield ping
            except BaseException:          # GeneratorExit / CancelledError on client disconnect
                retry_task.cancel()
                if retry_task.done() and not retry_task.cancelled():
                    retry_task.exception()
                raise
            try:
                result = retry_task.result()
                full_text = result.get("text", "")
                new_conv_id = result.get("conversation_id", "")
                new_account_id = result.get("account_id") or ""
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
                yield _err_chunk(e2)
                return
            # 重试拿到的正文要真的发出去。过去这里只赋值给 full_text（只进了持久化），
            # 客户端看到的是 role 首帧 + finish_reason=stop 的空回答。
            if full_text:
                streamed_any = True
                chunk = StreamChunk(
                    id=completion_id, model=model_name,
                    choices=[StreamChoice(delta=StreamDelta(content=full_text))],
                )
                yield format_sse(chunk.model_dump())
        else:
            if not streamed_any:
                emitted = False
                async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                    emitted = True
                    yield chunk
                if emitted:
                    return
            yield _err_chunk(e)
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
        conv.account_id = new_account_id
        conv.add_message("assistant", full_text)
        await conversation_store.update(conv)

    # 按-key 用量落账。OpenAI 流式过去从头到尾不出现 usage/estimate_tokens（四个协议里
    # 唯一的真空区）。这里**只在内部记账**，绝不往 SSE 里加 usage 帧 —— 那是线上协议的
    # 实际变更（客户端会突然开始收到 usage chunk）。
    _record_usage(model, prompt, full_text, emitted_thoughts if show_thinking else hidden.text)

    done_chunk = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")],
    )
    yield format_sse(done_chunk.model_dump())
    yield "data: [DONE]\n\n"


def _err_chunk(exc: Exception) -> str:
    """真实上游失败不能伪装成正常回答（与 v1.6.35 在 Claude 侧修的 defect ② 同类，
    这里补 OpenAI 协议的残留）：此前发 content:"Error: ..." + finish_reason="stop"，
    官方 SDK 看不到异常，会把错误文本当成模型说的话，client 的重试/故障转移/退避永远
    不会触发。改发 OpenAI 风格的 error 帧（data 帧带顶层 "error" 键）——openai SDK 的
    _streaming.py 专门检测这个键并抛 APIError，这才是流式中途报错的正确表达方式。
    复用与 Claude 侧同一份 classify_error，两个协议对同一类失败给出一致的 type。
    调用方在此之前已经先尝试过 _maybe_fallback_stream（第三方兜底），本函数只在
    兜底也未命中时才会被触达；已流出的内容不受影响（不回退已发内容）。"""
    status, err_type, _retry_after = classify_error(exc)
    chunk = {"error": {"message": str(exc), "type": err_type, "code": status}}
    return format_sse(chunk) + "data: [DONE]\n\n"


async def _stream_response_buffered(prompt: str, model: str, has_tools: bool, gemini_conv_id: str = "", conv=None, messages_raw=None, model_name: str = "", completion_id: str = "", attachments=None, base_url: str = "", request=None, req=None, gem_id=None, account_id=None, extended_thinking=False, gem_account_id=None) -> AsyncGenerator[str, None]:
    """非流式收集 + 切片伪流式：用于有工具调用/附件、需要完整文本的场景。

    account_id = 这一轮钉的账号（续接 = 会话的账号）；gem_account_id = 改发完整历史时还要钉的
    账号（只有 Gem 绑定，没有就不钉）。"""
    # 立即发出首帧 SSE，避免生图/工具路径在 generate() 阻塞期间零字节导致前置代理超时。
    first = StreamChunk(
        id=completion_id, model=model_name,
        choices=[StreamChoice(delta=StreamDelta(role="assistant"))],
    )
    yield format_sse(first.model_dump())

    async def _run_generate():
        # 思考档位照样生效（这条路径从不回传 reasoning_content，思考只进内部记账）；
        # 思考路径失败时在同一个 task 里退回不思考重试，keepalive 照常覆盖。
        return await generate_with_thinking_fallback(
            gemini_client, prompt, model, gemini_conv_id, attachments,
            gem_id=gem_id, account_id=account_id, extended_thinking=extended_thinking)

    gen_task = asyncio.create_task(_run_generate())
    try:
        async for ping in _sse_keepalive_during(gen_task):
            yield ping
    except BaseException:          # GeneratorExit / CancelledError on client disconnect
        gen_task.cancel()
        if gen_task.done() and not gen_task.cancelled():
            gen_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
        raise

    try:
        result = gen_task.result()
    except Exception as e:
        # 续接失败 → 用完整 prompt 重试；超时不重试（预算已经花完），直接兜底 / 报错。
        if gemini_conv_id and messages_raw and not is_timeout_error(e):
            # 新开会话：完整历史（带上工具说明 —— 这条路径就是为工具调用开的，丢了工具说明的
            # 回答不会是工具调用，客户端的工具循环直接断）、不带续接参数、只钉 Gem 的账号。
            full_prompt = build_prompt_from_messages(messages_raw)
            if has_tools and req is not None and req.tools:
                full_prompt = build_tool_prompt(full_prompt, [t.model_dump() for t in req.tools],
                                                req.tool_choice)
            retry_task = asyncio.create_task(
                gemini_client.generate(full_prompt, model, "", attachments,
                                       gem_id=gem_id, account_id=gem_account_id)
            )
            try:
                async for ping in _sse_keepalive_during(retry_task):
                    yield ping
            except BaseException:          # GeneratorExit / CancelledError on client disconnect
                retry_task.cancel()
                if retry_task.done() and not retry_task.cancelled():
                    retry_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
                raise
            try:
                result = retry_task.result()
            except Exception as e2:
                emitted = False
                async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                    emitted = True
                    yield chunk
                if emitted:
                    return
                yield _err_chunk(e2)
                return
            # 后面的工具 JSON 重试跟着这一轮的新会话走，别再拿旧的续接参数去敲原来的账号
            prompt, gemini_conv_id, account_id = full_prompt, "", gem_account_id
        else:
            emitted = False
            async for chunk in _maybe_fallback_stream(request, req, messages_raw, model, completion_id, model_name):
                emitted = True
                yield chunk
            if emitted:
                return
            yield _err_chunk(e)
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
        conv.account_id = result.get("account_id") or ""
        conv.add_message("assistant", text)
        await conversation_store.update(conv)

    if has_tools:
        # 此刻只发过 role 首帧 + keepalive，还没发任何 content 块，重试是安全的。
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, model, gemini_conv_id, attachments,
                                             gem_id=gem_id, account_id=account_id)
            return r.get("text", "")

        # 畸形工具 JSON 的重试要再跑一整轮上游 generate()——这条流早就开了（role 首帧已发），
        # 裸 await 会在这段已开的连接上制造一次远超单个 keepalive 间隔的死寂（issue #10
        # followup F2）。用与上面 gen_task 相同的 task + keepalive 套路续上心跳。
        parse_task = asyncio.create_task(parse_tool_response_with_retry(text, _regenerate_for_tools))
        try:
            async for ping in _sse_keepalive_during(parse_task):
                yield ping
        except BaseException:          # GeneratorExit / CancelledError on client disconnect
            parse_task.cancel()
            if parse_task.done() and not parse_task.cancelled():
                parse_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
            raise
        parsed = parse_task.result()
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

            _record_usage(model, prompt, text, result.get("thoughts") or "")
            final = StreamChunk(
                id=completion_id, model=model_name,
                choices=[StreamChoice(delta=StreamDelta(), finish_reason="tool_calls")],
            )
            yield format_sse(final.model_dump())
            yield "data: [DONE]\n\n"
            return
        text = parsed.get("content", text)

    _record_usage(model, prompt, text, result.get("thoughts") or "")

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

    requested_model = req.model or "gemini-pro"
    ensure_model_allowed(requested_model)
    model = _resolve_model(requested_model)
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
