# API 文档

本文档详细说明 Gemini2API 的所有 API 端点和使用方法。

## 认证

所有 API 请求都需要进行身份验证。支持两种认证方式：

### 方式 1：Authorization Header（推荐）

```bash
curl -H "Authorization: Bearer sk-你的API密钥" \
  http://localhost:5918/openai/v1/models
```

### 方式 2：x-api-key Header

```bash
curl -H "x-api-key: sk-你的API密钥" \
  http://localhost:5918/openai/v1/models
```

### 获取 API Key

API Key 在首次启动时自动生成，可通过以下方式获取：

```bash
# 查看日志
docker compose logs | grep "API_KEY"

# 或查看 .env 文件
cat .env | grep API_KEY
```

### 两种可用的密钥

| 类型 | 来源 | 能访问 | 计数 |
|------|------|--------|------|
| `API_KEY`（`.env`） | 首次启动自动生成，或自行设置 | 业务 API + `/admin/*`（未单独设置 `ADMIN_API_KEY` 时） | 不计 |
| 访问密钥 | 管理员在面板「访问密钥」页或 `POST /admin/access-keys` 签发 | **只有业务 API**，访问不到 `/admin/*` | 每个请求 +1 |

访问密钥是**附加**的一层：`API_KEY` 始终全权有效，一把访问密钥都不签发时鉴权行为与旧版完全一致。访问密钥可以各自带有效期、请求数上限、绑定账号与允许模型，详见 [`POST /admin/access-keys`](#post-adminaccess-keys)。

访问密钥失效时的状态码：已停用 / 已过期 / 已超额都返回 401，响应体里的 `message` 会说明具体原因。

## 路径说明

从 v1.6.4 起，每家接口同时支持两套路径：

### 带前缀路径（三家明确区分）

- OpenAI: `/openai/v1/chat/completions`、`/openai/v1/models`
- Claude: `/claude/v1/messages`、`/claude/v1/messages/count_tokens`、`/claude/v1/models`
- Gemini: `/gemini/v1beta/models/{model}:generateContent`、`:streamGenerateContent`、`/gemini/v1beta/models`

下文各端点文档基于这套路径。

### 标准裸路径（v1.6.4 新增，主流 SDK 开箱即用）

主流 SDK 填写 `base_url` 时无需添加后缀，直接使用标准路径：

**OpenAI 格式**：
- `/v1/chat/completions`
- `/v1/models`

**Claude 格式**：
- `/v1/messages`
- `/v1/messages/count_tokens`

**Gemini 格式**：
- `/v1beta/models/{model}:generateContent`
- `/v1beta/models/{model}:streamGenerateContent`
- `/v1beta/models`

**单个模型**（v1.6.50 起）：`GET /v1/models/{model}`（同样挂在 `/openai/v1` 下）按 OpenAI 格式返回单个模型对象，口径与列表一致（含白名单、访问密钥可见范围）；不在列表里回 404 `model_not_found`。供 OpenAI SDK 的 `models.retrieve` 使用。

**重要说明**：裸路径 `/v1/models` 返回 OpenAI 格式的模型列表（同一路径无法同时返回两种格式）。如需 Claude 格式的模型列表，请使用 `/claude/v1/models`。

## 错误响应

所有错误响应遵循以下格式：

```json
{
  "error": {
    "message": "错误描述",
    "type": "错误类型"
  }
}
```

### 常见错误码

| 状态码 | 错误类型 | 说明 |
|--------|---------|------|
| 400 | `invalid_request_error` | 请求参数错误 |
| 401 | `authentication_error` | 认证失败，API Key 无效 |
| 403 | `permission_error` | 禁止访问 |
| 429 | `rate_limit_error` | 请求过于频繁 |
| 500 | `server_error` | 服务器错误 |
| 502 | `api_error` | 上游错误，包括谷歌回了一句固定的失败套话代替回答，见[谷歌侧故障](#谷歌侧故障) |
| 503 | `service_unavailable_error` | 无可用账号 |
| 504 | `timeout_error` | 生成超时（上游迟迟不出结果，按超时预算掐断），见[超时](#超时) |

## 🧠 模型与思考档位

| 对外模型名 | 自动映射到网页上的模型（当前实测） | 说明 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 质量最高、较慢 |
| `gemini-flash` | 3.8 Flash | 快，推荐作为默认 |
| `gemini-flash-lite` | 3.5 Flash-Lite | 最轻最快，Pro/Flash 被限额时的兜底 |
| `gemini-argon` | 4 Argon | 面向复杂任务；**账号真的有 Argon 时才会列出** |

- **映射是自动的**：每个账号的心跳会报出它当前真实可用的网页模型，对外名字固定不变、内部自动对上网页当前的那一代（Google 换代时不用改客户端）。
- **`gemini-flash-thinking` 已下线**：它只是"flash + 思考模式"的假模型，思考现在是每个模型都有的档位（见下）。为兼容老客户端，`gemini-flash-thinking`、`gemini-2.5-flash-thinking`、`gemini-2.0-flash-thinking` 以及内部名 `gemini-3-flash-thinking*` **仍然可以调**（隐藏别名，等同 `gemini-flash`），只是不再出现在任何模型列表里；想要思考内容请改传档位参数。 例外：访问密钥的「允许模型」里勾过 `gemini-flash-thinking` 的，这把密钥拉到的模型列表里仍会列出它（免得只勾了它的旧密钥拉到空列表），新签发的密钥请改勾 `gemini-flash`。⚠️ 行为变化：老客户端不传档位调用 `gemini-flash-thinking` 时，v1.6.42 会回传思考内容，现在不再回传（没请求的思考一律不回传）。
- **思考三档**：`low` / `medium` / `high`，对应网页上的低 / 中 / 高三档（实测 `high` 想得最深、也最慢；`low` 与 `medium` 的差别在实测里分不太开）。
- **默认档 `low`**：客户端**没指定档位**时（没传思考参数的，和要了思考但没说几档的），用「默认思考档位」（环境变量 `DEFAULT_THINKING_LEVEL`，或面板「设置 → 思考」，保存即时生效、无需重启），出厂 `low`。
  - ⚠️ **速度代价**：实测默认 `low` 比不思考**平均每个请求多约 5 秒**（flash 简单题 6.5 / 8.8 秒 → 8.6 / 16.6 秒）。最看重速度就把默认档设成 **`off`**（不思考、最快，与旧版不传参数时发给上游的请求完全一样）。前置代理有首字节超时的（如 EdgeOne 免费版 15 秒）尤其要留意非流式请求。流式请求也有代价：没提思考的请求按默认档开的思考不回传，**正文要等思考做完才开始出**（期间只有保活帧，连接不会被代理掐断），pro 遇到需要推理的题 `low` 档实测总耗时 36～47 秒 —— 对首字延迟敏感就用 `off`。⚠️ `off`（以及默认档本身）管的是**没指定档位**的请求：没传思考参数的，和要了思考但没说几档的（Claude Code 出厂请求就是这种，所以 Claude Code 默认也跟随默认档）。客户端**明确指定了档位**的（Codex / Cursor 选了 low/medium/high、Anthropic 给了 `budget_tokens`、Claude Code `/effort max` 等）默认档管不到；要所有请求都不思考（真正最快），关掉下面的总闸 `EXTENDED_THINKING_ENABLED=false`。
  - 客户端**完全没提思考**时，按默认档替它开的思考**只用于生成，绝不回传**：响应里不会多出 `reasoning_content` / `thinking` 块 / 思考 part，结构与不思考时逐字段一致（严格校验的客户端不会因此报错）。客户端**要了思考**（不论给没给档位）才回传思考内容（Gemini 原生仍只看 `includeThoughts`）。默认档是 `off` 时，「要了思考但没给档位」的请求也不思考，自然没有思考可回传。
- **Claude Code**（新版）：每个请求都带 `adaptive` + `effort: high`（high 是 Claude Code 的出厂值，不换档时每个请求都是它），所以默认跟随这里的默认档（出厂 low，速度优先）；想让某个会话想得更深，在 Claude Code 里执行 `/effort max`（或 `xhigh`）→ high；`/effort low` / `medium` 也照档。
- **总闸** `EXTENDED_THINKING_ENABLED=false`：一律不思考，连客户端明确要求的思考也忽略，这才是**真正最快**的模式。面板「设置 → 思考 →「允许思考（总闸）」」里一直显示、保存即时生效；与「默认思考档位」的分工：默认档管没指定档位的请求（含 Claude Code 出厂请求），总闸连明确指定了档位的也管。
- 面板「模型测试」页用**档位选择**（低 / 中 / 高，默认低）代替原来的「思考」勾选框，所选档位以 `reasoning_effort` 发出，思考过程显示在回答上方。 另有「按默认档（不传参数）」一项：不带 `reasoning_effort`，与普通客户端走同一条路，可用来实测设置里「默认思考档位」（含 `off`）的真实速度（思考内容按规定不回传）。

各协议的档位写法（**没指定档位则用默认档**；完全没提思考的请求，思考不回传）：

| 协议 | 参数 | 取值 → 档位 |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`；`minimal` → low，`xhigh` → high；`none` → 不思考；认不出的值 → 跟随默认档（不报错） |
| OpenAI `/v1/responses` | `reasoning.effort`（或顶层 `reasoning_effort`） | 同上 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`：`N<2048` → low，`2048–4095` → medium，`≥4096` → high；`{"type":"adaptive"}` 或 budget 无效 → 看 `output_config.effort`：`low` / `medium` 照档，`xhigh` / `max` → high，`high`（Claude Code 出厂值，视同没专门选档）或没给 → 跟随默认档；`{"type":"disabled"}` → 不思考；认不出的 `type` 按没传处理 |
| Gemini 原生 `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`：`LOW` / `MEDIUM` / `HIGH`（`MINIMAL` → low，未指定 → 跟随默认档）；`thinkingBudget`：`0` → 不思考，`-1`（自动）→ 跟随默认档，`>0` 按 2048 / 4096 切点分档；两者都给时以 `thinkingLevel` 为准；只给 `includeThoughts: true` → 跟随默认档；`includeThoughts: true` 才在响应里回传思考（`"thought": true` 的 part） |

## OpenAI 兼容 API

### GET /openai/v1/models

获取可用模型列表。

**请求**：
```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-pro",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-flash",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-flash-lite",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-argon",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    }
  ]
}
```

> 💡 **模型选择建议**：四个模型对应不同的速度/质量权衡。
> - `gemini-flash`：最快（响应约 4-5 秒），适合 **agent / 高频 / 高并发**场景，推荐作为默认选择。
> - `gemini-argon`：4 Argon，面向复杂任务；只有账号真的有 Argon 时才会出现在列表里。
> - `gemini-flash-lite`：最轻量最快的档位（3.5 Flash-Lite），Pro/Flash 被限额时可作为可用兜底。
> - `gemini-pro`：质量最高但较慢（响应约 9-17 秒，长上下文更慢），适合对质量要求高、不在意延迟的场景。
>
> agent 类客户端（会并发发起大量请求）建议优先用 `gemini-flash`。本服务的流式接口为真正的增量流式，首字一生成即开始推送。

### POST /openai/v1/chat/completions

发送对话请求，获取 AI 回复。

**请求体**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称，如 `gemini-flash` |
| `messages` | array | 是 | 消息列表，每条消息包含 `role` 和 `content`。`content` 可以是字符串或对象数组（支持多模态） |
| `stream` | boolean | 否 | 是否流式返回，默认 false |
| `temperature` | number | 否 | 温度参数，0-2，默认 1 |
| `top_p` | number | 否 | Top-P 采样，0-1，默认 1 |
| `max_tokens` | number | 否 | 最大输出 token 数 |
| `tools` | array | 否 | 函数调用工具列表 |
| `tool_choice` | string | 否 | 工具选择策略，`auto`/`required`/`none` |
| `conversation_id` | string | 否 | 对话 ID，用于多轮续接（规则见下方「多轮续接」） |
| `reasoning_effort` | string | 否 | 思考档位 `low` / `medium` / `high`（见 [🧠 模型与思考档位](#-模型与思考档位)）。不传 = 默认档（出厂 `low`），且不回传 `reasoning_content` |

**转给第三方模型的参数**（v1.6.49 起）：`temperature`、`top_p`、`stop`、`presence_penalty`、`frequency_penalty`、`seed`、`response_format`、`max_tokens` / `max_completion_tokens`、`parallel_tool_calls`、`stream_options`（只在流式时带）原样转给 OpenAI 兼容的第三方模型与第三方兜底（空值不带，`parallel_tool_calls` 只在带了工具时才带；Anthropic 类上游只转 `stop`，`temperature` / `top_p` 不转，新版 Claude 不接受两者同时出现）；Gemini 网页版没有这些开关，Gemini 路径忽略它们。`developer` 角色按 `system` 处理（Gemini 路径拼进提示词，转第三方时改成 `system`）。

**多轮续接（`conversation_id`）**：同一个 `conversation_id` 的后续轮次接着上游 Gemini 的同一个会话往下聊，只发最新一条用户消息，并带上上一轮记下的续接元数据（`[cid, rid, rcid]`）。网页版的会话属于具体某个账号，所以后续轮次**钉在服务上一轮的那个账号上**。流式请求同样续接，但流式响应里不回传 `conversation_id`，要由客户端自己带上（非流式不带时服务端会生成一个，在响应的 `conversation_id` 字段里回给你）。下面任一情况都**自动改发完整历史、新开一个会话**（成功后记下新会话与账号，下一轮照常续接），绝不只发最后一句而悄悄丢掉上下文：

- 那个账号不可用：已过期、被删除、不在本次访问密钥绑定的账号里，或（池里有多个账号时）正好满载；
- 记下的续接元数据用不了（含升级前存下、没记账号的旧会话：第一轮发完整历史，之后恢复续接）；
- 上一轮是第三方兜底回答的，或上游那一轮没给出续接点；
- 新的一轮不只是一条用户消息：带着工具结果（`role: "tool"`，或用户消息里的 `tool_result` 块），或上一轮回答之后连着来了好几条消息；
- 用的是 Gem 模型，且 Gem 绑定的账号与会话记录的账号不一致（以 Gem 为准）。

谷歌那边会话真过期、续接请求失败时，仍会自动用完整历史重试一次（超时除外，见[超时](#超时)）。钉住的账号到真正发请求时才不可用（比如刚好被抢满），同样改发完整历史，这一轮的思考档位保持不变。

**多模态 content 格式**：

`content` 可以是字符串（纯文本）或对象数组（支持文本和图片）：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "这是什么"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
      }
    }
  ]
}
```

支持的 content 类型：
- `text`：纯文本内容
- `image_url`：图片，支持 Base64 Data URI（`data:image/...;base64,...`）和远程 HTTP URL

**非流式请求示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

**非流式响应**：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1715970000,
  "model": "gemini-2.0-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么我可以帮助你的吗？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  },
  "conversation_id": "conv-xxx"
}
```

**流式请求示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "写一首诗"}
    ],
    "stream": true
  }'
