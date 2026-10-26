from pydantic import BaseModel, Field
from typing import Any
import time as _time


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ToolFunction(BaseModel):
    name: str
    description: str = ""
    parameters: dict = Field(default_factory=dict)


class ToolDef(BaseModel):
    type: str = "function"
    function: ToolFunction


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[ToolDef] | None = None
    tool_choice: Any = None
    conversation_id: str | None = None
    reasoning_effort: str | None = None
    # 下面这些 Gemini 网页版用不上，只原样转给第三方模型 / 兜底（过去模型里没有字段，被直接丢弃）
    top_p: float | None = None
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    response_format: dict | None = None
    max_completion_tokens: int | None = None
    stream_options: dict | None = None
    parallel_tool_calls: bool | None = None


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict] | None = None
    reasoning_content: str | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(_time.time()))
    model: str
    choices: list[Choice]
    usage: UsageInfo = Field(default_factory=UsageInfo)
    conversation_id: str | None = None


class StreamDelta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[dict] | None = None
    reasoning_content: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: StreamDelta
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(_time.time()))
    model: str
    choices: list[StreamChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "google"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: str | None = "gemini-pro"
    n: int = 1
    size: str | None = None          # Gemini 固定尺寸，忽略；保留兼容
    response_format: str = "b64_json"  # b64_json（默认，因 lh3 URL 客户端 403）| url
    user: str | None = None


class ImageData(BaseModel):
    b64_json: str | None = None
    url: str | None = None
    revised_prompt: str | None = None


class ImageResponse(BaseModel):
    created: int = Field(default_factory=lambda: int(_time.time()))
    data: list[ImageData]
