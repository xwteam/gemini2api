<div align="center">

<img src="../logo.png" width="128" height="128" alt="Gemini2API">

<h1>Gemini2API</h1>
<h3>轻量级 Gemini Web 反向代理</h3>
<p>一套代码兼容 OpenAI / Claude / Gemini 三大主流 AI SDK，纯异步架构，零官方 Key，Docker 快速部署。</p>

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
  <a href="#-系统要求">系统要求</a> &bull;
  <a href="#-快速部署">快速部署</a> &bull;
  <a href="#-接入示例">接入示例</a> &bull;
  <a href="#-api-端点">API 端点</a> &bull;
  <a href="#-访问密钥">访问密钥</a> &bull;
  <a href="#-配置说明">配置说明</a> &bull;
  <a href="#-注意事项">注意事项</a> &bull;
  <a href="#-开发路线">开发路线</a>
</p>

<p>
  📖 文档语言：简体中文 | <a href="../zh-TW/README.md">繁體中文</a> | <a href="../en/README.md">English</a> | <a href="../ja/README.md">日本語</a> | <a href="../ko/README.md">한국어</a>
</p>

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> 本项目仅供研究和学习用途，请合理使用，不要用于任何商业目的。

> [!WARNING]
> 本项目与 Google 无关。项目通过逆向工程获取的浏览器 Cookie 实现功能，可能不符合 Google 服务条款。使用风险自负，作者不对任何账号处罚或数据丢失承担责任。

> [!TIP]
> 建议搭配 Gemini Pro 及以上订阅使用，以获得更完整的模型访问权限和更稳定的体验。

