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

## 🧠 模型與思考檔位

| 對外模型名 | 自動對應到網頁上的模型（目前實測） | 說明 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 品質最高、較慢 |
| `gemini-flash` | 3.8 Flash | 快，建議作為預設 |
| `gemini-flash-lite` | 3.5 Flash-Lite | 最輕最快，Pro/Flash 被限額時的備援 |
| `gemini-argon` | 4 Argon | 面向複雜任務；**帳號真的有 Argon 時才會列出** |

- **對應是自動的**：每個帳號的心跳會回報它目前真實可用的網頁模型，對外名字固定不變、內部自動對上網頁目前的那一代（Google 換代時不用改客戶端）。
- **`gemini-flash-thinking` 已下線**：它只是「flash + 思考模式」的假模型，思考現在是每個模型都有的檔位（見下）。為相容舊客戶端，`gemini-flash-thinking`、`gemini-2.5-flash-thinking`、`gemini-2.0-flash-thinking` 以及內部名 `gemini-3-flash-thinking*` **仍然可以呼叫**（隱藏別名，等同 `gemini-flash`），只是不再出現在任何模型清單裡；想要思考內容請改傳檔位參數。 例外：存取金鑰的「允許模型」裡勾過 `gemini-flash-thinking` 的，這把金鑰取得的模型清單裡仍會列出它（免得只勾了它的舊金鑰拿到空清單），新簽發的金鑰請改勾 `gemini-flash`。⚠️ 行為變化：舊客戶端不傳檔位呼叫 `gemini-flash-thinking` 時，v1.6.42 會回傳思考內容，現在不再回傳（未請求的思考一律不回傳）。
- **思考三檔**：`low` / `medium` / `high`，對應網頁上的低 / 中 / 高三檔（實測 `high` 想得最深、也最慢；`low` 與 `medium` 的差別在實測裡分不太開）。
- **預設檔 `low`**：客戶端**沒指定檔位**時（沒傳思考參數的，和要了思考但沒說幾檔的），使用「預設思考檔位」（環境變數 `DEFAULT_THINKING_LEVEL`，或面板「設定 → 思考」，儲存即時生效、無需重啟），出廠 `low`。
  - ⚠️ **速度代價**：實測預設 `low` 比不思考**平均每個請求多約 5 秒**（flash 簡單題 6.5 / 8.8 秒 → 8.6 / 16.6 秒）。最重視速度就把預設檔設成 **`off`**（不思考、最快，與舊版不傳參數時送往上游的請求完全一樣）。前置代理有首位元組逾時的（如 EdgeOne 免費版 15 秒）尤其要留意非流式請求。串流請求也有代價：沒提思考的請求，依預設檔位開啟的思考不回傳，**正文要等思考完成才開始輸出**（期間只有保活幀，連線不會被代理切斷），pro 遇到需要推理的題目 `low` 檔實測總耗時 36～47 秒 —— 對首字延遲敏感就用 `off`。⚠️ `off`（以及預設檔本身）管的是**沒指定檔位**的請求：沒傳思考參數的，和要了思考但沒說幾檔的（Claude Code 出廠請求就是這種，所以 Claude Code 預設也跟隨預設檔）。客戶端**明確指定了檔位**的（Codex / Cursor 選了 low/medium/high、Anthropic 給了 `budget_tokens`、Claude Code `/effort max` 等）預設檔管不到；要所有請求都不思考（真正最快），請關閉下方的總開關 `EXTENDED_THINKING_ENABLED=false`。
  - 客戶端**完全沒提思考**時，依預設檔替它開的思考**只用於生成，絕不回傳**：回應裡不會多出 `reasoning_content` / `thinking` 區塊 / 思考 part，結構與不思考時逐欄位一致（嚴格校驗的客戶端不會因此報錯）。客戶端**要了思考**（不論有沒有給檔位）才回傳思考內容（Gemini 原生仍只看 `includeThoughts`）。預設檔是 `off` 時，「要了思考但沒給檔位」的請求也不思考，自然沒有思考可回傳。
- **Claude Code**（新版）：每個請求都帶 `adaptive` + `effort: high`（high 是 Claude Code 的出廠值，不換檔時每個請求都是它），所以預設跟隨這裡的預設檔（出廠 low，速度優先）；想讓某個會話想得更深，在 Claude Code 裡執行 `/effort max`（或 `xhigh`）→ high；`/effort low` / `medium` 也照檔。
- **總開關** `EXTENDED_THINKING_ENABLED=false`：一律不思考，連客戶端明確要求的思考也忽略，這才是**真正最快**的模式。面板「設定 → 思考 →「允許思考（總開關）」」裡一直顯示、儲存即時生效；與「預設思考檔位」的分工：預設檔位管沒指定檔位的請求（含 Claude Code 出廠請求），總開關連明確指定了檔位的也管。
- 面板「模型測試」頁改用**檔位選擇**（低 / 中 / 高，預設低）取代原本的「思考」勾選框，所選檔位以 `reasoning_effort` 送出，思考過程顯示在回答上方。 另有「依預設檔位（不傳參數）」一項：不帶 `reasoning_effort`，與一般客戶端走同一條路，可用來實測設定中「預設思考檔位」（含 `off`）的實際速度（思考內容依規定不回傳）。

各協議的檔位寫法（**沒指定檔位則使用預設檔**；完全沒提思考的請求，思考不回傳）：