```

**流式响应**（Server-Sent Events 格式）：

```
data: {"choices":[{"delta":{"content":"春"},"index":0}]}

data: {"choices":[{"delta":{"content":"风"},"index":0}]}

data: {"choices":[{"delta":{"content":"又"},"index":0}]}

data: [DONE]
```

**函数调用示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "北京今天天气怎么样"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "获取指定城市的天气",
          "parameters": {
            "type": "object",
            "properties": {
              "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
          }
        }
      }
    ]
  }'
```

### POST /openai/v1/responses

OpenAI Responses API。为需要新版 Responses 协议（而非 Chat Completions）的客户端提供支持——例如 **Codex CLI**，它在 2026 年 2 月起砍掉了对 Chat Completions 的支持，要把 Codex CLI 接到 gemini2api 就得靠这个接口。支持文本对话、流式输出、工具（函数）调用，Gemini 模型和 API 管理里配置的第三方模型都能用。

**请求**：
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "1+1等于几？",
    "stream": false
  }'
```

**请求体**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称，如 `gemini-flash`，或 API 管理里配置的第三方模型 |
| `input` | string 或 array | 是 | 字符串（等同一条 user 消息的简写），或输入条目数组（见下） |
| `instructions` | string | 否 | 系统/开发者前置说明，加在对话最前面 |
| `stream` | boolean | 否 | 是否流式返回，默认 false |
| `tools` | array | 否 | 函数调用工具定义，**扁平格式**：`{"type":"function","name","description","parameters"}`（注意：跟 Chat Completions 的嵌套格式 `{"type":"function","function":{...}}` 不一样） |
| `tool_choice` | string 或 object | 否 | `auto`、`none`、`required`，或 `{"type":"function","name":"..."}` 指定必须调用某个工具 |
| `temperature` | number | 否 | 随机性（会透传给第三方模型；Gemini 路径不生效） |
| `max_output_tokens` | number | 否 | 最大输出长度（会透传给第三方模型；Gemini 路径不生效） |

**`input` 数组条目类型**：
- `{"type":"message","role":"user"|"assistant"|"system","content":[...]}` —— 内容块：`{"type":"input_text","text":...}`、`{"type":"input_image","image_url":"..."}`、`{"type":"output_text","text":...}`
- `{"type":"function_call","call_id","name","arguments"}` —— 历史里助手调用工具的那一轮（多轮续聊需要客户端自己重发完整历史）
- `{"type":"function_call_output","call_id","output"}`（或 `"tool_result"`）—— 客户端回传的工具执行结果
- 请求的是第三方模型（API 管理里配置的）时，`function_call` / `function_call_output` 按 OpenAI 原生格式转发（`assistant.tool_calls` + 带 `tool_call_id` 的 `tool` 消息，连续的调用并进同一条 assistant 消息）；只转发 `function` 类型的工具，`web_search` 等内置工具会被略过；第三方返回的工具调用（含流式）会变成 `function_call` 输出项（v1.6.48 起）。

**明确不支持（会报错，不会假装支持）**：`previous_response_id`——本服务不保存服务端对话状态，传了这个字段会返回 400 `invalid_request_error`，而不是悄悄忽略。请每次请求都在 `input` 里带上完整对话历史（Codex CLI 本身就是这么做的）。

**响应（非流式）**：
```json
{
  "id": "resp_xxx",
  "object": "response",
  "created_at": 1715970000,
  "status": "completed",
  "model": "gemini-flash",
  "output": [
    {
      "id": "msg_xxx",
      "type": "message",
      "role": "assistant",
      "status": "completed",
      "content": [
        {"type": "output_text", "text": "1+1等于2", "annotations": []}
      ]
    }
  ],
  "usage": {
    "input_tokens": 10,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens": 5,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 15
  },
  "previous_response_id": null,
  "instructions": null,
  "error": null
}
```

**响应（流式）**：严格按官方协议顺序发送带命名的 SSE 事件，每个事件都带递增的 `sequence_number`。**没有** `data: [DONE]` 结尾标记（那是 Chat Completions 的老约定）——完成信号是 `response.completed`（失败是 `response.failed`）：

```
event: response.created
data: {"type":"response.created","sequence_number":0,"response":{...}}

