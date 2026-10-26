"""OpenAI Responses API（/v1/responses）协议纯函数：input 解析、响应组装、流式事件编码。
无状态，不碰账号池/网络——生成本身仍由 account_pool.generate/generate_stream 完成。"""
import json
import time
import uuid


def _content_part_to_chat_shape(part: dict) -> dict | None:
    """Responses 内容块 -> 内部（chat 兼容）内容块。input_text/output_text -> text；
    input_image -> OpenAI 的 image_url 形状（供 extract_attachments 识别）。"""
    ptype = part.get("type")
    if ptype in ("input_text", "output_text"):
        return {"type": "text", "text": part.get("text", "")}
    if ptype == "input_image":
        url = part.get("image_url")
        if isinstance(url, dict):
            url = url.get("url", "")
        return {"type": "image_url", "image_url": {"url": url}}
    return None


def _message_item_to_internal(item: dict) -> dict:
    role = item.get("role", "user")
    content = item.get("content")
    if isinstance(content, str):
        return {"role": role, "content": content}
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            converted = _content_part_to_chat_shape(part)
            if converted:
                parts.append(converted)
        return {"role": role, "content": parts}
    return {"role": role, "content": ""}


def _input_item_to_internal(item: dict) -> dict | None:
    itype = item.get("type")
    if itype in (None, "message"):
        return _message_item_to_internal(item)
    if itype == "function_call":
        name = item.get("name", "")
        arguments = item.get("arguments", "")
        return {"role": "assistant",
                "content": f"(called tool {name} with arguments {arguments})"}
    if itype in ("function_call_output", "tool_result"):
        output = item.get("output", item.get("content", ""))
        return {"role": "tool", "content": output}
    return None


def _tool_output_text(output) -> str:
    """function_call_output 的 output：字符串原样；内容块数组取其中的文本；其它序列化成 JSON。"""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(p["text"] for p in output
                         if isinstance(p, dict) and isinstance(p.get("text"), str))
    return "" if output is None else json.dumps(output, ensure_ascii=False)


def _flat_text(content) -> str | None:
    """assistant 文本内容（字符串或文本块数组）→ 字符串；没有文本时 None（OpenAI 的工具调用轮次形态）。"""
    if isinstance(content, list):
        content = "\n".join(p["text"] for p in content
                            if isinstance(p, dict) and isinstance(p.get("text"), str))
    return content or None


def _append_native_tool_item(messages: list[dict], item: dict) -> bool:
    """第三方路径：function_call / function_call_output 转成 OpenAI chat 的原生形态
    （assistant.tool_calls + 带 tool_call_id 的 tool 消息）。处理了返回 True。

    严格按 OpenAI SDK 校验的上游（书生端砚的 deepseek / glm / kimi / qwen 等）不认「assistant 纯文本
    描述的调用 + 不带 tool_call_id 的 tool 消息」，Codex 的工具循环第二轮必 400。连续的调用（并行
    工具调用）、以及紧跟在 assistant 文本后面的调用，并进同一条 assistant 消息。
    """
    itype = item.get("type")
    if itype == "function_call":
        args = item.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        call = {"id": item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {"name": item.get("name") or "", "arguments": args or "{}"}}
        last = messages[-1] if messages else None
        if last is not None and last.get("role") == "assistant":
            last["content"] = _flat_text(last.get("content"))
            last["tool_calls"] = [*(last.get("tool_calls") or []), call]
        else:
            messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        return True
    if itype in ("function_call_output", "tool_result"):
        call_id = item.get("call_id") or item.get("tool_use_id") or item.get("id") or ""
        messages.append({"role": "tool", "tool_call_id": call_id,
                         "content": _tool_output_text(item.get("output", item.get("content", "")))})
        return True
    return False


def parse_responses_input(input_data, instructions: str | None = None, *,
                          native_tool_calls: bool = False) -> list[dict]:
    """Responses 的 input → 内部 chat 形态的 messages。

    native_tool_calls=False（Gemini 路径，默认）：工具调用与结果拍成文本，Gemini 的 prompt 拼装不变。
    native_tool_calls=True（第三方路径）：转成 OpenAI chat 原生的 tool_calls / tool_call_id。
    """
    messages: list[dict] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})

    if isinstance(input_data, str):
        messages.append({"role": "user", "content": input_data})
        return messages

    items = input_data if isinstance(input_data, list) else [input_data]
    for item in items:
        if not isinstance(item, dict):
            continue
        if native_tool_calls and _append_native_tool_item(messages, item):
            continue
        converted = _input_item_to_internal(item)
        if converted:
            messages.append(converted)
    return messages


def new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def _nested_usage(usage: dict | None) -> dict:
    usage = usage or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": usage.get("cached_tokens", 0)},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": usage.get("reasoning_tokens", 0)},
        "total_tokens": input_tokens + output_tokens,
    }


