# API 文檔

本文檔詳細說明 Gemini2API 的所有 API 端點、請求格式和回應格式。

## 認證

所有 API 請求都需要有效的 API Key。支援兩種認證方式：

**方式 1：Authorization Header（推薦）**
```bash
curl -H "Authorization: Bearer sk-your-api-key" http://localhost:5918/...
```

**方式 2：x-api-key Header**
```bash
curl -H "x-api-key: sk-your-api-key" http://localhost:5918/...
```

> **注意：** API Key 在首次啟動時自動生成，格式為 `sk-` 前綴 + 32 位隨機字元。

## OpenAI 相容 API（`/openai/v1`）

### GET /models

列出所有可用模型。

**請求：**
```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
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

### POST /chat/completions

發送對話請求，支援流式和非流式回應。

**請求體：**
```json
{
  "model": "gemini-2.5-pro",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 2048,
  "conversation_id": "optional-conv-id",
  "tools": [],
  "tool_choice": "auto"
}
```

**參數說明：**

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `model` | string | ✅ | 模型名稱（如 gemini-flash） |
| `messages` | array | ✅ | 訊息陣列，每個訊息包含 role 和 content。`content` 可以是字串或物件陣列（支援多模態） |
| `stream` | boolean | ❌ | 是否流式輸出（預設 false） |
| `temperature` | number | ❌ | 溫度參數，0-2（預設 0.7） |
| `max_tokens` | number | ❌ | 最大回應 token 數 |
| `conversation_id` | string | ❌ | 對話 ID，用於維持上下文 |
| `tools` | array | ❌ | 函數定義陣列 |
| `tool_choice` | string | ❌ | 工具選擇策略（auto/required/none） |

**多模態 content 格式**：

`content` 可以是字串（純文字）或物件陣列（支援文字和圖片）：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "這是什麼"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
      }
    }
  ]
}
```

支援的 content 類型：
- `text`：純文字內容
- `image_url`：圖片，支援 Base64 Data URI（`data:image/...;base64,...`）和遠端 HTTP URL

**非流式回應：**
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
        "content": "你好！有什麼我可以幫助你的嗎？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  },
  "conversation_id": "optional-conv-id"
}
```

**流式回應（SSE 格式）：**
```
data: {"choices":[{"delta":{"content":"你"},"index":0}]}
data: {"choices":[{"delta":{"content":"好"},"index":0}]}
data: [DONE]
```

## Claude 相容 API（`/claude/v1`）

### GET /models

列出所有可用模型。

**請求：**
```bash
curl http://localhost:5918/claude/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
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

### GET /models/{id}

取得特定模型詳情。

**請求：**
```bash
curl http://localhost:5918/claude/v1/models/gemini-2.5-pro \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /messages

發送訊息請求（Claude 格式）。

**請求體：**
```json
{
  "model": "gemini-2.5-pro",
  "max_tokens": 1024,
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "stream": false
}
```

**回應：**
```json
{
  "id": "msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "你好！有什麼我可以幫助你的嗎？"
    }
  ],
  "model": "gemini-2.5-pro",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 10,
    "output_tokens": 20
  }
}
```

### POST /messages/count_tokens

估算訊息的 token 數。

**請求體：**
```json
{
  "model": "gemini-2.5-pro",
  "messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

**回應：**
```json
{
  "input_tokens": 10
}
```

## Gemini 原生 API（`/gemini/v1beta`）

### GET /models

列出所有可用模型。

**請求：**
```bash
curl http://localhost:5918/gemini/v1beta/models \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /models/{model}:generateContent

生成內容（非流式）。

**請求體：**
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "你好"}]
    }
  ],
  "generationConfig": {
    "temperature": 0.7,
    "maxOutputTokens": 2048
  }
}
```

**回應：**
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [{"text": "你好！有什麼我可以幫助你的嗎？"}]
      },
      "finishReason": "STOP"
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 20,
    "totalTokenCount": 30
  }
}
```

### POST /models/{model}:streamGenerateContent

流式生成內容（Chunked JSON 格式）。

**請求體：**
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "你好"}]
    }
  ]
}
```

**流式回應：**
```
[{"candidates":[{"content":{"parts":[{"text":"你"}]}}]}]
[{"candidates":[{"content":{"parts":[{"text":"好"}]}}]}]
```

## 管理 API（`/admin`）

### GET /status

取得服務狀態和帳號池概覽。

**請求：**
```bash
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "status": "ok",
  "total_accounts": 2,
  "active_accounts": 2,
  "rotation_strategy": "round-robin",
  "accounts": [
    {
      "id": "account-0",
      "label": "主帳號",
      "healthy": true,
      "last_check": "2025-05-17T10:30:00Z"
    }
  ]
}
```

### GET /system-info

取得系統資訊。

**請求：**
```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "version": "1.1.0",
  "python_version": "3.12.0",
  "server_time": "2025/05/17 10:30:00",
  "os": "Linux 6.17.0",
  "memory_usage": 256,
  "memory_total": 2048,
  "cpu_percent": 15.5,
  "pid": 12345,
  "run_mode": "Docker",
  "uptime_seconds": 3600
}
```

### GET /accounts

列出所有帳號。

**請求：**
```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "accounts": [
    {
      "id": "account-0",
      "label": "主帳號",
      "healthy": true,
      "last_check": "2025-05-17T10:30:00Z",
      "request_count": 150
    }
  ]
}
```

