# 部署指南

本指南涵蓋使用 Docker 部署 gemini2api 的完整步驟，Docker 是生產環境的推薦部署方式。

## 系統要求

| 元件 | 最低要求 | 推薦配置 |
|------|---------|---------|
| Docker | 20.10+ | 最新穩定版 |
| 記憶體 | 512 MB | 2 GB+ |
| 磁碟空間 | 500 MB | 2 GB+ |
| 作業系統 | Linux / macOS / Windows | Linux（效能最佳） |
| 網路 | 能訪問 gemini.google.com | 穩定連線 |

## 取得 Cookie

Gemini2API 需要有效的 Google Gemini Cookie 才能運作。按照以下步驟取得：

### 步驟 1：訪問 Gemini

1. 使用 Chrome 或 Edge 瀏覽器
2. 訪問 [gemini.google.com](https://gemini.google.com)
3. 使用 Google 帳號登入
4. 確認能正常使用 Gemini（發送測試訊息）

### 步驟 2：提取 Cookie

1. 按下 `F12` 開啟開發者工具
2. 點擊頂部 **Application**（應用程式）標籤
3. 左側邊欄展開 **Cookies**
4. 點擊 `https://gemini.google.com`
5. 搜尋以下兩個 Cookie：

| Cookie 名稱 | 說明 |
|-------------|------|
| `__Secure-1PSID` | 以 `g.` 開頭的長字串，通常 50+ 個字元 |
| `__Secure-1PSIDTS` | 較短的字串，通常 20-30 個字元 |

**提示：** 使用搜尋框輸入 `__Secure-1P` 快速篩選。

### 步驟 3：複製數值

1. 雙擊 **Value** 欄位選取完整 Cookie 數值
2. 完整複製每個 Cookie（確保沒有截斷）
3. 安全地儲存以供下一步使用

> **警告：** Cookie 有效期為 2-24 小時，取決於帳號活動和 Google 的政策。如果服務停止運作，請檢查 Cookie 是否已過期並重新整理。

## Docker 部署

### 快速開始（單帳號）

```bash
# 複製倉庫
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 複製環境範本
cp .env.example .env
```

編輯 `.env` 並新增你的 Cookie：

```env
GEMINI_PSID=g.a000xxx...
GEMINI_PSIDTS=sidts-xxx...
API_KEY=sk-your-custom-key
```

**重要事項：**
- 不要在數值周圍加引號
- 移除任何尾部空格或分號
- 確保數值完整（沒有截斷）

啟動服務：

```bash
docker compose up -d
```

檢查日誌確認啟動成功：

```bash
docker compose logs -f
```

查看以下訊息：
- `Account pool ready: 1/1 active` — 服務已就緒
- `SNlM0e not found` — Cookie 無效，需要重新整理

### 多帳號設定（負載均衡）

為了提高吞吐量和冗餘性，可配置多個 Google 帳號：

在專案根目錄建立 `accounts.json`：

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "主帳號"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "備用帳號"
    },
    {
      "id": "account-2",
      "psid": "g.a000zzz...",
      "psidts": "sidts-zzz...",
      "label": "第三帳號"
    }
  ]
}
```

當 `accounts.json` 存在時，服務會使用它而不是 `.env` 認證資訊。你仍可在 `.env` 中配置 `API_KEY`。

**負載均衡策略：**
- `round-robin`（預設）：均勻分配請求到各帳號
- `failover`（故障轉移）：持續使用第一個可用帳號，直到失敗後切換到下一個

在 `.env` 中更改策略：
```env
ROTATION_STRATEGY=failover
```

### 動態帳號管理

無需重啟即可新增或移除帳號：

```bash
# 新增帳號
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new...",
    "label": "新帳號"
  }'

# 移除帳號
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-your-api-key"

# 列出所有帳號
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-your-api-key"
```

## Cookie 更新

Cookie 會定期過期。服務包含自動更新機制，但你也可以手動更新。

### 自動更新

服務每 5 分鐘自動更新一次 Cookie（可透過 `REFRESH_INTERVAL` 配置）。這會大幅延長 Cookie 壽命。

### 透過 Web 面板手動更新

1. 在 `http://localhost:5918` 開啟 Web 面板
2. 使用 API Key 登入
3. 前往 **帳號管理**
4. 點擊帳號的 **更新 Cookie**
5. 貼上新的 Cookie 數值
6. 點擊 **儲存**

無需重啟服務。

### 透過 API 手動更新

```bash
# 更新特定帳號的 Cookie
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new..."
  }'

# 從 .env 檔案重新載入
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-your-api-key"
```

## 驗證

### 健康檢查

```bash
curl http://localhost:5918/health
```

預期回應：
```json
{"status":"ok","service":"gemini2api"}
```

### 列出可用模型

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"
```

### 測試 API 請求

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

你應該收到 AI 的回應。如果收到 401 錯誤，請驗證 API Key 是否正確。

## 常見問題排除

### Cookie 快速過期

**症狀：** 服務運作 1-2 小時後失敗，顯示「SNlM0e not found」

**解決方案：**
1. 手動更新 Cookie（見 Cookie 更新部分）
2. 使用住宅 IP 而非資料中心 IP
3. 新增更多帳號以實現自動故障轉移
4. 增加 `.env` 中的 `REFRESH_INTERVAL`（例如 `REFRESH_INTERVAL=3` 為 3 分鐘更新）

### 連接埠已被佔用

**症狀：** `Error: bind: address already in use`

**解決方案：**
```bash
# 查找使用連接埠 5918 的程序
lsof -i :5918

# 終止程序
kill -9 <PID>