> [!IMPORTANT]
> 由于 Google 风控策略限制，Cookie 会话目前约 2 小时后会被强制失效，暂未找到完美的长期保活方案。如果您在这方面有经验或思路，非常欢迎通过 [Issue](https://github.com/xwteam/gemini2api/issues) 或 PR 分享，期待社区的智慧。

---

## 📝 最近更新

> 仅列出最近 10 条更新，完整更新日志请查看 [CHANGELOG.md](../../CHANGELOG.md)。

| 日期 | 更新内容 |
|------|----------|
| 2026-10-21 04:30:00 | v1.6.42 - 🤖 **接上 4 Argon 并让模型发现变成账号驱动的**：账号心跳本来就返回真实可用的模型清单，此前只认写死的表、认不出的连日志都不打就丢掉（这正是 Argon 用不了的原因），现在能自动采纳、Google 换代不必再等改代码；稳定公开名契约不变，自动采纳带校验、不合格条目仍丢弃但留日志。💵 每把**访问密钥的 token 用量与美元估算**（只统计不限额，界面已标注「估算」：本服务走网页版本身不花钱，且 token 是按字符估的）。📄 **Canvas 正文不再整段丢失**（此前只留一条打不开的占位链接）。🧼 清理 `<ctrl94>thought` 思考泄漏等控制标记。🧠 **Anthropic 协议补上思考链**（此前 Claude Code 发的 thinking 参数被静默丢弃、那边用户永远「不思考」） |
| 2026-10-21 00:58:00 | v1.6.41 - 🔑 新增**可分发的访问密钥**：面板可签发多把 key 分发给不同的人，每把独立设置启停／有效期／**惰性激活**（对方首次使用才开始计时）／请求数上限／绑定账号／限定模型；`.env` 的 API_KEY 仍全权有效，访问密钥进不了 /admin。⚠️ `REFRESH_INTERVAL` 默认 5→30 分钟（下限 10）：cookie 轮换循环此前**只在启动失败时才跑**，正常启动的网关从不轮换、几小时后账号必死（issue #11），现改为启动就跑。认出 Gemini 用 **HTTP 200** 返回的拒绝块（会话过期／限流／上下文超长／人机验证此前被当成「空回复」吞掉，既不标不健康也不触发自愈）。非流式超时按模型族分层且超时不再重试三遍（此前 60 秒硬掐＋重试＝等 183 秒才失败）。思考档位不再一律最高档。带附件恢复真流式 |
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 修复「模型测试页把真实错误显示成『无响应内容』」（issue #11 追加）：流式失败只能以流内 error 帧表达，而前端不认这个键，导致 503/529/500/400 全长一样；现在显示真实原因与状态码，已输出的内容不会被抹掉。账号卡片新增真实健康信息（`is_healthy`／连续失败数／最近成功时间／脱敏后的最近错误）—— 此前绿色 ACTIVE 徽章读的是池里的状态枚举而非客户端健康位，cookie 失效的账号照样显示绿色。空响应不再被当成功悄悄咽下（连续 3 次才计入错误，单次绝不降级）。启动日志明说 cookie 轮换循环有没有起来 |
| 2026-09-01 16:20:00 | v1.6.39 - ⚙️ `LOG_BODIES_ENABLED` 接入管理面板「日志」分组，点一下即时生效、无需改配置重启（默认仍关）；⚠️ 行为变更：面板保存过的设置项现在落盘 `data/settings-overrides.json` 并**优先于环境变量**（此前面板改完一重启就被打回）；修复面板小数字段被 `parseInt` 静默截断、拒绝 NaN/±Infinity 写入、写盘失败时三层（内存/覆盖文件/.env）全有或全无回滚；补齐面板里显示成原始字段名/写死中文的标签并加守卫测试 |
| 2026-09-01 13:10:00 | v1.6.38 - 🍪 修复「同名 Cookie 跨域并存」（Google 重定向到 .com.hk 等国家域名时）导致会话获取整体失败、账号被误标不健康（issue #10 追加；也是 issue #11 卡死的真实触发源之一）；工具调用 JSON 畸形时自动重新生成一次（重试期间有流式保活）；新增可开关的完整请求/响应记录 `LOG_BODIES_ENABLED`（默认关，只存内存不写盘、不记请求头） |
| 2026-08-30 18:20:00 | v1.6.37 - 🩺 修复账号池永久卡死并误报「All accounts busy」（issue #11）：会话失效的账号此前会让每个请求空等 60 秒并返回错误的 529，现改为立即返回准确的 503 并**自动尝试重载 cookie 自愈**；客户端断连不再被计为账号失败（点 3 次「停止」曾能让单账号池瘫痪）；cookie 重载失败不再永久拉黑健康账号 |
| 2026-08-28 19:40:00 | v1.6.36 - 🚨 OpenAI 流式上游错误不再伪装成正常回答（改发标准 error 帧，客户端可正确抛错重试）；上游 4xx 错误类型细化；Anthropic `citations` 字段在流式/非流式间对齐；非字符串 content 不再触发 500 |
| 2026-08-28 17:30:00 | v1.6.35 - 🛠️ 协议一致性与健壮性大修：修复生图意图误判导致**客户端工具被静默丢弃**（四协议共用）、上游错误伪装成正常回答、`HTTPStatusError` 逃逸成裸 500（池满改 529+Retry-After）、`/v1/responses` 与 native Gemini buffered 分支缺失的流式保活、原生 Gemini 不认官方 SDK camelCase 报文、OpenAI `tool_calls` 被丢弃、第三方 Anthropic 转发工具循环第二轮硬失败，以及 Anthropic 响应结构对齐（去掉非标准 image 块与 null 噪音） |
| 2026-08-28 15:10:00 | v1.6.34 - 🧹 Anthropic 协议细节打磨：响应补上规范的 `stop_sequence` 字段并同步五语言 API 文档；工具调用块 name 为 null 时不再渲染成 None；断连保活守卫补异常取回；并加固工具渲染格式与断连取消的测试覆盖 |
| 2026-08-28 14:20:00 | v1.6.33 - 🔌 修复 Claude Code 无法接入（issue #10）：`system` 支持文本块数组不再 422；`tool_use`/`tool_result` 块不再被丢弃（工具循环可用）；Anthropic 流式改为标准 event+data 两行制；并给 Claude buffered 流式补保活、断连及时归还账号槽位 |

---

## 🌟 核心功能

> 📖 详细使用文档：[USAGE.md](USAGE.md)

### 🔌 三合一协议兼容

- 一个服务同时提供 OpenAI、Claude、Gemini 三种 SDK 格式
- SSE 流式输出（OpenAI / Claude）+ Chunked JSON（Gemini）
- 函数调用（Function Calling）三种格式均支持
- Deep Research 多步骤深度研究
- **思考档位**：`low` / `medium` / `high` 三档对应网页的低 / 中 / 高，客户端不传时默认 `low`（可设 `off` 换最快），按默认档开的思考不回传；详见 [🧠 模型与思考档位](#-模型与思考档位)
- **带附件也走真流式**：带图片/文件的请求不再等全文生成完才吐第一个字（带工具调用的仍为 buffered —— 工具参数必须是完整 JSON 才能解析）

### 🧠 模型与思考档位

| 对外模型名 | 自动映射到网页上的模型（当前实测） | 说明 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 质量最高、较慢 |
| `gemini-flash` | 3.8 Flash | 快，推荐作为默认 |
| `gemini-flash-lite` | 3.5 Flash-Lite | 最轻最快，Pro/Flash 被限额时的兜底 |
| `gemini-argon` | 4 Argon | 面向复杂任务；**账号真的有 Argon 时才会列出** |

- **映射是自动的**：每个账号的心跳会报出它当前真实可用的网页模型，对外名字固定不变、内部自动对上网页当前的那一代（Google 换代时不用改客户端）。
- **`gemini-flash-thinking` 已下线**：它只是"flash + 思考模式"的假模型，思考现在是每个模型都有的档位（见下）。为兼容老客户端，`gemini-flash-thinking`、`gemini-2.5-flash-thinking`、`gemini-2.0-flash-thinking` 以及内部名 `gemini-3-flash-thinking*` **仍然可以调**（隐藏别名，等同 `gemini-flash`），只是不再出现在任何模型列表里；想要思考内容请改传档位参数。
- **思考三档**：`low` / `medium` / `high`，对应网页上的低 / 中 / 高三档（实测 `high` 想得最深、也最慢；`low` 与 `medium` 的差别在实测里分不太开）。
- **默认档 `low`**：客户端**没传**思考参数时，用「默认思考档位」（环境变量 `DEFAULT_THINKING_LEVEL`，或面板「设置 → 思考」，保存即时生效、无需重启），出厂 `low`。
  - ⚠️ **速度代价**：实测默认 `low` 比不思考**平均每个请求多约 5 秒**（flash 简单题 6.5 / 8.8 秒 → 8.6 / 16.6 秒）。最看重速度就把默认档设成 **`off`**（不思考、最快，与旧版不传参数时发给上游的请求完全一样）。前置代理有首字节超时的（如 EdgeOne 免费版 15 秒）尤其要留意非流式请求。
  - 按默认档替客户端开的思考**只用于生成，绝不回传**：响应里不会多出 `reasoning_content` / `thinking` 块 / 思考 part，结构与不思考时逐字段一致（严格校验的客户端不会因此报错）。客户端**明确传了**档位才回传思考内容。
- **总闸** `EXTENDED_THINKING_ENABLED=false`：一律不思考，连客户端明确要求的思考也忽略（高级/兼容项，一般不用碰；面板上只在它被关掉时才显示）。
- 面板「模型测试」页用**档位选择**（低 / 中 / 高，默认低）代替原来的「思考」勾选框，所选档位以 `reasoning_effort` 发出，思考过程显示在回答上方。

各协议的档位写法（**不传则一律用默认档、且不回传思考**）：

| 协议 | 参数 | 取值 → 档位 |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`；`none` / `minimal` → low，`xhigh` → high；认不出的值 → high（不报错） |
| OpenAI `/v1/responses` | `reasoning.effort`（或顶层 `reasoning_effort`） | 同上 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`：`N<2048` → low，`2048–4095` → medium，`≥4096` → high；`{"type":"adaptive"}` 或 budget 无效 → high；`{"type":"disabled"}` → 不思考；认不出的 `type` 按没传处理 |
| Gemini 原生 `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`：`LOW` / `MEDIUM` / `HIGH`（`MINIMAL` → low，未指定 → high）；`thinkingBudget`：`0` → 不思考，`-1`（自动）→ high，`>0` 按 2048 / 4096 切点分档；两者都给时以 `thinkingLevel` 为准；`includeThoughts: true` 才在响应里回传思考（`"thought": true` 的 part） |

### 🔐 安全与认证

- API Key 自动生成（`sk-` 前缀 + 32 位随机字符串）
- 支持 `Authorization: Bearer` 和 `x-api-key` 两种认证方式
- 首次部署自动生成密钥，用户可自定义修改
- **访问密钥**：管理员可签发多把可分发的入站密钥，每把独立配置有效期（支持「首次使用起算」的惰性激活）、请求数上限、绑定账号与可用模型，随时可停用或吊销
- `.env` 的 `API_KEY` 始终全权有效，访问密钥只是**附加**的一层；且访问密钥只能调业务 API，访问不到 `/admin/*`（详见下文 [🔑 访问密钥](#-访问密钥)）

### 🔄 多账号轮询与 Cookie 自愈

- **多账号负载均衡**：支持 round-robin（轮询）和 failover（故障转移）两种策略
- 每账号独立并发控制，避免单账号过载
- 连续失败自动标记不健康，自动跳过故障账号
- 后台自动轮换 Cookie，无感续期
- 热更新 Cookie API，无需重启容器
- 支持通过 API 动态添加/移除账号
- 健康检查历史记录，为 Web 面板提供数据支撑
- **Cookie 轮换循环启动即跑**：以前只有「启动时拿不到 token」才会拉起轮换循环，正常启动的网关从不轮换、Cookie 过几小时就死（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）；现在无条件常驻
- **识别 HTTP 200 里的拒绝块**：Gemini 有时在 200 响应正文里塞一个拒绝块（限流 / 会话过期 / 上下文超长 / 人机验证）。以前这类请求表现为「空回复」且不触发任何自愈，现在会被转成明确错误并走冷却 + 换号重试，可用 `BARD_ERROR_CODES` 为具体 code 配上语义

### 🛡 反检测与协议伪装

- **TLS 指纹一致性**：UA、Sec-Ch-Ua、curl_cffi impersonate 三者版本始终同步（当前 Chrome 124）
- **动态请求头**：按 Chrome 真实顺序排列，根据请求类型（导航 GET / API POST）动态调整 Sec-Fetch-* 值
- **完整 Cookie 持久化**：自动捕获所有响应 Cookie 并持久化到磁盘，跨重启保留
- **Cookie 域名隔离**：每次请求前清除 session 内部 cookie，防止跨域名累积冲突
- **Chrome 版本自动同步**：每 24 小时轮询 Google 版本 API，检测到新版本自动更新指纹配置
- **请求时间抖动**：模拟人类操作间隔（导航 200-800ms / API 50-300ms / Cookie 轮换 1-3s）
- **版本降级策略**：当 curl_cffi 不支持最新 Chrome 版本时，自动使用最近的可用版本

### 🖥 Web 管理面板

- 中文可视化管理界面，API Key 登录认证
- 右上角控制栏：主题切换、服务重启、登出
- 仪表盘：运行时间实时计时、二维码卡片（支持图片放大）、系统信息（版本/Python/OS/内存/CPU/PID/运行模式）、配置管理（轮换策略/并发上限）、账号状态总览、可用模型列表
- **热更新资源**：`api/` 目录 volume 挂载，二维码图片和文字配置修改后刷新页面即生效，无需重建容器
- 账号管理：添加/删除账号、单独更新 Cookie、健康检测
- **设置页面**：可视化管理运行时配置（性能、速率限制、健康检查、账号管理等），修改即时生效并传播到运行时
- **模型映射**：将请求中的模型名映射到实际使用的模型（如 gpt-4o → gemini-2.5-pro）
- **访问密钥**：签发/编辑/停用/吊销可分发的入站密钥，列表直接显示状态、用量与权限范围（与下面的「API Key 管理」无关，那管的是第三方**出站** Key）
- **API Key 管理**：集中管理第三方大模型 API Key（OpenAI/Anthropic/Gemini/OpenRouter/自定义），支持导入导出
- Playground：在线测试 API 请求
- 实时日志：结构化表格展示，支持方向过滤、文本搜索、分页（每页15条）、JSON 详情面板，日志持久化到磁盘（重启不丢失）
- 深色/浅色主题切换，响应式移动端适配

### 🔀 统一转发引擎

- 请求模型不在 Gemini Web 可用列表时，自动从 API Key 池匹配并转发到对应 Provider
- OpenAI 兼容格式直接转发（含流式），Anthropic 格式双向转换
- `/openai/v1/models` 自动聚合 Gemini Web 模型 + API Key 池中的第三方模型
- 一个接口、一个 Key 调用所有大模型
- 第三方自动兜底（`FALLBACK_ENABLED`，默认关）：任意 Gemini 模型报错/返回空响应时，自动改用 API Key 池中的第三方模型原生重试，客户端无感、仍只用一个模型名；默认自动选用池中所有"适合聊天"的第三方（排除 image/video 等非聊天模型）、随机轮询、失败换下一个，`FALLBACK_MODELS` 可选精确指定

### ⚡ 高性能架构

- 基于 Python asyncio + curl_cffi，全链路非阻塞
- Chrome TLS 指纹伪装 + 版本自动跟进，session 存活时间大幅延长
- Pydantic 强类型校验，请求参数自动验证
- 模块化设计，每个 API 格式独立路由文件
- 失败自动重试，指数退避策略

---

## 📋 系统要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 推荐 3.12，低版本未测试 |
| Docker | 20.10+ | 可选，推荐使用 Docker 部署 |
| Google 账号 | — | 需能正常访问 [gemini.google.com](https://gemini.google.com) |
| 浏览器 | Chrome / Edge | 用于获取 Cookie（仅部署时需要） |

> [!TIP]
> 使用 Docker 部署无需本地安装 Python 环境，只需 Docker 和有效的 Cookie 即可。

---

## ⚡ 快速部署

> 📖 详细部署文档：[DEPLOY.md](DEPLOY.md)

> **前置条件**：你需要一个能正常使用 Gemini 的 Google 账号。

### 1. 获取 Cookie

1. 使用 Chrome 或 Edge 浏览器访问 [gemini.google.com](https://gemini.google.com)
2. 登录你的 Google 账号，确保能正常使用 Gemini 对话
3. 按 `F12` 打开开发者工具
4. 点击顶部 **Application**（应用程序）标签
5. 左侧栏找到 **Cookies** -> 点击 `https://gemini.google.com`
6. 在 Cookie 列表中找到以下两个值：

| Cookie 名称 | 说明 |
|-------------|------|
| `__Secure-1PSID` | 以 `g.` 开头的长字符串，通常几十个字符 |
| `__Secure-1PSIDTS` | 较短的字符串 |

7. 建议在无痕模式下操作，获取到所需值后立即关闭窗口，避免页面刷新导致 Cookie 轮换失效

> [!TIP]
> 可以在搜索框中输入 `__Secure-1P` 快速过滤。双击 Value 列即可复制完整值。

> [!WARNING]
> Cookie 有有效期，过期后需要重新获取。如果服务突然无法使用，优先检查 Cookie 是否失效。

### 2. Docker 部署

```bash
# 克隆仓库
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 创建环境变量文件
cp .env.example .env
```

编辑 `.env` 文件，填入你的 Cookie：

```env
GEMINI_PSID=g.a000xxx...（粘贴你的 __Secure-1PSID 完整值）
GEMINI_PSIDTS=sidts-xxx...（粘贴你的 __Secure-1PSIDTS 完整值）
```

> [!IMPORTANT]
> 注意事项：
> - 值不需要加引号
> - 不要有多余的空格或换行
> - 确保复制的是完整值，不要遗漏末尾字符

启动服务：

```bash
docker compose up -d
```

查看日志确认启动成功：

```bash
docker compose logs -f
# 看到 "Account pool ready: 1/1 active" 表示账号池就绪
# 看到 "SNlM0e not found" 表示 Cookie 无效，需要重新获取
```

### 多账号配置（可选）

如需使用多个 Google 账号实现负载均衡，创建 `accounts.json`：

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "主账号"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "备用账号"
    }
  ]
}
```

> [!TIP]
> 不创建 `accounts.json` 时，服务自动使用 `.env` 中的单账号模式。也可以通过 `POST /admin/accounts` API 在运行时动态添加账号。

### Cookie 自动保活

gemini2api 内置 Cookie 自动轮换机制：默认每 30 分钟（`REFRESH_INTERVAL`，硬下限 10 分钟）通过 Google RotateCookies API 刷新 `__Secure-1PSIDTS`，配合 batchexecute 心跳模拟浏览器活跃行为，延长 session 寿命。

> [!IMPORTANT]
> **`REFRESH_INTERVAL` 的默认值已由 5 分钟改为 30 分钟，并在代码里夹了 10 分钟的硬下限**（配得更小会被自动抬到 10 并在启动日志里点名）。
> 原因：以前轮换循环**只在「启动时拿不到 token」的情况下才会被拉起**，正常启动的网关其实从不轮换，Cookie 过几个小时就死（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）。现在改成启动就常驻，同一个间隔下对 Google 的后台请求量会涨到约 3.5 倍，所以间隔必须相应放宽——轮换太勤在 Google 看来很像自动化，容易触发风控、反而把 session 搞死。

如需手动更新 Cookie，可通过 Web 面板的「账号管理」→「更新 Cookie」操作，无需重启服务。

> [!NOTE]
> Cookie 寿命受 Google 风控策略影响，数据中心 IP 通常可维持数小时。如 Cookie 频繁过期，建议使用住宅 IP 或增加账号数量做轮询。

### 3. 验证

```bash
# 健康检查
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# 查看可用模型（需要 API Key，首次启动在日志中查看）
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-你的API密钥"

# 发送测试请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

看到 AI 回复的文字即部署成功。如果返回 401，请检查 API Key 是否正确。

---

## 🧪 接入示例

> [!NOTE]
> 所有 API 请求都需要携带 API Key。支持两种方式：
> - `Authorization: Bearer sk-xxx`（推荐，兼容 OpenAI/Claude SDK）
> - `x-api-key: sk-xxx`
>
> API Key 在首次启动时自动生成并写入 `.env` 文件，可在日志中查看或手动修改。

<details>
<summary><b>OpenAI SDK（Python）</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "用三句话解释相对论"}],
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
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "写一个快速排序的Python实现"}]
)
print(msg.content[0].text)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
# 非流式请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}]}'

