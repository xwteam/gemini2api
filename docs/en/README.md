<div align="center">

<h1>Gemini2API</h1>
<h3>Lightweight Gemini Web Reverse Proxy</h3>
<p>Single codebase compatible with OpenAI / Claude / Gemini SDKs, pure async architecture, zero official keys, Docker quick deployment.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/curl__cffi-Chrome%20TLS-ff6b35?style=flat-square&logo=google-chrome&logoColor=white" alt="curl_cffi">
  <img src="https://img.shields.io/badge/Docker-20.10+-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Chrome%20%7C%20Edge-Latest-4285F4?style=flat-square&logo=googlechrome&logoColor=white" alt="Browser">
  <img src="https://img.shields.io/badge/License-Non--Commercial-red?style=flat-square" alt="License">
</p>

<p>
  <a href="#-recent-updates">Recent Updates</a> &bull;
  <a href="#-core-features">Core Features</a> &bull;
  <a href="#-system-requirements">System Requirements</a> &bull;
  <a href="#-quick-deployment">Quick Deployment</a> &bull;
  <a href="#-integration-examples">Integration Examples</a> &bull;
  <a href="#-api-endpoints">API Endpoints</a> &bull;
  <a href="#-configuration">Configuration</a> &bull;
  <a href="#-important-notes">Important Notes</a> &bull;
  <a href="#-roadmap">Roadmap</a>
</p>

<p>
  📖 Documentation: <a href="../zh-CN/README.md">简体中文</a> | <a href="../zh-TW/README.md">繁體中文</a> | English | <a href="../ja/README.md">日本語</a> | <a href="../ko/README.md">한국어</a>
</p>

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> This project is for research and learning purposes only. Please use it responsibly and do not use it for any commercial purposes.

> [!WARNING]
> This project is not affiliated with Google. It uses reverse-engineered browser cookies to access Gemini Web, which may violate Google's Terms of Service. Use at your own risk. The author is not responsible for any account penalties or data loss.

> [!TIP]
> It is recommended to use Gemini Pro or higher subscription for complete model access and stable experience.