# 或在 docker-compose.yml 中使用不同連接埠
# 將 "5918:5918" 改為 "5919:5918"
```

### 記憶體不足

**症狀：** 容器因 OOM 錯誤崩潰

**解決方案：**
1. 在 `docker-compose.yml` 中增加 Docker 記憶體限制：
   ```yaml
   services:
     gemini2api:
       mem_limit: 4g
   ```
2. 減少 `.env` 中的 `MAX_CONCURRENT_PER_ACCOUNT`（預設：8）
3. 在 `.env` 中啟用速率限制：
   ```env
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_MAX=5
   ```

### 帳號健康檢查失敗

**症狀：** 所有帳號顯示「不健康」狀態

**解決方案：**
1. 驗證 Cookie 有效性（在瀏覽器中測試）
2. 檢查到 gemini.google.com 的網路連線
3. 驗證 API Key 是否正確
4. 檢查日誌：`docker compose logs -f`
5. 透過 Web 面板手動更新 Cookie

### 高延遲或逾時

**症狀：** 請求耗時 30+ 秒或逾時

**解決方案：**
1. 檢查到 gemini.google.com 的網路延遲
2. 減少每帳號的並發請求：
   ```env
   MAX_CONCURRENT_PER_ACCOUNT=1
   ```
3. 在客戶端程式碼中增加請求逾時
4. 使用多帳號進行負載分配

## 配置參考

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `GEMINI_PSID` | — | 必填：`__Secure-1PSID` Cookie |
| `GEMINI_PSIDTS` | — | 必填：`__Secure-1PSIDTS` Cookie |
| `API_KEY` | 自動生成 | API 認證金鑰（sk- 前綴） |
| `REFRESH_INTERVAL` | 5 | Cookie 更新間隔（分鐘） |
| `MAX_RETRIES` | 3 | 失敗請求重試次數 |
| `PORT` | 5918 | 服務連接埠 |
| `LOG_LEVEL` | info | 日誌級別（debug/info/warning/error） |
| `ACCOUNTS_FILE` | accounts.json | 多帳號配置檔案路徑（不存在則使用環境變數單帳號模式） |
| `ROTATION_STRATEGY` | round-robin | 負載均衡：round-robin 或 failover |
| `MAX_CONCURRENT_PER_ACCOUNT` | 8 | 每帳號最大並發請求數 |
| `ACQUIRE_TIMEOUT` | 60.0 | 並發滿載時排隊等待可用槽位的上限（秒），等不到才報錯 |
| `SAME_ACCOUNT_5XX_RETRIES` | 1 | 遇 5xx 時同帳號快速重試次數（不長退避），仍失敗則 failover 換號 |
| `FAILOVER_COOLDOWN` | 30.0 | 被 5xx 限流的帳號進入冷卻的時長（秒），期間不優先選 |
| `HEALTH_CHECK_ENABLED` | true | 啟用定期帳號健康檢查 |
| `HEALTH_CHECK_INTERVAL` | 5 | 健康檢查間隔（分鐘） |
| `RATE_LIMIT_ENABLED` | false | 啟用請求速率限制 |
| `RATE_LIMIT_WINDOW` | 60 | 速率限制視窗（秒） |
| `RATE_LIMIT_MAX` | 10 | 每視窗最大請求數 |
| `FINGERPRINT_CONFIG_PATH` | data/fingerprint.json | 指紋配置檔案路徑 |
| `VERSION_SYNC_ENABLED` | true | 啟用 Chrome 版本自動同步 |
| `VERSION_SYNC_INTERVAL` | 24 | 版本同步間隔（小時） |
| `JITTER_ENABLED` | true | 啟用請求時間抖動（模擬人類行為） |
| `USAGE_STATS_ENABLED` | true | 啟用用量統計（時序快照 + 持久化） |
| `USAGE_STATS_INTERVAL` | 300 | 快照採集間隔（秒） |
| `USAGE_STATS_RETENTION_DAYS` | 30 | 歷史數據保留天數 |
| `MODEL_WHITELIST` | — | 模型白名單（逗號分隔，為空則不過濾；非空時過濾各 `/models` 列表） |
| `CHAT_CLEANUP_ENABLED` | true | 啟用 Gemini 網頁端會話自動清理 |
| `CHAT_CLEANUP_KEEP_HOURS` | 24.0 | 網頁會話保留時長（小時），超過則清理 |
| `CHAT_CLEANUP_INTERVAL_HOURS` | 6.0 | 自動清理任務運行間隔（小時） |
| `CHAT_CLEANUP_SKIP_PINNED` | true | 清理時跳過置頂會話 |
| `ADMIN_API_KEY` | — | 管理面板/`/admin` 獨立鑑權 key（留空則回退用 `API_KEY`） |
| `CORS_ALLOW_ORIGINS` | * | CORS 允許來源（逗號分隔，`*` 表示全部） |
| `CORS_ALLOW_CREDENTIALS` | true | CORS 是否允許攜帶憑據 |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | =s2048 | 生圖代下載尺寸後綴（`=s0` 為全解析度原圖） |
| `IMAGE_DOWNLOAD_TIMEOUT` | 25.0 | 單次圖片下載 HTTP 超時（秒） |

## Docker Compose 參考

關鍵卷及其用途：

```yaml
volumes:
  - ./data:/app/data           # 持久化資料（Cookie、日誌、統計）
  - ./api:/app/api             # 熱重載資源（二維碼、公告）
  - /etc/localtime:/etc/localtime:ro  # 系統時區
```

在 `docker-compose.yml` 中修改時區：
```yaml
environment:
  - TZ=Asia/Taipei  # 改為你的時區
```

## 後續步驟

- 閱讀 [USAGE.md](USAGE.md) 了解 Web 面板和客戶端整合
- 閱讀 [API.md](API.md) 查看詳細的 API 端點文檔
- 查看 [README.md](../../README.md) 了解架構和進階功能
