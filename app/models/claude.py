from pydantic import BaseModel, Field
from typing import Any


class ClaudeMessage(BaseModel):
    role: str
    content: str | list


class ClaudeTool(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)


class ClaudeRequest(BaseModel):
    model: str
    max_tokens: int = 4096
    messages: list[ClaudeMessage]
    system: str | None = None
    stream: bool = False
    tools: list[ClaudeTool] | None = None
    tool_choice: dict | None = None


class ContentBlock(BaseModel):
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None


class ClaudeUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeResponse(BaseModel):
    id: str
    type: str = "message"
    role: str = "assistant"
    model: str = ""
    content: list[ContentBlock] = Field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: ClaudeUsage = Field(default_factory=ClaudeUsage)


class ClaudeModelInfo(BaseModel):
    id: str
    type: str = "model"
    created_at: str = ""
    display_name: str = ""


class ClaudeModelList(BaseModel):
    data: list[ClaudeModelInfo]
