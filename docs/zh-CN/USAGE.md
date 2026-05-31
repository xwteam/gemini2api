# 使用指南

本文档详细说明如何使用 Gemini2API 服务。

## Web 管理面板

### 访问面板

启动服务后，在浏览器中访问：

```
http://localhost:5918
```

或使用服务器 IP：

```
http://服务器IP:5918
```

### 登录

首次访问需要输入 API Key 进行登录。API Key 在首次启动时自动生成，可在日志中查看。

### 仪表盘

仪表盘显示服务的实时状态和概览信息。

#### 系统信息卡片

显示以下信息：
- **版本**：Gemini2API 版本号
- **Python 版本**：运行环境 Python 版本
- **操作系统**：服务器操作系统和内核版本
- **内存使用**：当前内存占用 / 总内存
- **CPU 使用率**：实时 CPU 使用百分比
- **进程 ID**：服务进程 ID
- **运行模式**：Docker 或直接运行
- **运行时间**：服务启动以来的运行时长

#### 二维码卡片

显示二维码图片和文字配置，支持：
- 点击图片放大查看
- 从 `api/` 目录动态加载配置
- 修改无需重建容器

#### 账号状态总览

显示账号池的实时状态：
- 总账号数
- 活跃账号数
- 轮询策略
- 每个账号的状态和请求计数

#### 可用模型列表

显示当前可用的所有模型：
- Gemini Web 模型
- 第三方 API Key 池中的模型

### 账号管理

#### 查看账号列表

显示所有已配置的账号及其状态：
- 账号 ID
- 标签
- 状态（healthy/unhealthy）
- 最后检测时间
- 请求计数

#### 添加账号

点击"添加账号"按钮，填入以下信息：
- **PSID**：`__Secure-1PSID` Cookie 值
- **PSIDTS**：`__Secure-1PSIDTS` Cookie 值
- **标签**：账号描述（可选）

#### 更新 Cookie

选择账号，点击"更新 Cookie"按钮，输入新的 Cookie 值。无需重启服务，立即生效。

#### 删除账号

选择账号，点击"删除"按钮确认删除。

#### 检测账号

点击"检测"按钮，立即检测该账号的健康状态。

### Playground 测试

在线测试 API 请求，支持：
- 选择模型
- 输入消息
- 配置参数（temperature、max_tokens 等）
- 实时查看响应
- 支持流式和非流式请求

### 实时日志

显示结构化日志，支持：
- **方向过滤**：查看最新日志或最早日志
- **文本搜索**：按关键词搜索日志
- **分页显示**：每页 15 条记录
- **JSON 详情**：点击日志行查看完整 JSON 信息
- **日志持久化**：重启服务后日志不丢失

### 使用统计

显示服务的使用统计信息：
- 累计请求数
- 错误率
- 平均延迟
- Cookie 轮换成功率
- 历史趋势图表

### API Key 管理

集中管理第三方大模型 API Key：
- **OpenAI**：支持 GPT-4、GPT-4o 等模型
- **Anthropic**：支持 Claude 系列模型
- **Google Gemini**：支持 Gemini API Key
- **OpenRouter**：支持 OpenRouter 平台的模型
- **自定义**：支持其他兼容 OpenAI 格式的 API

#### 添加 API Key

1. 点击"添加 Key"按钮
2. 选择 Provider（OpenAI、Anthropic 等）
3. 输入 API Key
4. 选择模型
5. 点击保存

#### 导入导出

- **导出**：导出所有 API Key（包含完整密钥）
- **导入**：批量导入 API Key（JSON 格式）

#### 启用/禁用

点击 Key 行的开关按钮，可快速启用或禁用该 Key。

### 设置

可视化管理运行时配置，修改即时生效。

#### 性能设置

- **轮询策略**：round-robin（轮询）或 failover（故障转移）
- **每账号最大并发数**：1-10
- **Cookie 刷新周期**：1-60 分钟
- **失败重试次数**：1-5 次

#### 限流设置

- **启用限流**：开启/关闭
- **限流窗口**：时间窗口（秒）
- **窗口内最大请求数**：限制数量

#### 健康检查设置