_ECHO_KEYS = ("tools", "tool_choice", "temperature", "top_p", "max_output_tokens",
              "store", "truncation", "parallel_tool_calls")


def build_responses_object(*, model: str, status: str, output: list[dict],
                           request_params: dict, usage: dict | None = None,
                           previous_response_id: str | None = None,
                           instructions: str | None = None,
                           error: dict | None = None) -> dict:
    obj = {
        "id": new_response_id(),
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": output,
        "usage": _nested_usage(usage),
        "previous_response_id": previous_response_id,
        "instructions": instructions,
        "error": error,
    }
    for key in _ECHO_KEYS:
        if key in request_params:
            obj[key] = request_params[key]
    return obj


class ResponsesStreamEncoder:
    """流式 SSE 事件编码器：严格按官方顺序 + 递增 sequence_number，
    修正参考实现（kiro-go）漏发的 output_text.done / function_call_arguments.done，
    且不发送 [DONE]（新协议完成信号是 response.completed）。"""

    def __init__(self, response_id: str, model: str, request_params: dict):
        self._response_id = response_id
        self._model = model
        self._request_params = request_params
        self._seq = 0

    def _send(self, event_type: str, payload: dict) -> str:
        body = dict(payload)
        body["type"] = event_type
        body["sequence_number"] = self._seq
        self._seq += 1
        return f"event: {event_type}\ndata: {json.dumps(body)}\n\n"

    def created(self) -> str:
        obj = build_responses_object(model=self._model, status="in_progress", output=[],
                                     request_params=self._request_params)
        obj["id"] = self._response_id
        return self._send("response.created", {"response": obj})

    def in_progress(self) -> str:
        obj = build_responses_object(model=self._model, status="in_progress", output=[],
                                     request_params=self._request_params)
        obj["id"] = self._response_id
        return self._send("response.in_progress", {"response": obj})

    def text_message_start(self, item_id: str, output_index: int) -> list[str]:
        item = {"id": item_id, "type": "message", "role": "assistant",
               "status": "in_progress", "content": []}
        frames = [self._send("response.output_item.added",
                             {"output_index": output_index, "item": item})]
        part = {"type": "output_text", "text": "", "annotations": []}
        frames.append(self._send("response.content_part.added",
                                 {"item_id": item_id, "output_index": output_index,
                                  "content_index": 0, "part": part}))
        return frames

    def text_delta(self, item_id: str, output_index: int, delta: str) -> str:
        return self._send("response.output_text.delta",
                          {"item_id": item_id, "output_index": output_index,
                           "content_index": 0, "delta": delta})

    def text_message_end(self, item_id: str, output_index: int, full_text: str) -> list[str]:
        frames = [self._send("response.output_text.done",
                             {"item_id": item_id, "output_index": output_index,
                              "content_index": 0, "text": full_text})]
        part = {"type": "output_text", "text": full_text, "annotations": []}
        frames.append(self._send("response.content_part.done",
                                 {"item_id": item_id, "output_index": output_index,
                                  "content_index": 0, "part": part}))
        item = {"id": item_id, "type": "message", "role": "assistant", "status": "completed",
               "content": [part]}
        frames.append(self._send("response.output_item.done",
                                 {"output_index": output_index, "item": item}))
        return frames

    def function_call(self, item_id: str, output_index: int, call_id: str,
                      name: str, arguments_json: str) -> list[str]:
        added_item = {"id": item_id, "type": "function_call", "status": "in_progress",
                     "call_id": call_id, "name": name, "arguments": ""}
        frames = [self._send("response.output_item.added",
                             {"output_index": output_index, "item": added_item})]
        frames.append(self._send("response.function_call_arguments.delta",
                                 {"item_id": item_id, "output_index": output_index,
                                  "delta": arguments_json}))
        frames.append(self._send("response.function_call_arguments.done",
                                 {"item_id": item_id, "output_index": output_index,
                                  "arguments": arguments_json}))
        done_item = {"id": item_id, "type": "function_call", "status": "completed",
                    "call_id": call_id, "name": name, "arguments": arguments_json}
        frames.append(self._send("response.output_item.done",
                                 {"output_index": output_index, "item": done_item}))
        return frames

    def completed(self, output: list[dict], usage: dict) -> str:
        obj = build_responses_object(model=self._model, status="completed", output=output,
                                     request_params=self._request_params, usage=usage)
        obj["id"] = self._response_id
        return self._send("response.completed", {"response": obj})

    def failed(self, message: str, code: str = "internal_error") -> str:
        obj = build_responses_object(model=self._model, status="failed", output=[],
                                     request_params=self._request_params,
                                     error={"code": code, "message": message})
        obj["id"] = self._response_id
        return self._send("response.failed", {"response": obj})
