# API Reference

Complete API documentation for gemini2api. All endpoints require authentication via API Key.

## Authentication

All API requests must include an API Key in one of these formats:

**Option 1: Authorization Header (Recommended)**
```
Authorization: Bearer sk-your-api-key
```

**Option 2: Custom Header**
```
x-api-key: sk-your-api-key
```

Example:
```bash
curl http://localhost:5918/health \
  -H "Authorization: Bearer sk-your-api-key"
```

## Standard Bare Paths

As of v1.6.4, each API supports two sets of paths:

**Prefixed paths** (explicit per-provider, used in the endpoint documentation below):
- OpenAI: `/openai/v1/chat/completions`, `/openai/v1/models`
- Claude: `/claude/v1/messages`, `/claude/v1/messages/count_tokens`, `/claude/v1/models`
- Gemini: `/gemini/v1beta/models/{model}:generateContent`, `/gemini/v1beta/models/{model}:streamGenerateContent`, `/gemini/v1beta/models`

**Standard bare paths** (new in v1.6.4, major SDKs work out of the box without suffix on base_url):
- OpenAI: `/v1/chat/completions`, `/v1/models`
- Claude: `/v1/messages`, `/v1/messages/count_tokens`
- Gemini: `/v1beta/models/{model}:generateContent`, `/v1beta/models/{model}:streamGenerateContent`, `/v1beta/models`

**Important**: The bare `/v1/models` endpoint returns OpenAI format (a single path cannot return two formats). For the Claude-format model list, use `/claude/v1/models`.

## OpenAI Compatible API

These endpoints follow OpenAI API format and are compatible with OpenAI SDKs.

### GET /openai/v1/models

List available models.

**Request:**
```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-pro",
      "object": "model",
      "created": 1715970000,
      "owned_by": "google"
    },
    {
      "id": "gemini-flash",
      "object": "model",
      "created": 1715970000,
      "owned_by": "google"
    },
    {
      "id": "gemini-flash-thinking",
      "object": "model",
      "created": 1715970000,
      "owned_by": "google"
    }
  ]
}
```

### POST /openai/v1/chat/completions

Generate chat completions. Supports streaming and function calling.

**Request:**
```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "What is 2+2?"}
    ],
    "stream": false,
    "temperature": 0.7,
    "max_tokens": 1024
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Model ID (e.g., `gemini-flash`) |
| `messages` | array | Yes | Message history with `role` and `content`. `content` can be a string or array of objects (supports multimodal) |
| `stream` | boolean | No | Enable streaming (default: false) |
| `temperature` | number | No | Randomness 0-2 (default: 1.0) |
| `max_tokens` | number | No | Max response length (default: 4096) |
| `top_p` | number | No | Nucleus sampling 0-1 (default: 1.0) |
| `tools` | array | No | Function definitions for tool calling |
| `tool_choice` | string | No | `auto`, `required`, or function name |
| `conversation_id` | string | No | Maintain context across requests |

**Multimodal Content Format:**

`content` can be a string (text only) or array of objects (supports text and images):

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "What is this"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
      }
    }
  ]
}
```

Supported content types:
- `text`: Plain text content
- `image_url`: Image supporting Base64 Data URI (`data:image/...;base64,...`) and remote HTTP URLs

**Response (Non-Streaming):**
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1715970000,
  "model": "gemini-2.5-pro",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "2 + 2 = 4"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  },
  "conversation_id": "conv-xxx"
}
```

**Response (Streaming):**
```
data: {"choices":[{"delta":{"content":"2"},"index":0}]}
data: {"choices":[{"delta":{"content":" "},"index":0}]}
data: {"choices":[{"delta":{"content":"+"},"index":0}]}
...
data: [DONE]
```

**Function Calling Example:**
```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "What is the weather in Paris?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get weather for a city",
          "parameters": {
            "type": "object",
            "properties": {
              "city": {"type": "string"}
            },
            "required": ["city"]
          }
        }
      }
    ]
  }'
```

## Claude Compatible API

These endpoints follow Anthropic Claude API format.

### GET /claude/v1/models

List available models.

**Request:**
```bash
curl http://localhost:5918/claude/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "data": [
    {
      "id": "gemini-2.5-pro",
      "type": "model",
      "display_name": "Gemini 2.5 Pro"
    }
  ]
}
```

### POST /claude/v1/messages

Generate messages using Claude API format.

**Request:**
```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "stream": false
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Model ID |
| `max_tokens` | number | Yes | Maximum response tokens |
| `messages` | array | Yes | Message history |
| `stream` | boolean | No | Enable streaming |
| `temperature` | number | No | Randomness 0-2 |
| `tools` | array | No | Tool definitions |

**Response:**
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
  "model": "gemini-2.5-pro",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 10,
    "output_tokens": 15
  }
}
```

### POST /claude/v1/messages/count_tokens

Estimate token count for messages.

**Request:**
```bash
curl -X POST http://localhost:5918/claude/v1/messages/count_tokens \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

