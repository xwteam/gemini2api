import json
import time
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.account_pool import account_pool as gemini_client
from app.core.api_forwarder import forward_to_provider
from app.core.stream import split_into_chunks, format_sse
from app.models.openai import (
    ChatRequest, ChatResponse, Choice, ChoiceMessage,
    StreamChunk, StreamChoice, StreamDelta,
    ModelList, ModelInfo, UsageInfo,
)
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens
from app.utils.prompt import build_prompt_from_messages

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/openai/v1", tags=["OpenAI"])


@router.get("/models")
async def list_models(request: Request):
    models = list(gemini_client.models)
    # Also include models from API key pool
    pool = getattr(request.app.state, 'api_key_pool', None)
    if pool:
        for entry in pool.entries.values():
            if entry.status == 'active' and entry.model not in models:
                models.append(entry.model)
    now = int(time.time())
    data = [ModelInfo(id=m, created=now) for m in models]
    return ModelList(data=data)


@router.post("/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    # Check if model should be forwarded to third-party provider
    if req.model not in gemini_client.models:
        pool = getattr(request.app.state, 'api_key_pool', None)
        if pool:
            entry = pool.get_key_for_model(req.model)
            if entry:
                messages_raw = [m.model_dump() for m in req.messages]
                result = await forward_to_provider(entry, messages_raw, req)
                pool.update_last_used(entry.id)
                return result

    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw)

    has_tools = bool(req.tools)
    if has_tools:
        tools_raw = [t.model_dump() for t in req.tools]
        prompt = build_tool_prompt(prompt, tools_raw, req.tool_choice)

    if req.stream:
        return StreamingResponse(
            _stream_response(prompt, req.model, has_tools),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, req.model)
    except (RuntimeError, ValueError) as e:
        return JSONResponse(
            status_code=500 if "retry" in str(e).lower() else 400,
            content={"error": {"message": str(e), "type": "api_error"}},
        )

    text = result.get("text", "")
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

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
    )


async def _stream_response(prompt: str, model: str, has_tools: bool) -> AsyncGenerator[str, None]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    try:
        result = await gemini_client.generate(prompt, model)
    except Exception as e:
        error_chunk = StreamChunk(
            id=completion_id,
            model=model,
            choices=[StreamChoice(delta=StreamDelta(content=f"Error: {e}"), finish_reason="stop")],
        )
        yield format_sse(error_chunk.model_dump())
        yield "data: [DONE]\n\n"
        return

    text = result.get("text", "")

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
                    id=completion_id,
                    model=model,
                    choices=[StreamChoice(delta=StreamDelta(tool_calls=[tool_call_data]))],
                )
                yield format_sse(chunk.model_dump())

            final = StreamChunk(
                id=completion_id,
                model=model,
                choices=[StreamChoice(delta=StreamDelta(), finish_reason="tool_calls")],
            )
            yield format_sse(final.model_dump())
            yield "data: [DONE]\n\n"
            return
        text = parsed.get("content", text)

    first = StreamChunk(
        id=completion_id,
        model=model,
        choices=[StreamChoice(delta=StreamDelta(role="assistant"))],
    )
    yield format_sse(first.model_dump())

    async for word in split_into_chunks(text):
        chunk = StreamChunk(
            id=completion_id,
            model=model,
            choices=[StreamChoice(delta=StreamDelta(content=word))],
        )
        yield format_sse(chunk.model_dump())

    done_chunk = StreamChunk(
        id=completion_id,
        model=model,
        choices=[StreamChoice(delta=StreamDelta(), finish_reason="stop")],
    )
    yield format_sse(done_chunk.model_dump())
    yield "data: [DONE]\n\n"
