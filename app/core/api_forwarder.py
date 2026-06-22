"""
Forward chat completion requests to third-party LLM providers.
"""

import json
import logging
import time
import uuid
from typing import AsyncGenerator

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.api_key_store import ApiKeyEntry
from app.models.openai import ChatRequest, ChatResponse, Choice, ChoiceMessage, UsageInfo, StreamChunk, StreamChoice, StreamDelta
from app.utils.net_guard import assert_safe_url, UnsafeURLError

logger = logging.getLogger(__name__)


def _build_safe_target_url(entry: ApiKeyEntry, suffix: str) -> str:
    """根据存储的 base_url 构造出站 URL，并做两道防护：
    1) base_url 缺失（None / 空串）时抛 ValueError，避免 None.rstrip 的 AttributeError 崩溃；
    2) 用 SSRF 防护（assert_safe_url）校验目标主机不指向内网 / 环回 / 链路本地 / 云元数据，
       与 fetch_models 等其他出站路径保持一致的威胁模型。

    校验失败均抛 ValueError，由调用方转成结构化 400 响应（流式 / 非流式皆然）。
    """
    base_url = getattr(entry, "base_url", None)
    if not base_url:
        raise ValueError("base_url is not configured for this API key entry")
    url = f"{base_url.rstrip('/')}{suffix}"
    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        # 不把解析到的内网 IP 回显给调用方（信息泄露），仅记日志、对外给通用提示
        logger.warning(f"[forward] blocked unsafe base_url target: {e}")
        raise ValueError("base_url is not allowed (resolves to a disallowed/internal address)")
    return url


def _bad_request(message: str) -> JSONResponse:
    """统一的 400 错误响应（用于 base_url 缺失 / SSRF 拦截）。"""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": message,
                "type": "invalid_request_error",
            }
        },
    )


def _make_async_client(timeout: float = 300.0) -> httpx.AsyncClient:
    """集中创建 httpx 客户端，便于测试注入 MockTransport。"""
    return httpx.AsyncClient(timeout=timeout)


def _build_openai_request(entry: ApiKeyEntry, messages: list[dict], req) -> tuple[str, dict, dict]:
    """构造 OpenAI 兼容 chat/completions 的 (url, headers, payload)。URL 不安全时抛 ValueError。"""
    url = _build_safe_target_url(entry, "/chat/completions")
    headers = {
        "Authorization": f"Bearer {entry.api_key}",
        "Content-Type": "application/json",
    }
    if entry.provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/gemini2api"
        headers["X-Title"] = "Gemini2API"
    payload = {
        "model": entry.model,
        "messages": messages,
        "stream": req.stream,
    }
    if req.temperature is not None:
        payload["temperature"] = req.temperature
    if req.max_tokens is not None:
        payload["max_tokens"] = req.max_tokens
    if req.tools:
        payload["tools"] = [t.model_dump() for t in req.tools]
    if req.tool_choice is not None:
        payload["tool_choice"] = req.tool_choice
    effort = getattr(entry, "reasoning_effort", None)
    if effort:
        payload["reasoning_effort"] = effort
    return url, headers, payload


async def forward_to_provider(
    entry: ApiKeyEntry,
    messages: list[dict],
    req: ChatRequest
) -> StreamingResponse | JSONResponse:
    """
    Forward a chat completion request to the appropriate third-party provider.

    Args:
        entry: API key entry containing provider info and credentials
        messages: Raw messages list from the original request
        req: Original ChatRequest object

    Returns:
        StreamingResponse for streaming requests, JSONResponse otherwise
    """
    provider = entry.provider.lower()

    if provider in ("openai", "openrouter", "custom"):
        return await _forward_openai_compatible(entry, messages, req)
    elif provider == "anthropic":
        return await _forward_anthropic(entry, messages, req)
    elif provider == "gemini":
        return await _forward_gemini_api(entry, messages, req)
    else:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": f"Unsupported provider: {provider}",
                    "type": "invalid_request_error"
                }
            }
        )


