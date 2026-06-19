# Deployment Guide

This guide covers deploying gemini2api using Docker, the recommended method for production environments.

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Docker | 20.10+ | Latest stable |
| RAM | 512 MB | 2 GB+ |
| Disk | 500 MB | 2 GB+ |
| OS | Linux / macOS / Windows | Linux (best performance) |
| Network | Direct access to gemini.google.com | Stable connection |

## Getting Cookies

Gemini2API requires valid Google Gemini cookies to function. Follow these steps to obtain them:

### Step 1: Access Gemini

1. Open Chrome or Edge browser
2. Visit [gemini.google.com](https://gemini.google.com)
3. Log in with your Google account
4. Verify you can use Gemini normally (send a test message)

### Step 2: Extract Cookies

1. Press `F12` to open Developer Tools
2. Click the **Application** tab (top menu)
3. In the left sidebar, expand **Cookies**
4. Click `https://gemini.google.com`
5. Search for these two cookies:

| Cookie Name | Description |
|-------------|-------------|
| `__Secure-1PSID` | Long string starting with `g.`, typically 50+ characters |
| `__Secure-1PSIDTS` | Shorter string, typically 20-30 characters |

**Tip:** Use the search box to filter by `__Secure-1P` for quick access.

### Step 3: Copy Values

1. Double-click the **Value** column to select the full cookie value
2. Copy each cookie completely (ensure no truncation)
3. Store them securely for the next step

> **Warning:** Cookies expire after 2-24 hours depending on account activity and Google's policies. If the service stops working, check if cookies have expired and refresh them.

## Docker Deployment

### Quick Start (Single Account)

```bash
# Clone the repository
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# Copy environment template
cp .env.example .env
```

Edit `.env` and add your cookies:

```env
GEMINI_PSID=g.a000xxx...
GEMINI_PSIDTS=sidts-xxx...
API_KEY=sk-your-custom-key
```

**Important notes:**
- Do not add quotes around values
- Remove any trailing spaces or semicolons
- Ensure values are complete (no truncation)

Start the service:

```bash
docker compose up -d
```

Check logs to confirm startup:

```bash
docker compose logs -f
```

Look for these messages:
- `Account pool ready: 1/1 active` — Service is ready
- `SNlM0e not found` — Cookie is invalid, refresh it

### Multi-Account Setup (Load Balancing)

For higher throughput and redundancy, configure multiple Google accounts:

Create `accounts.json` in the project root:

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "Primary Account"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "Secondary Account"
    },
    {
      "id": "account-2",
      "psid": "g.a000zzz...",
      "psidts": "sidts-zzz...",
      "label": "Tertiary Account"
    }
  ]
}
```

When `accounts.json` exists, the service uses it instead of `.env` credentials. You can still configure `API_KEY` in `.env`.

**Load Balancing Strategies:**
- `round-robin` (default): Distributes requests evenly across accounts
- `failover`: Uses the first available account until it fails, then switches to the next

Change strategy in `.env`:
```env
ROTATION_STRATEGY=failover
```

### Dynamic Account Management

Add or remove accounts without restarting:

```bash
# Add a new account
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new...",
    "label": "New Account"
  }'

# Remove an account
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-your-api-key"

# List all accounts
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-your-api-key"
```

## Cookie Refresh

Cookies expire periodically. The service includes automatic refresh mechanisms, but you can also update them manually.

### Automatic Refresh

The service automatically refreshes cookies every 5 minutes (configurable via `REFRESH_INTERVAL`). This extends cookie lifetime significantly.

### Manual Refresh via Web Panel

1. Open the web panel at `http://localhost:5918`
2. Log in with your API Key
3. Go to **Account Management**
4. Click **Update Cookies** for the account
5. Paste new cookie values
6. Click **Save**

No restart required.

### Manual Refresh via API

```bash
# Update specific account cookies
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new..."
  }'

# Reload from .env file
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-your-api-key"
```

## Verification

### Health Check

```bash
curl http://localhost:5918/health
```

Expected response:
```json
{"status":"ok","service":"gemini2api"}
```

### List Available Models

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

### Test API Request

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

You should receive an AI response. If you get a 401 error, verify your API Key is correct.

## Troubleshooting

### Cookie Expires Quickly

**Symptom:** Service works for 1-2 hours then fails with "SNlM0e not found"

**Solutions:**
1. Refresh cookies manually (see Cookie Refresh section)
2. Use residential IP instead of data center IP
3. Add more accounts for automatic failover
4. Increase `REFRESH_INTERVAL` in `.env` (e.g., `REFRESH_INTERVAL=3` for 3-minute refresh)

### Port Already in Use

**Symptom:** `Error: bind: address already in use`

**Solutions:**
```bash
# Find process using port 5918
lsof -i :5918

# Kill the process
kill -9 <PID>

# Or use a different port in docker-compose.yml
# Change "5918:5918" to "5919:5918"
```

### Out of Memory

**Symptom:** Container crashes with OOM error

**Solutions:**
1. Increase Docker memory limit in `docker-compose.yml`:
   ```yaml
   services:
     gemini2api:
       mem_limit: 4g
   ```
