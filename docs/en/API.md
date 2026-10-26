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

### Two kinds of keys

| Kind | Source | Can reach | Counted |
|------|------|--------|------|
| `API_KEY` (`.env`) | Auto-generated on first start, or set by you | Business API + `/admin/*` (when no separate `ADMIN_API_KEY` is set) | No |
| Access key | Issued by the administrator on the panel's "Access Keys" page or via `POST /admin/access-keys` | **Business API only** — never `/admin/*` | +1 per request |

Access keys are an **additional** layer: `API_KEY` always keeps full privileges, and with no access key issued the authentication behavior is identical to previous versions. Each access key can carry its own expiry, request limit, bound accounts and allowed models — see `POST /admin/access-keys`.

When an access key is rejected (disabled / expired / limit reached) the response is 401, and `message` in the body states the reason.

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

## 🧠 Models & Thinking Levels

| Public model name | Maps automatically to the web model (as currently measured) | Notes |
|------|------|------|
| `gemini-pro` | 3.1 Pro | Highest quality, slower |
| `gemini-flash` | 3.8 Flash | Fast; recommended default |
| `gemini-flash-lite` | 3.5 Flash-Lite | Lightest and fastest; fallback when Pro/Flash are rate-limited |
| `gemini-argon` | 4 Argon | For complex tasks; **listed only when an account actually has Argon** |

