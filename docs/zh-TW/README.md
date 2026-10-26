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
  <img src="https://img.shields.io/badge/version-v1.6.45-success?style=flat-square" alt="Version">
</p>

<p>
  <a href="#-最近更新">最近更新</a> &bull;
  <a href="#-核心功能">核心功能</a> &bull;
  <a href="#-系統需求">系統需求</a> &bull;
  <a href="#-快速部署">快速部署</a> &bull;
  <a href="#-接入範例">接入範例</a> &bull;
  <a href="#-api-端點">API 端點</a> &bull;
  <a href="#-存取金鑰">存取金鑰</a> &bull;
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
| 2026-10-26 16:41:00 | v1.6.45 - ⏱️ **生成逾時不再回純文字 500**：谷歌卡住、超過生成預算時，用戶端過去拿到純文字 500（SDK 解析不了，也不轉兜底）；現在各協定統一回 504 + `timeout_error`，`/v1/chat/completions` 開了兜底會先轉第三方兜底，逾時不再重試、也不會把帳號標成過期。💬 **多輪對話真正續上同一個會話**：帶 `conversation_id` 的對話過去每一輪其實都新開了會話、只發最後一句，長對話會悄悄遺失上下文；現在按 `[cid, rid, rcid]` 續接並釘回同一個帳號，串流也續接，接不上就自動改發完整歷史 |
| 2026-10-26 14:01:00 | v1.6.44 - 🔄 **瀏覽器保活擴充功能重新生效**：會話被谷歌打回登入頁的帳號過去仍報 active（只把 is_healthy 設為 false），擴充功能只認 expired、一直不救，線上兩個帳號因此掉線約 37 小時；現在如實報 expired，換 cookie 成功後當場恢復。🔁 **不再和瀏覽器互相頂掉會話**：擴充功能推送 cookie 的帳號自動改為「瀏覽器保活」，伺服器不再輪換它（此前兩邊各自換 PSIDTS，後換的一方被踢下線，保活越來越短）；面板手動更新的帳號仍由伺服器輪換。配套擴充功能 v1.3.0：瀏覽器 cookie 一變就主動推送 |
| 2026-10-21 15:29:00 | v1.6.43 - 🧠 **思考改為低 / 中 / 高三檔，對齊網頁**：四個協定都能選同樣的三檔，**預設 `low`**（面板「設定 → 思考」儲存即時生效；實測平均每個請求多約 5 秒，最看重速度就設成「關閉」）；客戶端沒提思考時依預設檔開啟的思考只用於生成、絕不回傳。⚡ **Claude Code 不再每個請求都跑最深的一檔**（它每次都送 `adaptive` + `effort: high`，上一版寫死成 high），現在跟隨預設檔，`/effort low|medium|xhigh|max` 也生效了；`reasoning_effort: none` = 不思考。🤖 **對外模型收斂為四個**：`gemini-pro` / `gemini-flash` / `gemini-flash-lite` / `gemini-argon` 自動映射網頁的 3.1 Pro / 3.8 Flash / 3.5 Flash-Lite / 4 Argon，`gemini-flash-thinking` 下線（舊名仍可呼叫）。🔌 修好「API 管理」第三方轉發（書生端硯的 deepseek / glm / kimi 等此前全部 400，被誤報成額度不足）。🧪 模型測試頁改為檔位選擇 |
| 2026-10-21 04:30:00 | v1.6.42 - 🤖 **接上 4 Argon 並讓模型探索改由帳號驅動**：帳號心跳本來就回傳真實可用的模型清單，此前只認寫死的表、認不出的連日誌都不打就丟掉（這正是 Argon 用不了的原因），現在能自動採納、Google 換代不必再等改程式；穩定公開名契約不變，自動採納帶驗證、不合格條目仍丟棄但留日誌。💵 每把**存取金鑰的 token 用量與美元估算**（只統計不限額，介面已標註「估算」：本服務走網頁版本身不花錢，且 token 是按字元估的）。📄 **Canvas 正文不再整段遺失**（此前只留一條打不開的佔位連結）。🧼 清理 `<ctrl94>thought` 思考外洩等控制標記。🧠 **Anthropic 協定補上思考鏈**（此前 Claude Code 送的 thinking 參數被靜默丟棄、那邊使用者永遠「不思考」） |
| 2026-10-21 00:58:00 | v1.6.41 - 🔑 新增**可分發的存取金鑰**：面板可簽發多把 key 分發給不同的人，每把獨立設定啟停／有效期／**延遲啟用**（對方首次使用才開始計時）／請求數上限／綁定帳號／限定模型；`.env` 的 API_KEY 仍全權有效，存取金鑰進不了 /admin。⚠️ `REFRESH_INTERVAL` 預設 5→30 分鐘（下限 10）：cookie 輪換迴圈此前**只在啟動失敗時才跑**，正常啟動的閘道從不輪換、幾小時後帳號必死（issue #11），現改為啟動就跑。認出 Gemini 用 **HTTP 200** 回傳的拒絕區塊（工作階段過期／限流／上下文超長／人機驗證此前被當成「空回覆」吞掉，既不標不健康也不觸發自癒）。非串流逾時按模型族分層且逾時不再重試三遍（此前 60 秒硬斷＋重試＝等 183 秒才失敗）。思考等級不再一律最高檔。帶附件恢復真串流 |
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 修復「模型測試頁把真實錯誤顯示成『無回應內容』」（issue #11 追加）：串流失敗只能以串流內 error 幀表達，而前端不認這個鍵，導致 503/529/500/400 全長一樣；現在顯示真實原因與狀態碼，已輸出的內容不會被抹掉。帳號卡片新增真實健康資訊（`is_healthy`／連續失敗數／最近成功時間／去敏後的最近錯誤）—— 此前綠色 ACTIVE 徽章讀的是池裡的狀態列舉而非用戶端健康位，cookie 失效的帳號照樣顯示綠色。空回應不再被當成功悄悄嚥下（連續 3 次才計入錯誤，單次絕不降級）。啟動日誌明說 cookie 輪換迴圈有沒有起來 |
| 2026-09-01 16:20:00 | v1.6.39 - ⚙️ `LOG_BODIES_ENABLED` 接進管理面板「日誌」分組，點一下即時生效、無需改設定重啟（預設仍關）；⚠️ 行為變更：面板儲存過的設定項現在寫入 `data/settings-overrides.json` 並**優先於環境變數**（此前面板改完一重啟就被打回）；修復面板小數欄位被 `parseInt` 靜默截斷、拒絕 NaN/±Infinity 寫入、寫入失敗時三層（記憶體/覆寫檔/.env）全有或全無回復；補齊面板裡顯示成原始欄位名／寫死中文的標籤並加守衛測試 |
| 2026-09-01 13:10:00 | v1.6.38 - 🍪 修復「同名 Cookie 跨網域並存」（Google 重新導向到 .com.hk 等國家網域時）導致工作階段取得整體失敗、帳號被誤標不健康（issue #10 追加；也是 issue #11 卡死的真實觸發源之一）；工具呼叫 JSON 畸形時自動重新產生一次（重試期間有串流保活）；新增可開關的完整請求/回應記錄 `LOG_BODIES_ENABLED`（預設關，只存記憶體不寫磁碟、不記請求標頭） |
| 2026-08-30 18:20:00 | v1.6.37 - 🩺 修復帳號池永久卡死並誤報「All accounts busy」（issue #11）：工作階段失效的帳號此前會讓每個請求空等 60 秒並回傳錯誤的 529，現改為立即回傳準確的 503 並**自動嘗試重載 cookie 自癒**；用戶端斷線不再計為帳號失敗；cookie 重載失敗不再永久封鎖健康帳號 |
| 2026-08-28 19:40:00 | v1.6.36 - 🚨 OpenAI 串流上游錯誤不再偽裝成正常回答（改發標準 error 幀，客戶端可正確拋錯重試）；上游 4xx 錯誤類型細化；Anthropic `citations` 欄位在串流/非串流間對齊；非字串 content 不再觸發 500 |

