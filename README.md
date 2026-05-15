<p align="center">
  <img src="https://www.gstatic.com/lamda/images/gemini_sparkle_v002_d4735304ff6292a690b6.svg" width="120" alt="Gemini2API">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Async-httpx-ff6b35?style=flat-square&logo=python&logoColor=white" alt="httpx">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-PolyForm_NC-orange?style=flat-square" alt="License">
</p>

<h1 align="center">Gemini2API</h1>

<p align="center">
  轻量级 Gemini Web 反向代理，一套代码兼容三大主流 AI SDK<br/>
  纯异步架构 · 零官方 Key · 30 秒 Docker 部署
</p>

> [!NOTE]
> 本项目仅供研究和学习用途，请合理使用，不要用于任何商业目的。

> [!WARNING]
> 本项目与 Google 无关。项目通过逆向工程获取的浏览器 Cookie 实现功能，可能不符合 Google 服务条款。使用风险自负，作者不对任何账号处罚或数据丢失承担责任。

---

## 🎯 为什么选择 Gemini2API

- **三合一兼容** — 一个服务同时提供 OpenAI、Claude、Gemini 三种 SDK 格式，切换零成本
- **纯异步架构** — 基于 Python asyncio + httpx，全链路非阻塞，天然支持高并发
- **Pydantic 强类型** — 请求参数自动校验，不再因字段缺失导致 500
- **模块化设计** — 每个 API 格式独立路由文件，新增功能只需加一个文件，不影响现有代码
- **Cookie 自愈** — 后台自动轮换 + 定时刷新，无需手动维护会话
- **30 秒部署** — Docker Compose 一键启动，填入 Cookie 即可使用
- **易于扩展** — Python + FastAPI 组合，代码可读性高，二次开发门槛低

---

## ✨ 功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| OpenAI 兼容 API | ✅ | `/openai/v1/chat/completions`，支持流式 |
| Claude 兼容 API | ✅ | `/claude/v1/messages`，完整 SSE 协议 |
| Gemini 原生 API | ✅ | `/gemini/v1beta/models/:model:generateContent` |
| 函数调用 | ✅ | 三种格式均支持工具调用 |
| 流式响应 | ✅ | SSE（OpenAI/Claude）+ Chunked JSON（Gemini） |
| Deep Research | ✅ | 多步骤深度研究，支持同步/流式/异步 |
| Cookie 自动刷新 | ✅ | 后台定时轮换，无感续期 |
| 模型自动发现 | ✅ | 启动时从 Web 页面提取可用模型列表 |
| 速率限制 | ✅ | 可选，基于 IP 的滑动窗口限流 |
| 健康检查 | ✅ | `/health` 端点，适配 Docker 健康探针 |
| 账号状态检测 | ✅ | 定时主动验证 Cookie 有效性，支持历史记录查询 |

---

## ⚡ 快速部署

### 1. 获取 Cookie

1. 使用 Chrome 或 Edge 浏览器访问 [gemini.google.com](https://gemini.google.com)
2. 登录你的 Google 账号，确保能正常使用 Gemini 对话
3. 按 `F12` 打开开发者工具
4. 点击顶部 **Application**（应用程序）标签
5. 左侧栏找到 **Cookies** → 点击 `https://gemini.google.com`
6. 在 Cookie 列表中找到以下两个值：

| Cookie 名称 | 说明 |
|-------------|------|
| `__Secure-1PSID` | 以 `g.` 开头的长字符串，通常几十个字符 |
| `__Secure-1PSIDTS` | 较短的字符串 |

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
# 看到 "Gemini client ready" 表示连接成功
# 看到 "SNlM0e not found" 表示 Cookie 无效，需要重新获取
```

### 3. 验证服务

```bash
# 健康检查
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# 查看可用模型
curl http://localhost:5918/openai/v1/models

# 发送测试请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

---

## 🛠️ 环境变量

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

---

## 🧪 接入示例

> [!NOTE]
> 所有 API 请求都需要携带 API Key。支持两种方式：
> - `Authorization: Bearer sk-xxx`（推荐，兼容 OpenAI/Claude SDK）
> - `x-api-key: sk-xxx`
>
> API Key 在首次启动时自动生成并写入 `.env` 文件，可在日志中查看或手动修改。

### OpenAI SDK（Python）

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密钥",  # 填入 .env 中的 API_KEY
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "用三句话解释相对论"}],
    stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

### Claude SDK（Python）

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-你的API密钥",  # 填入 .env 中的 API_KEY
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "写一个快速排序的Python实现"}]
)
print(msg.content[0].text)
```

### cURL

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

### 函数调用（Function Calling）

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

---

## 📘 API 端点一览

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
| POST | `/` | 同步深度研究（规划→调研→综合报告） |
| POST | `/stream` | 流式研究（实时进度推送） |
| POST | `/interact` | 异步任务模式（创建→轮询结果） |

### 系统

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查（Docker 探针适配） |

### 管理接口（`/admin`）

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/reload-cookies` | 热更新 Cookie（无需重启容器） |
| GET | `/status` | 服务状态（健康状态 + 可用模型数） |
| GET | `/check-account` | 实时检测账号状态（主动验证 Cookie 有效性） |
| GET | `/health-history` | 最近 20 条健康检查记录 |

> 管理接口同样需要 API Key 验证。

**热更新 Cookie 示例：**

```bash
# 方式一：直接传入新 Cookie
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"psid":"g.a000新的PSID值","psidts":"sidts-新的PSIDTS值"}'

# 方式二：不传参数，从 .env 文件重新读取
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-你的API密钥"

# 查看服务状态
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-你的API密钥"

# 主动检测账号状态
curl http://localhost:5918/admin/check-account \
  -H "Authorization: Bearer sk-你的API密钥"
# 返回：{"valid":true,"has_token":true,"models_count":12,"checked_at":"..."}

# 查看健康检查历史
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-你的API密钥"
```

---

## 🏗️ 项目结构

```
gemini2api/
├── app/
│   ├── main.py                 # 应用入口，中间件注册
│   ├── config.py               # Pydantic 配置管理
│   ├── core/
│   │   ├── gemini_client.py    # Gemini Web 核心客户端
│   │   └── stream.py           # 流式工具函数
│   ├── models/                 # Pydantic 数据模型
│   │   ├── openai.py
│   │   ├── claude.py
│   │   └── gemini.py
│   ├── routers/                # API 路由（每种格式独立）
│   │   ├── openai.py
│   │   ├── claude.py
│   │   ├── gemini.py
│   │   └── research.py
│   └── utils/                  # 工具函数
│       ├── tools.py            # 函数调用桥接
│       └── prompt.py           # 消息格式化
├── Dockerfile                  # 多阶段构建
├── docker-compose.yml          # 编排配置
├── requirements.txt
└── .env.example
```

---

## 🗺️ 开发路线

- [x] OpenAI / Claude / Gemini 三格式兼容
- [x] 流式响应 + 函数调用
- [x] Deep Research 深度研究
- [x] Docker 部署
- [ ] 多账号轮询（负载均衡）
- [ ] Web 管理面板
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

## 📄 License

[PolyForm Noncommercial 1.0.0](LICENSE)

本项目仅供个人学习、研究、实验用途，禁止商业使用。商用授权请通过 GitHub Issues 联系。

---

<p align="center">Made with ❤️ by xwteam</p>
