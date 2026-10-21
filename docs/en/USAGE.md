# Usage Guide

This guide covers using gemini2api through the web panel and integrating it with third-party clients.

## Web Management Panel

Access the web panel at `http://localhost:5918` (or your server IP).

### Login

1. Open the web panel in your browser
2. Enter your API Key (from `.env` or logs)
3. Click **Login**

The API Key is displayed in startup logs and stored in `.env` as `API_KEY=sk-...`

### Dashboard

The dashboard provides a system overview:

- **Service Status**: Running time, version, and system information
- **Account Pool**: Number of active accounts and their health status
- **Available Models**: List of models you can use
- **System Info**: Python version, OS, memory usage, CPU usage, PID, run mode
- **Configuration**: Current rotation strategy and concurrent request limits
- **QR Codes**: Shareable codes (customizable via `api/` directory)

### Account Management

Manage your Google accounts:

1. Click **Account Management** in the sidebar
2. View all configured accounts with their status
3. **Add Account**: Click **Add Account**, paste PSID and PSIDTS, set a label
4. **Update Cookies**: Click **Update Cookies** for an account to refresh expired cookies
5. **Check Status**: Click **Check** to verify an account is healthy
6. **Remove Account**: Click **Delete** to remove an account

Changes take effect immediately without restarting.

### Playground

Test API requests directly in the browser:

1. Click **Playground** in the sidebar
2. Select a model from the dropdown
3. Enter your message in the chat interface
4. Click **Send** to get a response
5. View the full conversation history

The playground supports:
- Streaming responses (real-time text display)
- Multi-turn conversations
- Model switching mid-conversation

### Logs

View structured request logs:

1. Click **Logs** in the sidebar
2. Logs are displayed in a table with pagination (15 entries per page)
3. **Filter by Direction**: View requests, responses, or errors
4. **Search**: Filter logs by text content
5. **View Details**: Click a log entry to see full JSON details
6. **Clear Logs**: Delete all logs (cannot be undone)

Logs are persisted to disk and survive service restarts.

### Usage Statistics

Monitor API usage and performance:

1. Click **Usage Stats** in the sidebar
2. View summary metrics:
   - Total requests processed
   - Error rate percentage
   - Average response latency
   - Cookie refresh success rate
3. View historical trends with time-series data
4. Export data for analysis

### API Keys Management

Manage third-party API keys for model forwarding:

1. Click **API Keys** in the sidebar
2. **View Keys**: List all configured keys (passwords masked)
3. **Add Key**: Click **Add Key**, select provider, enter key and model name
4. **Enable/Disable**: Toggle keys on/off without deleting
5. **Delete Key**: Remove a key permanently
6. **Import/Export**: Bulk import or export keys as JSON

Supported providers:
- OpenAI (GPT-4, GPT-4o, etc.)
- Anthropic (Claude models)
- Google Gemini (API key)
- OpenRouter (multi-model)
- Custom providers

When a requested model isn't available in Gemini Web, the service automatically forwards to the appropriate provider using stored keys.

### Access Keys

Issue inbound access keys you can hand out to different people. This is unrelated to "API Keys Management" above — that one manages third-party **outbound** keys, while this one controls *who may call this service*.

