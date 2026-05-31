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
| 2026-05-31 17:00:00 | v1.6.4 - All three APIs expose standard bare paths (/v1/chat/completions, /v1/messages, /v1beta/...) — major SDKs work out of the box; fixed deployment mechanism (docker-compose switched from build to image, so docker compose pull actually takes effect) |
| 2026-05-31 14:10:00 | v1.6.3 - Image/file upload support (OpenAI/Claude/Gemini multimodal); models now use real web data + stable fixed names (gemini-pro/flash/flash-thinking); cookies no longer lost on restart |
| 2026-05-19 20:00:00 | v1.6.2 - Session auto-expires and logs out after 5 minutes of inactivity |
| 2025-05-18 16:30:00 | v1.6.1 - Dark theme comprehensive fixes, update check dialog beautification, GitHub Actions auto-build images, failover strategy |
| 2025-05-17 23:20:00 | Unified model list to user-friendly names, added thinking mode (gemini-2.5-flash-thinking) and Pro mode, fixed Playground conversation context |
| 2025-05-17 22:30:00 | Fixed container timezone to Asia/Shanghai, logs show Beijing time |

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

| Method | Endpoint | Function |
|--------|----------|----------|
| GET | `/status` | Service status (account pool overview + rotation strategy) |
| GET | `/accounts` | All accounts list and status |
| POST | `/accounts` | Dynamically add new account |
| DELETE | `/accounts/{id}` | Remove account |
| GET | `/accounts/{id}/check` | Check single account status |
| POST | `/reload-cookies` | Hot-update cookies (no container restart) |

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
| `ROTATION_STRATEGY` | ❌ | `round-robin` | Rotation strategy: `round-robin` / `failover` |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | Max concurrent requests per account |

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
