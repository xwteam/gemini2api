<div align="center">

<img src="../logo.png" width="128" height="128" alt="Gemini2API">

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
  <a href="#-access-keys">Access Keys</a> &bull;
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

> Showing the 10 most recent updates. For the complete changelog, see [CHANGELOG.md](../../CHANGELOG.md).

| Date | Update |
|------|--------|
| 2026-10-26 23:36:00 | v1.6.49 - 🧩 **Client compatibility fixes**: developer messages sent by Codex and newer OpenAI SDKs (they carry the permission and sandbox rules) used to be dropped entirely on the Gemini path and are now included as system text; top_p, stop, response_format, seed and similar parameters used to be discarded and are now forwarded to third-party models and the fallback; accounts added in the panel and the panel's fallback switch are now stored in the mounted data/ volume, so recreating the container on upgrade no longer loses them; one more canned refusal sentence is recognised |
| 2026-10-26 22:04:00 | v1.6.48 - 🛠️ **Tool calls now work on /v1/responses with third-party models (e.g. from Codex)**: streaming requests (Codex always streams) used to forward only text, so tool calls made by the third-party model were dropped and the tool loop could not run. Streaming and non-streaming responses now turn them into function_call output items. Tool calls and results in the history are also sent to the third party in native OpenAI form (tool_calls + tool_call_id), and built-in tools such as web_search are skipped. The Gemini path is unchanged |
| 2026-10-26 21:14:00 | v1.6.47 - 🙅 **Gemini's canned "language model" refusals are no longer returned as answers**: Google sometimes replies with nothing but a sentence such as "I'm just a language model, so I can't help you with that." (or its Chinese forms), even for easy questions like "is 17 a prime?" and during model outages. It used to be passed through as the answer; now it is handled like the canned failure reply (another account, optional fallback), but it does not count toward the model circuit breaker |
| 2026-10-26 20:26:00 | v1.6.46 - 🩺 **Less waiting when a Gemini model is down**: when Google stalls a model, streaming requests used to hang on an empty heartbeat frame sent every 60 s (we measured a 4-minute wait); they now time out on the same budget as non-streaming requests and drop the connection to free the account at once. Google's canned failure reply (I seem to be encountering an error…) is no longer returned as an answer or saved to the conversation; the request moves to another account or to the fallback instead. New per-model circuit breaker: when a model keeps failing, requests that have a fallback go straight to it instead of waiting a minute or two each time, and Google is probed again automatically |
| 2026-10-26 16:41:00 | v1.6.45 - ⏱️ **Generation timeouts no longer return a plain-text 500**: when Google stalled past the generation budget, clients got a plain-text 500 (unparseable by SDKs, and no fallback); every protocol now returns 504 with `timeout_error`, `/v1/chat/completions` tries the third-party fallback first when it is enabled, and timeouts are neither retried nor held against the account. 💬 **Multi-turn chats really continue the same conversation**: with `conversation_id`, every turn used to open a new conversation and send only the last message, silently losing context in long chats; turns now continue via `[cid, rid, rcid]` pinned to the same account (streaming too) and fall back to the full history whenever that is not possible |
| 2026-10-26 14:01:00 | v1.6.44 - 🔄 **The browser keepalive plugin works again**: accounts whose Google session had been bounced to the login page were still reported as active (only is_healthy turned false), and the plugin only reacts to expired — so it never rescued them, and two production accounts stayed down for about 37 hours. They are now reported as expired and recover the moment new cookies are accepted. 🔁 **No more tug-of-war with the browser**: accounts whose cookies come from the plugin switch to browser keepalive and the server stops rotating them (both sides rotating the same PSIDTS kicked whichever rotated second); accounts updated by hand in the panel are still rotated by the server. Companion plugin v1.3.0 pushes cookies as soon as the browser rotates them |
| 2026-10-21 15:29:00 | v1.6.43 - 🧠 **Thinking now has three levels — low / medium / high — matching the web app**: all four protocols can pick them, **defaulting to `low`** ("Settings → Thinking" in the panel, effective on save; measured at about 5 s extra per request on average — set it to Off if speed matters most); thinking turned on by default for a client that never asked for it is used for generation only and never returned. ⚡ **Claude Code no longer runs every request at the deepest level** (it always sends `adaptive` + `effort: high`, which the previous release hardcoded to high); it now follows the default level, and `/effort low|medium|xhigh|max` finally takes effect; `reasoning_effort: none` means no thinking. 🤖 **Public models trimmed to four**: `gemini-pro` / `gemini-flash` / `gemini-flash-lite` / `gemini-argon`, auto-mapped to the web's 3.1 Pro / 3.8 Flash / 3.5 Flash-Lite / 4 Argon; `gemini-flash-thinking` is retired (the old name still works). 🔌 Third-party forwarding ("API management") fixed — models such as deepseek / glm / kimi behind strict upstreams were all rejected with 400 and misreported as out of quota. 🧪 The model tester now picks a level |
| 2026-10-21 04:30:00 | v1.6.42 - 🤖 **4 Argon is now wired up and model discovery is account-driven**: the account heartbeat already returned the real available-model list, but anything not in the hardcoded table was discarded without so much as a log line — which is exactly why Argon was unusable. Discovered models can now be adopted automatically, so a Google generation change no longer requires a code release. The stable public model names are unchanged; adoption is validated and malformed entries are still dropped, but logged. 💵 **Per-access-key token usage and USD estimates** (statistics only, never a limit; the UI labels them as estimates — this service runs on the web endpoint and costs nothing, and the token count is a character-based approximation). 📄 **Canvas bodies no longer vanish** (previously the answer was a single unopenable placeholder link). 🧼 Control markers such as the `<ctrl94>thought` leak are stripped. 🧠 **Thinking is wired into the Anthropic protocol** (Claude Code's `thinking` parameter used to be silently dropped, locking those users into no-thinking) |
| 2026-10-21 00:58:00 | v1.6.41 - 🔑 New **distributable access keys**: issue as many keys as you like from the panel, each with its own enable/disable, expiry, **lazy activation** (the clock starts on first use, not when you hand it out), request quota, bound accounts and allowed models. The `.env` `API_KEY` stays fully privileged, and access keys can never reach `/admin`. ⚠️ `REFRESH_INTERVAL` default 5→30 min (floor 10): the cookie-rotation loop previously **only ran when startup had failed**, so a normally-started gateway never rotated and its account died within hours (issue #11) — it now starts unconditionally. Gemini's rejection blocks returned with **HTTP 200** are now recognised (session expiry / rate limit / context overflow / CAPTCHA were swallowed as "empty replies", flagging nothing and triggering no self-heal). Non-streaming timeouts are now tiered per model family and no longer retried three times (previously 60s hard cut + retries = 183s before failing). Thinking effort is no longer pinned to maximum. Attachments stream for real again |
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 Fixed the model-test page rendering real errors as "No response content" (issue #11 follow-up): a streaming failure can only be expressed as an in-stream error frame, and the frontend never read that key — so 503/529/500/400 all looked identical. It now shows the real reason and status code, and content already streamed is preserved. Account cards now expose real health info (`is_healthy` / consecutive failures / last success time / a redacted last error) — the green ACTIVE badge reads the pool's status enum, not the client's health flag, so an account with a dead cookie still showed green. Empty responses are no longer silently recorded as success (3 in a row before they count as errors; a single one never downgrades an account). Startup now logs whether the cookie-rotation loop actually started |

---

## 🌟 Core Features

> 📖 Detailed usage guide: [USAGE.md](USAGE.md)

### 🔌 Triple Protocol Compatibility

- Single service provides OpenAI, Claude, and Gemini SDK formats simultaneously
- SSE streaming (OpenAI / Claude) + Chunked JSON (Gemini)
- Function calling supported across all three formats
- Deep Research multi-step research capability
- **Thinking levels**: `low` / `medium` / `high` match the web client's low / medium / high; when the client does not specify a level the default is `low` (set `off` for maximum speed), and when the client does not mention thinking at all, thinking turned on by the default is not returned. See [🧠 Models & Thinking Levels](#-models--thinking-levels)
- **Attachments stream for real again**: requests carrying images or files no longer wait for the full generation before emitting the first token (requests carrying tools stay buffered — tool arguments must be complete JSON before they can be parsed)

### 🧠 Models & Thinking Levels

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

### 🔐 Security & Authentication

- Auto-generated API Keys (`sk-` prefix + 32 random characters)
- Supports both `Authorization: Bearer` and `x-api-key` authentication
- Auto-generated on first deployment, customizable by users
- **Access keys**: the administrator can issue any number of distributable inbound keys, each with its own expiry (including lazy activation that starts counting from first use), request limit, bound accounts and allowed models, and each can be disabled or revoked at any time
- The `API_KEY` in `.env` always keeps full privileges — access keys are an **additional** layer; and an access key can only call the business API, never `/admin/*` (see [🔑 Access Keys](#-access-keys) below)

### 🔄 Multi-Account Load Balancing & Cookie Self-Healing

- **Multi-account load balancing**: Supports round-robin and failover strategies
- Per-account concurrency control prevents single account overload
- Automatic health marking for failed accounts, auto-skip unhealthy ones
- Background cookie rotation for seamless renewal
- Hot-update Cookie API without container restart
- Dynamic account add/remove via API
- Health check history for web panel data support
- **Cookie rotation loop now always runs**: previously the rotation loop was only started when the gateway *failed* to obtain a token at boot, so a normally started gateway never rotated at all and its cookies died after a few hours ([issue #11](https://github.com/xwteam/gemini2api/issues/11)); it is now unconditionally resident
- **Two keep-alive modes, told apart automatically**: accounts whose cookies the browser extension pushes switch to browser keep-alive and the server stops rotating them (both sides rotating the same session knock each other offline); accounts whose Google session was redirected to the login page are now reported as `expired`, so the extension can come to the rescue
- **Reject blocks inside HTTP 200 are now recognized**: Gemini sometimes returns a reject block in the body of a 200 response (rate limit / session expired / context too long / CAPTCHA). Such requests used to surface as an "empty reply" and triggered no self-healing at all; they are now turned into an explicit error that goes through cooldown + account failover, and `BARD_ERROR_CODES` lets you attach a meaning to specific codes
- **Multi-turn `conversation_id` resumes on the same account**: on `/v1/chat/completions`, later turns of a conversation are pinned to the account that served the previous turn and carry the full continuation metadata (`[cid, rid, rcid]`), so the upstream Gemini conversation really continues and only the newest user message is sent (previously the stored continuation had the wrong format and the account was not remembered, so every turn actually opened a new conversation). Streaming requests continue too, as long as the client sends its own `conversation_id`. If that account is unavailable (expired / removed / outside the access key's bound accounts / at capacity), the stored metadata is unusable, the previous turn was answered by the third-party fallback, or the new turn is more than a single user message (for example it carries tool results), the full history is resent as a new conversation instead — context is never silently dropped. With a Gem model, the Gem's bound account wins

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
- **Access keys**: issue / edit / disable / revoke distributable inbound keys, with state, usage and scope shown right in the list (unrelated to "API Key management" below, which manages third-party **outbound** keys)
- **API Key management**: centralized third-party model API Key management (OpenAI/Anthropic/Gemini/OpenRouter/custom), import/export support
- Playground: online API testing
- Real-time logs: structured table display, direction filter, text search, pagination (15 per page), JSON detail panel, disk persistence (survives restart)
- Dark/light theme toggle, responsive mobile adaptation

### 🔀 Unified Forwarding Engine

- Auto-forward requests for models not in Gemini Web's available list to matching Provider from API Key pool
- Direct OpenAI-compatible format forwarding (including streaming), bidirectional Anthropic conversion
- `/openai/v1/models` auto-aggregates Gemini Web models + third-party models from API Key pool
- Single interface, single key to call all major models
- Third-party auto-fallback (`FALLBACK_ENABLED`, off by default): when any Gemini model errors (generation timeouts included) or returns an empty response, automatically retry natively with a third-party model from the API Key pool — transparent to the client, still using just one model name; by default automatically uses all "chat-capable" third-party models in the pool (excludes non-chat models such as image/video), random round-robin, switching to the next on failure; `FALLBACK_MODELS` optionally specifies them precisely

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

To use multiple Google accounts for load balancing, create `data/accounts.json` (inside the mounted volume, so it survives container recreation on upgrade):

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
> Without `data/accounts.json`, the service automatically uses single-account mode from `.env`. You can also dynamically add accounts via `POST /admin/accounts` API at runtime.

### Cookie Auto-Keep-Alive

gemini2api has built-in cookie auto-rotation: it refreshes `__Secure-1PSIDTS` every 30 minutes by default (`REFRESH_INTERVAL`, with a hard floor of 10 minutes) via the Google RotateCookies API, combined with a batchexecute heartbeat to simulate browser activity and extend session lifetime.

> [!IMPORTANT]
> **The default for `REFRESH_INTERVAL` changed from 5 minutes to 30 minutes, and the code now clamps it to a 10-minute floor** (smaller values are raised to 10 and named in the startup log).
> Why: the rotation loop used to be started **only when the gateway failed to obtain a token at boot**, which means a normally started gateway never rotated at all and its cookies died after a few hours ([issue #11](https://github.com/xwteam/gemini2api/issues/11)). Now that the loop is always resident, the same interval would raise background traffic to Google roughly 3.5×, so the interval has to widen to match — rotating too often looks automated to Google and tends to get the session flagged, which kills it faster than not rotating.

To manually update cookies, use the Web panel's "Account Management" → "Update Cookie" without restarting the service.

> [!NOTE]
> Cookie lifetime is affected by Google's risk control policies. Datacenter IPs typically last several hours. If cookies expire frequently, consider using residential IPs or adding more accounts for rotation.

#### Two ways to keep cookies alive: server rotation / browser extension

A Google session can **only be rotated by one side**: when the browser and the server both call RotateCookies, whichever goes second presents an `__Secure-1PSIDTS` the other side has already replaced, gets a 401, and the whole session is logged out (it shows up as "keeps dropping, have to log in again"). So every account uses exactly one of two modes:

- **Server rotation** (default): this service calls RotateCookies every `REFRESH_INTERVAL`. Newly added accounts, and cookies submitted through the panel's "Update Cookie", scripts or curl, all use this mode.
- **Browser keep-alive**: the companion browser extension [**gemini2api-plugin**](https://github.com/xwteam/gemini2api-plugin) runs in your local browser (residential IP); the browser keeps the session alive and the extension pushes the fresh cookies to this service. **An account whose cookies the extension pushed successfully switches to browser keep-alive automatically, and the server stops rotating it** (recognized by the `X-Gemini2API-Keepalive` request header; older extension versions that do not send it are recognized by the `Origin: chrome-extension://…` their requests carry).

More details:

- The panel's account cards show a "Browser keep-alive" tag on such accounts; every account in `GET /admin/status` carries `keepalive_mode` (`server` / `browser`).
- To hand an account back to server rotation (e.g. you switched to cookies taken from an incognito window — nobody rotates them once the window is closed), submit the cookie again through the panel's "Update Cookie".
- A browser-kept account depends on that browser: if it stays closed for long, the cookies expire and the account becomes `expired`.
- The record lives in `data/keepalive-modes.json`, keyed by the first 16 hex characters of the PSID's SHA-256 (the same scheme as the file names under `data/cookies/`); it holds no cookie values. The record follows the PSID: after logging in again (a new PSID) the old record no longer applies, and the new PSID is recorded according to whoever pushes it — still browser keep-alive when the extension pushes it; server rotation when the panel or a script pushes it, or when it is added through the panel's "Add Account" (including re-adding a deleted account with the same cookies).
- The bundled Playwright refresher sidecar (`docker compose --profile refresher`) is itself a browser and sends the same header, so the accounts it pushes are recorded as browser keep-alive too.
- **Bind the Account ID in the extension** ("bind the Account ID this browser owns" at the top of its sidebar). Without it, extension v1.2.3 reloads the Gemini tab in your browser on every poll (every 60 seconds by default) as soon as `/admin/status` lists any `expired` account, and only then matches accounts by PSID — so while an account that does not belong to this browser is expired, the Gemini page you are using keeps being reloaded and whatever you were typing may be lost. Since `expired` now also covers sessions redirected to the login page, this happens more often than before. The same reload loop happens when the browser itself has been logged out; logging in again in the browser fixes it.

> [!NOTE]
> Account status `expired` now also covers "**the Google session was redirected to the login page**" (the cookies are no longer valid). Such accounts used to show `active` with only `is_healthy: false`, so the browser extension never noticed and never came to the rescue. Once the session has been redirected to the login page and Google has answered RotateCookies for these very cookies with a 401, the server (the rotation loop and self-healing alike) stops calling RotateCookies in vain with the same cookies and only keeps probing the session, so a transient glitch still recovers on its own; a session that is merely redirected to the login page and has not been rejected by Google keeps being rotated (a session whose PSIDTS has expired is often rescued by a single rotation); once the extension or the panel supplies fresh cookies the account is back to `active` immediately — no need to click "Check".

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
| POST | `/responses` | OpenAI Responses API (text / streaming / tool calling; used by newer clients like Codex CLI) |

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
| POST | `/settings` | Batch-update config (hot-reloads memory + writes `data/settings-overrides.json`; also writes `.env`) |
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

> The six `/admin/access-keys` endpoints are documented under [🔑 Access Keys](#-access-keys) below.

---

## 🔑 Access Keys

Besides the single all-powerful `API_KEY` in `.env`, the administrator can issue any number of **distributable** access keys: each one gets its own expiry, request limit, usable accounts and allowed models, can be handed to a different person, and can be disabled or revoked individually at any time. The panel has a new "Access Keys" page for managing them visually, backed by the `/admin/access-keys` endpoints.

Keys are stored in `data/access_keys.json` (`data/` is the persistent bind mount used by docker-compose), so they survive restarts.

### Per-key fields

| Field | Description |
|------|------|
| `name` | Label, so you remember who a key was handed to (shown as `key-{id}` when empty) |
| `enabled` | On/off switch. Disabling it 401s the holder immediately, but the key stays in the list and can be re-enabled |
| `expires_at` | Absolute expiry (ISO8601); the key dies at that moment |
| `duration_days` | Valid days, with **lazy activation**: handing the key out starts no clock — the N days begin on the holder's first request |
| `request_limit` | Request cap; the key dies once the cumulative count reaches it ("Reset usage" zeroes it so the key can be reused) |
| `bound_account_ids` | Bound accounts: only the listed Gemini accounts may be used (empty = unrestricted) |
| `allowed_models` | Allowed models: only the listed model names may be called (empty = unrestricted) |

`expires_at` and `duration_days` are mutually exclusive; leave both empty for a key that never expires.

### Key states

| State | Meaning |
|------|------|
| Valid | Usable |
| Disabled | `enabled` was turned off by the administrator |
| Not activated | `duration_days` is set but the key has never been used, so the clock has not started |
| Expired | Past `expires_at` |
| Limit reached | `request_count` reached `request_limit` |

The state is resolved by short-circuiting in this priority order: Disabled → Expired → Limit reached → Not activated → Valid.

### Endpoints

| Method | Endpoint | Function |
|------|------|------|
| GET | `/admin/access-keys` | List all access keys (with state, usage and scope) |
| GET | `/admin/access-keys/options` | Choices for the panel's issue form (accounts in the pool + externally visible model names) |
| POST | `/admin/access-keys` | Issue keys; `count` issues a batch (max 50) |
| PATCH | `/admin/access-keys/{id}` | Change a key's configuration (clearing a field requires the `clear` array, see below) |
| DELETE | `/admin/access-keys/{id}` | Revoke a key |
| POST | `/admin/access-keys/{id}/reset-usage` | Reset the request counter |

```bash
# Issue one key: valid 7 days from first use, at most 500 requests, flash only
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"name":"Alice","duration_days":7,"request_limit":500,"allowed_models":["gemini-flash"]}'

# Issue 20 keys with the same configuration (auto-numbered trial-1 … trial-20)
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"name":"trial","count":20,"duration_days":3}'

# List all keys
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-your-api-key"

# Disable key 3
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"enabled":false}'

# Drop key 3's request cap and model restriction: a JSON null means "leave unchanged",
# so clearing a field requires putting its name in the clear array
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"clear":["request_limit","allowed_models"]}'

# Reset the usage counter
curl -X POST http://localhost:5918/admin/access-keys/3/reset-usage \
  -H "Authorization: Bearer sk-your-api-key"
```

### ⚠ Three boundaries worth knowing

> [!IMPORTANT]
> **1. The `API_KEY` in `.env` still has full privileges.** Access keys are an **additional** layer, not a replacement: a request matching `API_KEY` is let through immediately, without consulting the key store and without counting any usage. **With no access key issued at all, authentication behaves exactly as in previous versions.**
>
> **2. An access key can only call the business API — it can never reach `/admin/*`.** The admin surface is still guarded solely by `API_KEY` / `ADMIN_API_KEY`. That is what makes it safe to hand an access key to an outsider: they cannot read account cookies, cannot change configuration, and cannot see anyone else's keys.
>
> **3. Every business request counts +1, including `GET /v1/models`.** The counter is incremented atomically at the auth entry point; it is monotonic and never refunded (an upstream error still counts). Some clients list the models before every turn, which means **two counts per round** — leave headroom when setting `request_limit`.

---

## ⚙ Configuration

> [!IMPORTANT]
> **Settings changed in the panel take precedence over environment variables.**
> Anything you save on the web panel's Settings page is written to
> `data/settings-overrides.json` (`data/` is the persistent bind mount used by
> docker-compose) and replayed on every startup, **overriding** the corresponding
> environment variable in the table below. This is deliberate: once you turn
> `LOG_BODIES_ENABLED` off in the panel, `docker compose restart` must not turn it
> back on.
>
> So if you **edited `.env`, restarted, and nothing changed**, that field is most
> likely overridden by the panel. The startup log names the affected fields:
> `Applied N panel setting override(s) from data/settings-overrides.json: ...`.
> Delete `data/settings-overrides.json` to hand control back to the environment.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_PSID` | ✅ | — | Browser `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | Browser `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | Auto-generated | API access key (`sk-` prefix, auto-generated on first startup if empty) |
| `REFRESH_INTERVAL` | ❌ | `30` | Cookie refresh interval (minutes, minimum 10) |
| `MAX_RETRIES` | ❌ | `3` | Retry count on failure (exponential backoff) |
| `PORT` | ❌ | `5918` | Service port |
| `LOG_LEVEL` | ❌ | `info` | Log level (debug/info/warning/error) |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | Enable rate limiting |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | Rate limit window (seconds) |
| `RATE_LIMIT_MAX` | ❌ | `10` | Max requests per window |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | Enable scheduled account health checks |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | Check interval (minutes) |
| `ACCOUNTS_FILE` | ❌ | `data/accounts.json` | Multi-account config file path (falls back to single-account mode from env vars if absent). Since v1.6.49 the default lives in the mounted `data/` volume, so accounts added in the panel survive container recreation (upgrades); an `accounts.json` at the old default location is copied over on startup |
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
| `FALLBACK_ENABLED` | ❌ | `false` | Enable Gemini → third-party fallback: when any Gemini model (flash/pro/thinking) errors or returns an empty response, automatically retry natively with a third-party model from the API Key pool (the fallback switch on the panel's API management page is saved to `data/settings-overrides.json`, takes priority over this, and survives upgrades) |
| `FALLBACK_MODELS` | ❌ | — | Fallback models (comma-separated, tried in order); empty = automatically use all "chat-capable" third-party models in the pool (excludes non-chat models such as image/video/audio/embedding by name) with random round-robin, switching to the next one whenever one fails (errors or empty) |
| `DEFAULT_THINKING_LEVEL` | ❌ | `low` | Level used when the client does not specify a level: `off` / `low` / `medium` / `high`. `low` adds about 5 s per request on average (measured), `off` is fastest; switch it live in the panel (Settings → Thinking). When the client does not mention thinking at all, thinking turned on by this default is never returned to the client |
| `EXTENDED_THINKING_ENABLED` | ❌ | `true` | Thinking master switch (advanced/compatibility): `false` = no thinking on any of the four protocols, even when a client explicitly asks |
| `THIRDPARTY_FAILOVER_COOLDOWN` | ❌ | `180` | Cooldown in seconds for a failing third-party provider when several share one model name (0 disables) |
| `BARD_ERROR_CODES` | ❌ | — | Lookup table mapping the codes of reject blocks Gemini returns inside an **HTTP 200** body to a meaning, e.g. `1152=rate_limit,404=session_expired`; categories are `rate_limit` / `session_expired` / `context_too_long` / `captcha`. **While empty, every reject block is treated as unknown (cool down that account + retry on another), which is a deliberate safe fallback**; once configured, each category gets its own handling (session expiry triggers cookie self-healing, context overflow returns 400 without retrying, CAPTCHA releases that account) |
| `GEMINI_FAILURE_REPLIES` | ❌ | — | Extra "generic failure" sentences Google sends instead of an answer (separated by `\|`; the built-in `I seem to be encountering an error. Can I try something else for you?` always applies). An answer that is exactly one of them is handled as an upstream failure (switch account / fallback / 502) instead of being returned as a normal answer; see note 8 |
| `GENERATE_TIMEOUTS` | ❌ | — | Per-model-family override for the generation timeout, e.g. `pro=300,flash=120`; empty uses the built-in tiers (flash-lite 60 / flash 120 / pro 300 / argon 300, with 60 as the fallback for unrecognized families). A non-streaming request is cut at this budget; a streaming request must make its first progress, and each next progress, within it (Google's empty heartbeat frames do not count) |
| `GENERATE_TIMEOUT_IMAGE` | ❌ | `180` | Generation timeout (seconds) for requests that look like image generation. Takes the **larger** of this and the model-family tier, for streaming and non-streaming alike |
| `MODEL_BREAKER_ENABLED` | ❌ | `true` | Master switch of the model outage breaker (see note 7). With `false` the state is still recorded, but Google is never bypassed |
| `MODEL_BREAKER_THRESHOLD` | ❌ | `2` | Open the breaker once this many **different requests** fail in a suspected-outage way on the same model family within the window (account switches, retries and client resends of one request count once) |
| `MODEL_BREAKER_WINDOW` | ❌ | `300` | Counting window (seconds): when a failing attempt started more than this long after the last counted failure, the count restarts at 1 |
| `MODEL_BREAKER_COOLDOWN` | ❌ | `60` | How long the breaker stays open (seconds); meanwhile `/v1/chat/completions` requests with a fallback go straight to the fallback |
| `MODEL_BREAKER_MAX_COOLDOWN` | ❌ | `300` | Cap (seconds) for doubling the open period when probing Google fails again; never below `MODEL_BREAKER_COOLDOWN` |
| `TOKEN_PRICES` | ❌ | — | Price table for the **estimated USD** figure on access-key usage, e.g. `gemini-pro=2.0/12.0,gemini-flash=0.75/3.75` (public model name=input/output price, USD per million tokens). Empty uses the built-in defaults; malformed entries are ignored silently and an unpriced model shows `—` in the panel. **Statistics only — it takes no part in any quota decision**, and it is not a bill (the service uses Gemini Web and costs nothing by itself) |

---

## ⚠ Important Notes

1. **Cookie Expiration**: Google cookies expire periodically (typically hours to days). The service has built-in auto-refresh, but if your account is logged out or password changed, you need new cookies.

2. **Streaming Output**: All API endpoints stream by default. When `stream: false`, the service still receives streaming data internally and returns complete JSON after collection.

3. **Model Availability**: Available models depend on your Google account permissions. Free and Gemini Advanced accounts see different models. The service auto-detects on startup.

4. **Request Frequency**: Even with rate limiting disabled (`RATE_LIMIT_ENABLED=false`), Google has its own limits. High-frequency requests may trigger CAPTCHAs or temporary bans. Control request frequency appropriately.

5. **Network Environment**: The deployment server must have direct access to `gemini.google.com`. Some regions may need proxy configuration.

6. **Non-streaming timeouts and front proxies**: non-streaming (`stream: false`) requests time out per model family — flash-lite 60s, flash 120s, pro and argon 300s (override with `GENERATE_TIMEOUTS`; requests that look like image generation use `GENERATE_TIMEOUT_IMAGE`, default 180s) — and a timeout is no longer retried three times. When the budget runs out the service now answers **504** (error type `timeout_error`, in each protocol's own JSON error body; streaming requests get an in-protocol error event) instead of a plain-text 500, and with `FALLBACK_ENABLED` on, `/v1/chat/completions` tries the third-party fallback first. A timeout means Google stalled, so it does not count toward the account's consecutive failures and never marks the account `expired` (a connect-phase timeout is still retried a few times first; once those retries run out it is handled as a timeout too). Note that the connection emits **zero bytes** for that entire window, so this is a **time-to-first-byte** timeout rather than an idle timeout: **a non-streaming pro request can sit silent for up to 300 seconds, which exceeds the first-byte limit of common front proxies** (15 seconds on the EdgeOne free tier, 60 seconds by default on many reverse proxies), and the client then receives the proxy's 504 instead of this service's error body. Prefer streaming requests for that scenario. Requests with thinking on take a few seconds longer still (the default `low` adds about 5 s per request on average, measured). The 60 s for flash-lite was set for "no thinking, answers in seconds"; with the default level thinking, it may be tight for long prompts or hard questions. Raise it with `GENERATE_TIMEOUTS=flash-lite=120` (a generation-phase timeout is not retried without thinking; it is reported as a timeout). **Streaming requests are bound by the same family budget**: the first progress (new body text, thinking, generated images or Canvas) must arrive within the budget (waiting for the response headers counts too), and so must every next progress; the empty heartbeat frame Google sends every 60 seconds while a request is queued **does not count as progress**. When the budget runs out the client gets the in-protocol `timeout_error` event (with no body text sent yet, `/v1/chat/completions` tries the third-party fallback first). The streaming path used to watch only the 120 s between two received bytes, which Google's heartbeats kept resetting; a client was measured waiting about 240 s.

7. **Model outage breaker**: when a whole Gemini model family fails on Google's side (for example every account's gemini-flash is stuck in Google's queue or instantly returns the generic failure sentence), and `MODEL_BREAKER_THRESHOLD` (default 2) different requests fail on that family in a suspected-outage way within the window (the failure sentence, a generation timeout with almost no data received, a streaming timeout without any progress), the breaker opens for `MODEL_BREAKER_COOLDOWN` (default 60) seconds: `/v1/chat/completions` requests **with `FALLBACK_ENABLED` on and a fallback candidate available** go straight to the third-party fallback instead of first waiting out a whole budget. When the period ends, one real request probes Google; a failed probe doubles the period (capped at `MODEL_BREAKER_MAX_COOLDOWN`), and any success closes the breaker at once. Requests without a fallback and the Claude / Gemini native / Responses protocols always call Google as usual (their results still update the breaker). Only the failing family is affected; the account's other families keep working. The state is shown at the top of the panel's Accounts page and in `model_breakers` of `/admin/status`; it is cleared on restart.

8. **Google's generic failure sentence**: during an outage Gemini sometimes answers within a second with the fixed sentence `I seem to be encountering an error. Can I try something else for you?` instead of an answer. When the whole answer is exactly that sentence (or one added via `GEMINI_FAILURE_REPLIES`), it is handled as an upstream failure (another account is tried, `/v1/chat/completions` may use the fallback, otherwise 502 `api_error`) and it is never returned as a normal answer or saved into the conversation record. Streaming requests hold back an opening that could still grow into that sentence and release it as soon as it diverges (the first few words of an answer may arrive a moment later). Since v1.6.47, Gemini's canned "language model" refusals (e.g. `I'm just a language model, so I can't help you with that.` or the Chinese `我只是一个语言模型，无法提供这方面的帮助。`) are recognised built-in and handled the same way (another account / fallback / 502), but they do not count toward the model circuit breaker, because one particular question can trigger such a refusal every time.

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
- [x] [issues #2](https://github.com/xwteam/gemini2api/issues/2) Custom Gemini Gem support (panel list / create / update / delete + expose as a model name)
- [x] [issues #6](https://github.com/xwteam/gemini2api/issues/6) [#7](https://github.com/xwteam/gemini2api/issues/7) Native Gemini extended thinking (enable via `reasoning_effort`; reasoning streams frame-by-frame before the answer + "Thinking" toggle in the Playground panel + one-click off, never affects normal chat)
- [x] Gemini fallback toggle in API Management (instant on/off with persistence, no .env edit or restart needed)

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