> [!IMPORTANT]
> Due to Google's risk control policies, cookie sessions typically expire after about 2 hours. We haven't found a perfect long-term solution yet. If you have experience or ideas on this, please share them via [Issue](https://github.com/xwteam/gemini2api/issues) or PR. We look forward to community wisdom.

---

## 📝 Recent Updates

> For complete changelog, see [CHANGELOG.md](../../CHANGELOG.md). The following is auto-synced by CI.

| Date | Update |
|------|--------|
| 2026-06-22 14:21:48 | v1.6.23 - 🧠 Per-model thinking (reasoning_effort) setting for third parties: configure a thinking level per third-party model in API Management (unset / none / low / medium / high / custom); the relay auto-injects it on forward — reasoning_effort for OpenAI-compatible upstreams, mapped to thinking (budget_tokens) for Anthropic with the response thinking mapped back to reasoning_content; zero regression when unset, leave non-thinking models unset; also fixes "a reasoning-only response (content temporarily empty) wrongly treated as empty" |
| 2026-06-22 11:29:42 | v1.6.22 - 🔁 Third-party direct-call same-model multi-provider failover: when one model ID has multiple third-party providers in API Management, the direct call sticks to the first and, on error / rate-limit / quota-exhaustion / timeout / empty response, auto-switches to the next same-model provider, returning the last error only if all fail — the client sees one model name, transparently; streaming fails over before the first byte, failed providers enter an in-memory cooldown (`THIRDPARTY_FAILOVER_COOLDOWN`, default 180s) and are skipped until it expires, yet are still tried when all are cooling or only one exists (never starves); on by default with no switch, single-provider zero regression, Gemini→third-party fallback chain unaffected |
| 2026-06-21 00:33:02 | v1.6.21 - 🔀 Gemini → third-party auto-fallback chain: when any Gemini model (flash/pro/thinking) errors or returns an empty response, automatically retry natively with a third-party model from the API Key pool — transparent to the client, still one model name; candidates auto-taken from the pool, non-chat models (image/video/audio/embedding) skipped by name, random round-robin switching to the next on failure, probed non-streaming (neither errors nor empties mistaken for success), streaming converted to SSE with native tool calls; `FALLBACK_ENABLED` off by default, `FALLBACK_MODELS` optional pin, zero regression |
| 2026-06-19 22:40:00 | v1.6.20 - 🐳 Fix the non-root image upgrade regression from v1.6.19: existing deployments hit `PermissionError` → startup crash loop after `docker compose pull` because the root-owned `./data` was not writable by the non-root user. The image now starts as root via an entrypoint → `chown`s the data/api volumes → drops to non-root (uid 1000) via `gosu`, keeping the non-root hardening while making `docker compose pull && up -d` a seamless upgrade (no manual chown). |
| 2026-06-19 22:00:00 | v1.6.19 - 🔒 Security & quality hardening batch: fixed 6 admin-panel XSS, 2 SSRF (attachment-download redirect bypass / unvalidated forward base_url), a permanent DoS from corrupting `.env` via settings, and conversation_id path traversal; 🔧 streaming image-gen placeholder URL leak / forward SSE missing delimiter & `[DONE]`, usage-stats 500 when disabled, accounts.json atomic write, account ID collision, and more; ⚙️ MODEL_WHITELIST / JITTER_ENABLED / VERSION_SYNC_INTERVAL configs now actually honored; 📄 docs/config fully aligned + new drift test; 🐳 non-root image + blocking CI gate. Zero regression (63 tests + ruff + adversarial review pass) |
| 2026-06-19 14:15:00 | v1.6.18 - 🔧 Fixed gemini-pro image-gen network error: image POST timeout 60s→180s; SSE keepalive 10s + chunk ping. Zero regression (62 tests pass) |
| 2026-06-19 13:30:00 | v1.6.17 - 🔧 Fixed playground image-gen network error: immediate SSE first frame + 15s ping keepalive; image download =s2048/25s/=s512 fallback. 🎨 Generating wait-state UX + 5-locale i18n. Zero regression (52 tests pass) |
| 2026-06-19 03:01:44 | v1.6.16 - 🔧 Stability & security hardening: fixed deep-research endpoint always-500, broken third-party streaming forward, account slot-leak deadlock, multi-account model-resolution cross-talk, intermittent "Client not ready", and rate limiting that never took effect; 🔒 Security: admin/business key separation (optional `ADMIN_API_KEY`), API key log masking, dual SSRF guards, key-export/PSID masking, atomic credential writes, configurable CORS, constant-time compare; 🧪 added automated tests + CI gate and panel a11y/i18n improvements. Zero regression (58 tests pass) |
| 2026-06-06 19:29:01 | v1.6.15 - 🧹 Auto-cleanup of accumulated Gemini web sessions: every API conversation leaves a record on the web side and piles up over time. A background task now periodically (default every 6h) deletes old sessions beyond the retention window (default 24h); pinned sessions are never deleted; loops until clean to handle heavy accounts with hundreds of sessions; retention window is far larger than the proxy context window (6h) so active multi-turn conversations are never mis-deleted; new "Web Session Cleanup" group in Settings |
| 2026-06-02 20:16:19 | v1.6.14 - 🖼️ Image generation intent recognition now includes volitional verbs: requests like "I want an image of…", "want a picture", "I need a poster" using want/need now correctly trigger image generation with images first (previously images appeared after text or with http fragments); still requires image noun + verb co-occurrence to avoid false positives on everyday language |
| 2026-06-02 18:51:41 | v1.6.13 - 🖼️ Image generation responses now put images first with compact formatting (no more long text + blank lines + images); significantly enhanced image generation intent recognition (natural requests like "draw/generate/design/make/create a picture", "poster/logo" etc. now correctly generate images and put them first); filtered image_retrieval/image_collection placeholder URLs, show friendly message instead of empty content when no valid images |
| 2026-06-02 16:37:57 | v1.6.12 - 🛠️ Fixed agent (e.g. Hermes) with tools suppressing image generation and malformed tool call JSON passthrough: auto-detect image generation intent to skip tool simulation and generate directly; multi-layer fault-tolerant parsing for tool calls (strip markdown/extract JSON/tolerate malformation), no more malformed passthrough; Gemini native API tool calls now correctly return functionCall |
| 2026-06-02 13:04:39 | v1.6.11 - 🔁 Intelligent 503 failover: when Google intermittently rate-limits datacenter IPs with 503, multi-account setups now auto-switch to the next available account (immediate failover when one hits 503), rate-limited accounts enter 30s cooldown without being marked as invalid; single-account 5xx errors only retry quickly without long backoff waste |
| 2026-06-01 20:21:43 | v1.6.10 - ⚡ True streaming output: all three APIs now use genuine incremental streaming (push the first character as soon as it's generated, no longer waiting for a full chunk to fake character-by-character output), chat experience dramatically improved; 🚀 Massively increased concurrency: single-account concurrency 3→8, and queues when full instead of immediately erroring with "No available accounts", agents no longer fail on concurrent requests |
| 2026-06-01 00:32:16 | v1.6.9 - 🖼️ Generated images now returned at full resolution: previously downloaded a compressed thumbnail (512px); now appends `=s0` to get the original size (e.g. 1408×768) |
| 2026-06-01 00:18:01 | v1.6.8 - 🖼️ Image generation no longer returns the googleusercontent placeholder URL: this meaningless placeholder is now filtered out, so only the image itself is returned |
| 2026-06-01 00:02:09 | v1.6.7 - 🖼️ Fixed model test in the control panel not showing images: generated images now render directly instead of being displayed as markdown text/URL |
| 2026-05-31 23:41:15 | v1.6.6 - 🖼️ Local hosting for generated images: the chat APIs now return accessible local URLs (`/images/{id}`) for generated images instead of base64, so CLI/agent clients can render them properly (base64 doesn't display in these clients); images are auto-cleaned up periodically |
| 2026-05-31 22:36:53 | v1.6.5 - 🎨 AI image generation: added OpenAI-compatible `/v1/images/generations` endpoint (returns `b64_json`); all three chat APIs auto-embed generated images into replies (markdown / image block / inlineData) |
| 2026-05-31 17:00:00 | v1.6.4 - All three APIs expose standard bare paths (/v1/chat/completions, /v1/messages, /v1beta/...) — major SDKs work out of the box; fixed deployment mechanism (docker-compose switched from build to image, so docker compose pull actually takes effect) |
| 2026-05-31 14:10:00 | v1.6.3 - Image/file upload support (OpenAI/Claude/Gemini multimodal); models now use real web data + stable fixed names (gemini-pro/flash/flash-thinking); cookies no longer lost on restart |
| 2026-05-19 20:00:00 | v1.6.2 - Session auto-expires and logs out after 5 minutes of inactivity |
| 2026-05-18 16:30:00 | v1.6.1 - Dark theme comprehensive fixes, update check dialog beautification, GitHub Actions auto-build images, failover strategy |
| 2026-05-17 23:20:00 | Unified model list to user-friendly names, added thinking mode (gemini-2.5-flash-thinking) and Pro mode, fixed Playground conversation context |
| 2026-05-17 22:30:00 | Fixed container timezone to Asia/Shanghai, logs show Beijing time |

---

## 🌟 Core Features

> 📖 Detailed usage guide: [USAGE.md](USAGE.md)

### 🔌 Triple Protocol Compatibility

- Single service provides OpenAI, Claude, and Gemini SDK formats simultaneously
- SSE streaming (OpenAI / Claude) + Chunked JSON (Gemini)
- Function calling supported across all three formats
- Deep Research multi-step research capability

### 🔐 Security & Authentication

- Auto-generated API Keys (`sk-` prefix + 32 random characters)
- Supports both `Authorization: Bearer` and `x-api-key` authentication
- Auto-generated on first deployment, customizable by users

### 🔄 Multi-Account Load Balancing & Cookie Self-Healing

- **Multi-account load balancing**: Supports round-robin and failover strategies
- Per-account concurrency control prevents single account overload
- Automatic health marking for failed accounts, auto-skip unhealthy ones
- Background cookie rotation for seamless renewal
- Hot-update Cookie API without container restart
- Dynamic account add/remove via API
- Health check history for web panel data support

### 🛡 Anti-Detection & Protocol Spoofing

- **TLS fingerprint consistency**: UA, Sec-Ch-Ua, curl_cffi impersonate always synchronized (Chrome 124)
- **Dynamic request headers**: Arranged in Chrome's real order, dynamically adjust Sec-Fetch-* based on request type
- **Complete cookie persistence**: Auto-capture all response cookies and persist to disk across restarts
- **Cookie domain isolation**: Clear session cookies before each request to prevent cross-domain conflicts
- **Chrome version auto-sync**: Poll Google version API every 24 hours, auto-update fingerprint on new version
- **Request time jitter**: Simulate human operation intervals (navigation 200-800ms / API 50-300ms / cookie rotation 1-3s)
- **Version fallback strategy**: Auto-use nearest available version when curl_cffi doesn't support latest Chrome

### 🖥 Web Management Panel

- Chinese visual management interface with API Key authentication
- Top-right control bar: theme toggle, service restart, logout
- Dashboard: real-time uptime counter, QR code cards (image zoom support), system info (version/Python/OS/memory/CPU/PID/mode), config management, account status overview, available models list
- **Hot-update resources**: `api/` directory volume mount, QR code images and text config changes take effect on page refresh without container rebuild
- Account management: add/delete accounts, update individual cookies, health checks
- **Settings page**: visual runtime config management (performance, rate limiting, health checks, account management), changes take effect immediately
- **Model mapping**: map request model names to actual models (e.g., gpt-4o → gemini-2.5-pro)
- **API Key management**: centralized third-party model API Key management (OpenAI/Anthropic/Gemini/OpenRouter/custom), import/export support
- Playground: online API testing
- Real-time logs: structured table display, direction filter, text search, pagination (15 per page), JSON detail panel, disk persistence (survives restart)
- Dark/light theme toggle, responsive mobile adaptation

### 🔀 Unified Forwarding Engine

- Auto-forward requests for models not in Gemini Web's available list to matching Provider from API Key pool
- Direct OpenAI-compatible format forwarding (including streaming), bidirectional Anthropic conversion
- `/openai/v1/models` auto-aggregates Gemini Web models + third-party models from API Key pool
- Single interface, single key to call all major models
- Third-party auto-fallback (`FALLBACK_ENABLED`, off by default): when any Gemini model errors or returns an empty response, automatically retry natively with a third-party model from the API Key pool — transparent to the client, still using just one model name; by default automatically uses all "chat-capable" third-party models in the pool (excludes non-chat models such as image/video), random round-robin, switching to the next on failure; `FALLBACK_MODELS` optionally specifies them precisely

### ⚡ High-Performance Architecture

- Python asyncio + curl_cffi, fully non-blocking pipeline
- Chrome TLS fingerprint spoofing + auto version tracking, significantly extended session lifetime
- Pydantic strong type validation, automatic request parameter validation
- Modular design, independent routing files for each API format
- Automatic retry with exponential backoff

---

## 📋 System Requirements

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.12+ | Recommended 3.12, older versions untested |
| Docker | 20.10+ | Optional, Docker deployment recommended |
| Google Account | — | Must have normal access to [gemini.google.com](https://gemini.google.com) |
| Browser | Chrome / Edge | For cookie extraction (deployment only) |

> [!TIP]
> Docker deployment requires no local Python installation, just Docker and valid cookies.

---

## ⚡ Quick Deployment

> 📖 Detailed deployment guide: [DEPLOY.md](DEPLOY.md)

> **Prerequisite**: You need a Google account with normal Gemini access.

### 1. Get Cookies

1. Open Chrome or Edge browser and visit [gemini.google.com](https://gemini.google.com)
2. Log in with your Google account and verify Gemini works normally
3. Press `F12` to open Developer Tools
4. Click the **Application** tab at the top
5. In the left sidebar, find **Cookies** -> click `https://gemini.google.com`
6. Find these two values in the cookie list:

| Cookie Name | Description |
|-------------|-------------|
| `__Secure-1PSID` | Long string starting with `g.`, typically dozens of characters |
| `__Secure-1PSIDTS` | Shorter string |

7. Recommended to operate in incognito mode, close the window immediately after getting values to avoid cookie rotation issues

> [!TIP]
> Search for `__Secure-1P` in the search box for quick filtering. Double-click the Value column to copy the full value.

> [!WARNING]
> Cookies expire over time. If the service suddenly stops working, check if cookies have expired first.

### 2. Docker Deployment

```bash
# Clone repository
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# Create environment file
cp .env.example .env
```

Edit `.env` file and add your cookies:

```env
GEMINI_PSID=g.a000xxx...(paste your full __Secure-1PSID value)
GEMINI_PSIDTS=sidts-xxx...(paste your full __Secure-1PSIDTS value)
```

> [!IMPORTANT]
> Important notes:
> - Values don't need quotes
> - No extra spaces or newlines
> - Ensure you copy the complete value, don't miss the end

Start the service:

```bash
docker compose up -d
```

Check logs to confirm successful startup:

```bash
docker compose logs -f
# "Account pool ready: 1/1 active" means account pool is ready
# "SNlM0e not found" means cookie is invalid, need to get new one
```

### Multi-Account Configuration (Optional)

To use multiple Google accounts for load balancing, create `accounts.json`:

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "Main Account"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "Backup Account"
    }
  ]
}
```

> [!TIP]
> Without `accounts.json`, the service automatically uses single-account mode from `.env`. You can also dynamically add accounts via `POST /admin/accounts` API at runtime.

### Cookie Auto-Keep-Alive

gemini2api has built-in cookie auto-rotation: refresh `__Secure-1PSIDTS` every 5 minutes via Google RotateCookies API, combined with batchexecute heartbeat to simulate browser activity and extend session lifetime.

To manually update cookies, use the Web panel's "Account Management" → "Update Cookie" without restarting the service.

> [!NOTE]
> Cookie lifetime is affected by Google's risk control policies. Datacenter IPs typically last several hours. If cookies expire frequently, consider using residential IPs or adding more accounts for rotation.

### 3. Verification

```bash
# Health check
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# View available models (requires API Key, check logs on first startup)
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"

# Send test request
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

Seeing AI response text means deployment succeeded. If you get 401, check your API Key.

---

## 🧪 Integration Examples

> [!NOTE]
> All API requests require an API Key. Two authentication methods supported:
> - `Authorization: Bearer sk-xxx` (recommended, compatible with OpenAI/Claude SDKs)
> - `x-api-key: sk-xxx`
>
> API Key is auto-generated on first startup and written to `.env`, visible in logs or manually editable.

<details>
<summary><b>OpenAI SDK (Python)</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "Explain relativity in three sentences"}],
    stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