# 流式请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

</details>

<details>
<summary><b>函数调用</b></summary>

```python
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "北京今天天气怎么样"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气",
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

## 📡 API 端点

> 📖 详细 API 文档：[API.md](API.md)

### OpenAI 兼容（`/openai/v1`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 可用模型列表 |
| POST | `/chat/completions` | 对话补全（支持流式 + 工具调用） |
| POST | `/responses` | OpenAI Responses API（文本/流式/工具调用，Codex CLI 等新客户端使用） |

### Claude 兼容（`/claude/v1`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表 |
| GET | `/models/{id}` | 模型详情 |
| POST | `/messages` | 消息生成（支持流式 + 工具调用） |
| POST | `/messages/count_tokens` | Token 计数估算 |

### Gemini 原生（`/gemini/v1beta`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表 |
| POST | `/models/{m}:generateContent` | 内容生成 |
| POST | `/models/{m}:streamGenerateContent` | 流式生成（Chunked JSON） |

### 管理接口（`/admin`）

> 完整管理端点（含请求/响应示例）见 [API.md](API.md)，下表为完整列表。

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/status` | 服务状态（账号池概览 + 轮询策略） |
| GET | `/system-info` | 系统信息（版本/Python/OS/内存/CPU/PID/运行模式） |
| GET | `/accounts` | 所有账号列表及状态 |
| POST | `/accounts` | 动态添加新账号 |
| DELETE | `/accounts/{id}` | 移除指定账号 |
| GET | `/accounts/{id}/check` | 检测单个账号状态 |
| GET | `/check-account` | 检测所有账号状态 |
| POST | `/reload-cookies` | 热更新 Cookie（无需重启容器） |
| PUT | `/accounts/{id}/cookies` | 更新指定账号的 Cookie |
| GET | `/health-history` | 最近健康检查记录 |
| GET | `/usage-stats/summary` | 用量统计概览 |
| GET | `/usage-stats/history` | 历史趋势数据 |
| GET | `/settings` | 获取当前可编辑配置（分组返回） |
| POST | `/settings` | 批量更新配置（热更新内存 + 写入 `data/settings-overrides.json`，同时照写 `.env`） |
| GET | `/api-keys` | API Key 列表（密钥脱敏） |
| GET | `/api-keys/catalog` | Provider 目录（内置模型列表） |
| POST | `/api-keys` | 添加 API Key |
| DELETE | `/api-keys/{id}` | 删除 API Key |
| PATCH | `/api-keys/{id}/status` | 切换 Key 状态（启用/禁用） |
| PATCH | `/api-keys/{id}/label` | 修改 Key 标签 |
| POST | `/api-keys/import` | 批量导入 Key |
| GET | `/api-keys/export` | 导出所有 Key（默认脱敏，`?reveal=true` 取明文） |
| POST | `/api-keys/batch-delete` | 批量删除 |
| POST | `/api-keys/models` | 探测某 Provider/base_url 下可用模型列表 |
| GET | `/verify` | 验证 API Key 有效性（登录用） |
| POST | `/restart` | 重启服务（面板右上角一键重启） |
| GET | `/check-update` | 检查是否有新版本 |
| POST | `/update` | 触发更新到最新版本 |
| GET | `/logs` | 结构化日志分页查询 |
| GET | `/logs/state` | 日志记录状态 |
| POST | `/logs/state` | 更新日志记录状态 |
| POST | `/logs/clear` | 清空日志 |
| GET | `/logs/{id}` | 单条日志详情 |
| GET | `/model-mapping` | 获取所有模型映射 |
| POST | `/model-mapping` | 添加/更新模型映射 |
| DELETE | `/model-mapping/{alias}` | 删除模型映射 |
| GET | `/web-chats` | 列出账号在 Gemini 网页端堆积的会话（只读） |
| POST | `/cleanup-web-chats` | 手动触发清理超期网页会话（后台异步执行） |

