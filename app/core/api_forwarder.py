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

logger = logging.getLogger(__name__)


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
    url = f"{entry.base_url.rstrip('/')}/chat/completions"

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
                    if line.strip():
                        yield f"{line}\n"
    except httpx.RequestError as e:
        logger.error(f"Request error streaming from {provider}: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Failed to connect to {provider}: {e}', 'type': 'connection_error'}})}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error streaming from {provider}: {e}")
        yield f"data: {json.dumps({'error': {'message': f'Internal error: {e}', 'type': 'internal_error'}})}\n\n"


async def _forward_anthropic(
    entry: ApiKeyEntry,
    messages: list[dict],
    req: ChatRequest
) -> StreamingResponse | JSONResponse:
    """Forward request to Anthropic API with format conversion."""
    url = f"{entry.base_url.rstrip('/')}/v1/messages"

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
            yield "data: [DONE]\n\n"
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
