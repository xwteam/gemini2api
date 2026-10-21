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

### 兩種可用的金鑰

| 類型 | 來源 | 能存取 | 計數 |
|------|------|--------|------|
| `API_KEY`（`.env`） | 首次啟動自動生成，或自行設定 | 業務 API + `/admin/*`（未單獨設定 `ADMIN_API_KEY` 時） | 不計 |
| 存取金鑰 | 管理員在面板「存取金鑰」頁或 `POST /admin/access-keys` 簽發 | **只有業務 API**，存取不到 `/admin/*` | 每個請求 +1 |

存取金鑰是**附加**的一層：`API_KEY` 始終保有全部權限，一把存取金鑰都不簽發時認證行為與舊版完全一致。存取金鑰可以各自帶有效期、請求數上限、綁定帳號與允許模型，詳見 `POST /admin/access-keys`。

存取金鑰失效時的狀態碼：已停用／已到期／已超額都回傳 401，回應內文裡的 `message` 會說明具體原因。

## 路徑說明

自 v1.6.4 起，每家介面同時支援兩套路徑：

**帶前綴路徑（三家明確區分）：**
- OpenAI：`/openai/v1`
- Claude：`/claude/v1`
- Gemini：`/gemini/v1beta`

**標準裸路徑（v1.6.4 新增，主流 SDK 填 base_url 無需加後綴開箱即用）：**
- OpenAI：`/v1/chat/completions`、`/v1/models`
- Claude：`/v1/messages`、`/v1/messages/count_tokens`
- Gemini：`/v1beta/models/{model}:generateContent`、`:streamGenerateContent`、`/v1beta/models`

> **重要：** 裸 `/v1/models` 回傳 OpenAI 格式（同一路徑無法同時回傳兩種格式）；需要 Claude 格式的模型列表請用 `/claude/v1/models`。

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

> 💡 **模型選擇建議**：四個模型對應不同的速度/品質權衡。
> - `gemini-flash`：最快(回應約 4-5 秒),適合 **agent / 高頻 / 高並發**場景,推薦作為預設選擇。
> - `gemini-flash-thinking`：帶思考過程,速度接近 flash,適合需要推理的任務。
> - `gemini-flash-lite`：最輕量最快的檔位（3.5 Flash-Lite），Pro/Flash 被限額時可作為可用兜底。
> - `gemini-pro`：品質最高但較慢(回應約 9-17 秒,長上下文更慢),適合對品質要求高、不在意延遲的場景。
>
> agent 類客戶端(會並發發起大量請求)建議優先用 `gemini-flash`。本服務的串流介面為真正的增量串流,首字一生成即開始推送。

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

### POST /responses

OpenAI Responses API。為需要新版 Responses 協議（而非 Chat Completions）的客戶端提供支援——例如 **Codex CLI**，它在 2026 年 2 月起砍掉了對 Chat Completions 的支援，要把 Codex CLI 接到 gemini2api 就得靠這個介面。支援文字對話、流式輸出、工具（函數）呼叫，Gemini 模型和 API 管理裡設定的第三方模型都能用。

**請求**：
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "1+1等於幾？",
    "stream": false
  }'
