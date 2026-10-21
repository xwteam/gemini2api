"""OpenAI Responses API（POST /responses）。挂载见 app/main.py（/v1、/openai/v1 前缀）。
Gemini 路径复用 account_pool + 现有工具模拟机制；第三方模型见 responses_thirdparty.py。"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.account_pool import account_pool as gemini_client
from app.core.access_context import ensure_model_allowed, record_token_usage
from app.core.gemini_client import (GEMINI_MODELS, _resolve_model, parse_effort_request,
                                    resolve_thinking)
from app.core.responses_protocol import (
    parse_responses_input, build_responses_object, new_response_id, ResponsesStreamEncoder,
)
from app.core.thinking_stream import HiddenThoughts, drop_thought_events
from app.core.stream import iter_with_keepalive, SSE_KEEPALIVE_FRAME, sse_keepalive_during
from app.routers.openai import _images_to_markdown
from app.utils.tools import build_tool_prompt, parse_tool_response_with_retry, estimate_tokens
from app.utils.prompt import build_prompt_from_messages, extract_attachments

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Responses"])


def _error(status: int, message: str, error_type: str = "invalid_request_error",
          param: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"message": message, "type": error_type, "param": param, "code": None},
    })


def _request_params(body: dict) -> dict:
    params = {}
    for key in ("tools", "tool_choice", "temperature", "top_p", "max_output_tokens",
               "store", "truncation", "parallel_tool_calls"):
        if key in body and body[key] is not None:
            params[key] = body[key]
    return params


def _normalize_tool_choice_for_prompt(tool_choice):
    """Responses 的 tool_choice 指定工具用扁平形状 {"type":"function","name":"x"}；
    build_tool_prompt 期望嵌套形状 {"type":"function","function":{"name":"x"}}。"""
    if isinstance(tool_choice, dict) and "function" not in tool_choice and "name" in tool_choice:
        return {"type": tool_choice.get("type", "function"),
               "function": {"name": tool_choice["name"]}}
    return tool_choice


async def _build_output_items(text: str, has_tools: bool, regenerate=None) -> tuple[list[dict], str]:
    """把模型原始回复文本组装成 Responses output 数组。返回 (output_items, 剩余文本估算用)。

    ``regenerate`` 为可选的「重新取一次模型文本」闭包：工具调用 JSON 畸形时用它重试
    一次（仅一次，绝不修补截断的 JSON），见 app/utils/tools.parse_tool_response_with_retry。
    """
    output = []
    if has_tools:
        parsed = await parse_tool_response_with_retry(text, regenerate)
        if parsed["type"] == "tool_calls":
            for tc in parsed["tool_calls"]:
                output.append({
                    "id": f"fc_{uuid.uuid4().hex}", "type": "function_call", "status": "completed",
                    "call_id": f"call_{uuid.uuid4().hex[:24]}", "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                })
            return output, ""
        text = parsed.get("content", text)
    output.append({
        "id": f"msg_{uuid.uuid4().hex}", "type": "message", "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    })
    return output, text


@router.post("/responses")
async def create_response(request: Request):
    body = await request.json()
    model = body.get("model", "")
    input_data = body.get("input")
    instructions = body.get("instructions")
    stream = bool(body.get("stream", False))
    tools_raw = body.get("tools") or []
    tool_choice = _normalize_tool_choice_for_prompt(body.get("tool_choice"))
    previous_response_id = body.get("previous_response_id")

    _reasoning = body.get("reasoning") or {}
    _eff = ""
    if isinstance(_reasoning, dict):
        _eff = str(_reasoning.get("effort") or "").strip()
    if not _eff:
        _eff = str(body.get("reasoning_effort") or "").strip()
    # 与 /v1/chat/completions 同一套决策（见 gemini_client.resolve_thinking）：
    # low/medium/high 各走各的档，minimal 夹到 low、xhigh 夹到 high，none = 不思考；
    # **不传 → "默认思考档位"设置**（出厂 low），但思考只给上游用、不出 reasoning 输出项。
    _plan = resolve_thinking(parse_effort_request(_eff))
    extended_thinking = _plan.upstream
    show_thinking = _plan.show

    if previous_response_id:
        return _error(400, "previous_response_id is not supported by this server "
                          "(no server-side conversation state); resend full history in 'input'.",
                     param="previous_response_id")

    if input_data is None or (isinstance(input_data, (list, str)) and len(input_data) == 0):
        return _error(400, "input must contain at least one message", param="input")

    messages_raw = parse_responses_input(input_data, instructions)
    if not any(m.get("role") == "user" for m in messages_raw):
        return _error(400, "input must contain at least one user message", param="input")

    model_mapping = request.app.state.model_mapping
    resolved_model = model_mapping.resolve(model)
    gem_mapping = getattr(request.app.state, "gem_mapping", None)
    gem_id = None
    gem_account_id = None
    if gem_mapping:
        gem_info = gem_mapping.resolve(resolved_model)
        if gem_info:
            gem_id = gem_info.get("gem_id")
            gem_account_id = gem_info.get("account_id") or None
            resolved_model = gem_info.get("base_model") or "gemini-pro"

    ensure_model_allowed(model, resolved_model)

    request_params = _request_params(body)

    if resolved_model not in gemini_client.models and _resolve_model(resolved_model) not in GEMINI_MODELS:
        from app.core.responses_thirdparty import dispatch_thirdparty_responses
        result = await dispatch_thirdparty_responses(
            request, resolved_model, messages_raw, tools_raw, tool_choice, stream, request_params,
        )
        if result is not None:
            return result
        return _error(400, f"Model '{model}' is not a Gemini model and has no third-party "
                          f"entry configured", param="model")

    prompt = build_prompt_from_messages(messages_raw)
    has_tools = bool(tools_raw)
    if has_tools:
        prompt = build_tool_prompt(prompt, tools_raw, tool_choice)
    attachments = extract_attachments(messages_raw)

    if stream:
        return StreamingResponse(
            _stream_gemini_response(request, prompt, resolved_model, has_tools, attachments,
                                    gem_id, gem_account_id, request_params, extended_thinking,
                                    show_thinking),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                              gem_id=gem_id, account_id=gem_account_id,
                                              extended_thinking=extended_thinking)
    except Exception as e:
        # 扩展思维链路径失败：先原样退回非思维链重试一次（同 chat/completions 的兜底策略）
        if extended_thinking:
            logger.warning(f"extended-thinking request failed, retrying normal: {e}")
            show_thinking = False   # 这一轮确实没思考
            try:
                result = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                                      gem_id=gem_id, account_id=gem_account_id,
                                                      extended_thinking=False)
            except Exception as e2:
                return _error(502, str(e2), error_type="api_error")
        else:
            return _error(502, str(e), error_type="api_error")

    text = result.get("text", "")
    # AI 生成图片：沿用 chat/completions 的既有做法，Markdown 图片链接嵌入文字内容（design §4.3）
    gen_images = result.get("images") or []
    if gen_images:
        md = _images_to_markdown(gen_images, request)
        text = (md + "\n" + text.strip()) if text.strip() else md
    async def _regenerate_for_tools() -> str:
        r = await gemini_client.generate(prompt, resolved_model, "", attachments,
                                         gem_id=gem_id, account_id=gem_account_id,
                                         extended_thinking=extended_thinking)
        return r.get("text", "")

    output, _ = await _build_output_items(text, has_tools, _regenerate_for_tools)
    thoughts = result.get("thoughts") or ""
    if show_thinking and thoughts:
        output = [{"type": "reasoning", "id": new_response_id().replace("resp_", "rs_"),
                  "summary": [{"type": "summary_text", "text": thoughts}]}] + output
    usage = {"input_tokens": estimate_tokens(prompt), "output_tokens": estimate_tokens(text)}
    _record_usage(resolved_model, prompt, text, thoughts)
    obj = build_responses_object(model=resolved_model, status="completed", output=output,
                                 request_params=request_params, usage=usage,
                                 instructions=instructions)
    return JSONResponse(content=obj)


def _record_usage(model: str, prompt: str, text: str, thoughts: str = "") -> None:
    """按-key 用量落账（只统计、不限额）。

    思考链计进 output：官方 API 对 thinking token 按 output 计费，这里跟着官方口径走
    （协议回给客户端的 usage 一个字不改）。幂等由 record_token_usage 自己保证。
    ⚠️ 必须留在生成器自己的函数体里，不能挪进 asyncio.create_task 的协程。
    """
    record_token_usage(model, estimate_tokens(prompt),
                       estimate_tokens(text or "") + estimate_tokens(thoughts or ""))


async def _stream_gemini_response(request, prompt, model, has_tools, attachments, gem_id,
                                  gem_account_id, request_params, extended_thinking=False,
                                  show_thinking=False):
    response_id = new_response_id()
    enc = ResponsesStreamEncoder(response_id, model, request_params)
    yield enc.created()
    yield enc.in_progress()

    if has_tools:
        # 只有工具调用才走非流式收集（同 openai.py 的 buffered 门禁）：tool_calls 必须拿到
        # 完整 JSON 才能解析。附件不再挡在这里（底层 generate_stream 本就先上传附件再对话）。
        # Codex CLI 恒带 tools，这条分支必走——generate() 阻塞期间必须有心跳，否则首字节超时。
        gen_task = asyncio.create_task(gemini_client.generate(prompt, model, "", attachments,
                                                              gem_id=gem_id, account_id=gem_account_id,
                                                              extended_thinking=extended_thinking))
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
            # 扩展思维链路径失败：先原样退回非思维链重试一次
            if extended_thinking:
                logger.warning(f"extended-thinking stream(buffered) failed, retrying normal: {e}")
                try:
                    result = await gemini_client.generate(prompt, model, "", attachments,
                                                          gem_id=gem_id, account_id=gem_account_id,
                                                          extended_thinking=False)
                except Exception as e2:
                    yield enc.failed(str(e2))
                    return
            else:
                yield enc.failed(str(e))
                return
        text = result.get("text", "")
        thoughts = result.get("thoughts") or ""
        gen_images = result.get("images") or []
        if gen_images:
            md = _images_to_markdown(gen_images, request)
            text = (md + "\n" + text.strip()) if text.strip() else md
        # 此处只发过 created/in_progress/keepalive，还没发任何 output 块，重试是安全的。
        async def _regenerate_for_tools() -> str:
            r = await gemini_client.generate(prompt, model, "", attachments,
                                             gem_id=gem_id, account_id=gem_account_id,
                                             extended_thinking=extended_thinking)
            return r.get("text", "")

        # 畸形工具 JSON 的重试要再跑一整轮上游 generate()——这条流早就开了（created/
        # in_progress/keepalive 已发），裸 await 会在已开的连接上制造一次远超单个 keepalive
        # 间隔的死寂（issue #10 followup F2）。用与上面 gen_task 相同的 task + keepalive 续心跳。
        build_task = asyncio.create_task(_build_output_items(text, has_tools, _regenerate_for_tools))
        try:
            async for ping in sse_keepalive_during(build_task):
                yield ping
        except BaseException:          # GeneratorExit / CancelledError on client disconnect
            build_task.cancel()
            if build_task.done() and not build_task.cancelled():
                build_task.exception()   # 取回异常，避免 asyncio 在 GC 时打印 "Task exception was never retrieved"
            raise
        output, _ = build_task.result()
        for idx, item in enumerate(output):
            if item["type"] == "function_call":
                for frame in enc.function_call(item["id"], idx, item["call_id"],
                                               item["name"], item["arguments"]):
                    yield frame
            else:
                msg_id = item["id"]
                for frame in enc.text_message_start(msg_id, idx):
                    yield frame
                full_text = item["content"][0]["text"]
                for frame in enc.text_message_end(msg_id, idx, full_text):
                    yield frame
        usage = {"input_tokens": estimate_tokens(prompt), "output_tokens": estimate_tokens(text)}
        _record_usage(model, prompt, text, thoughts)
        completed_output = output
        if show_thinking and thoughts:
            completed_output = [{"type": "reasoning", "id": new_response_id().replace("resp_", "rs_"),
                                 "summary": [{"type": "summary_text", "text": thoughts}]}] + output
        yield enc.completed(completed_output, usage)
        return

    # 真流式路径：无工具/附件，逐块转发
    msg_id = f"msg_{uuid.uuid4().hex}"
    for frame in enc.text_message_start(msg_id, 0):
        yield frame
    full_text = ""
    final_images = []
    thoughts = ""
    streamed_any = False
    # 这条路径不逐帧转发思考（只在收尾的 reasoning 项里给出 final.thoughts），所以 thoughts
    # 事件一律在 iter_with_keepalive 之前滤掉：思考期间对保活计时器就是静默，到点照发保活帧。
    # 否则上游每隔几秒一个 thoughts 事件，整段思考期间一个保活帧都不发（见 thinking_stream）。
    upstream = drop_thought_events(
        gemini_client.generate_stream(prompt, model, "", attachments,
                                      gem_id=gem_id, account_id=gem_account_id,
                                      extended_thinking=extended_thinking),
        HiddenThoughts())
    try:
        async for _kind, evt in iter_with_keepalive(upstream):
            if _kind == "ping":
                yield SSE_KEEPALIVE_FRAME
                continue
            if evt.get("type") == "delta":
                delta = evt.get("text", "")
                if delta:
                    streamed_any = True
                    full_text += delta
                    yield enc.text_delta(msg_id, 0, delta)
            elif evt.get("type") == "final":
                final_text = evt.get("text", full_text)
                if final_text.startswith(full_text) and len(final_text) > len(full_text):
                    tail = final_text[len(full_text):]
                    if tail:
                        yield enc.text_delta(msg_id, 0, tail)
                full_text = final_text
                final_images = evt.get("images") or []
                thoughts = evt.get("thoughts") or ""
    except Exception as e:
        # 扩展思维链路径失败且尚未流出任何内容：退回非流式非思维链重试一次
        if extended_thinking and not streamed_any:
            logger.warning(f"extended-thinking stream failed, retrying normal: {e}")
            # 重试是一整轮非流式生成：用 task + keepalive 续心跳，别制造一段死寂
            retry_task = asyncio.create_task(gemini_client.generate(
                prompt, model, "", attachments,
                gem_id=gem_id, account_id=gem_account_id, extended_thinking=False))
            try:
                async for ping in sse_keepalive_during(retry_task):
                    yield ping
            except BaseException:          # GeneratorExit / CancelledError on client disconnect
                retry_task.cancel()
                if retry_task.done() and not retry_task.cancelled():
                    retry_task.exception()
                raise
            try:
                result = retry_task.result()
            except Exception as e2:
                yield enc.failed(str(e2))
                return
            full_text = result.get("text", "")
            final_images = result.get("images") or []
            if full_text:
                yield enc.text_delta(msg_id, 0, full_text)
        else:
            yield enc.failed(str(e))
            return

    if final_images:
        md = _images_to_markdown(final_images, request)
        full_text = (md + "\n" + full_text.strip()) if full_text.strip() else md

    for frame in enc.text_message_end(msg_id, 0, full_text):
        yield frame
    output = [{"id": msg_id, "type": "message", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": full_text, "annotations": []}]}]
    if show_thinking and thoughts:
        output = [{"type": "reasoning", "id": new_response_id().replace("resp_", "rs_"),
                  "summary": [{"type": "summary_text", "text": thoughts}]}] + output
    usage = {"input_tokens": estimate_tokens(prompt), "output_tokens": estimate_tokens(full_text)}
    _record_usage(model, prompt, full_text, thoughts)
    yield enc.completed(output, usage)