event: response.in_progress
data: {"type":"response.in_progress","sequence_number":1,...}

event: response.output_item.added
data: {"type":"response.output_item.added","sequence_number":2,...}

event: response.content_part.added
data: {"type":"response.content_part.added","sequence_number":3,...}

event: response.output_text.delta
data: {"type":"response.output_text.delta","sequence_number":4,"delta":"1"}

event: response.output_text.done
data: {"type":"response.output_text.done","sequence_number":5,"text":"1+1等于2"}

event: response.content_part.done
data: {"type":"response.content_part.done","sequence_number":6,...}

event: response.output_item.done
data: {"type":"response.output_item.done","sequence_number":7,...}

event: response.completed
data: {"type":"response.completed","sequence_number":8,"response":{...}}
```

工具调用场景下，`response.output_item.added`（类型 `function_call`）之后跟的是 `response.function_call_arguments.delta` / `response.function_call_arguments.done` / `response.output_item.done`，而不是上面的文本事件。

**工具调用示例**：
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "查一下巴黎的天气",
    "tools": [
      {
        "type": "function",
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string"}
          },
          "required": ["city"]
        }
      }
    ]
  }'
```
响应 `output` 里会含有一个 `function_call` 条目：
```json
{"id": "fc_xxx", "type": "function_call", "status": "completed", "call_id": "call_xxx", "name": "get_weather", "arguments": "{\"city\": \"巴黎\"}"}
```

