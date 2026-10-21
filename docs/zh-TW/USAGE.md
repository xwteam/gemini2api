# 使用指南

本指南涵蓋 Gemini2API Web 面板功能、支援的模型、第三方客戶端整合和進階使用方式。

## Web 面板概覽

Web 面板提供完整的可視化管理介面，訪問 `http://localhost:5918` 並使用 API Key 登入。

### 儀表板

儀表板顯示系統概覽和實時狀態：

- **運行時間**：服務啟動後的實時計時
- **系統資訊**：版本、Python 版本、作業系統、記憶體使用、CPU 使用率、PID、運行模式
- **二維碼卡片**：支援文字和圖片，點擊圖片可放大檢視
- **帳號狀態**：帳號池概覽，顯示活躍帳號數
- **可用模型**：列出當前可用的所有模型
- **配置管理**：輪換策略、並發上限等設定

### 帳號管理

在帳號管理頁面進行帳號操作：

**新增帳號：**
1. 點擊「新增帳號」按鈕
2. 輸入 `__Secure-1PSID` 和 `__Secure-1PSIDTS`
3. 選擇性輸入帳號標籤
4. 點擊「儲存」

**更新 Cookie：**
1. 在帳號列表中找到目標帳號
2. 點擊「更新 Cookie」
3. 輸入新的 Cookie 數值
4. 點擊「儲存」

**檢測帳號：**
1. 點擊帳號旁的「檢測」按鈕
2. 系統會驗證帳號是否有效

**刪除帳號：**
1. 點擊帳號旁的「刪除」按鈕
2. 確認刪除

### Playground（模型測試）

Playground 允許你直接測試 API 請求：

1. 選擇模型
2. 輸入訊息
3. 選擇是否流式輸出
4. 點擊「發送」
5. 檢視 AI 回應和原始 JSON

支援對話上下文：使用 `conversation_id` 欄位維持多輪對話。

### 即時日誌

結構化日誌檢視器提供：

- **方向過濾**：查看最新或最舊的日誌
- **文字搜尋**：按關鍵字搜尋
- **分頁**：每頁 15 條記錄
- **JSON 詳情**：點擊日誌行查看完整詳情
- **日誌持久化**：重啟後日誌不丟失

### 使用統計

查看服務使用情況：

- **累計請求數**：總請求數
- **錯誤率**：失敗請求百分比
- **平均延遲**：平均回應時間
- **輪換成功率**：Cookie 更新成功率
- **歷史趨勢**：支援按時間粒度查看

### API Key 管理

集中管理第三方大模型 API Key：

**新增 Key：**
1. 點擊「新增 Key」
2. 選擇 Provider（OpenAI/Anthropic/Gemini/OpenRouter/自訂）
3. 輸入 API Key
4. 點擊「儲存」

**導入/導出：**
- 點擊「導入」上傳 JSON 檔案
- 點擊「導出」下載所有 Key（包含完整密鑰）

**切換狀態：**
- 點擊 Key 旁的開關啟用/禁用

### 存取金鑰

簽發可分送給不同人的入站存取金鑰。與上面的「API Key 管理」無關——那管的是第三方**出站** Key，這裡管的是「誰能呼叫本服務」。

**簽發金鑰：**
1. 點擊「簽發金鑰」
2. 填「名稱」（例如對方的名字，方便事後對帳）
3. 「數量」可一次簽發多把（上限 50），名稱會自動編號為 `名稱-1`、`名稱-2`……
4. 「有效天數（自首次使用起算）」與「絕對到期時間」二選一，兩者留空則永不到期
5. 「請求數上限」留空 = 不限
6. 「綁定帳號」／「允許模型」未勾選 = 不限制
7. 點擊「簽發」，在列表裡用「複製金鑰」把明文交給對方

**列表與管理：**

每列顯示狀態（有效／未啟動／已停用／已到期／已超額）、有效期、用量與權限範圍，可以：
- **編輯**：改名稱、有效期、上限、綁定帳號與允許模型
- **啟用／停用**：停用後持有人立刻 401，金鑰仍留在列表裡可隨時恢復
- **重設用量**：把請求計數清零，超額的金鑰可繼續用
- **刪除**：撤銷金鑰，使用它的用戶端立即斷線

**三件要知道的事：**
1. `.env` 裡的 `API_KEY` 仍然保有全部權限，存取金鑰只是附加的一層；一把都不簽發時行為與舊版完全一致。
2. 存取金鑰**只能呼叫業務 API**，存取不到 `/admin/*`——管理面仍由 `API_KEY` / `ADMIN_API_KEY` 把守，所以可以放心把金鑰發給外人。
3. 每個業務請求都會 +1，**包括 `GET /v1/models`**。有些用戶端每輪對話前都會列一次模型，等於一輪消耗 2 次，設定「請求數上限」時記得留餘量。

