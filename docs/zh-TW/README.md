<div align="center">

<h1>Gemini2API</h1>
<h3>輕量級 Gemini Web 反向代理</h3>
<p>一套程式碼相容 OpenAI / Claude / Gemini 三大主流 AI SDK，純非同步架構，零官方 Key，Docker 快速部署。</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/curl__cffi-Chrome%20TLS-ff6b35?style=flat-square&logo=google-chrome&logoColor=white" alt="curl_cffi">
  <img src="https://img.shields.io/badge/Docker-20.10+-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Chrome%20%7C%20Edge-Latest-4285F4?style=flat-square&logo=googlechrome&logoColor=white" alt="Browser">
  <img src="https://img.shields.io/badge/License-Non--Commercial-red?style=flat-square" alt="License">
</p>

<p>
  <a href="#-最近更新">最近更新</a> &bull;
  <a href="#-核心功能">核心功能</a> &bull;
  <a href="#-系統需求">系統需求</a> &bull;
  <a href="#-快速部署">快速部署</a> &bull;
  <a href="#-接入範例">接入範例</a> &bull;
  <a href="#-api-端點">API 端點</a> &bull;
  <a href="#-設定說明">設定說明</a> &bull;
  <a href="#-注意事項">注意事項</a> &bull;
  <a href="#-開發路線">開發路線</a>
</p>

<p>
  📖 文件語言：<a href="../zh-CN/README.md">簡體中文</a> | 繁體中文 | <a href="../en/README.md">English</a> | <a href="../ja/README.md">日本語</a> | <a href="../ko/README.md">한국어</a>
</p>

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> 本專案僅供研究和學習用途，請合理使用，不要用於任何商業目的。

> [!WARNING]
> 本專案與 Google 無關。專案透過逆向工程取得的瀏覽器 Cookie 實現功能，可能不符合 Google 服務條款。使用風險自負，作者不對任何帳號處罰或資料遺失承擔責任。

> [!TIP]
> 建議搭配 Gemini Pro 及以上訂閱使用，以取得更完整的模型存取權限和更穩定的體驗。