### POST /openai/v1/images/generations

AI 生成图片：靠 prompt 触发生成，返回 b64_json 格式的图片。也可使用裸路径 `/v1/images/generations`。

**请求体**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称，如 `gemini-pro` |
| `prompt` | string | 是 | 图片描述提示词 |
| `n` | number | 否 | 生成图片数量，默认 1 |

**请求示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

**响应**：

```json
{
  "created": 1715970000,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

> [!TIP]
> 三家对话接口（OpenAI / Claude / Gemini）检测到生成图片时，也会自动将图片嵌入回复中（OpenAI 用 markdown 图片语法、Claude 用 image block、Gemini 用 inlineData）。

## Claude 兼容 API

### GET /claude/v1/models

获取模型列表。

**请求**：
```bash
curl http://localhost:5918/claude/v1/models \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "data": [
    {
      "id": "gemini-2.0-flash",
      "type": "model",
      "display_name": "Gemini 2.0 Flash"
    }
  ]
}
```

### GET /claude/v1/models/{id}

获取指定模型的详情。

**请求**：
```bash
curl http://localhost:5918/claude/v1/models/gemini-2.0-flash \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /claude/v1/messages

发送消息请求（Claude 格式）。

**请求体**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称 |
| `messages` | array | 是 | 消息列表 |
| `max_tokens` | number | 是 | 最大输出 token 数 |
| `stream` | boolean | 否 | 是否流式返回 |
| `temperature` | number | 否 | 温度参数 |
| `tools` | array | 否 | 工具列表 |

**请求示例**：

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

**响应**：

```json
{
  "id": "msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Hello! How can I help you?"
    }
  ],
  "model": "gemini-2.0-flash",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 20
  }
}
```

#### 扩展思考（`thinking`）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `thinking` | object | 否 | 指定思考档位。支持三类官方写法（见下表）。**不传时上游按「默认思考档位」（出厂 `low`）思考，但响应里绝不出 `thinking` 块，响应结构与旧版逐字节一致** |
| `output_config` | object | 否 | 只读其中的 `effort`，配合 `thinking` 定档位（用法见下表 `adaptive` 一行）。单独给 `output_config.effort`、没给 `thinking` 时不起作用（按没传思考参数处理）；形态不对（不是对象、`effort` 认不出）视同没给，不报错 |

| 写法 | 效果 |
|------|------|
| `{"type":"enabled","budget_tokens":N}` | 开启。`N` 按 `<2048` / `2048–4095` / `≥4096` 分成低 / 中 / 高三档 —— 这三个切点取自本服务出站给第三方 Anthropic 时用的 `{low:1024, medium:2048, high:4096}` 的反函数，保证经本服务来回转换时档位一致。`budget_tokens` 合法时以它为准，优先于 `output_config.effort` |
| `{"type":"adaptive"}` | 开启，档位看 `output_config.effort`：`low` / `medium` 照档，`xhigh` / `max` → high，`high`（Claude Code 出厂值，视同没专门选档）或没给 → 跟随默认思考档位；`budget_tokens` 缺失/无效时同此 |
| `{"type":"disabled"}` / `{"type":"between_tools"}` | 不思考（明确关闭，不受默认档影响；`output_config.effort` 给什么都不管） |

思考内容以 Anthropic 规范的 `thinking` 内容块回传，排在 `text` / `tool_use` 块**之前**；流式下是 `content_block_start(thinking)` → `thinking_delta` → `content_block_stop`。

⚠️ 两点必须知道：
- **不带 `signature`**。真实 Anthropic API 的 `thinking` 块恒带签名，本服务造不出合法签名，所以这个字段不发（发一个空串或自造串更坏：客户端把它回传给真 API 会 400）。
- 档位对应网页的低 / 中 / 高三档：真机实测 high 想得最深；low 与 medium 在实测里分不太开。
- 思考 token 会计进 `usage.output_tokens`（与官方计费口径一致），但那仍然是估算值，见「访问密钥用量统计」一节。
- 全局开关 `EXTENDED_THINKING_ENABLED=false` 时，即使传了 `thinking` 也不走思考路径。
- **正文开始之后才到的思考增量会被丢掉**（流式）。Anthropic 的块顺序不允许在 `text` 块之后再开或再续 `thinking` 块，所以上游在正文开始后还在增长思考时，后面那段只能丢（会打一条 WARNING 说明丢了多少字符）。需要完整思考链时请用 OpenAI 协议的 `reasoning_content`，那条路径没有块顺序约束。正常顺序（思考先到）不受影响，正文永远完整。
- `thinking` 传成非对象（字符串/数字/数组）时按**没传**处理、请求照常返回 200，不会变成 422。

### POST /claude/v1/messages/count_tokens

估算消息的 token 数。

**请求**：
```bash
curl -X POST http://localhost:5918/claude/v1/messages/count_tokens \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

**响应**：
```json
{
  "input_tokens": 10
}
```

## Gemini 原生 API

### GET /gemini/v1beta/models

获取 Gemini 模型列表。

**请求**：
```bash
curl http://localhost:5918/gemini/v1beta/models \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /gemini/v1beta/models/{model}:generateContent

生成内容（非流式）。

**请求**：
```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.0-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "Hello"}]
      }
    ]
  }'
```

### POST /gemini/v1beta/models/{model}:streamGenerateContent

生成内容（流式）。

**请求**：
```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.0-flash:streamGenerateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "Hello"}]
      }
    ]
  }'
```

**流式响应**（Chunked JSON 格式）：

```
[{"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}]
[{"candidates":[{"content":{"parts":[{"text":" there"}]}}]}]
```

## Deep Research API

### POST /gemini/v1beta/deepresearch/

同步深度研究（规划 -> 调研 -> 综合报告）。

**请求**：
```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "query": "人工智能的发展趋势"
  }'
```

**响应**：
```json
{
  "status": "completed",
  "query": "人工智能的发展趋势",
  "report": "详细的研究报告..."
}
```