#### Token 用量與估算成本

清單裡除「用量」（請求計次）之外，還有兩列：**Token（估算）** 與 **估算成本 (USD)**（數字前恆帶 `≈`）。

⚠️ **這不是帳單，是參考值。** 本服務走 Gemini 網頁版、**本身不產生任何費用**，這一列回答的是「同樣的內容若走官方 API 大約要多少錢」。token 數由 `len(文字) / 4` 估算、不是真分詞器（中文會明顯低估）；價格表按官方公布的標準付費檔拍平，未計長上下文階梯與未來調價；思考鏈 token 計進輸出。走第三方兜底的請求不計入。

**只統計、不限額**：額度限制仍然只有「請求數上限」（計次）這一條。「重置用量」會把請求計數與 token／成本一起清零。價格表用環境變數 `TOKEN_PRICES` 設定（公開模型名=輸入價/輸出價，單位 USD／百萬 token），留空＝用內建預設值，配不到價格的模型顯示 `—`。

### 設定

可視化配置管理，修改即時生效：

- **性能設定**：並發上限、輪換策略
- **速率限制**：啟用/禁用、視窗大小、最大請求數
- **健康檢查**：啟用/禁用、檢查間隔
- **帳號管理**：自動故障轉移、重試次數
- **網頁會話清理**：自動清理 Gemini 網頁端堆積的會話記錄。API 每次對話都會在 gemini.google.com 留下記錄，長期使用會堆積大量歷史會話。開啟後，後台會定時刪除超過保留時長的舊會話（置頂會話永不刪除，活躍對話不受影響）。可設定：開關、保留時長、清理間隔、是否跳過置頂
- **其他**：日誌級別、Cookie 更新間隔

修改後無需重啟服務。

### 右上角控制欄

- **主題切換**：深色/淺色模式
- **語言選擇**：繁體中文/簡體中文/English/日本語/한국어
- **服務重啟**：一鍵重啟服務
- **登出**：退出登入

## 圖片上傳

Gemini2API 支援多模態內容，包括圖片和檔案上傳。支援三種 API 格式的圖片傳輸。

### OpenAI 格式

在 `messages` 陣列中使用 `image_url` 類型，支援 Base64 Data URI 和遠端 HTTP URL：

**Base64 圖片示例**：

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
          {"type": "text", "text": "這是什麼"},
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

**遠端 URL 圖片示例**：

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
          {"type": "text", "text": "分析這張圖片"},
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

### Claude 格式

在 `content` 陣列中使用 `image` 類型：

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
          {"type": "text", "text": "這是什麼"},
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

### Gemini 原生格式