**Issuing a key:**
1. Click **Issue Key**
2. Fill in **Name** (e.g. the recipient's name, so you can reconcile later)
3. **Count** issues several keys at once (max 50); names are auto-numbered `name-1`, `name-2`, …
4. **Valid days (from first use)** and **Absolute expiry** are mutually exclusive; leave both empty for a key that never expires
5. **Request limit** empty = unlimited
6. **Bound accounts** / **Allowed models**: nothing checked = unrestricted
7. Click **Issue**, then use **Copy key** in the list to hand the plaintext over

**List and management:**

Each row shows the state (Valid / Not activated / Disabled / Expired / Limit reached), validity, usage and scope, and lets you:
- **Edit**: change the name, validity, limit, bound accounts and allowed models
- **Enable / Disable**: disabling 401s the holder immediately while the key stays in the list and can be restored
- **Reset usage**: zero the request counter so a key that hit its limit can be reused
- **Delete**: revoke the key; clients using it are cut off immediately

**Three things to know:**
1. The `API_KEY` in `.env` still has full privileges; access keys are only an additional layer, and with none issued the behavior is identical to previous versions.
2. An access key can **only call the business API** — never `/admin/*`. The admin surface stays guarded by `API_KEY` / `ADMIN_API_KEY`, which is what makes it safe to hand a key to an outsider.
3. Every business request counts +1, **including `GET /v1/models`**. Some clients list the models before every turn, which means two counts per round — leave headroom when setting the request limit.

#### Token usage and estimated cost

Besides **Usage** (a request count), the list shows two more columns: **Tokens (est.)** — the key's cumulative input / output tokens — and **Est. cost (USD)**, always prefixed with `≈`.

⚠️ **This is a reference number, not a bill.** Three things to know:

1. The service talks to Gemini **Web** and **costs nothing by itself**. This column answers "what would the same content cost on the official API".
2. Token counts come from `len(text) / 4`, **not a real tokenizer**. CJK text is badly underestimated (one Han character is usually one token, counted here as 0.25), so a long Chinese conversation can really be 3-4x this number.
3. The price table is flattened to the published standard paid tier, ignoring long-context steps and future price changes; thinking tokens count towards output (matching the official billing convention). Requests served by a third-party fallback are not counted.

**Statistics only, never a limit**: tokens and dollars take no part in any admission decision — the only quota is still the request limit (a count). "Reset usage" clears the request count and the token / cost figures together.

Configure the table with the `TOKEN_PRICES` env var, e.g. `gemini-pro=2.0/12.0,gemini-flash=0.75/3.75` (public model name=input/output price, USD per million tokens). Empty means the built-in defaults; malformed entries are ignored silently, and a model with no price shows `—` instead of falling back to a "close enough" rate. A crash loses at most 10 seconds of accounting, the same window the request counter already has.

### Settings

Configure runtime behavior:

1. Click **Settings** in the sidebar
2. Modify settings in organized groups:
   - **Performance**: Concurrency limits, retry behavior
   - **Rate Limiting**: Enable/disable and configure limits
   - **Health Checks**: Interval and enabled status
   - **Cookie Management**: Refresh interval, rotation strategy
   - **Statistics**: Enable/disable usage tracking
   - **Web Session Cleanup**: Enable automatic cleanup of accumulated Gemini web sessions. Every API conversation leaves a record on gemini.google.com that piles up over time. Configure retention window (default 24h, far larger than the 6h context window so active conversations are safe), cleanup interval (default 6h), and whether to skip pinned sessions (default: skip). The background task loops until all old sessions are deleted, handling accounts with hundreds of accumulated sessions.
3. Click **Save** to apply changes immediately

All changes take effect without restarting the service.

### Model Mapping

Create aliases for models:

1. Click **Model Mapping** in the sidebar
2. **Add Mapping**: Create an alias (e.g., `gpt-4o` → `gemini-2.5-pro`)
3. When clients request `gpt-4o`, the service uses `gemini-2.5-pro` instead
4. Useful for compatibility with existing client configurations

### Language Switching

Change the interface language:

1. Click the **globe icon** in the top-right corner
2. Select your language:
   - English
   - 简体中文 (Simplified Chinese)
   - 繁體中文 (Traditional Chinese)
   - 日本語 (Japanese)
   - 한국어 (Korean)

Language preference is saved in browser storage.

### Theme Switching

Toggle between light and dark themes:

1. Click the **theme icon** (sun/moon) in the top-right corner
2. Theme preference is saved in browser storage

### Service Control

Manage the service from the top-right control bar:

- **Restart Service**: Click the restart icon to restart the service (useful after configuration changes)
- **Logout**: Click to log out and return to login screen

## Image Upload

Gemini2API supports multimodal content including image and file uploads. Three API formats are supported for image transmission.

### OpenAI Format

Use `image_url` type in the `messages` array. Supports both Base64 Data URI and remote HTTP URLs:

**Base64 Image Example:**

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "messages": [
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
    ]
  }'
```

**Remote URL Image Example:**

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Analyze this image"},
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/image.jpg"
            }
          }
        ]
      }
    ]
  }'
```

### Claude Format

Use `image` type in the `content` array:

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "What is this"},
          {
            "type": "image",
            "source": {
              "type": "base64",
              "media_type": "image/png",
              "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            }
          }
        ]
      }
    ]
  }'
```

### Gemini Native Format

Use `inlineData` in the `parts` array:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "contents": [
      {
        "parts": [
          {"text": "What is this"},
          {
            "inlineData": {
              "mimeType": "image/png",
              "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            }
          }
        ]
      }
    ]
  }'
```

### Web Panel Upload

In the Playground test page, click the "Add Image" button to upload local images for testing.

## AI Image Generation

Gemini2API can generate images from text. Image generation is triggered by the prompt itself: simply ask the model to create an image in the conversation (for example, "generate an image of..."). All three chat endpoints support this, OpenAI `/v1/chat/completions`, Claude `/v1/messages`, and Gemini `/v1beta/...:generateContent`. A dedicated OpenAI-compatible endpoint, `/v1/images/generations`, is also available.