</details>

<details>
<summary><b>Claude SDK (Python)</b></summary>

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "Write a Python quicksort implementation"}]
)
print(msg.content[0].text)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
# Non-streaming request
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}]}'

# Streaming request
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

</details>

<details>
<summary><b>Function Calling</b></summary>

```python
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "What's the weather in Beijing today"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            }
        }
    }]
)
```

</details>

---

## 📡 API Endpoints

> 📖 Detailed API documentation: [API.md](API.md)

### OpenAI Compatible (`/openai/v1`)

| Method | Endpoint | Function |
|--------|----------|----------|
| GET | `/models` | Available models list |
| POST | `/chat/completions` | Chat completion (streaming + tool calling) |

### Claude Compatible (`/claude/v1`)

| Method | Endpoint | Function |
|--------|----------|----------|
| GET | `/models` | Models list |
| GET | `/models/{id}` | Model details |
| POST | `/messages` | Message generation (streaming + tool calling) |
| POST | `/messages/count_tokens` | Token count estimation |

### Gemini Native (`/gemini/v1beta`)

| Method | Endpoint | Function |
|--------|----------|----------|
| GET | `/models` | Models list |
| POST | `/models/{m}:generateContent` | Content generation |
| POST | `/models/{m}:streamGenerateContent` | Streaming generation (Chunked JSON) |

