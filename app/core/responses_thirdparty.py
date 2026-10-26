"""第三方模型（API 管理配置的、非 Gemini）走 /v1/responses 的适配层：
把 Responses 输入转成现有 ChatRequest 格式发给 forward_to_provider/open_stream（零改动复用），
再把返回的 Chat 补全结果转换回 Responses 输出格式。"""
import json
import time
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.core.api_forwarder import empty_upstream_error, forward_to_provider, open_stream, run_failover
from app.core.fallback import openai_data_is_empty
from app.models.openai import ChatRequest, ChatMessage, ToolDef, ToolFunction
from app.core.responses_protocol import build_responses_object, new_response_id, ResponsesStreamEncoder
from app.core.stream import SSE_KEEPALIVE_FRAME, SSE_KEEPALIVE_INTERVAL


def _to_chat_messages(messages_raw: list[dict]) -> list[ChatMessage]:
    return [ChatMessage(role=m.get("role", "user"), content=m.get("content", ""),
                        name=m.get("name"), tool_calls=m.get("tool_calls"),
                        tool_call_id=m.get("tool_call_id"))
            for m in messages_raw]


def _to_tool_defs(tools_raw: list[dict]) -> list[ToolDef] | None:
    """只转 function 工具。Codex 等客户端还会带 web_search / local_shell / custom 之类的内置工具，
    第三方的 chat 接口不认，转成空名字的 function 发过去只会整单 400。"""
    if not tools_raw:
        return None
    defs = []
    for t in tools_raw:
        if not isinstance(t, dict) or t.get("type", "function") != "function":
            continue
        func = t.get("function", t)  # 兼容扁平/嵌套两种形状
        if not func.get("name"):
            continue
        defs.append(ToolDef(type="function", function=ToolFunction(
            name=func["name"], description=func.get("description") or "",
            parameters=func.get("parameters") or func.get("input_schema") or {},
        )))
    return defs or None


def _tool_choice_for(tool_defs, tool_choice):
    """没有可发的 function 工具时不带 tool_choice（OpenAI 规定 tool_choice 只能和 tools 一起出现）；
    指向内置工具（{"type": "web_search"} 之类）的 tool_choice 同样丢掉。"""
    if not tool_defs:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type", "function") != "function":
        return None
    return tool_choice


def _call_id(raw_id) -> str:
    return raw_id or f"call_{uuid.uuid4().hex[:24]}"


def _arguments_json(args) -> str:
    if isinstance(args, str):
        return args or "{}"
    return "{}" if args is None else json.dumps(args, ensure_ascii=False)