async def _forward_openai_compatible(
    entry: ApiKeyEntry,
    messages: list[dict],
    req: ChatRequest
) -> StreamingResponse | JSONResponse:
    """Forward request to OpenAI-compatible endpoint."""
    try:
        url, headers, payload = _build_openai_request(entry, messages, req)
    except ValueError as e:
        return _bad_request(str(e))

    if req.stream:
        # 关键修复：client 生命周期交给流生成器内部（async with），
        # 避免「函数返回即关闭 client，生成器迭代时连接已关」导致流式转发失效。
        return StreamingResponse(
            _proxy_openai_stream(url, headers, payload, entry.provider),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return JSONResponse(content=response.json())

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error forwarding to {entry.provider}: {e}")
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = {"error": {"message": str(e), "type": "api_error"}}
        return JSONResponse(status_code=e.response.status_code, content=error_detail)

    except httpx.RequestError as e:
        logger.error(f"Request error forwarding to {entry.provider}: {e}")
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Failed to connect to {entry.provider}: {str(e)}",
                    "type": "connection_error"
                }
            }
        )

    except Exception as e:
        logger.error(f"Unexpected error forwarding to {entry.provider}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": f"Internal error: {str(e)}",
                    "type": "internal_error"
                }
            }
        )


async def _proxy_openai_stream(
    url: str, headers: dict, payload: dict, provider: str
) -> AsyncGenerator[str, None]:
    """Proxy OpenAI-compatible SSE stream as-is.

    生成器自身持有 httpx client 与流连接的生命周期（async with），
    保证流式期间连接存活（修复「client 提前关闭、迭代时连接已关」的失效）。
    """
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    try:
                        detail = json.loads(body)
                    except Exception:
                        detail = {"error": {"message": body.decode("utf-8", "replace")[:500],
                                            "type": "api_error"}}
                    yield f"data: {json.dumps(detail)}\n\n"
                    return
                async for line in response.aiter_lines():
                    # 修复：aiter_lines() 基于 splitlines() 已剥离行尾，并把 SSE 事件分隔的空行
                    # 作为 "" 单独产出。原代码 `yield f"{line}\n"` 丢弃空行且只补一个 \n，
                    # 导致下游收到的多个 data: 行之间没有空行分隔，被合并成一个未结束的事件，
                    # 严格 SSE 客户端无法增量解析。这里对每个非空行补回 "\n\n"（含 data: [DONE]），
                    # 恢复合法的 SSE 事件帧。
                    if line.strip():
                        yield f"{line}\n\n"
    except httpx.RequestError as e:
        logger.error(f"Request error streaming from {provider}: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Failed to connect to {provider}: {e}', 'type': 'connection_error'}})}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error streaming from {provider}: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Internal error: {e}', 'type': 'internal_error'}})}\n\n"


async def open_openai_stream(
    entry: ApiKeyEntry, messages: list[dict], req
) -> tuple[StreamingResponse | None, JSONResponse | None]:
    """OpenAI 兼容流式 pre-flight：先建连读响应头，状态<400 才提交流（让上层在开口前换家）。
    成功 -> (StreamingResponse, None)；失败 -> (None, JSONResponse 错误)。"""
    try:
        url, headers, payload = _build_openai_request(entry, messages, req)
    except ValueError as e:
        return None, _bad_request(str(e))

    client = _make_async_client(300.0)
    try:
        cm = client.stream("POST", url, headers=headers, json=payload)
        response = await cm.__aenter__()
    except httpx.RequestError as e:
        await client.aclose()
        return None, JSONResponse(
            status_code=502,
            content={"error": {"message": f"Failed to connect to {entry.provider}: {e}",
                               "type": "connection_error"}},
        )
    except Exception as e:  # noqa: BLE001
        await client.aclose()
        return None, JSONResponse(
            status_code=500,
            content={"error": {"message": f"Internal error: {e}", "type": "internal_error"}},
        )

    if response.status_code >= 400:
        body = await response.aread()
        await cm.__aexit__(None, None, None)
        await client.aclose()
        try:
            detail = json.loads(body)
        except Exception:
            detail = {"error": {"message": body.decode("utf-8", "replace")[:500], "type": "api_error"}}
        return None, JSONResponse(status_code=response.status_code, content=detail)

    async def _drain():
        try:
            async for line in response.aiter_lines():
                if line.strip():
                    yield f"{line}\n\n"
        finally:
            await cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        _drain(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    ), None


async def open_stream(
    entry: ApiKeyEntry, messages: list[dict], req
) -> tuple[StreamingResponse | None, JSONResponse | None]:
    """供分发器使用的统一流式入口：openai 兼容走 pre-flight 故障切换；其余 provider 直接提交。"""
    if entry.provider.lower() in ("openai", "openrouter", "custom"):
        return await open_openai_stream(entry, messages, req)
    return await forward_to_provider(entry, messages, req), None


async def _forward_anthropic(
    entry: ApiKeyEntry,
    messages: list[dict],
    req: ChatRequest
) -> StreamingResponse | JSONResponse:
    """Forward request to Anthropic API with format conversion."""
    # 修复：同 openai 路径——防 None base_url 崩溃 + SSRF 校验，失败转成结构化 400。
    try:
        url = _build_safe_target_url(entry, "/v1/messages")
    except ValueError as e:
        return _bad_request(str(e))

    headers = {
        "x-api-key": entry.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    # Extract system message if present
    system_message = None
    anthropic_messages = []

    for msg in messages:
        if msg["role"] == "system":
            system_message = msg["content"]
        else:
            # Anthropic requires alternating user/assistant messages
            anthropic_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    payload = {
        "model": entry.model,
        "messages": anthropic_messages,
        "max_tokens": req.max_tokens or 4096,
        "stream": req.stream,
    }

    if system_message:
        payload["system"] = system_message

    if req.tools:
        anthropic_tools = []
        for tool in req.tools:
            tool_dict = tool.model_dump()
            anthropic_tools.append({
                "name": tool_dict["function"]["name"],
                "description": tool_dict["function"].get("description", ""),
                "input_schema": tool_dict["function"].get("parameters", {})
            })
        payload["tools"] = anthropic_tools

    if req.stream:
        # 关键修复：同 openai 流式，client 生命周期交给流生成器内部，保证流式期间连接存活
        return StreamingResponse(
            _convert_anthropic_stream(url, headers, payload, entry.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            anthropic_response = response.json()

            # Convert Anthropic response to OpenAI format
            openai_response = _convert_anthropic_to_openai(anthropic_response, entry.model)
            return JSONResponse(content=openai_response)

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error forwarding to Anthropic: {e}")
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = {"error": {"message": str(e), "type": "api_error"}}
        return JSONResponse(status_code=e.response.status_code, content=error_detail)

    except httpx.RequestError as e:
        logger.error(f"Request error forwarding to Anthropic: {e}")
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Failed to connect to Anthropic: {str(e)}",
                    "type": "connection_error"
                }
            }
        )

    except Exception as e:
        logger.error(f"Unexpected error forwarding to Anthropic: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": f"Internal error: {str(e)}",
                    "type": "internal_error"
                }
            }
        )


