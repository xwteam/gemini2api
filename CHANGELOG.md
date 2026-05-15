# Changelog

本文件记录项目的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [Unreleased]

## [0.5.1] - 2025-05-16

### Fixed
- 修复 curl_cffi AsyncSession 跨域 Cookie 累积导致 "Multiple cookies exist" 错误
- 每次 HTTP 请求前清除 session 内部 cookie jar，防止跨域名（google.com / gemini.google.com / accounts.google.com）Cookie 冲突
- 修复 `_obtain_session_token` 导航流程中 Cookie 在多个 Google 域名间累积的问题
- 修复 Cookie 热更新（reload）时仍可能触发域名冲突的问题

### Changed
- 新增 `_clear_session_cookies()` 方法，统一管理 curl_cffi 内部 cookie 清理
- `_obtain_session_token` 每步导航前刷新 cookies 变量，确保使用 PersistentCookieJar 的最新状态
- 验证 chrome124 为当前 curl_cffi 0.7.4 最高可用 impersonate 目标（chrome126+ 请求失败）

## [0.5.0] - 2025-05-15

### Added
- 反检测与协议伪装系统，大幅延长 session 存活时间
- 指纹配置管理（`data/fingerprint.json`），Chrome 版本/UA/TLS 指纹三者自动保持一致
- 动态请求头构建器，按 Chrome 真实顺序排列，根据请求类型（GET/POST）动态调整 Sec-Fetch-* 值
- 完整 Cookie 持久化（`data/cookies/`），自动捕获所有响应 Cookie 并持久化到磁盘
- Chrome 版本自动同步，每 2小时轮询 Google 版本 API，检测到新版本自动更新指纹
- 请求时间抖动，模拟人类操作间隔（导航 200-800ms / API 50-300ms / Cookie 轮换 1-3s）
- 版本降级策略：当 curl_cffi 不支持最新 Chrome 版本时，自动使用最近的可用版本

### Changed
- GeminiWebClient 全面集成指纹系统，替换硬编码请求头和手动 Cookie 管理
- TLS 指纹从固定 Chrome 120 升级为动态版本（当前 Chrome 131），支持自动跟进
- 健康检查和 Cookie 刷新间隔加入随机因子（±20%），避免固定周期特征
- Docker 新增 `data` 卷挂载，指纹配置和 Cookie 跨容器重建持久4.0] - 2025-05-15

### Changed
- 替换 httpx 为 curl_cffi，使用 Chrome TLS 指纹伪装，降低被 Google 识别为脚本流量的风险
- Cookie 轮换逻辑适配 curl_cffi 的 cookies 解析方式

### Removed
- 移除 httpx 依赖

## [0.3.0] - 2025-05-15

### Added
- 多账号轮询（负载均衡）功能，支持 round-robin 和 least-used 两种策略
- 账号池管理 API（`GET/POST/DELETE /admin/accounts`）
- 单账号状态检测接口（`GET /admin/accounts/{id}/check`）
- 每账号独立并发控制（`MAX_CONCURRENT_PER_ACCOUNT`）
- `accounts.json` 多账号配置文件支持
- 连续失败自动标记不健康，请求自动跳过故障账号

### Changed
- 架构重构：从单客户端模式升级为账号池模式
- 所有路由通过 AccountPool 分发请求，支持多账号透明切换
- 向后兼容：无 `accounts.json` 时自动使用环境变量单账号模式

## [0.2.0] - 2025-05-15

### Added
- 账号状态定时检测功能，支持自定义检测间隔
- 健康检查历史记录 API（`GET /admin/health-history`）
- Cookie 热更新接口（`POST /admin/reload-cookies`），无需重启即可刷新凭证
- 账号状态实时检测接口（`GET /admin/check-account`）
- 连续失败自动标记不健康机制

### Changed
- 许可协议变更为 PolyForm Noncommercial 1.0.0

## [0.1.0] - 2025-05-14

### Added
- Deep Research 深度研究功能
- OpenAI / Claude / Gemini 三格式函数调用支持
- SSE 流式输出（OpenAI / Claude）+ Chunked JSON（Gemini）
- API Key 自动生成与认证（`sk-` 前缀）
- Cookie 后台自动刷新，无感续期
- Docker 一键部署
- 速率限制（可选）
- 完整的管理接口（`/admin`）

## [0.0.1] - 2025-05-13

### Added
- 项目初始化
- 基础 Gemini Web 反向代理功能
- FastAPI + httpx 异步架构搭建
- Pydantic 配置管理与数据模型