2. Reduce `MAX_CONCURRENT_PER_ACCOUNT` in `.env` (default: 8)
3. Enable rate limiting in `.env`:
   ```env
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_MAX=5
   ```

### Account Health Check Failures

**Symptom:** All accounts show "unhealthy" status

**Solutions:**
1. Verify cookies are valid (test in browser)
2. Check network connectivity to gemini.google.com
3. Verify API Key is correct
4. Check logs: `docker compose logs -f`
5. Manually refresh cookies via Web Panel

### High Latency or Timeouts

**Symptom:** Requests take 30+ seconds or timeout

**Solutions:**
1. Check network latency to gemini.google.com
2. Reduce concurrent requests per account:
   ```env
   MAX_CONCURRENT_PER_ACCOUNT=1
   ```
3. Increase request timeout in client code
4. Use multiple accounts for load distribution

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_PSID` | — | Required: `__Secure-1PSID` cookie |
| `GEMINI_PSIDTS` | — | Required: `__Secure-1PSIDTS` cookie |
| `API_KEY` | Auto-generated | API authentication key (sk- prefix) |
| `REFRESH_INTERVAL` | 5 | Cookie refresh interval (minutes) |
| `MAX_RETRIES` | 3 | Failed request retry attempts |
| `PORT` | 5918 | Service port |
| `LOG_LEVEL` | info | Logging level (debug/info/warning/error) |
| `ACCOUNTS_FILE` | accounts.json | Multi-account config file path (falls back to single-account env mode if absent) |
| `ROTATION_STRATEGY` | round-robin | Load balancing: round-robin or failover |
| `MAX_CONCURRENT_PER_ACCOUNT` | 8 | Max concurrent requests per account |
| `ACQUIRE_TIMEOUT` | 60.0 | Max seconds to queue for a free slot at full concurrency before erroring |
| `SAME_ACCOUNT_5XX_RETRIES` | 1 | Quick same-account retries on 5xx (no long backoff); failover if still failing |
| `FAILOVER_COOLDOWN` | 30.0 | Cooldown (seconds) for an account rate-limited by 5xx, during which it is not preferred |
| `HEALTH_CHECK_ENABLED` | true | Enable periodic account health checks |
| `HEALTH_CHECK_INTERVAL` | 5 | Health check interval (minutes) |
| `RATE_LIMIT_ENABLED` | false | Enable request rate limiting |
| `RATE_LIMIT_WINDOW` | 60 | Rate limit window (seconds) |
| `RATE_LIMIT_MAX` | 10 | Max requests per window |
| `FINGERPRINT_CONFIG_PATH` | data/fingerprint.json | Fingerprint config file path |
| `VERSION_SYNC_ENABLED` | true | Enable Chrome version auto-sync |
| `VERSION_SYNC_INTERVAL` | 24 | Version sync interval (hours) |
| `JITTER_ENABLED` | true | Enable request time jitter (simulate human behavior) |
| `USAGE_STATS_ENABLED` | true | Enable usage statistics (time-series snapshots + persistence) |
| `USAGE_STATS_INTERVAL` | 300 | Snapshot collection interval (seconds) |
| `USAGE_STATS_RETENTION_DAYS` | 30 | Historical data retention (days) |
| `MODEL_WHITELIST` | — | Model whitelist (comma-separated; empty = no filtering; when set, filters each `/models` list) |
| `CHAT_CLEANUP_ENABLED` | true | Enable auto-cleanup of Gemini web sessions |
| `CHAT_CLEANUP_KEEP_HOURS` | 24.0 | Web session retention (hours); older ones are cleaned up |
| `CHAT_CLEANUP_INTERVAL_HOURS` | 6.0 | Auto-cleanup task run interval (hours) |
| `CHAT_CLEANUP_SKIP_PINNED` | true | Skip pinned sessions during cleanup |
| `ADMIN_API_KEY` | — | Separate auth key for the admin panel / `/admin` (empty falls back to `API_KEY`) |
| `CORS_ALLOW_ORIGINS` | * | CORS allowed origins (comma-separated; `*` means all) |
| `CORS_ALLOW_CREDENTIALS` | true | Whether CORS allows credentials |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | =s2048 | Generated-image download size suffix (`=s0` for full-resolution original) |
| `IMAGE_DOWNLOAD_TIMEOUT` | 25.0 | Per-image download HTTP timeout (seconds) |

## Docker Compose Reference

Key volumes and their purposes:

```yaml
volumes:
  - ./data:/app/data           # Persistent data (cookies, logs, stats)
  - ./api:/app/api             # Hot-reload resources (QR codes, announcements)
  - /etc/localtime:/etc/localtime:ro  # System timezone
```

Modify timezone in `docker-compose.yml`:
```yaml
environment:
  - TZ=America/New_York  # Change to your timezone
```

## Next Steps

- Read [USAGE.md](USAGE.md) to learn about the web panel and client integration
- Read [API.md](API.md) for detailed API endpoint documentation
- Check [README.md](../../README.md) for architecture and advanced features
