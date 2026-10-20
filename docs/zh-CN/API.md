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
| 503 | `service_unavailable_error` | 无可用账号 |

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
      "id": "gemini-flash-thinking",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-flash-lite",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    }
  ]
}
```

> 💡 **模型选择建议**：四个模型对应不同的速度/质量权衡。
> - `gemini-flash`：最快（响应约 4-5 秒），适合 **agent / 高频 / 高并发**场景，推荐作为默认选择。
> - `gemini-flash-thinking`：带思考过程，速度接近 flash，适合需要推理的任务。
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
| `conversation_id` | string | 否 | 对话 ID，用于维护上下文 |

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
  "total_accounts": 2,
  "active_accounts": 2,
  "rotation_strategy": "round-robin",
  "accounts": [
    {
      "id": "account-0",
      "status": "healthy",
      "requests": 10,
      "last_check": "2025-05-17T23:35:00"
    },
    {
      "id": "account-1",
      "status": "healthy",
      "requests": 8,
      "last_check": "2025-05-17T23:35:00"
    }
  ]
}
```

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

## 获取帮助

- 查看 [DEPLOY.md](./DEPLOY.md) 了解部署方法
- 查看 [USAGE.md](./USAGE.md) 了解使用方法
- 查看 [README.md](../../README.md) 了解项目概况
- 提交 Issue：[GitHub Issues](https://github.com/xwteam/gemini2api/issues)