```

**請求體**：

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `model` | string | ✅ | 模型名稱，如 `gemini-flash`，或 API 管理裡設定的第三方模型 |
| `input` | string 或 array | ✅ | 字串（等同一條 user 訊息的簡寫），或輸入條目陣列（見下） |
| `instructions` | string | ❌ | 系統/開發者前置說明，加在對話最前面 |
| `stream` | boolean | ❌ | 是否流式回傳，預設 false |
| `tools` | array | ❌ | 函數呼叫工具定義，**扁平格式**：`{"type":"function","name","description","parameters"}`（注意：跟 Chat Completions 的巢狀格式 `{"type":"function","function":{...}}` 不一樣） |
| `tool_choice` | string 或 object | ❌ | `auto`、`none`、`required`，或 `{"type":"function","name":"..."}` 指定必須呼叫某個工具 |
| `temperature` | number | ❌ | 隨機性（會透傳給第三方模型；Gemini 路徑不生效） |
| `max_output_tokens` | number | ❌ | 最大輸出長度（會透傳給第三方模型；Gemini 路徑不生效） |

**`input` 陣列條目類型**：
- `{"type":"message","role":"user"|"assistant"|"system","content":[...]}` —— 內容區塊：`{"type":"input_text","text":...}`、`{"type":"input_image","image_url":"..."}`、`{"type":"output_text","text":...}`
- `{"type":"function_call","call_id","name","arguments"}` —— 歷史裡助手呼叫工具的那一輪（多輪續聊需要客戶端自己重發完整歷史）
- `{"type":"function_call_output","call_id","output"}`（或 `"tool_result"`）—— 客戶端回傳的工具執行結果

**明確不支援（會報錯，不會假裝支援）**：`previous_response_id`——本服務不儲存伺服器端對話狀態，傳了這個欄位會回傳 400 `invalid_request_error`，而不是悄悄忽略。請每次請求都在 `input` 裡帶上完整對話歷史（Codex CLI 本身就是這麼做的）。

**回應（非流式）**：
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
        {"type": "output_text", "text": "1+1等於2", "annotations": []}
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

**回應（流式）**：嚴格按官方協議順序發送帶命名的 SSE 事件，每個事件都帶遞增的 `sequence_number`。**沒有** `data: [DONE]` 結尾標記（那是 Chat Completions 的老約定）——完成訊號是 `response.completed`（失敗是 `response.failed`）：

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
data: {"type":"response.output_text.done","sequence_number":5,"text":"1+1等於2"}

event: response.content_part.done
data: {"type":"response.content_part.done","sequence_number":6,...}

event: response.output_item.done
data: {"type":"response.output_item.done","sequence_number":7,...}

event: response.completed
data: {"type":"response.completed","sequence_number":8,"response":{...}}
```

工具呼叫場景下，`response.output_item.added`（類型 `function_call`）之後跟的是 `response.function_call_arguments.delta` / `response.function_call_arguments.done` / `response.output_item.done`，而不是上面的文字事件。

**工具呼叫範例**：
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "查一下巴黎的天氣",
    "tools": [
      {
        "type": "function",
        "name": "get_weather",
        "description": "取得指定城市的天氣",
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
回應 `output` 裡會含有一個 `function_call` 條目：
```json
{"id": "fc_xxx", "type": "function_call", "status": "completed", "call_id": "call_xxx", "name": "get_weather", "arguments": "{\"city\": \"巴黎\"}"}
```

### POST /images/generations

AI 生成圖片。透過 `prompt` 觸發圖片生成，回傳 `b64_json` 格式的圖片資料。

> 同時支援裸路徑 `POST /v1/images/generations` 與帶前綴路徑 `POST /openai/v1/images/generations`。

**請求：**
```bash
curl -X POST http://localhost:5918/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-pro","prompt":"a cute cat","n":1}'
```

**請求體：**
```json
{
  "model": "gemini-pro",
  "prompt": "a cute cat",
  "n": 1
}
```

**參數說明：**

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `model` | string | ✅ | 模型名稱（如 gemini-pro） |
| `prompt` | string | ✅ | 圖片描述提示詞 |
| `n` | number | ❌ | 生成圖片數量（預設 1） |

**回應：**
```json
{
  "created": 1715970000,
  "data": [
    {"b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."}
  ]
}
```

> **提示：** 三家對話介面（OpenAI/Claude/Gemini）在偵測到回應中含有生成圖片時，也會自動將圖片嵌入回覆（OpenAI 以 markdown 圖片語法、Claude 以 image block、Gemini 以 inlineData 形式）。

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
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 20
  }
}
```

#### 擴展思考（`thinking`）

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `thinking` | object | ❌ | 開啟擴展思考。**不傳該參數時行為與舊版逐字節一致** |

- `{"type":"enabled","budget_tokens":N}`：開啟。`N` 按 `<2048` / `2048–4095` / `≥4096` 分成低／中／高三檔。
- `{"type":"adaptive"}`：開啟，用預設檔。
- `{"type":"disabled"}` / `{"type":"between_tools"}`：不思考，與完全不傳該參數**逐字節相同**。

思考內容以 Anthropic 規範的 `thinking` 內容區塊回傳，排在 `text` / `tool_use` 區塊**之前**；流式下是 `content_block_start(thinking)` → `thinking_delta` → `content_block_stop`。

⚠️ **不帶 `signature`**（本服務造不出合法簽名，發空串／自造串更糟：客戶端回傳給真 API 會 400）。**檔位與網頁端思考深度的對應關係尚未真機證實**。全域開關 `EXTENDED_THINKING_ENABLED=false` 時即使傳了也不走思考路徑。

⚠️ **正文開始之後才到的思考增量會被丟掉**（流式）：Anthropic 的區塊順序不允許在 `text` 之後再開或再續 `thinking` 區塊（會打一條 WARNING 說明丟了多少字元）。需要完整思考鏈請用 OpenAI 協議的 `reasoning_content`。正文永遠完整。`thinking` 傳成非物件時按**沒傳**處理、照常回 200。

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

### PATCH /admin/api-keys/{id}/label

修改 Key 標籤。

**請求：**
```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-1/label \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"label": "我的 OpenAI Key"}'
```

### GET /api-keys/export

匯出所有 Key。預設脫敏；加 `?reveal=true` 取明文。

**請求：**
```bash
curl "http://localhost:5918/admin/api-keys/export?reveal=true" \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/api-keys/models

