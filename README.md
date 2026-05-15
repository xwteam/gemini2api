<p align="center">
  <img src="https://www.gstatic.com/lamda/images/gemini_sparkle_v002_d4735304ff6292a690b6.svg" width="120" alt="Gemini2API">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-orange?style=flat-square" alt="License">
</p>

<h1 align="center">Gemini2API</h1>

<p align="center">
  通过浏览器 Cookie 将 Google Gemini Web 转换为标准 API 接口<br/>
  兼容 OpenAI、Claude、Gemini 原生 SDK 格式，无需官方 API Key
</p>

> [!NOTE]
> 本项目仅供学习研究使用，请遵守 Google 服务条款。

> [!WARNING]
> 本项目与 Google 无关。使用浏览器 Cookie 访问 Gemini 可能违反服务条款，请自行承担风险。

---

## 🎯 项目简介

**问题**：Google Gemini 官方 API 有配额限制且部分地区不可用。

**解决方案**：通过浏览器 Cookie 直接访问 Gemini Web 界面，并将其封装为标准 REST API，兼容主流 SDK 格式。

**适用场景**：
- 个人开发测试，无需申请 API Key
- 需要兼容 OpenAI / Claude SDK 的项目快速接入
- 研究和学习 Gemini 模型能力

---

## ✨ 功能特性

- 🔑 Cookie 自动认证与轮换刷新
- 🔄 兼容 OpenAI API 格式
- 🤖 兼容 Claude API 格式
- 💎 兼容 Gemini 原生 SDK 格式
- 📡 支持流式响应（SSE / Chunked）
- 🛠️ 支持工具调用 / Function Calling
- 🔬 Deep Research 深度研究
- 🐳 Docker 一键部署
- ⚡ 自动模型发现
- 🛡️ 可选速率限制

---

## ⚡ 快速开始

### 获取 Cookie

1. 打开浏览器访问 [gemini.google.com](https://gemini.google.com)
2. 登录你的 Google 账号
3. 按 F12 打开开发者工具 - Application - Cookies
4. 复制 `__Secure-1PSID` 和 `__Secure-1PSIDTS` 的值

### Docker 部署

```bash
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

cp .env.example .env
# 编辑 .env 填入你的 Cookie 值

docker compose up -d
```

服务启动后访问 `http://localhost:4981/health` 确认运行状态。

---

## 🛠️ 配置说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `GEMINI_PSID` | ✅ | - | `__Secure-1PSID` Cookie 值 |
| `GEMINI_PSIDTS` | ❌ | - | `__Secure-1PSIDTS` Cookie 值 |
| `REFRESH_INTERVAL` | ❌ | `5` | Cookie 刷新间隔（分钟） |
| `MAX_RETRIES` | ❌ | `3` | 最大重试次数 |
| `PORT` | ❌ | `4981` | 监听端口 |
| `LOG_LEVEL` | ❌ | `info` | 日志级别 |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | 启用速率限制 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 限流窗口（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | 窗口内最大请求数 |

---

## 🧪 使用示例

### Python OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="not-needed",
    base_url="http://localhost:4981/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "你好"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Python Claude SDK

```python
import anthropic

client = anthropic.Anthropic(
    api_key="not-needed",
    base_url="http://localhost:4981/claude"
)

message = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "解释量子计算"}]
)
print(message.content[0].text)
```

### cURL

```bash
curl http://localhost:4981/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

---

## 📘 API 接口

### OpenAI 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/openai/v1/models` | 模型列表 |
| POST | `/openai/v1/chat/completions` | 聊天补全 |

### Claude 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/claude/v1/models` | 模型列表 |
| POST | `/claude/v1/messages` | 创建消息 |
| POST | `/claude/v1/messages/count_tokens` | Token 估算 |

### Gemini 原生

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/gemini/v1beta/models` | 模型列表 |
| POST | `/gemini/v1beta/models/{model}:generateContent` | 生成内容 |
| POST | `/gemini/v1beta/models/{model}:streamGenerateContent` | 流式生成 |

### Deep Research

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/gemini/v1beta/deepresearch` | 同步研究 |
| POST | `/gemini/v1beta/deepresearch/stream` | 流式研究 |
| POST | `/gemini/v1beta/deepresearch/interact` | 异步研究 |

---

## 🏗️ 技术栈

- **语言**：Python 3.12
- **框架**：FastAPI + Uvicorn
- **HTTP 客户端**：httpx（异步）
- **配置管理**：pydantic-settings
- **部署**：Docker + Docker Compose

---

## 📄 License

MIT License

---

<p align="center">Made with ❤️ by xwteam</p>
