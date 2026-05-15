from pydantic import BaseModel, Field
from typing import Any


class GeminiPart(BaseModel):
    text: str | None = None
    function_call: dict | None = None
    function_response: dict | None = None


class GeminiContent(BaseModel):
    role: str = "user"
    parts: list[GeminiPart]


class GeminiFunctionDecl(BaseModel):
    name: str
    description: str = ""
    parameters: dict = Field(default_factory=dict)


class GeminiToolDef(BaseModel):
    function_declarations: list[GeminiFunctionDecl] = Field(default_factory=list)


class GeminiToolConfig(BaseModel):
    function_calling_config: dict = Field(default_factory=dict)


class GenerationConfig(BaseModel):
    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None


class GeminiRequest(BaseModel):
    contents: list[GeminiContent]
    tools: list[GeminiToolDef] | None = None
    tool_config: GeminiToolConfig | None = None
    generation_config: GenerationConfig | None = None
    safety_settings: list[dict] | None = None
    system_instruction: str | None = None


class GeminiCandidate(BaseModel):
    content: GeminiContent
    finish_reason: str | None = "STOP"


class GeminiUsageMetadata(BaseModel):
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0


class GeminiResponse(BaseModel):
    candidates: list[GeminiCandidate]
    usage_metadata: GeminiUsageMetadata = Field(default_factory=GeminiUsageMetadata)


class GeminiModelInfo(BaseModel):
    name: str
    display_name: str = ""
    supported_generation_methods: list[str] = Field(
        default_factory=lambda: ["generateContent", "streamGenerateContent"]
    )


class GeminiModelList(BaseModel):
    models: list[GeminiModelInfo]


class DeepResearchRequest(BaseModel):
    query: str
    model: str = ""
    language: str = "en"
    max_sources: int = 10


class InteractionRequest(BaseModel):
    input: str
    stream: bool = False
    language: str = "en"
    max_sources: int = 10
