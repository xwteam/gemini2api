import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.account_pool import account_pool as gemini_client
from app.core.access_context import (
    ensure_model_allowed, filter_models_for_access_key, record_token_usage,
    with_retired_models_for_access_key,
)
from app.core.gemini_client import (GENERATION_ERRORS, classify_error,
                                    generate_with_thinking_fallback, is_timeout_error,
                                    parse_gemini_thinking_config, resolve_thinking,
                                    should_retry_without_thinking)
from app.core.thinking_stream import HiddenThoughts, drop_thought_events
from app.core.stream import split_into_chunks, iter_with_keepalive, sse_keepalive_during
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
from app.utils.tools import build_tool_prompt, parse_tool_response_with_retry, estimate_tokens, is_image_generation_intent
from app.utils.prompt import build_prompt_from_messages
from app.core.limiter import limiter, dynamic_rate_limit, rate_limit_exempt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gemini"])


def _whitelist_set() -> set[str] | None:
    """解析 MODEL_WHITELIST（逗号分隔）为集合；为空返回 None 表示不过滤。
    白名单条目按裸模型名匹配（兼容传入带 `models/` 前缀的写法）。"""
    raw = (settings.model_whitelist or "").strip()
    if not raw:
        return None
    allowed = set()
    for m in raw.split(","):
        m = m.strip()
        if not m:
            continue
        allowed.add(m[7:] if m.startswith("models/") else m)
    return allowed or None


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


def _render_function_call_part(fc: dict) -> str:
    """渲染 functionCall part，格式与 app/utils/prompt.py 里 Anthropic tool_use 分支
    的 "[Tool call: NAME(ARGS_JSON)]" 保持一致，供四协议共用同一套模型侧契约。"""
    name = fc.get("name") or ""
    args = fc.get("args")
    try:
        args_str = "" if args is None else json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        args_str = str(args)
    return f"[Tool call: {name}({args_str})]"


def _render_function_response_part(fr: dict) -> str:
    """渲染 functionResponse part，格式与 app/utils/prompt.py 里 Anthropic tool_result
    分支的 "[Tool result: TEXT]" 保持一致。"""
    resp = fr.get("response")
    if resp is None:
        resp_str = ""
    elif isinstance(resp, str):
        resp_str = resp
    else:
        try:
            resp_str = json.dumps(resp, ensure_ascii=False)
        except (TypeError, ValueError):
            resp_str = str(resp)
    return f"[Tool result: {resp_str}]"


def _last_user_text_native(contents) -> str:
    """取 req.contents（未拍平的原生 Gemini Content 列表）中最后一条 role=="user" 的纯文本，
    只收 part.text，跳过 function_call / function_response / inline_data / file_data。

    专供「生图意图」判断使用，绝不能对 _parse_contents() 拍平后的 messages 调用
    app.utils.prompt.last_user_text 来做同一件事：_parse_contents 已经把
    functionResponse 渲染成 "[Tool result: ...]" 文本揉进了同一条消息的 content 字符串
    里，字符串层面这时已经无法把"用户真正打的字"和"工具结果"分开——工具结果里随便一句
    "assets/ contains an image of a logo" 就会被 is_image_generation_intent 命中，
    客户端声明的 functionDeclarations 被静默丢弃。这正是 commit efbdd1d 在 Anthropic/OpenAI
    router 修过的缺陷，因 2c6172c 给原生 Gemini router 加上 functionResponse 渲染又重新
    引入了一次。part 类型（text vs function_call/function_response）只有在这一层、
    也就是还没拍平的 req.contents 上才分辨得出来，所以这个函数必须在这里做，
    不要为了"复用 last_user_text"或"简化"把这段过滤逻辑合并/删掉。

    与 last_user_text 保持同样的停止语义：找到最后一条 user content 就返回（哪怕它的
    text 为空——例如整条内容只有 functionResponse），不再往更早的 user 消息回退。
    没有 user 消息时返回 ""（意图判断随即为 False，即保留 tools，安全的一侧）。
    """
    for content in reversed(contents):
        if content.role != "user":
            continue
        texts = [p.text for p in content.parts if isinstance(p.text, str) and p.text]
        return " ".join(texts)
    return ""