> [!IMPORTANT]
> 由於 Google 風控策略限制，Cookie 會話目前約 2 小時後會被強制失效，暫未找到完美的長期保活方案。如果您在這方面有經驗或思路，非常歡迎透過 [Issue](https://github.com/xwteam/gemini2api/issues) 或 PR 分享，期待社群的智慧。

---

## 📝 最近更新

> 完整更新日誌請查看 [CHANGELOG.md](../../CHANGELOG.md)，以下內容由 CI 自動同步。

| 日期 | 更新內容 |
|------|----------|
| 2026-06-02 16:37:57 | v1.6.12 - 🛠️ 修復 agent（如 Hermes）帶 tools 時生圖被壓制、工具呼叫畸形 JSON 透傳：偵測到生圖意圖自動跳過工具模擬直接出圖；工具呼叫多層容錯解析（剝離 markdown/提取 JSON/容忍畸形），畸形不再透傳；Gemini 原生介面工具呼叫正確回傳 functionCall |
| 2026-06-02 13:04:39 | v1.6.11 - 🔁 503 智慧 failover：Google 對資料中心 IP 間歇性 503 限流時，多帳號自動切換到下一個可用帳號重試（一個被限流立刻換號），被限流帳號進入 30s 冷卻但不標記失效；單帳號 5xx 只快速重試不長退避空耗 |
| 2026-06-01 20:21:43 | v1.6.10 - ⚡ 真串流輸出：三家介面改為真正的增量串流（首字一生成就推送，不再等整段生成完才假裝逐字吐），聊天體感大幅提升；🚀 並行大幅提升：單帳號並行 3→8，且滿載時排隊等待而非直接報錯 No available accounts，agent 不再一並行就失敗 |
| 2026-06-01 00:32:16 | v1.6.9 - 🖼️ 生成圖片回傳全解析度原圖：之前下載的是壓縮縮圖（512px），現加 =s0 後綴取原始尺寸（如 1408×768） |
| 2026-06-01 00:18:01 | v1.6.8 - 🖼️ 生圖不再回傳 googleusercontent 佔位網址：該佔位 URL 無實際意義，已從回覆中過濾，生圖只回傳圖片本身 |
| 2026-06-01 00:02:09 | v1.6.7 - 🖼️ 修復控制面板模型測試不顯示圖片：生成的圖片現在直接渲染顯示，不再顯示成 markdown 文字/URL |
| 2026-05-31 23:41:15 | v1.6.6 - 🖼️ 生成圖片本機託管：對話介面的生圖結果改為回傳可存取的本機 URL（/images/{id}），讓 CLI/agent 用戶端也能正常渲染顯示（base64 在這類用戶端無法顯示）；圖片定期自動清理 |
| 2026-05-31 22:36:53 | v1.6.5 - 🎨 AI 生成圖片：新增 OpenAI 相容 /v1/images/generations 介面（回傳 b64_json）；三家對話介面偵測到生成圖片自動嵌入回覆（markdown / image block / inlineData） |
| 2026-05-31 17:00:00 | v1.6.4 - 三家介面暴露標準裸路徑（/v1/chat/completions、/v1/messages、/v1beta/...），主流 SDK 開箱即用；修復部署機制（docker-compose 由 build 改 image，docker compose pull 真正生效） |
| 2026-05-31 14:10:00 | v1.6.3 - 圖片/檔案上傳支援（OpenAI/Claude/Gemini 多模態）；模型改用網頁版真實資料 + 對外固定穩定名（gemini-pro/flash/flash-thinking）；重啟不再遺失 Cookie |
| 2026-05-19 20:00:00 | v1.6.2 - 工作階段 5 分鐘無操作自動過期登出 |
| 2025-05-18 16:30:00 | v1.6.1 - 深色主題全面修復、檢查更新彈窗美化、GitHub Actions 自動建置映像、failover 故障轉移策略 |
| 2025-05-17 23:20:00 | 模型列表統一為使用者友善名稱，新增思考模式（gemini-2.5-flash-thinking）和 Pro 模式，Playground 對話上下文修復 |
| 2025-05-17 22:30:00 | 容器時區修正為 Asia/Shanghai，日誌顯示北京時間 |

---

## 🌟 核心功能

> 📖 詳細使用文件：[USAGE.md](USAGE.md)

### 🔌 三合一協議相容

- 一個服務同時提供 OpenAI、Claude、Gemini 三種 SDK 格式
- SSE 流式輸出（OpenAI / Claude）+ Chunked JSON（Gemini）
- 函數呼叫（Function Calling）三種格式均支援
- Deep Research 多步驟深度研究

### 🔐 安全與認證

- API Key 自動生成（`sk-` 前綴 + 32 位隨機字元）
- 支援 `Authorization: Bearer` 和 `x-api-key` 兩種認證方式
- 首次部署自動生成密鑰，使用者可自訂修改

### 🔄 多帳號輪詢與 Cookie 自癒

- **多帳號負載均衡**：支援 round-robin（輪詢）和 failover（故障轉移）兩種策略
- 每帳號獨立並行控制，避免單帳號過載
- 連續失敗自動標記不健康，自動跳過故障帳號
- 後台自動輪換 Cookie，無感續期
- 熱更新 Cookie API，無需重啟容器
- 支援透過 API 動態新增/移除帳號
- 健康檢查歷史記錄，為 Web 面板提供資料支撐

### 🛡 反檢測與協議偽裝

- **TLS 指紋一致性**：UA、Sec-Ch-Ua、curl_cffi impersonate 三者版本始終同步（目前 Chrome 124）
- **動態請求頭**：按 Chrome 真實順序排列，根據請求類型（導航 GET / API POST）動態調整 Sec-Fetch-* 值
- **完整 Cookie 持久化**：自動捕獲所有回應 Cookie 並持久化到磁碟，跨重啟保留
- **Cookie 網域隔離**：每次請求前清除 session 內部 cookie，防止跨網域累積衝突
- **Chrome 版本自動同步**：每 24 小時輪詢 Google 版本 API，偵測到新版本自動更新指紋設定
- **請求時間抖動**：模擬人類操作間隔（導航 200-800ms / API 50-300ms / Cookie 輪換 1-3s）
- **版本降級策略**：當 curl_cffi 不支援最新 Chrome 版本時，自動使用最近的可用版本

### 🖥 Web 管理面板

- 中文可視化管理介面，API Key 登入認證
- 右上角控制欄：主題切換、服務重啟、登出
- 儀表板：執行時間實時計時、二維碼卡片（支援圖片放大）、系統資訊（版本/Python/OS/記憶體/CPU/PID/執行模式）、設定管理（輪換策略/並行上限）、帳號狀態總覽、可用模型列表
- **熱更新資源**：`api/` 目錄 volume 掛載，二維碼圖片和文字設定修改後重新整理頁面即生效，無需重建容器
- 帳號管理：新增/刪除帳號、單獨更新 Cookie、健康檢測
- **設定頁面**：可視化管理執行時設定（效能、速率限制、健康檢查、帳號管理等），修改即時生效並傳播到執行時
- **模型對應**：將請求中的模型名對應到實際使用的模型（如 gpt-4o → gemini-2.5-pro）
- **API Key 管理**：集中管理第三方大模型 API Key（OpenAI/Anthropic/Gemini/OpenRouter/自訂），支援匯入匯出
- Playground：線上測試 API 請求
- 實時日誌：結構化表格展示，支援方向過濾、文字搜尋、分頁（每頁15條）、JSON 詳情面板，日誌持久化到磁碟（重啟不遺失）
- 深色/淺色主題切換，回應式行動端適配

### 🔀 統一轉發引擎

- 請求模型不在 Gemini Web 可用列表時，自動從 API Key 池比對並轉發到對應 Provider
- OpenAI 相容格式直接轉發（含流式），Anthropic 格式雙向轉換
- `/openai/v1/models` 自動聚合 Gemini Web 模型 + API Key 池中的第三方模型
- 一個介面、一個 Key 呼叫所有大模型

### ⚡ 高效能架構

- 基於 Python asyncio + curl_cffi，全鏈路非阻塞
- Chrome TLS 指紋偽裝 + 版本自動跟進，session 存活時間大幅延長
- Pydantic 強型別驗證，請求參數自動驗證
- 模組化設計，每個 API 格式獨立路由檔案
- 失敗自動重試，指數退避策略

---

## 📋 系統需求

| 依賴 | 版本 | 說明 |
|------|------|------|
| Python | 3.12+ | 推薦 3.12，低版本未測試 |
| Docker | 20.10+ | 可選，推薦使用 Docker 部署 |
| Google 帳號 | — | 需能正常存取 [gemini.google.com](https://gemini.google.com) |
| 瀏覽器 | Chrome / Edge | 用於取得 Cookie（僅部署時需要） |

> [!TIP]
> 使用 Docker 部署無需本地安裝 Python 環境，只需 Docker 和有效的 Cookie 即可。

---

## ⚡ 快速部署

> 📖 詳細部署文件：[DEPLOY.md](DEPLOY.md)

> **前置條件**：你需要一個能正常使用 Gemini 的 Google 帳號。

### 1. 取得 Cookie

1. 使用 Chrome 或 Edge 瀏覽器存取 [gemini.google.com](https://gemini.google.com)
2. 登入你的 Google 帳號，確保能正常使用 Gemini 對話
3. 按 `F12` 開啟開發者工具
4. 點擊頂部 **Application**（應用程式）標籤
5. 左側欄找到 **Cookies** -> 點擊 `https://gemini.google.com`
6. 在 Cookie 列表中找到以下兩個值：

| Cookie 名稱 | 說明 |
|-------------|------|
| `__Secure-1PSID` | 以 `g.` 開頭的長字元，通常幾十個字元 |
| `__Secure-1PSIDTS` | 較短的字元 |

7. 建議在無痕模式下操作，取得到所需值後立即關閉視窗，避免頁面重新整理導致 Cookie 輪換失效

> [!TIP]
> 可以在搜尋框中輸入 `__Secure-1P` 快速過濾。雙擊 Value 欄即可複製完整值。

> [!WARNING]
> Cookie 有有效期，過期後需要重新取得。如果服務突然無法使用，優先檢查 Cookie 是否失效。

### 2. Docker 部署

```bash
# 複製倉庫
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 建立環境變數檔案
cp .env.example .env
```

編輯 `.env` 檔案，填入你的 Cookie：

```env
GEMINI_PSID=g.a000xxx...（貼上你的 __Secure-1PSID 完整值）
GEMINI_PSIDTS=sidts-xxx...（貼上你的 __Secure-1PSIDTS 完整值）
```

> [!IMPORTANT]
> 注意事項：
> - 值不需要加引號
> - 不要有多餘的空格或換行
> - 確保複製的是完整值，不要遺漏末尾字元

啟動服務：

```bash
docker compose up -d
```

查看日誌確認啟動成功：

```bash
docker compose logs -f
# 看到 "Account pool ready: 1/1 active" 表示帳號池就緒
# 看到 "SNlM0e not found" 表示 Cookie 無效，需要重新取得
```

### 多帳號設定（可選）

如需使用多個 Google 帳號實現負載均衡，建立 `accounts.json`：

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
    }
  ]
}
```

> [!TIP]
> 不建立 `accounts.json` 時，服務自動使用 `.env` 中的單帳號模式。也可以透過 `POST /admin/accounts` API 在執行時動態新增帳號。

### Cookie 自動保活

gemini2api 內置 Cookie 自動輪換機制：每 5 分鐘透過 Google RotateCookies API 重新整理 `__Secure-1PSIDTS`，配合 batchexecute 心跳模擬瀏覽器活躍行為，延長 session 壽命。

如需手動更新 Cookie，可透過 Web 面板的「帳號管理」→「更新 Cookie」操作，無需重啟服務。

> [!NOTE]
> Cookie 壽命受 Google 風控策略影響，資料中心 IP 通常可維持數小時。如 Cookie 頻繁過期，建議使用住宅 IP 或增加帳號數量做輪詢。

### 3. 驗證

```bash
# 健康檢查
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# 查看可用模型（需要 API Key，首次啟動在日誌中查看）
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-你的API密鑰"

