<div align="center">

<h1>Gemini2API</h1>
<h3>轻量级 Gemini Web 反向代理</h3>
<p>一套代码兼容 OpenAI / Claude / Gemini 三大主流 AI SDK，纯异步架构，零官方 Key，30 秒 Docker 部署。</p>

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

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> 本项目仅供研究和学习用途，请合理使用，不要用于任何商业目的。

> [!WARNING]
> 本项目与 Google 无关。项目通过逆向工程获取的浏览器 Cookie 实现功能，可能不符合 Google 服务条款。使用风险自负，作者不对任何账号处罚或数据丢失承担责任。

---

## 📝 最近更新

> 完整更新日志请查看 [CHANGELOG.md](CHANGELOG.md)，以下内容由 CI 自动同步。

| 日期 | 更新内容 |
|------|----------|
| 2025-05-16 00:40:00 | 修复 curl_cffi 跨域 Cookie 累积冲突，Cookie 热更新恢复正常 |
| 2025-05-15 23:45:00 | 新增反检测与协议伪装系统：指纹一致性、完整 Cookie 持久化、Chrome 版本自动同步、请求时间抖动 |
| 2025-05-15 23:10:00 | 替换 httpx 为 curl_cffi，模拟 Chrome TLS 指纹延长 session 寿命 |
| 2025-05-15 21:30:00 | 新增 Web 管理面板（仪表盘、账号管理、实时日志、Playground） |
| 2025-05-15 19:08:40 | 新增多账号轮询（负载均衡），支持 round-robin / least-used 策略 |
| 2025-05-15 17:25:10 | 新增账号状态定时检测、健康检查历史记录 API |
| 2025-05-15 16:50:30 | 新增 Cookie 热更新接口，无需重启即可刷新凭证 |
| 2025-05-14 22:15:00 | 新增 Deep Research 深度研究功能 |
| 2025-05-14 15:30:00 | 支持 OpenAI / Claude / Gemini 三格式函数调用 |
| 2025-05-13 20:00:00 | 项目初始化，基础代理功能上线 |

---

## 🌟 核心功能

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

- **多账号负载均衡**：支持 round-robin（轮询）和 least-used（最少使用）两种策略
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
- 仪表盘：账号状态总览、可用模型列表、请求统计
- 账号管理：添加/删除账号、单独更新 Cookie、健康检测
- Playground：在线测试 API 请求
- 实时日志：SSE 推送服务端日志，支持自动滚动
- 深色/浅色主题切换，响应式移动端适配

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
│  POST /openai/v1/chat/completions                           │
│  POST /claude/v1/messages                                   │
│  POST /gemini/v1beta/models/:m:generateContent              │
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

<details>
<summary><b>点击展开完整端点列表</b></summary>

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
| GET | `/accounts` | 所有账号列表及状态 |
| POST | `/accounts` | 动态添加新账号 |
| DELETE | `/accounts/{id}` | 移除指定账号 |
| GET | `/accounts/{id}/check` | 检测单个账号状态 |
| GET | `/check-account` | 检测所有账号状态 |
| POST | `/reload-cookies` | 热更新 Cookie（无需重启容器） |
| PUT | `/accounts/{id}/cookies` | 更新指定账号的 Cookie |
| GET | `/health-history` | 最近健康检查记录 |
| GET | `/verify` | 验证 API Key 有效性（登录用） |
| GET | `/logs/stream` | SSE 实时日志流 |

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
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 轮询策略：`round-robin`（轮询）/ `least-used`（最少使用） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | 每账号最大并发请求数 |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | 指纹配置文件路径 |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | 启用 Chrome 版本自动同步 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | 版本同步间隔（小时） |
| `JITTER_ENABLED` | ❌ | `true` | 启用请求时间抖动（模拟人类行为） |

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
│   │   ├── account_pool.py     # 多账号池（负载均衡）
│   │   ├── auth.py             # API Key 验证
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
│   │   └── admin.py
│   └── utils/                  # 工具函数
│       ├── tools.py            # 函数调用桥接
│       └── prompt.py           # 消息格式化
├── data/                       # 持久化数据（Docker 卷挂载）
│   ├── fingerprint.json        # 指纹配置（自动生成）
│   └── cookies/                # Cookie 持久化存储
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
- [ ] 对话上下文持久化
- [ ] 图片/文件上传支持
- [ ] Prometheus 监控指标

---

## 🤝 贡献

欢迎 PR 和 Issue。

1. Fork 本仓库
2. 创建分支 `git checkout -b feature/your-feature`
3. 提交代码 `git commit -m "feat: add something"`
4. 推送并创建 Pull Request

---

## ⭐ Star History

<a href="https://star-history.com/#xwteam/gemini2api&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=xwteam/gemini2api&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=xwteam/gemini2api&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=xwteam/gemini2api&type=Date" />
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