在 `parts` 陣列中使用 `inlineData`：

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "contents": [
      {
        "parts": [
          {"text": "這是什麼"},
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

### Web 面板上傳

在 Playground 測試頁面，點擊「新增圖片」按鈕可直接上傳本機圖片進行測試。

## AI 生成圖片

Gemini2API 支援以 AI 生成圖片。生成靠 prompt 觸發：只要在對話中說「畫一張…圖」或英文 `generate an image of...`，即可產生圖片。三種對話介面（OpenAI `/v1/chat/completions`、Claude `/v1/messages`、Gemini `/v1beta/...:generateContent`）都支援這種觸發方式。此外，另提供 OpenAI 相容的專用介面 `POST /v1/images/generations`。

### 對話介面生圖

在 `messages` 中向模型提出生圖請求：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {"role": "user", "content": "generate an image of a cute cat"}
    ]
  }'
```

### 專用介面（OpenAI 相容）

使用 `/v1/images/generations` 端點直接生成圖片：

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

### 回應格式

對話介面會回傳圖片的本機 URL（例如 `http://你的位址/images/xxx.png`），可直接開啟或在客戶端中渲染；`/v1/images/generations` 則回傳 `b64_json`（Base64 編碼的圖片資料）。兩者皆回傳全解析度原圖（例如 1408×768）。

## 正文還原（Canvas 與控制標記）

Gemini 網頁端有兩類「正文不是正文」的情況，服務會在把回答交給客戶端之前統一處理（流式與非流式口徑完全一致）：

**Canvas 面板**：寫較長程式碼／文件時，網頁端會把內容搬進 Canvas 面板，回答正文裡只留一個 `http://googleusercontent.com/immersive_entry_chip/N` 佔位連結。服務會從回應裡取出該 Canvas 的真實內容還原進正文（程式碼自動補上帶語言的 Markdown 圍欄，文件原樣內嵌）。取不到真實內容時**剝掉死連結並留一句可讀說明**，不會把一條打不開的 URL 當答案交付，也不會讓正文變成空的。

**控制標記**：正文裡可能混進三類內部標記，都會被清掉：

| 標記 | 處理方式 |
|------|---------|
| `<ctrl94>thought…<ctrl95>` | 內容**歸入思考鏈**（`reasoning_content` / Anthropic `thinking` 區塊），不是直接丟棄。只處理**成對**出現的；未閉合的標記原樣保留 |
| `?code_reference&code_event_index=N` / `?code_stdout&…` | 只摘掉圍欄 info string 裡的這段標記，**圍欄正文一字不動** |
| `http://googleusercontent.com/card_content/N` | 刪除（客戶端訪問無效的死連結） |

正文裡只是「提到」這些字樣時不會被誤傷。

**已知邊界**：如果回答正文裡真的出現一對**成對**的 `<ctrl94>…<ctrl95>`（例如你貼了一段含這兩個字面量的日誌、要模型原樣回顯），中間那段會被當成思考內容移出正文。OpenAI 協議下它在 `reasoning_content` 裡、Anthropic 協議傳了 `thinking` 時它在 `thinking` 區塊裡，都取得回來；但原生 Gemini 協議與不傳 `thinking` 的 `/v1/messages` 沒有承載思考的通道，那段文字就拿不回來了。

## 支援的模型

### 對外固定穩定模型名

Gemini2API 對外提供 3 個固定的穩定模型名，永不變更。這些模型名作為 API 契約，客戶端可以長期使用而無需擔心模型名變化：

| 模型名稱 | 說明 |
|---------|------|
| `gemini-pro` | Pro 模型，效能最強，適合複雜任務 |
| `gemini-flash` | 快速模型，低延遲，適合即時應用 |
| `gemini-flash-lite` | 最輕量最快的模型（3.5 Flash-Lite），Pro/Flash 被限額時仍可用 |
| `gemini-argon` | 4 Argon，面向複雜任務。只有池裡至少一個帳號真的拿到它時才會出現在模型清單裡（別名：`gemini-4-argon`） |

> `gemini-flash-thinking` 已下線：它仍可呼叫（隱藏別名，等同 `gemini-flash`），但不再出現在模型清單裡。思考改為每個模型都有的 `low` / `medium` / `high` 三檔，客戶端沒指定檔位時預設 `low`（實測每請求平均多約 5 秒，可在面板「設定 → 思考」改成 `off` 換最快），詳見 [README 的「🧠 模型與思考檔位」](README.md#-模型與思考檔位)。

**帳號驅動的模型發現**：除上面這幾個固定名之外，服務還會從帳號心跳裡讀模型清單。帳號真的有、而內建表不認識的模型（4 Argon 正是這種情況）會被自動採納；採納前要過校驗（model id 為 16 位小寫十六進位、model number 為正整數、標籤可解析、產生的名字不得頂掉任何既有公開名），不合格的條目仍然丟棄並打日誌。上面 3 個契約名**永遠不來自發現**，所以一個畸形／被汙染的心跳改不了它們的指向。

**發現來的模型是按帳號生效的**：`gemini-argon` 這類發現來的名字，只在**真的發現過它的那個帳號**上可路由。模型清單是跨帳號聚合的，所以混合池裡（一部分帳號有 Argon、另一部分沒有）請求可能落到一個沒有它的帳號上 —— 這時服務直接報錯（HTTP 400 `Model ... unavailable`），**不會**退回到別的模型。這是故意的：靜默換模型的表現是 HTTP 200、正文正常、客戶端完全看不出答案來自另一個模型。需要穩定可用時，請讓池裡所有帳號都拿到該模型，或改用 3 個契約名。另外，某一輪心跳不再報告某個發現來的模型時，它會立刻從模型清單裡消失（不會留著一個「清單裡有、呼叫起來壞」的名字）。


**內部自動對應**：服務內部會根據你的 Google 帳號訂閱等級（Advanced/Plus/Basic）自動對應到當前真實可用的模型版本。無論帳號等級如何變化、Google 灰度發佈如何調整、服務重啟等，客戶端始終使用這 3 個固定名稱，無需修改。

**舊別名相容**：為了向後相容，以下舊模型名仍然支援：
- `gemini-2.5-pro`、`gemini-2.0-flash`、`gemini-2.0-flash-thinking` 等

### 第三方模型

通過 API Key 池支援：
- **OpenAI**：gpt-4o、gpt-4-turbo、gpt-3.5-turbo 等
- **Anthropic**：claude-3-opus、claude-3-sonnet、claude-3-haiku 等
- **Google Gemini**：通過官方 API Key
- **OpenRouter**：支援 OpenRouter 平台的所有模型

## 第三方客戶端整合

### ChatGPT-Next-Web

1. 部署 ChatGPT-Next-Web
2. 在設定中新增自訂 API：
   - **API 位址**：`http://伺服器IP:5918/openai/v1`
   - **API Key**：你的 sk- 金鑰
3. 選擇 Gemini 模型進行對話

### LobeChat

1. 部署 LobeChat
2. 在設定中新增自訂模型提供者：
   - **提供者名稱**：Gemini2API
   - **API 端點**：`http://伺服器IP:5918/openai/v1`
   - **API Key**：你的 sk- 金鑰
3. 選擇 Gemini 模型

### OpenCat

1. 開啟 OpenCat 應用
2. 在設定中新增自訂 API：
   - **API 位址**：`http://伺服器IP:5918/openai/v1`
   - **API Key**：你的 sk- 金鑰
3. 選擇 Gemini 模型

### Python SDK（OpenAI 相容）

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "你好"}],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