### Admin Interface (`/admin`)

> Full admin endpoints (with request/response examples) are in [API.md](API.md); the table below is the complete list.

| Method | Endpoint | Function |
|--------|----------|----------|
| GET | `/status` | Service status (account pool overview + rotation strategy) |
| GET | `/system-info` | System info (version/Python/OS/memory/CPU/PID/run mode) |
| GET | `/accounts` | All accounts list and status |
| POST | `/accounts` | Dynamically add new account |
| DELETE | `/accounts/{id}` | Remove account |
| GET | `/accounts/{id}/check` | Check single account status |
| GET | `/check-account` | Check all accounts status |
| POST | `/reload-cookies` | Hot-update cookies (no container restart) |
| PUT | `/accounts/{id}/cookies` | Update cookies for a specific account |
| GET | `/health-history` | Recent health check records |
| GET | `/usage-stats/summary` | Usage statistics summary |
| GET | `/usage-stats/history` | Historical trend data |
| GET | `/settings` | Get current editable config (grouped) |
| POST | `/settings` | Batch-update config (writes .env + hot-reloads memory) |
| GET | `/api-keys` | API Key list (keys masked) |
| GET | `/api-keys/catalog` | Provider catalog (built-in model lists) |
| POST | `/api-keys` | Add API Key |
| DELETE | `/api-keys/{id}` | Delete API Key |
| PATCH | `/api-keys/{id}/status` | Toggle Key status (enable/disable) |
| PATCH | `/api-keys/{id}/label` | Edit Key label |
| POST | `/api-keys/import` | Bulk-import Keys |
| GET | `/api-keys/export` | Export all Keys (masked by default, `?reveal=true` for plaintext) |
| POST | `/api-keys/batch-delete` | Bulk-delete |
| POST | `/api-keys/models` | Probe available models for a given Provider/base_url |
| GET | `/verify` | Verify API Key validity (used for login) |
| POST | `/restart` | Restart service (one-click restart from top-right of panel) |
| GET | `/check-update` | Check whether a new version is available |
| POST | `/update` | Trigger update to the latest version |
| GET | `/logs` | Structured log pagination query |
| GET | `/logs/state` | Log recording state |
| POST | `/logs/state` | Update log recording state |
| POST | `/logs/clear` | Clear logs |
| GET | `/logs/{id}` | Single log detail |
| GET | `/model-mapping` | Get all model mappings |
| POST | `/model-mapping` | Add/update model mapping |
| DELETE | `/model-mapping/{alias}` | Delete model mapping |
| GET | `/web-chats` | List sessions accumulated on the Gemini web side per account (read-only) |
| POST | `/cleanup-web-chats` | Manually trigger cleanup of expired web sessions (runs asynchronously in background) |