- **The mapping is automatic**: each account's heartbeat reports the web models it can really use right now. The public names never change; internally they follow whatever generation the web client currently serves (no client change needed when Google ships a new one).
- **`gemini-flash-thinking` is retired**: it was only a fake "flash + thinking mode" model, and thinking is now a level every model has (see below). For backward compatibility `gemini-flash-thinking`, `gemini-2.5-flash-thinking`, `gemini-2.0-flash-thinking` and the internal names `gemini-3-flash-thinking*` **still work** (hidden aliases of `gemini-flash`); they just no longer appear in any model list. To get thinking content back, pass a level parameter instead. Exception: an access key whose allowed models include `gemini-flash-thinking` still sees it in its model lists (so an old key restricted to it does not get an empty list); tick `gemini-flash` for new keys. ⚠️ Behaviour change: an old client calling `gemini-flash-thinking` without a level got the thinking content back in v1.6.42; it no longer does (unrequested thinking is never returned).
- **Three thinking levels**: `low` / `medium` / `high`, matching the web client's low / medium / high (measured: `high` thinks deepest and longest; `low` and `medium` could not be told apart in our samples).
- **Default level `low`**: when the client **does not specify a level** (it passed no thinking parameter at all, or asked for thinking without saying how much), the "default thinking level" applies (env var `DEFAULT_THINKING_LEVEL`, or the panel's Settings → Thinking, effective on save without a restart). Factory default `low`.
  - ⚠️ **Speed cost**: measured, the default `low` adds **about 5 s per request on average** compared with no thinking (simple flash prompts: 6.5 / 8.8 s → 8.6 / 16.6 s). If speed matters most, set the default to **`off`** (no thinking, fastest; the upstream request is identical to what older versions sent without the parameter). Watch non-streaming requests behind a proxy with a first-byte timeout (e.g. EdgeOne free tier, 15 s).Streaming pays too: for a request that does not mention thinking, the thinking turned on by the default is not returned, so **the answer only starts once thinking is done** (keep-alive frames are sent meanwhile, so proxies do not drop the connection); on a reasoning-heavy prompt, `gemini-pro` at `low` measured 36–47 s in total. If time-to-first-token matters, use `off`. ⚠️ `off` (and the default level itself) covers requests that **do not specify a level**: those that send no thinking parameter, and those that ask for thinking without saying how much (Claude Code's default requests are of this kind, so Claude Code follows the default level too). When the client **explicitly specifies a level** (Codex / Cursor picking low/medium/high, Anthropic sending `budget_tokens`, Claude Code's `/effort max`, and so on), the default level does not apply; to stop all thinking (truly fastest), turn off the master switch below (`EXTENDED_THINKING_ENABLED=false`).
  - When the client **does not mention thinking at all**, the thinking turned on for it by the default level is **used for generation only and never returned**: no extra `reasoning_content` / `thinking` block / thought part; the response is field-for-field identical to a no-thinking response, so strict clients do not break. Thinking content is returned only when the client **asked for thinking** (whether or not it specified a level); native Gemini still looks only at `includeThoughts`. When the default level is `off`, a request that asked for thinking without a level does not think either, so there is nothing to return.
- **Claude Code** (current versions): every request carries `adaptive` + `effort: high` (high is Claude Code's factory setting, sent on every request unless you change it), so it follows the default level here (factory `low`, speed first) out of the box; to make a session think deeper, run `/effort max` (or `xhigh`) in Claude Code → high; `/effort low` / `medium` are honoured as well.
- **Master switch** `EXTENDED_THINKING_ENABLED=false`: never think, even when a client explicitly asks. This is the **truly fastest** mode. It is always shown in the panel under Settings → Thinking → "Allow thinking (master switch)" and takes effect as soon as you save. Division of labour with the default thinking level: the default covers requests that do not specify a level (including Claude Code's default requests), the master switch also covers those that explicitly specify one.
- The panel's Model Test page replaces the old "Thinking" checkbox with a **level selector** (Low / Medium / High, default Low). The chosen level is sent as `reasoning_effort` and the reasoning is shown above the answer. There is also a "Default level (no parameter)" option: it sends no `reasoning_effort`, taking the same path as an ordinary client, so you can measure the real speed of the default thinking level in Settings (including `off`); the reasoning is not returned, as required.

Level parameters per protocol (**no level specified → default level**; a request that does not mention thinking at all gets no thinking back):

| Protocol | Parameter | Value → level |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`; `minimal` → low, `xhigh` → high; `none` → no thinking; unrecognized values → follow the default level (no error) |
| OpenAI `/v1/responses` | `reasoning.effort` (or top-level `reasoning_effort`) | Same as above |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`: `N<2048` → low, `2048–4095` → medium, `≥4096` → high; `{"type":"adaptive"}` or an invalid budget → look at `output_config.effort`: `low` / `medium` are used as is, `xhigh` / `max` → high, `high` (Claude Code's factory setting, treated as no explicit choice) or absent → follow the default level; `{"type":"disabled"}` → no thinking; an unrecognized `type` counts as not passed |
| Gemini native `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`: `LOW` / `MEDIUM` / `HIGH` (`MINIMAL` → low, unspecified → follow the default level); `thinkingBudget`: `0` → no thinking, `-1` (automatic) → follow the default level, `>0` tiered at 2048 / 4096; when both are given `thinkingLevel` wins; `includeThoughts: true` alone → follow the default level; thinking is returned (as a part with `"thought": true`) only with `includeThoughts: true` |

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
      "id": "gemini-flash-lite",
      "object": "model",
      "created": 1715970000,
      "owned_by": "google"
    },
    {
      "id": "gemini-argon",
      "object": "model",
      "created": 1715970000,
      "owned_by": "google"
    }
  ]
}
```

> 💡 **Model Selection Guide**: The four models offer different speed/quality tradeoffs.
> - `gemini-flash`: Fastest (response ~4-5 seconds), ideal for **agent / high-frequency / high-concurrency** scenarios, recommended as default.
> - `gemini-argon`: 4 Argon, for complex tasks; listed only when an account actually has Argon.
> - `gemini-flash-lite`: Lightest & fastest tier (3.5 Flash-Lite), a usable fallback when Pro/Flash hit rate limits.
> - `gemini-pro`: Highest quality but slower (response ~9-17 seconds, longer with extended context), suitable for quality-critical scenarios where latency is not a concern.
>
> Agent clients (which issue many concurrent requests) should prioritize `gemini-flash`. This service's streaming interface is true incremental streaming, pushing tokens as soon as the first character is generated.

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
| `conversation_id` | string | No | Multi-turn continuation (rules in "Multi-turn continuation" below) |

**Multi-turn continuation (`conversation_id`):** later turns with the same `conversation_id` continue the same upstream Gemini conversation: only the newest user message is sent, together with the continuation metadata recorded on the previous turn (`[cid, rid, rcid]`). A Gemini web conversation belongs to one account, so later turns are **pinned to the account that served the previous turn**. Streaming requests continue too, but a streaming response does not carry a `conversation_id`, so the client has to send its own (a non-streaming request without one gets a server-generated id back in the response's `conversation_id` field). In any of the cases below the gateway **resends the full history as a new conversation** instead (and records the new conversation and account on success, so the next turn resumes normally) — it never sends just the last message and silently drops the context:

- that account is unavailable: expired, removed, outside the access key's bound accounts, or (with more than one account in the pool) at capacity;
- the recorded metadata is unusable (including conversations stored before the upgrade, which have no account recorded: their first turn resends the full history, then continuation resumes);
- the previous turn was answered by the third-party fallback, or the upstream returned no continuation point for it;
- the new turn is more than a single user message: it carries tool results (`role: "tool"`, or `tool_result` blocks in a user message), or several messages arrived after the previous answer;
- a Gem model is used and the Gem's bound account differs from the conversation's account (the Gem wins).

When Google has really expired the conversation and the continuation request fails, the gateway still retries once with the full history (except on timeouts, see [Timeouts](#timeouts)). The same happens when the pinned account turns out to be unavailable only at send time (for example it has just filled up); the turn keeps its thinking level.

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

### POST /openai/v1/responses

OpenAI Responses API. Added for clients that require the newer Responses protocol instead of Chat Completions (e.g. **Codex CLI**, which dropped Chat Completions support in Feb 2026 — pointing Codex CLI at gemini2api needs this endpoint). Supports text, streaming, and function/tool calling, for both Gemini models and third-party models configured in API Management.

**Request:**
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "What is 2+2?",
    "stream": false
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Model ID (e.g., `gemini-flash`), or a third-party model configured in API Management |
| `input` | string or array | Yes | A plain string (shorthand for a single user message), or an array of input items (see below) |
| `instructions` | string | No | System/developer preamble prepended to the conversation |
| `stream` | boolean | No | Enable streaming (default: false) |
| `tools` | array | No | Function definitions for tool calling, **flat shape**: `{"type":"function","name","description","parameters"}` (note: different from Chat Completions' nested `{"type":"function","function":{...}}` shape) |
| `tool_choice` | string or object | No | `auto`, `none`, `required`, or `{"type":"function","name":"..."}` to force a specific tool |
| `temperature` | number | No | Randomness (forwarded to third-party models; not honored on the Gemini path) |
| `max_output_tokens` | number | No | Max response length (forwarded to third-party models; not honored on the Gemini path) |

**`input` array item types:**
- `{"type":"message","role":"user"|"assistant"|"system","content":[...]}` — content parts: `{"type":"input_text","text":...}`, `{"type":"input_image","image_url":"..."}`, `{"type":"output_text","text":...}`
- `{"type":"function_call","call_id","name","arguments"}` — a prior assistant tool-call turn (for multi-turn history you resend yourself)
- `{"type":"function_call_output","call_id","output"}` (or `"tool_result"`) — a tool's result you're sending back
- When the requested model is a third-party model (configured under API management), `function_call` / `function_call_output` items are forwarded in native OpenAI form (`assistant.tool_calls` plus `tool` messages carrying `tool_call_id`; consecutive calls share one assistant message). Only `function` tools are forwarded; built-in tools such as `web_search` are skipped. Tool calls returned by the third party, streaming included, become `function_call` output items (since v1.6.48).

**Not supported (explicit, not silent):** `previous_response_id` — this server does not keep server-side conversation state. Sending it returns a 400 `invalid_request_error` rather than silently ignoring it. Resend the full conversation in `input` on every request (this is what Codex CLI already does).

**Response (Non-Streaming):**
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
        {"type": "output_text", "text": "2 + 2 = 4", "annotations": []}
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

**Response (Streaming):** a spec-correct sequence of named SSE events, each carrying a monotonically increasing `sequence_number`. There is **no** `data: [DONE]` sentinel (that's a Chat Completions convention) — completion is signaled by `response.completed` (or `response.failed`):

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
data: {"type":"response.output_text.delta","sequence_number":4,"delta":"2"}

event: response.output_text.done
data: {"type":"response.output_text.done","sequence_number":5,"text":"2 + 2 = 4"}

event: response.content_part.done
data: {"type":"response.content_part.done","sequence_number":6,...}

event: response.output_item.done
data: {"type":"response.output_item.done","sequence_number":7,...}

event: response.completed
data: {"type":"response.completed","sequence_number":8,"response":{...}}
```

For a tool call, `response.output_item.added` (type `function_call`) is followed by `response.function_call_arguments.delta` / `response.function_call_arguments.done` / `response.output_item.done` instead of the text events above.

**Function Calling Example:**
```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "What is the weather in Paris?",
    "tools": [
      {
        "type": "function",
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
    ]
  }'
```
Response `output` will contain a `function_call` item:
```json
{"id": "fc_xxx", "type": "function_call", "status": "completed", "call_id": "call_xxx", "name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}
```

### POST /openai/v1/images/generations

Generate images with AI. Triggered by a text `prompt`, returns the image in `b64_json` format. Also available at the bare path `POST /v1/images/generations`.

**Request:**
```bash
curl -X POST http://localhost:5918/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Model ID (e.g., `gemini-pro`) |
| `prompt` | string | Yes | Text description of the image to generate |
| `n` | number | No | Number of images to generate (default: 1) |

**Response:**
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

> [!NOTE]
> The image is returned as a Base64-encoded string in `b64_json`. In addition, when the three chat APIs detect a generated image in a response, the image is automatically embedded into the reply (markdown for OpenAI, image block for Claude, `inlineData` for Gemini).

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
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 15
  }
}
```

#### Extended thinking (`thinking`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `thinking` | object | No | Sets the thinking level. **When omitted, the upstream thinks at the default thinking level (factory `low`) but the response never contains a `thinking` block — it stays byte-for-byte identical to previous versions** |
| `output_config` | object | No | Only its `effort` is read, together with `thinking`, to set the level (see the `adaptive` line below). `output_config.effort` alone, without `thinking`, has no effect (the request counts as passing no thinking parameter); a malformed value (not an object, or an unrecognized `effort`) counts as not given and never causes an error |

- `{"type":"enabled","budget_tokens":N}` — on. `N` maps to low / medium / high at `<2048` / `2048–4095` / `>=4096`. Those cut points are the inverse of the `{low:1024, medium:2048, high:4096}` table this service uses when forwarding to a third-party Anthropic endpoint, so a round trip through this service keeps the same level. A valid `budget_tokens` decides the level and takes precedence over `output_config.effort`.
- `{"type":"adaptive"}` — on; the level comes from `output_config.effort`: `low` / `medium` are used as is, `xhigh` / `max` → high, `high` (Claude Code's factory setting, treated as no explicit choice) or absent → follow the default thinking level; a missing/invalid `budget_tokens` does the same.
- `{"type":"disabled"}` / `{"type":"between_tools"}` — no thinking (an explicit off; the default level does not apply, and `output_config.effort` is ignored whatever it says).

Thinking is returned as an Anthropic `thinking` content block, placed **before** the `text` / `tool_use` blocks; when streaming, as `content_block_start(thinking)` → `thinking_delta` → `content_block_stop`.

⚠️ Two things to know:
- **No `signature`.** The real Anthropic API always signs `thinking` blocks; this service cannot produce a valid signature, so the field is omitted (an empty or invented signature would be worse — a client replaying it to the real API gets a 400).
- The levels match the web client's low / medium / high: measured on a real account, high thinks deepest; low and medium could not be told apart.
- Thinking tokens are counted into `usage.output_tokens` (matching the official billing convention), but that number is still an estimate — see the access-key usage section.
- With `EXTENDED_THINKING_ENABLED=false`, the thinking path is skipped even when `thinking` is sent.
- **Thinking deltas that arrive after the body started are dropped** (streaming). The Anthropic block order forbids opening or extending a `thinking` block after a `text` block, so when the upstream keeps growing its thinking after the body began, that remainder has to be dropped (a WARNING records how many characters were lost). If you need the complete chain, use `reasoning_content` on the OpenAI protocol, which has no block-order constraint. The normal order (thinking first) is unaffected, and the body is always complete.
- A `thinking` value that is not an object (string / number / array) is treated as **not sent**: the request still returns 200 rather than a 422.

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
  "total": 2,
  "active": 1,
  "strategy": "round-robin",
  "max_concurrent_per_account": 8,
  "accounts": [
    {
      "id": "account-0",
      "label": "Primary",
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
      "label": "Backup",
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

| Field | Description |
|------|------|
| `active` | Number of accounts whose exported `status` is `active` |
| `accounts[].status` | `active`: usable. `expired`: the session is dead and needs fresh cookies — 3 consecutive failures, an upstream 401/403, or **the Google session being redirected to the login page** (then `is_healthy` is `false`, and an empty `last_error` is filled with `Google session expired (login redirect)`); it goes back to `active` by itself once fresh cookies are in. `disabled`: disabled |
| `accounts[].is_healthy` | Whether the client session is usable right now. `active` with `false` means temporarily unavailable (e.g. a network glitch), not yet judged as a dead session |
| `accounts[].last_error` / `last_error_at` | Redacted summary and time of the most recent failure |
| `accounts[].keepalive_mode` | Who keeps the cookies alive: `server` (default; the server rotates them on a timer) / `browser` (pushed by the browser keep-alive extension; the server does not rotate them — see `PUT /admin/accounts/{id}/cookies`) |
| `model_breakers` | State of the model outage breaker per family (`GET /admin/accounts` carries it too); only families that ever had state are listed; see [Google-side outages](#google-side-outages) |
| `model_breakers.*.state` | `closed`: Google is called as usual; `open`: the family is failing on Google's side and `/v1/chat/completions` requests with a fallback go straight to the fallback; `half_open`: the open period is over and the next request probes Google |
| `model_breakers.*.enabled` | `MODEL_BREAKER_ENABLED`; with `false` the state is still recorded but Google is never bypassed |
| `model_breakers.*.consecutive_failures` | Number of different requests that failed in a suspected-outage way in the current window |
| `model_breakers.*.open_remaining_seconds` / `retry_at` | While `open`: seconds left / the absolute time (UTC) it ends; `0` / `null` otherwise |
| `model_breakers.*.cooldown_seconds` | Length of the current (or next) open period in seconds (doubles when a probe fails, capped at `MODEL_BREAKER_MAX_COOLDOWN`) |
| `model_breakers.*.probe_in_flight` | While `half_open`: whether a request is already probing Google |
| `model_breakers.*.last_reason` / `last_failure_at` | The last failure counted by the breaker (a safe summary: exception type + status code) and when it happened (UTC) |

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

> The response is the same as `GET /admin/status` (it carries `model_breakers` too; the breaker notice at the top of the panel's Accounts page reads this endpoint).

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

A newly added account also gets its `keepalive_mode` recorded from the request source (same rules as `PUT /admin/accounts/{id}/cookies`; accounts added through the panel's "Add Account" or by a script are `server`). Deleting an account does not clear the record for its PSID, but adding it back with the same cookies records it again from the new request.

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

**Keep-alive mode:** after a successful reload, the account's keep-alive mode is recorded from where the request came from (under the new PSID, in `data/keepalive-modes.json`, which stores only a hash of the PSID):

| Request | `keepalive_mode` | Effect |
|------|------|------|
| Carries the `X-Gemini2API-Keepalive` header (sent by the browser keep-alive extension from v1.3.0, value like `gemini2api-plugin/1.3.0`; the bundled Playwright refresher sidecar sends `gemini2api-refresher`) | `browser` | The server stops calling RotateCookies for this account; the browser rotates and the extension pushes |
| `Origin` starts with `chrome-extension://` (older extension versions that do not send the header) | `browser` | Same as above |
| Anything else (the panel's "Update Cookie", scripts / curl) | `server` | Handed back to the server's scheduled rotation |

On success the account is back to `active` with its consecutive failures reset right away — no follow-up `/check` needed. A failed reload (503) changes nothing: the cookies are not swapped in, and neither the keep-alive mode nor the account state changes. When the request comes from the browser keep-alive extension, the reload itself does not call RotateCookies either (the fallback rotation after a failed token fetch is skipped too, so the server never replaces the session the browser is using).

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

On success the keep-alive mode is recorded from the request source and the account is back to `active` right away, with the same rules as `PUT /admin/accounts/{id}/cookies`.

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

### PATCH /admin/api-keys/{id}/status

Toggle a Key's status (enable/disable).

**Request:**
```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-xxx/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"status": "active"}'
```

### PATCH /admin/api-keys/{id}/label

Edit a Key's label.

**Request:**
```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-xxx/label \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"label": "My OpenAI Key"}'
```

### POST /admin/api-keys/import

Bulk-import API Keys.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/api-keys/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "keys": [
      {"provider": "openai", "key": "sk-...", "model": "gpt-4o"}
    ]
  }'
```

### GET /admin/api-keys/export

Export all Keys. Masked by default; append `?reveal=true` to return plaintext keys.

**Request:**
```bash
curl "http://localhost:5918/admin/api-keys/export?reveal=true" \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/api-keys/batch-delete

Bulk-delete API Keys.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/api-keys/batch-delete \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"ids": ["key-1", "key-2"]}'
```

### POST /admin/api-keys/models

Probe the available model list for a given Provider / base_url (used to populate the model dropdown when adding a Key).

**Request:**
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

### GET /admin/verify

Verify API Key validity (used for login).

**Request:**
```bash
curl http://localhost:5918/admin/verify \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "valid": true
}
```

### POST /admin/restart

Restart the service (one-click restart from the top-right of the panel; the panel auto-polls until recovery).

**Request:**
```bash
curl -X POST http://localhost:5918/admin/restart \
  -H "Authorization: Bearer sk-your-api-key"
```

### GET /admin/check-update

Check whether a new version is available.

**Request:**
```bash
curl http://localhost:5918/admin/check-update \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/update

Trigger an update to the latest version.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/update \
  -H "Authorization: Bearer sk-your-api-key"
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

### GET /admin/web-chats

List the account's Gemini web sessions (read-only). Every API conversation creates a record on gemini.google.com. This endpoint returns session lists per account, including conversation ID, title, timestamp, and pinned status.

**Request:**
```bash
curl http://localhost:5918/admin/web-chats \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "accounts": [
    {
      "account_id": "account-0",
      "sessions": [
        {
          "cid": "c_abc123xyz",
          "title": "Conversation about Python",
          "timestamp": "2026-06-06T10:30:00Z",
          "pinned": false
        },
        {
          "cid": "c_def456uvw",
          "title": "Important research notes",
          "timestamp": "2026-06-05T14:20:00Z",
          "pinned": true
        }
      ]
    }
  ]
}
```

### POST /admin/cleanup-web-chats

Manually trigger cleanup of web sessions older than the specified retention window. This endpoint runs the cleanup task asynchronously in the background and returns immediately.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/cleanup-web-chats \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "keep_hours": 24,
    "skip_pinned": true
  }'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `keep_hours` | number | No | Retention window in hours (default: 24). Sessions older than this are deleted. |
| `skip_pinned` | boolean | No | Whether to skip pinned sessions (default: true). |

**Response:**
```json
{
  "status": "started",
  "message": "Cleanup task started in background"
}
```

> [!NOTE]
> The cleanup task runs asynchronously and loops until all old sessions across all accounts are deleted. Check logs for completion status and deleted session counts.

### GET /admin/access-keys

List all access keys (including the plaintext key, state, usage and scope).

**Request:**
```bash
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-your-api-key"
```

**Response:**
```json
{
  "keys": [
    {
      "id": 1,
      "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "Alice",
      "display_name": "Alice",
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

`state` is one of `valid`, `disabled`, `pending` (`duration_days` is set but the key has never been used), `expired`, `quota_exceeded`. It is resolved by short-circuiting in the order `disabled` → `expired` → `quota_exceeded` → `pending` → `valid`.

### GET /admin/access-keys/options

Choices for the panel's issue form: accounts in the pool plus the externally visible model names (same set as `GET /v1/models`).

**Request:**
```bash
curl http://localhost:5918/admin/access-keys/options \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/access-keys

Issue access keys.

**Parameters:**

| Field | Type | Required | Description |
|------|------|------|------|
| `name` | string | ❌ | Label; auto-numbered `name-1`, `name-2`, … when `count > 1` |
| `count` | integer | ❌ | How many to issue, default 1, **max 50** |
| `expires_at` | string | ❌ | Absolute expiry (ISO8601); mutually exclusive with `duration_days` |
| `duration_days` | number | ❌ | Valid days with **lazy activation**: the clock starts on the holder's first use (max 36500) |
| `request_limit` | integer | ❌ | Request cap; empty = unlimited |
| `bound_account_ids` | string[] | ❌ | Bound accounts; empty = unrestricted |
| `allowed_models` | string[] | ❌ | Allowed models; empty = unrestricted |
| `enabled` | boolean | ❌ | Usable immediately, default `true` |

**Request:**
```bash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "name": "Alice",
    "duration_days": 7,
    "request_limit": 500,
    "allowed_models": ["gemini-flash"]
  }'
```

In the response, `keys` holds every key issued by this call and `key` is the first of them (convenient when issuing a single key).

> A `count` of 0 or above 50 returns 400; giving both `expires_at` and `duration_days` returns 400; a failed write to disk returns 500 (the endpoint never returns 200 for a key it did not persist — otherwise a key you already handed out would stop working after a restart).

### PATCH /admin/access-keys/{id}

Change a key's configuration.

**Request:**
```bash
# Disable
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"enabled": false}'

# Clear the request cap and the model restriction
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"clear": ["request_limit", "allowed_models"]}'
```

> **A JSON `null` means "leave this field unchanged"**, not "clear it". To actually clear `expires_at` / `duration_days` / `request_limit` / `bound_account_ids` / `allowed_models`, put the field name in the `clear` array. Any other field name in `clear` returns 400.

### DELETE /admin/access-keys/{id}

Revoke a key; clients using it are cut off immediately.

**Request:**
```bash
curl -X DELETE http://localhost:5918/admin/access-keys/1 \
  -H "Authorization: Bearer sk-your-api-key"
```

### POST /admin/access-keys/{id}/reset-usage

Zero `request_count` so a key that hit its limit can be used again.

**Request:**
```bash
curl -X POST http://localhost:5918/admin/access-keys/1/reset-usage \
  -H "Authorization: Bearer sk-your-api-key"
```

> **How counting works:** every business request increments the counter atomically at the auth entry point; it is monotonic and never refunded (an upstream error still counts). **`GET /v1/models` counts too** — some clients list the models before every turn, which means two counts per round, so leave headroom when setting `request_limit`.

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
| 502 | Bad Gateway | Upstream error (`api_error`), including Google sending its fixed failure sentence instead of an answer; see [Google-side outages](#google-side-outages) |
| 503 | Service Unavailable | No healthy accounts available |
| 504 | Gateway Timeout | Generation timed out (`timeout_error`); see [Timeouts](#timeouts) |

### Common Error Types

| Type | Cause | Solution |
|------|-------|----------|
| `auth_error` | Invalid API Key | Verify API Key in Authorization header |
| `model_not_found` | Model doesn't exist | Check available models with `/openai/v1/models` |
| `no_available_accounts` | All accounts unhealthy | Refresh cookies, check account status |
| `rate_limit_exceeded` | Too many requests | Wait before retrying |
| `invalid_request` | Malformed request | Check request format and parameters |
| `timeout_error` | Generation timed out (Google stalled; cut at the timeout budget) | Retry later or use streaming; with `FALLBACK_ENABLED` the chat endpoint tries the third-party fallback first |

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

## Timeouts

The generation timeout is **tiered per model family** (the same budget for non-streaming and streaming requests) and can be overridden with `GENERATE_TIMEOUTS`:

| Model family | Default timeout |
|------|------|
| flash-lite | 60 s |
| flash | 120 s |
| pro | 300 s |
| argon | 300 s |
| Unrecognized family | 60 s |

Requests that look like image generation take the **larger** of the tier above and `GENERATE_TIMEOUT_IMAGE` (default 180 s). A timeout is no longer retried three times — a failure is a failure.

**Streaming requests** are bound by the same budget: the first progress (new body text, thinking, generated images or Canvas) must arrive within the budget, and waiting for the response headers counts too; after that, the gap between two progresses may not exceed the budget either. The empty heartbeat frame `[{"37":[0]}]` Google sends every 60 seconds while a request is queued **does not count as progress**, and neither do repeated frames or frames that only carry conversation metadata. Nothing is cut earlier than the family budget: on the same account, pro answering a hard question without thinking legitimately sends its response headers after 60 seconds and its answer after 89. Time spent uploading attachments does not count. When the budget runs out the service first aborts the transfer from Google, then sends the `timeout_error` event to the client.

A timeout returns **504** with error type `timeout_error`, in each protocol's own error body: OpenAI / Gemini native / Responses use `{"error": {..., "type": "timeout_error"}}`, Anthropic uses `{"type": "error", "error": {"type": "timeout_error", ...}}` (it used to be a plain-text `500 Internal Server Error` that SDKs could not parse and would not retry as a timeout). Streaming requests (including the buffered tool-calling streams) have already answered 200, so the timeout arrives as an in-protocol error event: the OpenAI error frame has `type` `timeout_error` and `code` `504`; the Anthropic `error` event and the Gemini native NDJSON error line have `type` `timeout_error`; in Responses, `response.failed` carries `error.code` `timeout_error`. The image endpoint `/v1/images/generations` also returns 504 with `timeout_error`; the deep-research endpoints (`/gemini/v1beta/deepresearch`, and non-streaming requests to `/gemini/v1beta/deepresearch/interact`) return 504 with a `{"detail": "..."}` body.

- With `FALLBACK_ENABLED` on, `/v1/chat/completions` tries the third-party fallback first, as long as no content has been sent to the client yet; the other three protocols have no third-party fallback and return the error above directly.
- A timeout is not retried without thinking and not retried with the full prompt: the turn's budget is already spent, and a retry would only make the client wait another full round.
- A timeout means Google stalled, not that the cookie died: it does not count toward the account's consecutive failures and never marks the account `expired` (it records one error and a short cooldown).
- A connect-phase timeout (one that comes back within seconds, without using up the generation budget) is still retried a few times on the same account first; once those retries run out it is handled as a timeout too: 504, not counted as a consecutive failure, no retry without thinking or with the full prompt.

> [!IMPORTANT]
> On the non-streaming path the connection emits **zero bytes** until generation returns, so this is a **time-to-first-byte** timeout, not an idle timeout.
> **A non-streaming pro request can sit silent for up to 300 seconds, which exceeds the first-byte limit of common front proxies** (15 seconds on the EdgeOne free tier, 60 seconds by default on many reverse proxies); the client then receives the proxy's 504 instead of this service's error body.
> This service's own timeout is also a 504, but it carries the JSON error body above (`timeout_error`), which tells it apart from a proxy's 504.
> Behind a front proxy, prefer `stream: true` for these requests (a stream sends its first frame at once and keep-alive frames while waiting); streaming requests are bound by the budget above too, see the rules above.

## Google-side outages

When a whole model family fails on Google's side (measured on 2026-10-26: two gemini-flash outages hitting all three accounts while flash-lite and pro on the same accounts kept working), it shows up in one of two ways: the request is stuck in Google's queue (response headers after 60 seconds, then an empty heartbeat frame every 60 seconds; handled by the [Timeouts](#timeouts) above), or Google answers within about a second with a fixed failure sentence.

**The generic failure sentence**: when the whole answer (with surrounding whitespace trimmed, runs of whitespace collapsed, case-insensitive) is exactly `I seem to be encountering an error. Can I try something else for you?` (or a sentence added via `GEMINI_FAILURE_REPLIES`), it is handled as an upstream failure: the next account is tried; if all fail, `/v1/chat/completions` tries the third-party fallback first, otherwise the answer is **502 `api_error`** (`{"error": {..., "type": "api_error"}}` for OpenAI / Gemini native / Responses, `{"type": "error", "error": {"type": "api_error", ...}}` for Anthropic; the image endpoint returns 502 too). Streaming requests get the same in-protocol error event as any other upstream error: the OpenAI error frame has `type` `api_error` and `code` `502`; the Anthropic `error` event and the Gemini native NDJSON error line have `type` `api_error`; in Responses, `response.failed` carries `error.code` `internal_error`; the deep-research endpoints keep answering 500. An answer that merely contains or starts with the sentence, or comes with generated images, is not affected, and neither is an answer to a user who asked for that very sentence. The sentence is never saved into the conversation record; the account only gets a short cooldown and the failure does not count toward its consecutive failures. Streaming requests hold back an opening that could still grow into the sentence (only the first few words of an answer) and release it as soon as it diverges. Since v1.6.47, Gemini's canned "language model" refusals (e.g. `I'm just a language model, so I can't help you with that.` or the Chinese `我只是一个语言模型，无法提供这方面的帮助。`) are recognised built-in and handled the same way (another account / fallback / 502), but they do not count toward the model circuit breaker, because one particular question can trigger such a refusal every time. Curly quotes are compared as straight quotes.

**Model outage breaker** (applies to `/v1/chat/completions` only): when `MODEL_BREAKER_THRESHOLD` (default 2) **different requests** fail in a suspected-outage way on the same model family within the window (`MODEL_BREAKER_WINDOW`, default 300 s) — the failure sentence, a non-streaming generation timeout with almost no data received (< 1 KB), a streaming timeout without any progress — the breaker opens for `MODEL_BREAKER_COOLDOWN` (default 60) seconds. Meanwhile `/v1/chat/completions` requests with `FALLBACK_ENABLED` on and a fallback candidate available **are answered by the third-party fallback directly** instead of first waiting out a whole budget (streams still get their first frame at once and keep-alive frames while the fallback works); if the fallback cannot answer, Google is called as usual and the fallback is not retried afterwards. When the period ends, one real request probes Google: a success closes the breaker at once, a failure doubles the period (capped at `MODEL_BREAKER_MAX_COOLDOWN`). Requests without a fallback, the other protocols, deep research and image generation always call Google as usual, and their results still update the breaker; only the failing family is affected. The state per family is in `model_breakers` of `GET /admin/status` (and `GET /admin/accounts`); it is cleared on restart.