> 访问密钥的 6 个 `/admin/access-keys` 端点见下文 [🔑 访问密钥](#-访问密钥)。

---

## 🔑 访问密钥

除了 `.env` 里那把全权 `API_KEY`，管理员还可以签发任意多把**可分发**的访问密钥：每把独立配置有效期、请求数上限、可用账号与可用模型，发给不同的人，随时可以单独停用或吊销。面板新增「访问密钥」页做可视化管理，后端对应 `/admin/access-keys` 系列端点。

密钥存放在 `data/access_keys.json`（`data/` 是 docker-compose 的持久化 bind mount），重启不丢。

### 每把密钥可配置的字段

| 字段 | 说明 |
|------|------|
| `name` | 标签，用来记住这把 key 发给了谁（留空则显示为 `key-{id}`） |
| `enabled` | 启停开关。停用后持有人立刻 401，但密钥仍在列表里，可随时恢复 |
| `expires_at` | 绝对过期时间（ISO8601），到点失效 |
| `duration_days` | 有效天数，**惰性激活**：发出去不计时，持有人第一次用它发请求才开始算 N 天 |
| `request_limit` | 请求数上限，累计达到即失效（可用「重置用量」清零后继续用） |
| `bound_account_ids` | 绑定账号，只允许用指定的 Gemini 账号（留空 = 不限制） |
| `allowed_models` | 允许模型，只允许调用指定的模型名（留空 = 不限制） |

`expires_at` 与 `duration_days` 二选一，两者都留空则永不过期。

### 密钥状态

| 状态 | 含义 |
|------|------|
| 有效 | 可正常调用 |
| 已停用 | `enabled` 被管理员关掉 |
| 未激活 | 配了 `duration_days` 但还没被用过，计时尚未开始 |
| 已过期 | 已过 `expires_at` |
| 已超额 | `request_count` 达到了 `request_limit` |

判定按「已停用 → 已过期 → 已超额 → 未激活 → 有效」的优先级依次短路。

### 端点

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/admin/access-keys` | 列出所有访问密钥（含状态、用量、权限范围） |
| GET | `/admin/access-keys/options` | 面板签发表单的候选项（账号池里的账号 + 对外可见的模型名） |
| POST | `/admin/access-keys` | 签发密钥，`count` 可批量（上限 50） |
| PATCH | `/admin/access-keys/{id}` | 修改配置（清空某字段要用 `clear` 数组，见下） |
| DELETE | `/admin/access-keys/{id}` | 吊销密钥 |
| POST | `/admin/access-keys/{id}/reset-usage` | 重置请求计数 |

```bash
# 签发 1 把：发出去 7 天有效（首次使用才开始算）、最多 500 次请求、只能用 flash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"name":"张三","duration_days":7,"request_limit":500,"allowed_models":["gemini-flash"]}'

# 批量签发 20 把同样配置的密钥（名称自动编号为 试用-1 … 试用-20）
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"name":"试用","count":20,"duration_days":3}'