---

## ⚙ Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_PSID` | ✅ | — | Browser `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | Browser `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | Auto-generated | API access key (`sk-` prefix, auto-generated on first startup if empty) |
| `REFRESH_INTERVAL` | ❌ | `5` | Cookie refresh interval (minutes) |
| `MAX_RETRIES` | ❌ | `3` | Retry count on failure (exponential backoff) |
| `PORT` | ❌ | `5918` | Service port |
| `LOG_LEVEL` | ❌ | `info` | Log level (debug/info/warning/error) |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | Enable rate limiting |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | Rate limit window (seconds) |
| `RATE_LIMIT_MAX` | ❌ | `10` | Max requests per window |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | Enable scheduled account health checks |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | Check interval (minutes) |
| `ACCOUNTS_FILE` | ❌ | `accounts.json` | Multi-account config file path (falls back to single-account mode from env vars if absent) |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | Rotation strategy: `round-robin` / `failover` |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `8` | Max concurrent requests per account |
| `ACQUIRE_TIMEOUT` | ❌ | `60.0` | Max time (seconds) to queue for a free slot when at full concurrency before erroring |
| `SAME_ACCOUNT_5XX_RETRIES` | ❌ | `1` | Quick same-account retries on 5xx (no long backoff); failover to another account if still failing |
| `FAILOVER_COOLDOWN` | ❌ | `30.0` | Cooldown (seconds) for an account rate-limited by 5xx, during which it is not preferred |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | Fingerprint config file path |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | Enable Chrome version auto-sync |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | Version sync interval (hours) |
| `JITTER_ENABLED` | ❌ | `true` | Enable request time jitter (simulate human behavior) |
| `USAGE_STATS_ENABLED` | ❌ | `true` | Enable usage statistics (time-series snapshots + persistence) |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | Snapshot collection interval (seconds) |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | Historical data retention (days) |
| `MODEL_WHITELIST` | ❌ | — | Model whitelist (comma-separated; empty = no filtering; when set, filters each `/models` list) |
| `CHAT_CLEANUP_ENABLED` | ❌ | `true` | Enable auto-cleanup of Gemini web sessions |
| `CHAT_CLEANUP_KEEP_HOURS` | ❌ | `24.0` | Web session retention (hours); older ones are cleaned up |
| `CHAT_CLEANUP_INTERVAL_HOURS` | ❌ | `6.0` | Auto-cleanup task run interval (hours) |
| `CHAT_CLEANUP_SKIP_PINNED` | ❌ | `true` | Skip pinned sessions during cleanup |
| `ADMIN_API_KEY` | ❌ | — | Separate auth key for the admin panel / `/admin` (empty falls back to `API_KEY`) |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | CORS allowed origins (comma-separated; `*` means all) |
| `CORS_ALLOW_CREDENTIALS` | ❌ | `true` | Whether CORS allows credentials |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | ❌ | `=s2048` | Generated-image download size suffix (`=s0` for full-resolution original) |
| `IMAGE_DOWNLOAD_TIMEOUT` | ❌ | `25.0` | Per-image download HTTP timeout (seconds) |
| `FALLBACK_ENABLED` | ❌ | `false` | Enable Gemini → third-party fallback: when any Gemini model (flash/pro/thinking) errors or returns an empty response, automatically retry natively with a third-party model from the API Key pool |
| `FALLBACK_MODELS` | ❌ | — | Fallback models (comma-separated, tried in order); empty = automatically use all "chat-capable" third-party models in the pool (excludes non-chat models such as image/video/audio/embedding by name) with random round-robin, switching to the next one whenever one fails (errors or empty) |

