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
    }
  ]
}
```

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
    "refresh_interval": 5
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