# 列出所有密钥
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-你的API密钥"

# 停用第 3 把
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"enabled":false}'

# 解除第 3 把的请求数上限和模型限制：JSON 里传 null 表示「不改」，
# 要清空字段必须把字段名放进 clear 数组
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"clear":["request_limit","allowed_models"]}'

# 重置用量计数
curl -X POST http://localhost:5918/admin/access-keys/3/reset-usage \
  -H "Authorization: Bearer sk-你的API密钥"
```

### ⚠ 三条重要边界

> [!IMPORTANT]
> **1. `.env` 的 `API_KEY` 仍然全权有效。** 访问密钥是**附加**的一层，不是替代：`API_KEY` 命中后立刻放行，不查密钥库、不计任何用量。**一把访问密钥都不签发时，鉴权行为与旧版完全一致。**
>
> **2. 访问密钥只能调业务 API，绝对访问不到 `/admin/*`。** 管理面仍然只由 `API_KEY` / `ADMIN_API_KEY` 把守。所以可以放心把访问密钥发给外人——他拿不到账号 Cookie、改不了配置，也看不到别人的密钥。
>
> **3. 每个业务请求都会 +1，包括 `GET /v1/models`。** 计数是在鉴权入口原子 +1 的，单调不减、不退还（上游报错也算）。有些客户端每轮对话前都会列一次模型，等于**一轮消耗 2 次**——设 `request_limit` 时记得留余量。

---

## ⚙ 配置说明

> [!IMPORTANT]
> **面板改过的设置项优先级高于环境变量。** 在 Web 面板「设置」页保存过的项会写进
> `data/settings-overrides.json`（`data/` 是 docker-compose 的持久化 bind mount），
> 并在每次启动时回放、**覆盖**下表中对应的环境变量。
> 这是刻意的：面板上关掉 `LOG_BODIES_ENABLED` 之后，`docker compose restart` 不能把它
> 重新打开。
>
> 所以：**改了 `.env` 重启却不生效**，多半就是该字段被面板覆盖了。启动日志里有一行
> `Applied N panel setting override(s) from data/settings-overrides.json: ...` 会点名
> 具体字段；删掉 `data/settings-overrides.json` 即可把控制权交回环境变量。

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 浏览器 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 浏览器 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自动生成 | API 访问密钥（`sk-` 开头，留空则首次启动自动生成） |
| `REFRESH_INTERVAL` | ❌ | `30` | Cookie 刷新周期（分钟，最小 10） |
| `MAX_RETRIES` | ❌ | `3` | 失败重试次数（指数退避） |
| `PORT` | ❌ | `5918` | 服务端口 |
| `LOG_LEVEL` | ❌ | `info` | 日志级别（debug/info/warning/error） |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | 启用限流 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 限流窗口（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | 窗口内最大请求数 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | 启用定时账号状态检测 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | 检测间隔（分钟） |
| `ACCOUNTS_FILE` | ❌ | `accounts.json` | 多账号配置文件路径（不存在则使用环境变量单账号模式） |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 轮询策略：`round-robin`（轮询）/ `failover`（故障转移） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `8` | 每账号最大并发请求数 |
| `ACQUIRE_TIMEOUT` | ❌ | `60.0` | 并发满载时排队等待可用槽位的上限（秒），等不到才报错 |
| `SAME_ACCOUNT_5XX_RETRIES` | ❌ | `1` | 遇 5xx 时同账号快速重试次数（不长退避），仍失败则 failover 换号 |
| `FAILOVER_COOLDOWN` | ❌ | `30.0` | 被 5xx 限流的账号进入冷却的时长（秒），期间不优先选 |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | 指纹配置文件路径 |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | 启用 Chrome 版本自动同步 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | 版本同步间隔（小时） |
| `JITTER_ENABLED` | ❌ | `true` | 启用请求时间抖动（模拟人类行为） |
| `USAGE_STATS_ENABLED` | ❌ | `true` | 启用用量统计（时序快照 + 持久化） |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | 快照采集间隔（秒） |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | 历史数据保留天数 |
| `MODEL_WHITELIST` | ❌ | — | 模型白名单（逗号分隔，为空则不过滤；非空时过滤各 `/models` 列表） |
| `CHAT_CLEANUP_ENABLED` | ❌ | `true` | 启用 Gemini 网页端会话自动清理 |
| `CHAT_CLEANUP_KEEP_HOURS` | ❌ | `24.0` | 网页会话保留时长（小时），超过则清理 |
| `CHAT_CLEANUP_INTERVAL_HOURS` | ❌ | `6.0` | 自动清理任务运行间隔（小时） |
| `CHAT_CLEANUP_SKIP_PINNED` | ❌ | `true` | 清理时跳过置顶会话 |
| `ADMIN_API_KEY` | ❌ | — | 管理面板/`/admin` 独立鉴权 key（留空则回退用 `API_KEY`） |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | CORS 允许来源（逗号分隔，`*` 表示全部） |
| `CORS_ALLOW_CREDENTIALS` | ❌ | `true` | CORS 是否允许携带凭据 |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | ❌ | `=s2048` | 生图代下载尺寸后缀（`=s0` 为全分辨率原图） |
| `IMAGE_DOWNLOAD_TIMEOUT` | ❌ | `25.0` | 单次图片下载 HTTP 超时（秒） |
| `FALLBACK_ENABLED` | ❌ | `false` | 启用 Gemini→第三方兜底：任意 Gemini 模型（flash/pro/thinking）报错或返回空响应时，自动改用 API Key 池中的第三方模型原生重试 |
| `FALLBACK_MODELS` | ❌ | — | 兜底模型（逗号分隔、按序尝试）；留空=自动选用池中所有"适合聊天"的第三方（按名称排除 image/video/audio/embedding 等非聊天模型）并随机轮询、一个失败（报错/空）就换下一个 |
| `DEFAULT_THINKING_LEVEL` | ❌ | `low` | 客户端没指定思考参数时用的档位：`off` / `low` / `medium` / `high`。`low` 实测每请求平均多约 5 秒，`off` 最快；面板「设置 → 思考」可即时切换。按默认档开的思考不回传给客户端 |
| `EXTENDED_THINKING_ENABLED` | ❌ | `true` | 思考总闸（高级/兼容项）：`false` = 四个协议一律不思考，连客户端明确要求的也忽略 |
| `THIRDPARTY_FAILOVER_COOLDOWN` | ❌ | `180` | 第三方「同名多家」故障切换的坏家冷却秒数（0 关闭） |
| `BARD_ERROR_CODES` | ❌ | — | Gemini 在 **HTTP 200** 正文里返回的拒绝块的 code→语义对照表，形如 `1152=rate_limit,404=session_expired`，分类可取 `rate_limit` / `session_expired` / `context_too_long` / `captcha`。**留空时所有拒绝块按未知处理（冷却该账号 + 换号重试），这是刻意的安全兜底**；配上之后各类才有专门处理（会话过期触发 Cookie 自愈、上下文超长直接回 400 不重试、人机验证让出该账号） |
| `GENERATE_TIMEOUTS` | ❌ | — | 非流式生成超时按模型族覆盖，形如 `pro=300,flash=120`；留空用内置分层（flash-lite 60 / flash 120 / pro 300 / argon 300，认不出的族回落 60） |
| `GENERATE_TIMEOUT_IMAGE` | ❌ | `180` | 疑似生图请求的非流式超时（秒）。与模型族档位**取大**，只作用于非流式路径 |
| `TOKEN_PRICES` | ❌ | — | 访问密钥用量的**美元估算**价格表，形如 `gemini-pro=2.0/12.0,gemini-flash=0.75/3.75`（公开模型名=输入价/输出价，单位 USD / 百万 token）。留空用内置默认值；写错的条目静默忽略，配不到价格的模型面板显示 `—`。**只统计、不参与任何限额判定**，且不是账单（本服务走网页版、本身不花钱） |

---

## ⚠ 注意事项

1. **Cookie 有效期**：Google Cookie 会定期过期（通常数小时到数天不等）。服务内置自动刷新机制，但如果账号被登出或密码变更，需要重新获取 Cookie。

2. **流式输出**：所有 API 端点默认流式返回。设置 `stream: false` 时，服务内部仍以流式方式接收数据，收集完毕后一次性返回完整 JSON。

3. **模型可用性**：可用模型列表取决于你的 Google 账号权限。免费账号和 Gemini Advanced 账号看到的模型不同，服务启动时会自动检测。

4. **请求频率**：即使关闭了内置限流（`RATE_LIMIT_ENABLED=false`），Google 侧仍有频率限制。高频请求可能触发验证码或临时封禁，建议合理控制调用频率。

5. **网络环境**：部署服务器需能直接访问 `gemini.google.com`，部分地区可能需要配置代理。

6. **非流式超时与前置代理**：非流式（`stream: false`）请求的超时按模型族分层——flash-lite 60 秒、flash 120 秒、pro 与 argon 300 秒（可用 `GENERATE_TIMEOUTS` 覆盖；疑似生图取 `GENERATE_TIMEOUT_IMAGE`，默认 180 秒），超时也不再重试三遍。注意这整段时间里连接上是**零字节输出**，所以它是**首字节**超时而不是空闲超时：**pro 非流式最长要干等 300 秒，会超过常见前置代理的首字节上限**（EdgeOne 免费版 15 秒，不少反向代理默认 60 秒），客户端拿到的将是代理的 504 而不是本服务的错误体。这类场景建议直接用流式请求。 开了思考的请求还要再多几秒（默认 `low` 实测平均每请求多约 5 秒）。

---

## 🗺 开发路线

- [x] OpenAI / Claude / Gemini 三格式兼容
- [x] 流式响应 + 函数调用
- [x] Deep Research 深度研究
- [x] Docker 部署
- [x] API Key 认证
- [x] Cookie 热更新 API
- [x] 账号状态定时检测
- [x] 多账号轮询（负载均衡）
- [x] Web 管理面板
- [x] 反检测与协议伪装
- [x] 设置页面（可视化配置管理）
- [x] API Key 管理（第三方大模型 Key 集中管理）
- [x] 统一转发引擎（一个接口调用所有大模型）
- [x] 模型映射（别名→实际模型名）
- [x] 自动清理网页端堆积会话（定时删除旧会话，置顶保留）
- [ ] 图片/文件上传支持
- [x] [issues #2](https://github.com/xwteam/gemini2api/issues/2) 自定义 Gemini Gem 支持（管理面板列出/新建/改/删 + 暴露为模型名调用）
- [x] [issues #6](https://github.com/xwteam/gemini2api/issues/6) [#7](https://github.com/xwteam/gemini2api/issues/7) 原生 Gemini 扩展思考支持（`reasoning_effort` 开启，思考过程逐帧流式、先于答案显示 + 模型测试面板「思考」开关 + 一键关不影响普通聊天）
- [x] API 管理页 Gemini 兜底一键开关（即时开/关兜底链并持久化，无需改 .env 重启）

---

## ☕ 赞赏 & 共享

觉得有帮助？请作者喝杯咖啡，或加入微信交流群获取使用帮助。完整内容请查看 [SPONSORS.md](SPONSORS.md)。

欢迎 PR 和 Issue。

1. Fork 本仓库
2. 创建分支 `git checkout -b feature/your-feature`
3. 提交代码 `git commit -m "feat: add something"`
4. 推送并创建 Pull Request

---

## 🙏 致谢

感谢所有在 [Issues](https://github.com/xwteam/gemini2api/issues) 里提交 bug 复现、日志、兼容性反馈和功能建议的用户。这些反馈直接推动了 Cookie 保活、多账号轮换、模型选择、多语言支持、Web 面板等核心能力的迭代。

---

## 📄 许可协议

本项目采用 [非商业许可 (Non-Commercial)](../../LICENSE)：

- **允许**：个人学习、研究、自用部署
- **禁止**：任何形式的商业用途，包括但不限于出售、转售、收费代理、商业产品集成

本项目与 Google 无关联。使用者需自行承担风险并遵守 Google 的服务条款。

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