### Python SDK（Claude 相容）

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/claude"
)

message = client.messages.create(
    model="gemini-2.5-pro",
    max_tokens=1024,
    messages=[{"role": "user", "content": "寫一個快速排序演算法"}]
)

print(message.content[0].text)
```

### cURL

```bash
# 非流式請求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "你好"}]
  }'

# 流式請求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## Cookie 更新

### 何時需要更新

- 服務返回 401 或 403 錯誤
- 日誌顯示「SNlM0e not found」
- 帳號檢測顯示「不健康」

### 更新方式

**方式 1：Web 面板**
1. 前往帳號管理
2. 點擊帳號的「更新 Cookie」
3. 輸入新的 Cookie 數值
4. 點擊「儲存」

**方式 2：API**
```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "psid": "g.a000new...",
    "psidts": "sidts-new..."
  }'
```

**方式 3：全域重新整理**
```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-your-api-key"
```

## 多語言切換

點擊右上角地球圖示選擇語言：

- 繁體中文
- 簡體中文
- English
- 日本語
- 한국어

所有頁面和訊息都會即時切換。

## 對話上下文

### 自動維護（推薦）

大多數客戶端（ChatGPT-Next-Web、LobeChat 等）會自動維護 `messages` 歷史。只需在同一對話中繼續提問，上下文會自動保留。

### 使用 conversation_id

對於需要跨會話保留上下文的場景，使用 `conversation_id` 欄位：

```python
# 第一輪對話
response1 = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "我叫小明"}],
    conversation_id="conv-123"  # 自訂 ID
)

# 第二輪對話，模型會記得「小明」
response2 = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "我叫什麼名字？"}],
    conversation_id="conv-123"  # 使用相同 ID
)
```

### 上下文限制

- 每個對話最多保留 50 輪交互
- 超過限制時自動清理最舊的訊息
- 可在設定中調整保留策略

## 進階功能

### 函數調用

```python
response = client.chat.completions.create(
    model="gemini-2.5-pro",
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

### 模型映射

在設定中建立模型別名，例如將 `gpt-4o` 對應到 `gemini-2.5-pro`：

1. 前往 Web 面板設定
2. 找到「模型映射」
3. 新增映射：`gpt-4o` → `gemini-2.5-pro`
4. 之後所有 `gpt-4o` 請求會自動轉向 Gemini

### 統一轉發

如果請求的模型不在 Gemini Web 可用列表中，系統會自動從 API Key 池匹配並轉發到對應 Provider（OpenAI/Anthropic/Gemini API 等）。

## 常見問題

**Q：如何重啟服務？**
A：點擊右上角控制欄的「重啟」按鈕，或執行 `docker compose restart`。

**Q：日誌在哪裡？**
A：日誌持久化到 `data/logs.json`，也可在 Web 面板的「日誌」頁面檢視。

**Q：如何備份設定？**
A：所有設定儲存在 `data/` 目錄，定期備份該目錄即可。

**Q：支援圖片上傳嗎？**
A：目前不支援，計畫在後續版本新增。

**Q：可以同時使用多個 API Key 嗎？**
A：可以，在 API Key 管理中新增多個 Key，系統會自動選擇合適的 Key。
