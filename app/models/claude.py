from pydantic import BaseModel, Field, field_validator, field_serializer
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
    system: str | list | None = None
    stream: bool = False
    tools: list[ClaudeTool] | None = None
    tool_choice: dict | None = None
    # Anthropic 的扩展思考入参。刻意用 Any 而不是严格子模型、甚至不限成 dict：官方这个
    # 对象的形态还在变（enabled+budget_tokens / adaptive+display / disabled /
    # between_tools），用严格模型的话以后多一个字段就会被吞掉或直接 422。
    # 限成 `dict | None` 也不行：客户端（或中间层）把它传成字符串/数字/数组时会变成
    # FastAPI 原生 422 `{"detail":[...]}` —— 既改了既有状态码（这个字段在加进来之前是被
    # extra="ignore" 静默吞掉、请求照常 200），错误信封也不是 Anthropic 的
    # `{"type":"error","error":{...}}` 形状，SDK 拿到它会报解析错误而不是一条可读的报错。
    # parse_anthropic_thinking 本身对非 dict 是宽容的（返回 False = 和不传一样），
    # 这里放开类型正是为了让那份宽容真的生效。
    # 不传（None）时整条路径与改动前逐字节一致 —— 这是本功能唯一的开关。
    thinking: Any | None = None

    @field_validator("system", mode="before")
    @classmethod
    def _flatten_system(cls, v):
        """Anthropic 的 system 允许字符串或文本块数组 [{type:"text",text:...}]（Claude Code 发的是
        数组，块上可能带 cache_control）。这里在类型校验前把数组拍平成字符串，下游只需处理 str。"""
        if isinstance(v, (list, tuple)):
            parts = [b["text"] for b in v
                     if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
            joined = "\n\n".join(p for p in parts if p)
            return joined or None
        return v


class ContentBlock(BaseModel):
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None
    source: dict | None = None  # type=image 时：{type:"base64",media_type,data}
    # type=thinking 时的思考正文。真实 API 的 thinking 块恒带 signature，我们造不出
    # 合法签名，所以**不发** signature（参考实现的 ConfigContent 同样没有这个字段）：
    # 发一个空串/自造串更坏 —— 客户端把它回传给真 API 会 400。
    thinking: str | None = None
    citations: list | None = None  # 仅 text 块：真实 Anthropic API 两侧（流式/非流式）恒发该字段


class ClaudeUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    # 0 是诚实值：本中转没有 prompt cache，不是伪造非零数字掩盖真实差异。
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    service_tier: str = "standard"


class ClaudeResponse(BaseModel):
    id: str
    type: str = "message"
    role: str = "assistant"
    model: str = ""
    content: list[ContentBlock] = Field(default_factory=list)
    stop_reason: str = "end_turn"
    stop_sequence: str | None = None
    usage: ClaudeUsage = Field(default_factory=ClaudeUsage)

    @field_serializer("content")
    def _serialize_content(self, v: list[ContentBlock]) -> list[dict]:
        """按块类型只发相关字段（真实 API 行为）：text 块不带 id/name/input/source，
        tool_use 块不带 text/source 等。只对内容列表做 exclude_none，绝不整模型
        exclude_none——那样会连带吞掉顶层 stop_sequence:null（真实 API 恒发该字段）。

        R3：text 块的 citations 是例外——真实 Anthropic API 两侧（流式/非流式）text 块
        恒发 "citations": null，但它跟 id/name/input/source 一样默认是 None，会被上面
        这行 exclude_none 连带丢掉。这里对 text 块显式补回，其余块类型（tool_use 等）
        仍然走 exclude_none（不带 citations）。"""
        out = []
        for b in v:
            d = b.model_dump(exclude_none=True)
            if b.type == "text":
                d["citations"] = b.citations
            out.append(d)
        return out


class ClaudeModelInfo(BaseModel):
    id: str
    type: str = "model"
    created_at: str = ""
    display_name: str = ""


class ClaudeModelList(BaseModel):
    data: list[ClaudeModelInfo]