**Response:**
```json
{
  "input_tokens": 10
}
```

## Gemini Native API

These endpoints follow Google Gemini API format.

### GET /gemini/v1beta/models

List available models.

**Request:**
```bash
curl http://localhost:5918/gemini/v1beta/models \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "models": [
    {
      "name": "models/gemini-2.5-pro",
      "displayName": "Gemini 2.5 Pro",
      "description": "Latest Gemini model",
      "inputTokenLimit": 1000000,
      "outputTokenLimit": 4096
    }
  ]
}
```

### POST /gemini/v1beta/models/{model}:generateContent

Generate content using Gemini format.

**Request:**
```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.5-pro:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "Hello"}]
      }
    ],
    "generationConfig": {
      "temperature": 0.7,
      "maxOutputTokens": 1024
    }
  }'
```

**Response:**
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [{"text": "Hello! How can I help?"}]
      },
      "finishReason": "STOP"
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 5,
    "totalTokenCount": 15
  }
}
```

### POST /gemini/v1beta/models/{model}:streamGenerateContent

Stream content generation (Chunked JSON format).

**Request:**
```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.5-pro:streamGenerateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "contents": [{"role": "user", "parts": [{"text": "Hello"}]}]
  }'
```

**Response (Chunked):**
```
[{"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}]
[{"candidates":[{"content":{"parts":[{"text":"!"}]}}]}]
```

## Admin API

Administrative endpoints for account and service management. Require API Key authentication.

### GET /admin/status

Get service and account pool status.

**Request:**
```bash
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "service": "gemini2api",
  "status": "ok",
  "accounts": [
    {
      "id": "account-0",
      "label": "Primary",
      "status": "healthy",
      "last_checked": "2025-05-17T10:30:00Z"
    }
  ],
  "rotation_strategy": "round-robin",
  "total_requests": 1234,
  "failed_requests": 5
}
```

### GET /admin/system-info

Get system information.

**Request:**
```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "version": "1.1.0",
  "python_version": "3.12.1",
  "server_time": "2025/05/17 10:30:00",
  "os": "Linux 6.1.0",
  "memory_usage": 256,
  "memory_total": 2048,
  "cpu_percent": 15.5,
  "pid": 12345,
  "run_mode": "Docker",
  "uptime_seconds": 3600
}
```

### GET /admin/accounts

List all accounts.

**Request:**
```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "accounts": [
    {
      "id": "account-0",
      "label": "Primary Account",
      "status": "healthy",
      "last_checked": "2025-05-17T10:30:00Z",
      "active_requests": 2
    }
  ]
}
```

### POST /admin/accounts

Add a new account.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000xxx...",
    "psidts": "sidts-xxx...",
    "label": "New Account"
  }'
```

**Response:**
```json
{
  "status": "ok",
  "account": {
    "id": "account-1",
    "label": "New Account",
    "status": "healthy"
  }
}
```

### DELETE /admin/accounts/{id}

Remove an account.

**Request:**
```bash
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "status": "ok",
  "message": "Account account-1 removed"
}
```

### GET /admin/accounts/{id}/check

Check single account health.

**Request:**
```bash
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "id": "account-0",
  "status": "healthy",
  "checked_at": "2025-05-17T10:30:00Z",
  "response_time_ms": 250
}
```

### PUT /admin/accounts/{id}/cookies

Update account cookies.

**Request:**
```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new..."
  }'
```

**Response:**
```json
{
  "status": "ok",
  "message": "Cookies updated successfully"
}
```

### POST /admin/reload-cookies

Reload cookies from .env file.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "status": "ok",
  "message": "Cookies reloaded successfully",
  "healthy": true
}
```

### GET /admin/health-history

Get recent health check history.

**Request:**
```bash
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "total": 50,
  "records": [
    {
      "account_id": "account-0",
      "status": "healthy",
      "checked_at": "2025-05-17T10:30:00Z",
      "response_time_ms": 250
    }
  ]
}
```

### GET /admin/logs

Get structured logs with pagination.

**Request:**
```bash
curl "http://localhost:5918/admin/logs?limit=15&offset=0&direction=all&search=" \
  -H "Authorization: Bearer sk-your-api-key"
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | number | Entries per page (default: 15) |
| `offset` | number | Pagination offset (default: 0) |
| `direction` | string | Filter: `all`, `request`, `response`, `error` |
| `search` | string | Text search in logs |

**Response:**
```json
{
  "total": 1234,
  "logs": [
    {
      "id": "log-xxx",
      "timestamp": "2025-05-17T10:30:00Z",
      "level": "info",
      "message": "Request received",
      "details": {}
    }
  ]
}
```

### POST /admin/logs/clear