| 協議 | 參數 | 取值 → 檔位 |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`；`minimal` → low，`xhigh` → high；`none` → 不思考；認不出的值 → 跟隨預設檔（不報錯） |
| OpenAI `/v1/responses` | `reasoning.effort`（或頂層 `reasoning_effort`） | 同上 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`：`N<2048` → low，`2048–4095` → medium，`≥4096` → high；`{"type":"adaptive"}` 或 budget 無效 → 看 `output_config.effort`：`low` / `medium` 照檔，`xhigh` / `max` → high，`high`（Claude Code 出廠值，視同沒專門選檔）或沒給 → 跟隨預設檔；`{"type":"disabled"}` → 不思考；認不出的 `type` 視同沒傳 |
| Gemini 原生 `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`：`LOW` / `MEDIUM` / `HIGH`（`MINIMAL` → low，未指定 → 跟隨預設檔）；`thinkingBudget`：`0` → 不思考，`-1`（自動）→ 跟隨預設檔，`>0` 按 2048 / 4096 切點分檔；兩者都給時以 `thinkingLevel` 為準；只給 `includeThoughts: true` → 跟隨預設檔；`includeThoughts: true` 才在回應裡回傳思考（`"thought": true` 的 part） |

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

> 💡 **模型選擇建議**：四個模型對應不同的速度/品質權衡。
> - `gemini-flash`：最快(回應約 4-5 秒),適合 **agent / 高頻 / 高並發**場景,推薦作為預設選擇。
> - `gemini-argon`：4 Argon，面向複雜任務；只有帳號真的有 Argon 時才會出現在清單裡。
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
| `thinking` | object | ❌ | 指定思考檔位。**不傳時上游依「預設思考檔位」（出廠 `low`）思考，但回應裡絕不出 `thinking` 區塊，回應結構與舊版逐字節一致** |
| `output_config` | object | ❌ | 只讀其中的 `effort`，配合 `thinking` 定檔位（用法見下方 `adaptive` 一行）。單獨給 `output_config.effort`、沒給 `thinking` 時不起作用（按沒傳思考參數處理）；形態不對（不是物件、`effort` 認不出）視同沒給，不報錯 |

- `{"type":"enabled","budget_tokens":N}`：開啟。`N` 按 `<2048` / `2048–4095` / `≥4096` 分成低／中／高三檔。`budget_tokens` 合法時以它為準，優先於 `output_config.effort`。
- `{"type":"adaptive"}`：開啟，檔位看 `output_config.effort`：`low` / `medium` 照檔，`xhigh` / `max` → high，`high`（Claude Code 出廠值，視同沒專門選檔）或沒給 → 跟隨預設思考檔位；`budget_tokens` 缺失/無效時同此。
- `{"type":"disabled"}` / `{"type":"between_tools"}`：不思考（明確關閉，不受預設檔影響；`output_config.effort` 給什麼都不管）。

思考內容以 Anthropic 規範的 `thinking` 內容區塊回傳，排在 `text` / `tool_use` 區塊**之前**；流式下是 `content_block_start(thinking)` → `thinking_delta` → `content_block_stop`。

⚠️ **不帶 `signature`**（本服務造不出合法簽名，發空串／自造串更糟：客戶端回傳給真 API 會 400）。檔位對應網頁的低 / 中 / 高三檔（真機實測 high 想得最深；low 與 medium 分不太開）。全域開關 `EXTENDED_THINKING_ENABLED=false` 時即使傳了也不走思考路徑。

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
  "total": 2,
  "active": 1,
  "strategy": "round-robin",
  "max_concurrent_per_account": 8,
  "accounts": [
    {
      "id": "account-0",
      "label": "主帳號",
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
      "label": "備用帳號",
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
  ]
}
```

| 欄位 | 說明 |
|------|------|
| `active` | 對外 `status` 為 `active` 的帳號數 |
| `accounts[].status` | `active`：可用；`expired`：工作階段已失效，需要換 cookie —— 包括連續失敗 3 次、上游回 401/403，以及**Google 工作階段被導回登入頁**（此時 `is_healthy` 為 `false`，`last_error` 為空時補上 `Google session expired (login redirect)`）；換上新 cookie 後自動回到 `active`。`disabled`：已停用 |
| `accounts[].is_healthy` | 用戶端工作階段目前是否可用。`active` 但為 `false` 表示暫時不可用（如網路抖動），尚未判定為工作階段失效 |
| `accounts[].last_error` / `last_error_at` | 最近一次失敗的去敏摘要與時間 |
| `accounts[].keepalive_mode` | cookie 由誰保活：`server`（預設，伺服器端定時輪換）/ `browser`（由瀏覽器保活擴充功能推送，伺服器端不輪換，見 `PUT /admin/accounts/{id}/cookies`） |

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

成功後同樣依請求來源記錄 `keepalive_mode`，該帳號立即恢復為 `active`（規則同 `PUT /admin/accounts/{id}/cookies`）。

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

**保活方式**：reload 成功後，依請求來源記下這個帳號由誰保活（記在新 PSID 名下，保存在 `data/keepalive-modes.json`，只存 PSID 的雜湊）：

| 請求來源 | `keepalive_mode` | 效果 |
|------|------|------|
| 帶請求標頭 `X-Gemini2API-Keepalive`（瀏覽器保活擴充功能 v1.3.0 起會帶，值形如 `gemini2api-plugin/1.3.0`） | `browser` | 伺服器端不再對該帳號呼叫 RotateCookies，由瀏覽器輪換、擴充功能推送 |
| `Origin` 以 `chrome-extension://` 開頭（相容不帶上述標頭的舊版擴充功能） | `browser` | 同上 |
| 其他（面板「更新 Cookie」、腳本 / curl） | `server` | 交回伺服器端定時輪換 |

成功後該帳號立即恢復為 `active`、連續失敗數歸零，不需要再呼叫 `/check`。reload 失敗（503）時既不改保活方式，也不改帳號狀態。

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
| pro | 300 秒 |
| argon | 300 秒 |
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