### POST /gemini/v1beta/deepresearch/stream

流式深度研究（实时进度推送）。

**请求**：
```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "query": "人工智能的发展趋势"
  }'
```

### POST /gemini/v1beta/deepresearch/interact

异步任务模式（创建 -> 轮询结果）。

**创建任务**：
```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/interact \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "query": "人工智能的发展趋势",
    "action": "create"
  }'
```

**轮询结果**：
```bash
curl http://localhost:5918/gemini/v1beta/deepresearch/interact?task_id=xxx \
  -H "Authorization: Bearer sk-你的API密钥"
```

## 管理 API

### GET /admin/status

获取服务状态和账号池概览。

**请求**：
```bash
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "total": 2,
  "active": 1,
  "strategy": "round-robin",
  "max_concurrent_per_account": 8,
  "accounts": [
    {
      "id": "account-0",
      "label": "主账号",
      "psid": "g.a0****x0yz",
      "status": "active",
      "request_count": 152,
      "error_count": 1,
      "active_requests": 0,
      "last_used": "2026-10-26T03:58:10.512014+00:00",
      "cooling_down": false,
      "is_healthy": true,
      "consecutive_failures": 0,
      "consecutive_empty": 0,
      "empty_count": 0,
      "last_success_at": "2026-10-26T03:58:12.104233+00:00",
      "last_error": "",
      "last_error_at": null,
      "models": ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"],
      "models_count": 4,
      "keepalive_mode": "browser"
    },
    {
      "id": "account-1",
      "label": "备用账号",
      "psid": "g.a0****k9qr",
      "status": "expired",
      "request_count": 87,
      "error_count": 0,
      "active_requests": 0,
      "last_used": "2026-10-24T14:40:02.338190+00:00",
      "cooling_down": false,
      "is_healthy": false,
      "consecutive_failures": 0,
      "consecutive_empty": 0,
      "empty_count": 0,
      "last_success_at": "2026-10-24T14:40:05.901123+00:00",
      "last_error": "Google session expired (login redirect)",
      "last_error_at": null,
      "models": ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"],
      "models_count": 4,
      "keepalive_mode": "server"
    }
  ],
  "model_breakers": {
    "flash": {
      "state": "open",
      "enabled": true,
      "consecutive_failures": 2,
      "open_remaining_seconds": 41.2,
      "retry_at": "2026-10-26T09:01:03.402771+00:00",
      "cooldown_seconds": 60.0,
      "probe_in_flight": false,
      "last_reason": "GeminiFailureReply (HTTP 502)",
      "last_failure_at": "2026-10-26T09:00:03.402771+00:00"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `active` | 对外 `status` 为 `active` 的账号数 |
| `accounts[].status` | `active`：可用；`expired`：会话已失效，需要换 cookie —— 包括连续失败 3 次、上游回 401/403，以及**谷歌会话被打回登录页**（此时 `is_healthy` 为 `false`，`last_error` 为空时补上 `Google session expired (login redirect)`）；换上新 cookie 后自动回到 `active`。`disabled`：已停用 |
| `accounts[].is_healthy` | 客户端会话当前是否可用。`active` 但为 `false` 表示暂时不可用（如网络抖动），尚未判定为会话失效 |
| `accounts[].last_error` / `last_error_at` | 最近一次失败的脱敏摘要与时间 |
| `accounts[].keepalive_mode` | cookie 由谁保活：`server`（默认，服务端定时轮换）/ `browser`（由浏览器保活插件推送，服务端不轮换，见 `PUT /admin/accounts/{id}/cookies`） |
| `model_breakers` | 模型故障熔断各族的状态（`GET /admin/accounts` 同样带这个字段），只列有过状态的族，见[谷歌侧故障](#谷歌侧故障) |
| `model_breakers.*.state` | `closed`：照常调谷歌；`open`：谷歌侧故障中，开了兜底的 `/v1/chat/completions` 请求直接走兜底；`half_open`：开放期已到，下一个请求去试探谷歌 |
| `model_breakers.*.enabled` | `MODEL_BREAKER_ENABLED`；为 `false` 时照常记录状态，但绝不绕开谷歌 |
| `model_breakers.*.consecutive_failures` | 当前窗口里疑似故障地失败过的不同请求个数 |
| `model_breakers.*.open_remaining_seconds` / `retry_at` | `open` 时还剩多少秒 / 到点的绝对时间（UTC）；其它状态为 `0` / `null` |
| `model_breakers.*.cooldown_seconds` | 本次（或下一次）开放期的秒数（试探失败会翻倍，封顶 `MODEL_BREAKER_MAX_COOLDOWN`） |
| `model_breakers.*.probe_in_flight` | `half_open` 时是否已有一个请求在试探谷歌 |
| `model_breakers.*.last_reason` / `last_failure_at` | 最近一次计入熔断的失败（异常类型 + 状态码的安全摘要）与时间（UTC） |

### GET /admin/system-info

获取系统信息。

**请求**：
```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "version": "1.0.0",
  "python_version": "3.12.0",
  "server_time": "2025/05/17 23:35:00",
  "os": "Linux 6.17.0",
  "memory_usage": 256,
  "memory_total": 8192,
  "cpu_percent": 5.2,
  "pid": 12345,
  "run_mode": "Docker",
  "uptime_seconds": 3600
}
```

### GET /admin/accounts

获取所有账号列表及状态。

> 响应与 `GET /admin/status` 相同（同样带 `model_breakers`，面板账号页顶部的熔断提示读的就是这个接口）。

**请求**：
```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "accounts": [
    {
      "id": "account-0",
      "label": "主账号",
      "status": "healthy",
      "requests": 10,
      "last_check": "2025-05-17T23:35:00"
    }
  ]
}
```

### POST /admin/accounts

动态添加新账号。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "psid": "g.a000新的值",
    "psidts": "sidts-新的值",
    "label": "新账号"
  }'
```

**响应**：
```json
{
  "id": "account-2",
  "status": "ok",
  "message": "Account added successfully"
}
```

新添加的账号同样按请求来源记录 `keepalive_mode`（规则同 `PUT /admin/accounts/{id}/cookies`，面板「添加账号」和脚本添加的是 `server`）。删除账号不会清掉它那个 PSID 的记录，但用同一份 cookie 加回来时会按这次的来源重新记录。

### DELETE /admin/accounts/{id}

删除指定账号。

**请求**：
```bash
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "status": "ok",
  "message": "Account deleted successfully"
}
```

### GET /admin/accounts/{id}/check

检测单个账号状态。

**请求**：
```bash
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "id": "account-0",
  "status": "healthy",
  "message": "Account is healthy"
}
```

### GET /admin/check-account

检测所有账号状态。