探測某 Provider / base_url 下可用的模型列表（用於新增 Key 時填充模型下拉）。

**請求：**
```bash
curl -X POST http://localhost:5918/admin/api-keys/models \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "provider": "openai",
    "api_key": "sk-xxx",
    "base_url": "https://api.openai.com/v1"
  }'
```

### POST /admin/restart

重啟服務（面板右上角一鍵重啟，重啟後自動輪詢恢復）。

**請求：**
```bash
curl -X POST http://localhost:5918/admin/restart \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /admin/check-update

檢查是否有新版本。

**請求：**
```bash
curl http://localhost:5918/admin/check-update \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/update

觸發更新到最新版本。

**請求：**
```bash
curl -X POST http://localhost:5918/admin/update \
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

### GET /admin/web-chats

列出帳號在 Gemini 網頁端的會話（唯讀）。

**請求：**
```bash
curl http://localhost:5918/admin/web-chats \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "chats": [
    {
      "id": "chat-xxx",
      "title": "對話標題",
      "pinned": false,
      "created_at": "2026-06-05T12:00:00Z"
    }
  ]
}
```

### POST /admin/cleanup-web-chats

手動觸發清理超過保留時長的網頁會話。置頂會話不會被刪除，活躍對話不受影響。後台非同步執行，立即回傳。

**請求體：**
```json
{
  "keep_hours": 24,
  "skip_pinned": true
}
```

**參數說明：**

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `keep_hours` | number | ✅ | 保留時長（小時），超過此時長的會話將被刪除 |
| `skip_pinned` | boolean | ❌ | 是否跳過置頂會話（預設 true） |

**請求：**
```bash
curl -X POST http://localhost:5918/admin/cleanup-web-chats \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"keep_hours": 24, "skip_pinned": true}'
```

**回應：**
```json
{
  "status": "started",
  "message": "清理任務已啟動"
}
```

### GET /admin/access-keys

列出所有存取金鑰（含明文金鑰、狀態、用量與權限範圍）。

**請求：**
```bash
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-your-api-key"
```

**回應：**
```json
{
  "keys": [
    {
      "id": 1,
      "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "張三",
      "display_name": "張三",
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

`state` 取值：`valid`（有效）／`disabled`（已停用）／`pending`（未啟動，設定了 `duration_days` 但還沒被用過）／`expired`（已到期）／`quota_exceeded`（已超額）。判定按 `disabled` → `expired` → `quota_exceeded` → `pending` → `valid` 的優先級短路。

### GET /admin/access-keys/options

面板簽發表單的候選項：帳號池裡的帳號 + 對外可見的模型名（口徑與 `GET /v1/models` 一致）。

**請求：**
```bash
curl http://localhost:5918/admin/access-keys/options \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/access-keys

簽發存取金鑰。

**參數：**

| 欄位 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `name` | string | ❌ | 標籤；`count > 1` 時自動編號為 `name-1`、`name-2`…… |
| `count` | integer | ❌ | 一次簽發幾把，預設 1，**上限 50** |
| `expires_at` | string | ❌ | 絕對到期時間（ISO8601），與 `duration_days` 互斥 |
| `duration_days` | number | ❌ | 有效天數，**惰性啟動**：持有人首次使用才開始計時（上限 36500） |
| `request_limit` | integer | ❌ | 請求數上限，留空＝不限 |
| `bound_account_ids` | string[] | ❌ | 綁定帳號，留空＝不限制 |
| `allowed_models` | string[] | ❌ | 允許模型，留空＝不限制 |
| `enabled` | boolean | ❌ | 是否立即可用，預設 `true` |

**請求：**
```bash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "name": "張三",
    "duration_days": 7,
    "request_limit": 500,
    "allowed_models": ["gemini-flash"]
  }'
```

回應裡 `keys` 是本次簽發的全部金鑰，`key` 是其中第一把（方便單把簽發時直接取用）。

> `count` 傳 0 或大於 50 回傳 400；`expires_at` 與 `duration_days` 同時給出回傳 400；寫入磁碟失敗回傳 500（絕不會在沒存下來的情況下回 200，否則發出去的金鑰重啟後就失效了）。

### PATCH /admin/access-keys/{id}

修改金鑰設定。

**請求：**
```bash
# 停用
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"enabled": false}'

# 清空請求數上限與模型限制
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"clear": ["request_limit", "allowed_models"]}'
```

> **JSON 裡傳 `null` 表示「不改這個欄位」**，不是「清空」。要真的清空 `expires_at` / `duration_days` / `request_limit` / `bound_account_ids` / `allowed_models`，必須把欄位名放進 `clear` 陣列。`clear` 裡出現其它欄位名回傳 400。

### DELETE /admin/access-keys/{id}

撤銷金鑰，使用它的用戶端立即斷線。

**請求：**
```bash
curl -X DELETE http://localhost:5918/admin/access-keys/1 \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/access-keys/{id}/reset-usage