# 傳送測試請求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密鑰" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

看到 AI 回覆的文字即部署成功。如果傳回 401，請檢查 API Key 是否正確。

---

## 🧪 接入範例

> [!NOTE]
> 所有 API 請求都需要攜帶 API Key。支援兩種方式：
> - `Authorization: Bearer sk-xxx`（推薦，相容 OpenAI/Claude SDK）
> - `x-api-key: sk-xxx`
>
> API Key 在首次啟動時自動生成並寫入 `.env` 檔案，可在日誌中查看或手動修改。

<details>
<summary><b>OpenAI SDK（Python）</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密鑰",
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "用三句話解釋相對論"}],
    stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

</details>

<details>
<summary><b>Claude SDK（Python）</b></summary>

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-你的API密鑰",
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "寫一個快速排序的Python實現"}]
)
print(msg.content[0].text)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
# 非流式請求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密鑰" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}]}'

# 流式請求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密鑰" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

</details>

<details>
<summary><b>函數呼叫</b></summary>

```python
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "北京今天天氣怎麼樣"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "取得指定城市的天氣",
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

## 📡 API 端點

> 📖 詳細 API 文件：[API.md](API.md)

### OpenAI 相容（`/openai/v1`）

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/models` | 可用模型列表 |
| POST | `/chat/completions` | 對話補全（支援流式 + 工具呼叫） |