Clear all logs.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/logs/clear \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "status": "ok",
  "message": "Logs cleared"
}
```

### GET /admin/usage-stats/summary

Get usage statistics summary.

**Request:**
```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "total_requests": 5000,
  "error_rate": 0.5,
  "avg_latency_ms": 1250,
  "cookie_refresh_success_rate": 99.8
}
```

### GET /admin/usage-stats/history

Get historical usage trends.

**Request:**
```bash
curl "http://localhost:5918/admin/usage-stats/history?granularity=hourly&hours=24" \
  -H "Authorization: Bearer sk-your-api-key"
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `granularity` | string | `hourly`, `daily` |
| `hours` | number | Look back period in hours |

**Response:**
```json
{
  "data": [
    {
      "timestamp": "2025-05-17T10:00:00Z",
      "requests": 100,
      "errors": 1,
      "avg_latency_ms": 1200
    }
  ]
}
```

### GET /admin/settings

Get current configuration.

**Request:**
```bash
curl http://localhost:5918/admin/settings \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "performance": {
    "max_concurrent_per_account": 3,
    "max_retries": 3
  },
  "rate_limiting": {
    "enabled": false,
    "window": 60,
    "max": 10
  },
  "health_checks": {
    "enabled": true,
    "interval": 5
  }
}
```

### POST /admin/settings

Update configuration.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "max_concurrent_per_account": 5,
    "rate_limit_enabled": true
  }'
```

**Response:**
```json
{
  "status": "ok",
  "message": "Settings updated"
}
```

### GET /admin/api-keys

List API keys (passwords masked).

**Request:**
```bash
curl http://localhost:5918/admin/api-keys \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "keys": [
    {
      "id": "key-xxx",
      "provider": "openai",
      "model": "gpt-4o",
      "status": "active",
      "key": "sk-***...***"
    }
  ]
}
```

### POST /admin/api-keys

Add an API key.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "provider": "openai",
    "key": "sk-...",
    "model": "gpt-4o"
  }'
```

**Response:**
```json
{
  "status": "ok",
  "id": "key-xxx"
}
```

### DELETE /admin/api-keys/{id}

Delete an API key.

**Request:**
```bash
curl -X DELETE http://localhost:5918/admin/api-keys/key-xxx \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "status": "ok"
}
```

### GET /admin/model-mapping

Get all model mappings.

**Request:**
```bash
curl http://localhost:5918/admin/model-mapping \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "mappings": [
    {
      "alias": "gpt-4o",
      "target": "gemini-2.5-pro"
    }
  ]
}
```

### POST /admin/model-mapping

Add or update a model mapping.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/model-mapping \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "alias": "gpt-4o",
    "target": "gemini-2.5-pro"
  }'
```

**Response:**
```json
{
  "status": "ok"
}
```

### DELETE /admin/model-mapping/{alias}

Delete a model mapping.

**Request:**
```bash
curl -X DELETE http://localhost:5918/admin/model-mapping/gpt-4o \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "status": "ok"
}
```

## System Endpoints

### GET /health

Health check endpoint (no authentication required).

**Request:**
```bash
curl http://localhost:5918/health
```

**Response:**
```json
{
  "status": "ok",
  "service": "gemini2api"
}
```

## Error Responses

All error responses follow this format:

```json
{
  "error": {
    "message": "Error description",
    "type": "error_type"
  }
}
```

### HTTP Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request succeeded |
| 400 | Bad Request | Invalid request parameters |
| 401 | Unauthorized | Missing or invalid API Key |
| 403 | Forbidden | Access denied |
| 500 | Internal Error | Server error |
| 503 | Service Unavailable | No healthy accounts available |

### Common Error Types

| Type | Cause | Solution |
|------|-------|----------|
| `auth_error` | Invalid API Key | Verify API Key in Authorization header |
| `model_not_found` | Model doesn't exist | Check available models with `/openai/v1/models` |
| `no_available_accounts` | All accounts unhealthy | Refresh cookies, check account status |
| `rate_limit_exceeded` | Too many requests | Wait before retrying |
| `invalid_request` | Malformed request | Check request format and parameters |

## Rate Limiting

Rate limiting is optional and disabled by default. When enabled:

- Requests exceeding the limit receive HTTP 429 (Too Many Requests)
- Limit resets after the configured window
- Configure via Settings or `.env`:
  ```env
  RATE_LIMIT_ENABLED=true
  RATE_LIMIT_WINDOW=60
  RATE_LIMIT_MAX=10
  ```

## Streaming

Streaming responses use different formats depending on the API:

**OpenAI Format (SSE):**
```
data: {"choices":[{"delta":{"content":"text"}}]}
data: [DONE]
```

**Gemini Format (Chunked JSON):**
```
[{"candidates":[{"content":{"parts":[{"text":"text"}]}}]}]
```

Set `stream: true` in request body to enable streaming.
