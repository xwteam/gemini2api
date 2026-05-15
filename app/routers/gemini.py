import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.gemini_client import gemini_client
from app.core.stream import split_into_chunks
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
from app.utils.tools import build_tool_prompt, parse_tool_response, estimate_tokens
from app.utils.prompt import build_prompt_from_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gemini/v1beta")


@router.get("/models")
async def list_models():
    """List available Gemini models."""
    models = [
        GeminiModelInfo(
            name="models/gemini-2.0-flash-exp",
            display_name="Gemini 2.0 Flash Experimental",
            description="Fast and efficient model for general tasks",
        ),
        GeminiModelInfo(
            name="models/gemini-1.5-pro",
            display_name="Gemini 1.5 Pro",
            description="Advanced model for complex reasoning",
        ),
        GeminiModelInfo(
            name="models/gemini-1.5-flash",
            display_name="Gemini 1.5 Flash",
            description="Fast model for quick responses",
        ),
    ]
    return JSONResponse(content=GeminiModelList(models=models).model_dump())


@router.post("/models/{model}:generateContent")
async def generate_content(model: str, req: GeminiRequest):
    """Generate content using Gemini API (non-streaming)."""
    if model.startswith("models/"):
        model = model[7:]

    messages = []
    for content in req.contents:
        role = content.role
        text_parts = [part.text for part in content.parts if part.text]
        if text_parts:
            messages.append({"role": role, "content": " ".join(text_parts)})

    system = None
    if req.system_instruction:
        system_parts = [part.text for part in req.system_instruction.parts if part.text]
        if system_parts:
            system = " ".join(system_parts)

    tool_prompt = None
    if req.tools:
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend(tool.function_declarations)
        if function_declarations:
            tool_prompt = build_tool_prompt(function_declarations)

    prompt = build_prompt_from_messages(messages, system=system, tool_prompt=tool_prompt)

    response_text = await gemini_client.generate(
        model=model,
        prompt=prompt,
        temperature=req.generation_config.temperature if req.generation_config else None,
        max_tokens=req.generation_config.max_output_tokens if req.generation_config else None,
    )

    if tool_prompt:
        response_text = parse_tool_response(response_text)

    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(response_text)

    gemini_response = GeminiResponse(
        candidates=[
            GeminiCandidate(
                content=GeminiContent(
                    parts=[GeminiPart(text=response_text)],
                    role="model",
                ),
                finish_reason="STOP",
                index=0,
            )
        ],
        usage_metadata=GeminiUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
            total_token_count=prompt_tokens + completion_tokens,
        ),
    )

    return JSONResponse(content=gemini_response.model_dump())


@router.post("/models/{model}:streamGenerateContent")
async def stream_generate_content(model: str, req: GeminiRequest):
    """Generate content using Gemini API (streaming with chunked JSON)."""
    if model.startswith("models/"):
        model = model[7:]

    messages = []
    for content in req.contents:
        role = content.role
        text_parts = [part.text for part in content.parts if part.text]
        if text_parts:
            messages.append({"role": role, "content": " ".join(text_parts)})

    system = None
    if req.system_instruction:
        system_parts = [part.text for part in req.system_instruction.parts if part.text]
        if system_parts:
            system = " ".join(system_parts)

    tool_prompt = None
    if req.tools:
        function_declarations = []
        for tool in req.tools:
            if tool.function_declarations:
                function_declarations.extend(tool.function_declarations)
        if function_declarations:
            tool_prompt = build_tool_prompt(function_declarations)

    prompt = build_prompt_from_messages(messages, system=system, tool_prompt=tool_prompt)

    async def stream_generator() -> AsyncGenerator[str, None]:
        response_text = await gemini_client.generate(
            model=model,
            prompt=prompt,
            temperature=req.generation_config.temperature if req.generation_config else None,
            max_tokens=req.generation_config.max_output_tokens if req.generation_config else None,
        )

        if tool_prompt:
            response_text = parse_tool_response(response_text)

        chunks = split_into_chunks(response_text)

        for chunk in chunks:
            chunk_response = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": chunk}],
                            "role": "model",
                        },
                        "index": 0,
                    }
                ]
            }
            yield json.dumps(chunk_response) + "\n"

        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(response_text)

        final_chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": ""}],
                        "role": "model",
                    },
                    "finish_reason": "STOP",
                    "index": 0,
                }
            ],
            "usage_metadata": {
                "prompt_token_count": prompt_tokens,
                "candidates_token_count": completion_tokens,
                "total_token_count": prompt_tokens + completion_tokens,
            },
        }
        yield json.dumps(final_chunk) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/json")