def _chat_response_to_responses_object(chat_body: dict, model: str, request_params: dict) -> dict:
    choice = (chat_body.get("choices") or [{}])[0]
    message = choice.get("message", {})
    output = []
    tool_calls = [tc for tc in (message.get("tool_calls") or []) if isinstance(tc, dict)]
    text = message.get("content", "") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    # 文本和工具调用可以同时有（「我先看一下目录」+ 调 shell）：文本作为 message 项在前，调用跟在后面
    if text or not tool_calls:
        output.append({
            "id": f"msg_{chat_body.get('id', 'x')}", "type": "message", "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        })
    for tc in tool_calls:
        func = tc.get("function") or {}
        call_id = _call_id(tc.get("id"))
        output.append({
            "id": f"fc_{call_id}", "type": "function_call", "status": "completed",
            "call_id": call_id, "name": func.get("name", ""),
            "arguments": _arguments_json(func.get("arguments")),
        })
    usage_raw = chat_body.get("usage", {})
    usage = {"input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0)}
    return build_responses_object(model=model, status="completed", output=output,
                                  request_params=request_params, usage=usage)


async def _dispatch_non_stream(request, resolved_model, messages_raw, tools_raw, tool_choice,
                               request_params, entries, pool):
    tool_defs = _to_tool_defs(tools_raw)
    chat_req = ChatRequest(model=resolved_model, messages=_to_chat_messages(messages_raw),
                          stream=False, tools=tool_defs, tool_choice=_tool_choice_for(tool_defs, tool_choice),
                          temperature=request_params.get("temperature"),
                          max_tokens=request_params.get("max_output_tokens"))

    async def attempt(entry):
        resp = await forward_to_provider(entry, messages_raw, chat_req)
        if isinstance(resp, JSONResponse) and getattr(resp, "status_code", 200) < 400:
            body = resp.body
            if isinstance(body, (bytes, bytearray)):
                body = body.decode("utf-8", "replace")
            try:
                chat_body = json.loads(body)
            except Exception:
                chat_body = None
            if chat_body is not None and not openai_data_is_empty(chat_body):
                obj = _chat_response_to_responses_object(chat_body, resolved_model, request_params)
                return JSONResponse(content=obj), None
            return None, empty_upstream_error()
        return None, resp

    # 冷却与"全败回哪个错误"的规则与 /v1/chat/completions 共用（api_forwarder.run_failover）
    ok, error = await run_failover(entries, attempt, pool, settings.thirdparty_failover_cooldown)
    return ok if ok is not None else error


async def dispatch_thirdparty_responses(request, resolved_model, messages_raw, tools_raw,
                                        tool_choice, stream, request_params):
    pool = getattr(request.app.state, "api_key_pool", None)
    if not pool:
        return None
    entries = pool.get_entries_for_model(resolved_model)
    if not entries:
        return None
    if stream:
        return StreamingResponse(
            _dispatch_stream(request, resolved_model, messages_raw, tools_raw,
                             tool_choice, request_params, entries, pool),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await _dispatch_non_stream(request, resolved_model, messages_raw, tools_raw,
                                      tool_choice, request_params, entries, pool)


async def _dispatch_stream(request, resolved_model, messages_raw, tools_raw, tool_choice,
                           request_params, entries, pool):
    tool_defs = _to_tool_defs(tools_raw)
    chat_req = ChatRequest(model=resolved_model, messages=_to_chat_messages(messages_raw),
                          stream=True, tools=tool_defs, tool_choice=_tool_choice_for(tool_defs, tool_choice),
                          temperature=request_params.get("temperature"),
                          max_tokens=request_params.get("max_output_tokens"))
    response_id = new_response_id()
    enc = ResponsesStreamEncoder(response_id, resolved_model, request_params)
    yield enc.created()
    yield enc.in_progress()

    async def attempt(entry):
        return await open_stream(entry, messages_raw, chat_req)

    stream_resp, error = await run_failover(entries, attempt, pool,
                                            settings.thirdparty_failover_cooldown)
    if stream_resp is None:
        status = getattr(error, "status_code", "?")
        yield enc.failed(f"all third-party candidates failed to open a stream (best error: HTTP {status})")
        return

    msg_id = f"msg_{new_response_id()}"
    started = False
    full_text = ""
    # 上游流式的工具调用增量（OpenAI 形态：按 index 分槽，id / name 只在第一片，arguments 分片拼接）。
    # 过去这里只看 content，模型发起的工具调用整个丢掉 —— Codex（恒流式）的工具循环根本跑不起来。
    # 有的上游并行调用全给 index 0、或者干脆不给 index：带了与当前槽不同的 id 就另开一槽；没有 index
    # 的续片接在最后一槽后面。
    calls: list[dict] = []
    by_index: dict[int, dict] = {}
    # 工具调用要攒到最后才发：攒的这段（长补丁可能几十秒）按保活间隔发心跳，免得被中间代理当空闲掐断
    last_out = time.monotonic()
    buf = ""
    async for raw in stream_resp.body_iterator:
        buf += raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            line = frame.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                continue
            try:
                chunk = json.loads(payload)
            except Exception:
                continue
            delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index") if isinstance(tc.get("index"), int) else None
                tc_id = tc.get("id") or ""
                slot = by_index.get(idx) if idx is not None else (calls[-1] if calls else None)
                if slot is None or (tc_id and slot["id"] and tc_id != slot["id"]):
                    slot = {"id": "", "name": "", "arguments": ""}
                    calls.append(slot)
                    if idx is not None:
                        by_index[idx] = slot
                fn = tc.get("function") or {}
                slot["id"] = slot["id"] or tc_id
                slot["name"] = slot["name"] or (fn.get("name") or "")
                if isinstance(fn.get("arguments"), str):
                    slot["arguments"] += fn["arguments"]
            text_piece = delta.get("content") or ""
            if text_piece:
                if not started:
                    for frame_out in enc.text_message_start(msg_id, 0):
                        yield frame_out
                    started = True
                full_text += text_piece
                yield enc.text_delta(msg_id, 0, text_piece)
                last_out = time.monotonic()
            elif time.monotonic() - last_out >= SSE_KEEPALIVE_INTERVAL:
                yield SSE_KEEPALIVE_FRAME
                last_out = time.monotonic()

    function_calls = [slot for slot in calls if slot["name"]]
    output = []
    # 有文本、或者什么都没有时才出 message 项（只有工具调用的回合不塞一个空 message）
    if started or not function_calls:
        if not started:
            for frame_out in enc.text_message_start(msg_id, 0):
                yield frame_out
        for frame_out in enc.text_message_end(msg_id, 0, full_text):
            yield frame_out
        output.append({"id": msg_id, "type": "message", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": full_text, "annotations": []}]})
    for slot in function_calls:
        call_id = _call_id(slot["id"])
        item_id = f"fc_{call_id}"
        arguments = _arguments_json(slot["arguments"])
        for frame_out in enc.function_call(item_id, len(output), call_id, slot["name"], arguments):
            yield frame_out
        output.append({"id": item_id, "type": "function_call", "status": "completed",
                       "call_id": call_id, "name": slot["name"], "arguments": arguments})
    yield enc.completed(output, usage={"input_tokens": 0, "output_tokens": 0})
