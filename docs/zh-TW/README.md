<div align="center">

<img src="../logo.png" width="128" height="128" alt="Gemini2API">

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
  <img src="https://img.shields.io/badge/version-v1.6.40-success?style=flat-square" alt="Version">
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

> 僅列出最近 10 條更新，完整更新日誌請查看 [CHANGELOG.md](../../CHANGELOG.md)。

| 日期 | 更新內容 |
|------|----------|
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 修復「模型測試頁把真實錯誤顯示成『無回應內容』」（issue #11 追加）：串流失敗只能以串流內 error 幀表達，而前端不認這個鍵，導致 503/529/500/400 全長一樣；現在顯示真實原因與狀態碼，已輸出的內容不會被抹掉。帳號卡片新增真實健康資訊（`is_healthy`／連續失敗數／最近成功時間／去敏後的最近錯誤）—— 此前綠色 ACTIVE 徽章讀的是池裡的狀態列舉而非用戶端健康位，cookie 失效的帳號照樣顯示綠色。空回應不再被當成功悄悄嚥下（連續 3 次才計入錯誤，單次絕不降級）。啟動日誌明說 cookie 輪換迴圈有沒有起來 |
| 2026-09-01 16:20:00 | v1.6.39 - ⚙️ `LOG_BODIES_ENABLED` 接進管理面板「日誌」分組，點一下即時生效、無需改設定重啟（預設仍關）；⚠️ 行為變更：面板儲存過的設定項現在寫入 `data/settings-overrides.json` 並**優先於環境變數**（此前面板改完一重啟就被打回）；修復面板小數欄位被 `parseInt` 靜默截斷、拒絕 NaN/±Infinity 寫入、寫入失敗時三層（記憶體/覆寫檔/.env）全有或全無回復；補齊面板裡顯示成原始欄位名／寫死中文的標籤並加守衛測試 |
| 2026-09-01 13:10:00 | v1.6.38 - 🍪 修復「同名 Cookie 跨網域並存」（Google 重新導向到 .com.hk 等國家網域時）導致工作階段取得整體失敗、帳號被誤標不健康（issue #10 追加；也是 issue #11 卡死的真實觸發源之一）；工具呼叫 JSON 畸形時自動重新產生一次（重試期間有串流保活）；新增可開關的完整請求/回應記錄 `LOG_BODIES_ENABLED`（預設關，只存記憶體不寫磁碟、不記請求標頭） |
| 2026-08-30 18:20:00 | v1.6.37 - 🩺 修復帳號池永久卡死並誤報「All accounts busy」（issue #11）：工作階段失效的帳號此前會讓每個請求空等 60 秒並回傳錯誤的 529，現改為立即回傳準確的 503 並**自動嘗試重載 cookie 自癒**；用戶端斷線不再計為帳號失敗；cookie 重載失敗不再永久封鎖健康帳號 |
| 2026-08-28 19:40:00 | v1.6.36 - 🚨 OpenAI 串流上游錯誤不再偽裝成正常回答（改發標準 error 幀，客戶端可正確拋錯重試）；上游 4xx 錯誤類型細化；Anthropic `citations` 欄位在串流/非串流間對齊；非字串 content 不再觸發 500 |
| 2026-08-28 17:30:00 | v1.6.35 - 🛠️ 協定一致性與健壯性大修：修復生圖意圖誤判導致**客戶端工具被靜默丟棄**（四協定共用）、上游錯誤偽裝成正常回答、`HTTPStatusError` 逃逸成裸 500（池滿改 529+Retry-After）、`/v1/responses` 與 native Gemini buffered 分支缺失的串流保活、原生 Gemini 不認官方 SDK camelCase 報文、OpenAI `tool_calls` 被丟棄、第三方 Anthropic 轉發工具迴圈第二輪硬失敗，以及 Anthropic 回應結構對齊 |
| 2026-08-28 15:10:00 | v1.6.34 - 🧹 Anthropic 協定細節打磨：回應補上規範的 `stop_sequence` 欄位並同步五語言 API 文件；工具呼叫區塊 name 為 null 時不再渲染成 None；斷線保活守衛補異常取回；並加固工具渲染格式與斷線取消的測試覆蓋 |
| 2026-08-28 14:20:00 | v1.6.33 - 🔌 修復 Claude Code 無法接入（issue #10）：`system` 支援文字區塊陣列不再 422；`tool_use`/`tool_result` 區塊不再被丟棄（工具迴圈可用）；Anthropic 串流改為標準 event+data 兩行制；並為 Claude buffered 串流補保活、斷線及時歸還帳號槽位 |
| 2026-08-14 22:50:00 | v1.6.32 - 🧠 思考內容逐幀串流：原生 Gemini 的思考過程在生成階段就作為 reasoning_content 逐幀增量流出（/v1/chat/completions），思考先於答案顯示、帶打字機效果，修復面板「答案早於思考」；收尾仍帶完整思考兜底，不開思考/一般對話零回歸 |
| 2026-08-14 22:40:00 | v1.6.31 - 🌊 修復串流連線偶發中斷：為全部四條串流介面（/v1/chat/completions、/v1/responses、/v1/messages、native Gemini streamGenerateContent）在等待模型生成的靜默期補發保活心跳，避免長回應被跨境/閘道閒置逾時掐斷；並修正面板誤導的網路錯誤提示 |

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
- **第三方自動兜底**（`FALLBACK_ENABLED`，預設關）：任意 Gemini 模型報錯/回傳空回應時，自動改用 API Key 池中的第三方模型原生重試，客戶端無感、仍只用一個模型名；預設自動選用池中所有「適合聊天」的第三方（排除 image/video 等非聊天模型）、隨機輪詢、失敗換下一個，`FALLBACK_MODELS` 可選精確指定

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
| POST | `/responses` | OpenAI Responses API（文字/流式/工具呼叫，Codex CLI 等新客戶端使用） |

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