def _convert_anthropic_to_openai(anthropic_response: dict, model: str) -> dict:
    """Convert Anthropic response format to OpenAI format."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # Extract content
    content_blocks = anthropic_response.get("content", [])
    text_content = ""
    tool_calls = []

    for block in content_blocks:
        if block.get("type") == "text":
            text_content += block.get("text", "")
        elif block.get("type") == "tool_use":
            call_id = block.get("id", f"call_{uuid.uuid4().hex[:8]}")
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}))
                }
            })

    # Build message
    message = {"role": "assistant"}
    if text_content:
        message["content"] = text_content
    if tool_calls:
        message["tool_calls"] = tool_calls

    # Determine finish reason
    stop_reason = anthropic_response.get("stop_reason", "end_turn")
    finish_reason_map = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "stop_sequence": "stop"
    }
    finish_reason = finish_reason_map.get(stop_reason, "stop")

    # Build usage
    usage_data = anthropic_response.get("usage", {})
    usage = {
        "prompt_tokens": usage_data.get("input_tokens", 0),
        "completion_tokens": usage_data.get("output_tokens", 0),
        "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)
    }

    return {
        "id": completion_id,
        "object": "chat.completion",
        # 修复：Anthropic 消息 id 形如 msg_01AbC...（非数字尾），原 int(id.split("_")[-1])
        # 必抛 ValueError 致非流式转发恒 500。created 语义即响应生成时间，直接用当前时间戳。
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason
        }],
        "usage": usage
    }


async def _convert_anthropic_stream(
    url: str, headers: dict, payload: dict, model: str
) -> AsyncGenerator[str, None]:
    """Convert Anthropic SSE stream to OpenAI format.

    生成器自身持有 httpx client 与流连接的生命周期（async with），保证流式期间连接存活
    （修复「client 提前关闭、迭代时连接已关」的失效）。
    """
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    try:
                        detail = json.loads(body)
                    except Exception:
                        detail = {"error": {"message": body.decode("utf-8", "replace")[:500],
                                            "type": "api_error"}}
                    yield f"data: {json.dumps(detail)}\n\n"
                    return
                async for chunk in _anthropic_stream_to_openai(response, model):
                    yield chunk
    except httpx.RequestError as e:
        logger.error(f"Request error streaming from Anthropic: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Failed to connect to Anthropic: {e}', 'type': 'connection_error'}})}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error streaming from Anthropic: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Internal error: {e}', 'type': 'internal_error'}})}\n\n"


async def _anthropic_stream_to_openai(response: httpx.Response, model: str) -> AsyncGenerator[str, None]:
    """把已建立的 Anthropic SSE 响应逐行转换为 OpenAI chunk（内部 helper，连接由调用方持有）。"""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    async for line in response.aiter_lines():
        if not line.strip() or not line.startswith("data: "):
            continue

        data_str = line[6:]  # Remove "data: " prefix

        if data_str == "[DONE]":
            # Anthropic 实际不发该哨兵（以 message_stop 结束），此分支仅为兼容性保留。
            # 真正的 [DONE] 在循环结束后统一补发，故这里只 break，不重复 yield。
            break

        try:
            event = json.loads(data_str)
            event_type = event.get("type")

            if event_type == "message_start":
                # Send initial chunk with role
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            elif event_type == "message_delta":
                stop_reason = event.get("delta", {}).get("stop_reason")
                if stop_reason:
                    finish_reason_map = {
                        "end_turn": "stop",
                        "max_tokens": "length",
                        "tool_use": "tool_calls",
                        "stop_sequence": "stop"
                    }
                    finish_reason = finish_reason_map.get(stop_reason, "stop")

                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish_reason
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

        except json.JSONDecodeError:
            continue

    # 修复：Anthropic Messages 流以 message_stop 结束、从不发送 data: [DONE]，
    # 而 OpenAI 客户端期望以 [DONE] 标记流结束。上游流自然结束后无条件补发终止哨兵，
    # 避免严格客户端（等待 [DONE] 才判定完成的 SDK）挂起 / 误判未完成。
    yield "data: [DONE]\n\n"


async def _forward_gemini_api(
    entry: ApiKeyEntry,
    messages: list[dict],
    req: ChatRequest
) -> StreamingResponse | JSONResponse:
    """Forward request to Gemini official API (stub)."""
    return JSONResponse(
        status_code=501,
        content={
            "error": {
                "message": "Gemini official API forwarding not yet implemented",
                "type": "not_implemented_error"
            }
        }
    )
