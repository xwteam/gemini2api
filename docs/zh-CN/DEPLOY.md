# 部署指南

本文档详细说明如何部署 Gemini2API 服务。

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Docker | 20.10+ | 推荐使用 Docker 部署 |
| Docker Compose | 1.29+ | 编排工具 |
| 内存 | 2GB+ | 建议 4GB 以上 |
| 磁盘 | 500MB+ | 用于存储日志和配置 |
| 操作系统 | Linux/Mac/Windows | 任何支持 Docker 的系统 |
| 网络 | 直连 gemini.google.com | 需要能访问 Google 服务 |

## 获取 Cookie

### 前置条件

- 拥有有效的 Google 账号
- 账号能正常访问 [gemini.google.com](https://gemini.google.com)
- 使用 Chrome 或 Edge 浏览器

### 获取步骤

1. 打开浏览器，访问 [gemini.google.com](https://gemini.google.com)

2. 使用 Google 账号登录，确保能正常使用 Gemini 对话

3. 按 `F12` 打开开发者工具

4. 点击顶部菜单栏的 **Application**（应用程序）标签

5. 在左侧栏找到 **Cookies** 选项，点击展开

6. 点击 `https://gemini.google.com` 条目

7. 在 Cookie 列表中查找以下两个值：

   | Cookie 名称 | 特征 | 示例 |
   |------------|------|------|
   | `__Secure-1PSID` | 以 `g.` 开头，通常 50-100 字符 | `g.a000xxx...` |
   | `__Secure-1PSIDTS` | 较短的字符串，通常 20-40 字符 | `sidts-xxx...` |

8. 双击 Value 列复制完整值

9. 将两个值保存到安全位置

### 获取技巧

- 在搜索框输入 `__Secure-1P` 快速过滤相关 Cookie
- 建议在无痕模式下操作，获取后立即关闭窗口
- 避免页面刷新导致 Cookie 轮换失效
- 复制时确保没有多余空格或换行符

### Cookie 有效期

- Google Cookie 通常有效期为 2-24 小时
- 数据中心 IP 可能更短（1-2 小时）
- 住宅 IP 通常更长（6-24 小时）
- 如果服务突然无法使用，优先检查 Cookie 是否过期

## Docker 部署

### 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 2. 复制环境变量模板
cp .env.example .env

# 3. 编辑 .env 文件，填入 Cookie
# 使用你喜欢的编辑器打开 .env
nano .env
# 或
vim .env
```

### 配置 .env 文件

编辑 `.env` 文件，填入获取的 Cookie 值：

```env
# 必填：从浏览器获取的 Cookie
GEMINI_PSID=g.a000xxx...
GEMINI_PSIDTS=sidts-xxx...

# 可选：API 访问密钥（留空则自动生成）
API_KEY=

# 可选：服务端口（默认 5918）
PORT=5918

# 可选：Cookie 刷新周期（分钟，默认 5）
REFRESH_INTERVAL=5

# 可选：失败重试次数（默认 3）
MAX_RETRIES=3

# 可选：日志级别（debug/info/warning/error，默认 info）
LOG_LEVEL=info

# 可选：限流配置
RATE_LIMIT_ENABLED=false
RATE_LIMIT_WINDOW=60
RATE_LIMIT_MAX=10

# 可选：健康检查配置
HEALTH_CHECK_ENABLED=true
HEALTH_CHECK_INTERVAL=5

# 可选：多账号配置文件路径（不存在则使用环境变量单账号模式）
ACCOUNTS_FILE=accounts.json

# 可选：轮询策略（round-robin/failover，默认 round-robin）
ROTATION_STRATEGY=round-robin

# 可选：每账号最大并发数（默认 8）
MAX_CONCURRENT_PER_ACCOUNT=8

# 可选：并发满载时排队等待可用槽位的上限（秒），等不到才报错
ACQUIRE_TIMEOUT=60.0

# 可选：遇 5xx 时同账号快速重试次数，仍失败则换号 failover；被限流账号的冷却时长（秒）
SAME_ACCOUNT_5XX_RETRIES=1
FAILOVER_COOLDOWN=30.0

# 可选：指纹 / 版本同步 / 抖动
FINGERPRINT_CONFIG_PATH=data/fingerprint.json
VERSION_SYNC_ENABLED=true
VERSION_SYNC_INTERVAL=24
JITTER_ENABLED=true

# 可选：用量统计
USAGE_STATS_ENABLED=true
USAGE_STATS_INTERVAL=300
USAGE_STATS_RETENTION_DAYS=30

# 可选：模型白名单（逗号分隔，留空则不过滤；非空时过滤各 /models 列表）
MODEL_WHITELIST=

# 可选：Gemini 网页端会话自动清理
CHAT_CLEANUP_ENABLED=true
CHAT_CLEANUP_KEEP_HOURS=24.0
CHAT_CLEANUP_INTERVAL_HOURS=6.0
CHAT_CLEANUP_SKIP_PINNED=true

# 可选：管理面板/admin 独立鉴权 key（留空则回退用 API_KEY）
ADMIN_API_KEY=

# 可选：CORS（允许来源逗号分隔，* 表示全部；是否允许携带凭据）
CORS_ALLOW_ORIGINS=*
CORS_ALLOW_CREDENTIALS=true

# 可选：生图代下载尺寸后缀（=s0 为全分辨率原图）与单次下载超时（秒）
IMAGE_DOWNLOAD_SIZE_SUFFIX==s2048
IMAGE_DOWNLOAD_TIMEOUT=25.0
```

### 配置注意事项

- **不要加引号**：`GEMINI_PSID=g.a000xxx` 而不是 `GEMINI_PSID="g.a000xxx"`
- **不要有空格**：`GEMINI_PSID=g.a000xxx` 而不是 `GEMINI_PSID = g.a000xxx`
- **完整值**：确保复制的是完整的 Cookie 值，不要遗漏末尾字符
- **敏感信息**：不要将 `.env` 文件提交到 Git，已在 `.gitignore` 中

### 启动服务

```bash
# 后台启动
docker compose up -d

# 查看启动日志
docker compose logs -f

# 看到以下日志表示启动成功：
# "Account pool ready: 1/1 active"
# "Uvicorn running on 0.0.0.0:5918"
```

### 停止服务

```bash
# 停止服务
docker compose down

# 停止并删除数据卷
docker compose down -v
```

### 查看日志

```bash
# 实时查看日志
docker compose logs -f

# 查看最后 100 行日志
docker compose logs --tail=100

# 查看特定服务的日志
docker compose logs gemini2api
```

## 多账号配置

### 为什么需要多账号

- 提高并发处理能力
- 实现负载均衡
- 增加服务稳定性
- 绕过单账号频率限制

### 创建 accounts.json

在项目根目录创建 `accounts.json` 文件：

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
    },
    {
      "id": "account-2",
      "psid": "g.a000zzz...",
      "psidts": "sidts-zzz...",
      "label": "第三账号"
    }
  ]
}
```

### 配置说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 账号唯一标识，建议使用 `account-0`, `account-1` 等 |
| `psid` | 是 | `__Secure-1PSID` Cookie 值 |
| `psidts` | 是 | `__Secure-1PSIDTS` Cookie 值 |
| `label` | 否 | 账号标签，用于 Web 面板显示 |

### 启用多账号

```bash
# 确保 accounts.json 在项目根目录
ls -la accounts.json

# 重启服务使配置生效
docker compose restart
```

### 验证多账号

```bash
# 查看账号池状态
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-你的API密钥"

# 输出示例：
# {
#   "total_accounts": 3,
#   "active_accounts": 3,
#   "rotation_strategy": "round-robin",
#   "accounts": [
#     {"id": "account-0", "status": "healthy", "requests": 10},
#     {"id": "account-1", "status": "healthy", "requests": 8},
#     {"id": "account-2", "status": "healthy", "requests": 12}
#   ]
# }
```

### 运行时添加账号

无需重启服务，通过 API 动态添加新账号：

```bash
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "psid": "g.a000新的值",
    "psidts": "sidts-新的值",
    "label": "新账号"
  }'
```

## 验证部署

### 健康检查

```bash
# 基础健康检查（无需认证）
curl http://localhost:5918/health

# 输出示例：
# {"status":"ok","service":"gemini2api"}
```

### 获取 API Key

首次启动时，API Key 会自动生成并显示在日志中：

```bash
# 查看日志获取 API Key
docker compose logs | grep "API_KEY"

# 或在 .env 文件中查看
cat .env | grep API_KEY
```

### 测试 API

```bash
# 获取可用模型列表
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-你的API密钥"

# 发送测试请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# 流式请求
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API密钥" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## 常见问题

### Cookie 过期

**症状**：服务返回 `SNlM0e not found` 错误

**解决方案**：
1. 重新获取 Cookie（参考上面的获取步骤）
2. 更新 `.env` 文件中的 Cookie 值
3. 通过 Web 面板更新 Cookie（无需重启）：
   ```bash
   curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer sk-你的API密钥" \
     -d '{
       "psid": "g.新的值",
       "psidts": "sidts-新的值"
     }'
   ```
4. 或重启服务：`docker compose restart`

### 端口冲突

**症状**：启动时报错 `Address already in use`

**解决方案**：
1. 修改 `.env` 中的 PORT 值：
   ```env
   PORT=5919
   ```
2. 或停止占用该端口的其他服务
3. 重启 Docker Compose：
   ```bash
   docker compose down
   docker compose up -d
   ```

### 内存不足

**症状**：服务频繁崩溃或响应缓慢

**解决方案**：
1. 增加 Docker 容器内存限制，编辑 `docker-compose.yml`：
   ```yaml
   services:
     gemini2api:
       mem_limit: 4g
       memswap_limit: 4g
   ```
2. 或在系统中增加 SWAP：
   ```bash
   # Linux 系统
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   ```

### 无法连接 Google

**症状**：请求返回网络错误或超时

**解决方案**：
1. 检查网络连接：`ping gemini.google.com`
2. 如果在中国大陆，需要配置代理
3. 编辑 `docker-compose.yml` 添加代理环境变量：
   ```yaml
   environment:
     - HTTP_PROXY=http://proxy:port
     - HTTPS_PROXY=http://proxy:port
   ```

### 认证失败

**症状**：API 请求返回 401 Unauthorized

**解决方案**：
1. 检查 API Key 是否正确
2. 确保请求头中包含 Authorization：
   ```bash
   -H "Authorization: Bearer sk-你的API密钥"
   ```
3. 检查 API Key 是否在 `.env` 中正确配置

### 账号标记为不健康

**症状**：Web 面板显示账号状态为 "unhealthy"

**解决方案**：
1. 检查 Cookie 是否过期
2. 更新 Cookie：
   ```bash
   curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer sk-你的API密钥" \
     -d '{"psid": "新值", "psidts": "新值"}'
   ```
3. 或通过 Web 面板的账号管理页面更新

## 性能优化

### 调整并发限制

编辑 `.env` 文件：

```env
# 每账号最大并发请求数（默认 8）
# 增加此值可提高吞吐量，但可能增加被限流的风险
MAX_CONCURRENT_PER_ACCOUNT=10
```

### 调整轮询策略

```env
# round-robin: 轮询分配（默认）
# failover: 故障转移，一个账号持续使用直到失败才切换
ROTATION_STRATEGY=failover
```

### 启用限流

```env
# 启用限流保护
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WINDOW=60
RATE_LIMIT_MAX=100
```

### 调整日志级别

```env
# 生产环境建议使用 warning 或 error
LOG_LEVEL=warning
```

## 监控和维护

### 查看系统信息

```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-你的API密钥"
```

### 查看使用统计

```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-你的API密钥"
```

### 定期检查账号状态

```bash
curl http://localhost:5918/admin/check-account \
  -H "Authorization: Bearer sk-你的API密钥"
```

### 查看实时日志

```bash
docker compose logs -f --tail=50
```

## 升级服务

```bash
# 拉取最新代码
git pull origin main

# 重新构建镜像
docker compose build --no-cache

# 重启服务
docker compose up -d

# 查看升级日志
docker compose logs -f
```

## 备份和恢复

### 备份数据

```bash
# 备份 data 目录（包含 Cookie、日志、配置等）
tar -czf gemini2api-backup-$(date +%Y%m%d).tar.gz data/

# 备份 .env 文件
cp .env .env.backup
```

### 恢复数据

```bash
# 恢复 data 目录
tar -xzf gemini2api-backup-20250517.tar.gz

# 恢复 .env 文件
cp .env.backup .env

# 重启服务
docker compose restart
```

## 安全建议

1. **保护 API Key**：不要在代码中硬编码 API Key，使用环境变量
2. **保护 Cookie**：不要将 `.env` 文件提交到 Git
3. **限制访问**：在生产环境中使用防火墙限制 API 访问
4. **定期更新 Cookie**：Google Cookie 会定期过期，建议每周检查一次
5. **监控日志**：定期查看日志，及时发现异常
6. **使用 HTTPS**：在生产环境中使用 HTTPS 反向代理（如 Nginx）

## 获取帮助

- 查看 [README.md](../../README.md) 了解项目概况
- 查看 [USAGE.md](./USAGE.md) 了解使用方法
- 查看 [API.md](./API.md) 了解 API 文档
- 提交 Issue：[GitHub Issues](https://github.com/xwteam/gemini2api/issues)