### Chat Endpoint

Ask for an image in a normal chat request:

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-pro",
    "messages": [
      {"role": "user", "content": "generate an image of a cute cat"}
    ]
  }'
```

### Dedicated Endpoint

Use the OpenAI-compatible image generation endpoint:

```bash
curl -X POST http://localhost:5918/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

Chat endpoints return a locally hosted image URL (such as `http://localhost:5918/images/xxx.png`) that you can open or render directly. The `/v1/images/generations` endpoint returns `b64_json` instead. In both cases the image is the full-resolution original (for example, 1408x768).

## Body Recovery (Canvas and control markers)

Gemini Web has two cases where "the body isn't the body". The service normalises both before handing the answer to the client, with the streaming and non-streaming paths producing byte-for-byte the same text:

**Canvas panel**: when writing longer code or documents, the web client moves the content into its Canvas panel and leaves only a `http://googleusercontent.com/immersive_entry_chip/N` placeholder link in the body. The service pulls the real Canvas content out of the response and restores it into the body (code gets a fenced block with its language, documents are inlined as-is). When the real content cannot be recovered, the dead link is **stripped and replaced with a readable note** — an unopenable URL is never delivered as the answer, and the body never ends up empty.

**Control markers**: three kinds of internal markers can leak into the body; all of them are cleaned up:

| Marker | Handling |
|--------|----------|
| `<ctrl94>thought…<ctrl95>` | The content is **moved into the thinking chain** (`reasoning_content` / Anthropic `thinking` block) rather than discarded. Only **paired** markers are processed; an unterminated marker is left untouched — a missing end marker must never cause the rest of the body to be treated as thinking |
| `?code_reference&code_event_index=N` / `?code_stdout&…` | Only the marker inside the fence info string is removed; **the fence body is kept verbatim** |
| `http://googleusercontent.com/card_content/N` | Removed (a dead link clients cannot open) |

Prose that merely mentions these strings (e.g. asking the model what `<ctrl94>` is) is not touched.

**Known boundary**: if the body genuinely contains a **paired** `<ctrl94>…<ctrl95>` (for example you pasted a log holding both literals and asked the model to echo it), the enclosed text is treated as thinking and moved out of the body. On the OpenAI protocol it comes back in `reasoning_content`, and on the Anthropic protocol it comes back in a `thinking` block when you pass `thinking`; but the native Gemini protocol and `/v1/messages` without `thinking` have no channel for thinking, so that text is not recoverable there. For such content, use the OpenAI protocol.

## Supported Models

Gemini2API provides 3 fixed stable model names that never change. These serve as the API contract, allowing clients to use them long-term without worrying about model name changes:

| Model ID | Description |
|----------|-------------|
| `gemini-pro` | Pro model with strongest performance, suitable for complex tasks |
| `gemini-flash` | Fast model with low latency, suitable for real-time applications |
| `gemini-flash-lite` | Lightest & fastest model (3.5 Flash-Lite), usable when Pro/Flash are rate-limited |
| `gemini-argon` | 4 Argon, for complex tasks. Only listed when at least one account actually has it (aliases: `gemini-4-argon`) |