- **启用健康检查**：开启/关闭
- **检查间隔**：1-60 分钟

#### 日志设置

- **日志级别**：debug/info/warning/error
- **启用日志记录**：开启/关闭

### 模型映射

将请求中的模型名映射到实际使用的模型。

#### 添加映射

例如，将 `gpt-4o` 映射到 `gemini-2.5-pro`：
1. 点击"添加映射"
2. 输入别名：`gpt-4o`
3. 输入目标模型：`gemini-2.5-pro`
4. 保存

#### 使用映射

客户端请求时使用别名：
```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{"model": "gpt-4o", "messages": [...]}'
```

服务会自动将 `gpt-4o` 转换为 `gemini-2.5-pro`。

### 主题切换

右上角点击主题按钮，在深色和浅色主题之间切换。

### 服务重启

右上角点击重启按钮，可一键重启服务。

### 登出

右上角点击登出按钮，退出登录。

## 图片上传

Gemini2API 支持多模态内容，包括图片和文件上传。支持三种 API 格式的图片传输。

### OpenAI 格式

在 `messages` 数组中使用 `image_url` 类型，支持 Base64 Data URI 和远程 HTTP URL：

**Base64 图片示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "这是什么"},
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

**远程 URL 图片示例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "分析这张图片"},
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

在 `content` 数组中使用 `image` 类型：

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-flash",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "这是什么"},
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

在 `parts` 数组中使用 `inlineData`：

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "contents": [
      {
        "parts": [
          {"text": "这是什么"},
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

### Web 面板上传

在 Playground 测试页面，点击"添加图片"按钮可直接上传本地图片进行测试。

## 支持的模型

### 对外固定稳定模型名

Gemini2API 对外提供 3 个固定的稳定模型名，永不变更。这些模型名作为 API 契约，客户端可以长期使用而无需担心模型名变化：

| 模型名称 | 说明 |
|---------|------|
| `gemini-pro` | Pro 模型，性能最强，适合复杂任务 |
| `gemini-flash` | 快速模型，低延迟，适合实时应用 |
| `gemini-flash-thinking` | 思考模型，支持深度推理和分析 |

**内部自动映射**：服务内部会根据你的 Google 账号订阅等级（Advanced/Plus/Basic）自动映射到当前真实可用的模型版本。无论账号等级如何变化、Google 灰度发布如何调整、服务重启等，客户端始终使用这 3 个固定名称，无需修改。

**旧别名兼容**：为了向后兼容，以下旧模型名仍然支持：
- `gemini-2.5-pro`、`gemini-2.0-flash`、`gemini-2.0-flash-thinking` 等

### 第三方模型

通过 API Key 池支持：
- **OpenAI**：gpt-4o、gpt-4-turbo、gpt-3.5-turbo 等
- **Anthropic**：claude-3-opus、claude-3-sonnet、claude-3-haiku 等
- **Google Gemini**：通过官方 API Key
- **OpenRouter**：支持 OpenRouter 平台的所有模型

## 第三方客户端接入

### ChatGPT-Next-Web

1. 部署 ChatGPT-Next-Web
2. 打开设置页面
3. 在"API 设置"中填入：
   - **API 地址**：`http://服务器IP:5918/openai/v1`
   - **API Key**：`sk-你的API密钥`
4. 选择模型为 `gemini-2.0-flash` 或其他可用模型
5. 开始对话

### LobeChat

1. 部署 LobeChat
2. 打开设置页面
3. 在"模型提供商"中选择"OpenAI"
4. 填入：
   - **API 地址**：`http://服务器IP:5918/openai/v1`
   - **API Key**：`sk-你的API密钥`
5. 选择模型
6. 开始对话

### OpenCat

1. 打开 OpenCat 应用
2. 进入设置
3. 添加自定义 API 端点：
   - **API 地址**：`http://服务器IP:5918/openai/v1`
   - **API Key**：`sk-你的API密钥`
4. 选择模型
5. 开始对话

### 通用 OpenAI 兼容客户端

任何支持自定义 API 端点的 OpenAI 兼容客户端都可以使用：

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密钥",
    base_url="http://服务器IP:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "Hello"}]
)
```

## Cookie 管理

### 自动更新

服务内置 Cookie 自动轮换机制：
- 每 5 分钟（可配置）通过 Google RotateCookies API 刷新 `__Secure-1PSIDTS`
- 配合 batchexecute 心跳模拟浏览器活跃行为
- 延长 session 寿命

### 手动更新

#### 通过 Web 面板

1. 打开 Web 面板
2. 进入"账号管理"
3. 选择要更新的账号
4. 点击"更新 Cookie"
5. 输入新的 Cookie 值
6. 保存

#### 通过 API

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "psid": "g.新的值",
    "psidts": "sidts-新的值"
  }'
```

### Cookie 过期处理

如果 Cookie 过期，服务会：
1. 自动标记账号为不健康
2. 跳过该账号，使用其他账号
3. 在日志中记录错误
4. 等待手动更新 Cookie

## 多语言支持

Web 面板支持多种语言，点击右上角地球图标切换：
- 简体中文
- 繁體中文
- English
- 日本語
- 한국어

## 对话上下文

### 自动维护

客户端 SDK 会自动维护对话历史：
```python
messages = [
    {"role": "user", "content": "第一条消息"},
    {"role": "assistant", "content": "回复"},
    {"role": "user", "content": "第二条消息"}
]
```

### 使用 conversation_id

支持通过 `conversation_id` 字段维护长对话：

```bash
# 第一条消息
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hi"}],
    "conversation_id": "conv-123"
  }'

# 后续消息（使用相同的 conversation_id）
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "继续之前的话题"}],
    "conversation_id": "conv-123"
  }'
```

## 流式和非流式请求

### 流式请求

设置 `stream: true` 获取实时流式响应：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "写一首诗"}],
    "stream": true
  }'