把 `request_count` 清零，已超額的金鑰可繼續使用。

**請求：**
```bash
curl -X POST http://localhost:5918/admin/access-keys/1/reset-usage \
  -H "Authorization: Bearer sk-your-api-key"
```

> **計數口徑**：每個業務請求在認證入口原子 +1，單調不減、不退還（上游報錯也算）。**`GET /v1/models` 同樣計數** —— 有些用戶端每輪對話前都會列一次模型，等於一輪消耗 2 次，設定 `request_limit` 時要留餘量。

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

## 超時

非流式（`stream: false`）請求的生成超時**按模型族分層**，可用 `GENERATE_TIMEOUTS` 覆寫：

| 模型族 | 預設超時 |
|------|------|
| flash-lite | 60 秒 |
| flash | 120 秒 |
| flash-thinking | 120 秒 |
| pro | 300 秒 |
| 認不出的族 | 60 秒 |

疑似生圖的請求與 `GENERATE_TIMEOUT_IMAGE`（預設 180 秒）**取大**。超時不再重試三遍 —— 失敗就是失敗。

> [!IMPORTANT]
> 非流式路徑在生成回傳之前**連線上是零位元組輸出**，所以這是**首位元組**超時而不是閒置超時。
> **pro 非流式最長要乾等 300 秒，會超過常見前置代理的首位元組上限**（EdgeOne 免費版 15 秒，不少反向代理預設 60 秒），這時用戶端拿到的是代理的 504 而不是本服務的錯誤內文。
> 有前置代理的部署建議對這類請求直接用 `stream: true`；流式路徑受自己的包線約束（單 chunk 120 秒／整條 180 秒），不受上表影響。

## 最佳實踐

1. **使用 conversation_id 維持上下文**：對於需要多輪對話的場景，使用相同的 conversation_id
2. **實現重試邏輯**：對於 5xx 錯誤實現指數退避重試
3. **監控使用統計**：定期檢查 `/admin/usage-stats/summary` 了解服務狀態
4. **定期更新 Cookie**：監控帳號健康狀態，及時更新過期 Cookie
5. **使用流式輸出**：對於長回應，使用 `stream: true` 改善使用者體驗