> `gemini-flash-thinking` is retired: it still works (a hidden alias of `gemini-flash`) but no longer appears in model lists. Thinking is now a `low` / `medium` / `high` level on every model; when the client passes nothing the default is `low` (measured: about 5 s more per request on average; switch to `off` in the panel's Settings → Thinking for maximum speed). See ["🧠 Models & Thinking Levels" in the README](README.md#-models--thinking-levels).

**Account-driven model discovery**: beyond the fixed names above, the service reads the model list from the account heartbeat. A model the account really has but the built-in table does not know (4 Argon is exactly this case) is adopted automatically, validated first (16-hex model id, positive model number, parsable label, and a name that cannot shadow any existing public name); entries that fail validation are dropped and logged. The three contract names above never come from discovery, so a malformed heartbeat can never re-point them.

**Discovered models are per-account**: a discovered name such as `gemini-argon` is routable only on the account that actually discovered it. The model list is aggregated across the pool, so in a mixed pool (some accounts have Argon, some do not) a request can land on an account without it — the service then fails the request (HTTP 400 `Model ... unavailable`) instead of falling back to another model. That is deliberate: a silent model swap looks like HTTP 200 with a perfectly normal body, and the client cannot tell the answer came from a different model. For stable availability, make sure every account in the pool has the model, or use one of the three contract names. Also, once a heartbeat round stops reporting a discovered model, it disappears from the model list right away, so you never get a name that is listed but broken.


**Internal Auto-Mapping**: The service automatically maps these fixed names to the actual available models based on your Google account subscription level (Advanced/Plus/Basic). Regardless of account tier changes, Google rollouts, or service restarts, clients always use these 3 fixed names without modification.

**Legacy Alias Compatibility**: For backward compatibility, older model names are still supported:
- `gemini-2.5-pro`, `gemini-2.0-flash`, `gemini-2.0-flash-thinking`, etc.

### Third-Party Models

Supported via API Key pool:
- **OpenAI**: gpt-4o, gpt-4-turbo, gpt-3.5-turbo, etc.
- **Anthropic**: claude-3-opus, claude-3-sonnet, claude-3-haiku, etc.
- **Google Gemini**: via official API Key
- **OpenRouter**: all models on OpenRouter platform

## Third-Party Client Integration

### ChatGPT-Next-Web

1. Deploy ChatGPT-Next-Web or open the web interface
2. Click **Settings** (bottom-left)
3. Under **API Settings**:
   - **API Key**: Enter your gemini2api API Key (sk-...)
   - **API Endpoint**: `http://SERVER_IP:5918/openai/v1`
4. Click **Save**
5. Start a new conversation and select a Gemini model

### LobeChat

1. Open LobeChat settings
2. Go to **Model Provider** → **OpenAI**
3. Configure:
   - **API Key**: Your gemini2api API Key
   - **Base URL**: `http://SERVER_IP:5918/openai/v1`
4. Save and refresh
5. Models will appear in the model selector

### OpenCat (iOS)

1. Open OpenCat app
2. Tap **Settings** → **API Configuration**
3. Add custom endpoint:
   - **Name**: Gemini2API
   - **API Key**: Your gemini2api API Key
   - **Base URL**: `http://SERVER_IP:5918/openai/v1`
4. Select Gemini2API as your provider
5. Choose a model and start chatting

### Python SDK (OpenAI)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "user", "content": "Explain quantum computing"}
    ],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

### Python SDK (Anthropic/Claude)

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/claude"
)

message = client.messages.create(
    model="gemini-2.5-pro",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Write a haiku about programming"}
    ]
)

print(message.content[0].text)
```

### cURL

```bash
# Non-streaming request
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "Hi"}]
  }'

# Streaming request
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": true
  }'
```

## Conversation Context

Gemini2API supports multi-turn conversations in two ways:

### Method 1: Client-Side History

Most clients (ChatGPT-Next-Web, LobeChat, etc.) maintain conversation history locally. Simply continue the conversation in the UI.

### Method 2: Conversation ID (Advanced)

For programmatic use, include `conversation_id` in requests:

```python
response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "Remember this: I like Python"}],
    conversation_id="conv-12345"  # Unique conversation identifier
)

# Later, continue the same conversation
response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "What do I like?"}],
    conversation_id="conv-12345"  # Same ID continues context
)
```

The service maintains conversation context on the Gemini Web backend, enabling multi-turn interactions without sending full history.

## Cookie Management

### When to Refresh Cookies

Cookies expire after 2-24 hours. Refresh them when:
- Service returns "SNlM0e not found" error
- All accounts show "unhealthy" status
- Requests start failing with 503 errors

### How to Refresh

**Via Web Panel:**
1. Go to **Account Management**
2. Click **Update Cookies** for an account
3. Get fresh cookies from gemini.google.com (see DEPLOY.md)
4. Paste and save

**Via API:**
```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new..."
  }'
```

## Performance Tips

1. **Use Multiple Accounts**: Distribute load across 2-3 accounts for better throughput
2. **Enable Failover Strategy**: Set `ROTATION_STRATEGY=failover` for automatic failover when an account fails
3. **Adjust Concurrency**: Increase `MAX_CONCURRENT_PER_ACCOUNT` if you have spare resources
4. **Use Flash Models**: `gemini-2.5-flash` is faster than `gemini-2.5-pro` for most tasks
5. **Enable Caching**: Use conversation IDs to maintain context without resending history

## Troubleshooting

### "Unauthorized" Error (401)

- Verify API Key is correct
- Check Authorization header format: `Authorization: Bearer sk-xxx`
- Regenerate API Key in Settings if needed

### "No Available Accounts" Error (503)

- All accounts are unhealthy
- Refresh cookies via Web Panel
- Check account status in Account Management
- Verify network connectivity to gemini.google.com

### Slow Responses

- Check account health status
- Reduce concurrent requests
- Use `gemini-2.5-flash` instead of `gemini-2.5-pro`
- Add more accounts for load distribution

### Model Not Found

- Verify model name is correct (case-sensitive)
- Check available models in Dashboard
- Model availability depends on your Google account tier