---

## 🌟 核心功能

> 📖 詳細使用文件：[USAGE.md](USAGE.md)

### 🔌 三合一協議相容

- 一個服務同時提供 OpenAI、Claude、Gemini 三種 SDK 格式
- SSE 流式輸出（OpenAI / Claude）+ Chunked JSON（Gemini）
- 函數呼叫（Function Calling）三種格式均支援
- Deep Research 多步驟深度研究
- **思考檔位**：`low` / `medium` / `high` 三檔對應網頁的低 / 中 / 高，客戶端沒指定檔位時預設 `low`（可設 `off` 換最快），客戶端完全沒提思考時依預設檔開的思考不回傳；詳見 [🧠 模型與思考檔位](#-模型與思考檔位)
- **帶附件也走真流式**：帶圖片／檔案的請求不再等全文生成完才吐出第一個字（帶工具呼叫的仍為 buffered —— 工具參數必須是完整 JSON 才能解析）

### 🧠 模型與思考檔位

| 對外模型名 | 自動對應到網頁上的模型（目前實測） | 說明 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 品質最高、較慢 |
| `gemini-flash` | 3.8 Flash | 快，建議作為預設 |
| `gemini-flash-lite` | 3.5 Flash-Lite | 最輕最快，Pro/Flash 被限額時的備援 |
| `gemini-argon` | 4 Argon | 面向複雜任務；**帳號真的有 Argon 時才會列出** |

- **對應是自動的**：每個帳號的心跳會回報它目前真實可用的網頁模型，對外名字固定不變、內部自動對上網頁目前的那一代（Google 換代時不用改客戶端）。
- **`gemini-flash-thinking` 已下線**：它只是「flash + 思考模式」的假模型，思考現在是每個模型都有的檔位（見下）。為相容舊客戶端，`gemini-flash-thinking`、`gemini-2.5-flash-thinking`、`gemini-2.0-flash-thinking` 以及內部名 `gemini-3-flash-thinking*` **仍然可以呼叫**（隱藏別名，等同 `gemini-flash`），只是不再出現在任何模型清單裡；想要思考內容請改傳檔位參數。 例外：存取金鑰的「允許模型」裡勾過 `gemini-flash-thinking` 的，這把金鑰取得的模型清單裡仍會列出它（免得只勾了它的舊金鑰拿到空清單），新簽發的金鑰請改勾 `gemini-flash`。⚠️ 行為變化：舊客戶端不傳檔位呼叫 `gemini-flash-thinking` 時，v1.6.42 會回傳思考內容，現在不再回傳（未請求的思考一律不回傳）。
- **思考三檔**：`low` / `medium` / `high`，對應網頁上的低 / 中 / 高三檔（實測 `high` 想得最深、也最慢；`low` 與 `medium` 的差別在實測裡分不太開）。
- **預設檔 `low`**：客戶端**沒指定檔位**時（沒傳思考參數的，和要了思考但沒說幾檔的），使用「預設思考檔位」（環境變數 `DEFAULT_THINKING_LEVEL`，或面板「設定 → 思考」，儲存即時生效、無需重啟），出廠 `low`。
  - ⚠️ **速度代價**：實測預設 `low` 比不思考**平均每個請求多約 5 秒**（flash 簡單題 6.5 / 8.8 秒 → 8.6 / 16.6 秒）。最重視速度就把預設檔設成 **`off`**（不思考、最快，與舊版不傳參數時送往上游的請求完全一樣）。前置代理有首位元組逾時的（如 EdgeOne 免費版 15 秒）尤其要留意非流式請求。串流請求也有代價：沒提思考的請求，依預設檔位開啟的思考不回傳，**正文要等思考完成才開始輸出**（期間只有保活幀，連線不會被代理切斷），pro 遇到需要推理的題目 `low` 檔實測總耗時 36～47 秒 —— 對首字延遲敏感就用 `off`。⚠️ `off`（以及預設檔本身）管的是**沒指定檔位**的請求：沒傳思考參數的，和要了思考但沒說幾檔的（Claude Code 出廠請求就是這種，所以 Claude Code 預設也跟隨預設檔）。客戶端**明確指定了檔位**的（Codex / Cursor 選了 low/medium/high、Anthropic 給了 `budget_tokens`、Claude Code `/effort max` 等）預設檔管不到；要所有請求都不思考（真正最快），請關閉下方的總開關 `EXTENDED_THINKING_ENABLED=false`。
  - 客戶端**完全沒提思考**時，依預設檔替它開的思考**只用於生成，絕不回傳**：回應裡不會多出 `reasoning_content` / `thinking` 區塊 / 思考 part，結構與不思考時逐欄位一致（嚴格校驗的客戶端不會因此報錯）。客戶端**要了思考**（不論有沒有給檔位）才回傳思考內容（Gemini 原生仍只看 `includeThoughts`）。預設檔是 `off` 時，「要了思考但沒給檔位」的請求也不思考，自然沒有思考可回傳。
- **Claude Code**（新版）：每個請求都帶 `adaptive` + `effort: high`（high 是 Claude Code 的出廠值，不換檔時每個請求都是它），所以預設跟隨這裡的預設檔（出廠 low，速度優先）；想讓某個會話想得更深，在 Claude Code 裡執行 `/effort max`（或 `xhigh`）→ high；`/effort low` / `medium` 也照檔。
- **總開關** `EXTENDED_THINKING_ENABLED=false`：一律不思考，連客戶端明確要求的思考也忽略，這才是**真正最快**的模式。面板「設定 → 思考 →「允許思考（總開關）」」裡一直顯示、儲存即時生效；與「預設思考檔位」的分工：預設檔位管沒指定檔位的請求（含 Claude Code 出廠請求），總開關連明確指定了檔位的也管。
- 面板「模型測試」頁改用**檔位選擇**（低 / 中 / 高，預設低）取代原本的「思考」勾選框，所選檔位以 `reasoning_effort` 送出，思考過程顯示在回答上方。 另有「依預設檔位（不傳參數）」一項：不帶 `reasoning_effort`，與一般客戶端走同一條路，可用來實測設定中「預設思考檔位」（含 `off`）的實際速度（思考內容依規定不回傳）。

各協議的檔位寫法（**沒指定檔位則使用預設檔**；完全沒提思考的請求，思考不回傳）：

| 協議 | 參數 | 取值 → 檔位 |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`；`minimal` → low，`xhigh` → high；`none` → 不思考；認不出的值 → 跟隨預設檔（不報錯） |
| OpenAI `/v1/responses` | `reasoning.effort`（或頂層 `reasoning_effort`） | 同上 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`：`N<2048` → low，`2048–4095` → medium，`≥4096` → high；`{"type":"adaptive"}` 或 budget 無效 → 看 `output_config.effort`：`low` / `medium` 照檔，`xhigh` / `max` → high，`high`（Claude Code 出廠值，視同沒專門選檔）或沒給 → 跟隨預設檔；`{"type":"disabled"}` → 不思考；認不出的 `type` 視同沒傳 |
| Gemini 原生 `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`：`LOW` / `MEDIUM` / `HIGH`（`MINIMAL` → low，未指定 → 跟隨預設檔）；`thinkingBudget`：`0` → 不思考，`-1`（自動）→ 跟隨預設檔，`>0` 按 2048 / 4096 切點分檔；兩者都給時以 `thinkingLevel` 為準；只給 `includeThoughts: true` → 跟隨預設檔；`includeThoughts: true` 才在回應裡回傳思考（`"thought": true` 的 part） |

### 🔐 安全與認證

- API Key 自動生成（`sk-` 前綴 + 32 位隨機字元）
- 支援 `Authorization: Bearer` 和 `x-api-key` 兩種認證方式
- 首次部署自動生成密鑰，使用者可自訂修改
- **存取金鑰**：管理員可簽發多把可分送的入站金鑰，每把獨立設定有效期（支援「自首次使用起算」的惰性啟動）、請求數上限、綁定帳號與可用模型，隨時可停用或撤銷
- `.env` 的 `API_KEY` 始終保有全部權限，存取金鑰只是**附加**的一層；且存取金鑰只能呼叫業務 API，存取不到 `/admin/*`（詳見下文 [🔑 存取金鑰](#-存取金鑰)）

### 🔄 多帳號輪詢與 Cookie 自癒

- **多帳號負載均衡**：支援 round-robin（輪詢）和 failover（故障轉移）兩種策略
- 每帳號獨立並行控制，避免單帳號過載
- 連續失敗自動標記不健康，自動跳過故障帳號
- 後台自動輪換 Cookie，無感續期
- 熱更新 Cookie API，無需重啟容器
- 支援透過 API 動態新增/移除帳號
- 健康檢查歷史記錄，為 Web 面板提供資料支撐
- **Cookie 輪換迴圈啟動即跑**：以前只有「啟動時拿不到 token」才會拉起輪換迴圈，正常啟動的閘道其實從不輪換、Cookie 過幾小時就死（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）；現在無條件常駐
- **兩種保活方式自動區分**：瀏覽器擴充功能推送 cookie 的帳號自動改為瀏覽器保活、伺服器端不再輪換（雙方各自輪換會互相把工作階段擠下線）；工作階段被導回登入頁的帳號對外如實回報 `expired`，擴充功能據此及時補救
- **辨識 HTTP 200 裡的拒絕區塊**：Gemini 有時會在 200 回應內文裡塞一個拒絕區塊（限流／工作階段過期／上下文超長／人機驗證）。以前這類請求表現為「空回覆」且不觸發任何自癒，現在會被轉成明確錯誤並走冷卻 + 換帳號重試，可用 `BARD_ERROR_CODES` 為具體 code 設定語意
- **多輪續接釘回同一帳號**：`/v1/chat/completions` 帶 `conversation_id` 的多輪對話，後續輪次釘在服務上一輪的那個帳號上，帶完整的續接中繼資料（`[cid, rid, rcid]`）接著上游 Gemini 的同一個對話往下聊、只送最新一則使用者訊息（以前存的續接參數格式不對、也不記帳號，其實每一輪都新開了對話）。流式請求同樣續接，`conversation_id` 由用戶端自己帶上即可。那個帳號不可用（過期／被刪除／不在存取金鑰綁定的帳號裡／滿載）、記下的中繼資料用不了、上一輪由第三方兜底回答、或新的一輪不只是一則使用者訊息（例如帶著工具結果）時，自動改送完整歷史、新開對話，絕不只送最後一句而悄悄丟掉上下文；用 Gem 模型時以 Gem 綁定的帳號為準

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
- **存取金鑰**：簽發／編輯／停用／撤銷可分送的入站金鑰，列表直接顯示狀態、用量與權限範圍（與下面的「API Key 管理」無關，那管的是第三方**出站** Key）
- **API Key 管理**：集中管理第三方大模型 API Key（OpenAI/Anthropic/Gemini/OpenRouter/自訂），支援匯入匯出
- Playground：線上測試 API 請求
- 實時日誌：結構化表格展示，支援方向過濾、文字搜尋、分頁（每頁15條）、JSON 詳情面板，日誌持久化到磁碟（重啟不遺失）
- 深色/淺色主題切換，回應式行動端適配

### 🔀 統一轉發引擎

- 請求模型不在 Gemini Web 可用列表時，自動從 API Key 池比對並轉發到對應 Provider
- OpenAI 相容格式直接轉發（含流式），Anthropic 格式雙向轉換
- `/openai/v1/models` 自動聚合 Gemini Web 模型 + API Key 池中的第三方模型
- 一個介面、一個 Key 呼叫所有大模型
- **第三方自動兜底**（`FALLBACK_ENABLED`，預設關）：任意 Gemini 模型報錯（含生成超時）/回傳空回應時，自動改用 API Key 池中的第三方模型原生重試，客戶端無感、仍只用一個模型名；預設自動選用池中所有「適合聊天」的第三方（排除 image/video 等非聊天模型）、隨機輪詢、失敗換下一個，`FALLBACK_MODELS` 可選精確指定

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

gemini2api 內置 Cookie 自動輪換機制：預設每 30 分鐘（`REFRESH_INTERVAL`，硬性下限 10 分鐘）透過 Google RotateCookies API 重新整理 `__Secure-1PSIDTS`，配合 batchexecute 心跳模擬瀏覽器活躍行為，延長 session 壽命。

> [!IMPORTANT]
> **`REFRESH_INTERVAL` 的預設值已由 5 分鐘改為 30 分鐘，並在程式碼裡夾了 10 分鐘的硬性下限**（設定得更小會被自動抬到 10，並在啟動日誌裡點名）。
> 原因：以前輪換迴圈**只在「啟動時拿不到 token」的情況下才會被拉起**，正常啟動的閘道其實從不輪換，Cookie 過幾個小時就死（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）。現在改成啟動就常駐，同一個間隔下對 Google 的背景請求量會漲到約 3.5 倍，所以間隔必須相應放寬——輪換太勤在 Google 看來很像自動化，容易觸發風控、反而把工作階段搞死。

如需手動更新 Cookie，可透過 Web 面板的「帳號管理」→「更新 Cookie」操作，無需重啟服務。

> [!NOTE]
> Cookie 壽命受 Google 風控策略影響，資料中心 IP 通常可維持數小時。如 Cookie 頻繁過期，建議使用住宅 IP 或增加帳號數量做輪詢。

#### 兩種保活方式：伺服器端輪換 / 瀏覽器擴充功能推送

同一個 Google 工作階段**只能由一方輪換**：瀏覽器和伺服器端各自呼叫 RotateCookies 時，後一方拿著已被對方換掉的舊 `__Secure-1PSIDTS` 去換就會 401、整個工作階段被踢下線（表現為「常常斷線、要重新登入」）。所以每個帳號在兩種方式裡二選一：

- **伺服器端輪換**（預設）：本服務依 `REFRESH_INTERVAL` 定時呼叫 RotateCookies。新增的帳號、面板「更新 Cookie」、腳本 / curl 提交的 cookie 都走這種方式。
- **瀏覽器保活**：配套瀏覽器擴充功能 [**gemini2api-plugin**](https://github.com/xwteam/gemini2api-plugin) 裝在你本機的瀏覽器（住宅 IP）裡，由瀏覽器維持工作階段，擴充功能把新 cookie 推給本服務。**擴充功能推送成功的帳號會自動改為瀏覽器保活，伺服器端從此不再輪換它**（依請求標頭 `X-Gemini2API-Keepalive` 辨識；不帶這個標頭的舊版擴充功能，依它請求自帶的 `Origin: chrome-extension://…` 辨識）。

補充說明：

- 面板帳號卡片會給瀏覽器保活的帳號顯示「瀏覽器保活」標籤；`GET /admin/status` 的每個帳號都帶 `keepalive_mode`（`server` / `browser`）。
- 想交回伺服器端輪換（例如改用無痕視窗取得的 cookie——視窗一關就沒人輪換了），在面板「更新 Cookie」裡重新提交一次即可。
- 瀏覽器保活的帳號靠那個瀏覽器維持：瀏覽器長時間不開，cookie 會過期，帳號會變成 `expired`。
- 記錄保存在 `data/keepalive-modes.json`，鍵是 PSID 的 SHA-256 前 16 位（與 `data/cookies/` 下的檔名同一演算法），不含任何 cookie 值。記錄跟著 PSID 走：重新登入換了 PSID，舊記錄就不再適用，新 PSID 由誰推來就依誰記——擴充功能推來的仍是瀏覽器保活；面板 / 腳本推來的，以及透過面板「新增帳號」加進來的（包括刪掉後用同一份 cookie 加回來的）是伺服器端輪換。
- 倉庫自帶的 Playwright 續期邊車（`docker compose --profile refresher`）本身就是一個瀏覽器，推送時帶同一個請求標頭，它推過的帳號同樣記為瀏覽器保活。
- **擴充功能請綁定帳號 ID**（擴充功能側邊欄頂部「綁定本瀏覽器負責的帳號 ID」）。沒綁定時，擴充功能 v1.2.3 只要在 `/admin/status` 裡看到任何 `expired` 帳號，每輪輪詢（預設 60 秒）都會先重新整理一次瀏覽器裡的 Gemini 分頁、再依 PSID 比對帳號：池裡有不屬於這個瀏覽器的帳號失效時，你正在用的 Gemini 頁面會被反覆重新整理，正在輸入的內容可能會遺失。現在「工作階段被導回登入頁」也回報 `expired`，這種情況比以前常見。瀏覽器自己也掉了登入時同樣會每輪重新整理，在瀏覽器裡重新登入即可。

> [!NOTE]
> 帳號狀態 `expired` 現在也包括「**Google 工作階段被導回登入頁**」（cookie 已失效）。以前這種帳號仍顯示 `active`、只有 `is_healthy` 為 `false`，瀏覽器擴充功能看不見、不會去救。工作階段被導回登入頁、且 Google 已對這份 cookie 的 RotateCookies 回過 401 之後，伺服器端（輪換迴圈和自癒都一樣）不再拿同一份 cookie 白白呼叫 RotateCookies，只繼續探測工作階段，偶發故障能自己恢復；只是被導回登入頁、Google 還沒拒絕過的工作階段照舊輪換（PSIDTS 過期的工作階段往往一次輪換就能救回來）；擴充功能或面板換上新 cookie 後帳號立即回到 `active`，不用再點「檢測」。

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

> 存取金鑰的 6 個 `/admin/access-keys` 端點見下文 [🔑 存取金鑰](#-存取金鑰)。

---

## 🔑 存取金鑰

除了 `.env` 裡那把全權 `API_KEY`，管理員還可以簽發任意多把**可分送**的存取金鑰：每把獨立設定有效期、請求數上限、可用帳號與可用模型，發給不同的人，隨時可以單獨停用或撤銷。面板新增「存取金鑰」頁做視覺化管理，後端對應 `/admin/access-keys` 系列端點。

金鑰存放在 `data/access_keys.json`（`data/` 是 docker-compose 的持久化 bind mount），重啟不遺失。

### 每把金鑰可設定的欄位

| 欄位 | 說明 |
|------|------|
| `name` | 標籤，用來記住這把 key 發給了誰（留空則顯示為 `key-{id}`） |
| `enabled` | 啟停開關。停用後持有人立刻 401，但金鑰仍在列表裡，可隨時恢復 |
| `expires_at` | 絕對到期時間（ISO8601），到點失效 |
| `duration_days` | 有效天數，**惰性啟動**：發出去不計時，持有人第一次用它發請求才開始算 N 天 |
| `request_limit` | 請求數上限，累計達到即失效（可用「重設用量」清零後繼續用） |
| `bound_account_ids` | 綁定帳號，只允許用指定的 Gemini 帳號（留空 = 不限制） |
| `allowed_models` | 允許模型，只允許呼叫指定的模型名（留空 = 不限制） |

`expires_at` 與 `duration_days` 二選一，兩者都留空則永不到期。

### 金鑰狀態

| 狀態 | 含義 |
|------|------|
| 有效 | 可正常呼叫 |
| 已停用 | `enabled` 被管理員關掉 |
| 未啟動 | 設定了 `duration_days` 但還沒被用過，計時尚未開始 |
| 已到期 | 已過 `expires_at` |
| 已超額 | `request_count` 達到了 `request_limit` |

判定按「已停用 → 已到期 → 已超額 → 未啟動 → 有效」的優先級依次短路。

### 端點

| 方法 | 端點 | 功能 |
|------|------|------|
| GET | `/admin/access-keys` | 列出所有存取金鑰（含狀態、用量、權限範圍） |
| GET | `/admin/access-keys/options` | 面板簽發表單的候選項（帳號池裡的帳號 + 對外可見的模型名） |
| POST | `/admin/access-keys` | 簽發金鑰，`count` 可批次（上限 50） |
| PATCH | `/admin/access-keys/{id}` | 修改設定（清空某欄位要用 `clear` 陣列，見下） |
| DELETE | `/admin/access-keys/{id}` | 撤銷金鑰 |
| POST | `/admin/access-keys/{id}/reset-usage` | 重設請求計數 |

```bash
# 簽發 1 把：發出去 7 天有效（首次使用才開始算）、最多 500 次請求、只能用 flash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API金鑰" \
  -d '{"name":"張三","duration_days":7,"request_limit":500,"allowed_models":["gemini-flash"]}'

# 批次簽發 20 把同樣設定的金鑰（名稱自動編號為 試用-1 … 試用-20）
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API金鑰" \
  -d '{"name":"試用","count":20,"duration_days":3}'

# 列出所有金鑰
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-你的API金鑰"

# 停用第 3 把
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API金鑰" \
  -d '{"enabled":false}'

# 解除第 3 把的請求數上限和模型限制：JSON 裡傳 null 表示「不改」，
# 要清空欄位必須把欄位名放進 clear 陣列
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API金鑰" \
  -d '{"clear":["request_limit","allowed_models"]}'

# 重設用量計數
curl -X POST http://localhost:5918/admin/access-keys/3/reset-usage \
  -H "Authorization: Bearer sk-你的API金鑰"
```

### ⚠ 三條重要邊界

> [!IMPORTANT]
> **1. `.env` 的 `API_KEY` 仍然保有全部權限。** 存取金鑰是**附加**的一層，不是取代：`API_KEY` 命中後立刻放行，不查金鑰庫、不計任何用量。**一把存取金鑰都不簽發時，認證行為與舊版完全一致。**
>
> **2. 存取金鑰只能呼叫業務 API，絕對存取不到 `/admin/*`。** 管理面仍然只由 `API_KEY` / `ADMIN_API_KEY` 把守。所以可以放心把存取金鑰發給外人——他拿不到帳號 Cookie、改不了設定，也看不到別人的金鑰。
>
> **3. 每個業務請求都會 +1，包括 `GET /v1/models`。** 計數是在認證入口原子 +1 的，單調不減、不退還（上游報錯也算）。有些用戶端每輪對話前都會列一次模型，等於**一輪消耗 2 次**——設定 `request_limit` 時記得留餘量。

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
| `DEFAULT_THINKING_LEVEL` | ❌ | `low` | 客戶端沒指定檔位時使用的檔位：`off` / `low` / `medium` / `high`。`low` 實測每請求平均多約 5 秒，`off` 最快；面板「設定 → 思考」可即時切換。客戶端完全沒提思考時，依預設檔開的思考不回傳給客戶端 |
| `EXTENDED_THINKING_ENABLED` | ❌ | `true` | 思考總開關（進階/相容項）：`false` = 四個協議一律不思考，連客戶端明確要求的也忽略 |
| `THIRDPARTY_FAILOVER_COOLDOWN` | ❌ | `180` | 第三方「同名多家」故障切換的壞家冷卻秒數（0 關閉） |
| `BARD_ERROR_CODES` | ❌ | — | Gemini 在 **HTTP 200** 內文裡回傳的拒絕區塊的 code→語意對照表，形如 `1152=rate_limit,404=session_expired`，分類可取 `rate_limit` / `session_expired` / `context_too_long` / `captcha`。**留空時所有拒絕區塊按未知處理（冷卻該帳號 + 換帳號重試），這是刻意的安全兜底**；設定之後各類才有專門處理（工作階段過期觸發 Cookie 自癒、上下文超長直接回 400 不重試、人機驗證讓出該帳號） |
| `GEMINI_FAILURE_REPLIES` | ❌ | — | 追加谷歌的「失敗套話」（以 `\|` 分隔；內建的 `I seem to be encountering an error. Can I try something else for you?` 始終生效）。整段回答恰好是其中一句時按上游失敗處理（換帳號 / 兜底 / 502），不會當成正常回答回傳，見注意事項 8 |
| `GENERATE_TIMEOUTS` | ❌ | — | 生成超時按模型族覆寫，形如 `pro=300,flash=120`；留空用內建分層（flash-lite 60 / flash 120 / pro 300 / argon 300，認不出的族回落 60）。非流式依它掐斷整個請求；流式依它約束「第一次有新內容」與「相鄰兩次有新內容」的間隔（谷歌的心跳幀不算） |
| `GENERATE_TIMEOUT_IMAGE` | ❌ | `180` | 疑似生圖請求的生成超時（秒）。與模型族檔位**取大**，流式與非流式同口徑 |
| `MODEL_BREAKER_ENABLED` | ❌ | `true` | 模型故障熔斷總開關（見注意事項 7）。`false` 時照常記錄狀態，但絕不繞開谷歌 |
| `MODEL_BREAKER_THRESHOLD` | ❌ | `2` | 視窗內有這麼多個**不同請求**在同一模型族上疑似故障地失敗就熔斷（同一請求換帳號、重試、用戶端重送只算一個） |
| `MODEL_BREAKER_WINDOW` | ❌ | `300` | 計數視窗（秒）：這次失敗的嘗試開始時距上一次計入的失敗超過它，計數從 1 重新開始 |
| `MODEL_BREAKER_COOLDOWN` | ❌ | `60` | 熔斷打開後的開放期（秒），期間開了兜底的 `/v1/chat/completions` 請求直接走兜底 |
| `MODEL_BREAKER_MAX_COOLDOWN` | ❌ | `300` | 試探谷歌又失敗時開放期翻倍的上限（秒），至少等於 `MODEL_BREAKER_COOLDOWN` |
| `TOKEN_PRICES` | ❌ | — | 存取金鑰用量的**美元估算**價格表，形如 `gemini-pro=2.0/12.0,gemini-flash=0.75/3.75`（公開模型名=輸入價/輸出價，單位 USD／百萬 token）。留空用內建預設值；寫錯的條目靜默忽略，配不到價格的模型面板顯示 `—`。**只統計、不參與任何限額判定**，且不是帳單（本服務走網頁版、本身不花錢） |

---

## ⚠ 注意事項

1. **Cookie 有效期**：Google Cookie 會定期過期（通常數小時到數天不等）。服務內置自動重新整理機制，但如果帳號被登出或密碼變更，需要重新取得 Cookie。

2. **流式輸出**：所有 API 端點預設流式傳回。設定 `stream: false` 時，服務內部仍以流式方式接收資料，收集完畢後一次性傳回完整 JSON。

3. **模型可用性**：可用模型列表取決於你的 Google 帳號權限。免費帳號和 Gemini Advanced 帳號看到的模型不同，服務啟動時會自動檢測。

4. **請求頻率**：即使關閉了內置限流（`RATE_LIMIT_ENABLED=false`），Google 側仍有頻率限制。高頻請求可能觸發驗證碼或臨時封禁，建議合理控制呼叫頻率。

5. **網路環境**：部署服務器需能直接存取 `gemini.google.com`，部分地區可能需要設定代理。

6. **非流式超時與前置代理**：非流式（`stream: false`）請求的超時按模型族分層——flash-lite 60 秒、flash 120 秒、pro 與 argon 300 秒（可用 `GENERATE_TIMEOUTS` 覆寫；疑似生圖取 `GENERATE_TIMEOUT_IMAGE`，預設 180 秒），超時也不再重試三遍。到點後本服務回 **504**（錯誤類型 `timeout_error`，用各協議自己的 JSON 錯誤內文；流式請求是協議內的錯誤事件），不再是純文字的 500；開了 `FALLBACK_ENABLED` 時 `/v1/chat/completions` 會先嘗試第三方兜底。超時是谷歌那邊卡住，不計入帳號的連續失敗、不會把帳號標成 `expired`（建立連線階段的超時照舊先重試幾次，重試用完同樣按超時處理）。注意這整段時間裡連線上是**零位元組輸出**，所以它是**首位元組**超時而不是閒置超時：**pro 非流式最長要乾等 300 秒，會超過常見前置代理的首位元組上限**（EdgeOne 免費版 15 秒，不少反向代理預設 60 秒），用戶端拿到的將是代理的 504 而不是本服務的錯誤內文。這類場景建議直接用流式請求。 開了思考的請求還要再多幾秒（預設 `low` 實測平均每請求多約 5 秒）。 flash-lite 的 60 秒是依「不思考、幾秒就回」訂的，預設檔位開啟思考後在長 prompt / 難題上可能偏緊，可用 `GENERATE_TIMEOUTS=flash-lite=120` 調大（生成期逾時不會退回不思考重試，會直接回報逾時）。 **流式請求同樣受這套族預算約束**：第一次有新內容（內文 / 思考 / 生成圖片 / Canvas）必須在預算內到達（等回應標頭的時間也算在內），之後相鄰兩次有新內容的間隔也不能超過預算；谷歌排隊時每 60 秒送一個不含任何內容的心跳幀，它**不算進展**。到點同樣回協議內的 `timeout_error` 錯誤事件（還沒流出內文時 `/v1/chat/completions` 先試第三方兜底）。過去流式只看「兩次收到位元組之間」的 120 秒，被谷歌的心跳一次次重置，實測用戶端乾等了約 240 秒。

7. **模型故障熔斷**：谷歌某個模型族整體故障時（例如 gemini-flash 所有帳號都在排隊卡住或秒回失敗套話），視窗內有 `MODEL_BREAKER_THRESHOLD`（預設 2）個不同請求在這個族上疑似故障地失敗（失敗套話、幾乎沒收到資料的生成超時、一次進展都沒有的流式超時），熔斷就打開 `MODEL_BREAKER_COOLDOWN`（預設 60）秒：這期間**開了 `FALLBACK_ENABLED` 且有兜底候選**的 `/v1/chat/completions` 請求直接走第三方兜底，不再先白等一個預算；到期後放一個真實請求去試探谷歌，試探失敗開放期翻倍（封頂 `MODEL_BREAKER_MAX_COOLDOWN`），任何成功都立即恢復。沒開兜底的請求和 Claude / Gemini 原生 / Responses 一律照常呼叫谷歌（它們的結果照樣更新熔斷狀態）；只影響故障的那個族，同帳號的其他族照常。狀態見面板帳號頁頂部的提示和 `/admin/status` 的 `model_breakers`；行程重啟後清空。

8. **谷歌的失敗套話**：谷歌端故障時 Gemini 有時會秒回一句固定的 `I seem to be encountering an error. Can I try something else for you?` 代替回答。整段回答恰好是這句（或 `GEMINI_FAILURE_REPLIES` 裡追加的某句）時按上游失敗處理——換帳號重試、`/v1/chat/completions` 可走兜底、否則回 502 `api_error`——不會當成正常回答回傳，也不會寫進對話紀錄；流式請求會先扣住還可能長成這句的開頭，確認不是才放出去（回答開頭最多晚幾個字）。

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
