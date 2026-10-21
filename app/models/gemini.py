from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from typing import Any

# 官方 Gemini SDK 在 wire format 上用 camelCase（systemInstruction/generationConfig/
# inlineData/functionCall/...）。这些请求模型此前只认 snake_case，官方 SDK 发来的
# camelCase 字段会被 pydantic 当成未知字段静默丢弃（system prompt/生成参数/附件全部
# 消失但请求仍然 200）。alias_generator=to_camel 让两种大小写都能被接受；
# populate_by_name=True 保证既有 snake_case 调用方（内部测试、其它协议转发）不受影响。
_CAMEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GeminiPart(BaseModel):
    model_config = _CAMEL_CONFIG

    text: str | None = None
    function_call: dict | None = None
    function_response: dict | None = None
    inline_data: dict | None = None
    file_data: dict | None = None


class GeminiContent(BaseModel):
    role: str = "user"
    parts: list[GeminiPart]


class GeminiFunctionDecl(BaseModel):
    name: str
    description: str = ""
    parameters: dict = Field(default_factory=dict)


class GeminiToolDef(BaseModel):
    model_config = _CAMEL_CONFIG

    function_declarations: list[GeminiFunctionDecl] = Field(default_factory=list)


class GeminiToolConfig(BaseModel):
    model_config = _CAMEL_CONFIG

    function_calling_config: dict = Field(default_factory=dict)


class GenerationConfig(BaseModel):
    model_config = _CAMEL_CONFIG

    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    # thinkingConfig（includeThoughts / thinkingBudget / thinkingLevel）。刻意用 Any：
    # 限成 dict/严格模型的话，客户端传成字符串/数字时会从 200 变成 FastAPI 原生 422
    # （与 app/models/claude.py 的 thinking 字段同一个教训）。宽容解析见
    # gemini_client.parse_gemini_thinking_config —— 非 dict 视同没传。
    thinking_config: Any = None


class GeminiRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    contents: list[GeminiContent]
    tools: list[GeminiToolDef] | None = None
    tool_config: GeminiToolConfig | None = None
    generation_config: GenerationConfig | None = None
    safety_settings: list[dict] | None = None
    system_instruction: GeminiContent | str | None = None


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
    description: str = ""
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