**请求**：
```bash
curl http://localhost:5918/admin/check-account \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/reload-cookies

热更新 Cookie（无需重启容器）。

**从请求体更新**：
```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "psid": "g.新的值",
    "psidts": "sidts-新的值"
  }'
```

**从 .env 文件读取**：
```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-你的API密钥"
```

成功后同样按请求来源记录 `keepalive_mode`，该账号立即恢复为 `active`（规则同 `PUT /admin/accounts/{id}/cookies`）。

### PUT /admin/accounts/{id}/cookies

更新指定账号的 Cookie。

**请求**：
```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "psid": "g.新的值",
    "psidts": "sidts-新的值"
  }'
```

**保活方式**：reload 成功后，按请求来源记下这个账号由谁保活（记在新 PSID 名下，保存在 `data/keepalive-modes.json`，只存 PSID 的哈希）：

| 请求来源 | `keepalive_mode` | 效果 |
|------|------|------|
| 带请求头 `X-Gemini2API-Keepalive`（浏览器保活插件 v1.3.0 起会带，值形如 `gemini2api-plugin/1.3.0`；仓库自带的 Playwright 续期边车带 `gemini2api-refresher`） | `browser` | 服务端不再对该账号调 RotateCookies，由浏览器轮换、插件推送 |
| `Origin` 以 `chrome-extension://` 开头（兼容不带上述请求头的旧版插件） | `browser` | 同上 |
| 其他（面板「更新 Cookie」、脚本 / curl） | `server` | 交回服务端定时轮换 |

成功后该账号立即恢复为 `active`、连续失败数清零，不需要再调 `/check`。reload 失败（503）时什么都不改：不换上这份 cookie，也不改保活方式和账号状态。来源是浏览器保活插件时，这次 reload 本身也不会调 RotateCookies（取 token 失败后的兜底轮换同样跳过，免得替浏览器把它正在用的会话换掉）。

### GET /admin/health-history

获取最近的健康检查记录。

**请求**：
```bash
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/usage-stats/summary

获取使用统计概览。

**请求**：
```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "total_requests": 1000,
  "error_rate": 0.01,
  "average_latency_ms": 500,
  "cookie_rotation_success_rate": 0.99
}
```

### GET /admin/usage-stats/history

获取历史趋势数据。

**请求参数**：
- `granularity`：粒度（hour/day，默认 hour）
- `hours`：查询小时数（默认 24）

**请求**：
```bash
curl "http://localhost:5918/admin/usage-stats/history?granularity=hour&hours=24" \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/settings

获取当前可编辑配置。

**请求**：
```bash
curl http://localhost:5918/admin/settings \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "performance": {
    "rotation_strategy": "round-robin",
    "max_concurrent_per_account": 3,
    "refresh_interval": 30
  },
  "rate_limit": {
    "enabled": false,
    "window": 60,
    "max": 10
  }
}
```

### POST /admin/settings

批量更新配置（写入 .env + 热更新内存）。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "rotation_strategy": "failover",
    "max_concurrent_per_account": 5
  }'
```

### GET /admin/api-keys

获取 API Key 列表（密钥脱敏）。

**请求**：
```bash
curl http://localhost:5918/admin/api-keys \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/api-keys/catalog

获取 Provider 目录（内置模型列表）。

**请求**：
```bash
curl http://localhost:5918/admin/api-keys/catalog \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/api-keys

添加 API Key。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "provider": "openai",
    "api_key": "sk-xxx",
    "model": "gpt-4o"
  }'
```

### DELETE /admin/api-keys/{id}

删除 API Key。

**请求**：
```bash
curl -X DELETE http://localhost:5918/admin/api-keys/key-1 \
  -H "Authorization: Bearer sk-你的API密钥"
```

### PATCH /admin/api-keys/{id}/status

切换 Key 状态（启用/禁用）。

**请求**：
```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-1/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"status": "active"}'
```

### PATCH /admin/api-keys/{id}/label

修改 Key 标签。

**请求**：
```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-1/label \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"label": "我的 OpenAI Key"}'
```

### POST /admin/api-keys/import

批量导入 API Key。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/api-keys/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "keys": [
      {"provider": "openai", "api_key": "sk-xxx", "model": "gpt-4o"},
      {"provider": "anthropic", "api_key": "sk-ant-xxx", "model": "claude-3-opus"}
    ]
  }'
```

### GET /admin/api-keys/export

导出所有 API Key（包含完整密钥）。

**请求**：
```bash
curl http://localhost:5918/admin/api-keys/export \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/api-keys/batch-delete

批量删除 API Key。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/api-keys/batch-delete \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"ids": ["key-1", "key-2"]}'
```

### POST /admin/api-keys/models

探测某 Provider / base_url 下可用的模型列表（用于添加 Key 时填充模型下拉）。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/api-keys/models \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "provider": "openai",
    "api_key": "sk-xxx",
    "base_url": "https://api.openai.com/v1"
  }'
```

### GET /admin/verify

验证 API Key 有效性（登录用）。

**请求**：
```bash
curl http://localhost:5918/admin/verify \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "valid": true,
  "message": "API Key is valid"
}
```

### POST /admin/restart

重启服务（面板右上角一键重启，重启后自动轮询恢复）。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/restart \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/check-update

检查是否有新版本。

**请求**：
```bash
curl http://localhost:5918/admin/check-update \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/update

触发更新到最新版本。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/update \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/logs

结构化日志分页查询。

**请求参数**：
- `direction`：查询方向（asc/desc，默认 desc）
- `search`：搜索关键词
- `limit`：每页记录数（默认 15）
- `offset`：偏移量（默认 0）

**请求**：
```bash
curl "http://localhost:5918/admin/logs?limit=15&offset=0&search=error" \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/logs/state

获取日志记录状态。

**请求**：
```bash
curl http://localhost:5918/admin/logs/state \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/logs/state

更新日志记录状态。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/logs/state \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"enabled": true}'
```

### POST /admin/logs/clear

清空日志。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/logs/clear \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/logs/{id}

获取单条日志详情。

**请求**：
```bash
curl http://localhost:5918/admin/logs/log-123 \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/web-chats

列出账号在 Gemini 网页端的会话（只读）。

用于查看各账号在 gemini.google.com 堆积的会话列表，包括会话 ID、标题、时间戳、是否置顶等信息。

**请求**：
```bash
curl http://localhost:5918/admin/web-chats \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "accounts": [
    {
      "account_id": "account-0",
      "chats": [
        {
          "cid": "chat-id-1",
          "title": "对话标题",
          "timestamp": "2026-06-06T10:30:00Z",
          "pinned": false
        },
        {
          "cid": "chat-id-2",
          "title": "置顶会话",
          "timestamp": "2026-06-05T15:20:00Z",
          "pinned": true
        }
      ]
    }
  ]
}
```

### POST /admin/cleanup-web-chats

手动触发清理超过指定时长的网页会话。

后台异步执行清理任务，立即返回。可配置保留时长和是否跳过置顶会话。清理任务会循环执行直到所有超期会话被删除。

**请求体**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keep_hours` | number | 否 | 保留多少小时内的会话，默认 24 |
| `skip_pinned` | boolean | 否 | 是否跳过置顶会话，默认 true |