### Claude 相容（`/claude/v1`）

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表 |
| GET | `/models/{id}` | 模型詳情 |
| POST | `/messages` | 訊息生成（支援流式 + 工具呼叫） |
| POST | `/messages/count_tokens` | Token 計數估算 |

### Gemini 原生（`/gemini/v1beta`）

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表 |
| POST | `/models/{m}:generateContent` | 內容生成 |
| POST | `/models/{m}:streamGenerateContent` | 流式生成（Chunked JSON） |

### 管理介面（`/admin`）

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/status` | 服務狀態（帳號池概覽 + 輪詢策略） |
| GET | `/accounts` | 所有帳號列表及狀態 |
| POST | `/accounts` | 動態新增新帳號 |
| DELETE | `/accounts/{id}` | 移除指定帳號 |
| GET | `/accounts/{id}/check` | 檢測單個帳號狀態 |
| POST | `/reload-cookies` | 熱更新 Cookie（無需重啟容器） |

---

## ⚙ 設定說明

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 瀏覽器 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 瀏覽器 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自動生成 | API 存取密鑰（`sk-` 開頭，留空則首次啟動自動生成） |
| `REFRESH_INTERVAL` | ❌ | `5` | Cookie 重新整理週期（分鐘） |
| `MAX_RETRIES` | ❌ | `3` | 失敗重試次數（指數退避） |
| `PORT` | ❌ | `5918` | 服務連接埠 |
| `LOG_LEVEL` | ❌ | `info` | 日誌級別（debug/info/warning/error） |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | 啟用限流 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 限流視窗（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | 視窗內最大請求數 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | 啟用定時帳號狀態檢測 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | 檢測間隔（分鐘） |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 輪詢策略：`round-robin`（輪詢）/ `failover`（故障轉移） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | 每帳號最大並行請求數 |

---

## ⚠ 注意事項

1. **Cookie 有效期**：Google Cookie 會定期過期（通常數小時到數天不等）。服務內置自動重新整理機制，但如果帳號被登出或密碼變更，需要重新取得 Cookie。

2. **流式輸出**：所有 API 端點預設流式傳回。設定 `stream: false` 時，服務內部仍以流式方式接收資料，收集完畢後一次性傳回完整 JSON。

3. **模型可用性**：可用模型列表取決於你的 Google 帳號權限。免費帳號和 Gemini Advanced 帳號看到的模型不同，服務啟動時會自動檢測。

4. **請求頻率**：即使關閉了內置限流（`RATE_LIMIT_ENABLED=false`），Google 側仍有頻率限制。高頻請求可能觸發驗證碼或臨時封禁，建議合理控制呼叫頻率。

5. **網路環境**：部署服務器需能直接存取 `gemini.google.com`，部分地區可能需要設定代理。

---

## 🗺 開發路線

- [x] OpenAI / Claude / Gemini 三格式相容
- [x] 流式回應 + 函數呼叫
- [x] Deep Research 深度研究
- [x] Docker 部署
- [x] API Key 認證
- [x] Cookie 熱更新 API
- [x] 帳號狀態定時檢測
- [x] 多帳號輪詢（負載均衡）
- [x] Web 管理面板
- [x] 反檢測與協議偽裝
- [x] 設定頁面（可視化設定管理）
- [x] API Key 管理（第三方大模型 Key 集中管理）
- [x] 統一轉發引擎（一個介面呼叫所有大模型）
- [x] 模型對應（別名→實際模型名）
- [ ] 圖片/檔案上傳支援

---

## ☕ 贊賞 & 共享

覺得有幫助？請作者喝杯咖啡，或加入微信交流群獲取使用幫助。完整內容請查看 [SPONSORS.md](SPONSORS.md)。

歡迎 PR 和 Issue。

1. Fork 本倉庫
2. 建立分支 `git checkout -b feature/your-feature`
3. 提交程式碼 `git commit -m "feat: add something"`
4. 推送並建立 Pull Request

---

## 🙏 致謝

感謝所有在 [Issues](https://github.com/xwteam/gemini2api/issues) 裡提交 bug 復現、日誌、相容性回饋和功能建議的使用者。這些回饋直接推動了 Cookie 保活、多帳號輪換、模型選擇、多語言支援、Web 面板等核心能力的迭代。

---

## 📄 授權協議

本專案採用 [非商業授權 (Non-Commercial)](../../LICENSE)：

- **允許**：個人學習、研究、自用部署
- **禁止**：任何形式的商業用途，包括但不限於出售、轉售、收費代理、商業產品整合

本專案與 Google 無關聯。使用者需自行承擔風險並遵守 Google 的服務條款。

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