def _parse_contents(contents):
    """从 Gemini contents 解析出 messages 和 attachments（inline_data）。

    functionCall/functionResponse part（Gemini 原生工具循环的载体）此前完全不被识别——
    只认 text part，一轮工具调用/工具结果会在拍平时整体消失，agent 循环从第二轮起断链。
    GeminiPart 的 alias_generator 已经把 camelCase/snake_case 两种入参形态统一收敛到
    同一批 snake_case 属性上，这里直接用 part.function_call / part.function_response 即可，
    不需要再分别判断两种大小写。
    """
    messages = []
    attachments = []
    idx = 0
    for content in contents:
        role = content.role
        text_parts = []
        for part in content.parts:
            if part.text:
                text_parts.append(part.text)
            elif isinstance(part.function_call, dict):
                text_parts.append(_render_function_call_part(part.function_call))
            elif isinstance(part.function_response, dict):
                text_parts.append(_render_function_response_part(part.function_response))
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


# 对外模型名的一句话说明。官方 /v1beta/models 的每条都带 description，有些 SDK / UI
# 直接把它显示给用户 —— 全给空串等于那一栏集体变空白。认不出的名字（心跳发现来的新
# family）不编描述，只说它来自账号发现，别替 Google 吹性能。
_MODEL_DESCRIPTIONS = {
    "gemini-pro": "Most capable model, for complex reasoning and long tasks",
    "gemini-flash": "Fast model with low latency, for interactive use",
    "gemini-flash-lite": "Lightest and fastest model; still available when Pro/Flash are rate-limited",
    "gemini-argon": "4 Argon, for complex tasks; listed only when an account actually has it",
    # 已下线的旧名，只会列给明确勾选过它的访问密钥（见 with_retired_models_for_access_key）
    "gemini-flash-thinking": "Retired name, now an alias of gemini-flash; pass a thinking level instead",
}
_DISCOVERED_DESCRIPTION = "Discovered from the account model list"


def _describe(model: str) -> str:
    return _MODEL_DESCRIPTIONS.get(model, _DISCOVERED_DESCRIPTION)


def _thinking_plan(req: GeminiRequest):
    """generationConfig.thinkingConfig → ThinkingPlan（见 gemini_client.resolve_thinking）。

    不传 → 上游按"默认思考档位"思考，但响应里**不加**思考部分（官方语义：只有
    includeThoughts=true 才返回思考），响应结构与不思考时逐字节一致。
    """
    config = req.generation_config.thinking_config if req.generation_config else None
    requested, show = parse_gemini_thinking_config(config)
    return resolve_thinking(requested, show=show)


def _stream_error_line(exc: Exception) -> str:
    """NDJSON 流里的错误行（buffered 与真流式共用，形态沿用原来的 {"error": {message, type}}）。

    超时按 classify_error 给 timeout_error；别的失败维持原来写死的 api_error —— 只改超时这一类，
    不顺手改其它错误在这条流里的类型。
    """
    err_type = classify_error(exc)[1] if is_timeout_error(exc) else "api_error"
    return json.dumps({"error": {"message": str(exc), "type": err_type}}) + "\n"


def _thought_part(thoughts: str) -> dict:
    """官方 wire format 的思考部分：Part.thought=true 标记这段文本是思考。"""
    return {"text": thoughts, "thought": True}


@router.get("/models")
async def list_models():
    """List available Gemini models."""
    # 这里过去写死三条 1.5 / 2.0 时代的名字，而**列表里一个契约公开名都没有**：用官方
    # Gemini SDK 接我们、先 list_models() 再从列表里挑名字的人，看不到 gemini-pro /
    # gemini-flash 这些真正该用的名字，也永远看不到新发现的模型（如 Argon）。
    # 所以改成和 /v1/models、/claude/v1/models 同一个来源（账号池的公开名）。
    # 口径说明（别把这条写错）：那三条里 gemini-1.5-pro / gemini-1.5-flash 其实**是能
    # 调通的**（MODEL_ALIASES 里有，解析到 gemini-pro / gemini-flash），只有
    # gemini-2.0-flash-exp 连别名都没有、真的调不通。它们被从**列表**里去掉是有意的
    # —— 列表该反映"账号池此刻真有什么"，而不是一张陈年别名表 —— 但**请求路径一个字
    # 都没改**：这些旧名字照旧能调，只是不再被列出来（与另外三个协议的列表口径一致）。
    models = [
        GeminiModelInfo(name=f"models/{m}", display_name=m, description=_describe(m))
        for m in with_retired_models_for_access_key(gemini_client.models)
    ]
    # MODEL_WHITELIST 过滤（为空则放行全部）；按裸模型名匹配 name 去掉 `models/` 前缀
    allowed = _whitelist_set()
    if allowed is not None:
        models = [
            m for m in models
            if (m.name[7:] if m.name.startswith("models/") else m.name) in allowed
        ]
    # 再叠一层访问密钥的 allowed_models（未限定则原样返回）
    models = [
        m for m in models
        if filter_models_for_access_key([m.name[7:] if m.name.startswith("models/") else m.name])
    ]
    return JSONResponse(content=GeminiModelList(models=models).model_dump())