**请求**：
```bash
curl -X POST http://localhost:5918/admin/cleanup-web-chats \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "keep_hours": 24,
    "skip_pinned": true
  }'
```

**响应**：
```json
{
  "status": "started",
  "message": "Cleanup task started in background"
}
```

### GET /admin/model-mapping

获取所有模型映射。

**请求**：
```bash
curl http://localhost:5918/admin/model-mapping \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/model-mapping

添加/更新模型映射。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/model-mapping \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "alias": "gpt-4o",
    "target_model": "gemini-2.5-pro"
  }'
```

### DELETE /admin/model-mapping/{alias}

删除模型映射。

**请求**：
```bash
curl -X DELETE http://localhost:5918/admin/model-mapping/gpt-4o \
  -H "Authorization: Bearer sk-你的API密钥"
```

### GET /admin/access-keys

列出所有访问密钥（含明文密钥、状态、用量与权限范围）。

**请求**：
```bash
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "keys": [
    {
      "id": 1,
      "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "张三",
      "display_name": "张三",
      "enabled": true,
      "created_at": "2026-10-20T03:00:00+00:00",
      "expires_at": null,
      "duration_days": 7,
      "activated_at": null,
      "request_limit": 500,
      "request_count": 0,
      "bound_account_ids": null,
      "allowed_models": ["gemini-flash"],
      "last_used_at": null,
      "state": "pending"
    }
  ]
}
```

`state` 取值：`valid`（有效）/ `disabled`（已停用）/ `pending`（未激活，配了 `duration_days` 但还没被用过）/ `expired`（已过期）/ `quota_exceeded`（已超额）。判定按 `disabled` → `expired` → `quota_exceeded` → `pending` → `valid` 的优先级短路。

### GET /admin/access-keys/options

面板签发表单的候选项：账号池里的账号 + 对外可见的模型名（口径与 `GET /v1/models` 一致）。

**请求**：
```bash
curl http://localhost:5918/admin/access-keys/options \
  -H "Authorization: Bearer sk-你的API密钥"
```

**响应**：
```json
{
  "accounts": [{"id": "account-0", "label": "我的主号", "status": "active"}],
  "models": ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"]
}
```

### POST /admin/access-keys

签发访问密钥。

**参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ❌ | 标签；`count > 1` 时自动编号为 `name-1`、`name-2`…… |
| `count` | integer | ❌ | 一次签发几把，默认 1，**上限 50** |
| `expires_at` | string | ❌ | 绝对过期时间（ISO8601），与 `duration_days` 互斥 |
| `duration_days` | number | ❌ | 有效天数，**惰性激活**：持有人首次使用才开始计时（上限 36500） |
| `request_limit` | integer | ❌ | 请求数上限，留空=不限 |
| `bound_account_ids` | string[] | ❌ | 绑定账号，留空=不限制 |
| `allowed_models` | string[] | ❌ | 允许模型，留空=不限制 |
| `enabled` | boolean | ❌ | 是否立即可用，默认 `true` |

**请求**：
```bash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "name": "张三",
    "duration_days": 7,
    "request_limit": 500,
    "allowed_models": ["gemini-flash"]
  }'
```

响应里 `keys` 是本次签发的全部密钥，`key` 是其中第一把（方便单把签发时直接取用）。

> `count` 传 0 或大于 50 返回 400；`expires_at` 与 `duration_days` 同时给出返回 400；落盘失败返回 500（绝不会在没存下来的情况下回 200，否则发出去的密钥重启后就失效了）。

### PATCH /admin/access-keys/{id}

修改密钥配置。

**请求**：
```bash
# 停用
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"enabled": false}'

# 清空请求数上限与模型限制
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"clear": ["request_limit", "allowed_models"]}'
```

> **JSON 里传 `null` 表示「不改这个字段」**，不是「清空」。要真的清空 `expires_at` / `duration_days` / `request_limit` / `bound_account_ids` / `allowed_models`，必须把字段名放进 `clear` 数组。`clear` 里出现其它字段名返回 400。

### DELETE /admin/access-keys/{id}

吊销密钥，使用它的客户端立即断连。

**请求**：
```bash
curl -X DELETE http://localhost:5918/admin/access-keys/1 \
  -H "Authorization: Bearer sk-你的API密钥"
```

### POST /admin/access-keys/{id}/reset-usage

把 `request_count` 清零，已超额的密钥可继续使用。

**请求**：
```bash
curl -X POST http://localhost:5918/admin/access-keys/1/reset-usage \
  -H "Authorization: Bearer sk-你的API密钥"
```

> **计数口径**：每个业务请求在鉴权入口原子 +1，单调不减、不退还（上游报错也算）。**`GET /v1/models` 同样计数**——有些客户端每轮对话前都会列一次模型，等于一轮消耗 2 次，设 `request_limit` 时要留余量。

## 系统 API

### GET /health

健康检查（Docker 探针适配）。

**请求**：
```bash
curl http://localhost:5918/health
```

**响应**：
```json
{
  "status": "ok",
  "service": "gemini2api"
}
```

## 请求示例

### Python - OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/openai/v1"
)

# 非流式请求
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)

# 流式请求
for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True
):
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Python - Claude SDK

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/claude"
)

message = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)
print(message.content[0].text)
```

### JavaScript - Node.js

```javascript
import OpenAI from "@anthropic-ai/sdk";

const client = new OpenAI({
  apiKey: "sk-你的API密钥",
  baseURL: "http://localhost:5918/openai/v1"
});

const message = await client.chat.completions.create({
  model: "gemini-2.0-flash",
  messages: [{ role: "user", content: "Hello" }]
});

console.log(message.choices[0].message.content);
```

### cURL

```bash
# 非流式请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# 流式请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## 超时

生成超时**按模型族分层**（非流式与流式同一个预算），可用 `GENERATE_TIMEOUTS` 覆盖：

| 模型族 | 默认超时 |
|------|------|
| flash-lite | 60 秒 |
| flash | 120 秒 |
| pro | 300 秒 |
| argon | 300 秒 |
| 认不出的族 | 60 秒 |

疑似生图的请求与 `GENERATE_TIMEOUT_IMAGE`（默认 180 秒）**取大**。超时不再重试三遍——失败就是失败。