### POST /accounts

新增帳號。

**請求體：**
```json
{
  "psid": "g.a000xxx...",
  "psidts": "sidts-xxx...",
  "label": "新帳號"
}
```

**回應：**
```json
{
  "id": "account-2",
  "label": "新帳號",
  "healthy": true
}
```

### DELETE /accounts/{id}

刪除帳號。

**請求：**
```bash
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{"status": "ok", "message": "Account deleted"}
```

### GET /accounts/{id}/check

檢測單個帳號狀態。

**請求：**
```bash
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "id": "account-0",
  "healthy": true,
  "message": "Account is healthy"
}
```

### POST /reload-cookies

重新載入 Cookie（從 .env 或指定值）。

**請求體（可選）：**
```json
{
  "psid": "g.a000new...",
  "psidts": "sidts-new..."
}
```

**回應：**
```json
{
  "status": "ok",
  "message": "Cookies reloaded successfully",
  "healthy": true
}
```

### PUT /admin/accounts/{id}/cookies

更新特定帳號的 Cookie。

**請求體：**
```json
{
  "psid": "g.a000new...",
  "psidts": "sidts-new..."
}
```

**回應：**
```json
{
  "status": "ok",
  "message": "Cookies updated"
}
```

### GET /health-history

取得最近的健康檢查記錄。

**請求：**
```bash
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /usage-stats/summary

取得使用統計概覽。

**請求：**
```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "total_requests": 1000,
  "error_rate": 0.02,
  "avg_latency_ms": 2500,
  "cookie_rotation_success_rate": 0.98
}
```

### GET /usage-stats/history

取得歷史趨勢數據。

**查詢參數：**
- `granularity`：時間粒度（minute/hour/day，預設 hour）
- `hours`：查詢時間範圍（預設 24）

**請求：**
```bash
curl "http://localhost:5918/admin/usage-stats/history?granularity=hour&hours=24" \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /settings

取得當前可編輯配置。

**請求：**
```bash
curl http://localhost:5918/admin/settings \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "performance": {
    "max_concurrent_per_account": 3,
    "rotation_strategy": "round-robin"
  },
  "rate_limit": {
    "enabled": false,
    "window": 60,
    "max": 10
  }
}
```

### POST /settings

批量更新配置。

**請求體：**
```json
{
  "max_concurrent_per_account": 5,
  "rotation_strategy": "failover",
  "rate_limit_enabled": true
}
```

**回應：**
```json
{
  "status": "ok",
  "message": "Settings updated"
}
```

### GET /api-keys

列出所有 API Key。

**請求：**
```bash
curl http://localhost:5918/admin/api-keys \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /api-keys

新增 API Key。

**請求體：**
```json
{
  "provider": "openai",
  "key": "sk-xxx...",
  "label": "My OpenAI Key"
}
```

### DELETE /api-keys/{id}

刪除 API Key。

**請求：**
```bash
curl -X DELETE http://localhost:5918/admin/api-keys/key-123 \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /logs

取得結構化日誌。

**查詢參數：**
- `direction`：排序方向（asc/desc，預設 desc）
- `search`：搜尋關鍵字
- `limit`：每頁記錄數（預設 15）
- `offset`：分頁偏移

**請求：**
```bash
curl "http://localhost:5918/admin/logs?limit=15&offset=0" \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /logs/clear

清空所有日誌。

**請求：**
```bash
curl -X POST http://localhost:5918/admin/logs/clear \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /model-mapping

取得所有模型映射。

**請求：**
```bash
curl http://localhost:5918/admin/model-mapping \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/model-mapping

新增或更新模型映射。

**請求體：**
```json
{
  "alias": "gpt-4o",
  "target": "gemini-2.5-pro"
}
```

### DELETE /admin/model-mapping/{alias}

刪除模型映射。

**請求：**
```bash
curl -X DELETE http://localhost:5918/admin/model-mapping/gpt-4o \
  -H "Authorization: Bearer sk-your-api-key"
```

## 系統 API

### GET /health

健康檢查（Docker 探針適配）。

**請求：**
```bash
curl http://localhost:5918/health
```

**回應：**
```json
{"status":"ok","service":"gemini2api"}
```

## 錯誤碼

| 狀態碼 | 說明 |
|--------|------|
| 200 | 成功 |
| 400 | 參數錯誤 |
| 401 | 未認證（API Key 無效或缺失） |
| 403 | 禁止（API Key 無效） |
| 500 | 伺服器錯誤 |
| 503 | 服務不可用（無可用帳號） |

**錯誤回應格式：**
```json
{
  "error": {
    "message": "Invalid API key",
    "type": "invalid_request_error"
  }
}
```

## 速率限制

如果啟用了速率限制（`RATE_LIMIT_ENABLED=true`），超過限制的請求會返回 429 狀態碼：

```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error"
  }
}
```

## 最佳實踐

1. **使用 conversation_id 維持上下文**：對於需要多輪對話的場景，使用相同的 conversation_id
2. **實現重試邏輯**：對於 5xx 錯誤實現指數退避重試
3. **監控使用統計**：定期檢查 `/admin/usage-stats/summary` 了解服務狀態
4. **定期更新 Cookie**：監控帳號健康狀態，及時更新過期 Cookie
5. **使用流式輸出**：對於長回應，使用 `stream: true` 改善使用者體驗