> 完整管理端點（含請求/回應範例）見 [API.md](API.md)，下表為完整列表。

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/status` | 服務狀態（帳號池概覽 + 輪詢策略） |
| GET | `/system-info` | 系統資訊（版本/Python/OS/記憶體/CPU/PID/執行模式） |
| GET | `/accounts` | 所有帳號列表及狀態 |
| POST | `/accounts` | 動態新增新帳號 |
| DELETE | `/accounts/{id}` | 移除指定帳號 |
| GET | `/accounts/{id}/check` | 檢測單個帳號狀態 |
| GET | `/check-account` | 檢測所有帳號狀態 |
| POST | `/reload-cookies` | 熱更新 Cookie（無需重啟容器） |
| PUT | `/accounts/{id}/cookies` | 更新指定帳號的 Cookie |
| GET | `/health-history` | 最近健康檢查記錄 |
| GET | `/usage-stats/summary` | 用量統計概覽 |
| GET | `/usage-stats/history` | 歷史趨勢數據 |
| GET | `/settings` | 取得當前可編輯配置（分組回傳） |
| POST | `/settings` | 批量更新配置（熱更新記憶體 + 寫入 `data/settings-overrides.json`，同時照寫 `.env`） |
| GET | `/api-keys` | API Key 列表（密鑰脫敏） |
| GET | `/api-keys/catalog` | Provider 目錄（內建模型列表） |
| POST | `/api-keys` | 新增 API Key |
| DELETE | `/api-keys/{id}` | 刪除 API Key |
| PATCH | `/api-keys/{id}/status` | 切換 Key 狀態（啟用/停用） |
| PATCH | `/api-keys/{id}/label` | 修改 Key 標籤 |
| POST | `/api-keys/import` | 批量匯入 Key |
| GET | `/api-keys/export` | 匯出所有 Key（預設脫敏，`?reveal=true` 取明文） |
| POST | `/api-keys/batch-delete` | 批量刪除 |
| POST | `/api-keys/models` | 探測某 Provider/base_url 下可用模型列表 |
| GET | `/verify` | 驗證 API Key 有效性（登入用） |
| POST | `/restart` | 重啟服務（面板右上角一鍵重啟） |
| GET | `/check-update` | 檢查是否有新版本 |
| POST | `/update` | 觸發更新到最新版本 |
| GET | `/logs` | 結構化日誌分頁查詢 |
| GET | `/logs/state` | 日誌記錄狀態 |
| POST | `/logs/state` | 更新日誌記錄狀態 |
| POST | `/logs/clear` | 清空日誌 |
| GET | `/logs/{id}` | 單條日誌詳情 |
| GET | `/model-mapping` | 取得所有模型映射 |
| POST | `/model-mapping` | 新增/更新模型映射 |
| DELETE | `/model-mapping/{alias}` | 刪除模型映射 |
| GET | `/web-chats` | 列出帳號在 Gemini 網頁端堆積的會話（唯讀） |
| POST | `/cleanup-web-chats` | 手動觸發清理超期網頁會話（後台非同步執行） |

---

## ⚙ 設定說明

> [!IMPORTANT]
> **面板改過的設定項優先級高於環境變數。** 在 Web 面板「設定」頁儲存過的項目會寫進
> `data/settings-overrides.json`（`data/` 是 docker-compose 的持久化 bind mount），
> 並在每次啟動時回放、**覆蓋**下表中對應的環境變數。
> 這是刻意的：面板上關掉 `LOG_BODIES_ENABLED` 之後，`docker compose restart` 不能把它
> 重新打開。
>
> 所以：**改了 `.env` 重啟卻不生效**，多半就是該欄位被面板覆蓋了。啟動日誌裡有一行
> `Applied N panel setting override(s) from data/settings-overrides.json: ...` 會點名
> 具體欄位；刪掉 `data/settings-overrides.json` 即可把控制權交回環境變數。

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 瀏覽器 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 瀏覽器 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自動生成 | API 存取密鑰（`sk-` 開頭，留空則首次啟動自動生成） |
| `REFRESH_INTERVAL` | ❌ | `30` | Cookie 重新整理週期（分鐘，最小 10） |
| `MAX_RETRIES` | ❌ | `3` | 失敗重試次數（指數退避） |
| `PORT` | ❌ | `5918` | 服務連接埠 |
| `LOG_LEVEL` | ❌ | `info` | 日誌級別（debug/info/warning/error） |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | 啟用限流 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 限流視窗（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | 視窗內最大請求數 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | 啟用定時帳號狀態檢測 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | 檢測間隔（分鐘） |
| `ACCOUNTS_FILE` | ❌ | `accounts.json` | 多帳號配置檔案路徑（不存在則使用環境變數單帳號模式） |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 輪詢策略：`round-robin`（輪詢）/ `failover`（故障轉移） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `8` | 每帳號最大並行請求數 |
| `ACQUIRE_TIMEOUT` | ❌ | `60.0` | 並行滿載時排隊等待可用槽位的上限（秒），等不到才報錯 |
| `SAME_ACCOUNT_5XX_RETRIES` | ❌ | `1` | 遇 5xx 時同帳號快速重試次數（不長退避），仍失敗則 failover 換號 |
| `FAILOVER_COOLDOWN` | ❌ | `30.0` | 被 5xx 限流的帳號進入冷卻的時長（秒），期間不優先選 |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | 指紋配置檔案路徑 |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | 啟用 Chrome 版本自動同步 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | 版本同步間隔（小時） |
| `JITTER_ENABLED` | ❌ | `true` | 啟用請求時間抖動（模擬人類行為） |
| `USAGE_STATS_ENABLED` | ❌ | `true` | 啟用用量統計（時序快照 + 持久化） |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | 快照採集間隔（秒） |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | 歷史數據保留天數 |
| `MODEL_WHITELIST` | ❌ | — | 模型白名單（逗號分隔，為空則不過濾；非空時過濾各 `/models` 列表） |
| `CHAT_CLEANUP_ENABLED` | ❌ | `true` | 啟用 Gemini 網頁端會話自動清理 |
| `CHAT_CLEANUP_KEEP_HOURS` | ❌ | `24.0` | 網頁會話保留時長（小時），超過則清理 |
| `CHAT_CLEANUP_INTERVAL_HOURS` | ❌ | `6.0` | 自動清理任務運行間隔（小時） |
| `CHAT_CLEANUP_SKIP_PINNED` | ❌ | `true` | 清理時跳過置頂會話 |
| `ADMIN_API_KEY` | ❌ | — | 管理面板/`/admin` 獨立鑑權 key（留空則回退用 `API_KEY`） |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | CORS 允許來源（逗號分隔，`*` 表示全部） |
| `CORS_ALLOW_CREDENTIALS` | ❌ | `true` | CORS 是否允許攜帶憑據 |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | ❌ | `=s2048` | 生圖代下載尺寸後綴（`=s0` 為全解析度原圖） |
| `IMAGE_DOWNLOAD_TIMEOUT` | ❌ | `25.0` | 單次圖片下載 HTTP 超時（秒） |
| `FALLBACK_ENABLED` | ❌ | `false` | 啟用 Gemini→第三方兜底：任意 Gemini 模型（flash/pro/thinking）報錯或回傳空回應時，自動改用 API Key 池中的第三方模型「原生重試」 |
| `FALLBACK_MODELS` | ❌ | — | 兜底模型（逗號分隔、按序嘗試）；留空＝自動選用池中所有「適合聊天」的第三方（按名稱排除 image/video/audio/embedding 等非聊天模型）並隨機輪詢、一個失敗（報錯/空）就換下一個 |

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
- [x] 自動清理網頁端堆積會話（定時刪除舊會話，置頂保留）
- [x] [issues #2](https://github.com/xwteam/gemini2api/issues/2) 自訂 Gemini Gem 支援（管理面板列出/新建/修改/刪除 + 暴露為模型名呼叫）
- [x] [issues #6](https://github.com/xwteam/gemini2api/issues/6) [#7](https://github.com/xwteam/gemini2api/issues/7) 原生 Gemini 擴展思考支援（`reasoning_effort` 開啟，思考過程逐幀串流、先於答案顯示 + 模型測試面板「思考」開關 + 一鍵關不影響一般聊天）
- [x] API 管理頁 Gemini 兜底一鍵開關（即時開/關兜底鏈並持久化，無需改 .env 重啟）

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