---

## ⚠ Important Notes

1. **Cookie Expiration**: Google cookies expire periodically (typically hours to days). The service has built-in auto-refresh, but if your account is logged out or password changed, you need new cookies.

2. **Streaming Output**: All API endpoints stream by default. When `stream: false`, the service still receives streaming data internally and returns complete JSON after collection.

3. **Model Availability**: Available models depend on your Google account permissions. Free and Gemini Advanced accounts see different models. The service auto-detects on startup.

4. **Request Frequency**: Even with rate limiting disabled (`RATE_LIMIT_ENABLED=false`), Google has its own limits. High-frequency requests may trigger CAPTCHAs or temporary bans. Control request frequency appropriately.

5. **Network Environment**: The deployment server must have direct access to `gemini.google.com`. Some regions may need proxy configuration.

---

## 🗺 Roadmap

- [x] OpenAI / Claude / Gemini triple format compatibility
- [x] Streaming responses + function calling
- [x] Deep Research multi-step research
- [x] Docker deployment
- [x] API Key authentication
- [x] Cookie hot-update API
- [x] Scheduled account health checks
- [x] Multi-account rotation (load balancing)
- [x] Web management panel
- [x] Anti-detection & protocol spoofing
- [x] Settings page (visual config management)
- [x] API Key management (third-party model keys)
- [x] Unified forwarding engine (single interface for all models)
- [x] Model mapping (alias → actual model)
- [x] Auto-cleanup of accumulated web sessions (periodically delete old sessions, keep pinned)
- [ ] Image/file upload support

---

## ☕ Support & Contribute

Find this helpful? Buy the author a coffee or join the WeChat group for support. For full details, see [SPONSORS.md](SPONSORS.md).

PRs and Issues welcome.

1. Fork this repository
2. Create a branch `git checkout -b feature/your-feature`
3. Commit code `git commit -m "feat: add something"`
4. Push and create a Pull Request

---

## 🙏 Acknowledgments

Thanks to everyone who submitted bug reports, logs, compatibility feedback, and feature suggestions through [Issues](https://github.com/xwteam/gemini2api/issues). Your feedback directly drove the development of Cookie persistence, multi-account rotation, model selection, multi-language support, and the Web panel.

---

## 📄 License

This project uses [Non-Commercial License](../../LICENSE):

- **Allowed**: Personal learning, research, self-hosted deployment
- **Prohibited**: Any commercial use including selling, reselling, paid proxies, commercial product integration

This project is not affiliated with Google. Users assume all risks and must comply with Google's Terms of Service.

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
