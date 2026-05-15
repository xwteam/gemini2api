import time
import uuid
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.gemini_client import gemini_client
from app.core.stream import split_into_chunks, format_sse
from app.models.claude import (
    ClaudeRequest, ClaudeResponse, ContentBlock, ClaudeUsage,
    ClaudeModelInfo, ClaudeModelList,
)
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens
from app.utils.prompt import build_prompt_from_messages

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/claude/v1", tags=["Claude"])


@router.get("/models")
async def list_models():
    models = gemini_client.models
    data = [
        ClaudeModelInfo(
            id=m,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            display_name=m,
        )
        for m in models
    ]
    return ClaudeModelList(data=data)


@router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    if model_id not in gemini_client.models:
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
async def create_message(req: ClaudeRequest):
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)

    has_tools = bool(req.tools)
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
            _stream_claude(prompt, req.model, has_tools),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await gemini_client.generate(prompt, req.model)
    except (RuntimeError, ValueError) as e:
        return JSONResponse(
            status_code=500 if "retry" in str(e).lower() else 400,
            content={"type": "error", "error": {"type": "api_error", "message": str(e)}},
        )

    text = result.get("text", "")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    if has_tools:
        parsed = parse_tool_response(text)
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

    return ClaudeResponse(
        id=msg_id,
        model=req.model,
        content=[ContentBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=ClaudeUsage(
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
        ),
    )


@router.post("/messages/count_tokens")
async def count_tokens(req: ClaudeRequest):
    messages_raw = [m.model_dump() for m in req.messages]
    prompt = build_prompt_from_messages(messages_raw, system=req.system)
    count = estimate_tokens(prompt)
    return {"input_tokens": count}


async def _stream_claude(prompt: str, model: str, has_tools: bool) -> AsyncGenerator[str, None]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    try:
        result = await gemini_client.generate(prompt, model)
    except Exception as e:
        yield format_sse({"type": "error", "error": {"type": "api_error", "message": str(e)}})
        return

    text = result.get("text", "")

    yield format_sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "usage": {"input_tokens": estimate_tokens(prompt), "output_tokens": 0},
        },
    })

    if has_tools:
        parsed = parse_tool_response(text)
        if parsed["type"] == "tool_calls":
            for i, tc in enumerate(parsed["tool_calls"]):
                block_id = f"toolu_{uuid.uuid4().hex[:8]}"
                yield format_sse({
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {"type": "tool_use", "id": block_id, "name": tc["name"], "input": {}},
                })
                args_str = json.dumps(tc.get("arguments", {}))
                yield format_sse({
                    "type": "content_block_delta",
                    "index": i,
                    "delta": {"type": "input_json_delta", "partial_json": args_str},
                })
                yield format_sse({"type": "content_block_stop", "index": i})

            yield format_sse({
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": estimate_tokens(text)},
            })
            yield format_sse({"type": "message_stop"})
            return
        text = parsed.get("content", text)

    yield format_sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    async for word in split_into_chunks(text):
        yield format_sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": word},
        })

    yield format_sse({"type": "content_block_stop", "index": 0})

    yield format_sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": estimate_tokens(text)},
    })

    yield format_sse({"type": "message_stop"})
