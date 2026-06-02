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

> 完整更新日志请查看 [CHANGELOG.md](../../CHANGELOG.md)，以下内容由 CI 自动同步。

| 日期 | 更新内容 |
|------|----------|
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
| 2026-05-31 17:00:00 | v1.6.4 - 三家接口暴露标准裸路径（/v1/chat/completions、/v1/messages、/v1beta/...），主流 SDK 开箱即用；修复部署机制（docker-compose 由 build 改 image，docker compose pull 真正生效） |
| 2026-05-31 14:10:00 | v1.6.3 - 图片/文件上传支持（OpenAI/Claude/Gemini 多模态）；模型改用网页版真实数据 + 对外固定稳定名（gemini-pro/flash/flash-thinking）；重启不再丢 Cookie |
| 2026-05-19 20:00:00 | v1.6.2 - 会话 5 分钟无操作自动过期登出 |
| 2025-05-18 16:30:00 | v1.6.1 - 深色主题全面修复、检查更新弹窗美化、GitHub Actions 自动构建镜像、failover 故障转移策略 |
| 2025-05-17 23:20:00 | 模型列表统一为用户友好名称，新增思考模式（gemini-2.5-flash-thinking）和 Pro 模式，Playground 对话上下文修复 |
| 2025-05-17 22:30:00 | 容器时区修正为 Asia/Shanghai，日志显示北京时间 |

---

## 🌟 核心功能

> 📖 详细使用文档：[USAGE.md](USAGE.md)

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

gemini2api 内置 Cookie 自动轮换机制：每 5 分钟通过 Google RotateCookies API 刷新 `__Secure-1PSIDTS`，配合 batchexecute 心跳模拟浏览器活跃行为，延长 session 寿命。

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

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/status` | 服务状态（账号池概览 + 轮询策略） |
| GET | `/accounts` | 所有账号列表及状态 |
| POST | `/accounts` | 动态添加新账号 |
| DELETE | `/accounts/{id}` | 移除指定账号 |
| GET | `/accounts/{id}/check` | 检测单个账号状态 |
| POST | `/reload-cookies` | 热更新 Cookie（无需重启容器） |

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
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 轮询策略：`round-robin`（轮询）/ `failover`（故障转移） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | 每账号最大并发请求数 |

---

## ⚠ 注意事项

1. **Cookie 有效期**：Google Cookie 会定期过期（通常数小时到数天不等）。服务内置自动刷新机制，但如果账号被登出或密码变更，需要重新获取 Cookie。

2. **流式输出**：所有 API 端点默认流式返回。设置 `stream: false` 时，服务内部仍以流式方式接收数据，收集完毕后一次性返回完整 JSON。

3. **模型可用性**：可用模型列表取决于你的 Google 账号权限。免费账号和 Gemini Advanced 账号看到的模型不同，服务启动时会自动检测。

4. **请求频率**：即使关闭了内置限流（`RATE_LIMIT_ENABLED=false`），Google 侧仍有频率限制。高频请求可能触发验证码或临时封禁，建议合理控制调用频率。

5. **网络环境**：部署服务器需能直接访问 `gemini.google.com`，部分地区可能需要配置代理。

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
- [ ] 图片/文件上传支持

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