**流式请求**同样受这个预算约束：第一次进展（正文 / 思考 / 生成图片 / Canvas 有了新内容）必须在预算内到达，等响应头的时间也算在内；之后相邻两次进展的间隔同样不能超过预算。谷歌排队时每 60 秒发一个不含任何内容的心跳帧 `[{"37":[0]}]`，它**不算进展**；重复的帧、只带会话元数据的帧也不算。不会比族预算更早掐断：同账号 pro 不开思考做难题时，60 秒才回响应头、89 秒才出正文是正常回答。附件上传的时间不计入。到点后服务会先中止与谷歌的传输，再把 `timeout_error` 事件发给客户端。

超时回 **504**，错误类型 `timeout_error`，用各协议自己的错误体：OpenAI / Gemini 原生 / Responses 是 `{"error": {..., "type": "timeout_error"}}`，Anthropic 是 `{"type": "error", "error": {"type": "timeout_error", ...}}`（过去是纯文本的 `500 Internal Server Error`，SDK 解析不了、也不会按超时重试）。流式请求（含带工具的伪流式）已经回过 200，超时是协议内的错误事件：OpenAI 的 error 帧 `type` 为 `timeout_error`、`code` 为 `504`；Anthropic 的 `error` 事件与 Gemini 原生 NDJSON 的错误行 `type` 为 `timeout_error`；Responses 的 `response.failed` 里 `error.code` 为 `timeout_error`。生图接口 `/v1/images/generations` 同样回 504 + `timeout_error`；深度研究接口（`/gemini/v1beta/deepresearch`，以及 `/gemini/v1beta/deepresearch/interact` 的非流式请求）回 504，错误体是 `{"detail": "..."}`。

- 开了 `FALLBACK_ENABLED` 时，`/v1/chat/completions` 在还没向客户端发出正文前会先尝试第三方兜底，兜到了就不报错；另外三个协议没有第三方兜底，直接回上面的错误。
- 超时不会退回不思考重试，也不会用完整 prompt 重试：这一轮的预算已经花完，再试只会让客户端再等一整轮。
- 超时是谷歌那边卡住、不是 cookie 失效：不计入账号的连续失败，不会因此把账号标成 `expired`（只记一次错误、短暂冷却）。
- 建连阶段的超时（几秒就回来、没吃掉生成预算）照旧先在同一账号上重试几次；重试用完也按超时处理：回 504、不计入连续失败、不再退回不思考或用完整 prompt 重试。

> [!IMPORTANT]
> 非流式路径在生成返回之前**连接上是零字节输出**，所以这是**首字节**超时而不是空闲超时。
> **pro 非流式最长要干等 300 秒，会超过常见前置代理的首字节上限**（EdgeOne 免费版 15 秒，不少反向代理默认 60 秒），这时客户端拿到的是代理的 504 而不是本服务的错误体。
> 本服务自己的超时同样是 504，但带上面的 JSON 错误体（`timeout_error`），据此可以和代理的 504 区分开。
> 有前置代理的部署建议对这类请求直接用 `stream: true`（流式先发首帧、等待期间有保活帧）；流式请求同样受上表的预算约束，规则见上。

## 谷歌侧故障

谷歌那边某个模型族整体出问题时（2026-10-26 实测 gemini-flash 两段故障，三个账号都中招，同账号的 flash-lite、pro 正常），表现有两种：排队卡住（60 秒才回响应头，之后每 60 秒一个空心跳帧，按上面的[超时](#超时)处理），或者 1 秒左右就回一句固定的失败套话。

**失败套话**：整段回答（去掉首尾空白、连续空白压成一个、不分大小写）恰好是 `I seem to be encountering an error. Can I try something else for you?`（或 `GEMINI_FAILURE_REPLIES` 里追加的某句）时，按上游失败处理：换下一个账号重试；全部失败时 `/v1/chat/completions` 先试第三方兜底，否则回 **502 `api_error`**（OpenAI / Gemini 原生 / Responses 是 `{"error": {..., "type": "api_error"}}`，Anthropic 是 `{"type": "error", "error": {"type": "api_error", ...}}`，生图接口同样 502）。流式请求与别的上游错误一样是协议内的错误事件：OpenAI 的 error 帧 `type` 为 `api_error`、`code` 为 `502`；Anthropic 的 `error` 事件与 Gemini 原生 NDJSON 的错误行 `type` 为 `api_error`；Responses 的 `response.failed` 里 `error.code` 为 `internal_error`；深度研究接口照旧回 500。包含这句、以它开头、带生成图片的回答都不算，用户本来就让模型复述这句时也不算。套话不会写进会话记录，账号只短暂冷却、不计入连续失败。流式请求会先扣住还可能长成这句的开头（只影响回答开头这一小段），确认不是才放出去。 v1.6.47 起，谷歌的「语言模型」类拒答套话（如 `我只是一个语言模型，无法提供这方面的帮助。`、`I'm just a language model, so I can't help you with that.`）同样内置识别、同样换号 / 兜底 / 502，但不计入模型熔断（它也可能是某个问题每次都会触发的真拒答）。 比较时弯引号按直引号算。

**模型故障熔断**（只作用于 `/v1/chat/completions`）：窗口（`MODEL_BREAKER_WINDOW`，默认 300 秒）内有 `MODEL_BREAKER_THRESHOLD`（默认 2）个**不同请求**在同一个模型族上疑似故障地失败——失败套话、几乎没收到数据（< 1KB）的非流式生成超时、一次进展都没有的流式超时——熔断就打开 `MODEL_BREAKER_COOLDOWN`（默认 60）秒。这期间开了 `FALLBACK_ENABLED` 且有兜底候选的 `/v1/chat/completions` 请求**直接由第三方兜底回答**，不再先白等一个预算（流式请求照常先收到首帧，等兜底期间有保活帧）；兜底没答出来就照常调谷歌，之后不再重复兜底。到期后放一个真实请求去试探谷歌：成功立即恢复，失败开放期翻倍（封顶 `MODEL_BREAKER_MAX_COOLDOWN`）。没开兜底的请求、其它协议、深度研究、生图一律照常调谷歌，它们的结果照样更新熔断状态；只影响故障的那个族。各族状态见 `GET /admin/status`（和 `GET /admin/accounts`）的 `model_breakers`；进程重启后清空。

## 获取帮助

- 查看 [DEPLOY.md](./DEPLOY.md) 了解部署方法
- 查看 [USAGE.md](./USAGE.md) 了解使用方法
- 查看 [README.md](../../README.md) 了解项目概况
- 提交 Issue：[GitHub Issues](https://github.com/xwteam/gemini2api/issues)