```

### 非流式请求

设置 `stream: false` 获取完整响应：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "写一首诗"}],
    "stream": false
  }'
```

## 函数调用

支持 OpenAI 格式的函数调用：

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
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                },
                "required": ["city"]
            }
        }
    }]
)
```

## Deep Research

支持深度研究功能，进行多步骤的研究和分析：

```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/stream \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "query": "人工智能的发展趋势"
  }'
```

## 常见使用场景

### 场景 1：简单对话

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "你好"}]
)

print(response.choices[0].message.content)
```

### 场景 2：流式对话

```python
for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "写一个 Python 快速排序"}],
    stream=True
):
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 场景 3：多轮对话

```python
messages = []

# 第一轮
messages.append({"role": "user", "content": "什么是机器学习"})
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=messages
)
messages.append({"role": "assistant", "content": response.choices[0].message.content})

# 第二轮
messages.append({"role": "user", "content": "能举个例子吗"})
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=messages
)
messages.append({"role": "assistant", "content": response.choices[0].message.content})

print(messages[-1]["content"])
```

### 场景 4：使用 Claude SDK

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-你的API密钥",
    base_url="http://localhost:5918/claude"
)

message = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)

print(message.content[0].text)
```

## 故障排查

### 请求返回 401

**原因**：API Key 无效或未提供

**解决**：
1. 检查 API Key 是否正确
2. 确保请求头中包含 `Authorization: Bearer sk-xxx`
3. 检查 API Key 是否在 `.env` 中正确配置

### 请求返回 503

**原因**：没有可用的账号

**解决**：
1. 检查账号 Cookie 是否过期
2. 通过 Web 面板更新 Cookie
3. 检查账号状态是否为 healthy

### 响应缓慢

**原因**：
1. 网络延迟
2. 账号被限流
3. 服务器资源不足

**解决**：
1. 增加账号数量
2. 调整并发限制
3. 增加服务器资源

### 对话上下文丢失

**原因**：未使用 `conversation_id` 或 ID 过期

**解决**：
1. 使用 `conversation_id` 维护对话
2. 定期检查 ID 是否有效
3. 在客户端维护完整的 messages 历史

## 获取帮助

- 查看 [DEPLOY.md](./DEPLOY.md) 了解部署方法
- 查看 [API.md](./API.md) 了解 API 文档
- 查看 [README.md](../../README.md) 了解项目概况
- 提交 Issue：[GitHub Issues](https://github.com/xwteam/gemini2api/issues)