@router.post("/models/{model}:generateContent")
@limiter.limit(dynamic_rate_limit, exempt_when=rate_limit_exempt)
async def generate_content(model: str, req: GeminiRequest, request: Request):
    """Generate content using Gemini API (non-streaming)."""
    if model.startswith("models/"):
        model = model[7:]
    requested_model = model

    # gem 模型解析：命中则取出 gem_id/account_id，并把对话模型换成 base_model
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            model = gem_info.get("base_model") or "gemini-pro"

    ensure_model_allowed(requested_model, model)

    messages, attachments = _parse_contents(req.contents)
    system = _parse_system(req.system_instruction)
    prompt = build_prompt_from_messages(messages, system=system)

    has_tools = False
    # 生图意图只看最后一轮用户消息，且必须在 req.contents（未拍平）这一层取——
    # messages 已经把 functionResponse 渲染进文本，字符串层面分不清工具结果和用户诉求，
    # 见 _last_user_text_native 的 docstring。
    if req.tools and not is_image_generation_intent(_last_user_text_native(req.contents)):
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend([fd.model_dump() for fd in tool.function_declarations])
        if function_declarations:
            has_tools = True
            prompt = build_tool_prompt(prompt, function_declarations)

    plan = _thinking_plan(req)
    try:
        # 思考路径失败时退回不思考重试一次（同另外三个协议的口径）。
        result = await generate_with_thinking_fallback(
            gemini_client, prompt, model, "", attachments,
            gem_id=gem_id, account_id=gem_account_id, extended_thinking=plan.upstream)
    except GENERATION_ERRORS as e:
        # 超时也在这里接住（过去冒到 ASGI 层变成纯文本 500），按 classify_error 回 504。
        status, err_type, retry_after = classify_error(e)
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        return JSONResponse(
            status_code=status,
            content={"error": {"message": str(e), "type": err_type}},
            headers=headers,
        )

    response_text = result.get("text", "")

    # 工具调用：解析成 Gemini 原生 functionCall part（而非把工具 JSON 当文本塞回去）
    tool_parts = []
    if has_tools:
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, model, "", attachments,
                                             gem_id=gem_id, account_id=gem_account_id)
            return r.get("text", "")

        parsed = await parse_tool_response_with_retry(response_text, _regenerate_for_tools)
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
    # 按-key 用量落账（只统计、不限额）。思考链计进 output：官方 API 对 thinking token
    # 按 output 计费，这里跟着官方口径走（协议回给客户端的 usageMetadata 一个字不改）。
    record_token_usage(model, prompt_tokens,
                       completion_tokens + estimate_tokens(result.get("thoughts") or ""))

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
    # 思考部分排最前，只在客户端 includeThoughts=true 时出现
    thoughts = result.get("thoughts") or ""
    if plan.show and thoughts.strip():
        parts = [_thought_part(thoughts)] + parts

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
    requested_model = model

    # gem 模型解析：命中则取出 gem_id/account_id，并把对话模型换成 base_model
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            model = gem_info.get("base_model") or "gemini-pro"

    ensure_model_allowed(requested_model, model)

    messages, attachments = _parse_contents(req.contents)
    system = _parse_system(req.system_instruction)
    prompt = build_prompt_from_messages(messages, system=system)

    has_tools = False
    # 生图意图只看最后一轮用户消息，且必须在 req.contents（未拍平）这一层取——
    # messages 已经把 functionResponse 渲染进文本，字符串层面分不清工具结果和用户诉求，
    # 见 _last_user_text_native 的 docstring。
    if req.tools and not is_image_generation_intent(_last_user_text_native(req.contents)):
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend([fd.model_dump() for fd in tool.function_declarations])
        if function_declarations:
            has_tools = True
            prompt = build_tool_prompt(prompt, function_declarations)

    plan = _thinking_plan(req)

    async def stream_generator() -> AsyncGenerator[str, None]:
        def _chunk(text: str) -> str:
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "index": 0,
                }]
            }) + "\n"

        def _thought_chunk(text: str) -> str:
            return json.dumps({
                "candidates": [{
                    "content": {"parts": [_thought_part(text)], "role": "model"},
                    "index": 0,
                }]
            }) + "\n"

        prompt_tokens = estimate_tokens(prompt)
        response_text = ""
        # 这条流里拿到的思考链（两条子路径各自填）。用于按-key 用量落账；只有客户端
        # includeThoughts=true 时才以 thought 部分回传，否则 wire format 一个字节不变。
        stream_thoughts = ""
        emitted_thoughts = ""

        # 只有「工具调用」才强制走 buffered：tool_calls 必须拿到完整 JSON 才能解析。
        # 附件不再挡在这里（底层 generate_stream 本就先上传附件再对话，下方真流式路径也已
        # 把 attachments 原样传下去），与 /v1/chat/completions 同口径。
        # generate() 阻塞期间此前零字节输出——不是空闲读超时，是首字节超时，60s 首字节限制的
        # 代理会直接杀连接。NDJSON 流不能用 SSE 注释帧保活，改发空行（与下方真流式路径同款）。
        if has_tools:
            # 思考路径失败时在同一个 task 里退回不思考重试一次（keepalive 照常覆盖）。
            gen_task = asyncio.create_task(generate_with_thinking_fallback(
                gemini_client, prompt, model, "", attachments,
                gem_id=gem_id, account_id=gem_account_id, extended_thinking=plan.upstream))
            try:
                async for _ping in sse_keepalive_during(gen_task):
                    yield "\n"
            except BaseException:          # GeneratorExit / CancelledError on client disconnect
                gen_task.cancel()
                if gen_task.done() and not gen_task.cancelled():
                    gen_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
                raise
            try:
                result = gen_task.result()
            except Exception as e:
                yield _stream_error_line(e)
                return
            response_text = result.get("text", "")
            stream_thoughts = result.get("thoughts") or ""
            if has_tools:
                # NDJSON 流此前只发过空行保活，还没发任何 candidates 块，重试是安全的。
                # 这条路径不发 functionCall（历史行为：原样把文本流回去），所以重试成功时
                # 必须改用**重试的那段文本**——否则会把首次那段畸形 JSON 原样流给客户端，
                # 比修复前（只发降级提示）更糟。未发生重试时 _retried 为空，行为逐字节不变。
                _retried = {}

                async def _regenerate_for_tools() -> str:
                    r = await gemini_client.generate(prompt, model, "", attachments,
                                                     gem_id=gem_id, account_id=gem_account_id)
                    _retried["text"] = r.get("text", "")
                    return _retried["text"]

                # 畸形工具 JSON 的重试要再跑一整轮上游 generate()——这条 NDJSON 流早就开了
                # （上面的空行保活已经发过），裸 await 会制造一次远超单个 keepalive 间隔的
                # 死寂（issue #10 followup F2）。同上面 gen_task 一样用 task + keepalive 续心跳；
                # NDJSON 不能用 SSE 注释帧，沿用同款裸换行（丢弃 ping 的实际内容只借它的节奏）。
                parse_task = asyncio.create_task(
                    parse_tool_response_with_retry(response_text, _regenerate_for_tools)
                )
                try:
                    async for _ping in sse_keepalive_during(parse_task):
                        yield "\n"
                except BaseException:          # GeneratorExit / CancelledError on client disconnect
                    parse_task.cancel()
                    if parse_task.done() and not parse_task.cancelled():
                        parse_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
                    raise
                parsed = parse_task.result()
                if isinstance(parsed, dict):
                    response_text = parsed.get("content", _retried.get("text") or response_text)
            if plan.show and stream_thoughts.strip():
                yield _thought_chunk(stream_thoughts)
            async for chunk in split_into_chunks(response_text):
                yield _chunk(chunk)
        else:
            # === 真流式路径（纯文本）===
            # 不回传的思考在 iter_with_keepalive 之前滤掉：思考期间对保活计时器就是静默，
            # 到点照发空行。否则上游每隔几秒一个 thoughts 事件，保活一个都不发，这条 NDJSON
            # 流在整段思考期间（pro 实测 36～65 秒）连首字节都没有（见 app/core/thinking_stream.py）。
            hidden = HiddenThoughts()
            upstream = gemini_client.generate_stream(prompt, model, "", attachments,
                                                     gem_id=gem_id, account_id=gem_account_id,
                                                     extended_thinking=plan.upstream)
            if not plan.show:
                upstream = drop_thought_events(upstream, hidden)
            streamed_text = False
            failure = None
            try:
                async for _kind, evt in iter_with_keepalive(upstream):
                    if _kind == "ping":
                        # NDJSON blank-line keepalive (SSE ": ping" comment is invalid on this application/json stream)
                        yield "\n"
                        continue
                    if evt.get("type") == "delta":
                        # generate_stream 现在是严格 append-only（不再发 _replace），delta 总是新增尾部
                        delta = evt.get("text", "")
                        response_text += delta
                        if delta:
                            streamed_text = True
                            yield _chunk(delta)
                    elif evt.get("type") == "thoughts":
                        # 只有 includeThoughts=true 才会到这里（不回传的已在上游一侧被滤掉）
                        t_delta = evt.get("text", "")
                        stream_thoughts += t_delta
                        if plan.show and t_delta:
                            emitted_thoughts += t_delta
                            yield _thought_chunk(t_delta)
                    elif evt.get("type") == "final":
                        stream_thoughts = evt.get("thoughts") or stream_thoughts
                        # 收尾补发思考差量（按已发前缀 diff，不重发整段；同 openai.py 口径）
                        if plan.show and stream_thoughts != emitted_thoughts \
                                and stream_thoughts.startswith(emitted_thoughts):
                            t_tail = stream_thoughts[len(emitted_thoughts):]
                            emitted_thoughts = stream_thoughts
                            if t_tail.strip():
                                yield _thought_chunk(t_tail)
                        # final.text 是过滤完占位串的完整文本，可能比已流出的 response_text
                        # 多出（流式时被 hold 住的尾部）。补发缺失尾部，保证拿到完整内容。
                        final_text = evt.get("text", response_text)
                        if final_text.startswith(response_text) and len(final_text) > len(response_text):
                            tail = final_text[len(response_text):]
                            response_text = final_text
                            if tail:
                                streamed_text = True
                                yield _chunk(tail)
                        else:
                            response_text = final_text
            except Exception as e:
                # generate_stream 在 HTTP>=400 时抛 HTTPStatusError（非 RuntimeError/ValueError 子类），
                # 故这里捕获 Exception，与 openai/claude 真流式路径一致，避免击穿生成器
                failure = e
            if not stream_thoughts:
                stream_thoughts = hidden.text

            if failure is not None and not streamed_text \
                    and should_retry_without_thinking(failure, plan.upstream):
                # 思考路径失败、还没发出任何正文：原样退回不思考、非流式重试一次（与非流式 /
                # buffered 的 generate_with_thinking_fallback、Responses 真流式同口径）。
                # 重试期间同样用空行保活。
                logger.warning(f"extended-thinking stream failed, retrying normal: {failure}")
                retry_task = asyncio.create_task(gemini_client.generate(
                    prompt, model, "", attachments,
                    gem_id=gem_id, account_id=gem_account_id, extended_thinking=False))
                try:
                    async for _ping in sse_keepalive_during(retry_task):
                        yield "\n"
                except BaseException:          # GeneratorExit / CancelledError on client disconnect
                    retry_task.cancel()
                    if retry_task.done() and not retry_task.cancelled():
                        retry_task.exception()
                    raise
                try:
                    result = retry_task.result()
                except Exception as e2:
                    failure = e2
                else:
                    failure = None
                    response_text = result.get("text", "") or ""
                    if response_text:
                        yield _chunk(response_text)

            if failure is not None:
                yield _stream_error_line(failure)
                return

        completion_tokens = estimate_tokens(response_text)
        # 按-key 用量落账（同非流式口径）。只在内部记账，wire format 一个字节不变。
        record_token_usage(model, prompt_tokens,
                           completion_tokens + estimate_tokens(stream_thoughts))

        # Google 原生 wire format 用 camelCase（finishReason/usageMetadata...），
        # 与非流式 generateContent 端点一致；snake_case 会被官方 SDK 静默忽略，
        # 导致流式端丢失 finishReason 和用量统计。
        final_chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": ""}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": completion_tokens,
                "totalTokenCount": prompt_tokens + completion_tokens,
            },
        }
        yield json.dumps(final_chunk) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/json")
