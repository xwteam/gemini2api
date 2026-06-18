<div align="center">

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
  <img src="https://img.shields.io/badge/version-v1.6.14-success?style=flat-square" alt="Version">
</p>

<p>
  <a href="#-最近更新">最近更新</a> &bull;
  <a href="#-核心功能">核心功能</a> &bull;
  <a href="#-系统要求">系统要求</a> &bull;
  <a href="#-快速部署">快速部署</a> &bull;
  <a href="#-接入示例">接入示例</a> &bull;
  <a href="#-api-端点">API 端点</a> &bull;
  <a href="#-配置说明">配置说明</a> &bull;
  <a href="#-注意事项">注意事项</a> &bull;
  <a href="#-开发路线">开发路线</a>
</p>

<p>
  📖 文档语言：<a href="docs/zh-CN/README.md">简体中文</a> | <a href="docs/zh-TW/README.md">繁體中文</a> | <a href="docs/en/README.md">English</a> | <a href="docs/ja/README.md">日本語</a> | <a href="docs/ko/README.md">한국어</a>
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
> 由于 Google 风控策略限制，Cookie 会话目前约 2 小时后会被强制失效，暂未找到完美的长期保活方案。一个思路是用**本地浏览器（住宅 IP）**自动刷新并回传 Cookie —— 配套的浏览器插件 [**gemini2api-plugin**](https://github.com/xwteam/gemini2api-plugin) 正在尝试这个方向。如果您在这方面有经验或思路，非常欢迎通过 [Issue](https://github.com/xwteam/gemini2api/issues) 或 PR 分享，期待社区的智慧。

---

## 📝 最近更新

> 完整更新日志请查看 [CHANGELOG.md](CHANGELOG.md)，以下内容由 CI 自动同步。

| 日期 | 更新内容 |
|------|----------|
| 2026-06-19 03:01:44 | v1.6.16 - 🔧 稳定性与安全强化：修复深度研究接口必崩、第三方流式转发失效、账号槽位泄漏死锁、多账号模型解析串扰、间歇 "Client not ready"、限流配置未生效；🔒 安全加固：管理权限分离（可选 `ADMIN_API_KEY`）、API Key 日志脱敏、双 SSRF 防护、密钥导出/PSID 脱敏、凭据文件原子写、CORS 可配、恒定时间比较；🧪 新增自动化测试 + CI 门禁、面板无障碍/多语言增强。全程零回归（58 测试通过）|
| 2026-06-06 19:29:01 | v1.6.15 - 🧹 自动清理 Gemini 网页端会话：API 每次对话都会在网页端堆积会话记录，现在后台定时（默认每 6h）自动删除超过保留期（默认 24h）的旧会话，置顶会话保留；循环清理彻底清空堆积，重度账号也能清干净。设置面板可调（开关/保留时长/清理间隔/跳过置顶），5 语种 |
| 2026-06-02 20:16:19 | v1.6.14 - 🖼️ 生图意图识别补充意愿动词：「我想要一张…的图」「要一张图」「我需要一张海报」等用想要/要/需要表达的生图请求现在能正确识别、图片排在前面（之前会图在文字后或出现 http 残片）；仍要求图像名词+动词同现，不误判日常用语 |
| 2026-06-02 18:51:41 | v1.6.13 - 🖼️ 生图回复改为图片在前+紧凑排版（不再是大段文字+空行+图片）；生图意图识别大幅增强（画/生成/设计/做/来张…图、海报/logo/poster 等口语化请求都能正确生图并图片在前）；过滤 image_retrieval/image_collection 检索占位 URL，无有效图时给友好提示而非空内容 |
| 2026-06-02 16:37:57 | v1.6.12 - 🛠️ 修复 agent（如 Hermes）带 tools 时生图被压制、工具调用畸形 JSON 透传：检测到生图意图自动跳过工具模拟直接出图；工具调用多层容错解析（剥离 markdown/提取 JSON/容忍畸形），畸形不再透传；Gemini 原生接口工具调用正确返回 functionCall |
| 2026-06-02 13:04:39 | v1.6.11 - 🔁 503 智能 failover：Google 对数据中心 IP 间歇性 503 限流时，多账号自动切换到下一个可用账号重试（一个被限流立刻换号），被限流账号进入 30s 冷却但不标记失效；单账号 5xx 只快速重试不长退避空耗 |
| 2026-06-01 20:21:43 | v1.6.10 - ⚡ 真流式输出：三家接口改为真正的增量流式（首字一生成就推送，不再等整段生成完才假装逐字吐），聊天体感大幅提升；🚀 并发大幅提升：单账号并发 3→8，且满载时排队等待而非直接报错 No available accounts，agent 不再一并发就失败 |
| 2026-06-01 00:32:16 | v1.6.9 - 🖼️ 生成图片返回全分辨率原图：之前下载的是压缩缩略图（512px），现加 =s0 后缀拿原始尺寸（如 1408×768） |
| 2026-06-01 00:18:01 | v1.6.8 - 🖼️ 生图不再返回 googleusercontent 占位网址：该占位 URL 无实际意义，已从回复中过滤，生图只返回图片本身 |
| 2026-06-01 00:02:09 | v1.6.7 - 🖼️ 修复控制面板模型测试不显示图片：生成的图片现在直接渲染显示，不再显示成 markdown 文本/URL |
| 2026-05-31 23:41:15 | v1.6.6 - 🖼️ 生成图片本地托管：对话接口的生图结果改为返回可访问的本地 URL（/images/{id}），让 CLI/agent 客户端也能正常渲染显示（base64 在这类客户端无法显示）；图片定期自动清理 |
| 2026-05-31 22:36:53 | v1.6.5 - 🎨 AI 生成图片：新增 OpenAI 兼容 `/v1/images/generations` 接口（返回 b64_json）；三家对话接口检测到生成图片自动嵌入回复（markdown / image block / inlineData） |
| 2026-05-31 17:00:00 | v1.6.4 - 三家接口暴露标准裸路径（`/v1/chat/completions`、`/v1/messages`、`/v1beta/...`），主流 SDK 开箱即用；修复部署机制（compose 由 build 改 image，`docker compose pull` 真正生效） |
| 2025-05-31 14:10:00 | v1.6.3 - 图片/文件上传支持（OpenAI/Claude/Gemini 多模态）；模型改用网页版真实数据 + 对外固定稳定名（gemini-pro/flash/flash-thinking）；重启不再丢 Cookie |
| 2025-05-19 20:00:00 | v1.6.2 - 会话5分钟无操作自动过期登出 |
| 2025-05-17 23:20:00 | 模型列表统一为用户友好名称，新增思考模式（gemini-2.5-flash-thinking）和 Pro 模式，Playground 对话上下文修复 |
| 2025-05-17 22:30:00 | 容器时区修正为 Asia/Shanghai，日志显示北京时间 |
| 2025-05-17 17:00:00 | 模型选择修复（通过 x-goog-ext header 真正切换模型），支持 gemini-3 全系列 + 旧版别名兼容 |
| 2025-05-17 15:30:00 | 对话上下文持久化（混合模式）：Gemini 原生 conversation_id 多轮续接 + 本地备份 + 自动 fallback |
| 2025-05-17 09:00:00 | 新增多语言切换（简体中文/繁體中文/English/日本語/한국어），确认弹窗美化为自定义 Modal |
| 2025-05-17 08:30:00 | 多语言覆盖全部页面（仪表盘/账号/日志/测试/统计/API/设置），修复 MutationObserver 无限循环 |
| 2025-05-16 19:00:00 | 新增服务重启按钮（右上角控制栏），支持一键重启服务 |

---

## 🌟 核心功能

> 📖 详细使用文档：[简体中文](docs/zh-CN/USAGE.md) | [繁體中文](docs/zh-TW/USAGE.md) | [English](docs/en/USAGE.md) | [日本語](docs/ja/USAGE.md) | [한국어](docs/ko/USAGE.md)

### 🔌 三合一协议兼容

- 一个服务同时提供 OpenAI、Claude、Gemini 三种 SDK 格式
- SSE 流式输出（OpenAI / Claude）+ Chunked JSON（Gemini）
- 函数调用（Function Calling）三种格式均支持
- Deep Research 多步骤深度研究

### 🔐 安全与认证

- API Key 自动生成（`sk-` 前缀 + 32 位随机字符串）
- 支持 `Authorization: Bearer` 和 `x-api-key` 两种认证方式
- 首次部署自动生成密钥，用户可自定义修改

### 🔄 多账号轮询与 Cookie 自愈

- **多账号负载均衡**：支持 round-robin（轮询）和 failover（故障转移）两种策略
- 每账号独立并发控制，避免单账号过载
- 连续失败自动标记不健康，自动跳过故障账号
- 后台自动轮换 Cookie，无感续期
- 热更新 Cookie API，无需重启容器
- 支持通过 API 动态添加/移除账号
- 健康检查历史记录，为 Web 面板提供数据支撑

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
- **API Key 管理**：集中管理第三方大模型 API Key（OpenAI/Anthropic/Gemini/OpenRouter/自定义），支持导入导出
- Playground：在线测试 API 请求
- 实时日志：结构化表格展示，支持方向过滤、文本搜索、分页（每页15条）、JSON 详情面板，日志持久化到磁盘（重启不丢失）
- 深色/浅色主题切换，响应式移动端适配

### 🔀 统一转发引擎

- 请求模型不在 Gemini Web 可用列表时，自动从 API Key 池匹配并转发到对应 Provider
- OpenAI 兼容格式直接转发（含流式），Anthropic 格式双向转换
- `/openai/v1/models` 自动聚合 Gemini Web 模型 + API Key 池中的第三方模型
- 一个接口、一个 Key 调用所有大模型

### ⚡ 高性能架构

- 基于 Python asyncio + curl_cffi，全链路非阻塞
- Chrome TLS 指纹伪装 + 版本自动跟进，session 存活时间大幅延长
- Pydantic 强类型校验，请求参数自动验证
- 模块化设计，每个 API 格式独立路由文件
- 失败自动重试，指数退避策略

---

## 🏗 技术架构

```
                           Gemini2API
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Client (OpenAI SDK / Claude SDK / Gemini SDK / cURL)       │
│       |                                                     │
│  POST /v1/chat/completions   (或 /openai/v1/...)            │
│  POST /v1/messages           (或 /claude/v1/...)            │
│  POST /v1beta/models/:m:generateContent (或 /gemini/...)    │
│       |                                                     │
│       v                                                     │
│  +-----------+    +----------------+    +---------------+   │
│  |  Routes   |--->|  Translation   |--->| Account Pool  |   │
│  | (FastAPI) |    | Multi->Gemini  |    |  (负载均衡)   |   │
│  +-----------+    +----------------+    +---------------+   │
│                                               |             │
│                                    ┌──────────┼────────┐    │
│                                    v          v        v    │
│                               Account-0  Account-1   ...   │
│                                (Client)   (Client)          │
│                                                             │
│  +-----------+    +----------------+    +---------------+   │
│  |   Auth    |    | Fingerprint    |    | Health Check  |   │
│  |  API Key  |    | TLS+UA+Header  |    |  Scheduled    |   │
│  +-----------+    +----------------+    +---------------+   │
│                                                             │
│  +-----------+    +----------------+    +---------------+   │
│  |  Cookie   |    | Version Sync   |    |   Jitter      |   │
│  | Persist   |    | Chrome Auto    |    | Human-like    |   │
│  +-----------+    +----------------+    +---------------+   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                           |
              Fingerprint Layer (curl_cffi)
          Chrome TLS + 动态 UA + 完整 Cookie
                           |
                           v
                   gemini.google.com
             /BardChatUi/StreamGenerate
```

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

> 📖 详细部署文档：[简体中文](docs/zh-CN/DEPLOY.md) | [繁體中文](docs/zh-TW/DEPLOY.md) | [English](docs/en/DEPLOY.md) | [日本語](docs/ja/DEPLOY.md) | [한국어](docs/ko/DEPLOY.md)

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

gemini2api 内置 Cookie 自动轮换机制：每 5 分钟通过 Google RotateCookies API 刷新 `__Secure-1PSIDTS`，配合 batchexecute 心跳模拟浏览器活跃行为，延长 session 寿命。

如需手动更新 Cookie，可通过 Web 面板的「账号管理」→「更新 Cookie」操作，无需重启服务。

> [!NOTE]
> Cookie 寿命受 Google 风控策略影响，数据中心 IP 通常可维持数小时。如 Cookie 频繁过期，建议使用住宅 IP 或增加账号数量做轮询。

> [!TIP]
> 配套浏览器插件 [**gemini2api-plugin**](https://github.com/xwteam/gemini2api-plugin)：装在你本地浏览器（住宅 IP），定时检测本服务的账号状态，过期时自动刷新本地 Gemini 页面、读取新 Cookie 回传给本服务，尝试突破数据中心 IP 的 2 小时限制。

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

### 🎨 AI 生成图片

```bash
# 方式一：对话里说"画图"，回复直接带图片（本地 URL，可渲染）
curl -X POST http://localhost:5918/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-pro","messages":[{"role":"user","content":"generate an image of a cute cat"}]}'

# 方式二：OpenAI 兼容图片接口，返回 b64_json
curl -X POST http://localhost:5918/v1/images/generations \
  -H "Authorization: Bearer sk-你的API密钥" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-pro","prompt":"a cute cat","n":1}'
```

> 返回全分辨率原图（如 1408×768）。对话接口返回可访问的本地图片 URL，`/images/generations` 返回 b64_json。

</details>

---

## 📡 API 端点

> 📖 详细 API 文档：[简体中文](docs/zh-CN/API.md) | [繁體中文](docs/zh-TW/API.md) | [English](docs/en/API.md) | [日本語](docs/ja/API.md) | [한국어](docs/ko/API.md)

<details>
<summary><b>点击展开完整端点列表</b></summary>

> **两套路径并存**：每家接口同时提供「带前缀路径」和「标准裸路径」。标准裸路径让官方 SDK 填 `base_url` 时无需加后缀，开箱即用；带前缀路径用于三家明确区分。下表「端点」列基于带前缀路径，括号内标注等价的裸路径。

### OpenAI 兼容（`/openai/v1` 或裸 `/v1`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 可用模型列表 |
| POST | `/chat/completions` | 对话补全（支持流式 + 工具调用 + 生图） |
| POST | `/images/generations` | AI 生成图片（返回 b64_json） |

### Claude 兼容（`/claude/v1`；对话入口同时挂裸 `/v1`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表（仅 `/claude/v1`，裸 `/v1/models` 归 OpenAI 格式） |
| GET | `/models/{id}` | 模型详情（仅 `/claude/v1`） |
| POST | `/messages` | 消息生成（支持流式 + 工具调用，裸 `/v1/messages` 可用） |
| POST | `/messages/count_tokens` | Token 计数估算（裸 `/v1/messages/count_tokens` 可用） |

### Gemini 原生（`/gemini/v1beta` 或裸 `/v1beta`）

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/models` | 模型列表 |
| POST | `/models/{m}:generateContent` | 内容生成 |
| POST | `/models/{m}:streamGenerateContent` | 流式生成（Chunked JSON） |

### Deep Research（`/gemini/v1beta/deepresearch`）

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/` | 同步深度研究（规划->调研->综合报告） |
| POST | `/stream` | 流式研究（实时进度推送） |
| POST | `/interact` | 异步任务模式（创建->轮询结果） |

### 管理接口（`/admin`）

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
| GET | `/usage-stats/summary` | 用量统计概览（累计请求数、错误率、延迟、轮换成功率） |
| GET | `/usage-stats/history` | 历史趋势数据（支持 granularity 和 hours 参数） |
| GET | `/settings` | 获取当前可编辑配置（分组返回） |
| POST | `/settings` | 批量更新配置（写入 .env + 热更新内存） |
| GET | `/api-keys` | API Key 列表（密钥脱敏） |
| GET | `/api-keys/catalog` | Provider 目录（内置模型列表） |
| POST | `/api-keys` | 添加 API Key |
| DELETE | `/api-keys/{id}` | 删除 API Key |
| PATCH | `/api-keys/{id}/status` | 切换 Key 状态（启用/禁用） |
| POST | `/api-keys/import` | 批量导入 Key |
| GET | `/api-keys/export` | 导出所有 Key（完整密钥） |
| POST | `/api-keys/batch-delete` | 批量删除 |
| GET | `/verify` | 验证 API Key 有效性（登录用） |
| GET | `/logs` | 结构化日志分页查询（支持 direction/search/limit/offset） |
| GET | `/logs/state` | 日志记录状态（enabled/paused） |
| POST | `/logs/state` | 更新日志记录状态 |
| POST | `/logs/clear` | 清空日志 |
| GET | `/logs/{id}` | 单条日志详情 |
| GET | `/model-mapping` | 获取所有模型映射 |
| POST | `/model-mapping` | 添加/更新模型映射 |
| DELETE | `/model-mapping/{alias}` | 删除模型映射 |

### 系统

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查（Docker 探针适配） |

</details>

**管理接口使用示例：**

```bash
# 查看账号池状态
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-你的API密钥"

# 动态添加新账号
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"psid":"g.a000新的值","psidts":"sidts-新的值","label":"我的第二个账号"}'

# 移除账号
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \"Authorization: Bearer sk-你的API密钥"

# 检测单个账号状态
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-你的API密钥"

# 热更新 Cookie（更新第一个账号）
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"psid":"g.a000新的值","psidts":"sidts-新的值"}'

# 从 .env 重新读取 Cookie
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-你的API密钥"
```

---

## ⚙ 配置说明

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 浏览器 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 浏览器 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自动生成 | API 访问密钥（`sk-` 开头，留空则首次启动自动生成） |
| `REFRESH_INTERVAL` | ❌ | `5` | Cookie 刷新周期（分钟） |
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
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | 每账号最大并发请求数 |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | 指纹配置文件路径 |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | 启用 Chrome 版本自动同步 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | 版本同步间隔（小时） |
| `JITTER_ENABLED` | ❌ | `true` | 启用请求时间抖动（模拟人类行为） |
| `USAGE_STATS_ENABLED` | ❌ | `true` | 启用用量统计（时序快照 + 持久化） |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | 快照采集间隔（秒） |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | 历史数据保留天数 |
| `MODEL_WHITELIST` | ❌ | — | 模型白名单（逗号分隔，为空则不过滤） |

---

## ⚠ 注意事项

1. **Cookie 有效期**：Google Cookie 会定期过期（通常数小时到数天不等）。服务内置自动刷新机制，但如果账号被登出或密码变更，需要重新获取 Cookie。

2. **流式输出**：所有 API 端点默认流式返回。设置 `stream: false` 时，服务内部仍以流式方式接收数据，收集完毕后一次性返回完整 JSON。

3. **模型可用性**：可用模型列表取决于你的 Google 账号权限。免费账号和 Gemini Advanced 账号看到的模型不同，服务启动时会自动检测。

4. **请求频率**：即使关闭了内置限流（`RATE_LIMIT_ENABLED=false`），Google 侧仍有频率限制。高频请求可能触发验证码或临时封禁，建议合理控制调用频率。

5. **网络环境**：部署服务器需能直接访问 `gemini.google.com`，部分地区可能需要配置代理。

---

## 🗂 项目结构

```
gemini2api/
├── app/
│   ├── main.py                 # 应用入口，中间件注册
│   ├── config.py               # Pydantic 配置管理
│   ├── core/
│   │   ├── gemini_client.py    # Gemini Web 核心客户端
│   │   ├── account_pool.py     # 多账号池（负载均衡 + 运行时策略切换）
│   │   ├── auth.py             # API Key 验证
│   │   ├── api_key_store.py    # 第三方 API Key 存储池
│   │   ├── api_forwarder.py    # 统一转发引擎
│   │   ├── model_mapping.py    # 模型名映射（别名→实际模型）
│   │   ├── stream.py           # 流式工具函数
│   │   └── fingerprint/        # 反检测与协议伪装
│   │       ├── config.py       # 指纹配置管理（加载/保存/热更新）
│   │       ├── header_builder.py # 动态请求头构建器
│   │       ├── cookie_jar.py   # 完整 Cookie 持久化管理
│   │       ├── version_sync.py # Chrome 版本自动同步
│   │       └── jitter.py       # 请求时间抖动
│   ├── models/                 # Pydantic 数据模型
│   │   ├── openai.py
│   │   ├── claude.py
│   │   └── gemini.py
│   ├── routers/                # API 路由（每种格式独立）
│   │   ├── openai.py
│   │   ├── claude.py
│   │   ├── gemini.py
│   │   ├── research.py
│   │   ├── admin.py
│   │   ├── settings.py         # 设置管理 API
│   │   ├── api_keys.py         # API Key 管理 API
│   │   └── model_mapping.py    # 模型映射 API
│   └── utils/                  # 工具函数
│       ├── tools.py            # 函数调用桥接
│       └── prompt.py           # 消息格式化
├── data/                       # 持久化数据（Docker 卷挂载）
│   ├── fingerprint.json        # 指纹配置（自动生成）
│   ├── api-keys.json           # 第三方 API Key 存储
│   ├── model-mapping.json      # 模型名映射配置
│   ├── usage-stats.json        # 用量统计快照
│   └── cookies/                # Cookie 持久化存储
├── api/                        # 热更新资源（Docker 卷挂载，修改无需重建）
│   ├── qr-config.json          # 二维码卡片文字配置
│   ├── wechat-qr.png           # 微信二维码图片
│   └── sponsor-qr.png          # 赞助二维码图片
├── static/                     # Web 管理面板
│   ├── index.html              # 主页面（SPA）
│   ├── login.html              # 登录页
│   ├── app/                    # JS/CSS 核心模块
│   └── components/             # HTML 组件片段
├── Dockerfile                  # 多阶段构建
├── docker-compose.yml          # 编排配置
├── accounts.json.example       # 多账号配置示例
├── requirements.txt
└── .env.example
```

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
- [x] 反检测与协议伪装（TLS 指纹一致性、Cookie 持久化、版本自动同步）
- [x] 设置页面（可视化配置管理）
- [x] API Key 管理（第三方大模型 Key 集中管理）
- [x] 统一转发引擎（一个接口调用所有大模型）
- [x] 模型映射（别名→实际模型名，如 gpt-4o → gemini-2.5-pro）
- [x] 轮换策略运行时热更新（设置修改即时生效）
- [x] 仪表盘系统信息面板（版本/Python/OS/内存/CPU/PID/运行模式）
- [x] 对话上下文持久化
- [x] GitHub Actions 自动构建镜像
- [x] 图片/文件上传支持
- [x] AI 生成图片（`/v1/images/generations` + 三家对话接口嵌图）
- [x] 自动清理 Gemini 网页端堆积会话（定时删旧会话，保留置顶）

---

## ☕ 赞赏 & 共享

> 完整内容请查看 [SPONSORS.md](SPONSORS.md)

觉得有帮助？请作者喝杯咖啡，或加入微信交流群获取使用帮助。二维码见页面顶部。

Gemini2API 主要由个人维护，欢迎通过代码、文档、修复或 PR 参与建设。

**参与贡献：**

1. Fork 本仓库
2. 创建分支 `git checkout -b feature/your-feature`
3. 提交代码 `git commit -m "feat: add something"`
4. 推送并创建 Pull Request

---

## 🙏 致谢

感谢所有在 [Issues](https://github.com/xwteam/gemini2api/issues) 里提交 bug 复现、日志、兼容性反馈和功能建议的用户。这些反馈直接推动了 Cookie 保活、多账号轮换、模型选择、多语言支持、Web 面板等核心能力的迭代。

---

## ⭐ Star History

<a href="https://star-history.com/#xwteam/gemini2api&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=xwteam/gemini2api&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=xwteam/gemini2api&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=xwteam/gemini2api&type=date&legend=top-left" />
 </picture>
</a>

---

## 📄 许可协议

本项目采用 [非商业许可 (Non-Commercial)](LICENSE)：

- **允许**：个人学习、研究、自用部署
- **禁止**：任何形式的商业用途，包括但不限于出售、转售、收费代理、商业产品集成

本项目与 Google 无关联。使用者需自行承担风险并遵守 Google 的服务条款。

---

## ⚠ 免责声明

1. **技术性质**：Gemini2API 是一个技术研究项目，通过浏览器 Cookie 模拟访问 Google Gemini Web 界面。本项目不提供任何 AI 服务，所有生成内容均来自 Google。使用本项目可能违反 Google 服务条款，由此产生的一切后果由使用者自行承担。

2. **无担保声明**：本项目按"原样"提供，不作任何明示或暗示的保证，包括但不限于适销性、特定用途适用性。开发者不对因使用本项目导致的账号封禁、数据丢失或其他任何损失承担责任。

3. **数据与隐私**：本项目完全在用户本地环境运行，不收集、不上传、不存储任何用户数据。您的 Cookie 和 API Key 仅保存在本地配置中，请妥善保管，切勿泄露。

4. **合规责任**：使用者应确保其使用行为符合所在地区的法律法规。严禁将本项目用于任何违法违规活动。

5. **第三方服务**：本项目与 Google 无任何关联或授权关系。Google Gemini 的可用性、稳定性及内容准确性均由 Google 负责，与本项目无关。

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
