# Changelog

本文件记录项目的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [Unreleased]

## [1.6.21] - 2026-06-21

### Added
- 🔀 **Gemini→第三方自动兜底链**（`FALLBACK_ENABLED`，默认关闭，零回归）：任意 Gemini 模型（flash/pro/thinking）请求报错或返回空响应时，自动改用 API Key 池中已配置的第三方模型原生重试，客户端无感、仍只用一个模型名。
  - 选择自动且与具体服务商无关：候选取自 API Key 池中你已添加的第三方，按名称跳过明显非聊天的模型（image/video/audio/embedding 等），其余**随机轮询、一个失败（报错/空响应）就换下一个**直到成功。统一以非流式探测候选，从而既不会把报错也不会把空响应误当成功；流式则把验证后的结果转成 SSE（含原生工具调用）。
  - `FALLBACK_MODELS` 为可选的精确指定（逗号分隔、按序尝试）；留空即自动。新增 `app/core/fallback.py` 与单元测试 `tests/unit/test_fallback.py`，`.env.example` 同步。

## [1.6.20] - 2026-06-19

### Fixed
- 🐳 **修复 v1.6.19 非 root 镜像导致的升级回归**：v1.6.19 把镜像改为非 root（`USER appuser`）运行，但既有部署 bind 挂载的 `./data` 是旧 root 容器创建的（属主非容器用户），`docker compose pull && docker compose up -d` 后非 root 进程写 `data/cookies` 等触发 `PermissionError: [Errno 13]` → `Application startup failed` 崩溃重启循环。
  - 改为 **入口脚本（`docker-entrypoint.sh`）以 root 启动 → `chown` 修复 `/app/data`、`/app/api` 卷属主 → `gosu` 降权到非 root 的 `appuser` 运行**。既保持非 root 加固，又让历史部署 `docker compose pull` **无缝升级、无需手动 chown**。
  - `appuser` uid 改为 **1000**（与常见宿主用户、refresher 的 `pwuser` 对齐），共享 `./data` 属主一致，且升级后文件仍归宿主用户、便于免 sudo 查看。
  - `docker-compose.yml` 移除 v1.6.19 引入的 `user:` 行（属主与降权改由入口脚本处理），镜像新增 `gosu` 依赖。

## [1.6.19] - 2026-06-19

### Security
- 🔒 **管理面板存储/反射型 XSS 全面加固**：日志面板（`r.path`/`model`，中间件在鉴权前记录，未认证即可注入）、账号面板（`account.label` 注入 `onclick` 单引号字符串）、API Key 表、模型映射编辑器、Playground 图片 URL、远程二维码配置——所有动态字段统一 HTML 转义；内联 `onclick` 改 `data-*` + `addEventListener`（单引号无法靠 escapeHtml 兜住），属性值用专门的 `escapeAttr`。
- 🔒 **SSRF 修复**：远程附件下载改为禁跟随重定向并对每一跳 `Location` 重新校验（堵住经 3xx 跳转到 `169.254.169.254`/内网的绕过），并提前按 Content-Length 限制大小；统一转发引擎对存储的 `base_url` 增加出站 SSRF 校验，报错不再回显内网 IP。
- 🔒 **设置写坏 `.env` 的永久 DoS**：`POST /admin/settings` 改为先做取值域校验（拒绝非法 `rotation_strategy`、拒绝把 bool 当 int）、再更新内存、最后写盘，失败回滚，杜绝畸形值落盘导致重启崩溃。
- 🔒 **路径穿越**：客户端可控的 `conversation_id` 作文件名时做安全字符校验/哈希，无法逃逸数据目录读写删。
- 🔒 CORS 通配 + 凭据时启动告警；限流可选信任代理头取真实客户端 IP（默认行为不变）。

### Fixed
- 🌊 **真流式生图占位 URL 泄漏 + 不可兑现的 `_replace`**：改为纯追加式（回收不稳定尾段、在 final 事件对账），三家接口一致，纯文本回复字节级零回归。
- 🌊 OpenAI buffered keepalive 异常穿透生成器（绕过重试/错误映射）、Gemini 流式末帧改 Google camelCase 字段。
- 🔀 统一转发：OpenAI 流式 SSE 缺空行分隔符、Anthropic→OpenAI 转换缺终止 `data: [DONE]`、`base_url=None` 崩溃 → 干净 400。
- 📊 `USAGE_STATS_ENABLED=false`（或运行时关）时 usage-stats 端点不再 500；`hours` 非法参数返回 422；legacy 快照共享 dict 引用导致历史损坏、漏算当前未落盘区间已修。
- 👥 账号池：`accounts.json` 原子写 + 加载坏文件/坏条目容错（不再崩启动）、`add_account` 删除后 ID 冲突、round-robin 公平性。
- 🍪 Cookie 解析：删除/空值不再覆盖有效鉴权 Cookie，记录并清理 Max-Age/Expires。
- 🛡 指纹：配置原子写 + 坏文件容错、版本同步会话泄漏修复；`reload-cookies` 空池时返回 503 而非 500；深度研究子问题编号剥离不再误删数字开头正文。
- 🔑 无 `.env` 文件时自动生成的 API Key 现会落盘，不再每次重启更换。
- 🧰 `atomic_io` 写后 fsync 父目录提升崩溃持久性。

### Changed
- ⚙️ 让此前"声明了但未生效"的配置真正生效：`MODEL_WHITELIST`（过滤 /models）、`JITTER_ENABLED`、`VERSION_SYNC_INTERVAL`、`FINGERPRINT_CONFIG_PATH`。
- 🐳 主镜像与 refresher 镜像改非 root 运行 + 内置 HEALTHCHECK；`docker-publish` 确保 `api/` 热更新资源进镜像；refresher 接入 compose（`--profile refresher`）并修复鉴权（支持 `ADMIN_API_KEY`）/状态回注/间隔单位/空 PSIDTS。
- 🚦 CI 的 ruff + pytest 改为阻塞式门禁（不再 `continue-on-error`）。
- 🖼 生图代下载移出事件循环（`asyncio.to_thread`）。

### Docs
- 📄 README/zh-CN/.env.example 全面与 `app/config.py` 对齐：`MAX_CONCURRENT_PER_ACCOUNT` 3→8、补全约 16 个 env、补 7 个未文档化 `/admin` 端点、修复坏 curl 示例、修复 CHANGELOG `[0.4.0]` 损坏标题与多处 2025→2026 年份、Chrome 131/2h→124/24h 更正。
- 🧪 新增 `tests/unit/test_env_example_sync.py` 漂移测试，防止配置与 `.env.example` 再次脱节。

## [1.6.18] - 2026-06-19

### Fixed
- 🔧 **gemini-pro 生图仍报 network error**：v1.6.17 的 SSE 心跳已解决 flash 路径，但 `gemini-pro` 生图常需 **>60s**，Google POST 仍用 60s 默认超时导致服务端断连。修复：生图意图 POST 超时延长至 **180s**（普通对话仍 60s）；SSE keepalive 间隔 15s→**10s**；内容切片阶段也发 ping；生图结果切片 **delay=0** 更快收尾。

## [1.6.17] - 2026-06-19

### Fixed
- 🔧 **生图 playground 返回 `network error`**：生图意图走 buffered 伪流式时，`await generate()`（含图片代下载）整段阻塞期间零 SSE 字节，经 Cloudflare/nginx 前置代理触发首字节/读超时（520）→ 浏览器报 network error，而 Gemini 网页端图实际已生成。修复：立即发首帧 SSE + 阻塞期间周期 `: ping` 心跳保活；图片代下载默认 `=s2048`（替代 `=s0` 全分辨率）、单次超时收敛至 25s、失败降级 `=s512` 重试并回退占位提示（不静默丢图）。

### Added
- 🎨 **Playground 生图等待态 UX**：生图 1–2 分钟期间显示等待气泡与脉冲动画；识别 SSE 心跳刷新「仍在处理中」；network/520/502 友好 i18n 提示（5 语种）。

## [1.6.16] - 2026-06-19

### Fixed
- 🔧 **深度研究同步接口必崩**：`/gemini/v1beta/deepresearch` 因参数名笔误（`max_s`→`max_sources`）每次返回 500，已修复。
- 🔧 **第三方流式转发失效**：OpenAI/Anthropic 兼容转发因 HTTP client 在返回响应前被提前关闭，导致流式迭代时连接已断；改为由流生成器内部持有连接生命周期，流式转发恢复正常（非流式路径不变）。
- 🔧 **Anthropic 非流式转发崩溃**：`created` 字段解析消息 id 触发 `ValueError` 致 500，改用响应生成时间戳。
- 🔧 **账号槽位泄漏导致死锁**：客户端断连/流中断时槽位未归还，长期累积后全池报"无可用账号"；用 `try/finally` 兜底确保任何路径都释放槽位。
- 🔧 **多账号模型解析串扰**：模块级全局模型映射被多账号互相覆盖，改为按账号实例隔离。
- 🔧 **"Client not ready" 间歇报错**：账号 Cookie 失效时不再硬失败——选号时跳过不健康账号、将"未就绪/401/403"纳入 failover 自动换号、单账号在抛错前单飞自愈重载 Cookie。
- 🔧 **限流配置从未生效**：已创建 Limiter 但未挂载中间件/未对端点限流；补挂 `SlowAPIMiddleware` 并对对话端点限流（默认 `RATE_LIMIT_ENABLED=false` 旁路，零回归）。

### Security
- 🔒 **管理权限分离**：新增可选 `ADMIN_API_KEY`，`/admin/*` 走独立鉴权（留空则回退 `API_KEY`，单 key 仍可管全部，零回归）。
- 🔒 **API Key 不再明文写入启动日志**（改掩码 `sk-****`）。
- 🔒 **SSRF 防护**：API Key 探测的 `base_url` 与多模态附件远程 URL 在请求前校验，拦截内网/环回/链路本地/云元数据地址，且不回显内网响应。
- 🔒 **凭据脱敏**：第三方密钥导出默认脱敏（需 `?reveal=true` 取明文）、管理接口的 Google PSID 凭据响应改掩码（字段保留）。
- 🔒 **凭据/Cookie 文件原子写**（临时文件 + 原子替换），加载时坏记录容错跳过，不再因单条损坏清空整库。
- 🔒 **API Key 恒定时间比较**（`secrets.compare_digest`，防时序侧信道）。
- 🔒 **CORS 可配置**：新增 `CORS_ALLOW_ORIGINS` / `CORS_ALLOW_CREDENTIALS`（默认与原行为完全一致，可按需收紧）。
- 🔒 **前端确认弹窗 XSS 加固**：`showConfirm` 文案统一转义后再注入。

### Added
- 🧪 **自动化测试与 CI 门禁**：引入 pytest 单元/冒烟测试与 GitHub Actions CI（ruff + pytest），并补齐 `.gitignore`/`.dockerignore` 防止凭据误入构建上下文/仓库。
- ♿ **管理面板无障碍与多语言增强**：全局 `:focus-visible` 焦点环、修正暗色按钮/三级文本对比度、弹窗 `role=dialog`+焦点陷阱+Esc、表单 `label` 关联、登录页/状态徽章/日期数字多语言。

## [1.6.15] - 2026-06-06

### Added
- 🧹 **自动清理 Gemini 网页端堆积会话**：API 每次对话都会在 Gemini 网页端（gemini.google.com）留下一条会话记录，长期调用会堆积大量历史。现在新增自动清理：
  - 后台定时（默认每 6 小时）删除超过保留窗口（默认 24 小时）的旧网页会话，**置顶会话永不删除**
  - 循环清理直到删空，解决重度账号堆积数百会话单轮清不完的问题
  - 保留窗口（24h）远大于反代上下文窗口（6h），**正在续接的多轮对话绝不会被误删**；反代多轮上下文用本地存储维护，与网页端会话记录无关
  - 设置面板新增「网页会话清理」分组（开关 / 保留时长 / 清理间隔 / 是否跳过置顶），5 语种本地化
  - 新增管理端点 `GET /admin/web-chats`（列出网页会话）、`POST /admin/cleanup-web-chats`（手动触发清理，后台异步执行立即返回）
  - 清理参数有下界保护（保留时长至少 1 小时），避免误传 0 清空所有会话

## [1.6.14] - 2026-06-02

### Fixed
- 🖼️ **生图意图识别补充意愿动词**：之前"我想要一张…的图""要一张图""我需要一张海报"等用「想要/要/需要」表达的生图请求没被识别，导致走真流式、图片跑到文字后面（还可能出现 `http` 残片）。现在补充了意愿动词（想要/要/想/需要/求/want/need），这类请求正确走生图、图片排在前面。仍要求「图像名词+动词」同时出现，"我想吃饭""要去开会"等不会误判。

## [1.6.13] - 2026-06-02

### Changed
- 🖼️ **生图回复改为「图片在前」+ 紧凑排版**：生图成功时图片排在最前面，紧跟文字描述（单换行，去掉之前的多余空行），不再是"一大段文字+空行+图片"。三家接口（OpenAI/Claude/Gemini）一致：OpenAI/Gemini 图片 markdown 在前、Claude image block 在文字 block 前。
- 🎯 **生图意图识别大幅增强**：扩充关键词（画/生成/设计/做/来张…图、海报/插画/logo/照片、poster/image/draw 等），并新增宽松兜底判断（图像名词+产出动词组合），让"设计一张海报""来张柴犬图""帮我弄个logo"等口语化生图请求也能正确走生图路径、图片排在前面，避免漏识别导致图片跑到文字后面。

### Fixed
- 🧹 **过滤更多 googleusercontent 占位 URL**：除 `image_generation_content` 外，新增过滤 `image_retrieval`/`image_collection`（Gemini 走"图片检索"而非"生成"时返回的占位 URL，客户端无法访问）。过滤后若无有效图片，返回友好提示引导用明确生图指令，而不是返回空内容或无效网址。

## [1.6.12] - 2026-06-02

### Fixed
- 🛠️ **修复 agent（如 Hermes）带 tools 时生图被压制、工具调用畸形**：agent 客户端每个请求都带 tools 参数，导致两个问题——
  - **生图被压制**：带 tools 时工具模拟提示词会劫持 Gemini，让它"以为自己只是文本AI画不了图"。现在**检测到明确生图意图时自动跳过工具模拟、直接生图**（即使带 tools），Hermes 里说"画图"能正常出图。
  - **工具调用畸形 JSON 透传**：Gemini Web 非原生 function-calling 模型（已确认网页版逆向端点不支持原生工具调用，提示词模拟是唯一路径），模拟工具调用时常输出畸形 JSON（对象当数组、缺引号、被 markdown 包裹、夹带解释文字），之前直接当文本透传给客户端。现在**多层容错解析**：剥离 markdown 代码块、提取 JSON 子串、容忍单对象/缺 status/OpenAI 风格嵌套；无法挽救的畸形工具 JSON 不再透传垃圾，降级为干净提示。
- 🔧 **修复 Gemini 原生接口（/v1beta）工具调用返回文本而非 `functionCall`**：之前 Gemini 格式接口的工具调用把工具 JSON 当文本塞回 parts，现在正确转成原生 `functionCall` part（`{name, args}`）。

### Changed
- 改进工具调用提示词：更严格的 JSON 格式约束 + few-shot 示例 + 允许 ```json 代码块包裹，降低模型写畸形的概率。
- 生图意图检测收窄关键词（必须是明确的画图/生成图片表达），避免"生成报告""create a plan"等被误判为生图。

## [1.6.11] - 2026-06-02

### Added
- 🔁 **503 智能 failover（多账号容灾）**：Google 对数据中心 IP 会间歇性返回 503 "Sorry" 限流（账号×IP 级，会自愈但无法根除）。现在遇到 5xx/503 时：
  - 单账号只快速重试 1 次（短退避 0.5s，应对瞬时抖动），不再 `2^n` 长退避空耗 7 秒
  - 多账号时**自动切换到下一个可用账号重试**（failover），一个被限流立刻换下一个，可用性大幅提升
  - 被限流的账号进入 30 秒**冷却**（期间不优先选），但**不标记为 expired**（它没坏，只是被限流），冷却结束自动恢复优先级
  - 流式请求在「首字推送前」遇 503 也会 failover；已开始吐字后出错则终止（避免重复内容）
  - 所有账号都被限流时快速抛出 503（不死循环空转）
- `/admin/status` 每个账号新增 `cooling_down` 字段，便于观察哪个账号正被限流冷却

### Changed
- 新增配置项 `same_account_5xx_retries`（默认 1）、`failover_cooldown`（默认 30 秒）

## [1.6.10] - 2026-06-01

### Added
- ⚡ **真流式输出**：三家接口（OpenAI/Claude/Gemini）的流式响应改为**真正的增量流式**。之前是「伪流式」——先等 Gemini 整段生成完，再把完整文本切词假装逐字吐出，客户端/agent 感知不到提速。现在直接读 Gemini 的 `StreamGenerate` 增量响应，**首字一生成就开始推送**，token 实时到达，聊天打字机体感大幅改善
  - 纯文本对话走真流式；带工具调用（tool_calls）或附件上传的请求仍走完整收集路径（保证功能正确，零回归）
  - 流式请求用独立连接隔离，规避 curl_cffi 并发流的已知问题，多路并发流式互不串扰

### Changed
- 🚀 **并发能力大幅提升**：单账号最大并发从 `3` 提升到 `8`（面板「设置」可继续调整）。更关键的是，**并发满载时不再直接报错** `No available accounts`——改为**排队等待**可用槽位（默认最多等 60 秒），等不到才报错。这样 agent 类客户端（会并发发起多个请求）不再一并发就失败，可以稳定干活
- 📝 文档：建议 agent 重负载场景优先使用 `gemini-flash`（响应约 4-5 秒），比 `gemini-pro`（约 9-17 秒）更快

## [1.6.9] - 2026-06-01

### Fixed
- 🖼️ 生成图片现在返回**全分辨率原图**：之前下载的是压缩缩略图（如 512px），分辨率和大小都不对。现在下载时给图片 URL 加 `=s0` 后缀，拿到原始全分辨率图（如 1408×768）

## [1.6.8] - 2026-06-01

### Fixed
- 🖼️ 生图时不再返回 `googleusercontent.com/image_generation_content/...` 占位网址：该占位 URL 没有实际意义（真图在图片数据里），现已从回复文本中过滤，生图只返回图片本身，不留网址也不留空文本

## [1.6.7] - 2026-06-01

### Fixed
- 🖼️ 控制面板模型测试：生成的图片现在直接渲染为图片显示，不再显示成 markdown 文本/URL（之前用 textContent 纯文本展示，markdown 图链接显示成了原始文字）
- 面板回复中的图片（markdown `![](url)` / data URI / `/images/` 链接）统一解析渲染为 `<img>`

## [1.6.6] - 2026-05-31

### Added
- 🖼️ 生成图片本地托管：对话接口的生图结果改为返回可访问的本地 URL（`/images/{id}`），CLI/agent 客户端（OpenClaw、Hermes 等）也能正常渲染显示，不再是无法显示的 base64
  - OpenAI chat：markdown `![](http://host/images/xxx.png)`
  - Claude messages：image block 用 `source.type=url`
  - Gemini generateContent：inlineData 保留 + 文本附图片 URL
  - `/v1/images/generations` 接口仍返回 b64_json（OpenAI 标准）
- 图片存 `data/generated_images/`（bind-mount 持久），后台每 6 小时清理超过 7 天的旧图

## [1.6.5] - 2026-05-31

### Added
- 🎨 AI 生成图片支持（基于 Gemini Web 的 Nano Banana / Imagen）：
  - 新增 OpenAI 兼容图片接口 `POST /v1/images/generations`（+ `/openai/v1/...`），返回 b64_json
  - 三家对话接口检测到生成图片时自动嵌入回复：OpenAI（markdown data URI）、Claude（image block）、Gemini（inlineData part）
  - 靠 prompt 触发生图（不含生图意图时自动加 "Generate an image of" 前缀）
  - 服务端带 cookie 代下载图片（lh3 多级 302 重定向，客户端直接访问会 403），转 base64 返回

## [1.6.4] - 2026-05-31

### Added
- 三家接口全部暴露标准裸路径，主流 SDK 开箱即用、无需改 base_url 后缀：
  - OpenAI：`/v1/chat/completions`、`/v1/models`
  - Claude：`/v1/messages`、`/v1/messages/count_tokens`
  - Gemini：`/v1beta/models/{m}:generateContent`、`/v1beta/models/{m}:streamGenerateContent`、`/v1beta/models`
- 原有带前缀路径（`/openai/v1`、`/claude/v1`、`/gemini/v1beta`）全部保留，向后兼容

### Fixed
- 修复部署机制：`docker-compose.yml` 由 `build: .` 改为 `image: ghcr.io/xwteam/gemini2api:latest`，`docker compose pull` 真正生效（此前因 build 优先，pull 被忽略，生产长期跑本地旧镜像导致面板版本号卡住）

### Notes
- 裸 `/v1/models` 归 OpenAI 格式独占（同一路径无法同时返回两种格式）；Claude 模型列表仍可通过 `/claude/v1/models` 获取

## [1.6.3] - 2026-05-31

### Added
- 图片/文件上传支持：OpenAI（image_url）、Claude（image.source）、Gemini（inline_data）三格式多模态
- 上传模块 `app/core/file_upload.py`：content-push.googleapis.com，支持 base64 data URI 和远程 URL
- Playground 图片上传 UI：添加图片按钮、缩略图预览、删除、聊天显示
- 对外固定稳定模型名 `gemini-pro` / `gemini-flash` / `gemini-flash-thinking`（API 稳定契约，永不变）
- 模型改用网页版 `otAQ7b`(GetUserStatus) RPC 拉取账号真实可用模型，内部按账号订阅等级动态映射

### Fixed
- 重启不再丢 Cookie：initialize 优先加载磁盘持久化的有效 Cookie，不被 .env 旧值覆盖
- 模型不再用正则从 HTML 乱抓（消除 gemini-2.5-flash-image 等不可用脏数据）
- 深色主题取消按钮文字白色（补 `.btn-secondary` 样式）
- 修复 gemini.py 既有 bug：generate 调用签名、system_instruction 类型、build_tool_prompt 用法、split_into_chunks async

## [1.6.2] - 2026-05-19

### Added
- 会话过期机制：页面 5 分钟无操作自动登出，保护面板安全

## [1.6.1] - 2026-05-18

### Added
- 新增 failover（故障转移）策略：一个账号持续使用直到失败才自动切换下一个
- 模型选择通过 `x-goog-ext-525001261-jspb` header 实现真正切换，支持 gemini-3 全系列
- 旧版模型名别名兼容（gemini-2.5-pro → gemini-3-pro-plus 等）
- 新增思考模式：`gemini-2.5-flash-thinking`、`gemini-2.0-flash-thinking`
- 对话上下文持久化（混合模式）：优先 Gemini 原生 conversation_id 多轮续接，本地 `data/conversations/` 备份历史
- 请求参数新增 `conversation_id` 字段，响应返回 `conversation_id` 供下次续接
- 容器时区设置为 Asia/Shanghai，日志显示北京时间
- Gemini 会话过期时自动 fallback 到完整 prompt 拼接模式，对客户端透明
- 多语言切换系统（简体中文/繁體中文/English/日本語/한국어），语言偏好 localStorage 持久化
- 语言切换器组件（右上角下拉菜单），MutationObserver 自动翻译动态元素
- 全部页面组件 data-i18n 国际化标记（仪表盘/账号管理/日志/模型测试/使用统计/API管理/设置）
- 自定义确认弹窗（showConfirm），替换浏览器原生 confirm()，支持 warning/danger/info 三种类型
- 服务重启按钮（右上角控制栏），`POST /admin/restart` 端点，重启后自动轮询恢复并刷新页面
- 模型测试 textarea 添加快捷键提示（Enter 发送，Shift+Enter 换行）

### Fixed
- 移除无意义的 least-used 策略（Gemini Web 无法获取真实用量）
- 模型列表统一为用户友好名称（gemini-2.5-xxx），不再暴露内部 gemini-3 名称
- 响应中 model 字段返回用户请求的原始模型名
- Playground 模型下拉框从统一别名列表加载，不再使用页面缓存的旧模型名
- Playground 对话支持上下文（累积消息历史），点击"新对话"清空
- 修复 MutationObserver 无限循环导致页面卡死（textContent 变更触发 addedNodes 回调）
- 设置页面：可视化管理运行时配置（刷新间隔、重试次数、速率限制、健康检查等）
- `GET/POST /admin/settings` API，支持分组查看和批量更新配置
- API Key 管理系统：集中管理第三方大模型 API Key（OpenAI、Anthropic、Gemini、OpenRouter、自定义）
- `GET/POST/DELETE /admin/api-keys` 完整 CRUD API，支持批量导入导出
- Provider 目录（`/admin/api-keys/catalog`），内置主流模型列表
- 统一转发引擎（`api_forwarder`）：请求模型不在 Gemini Web 时自动转发到对应 Provider
- OpenAI 兼容格式转发（支持流式），Anthropic 格式双向转换
- `/openai/v1/models` 自动聚合 Gemini Web 模型和 API Key 池中的模型
- 前端设置面板：分组表单、控件、保存/重置
- 前端 API 管理面板：添加/删除/启禁用 Key、批量操作、导入导出

### Changed
- 用量统计图表自适应容器宽度，高度增至 320px，撑满面板
- 用量统计增加更多时间范围选项（3d/30d/全部），粒度与时间范围智能联动
- 模型分布：无请求数据时从账号池获取模型列表作为占位显示
- 模型发现 regex 改进：只匹配含版本号的完整模型名，过滤无效短名
- 新增 `MODEL_WHITELIST` 配置项，支持逗号分隔的模型白名单过滤
- 用量统计面板全面中文化（图例、空状态、加载提示）
- 柱状图颜色从蓝色改为项目主题绿色（#059669）
- 日志面板 UI 优化：选中行样式改为绿色调，与侧边栏风格统一
- 日志面板全面汉化：标题、筛选按钮、表头、搜索框、分页、详情面板
- 方向徽章中文化：ingress → 入站，egress → 出站
- 修复 CSS 语法错误（white-space、badge text-transform 截断）

## [0.7.0] - 2026-05-16

### Added
- 结构化实时日志系统，替代旧的纯文本 SSE 流
- LogStore 环形缓冲区（2000 条），支持分页、方向过滤、文本搜索
- HTTP 请求捕获中间件，自动记录方法、路径、状态码、延迟、模型
- `GET /admin/logs` 分页查询接口，支持 direction/search 参数
- `GET /admin/logs/state` 和 `POST /admin/logs/state` 日志状态管理
- `POST /admin/logs/clear` 清空日志
- `GET /admin/logs/{id}` 单条记录详情
- 前端表格式日志面板：方向徽章、状态码着色、延迟显示、JSON 详情面板
- 前端 REST 轮询（1.5s 间隔）+ 暂停/恢复控制

### Removed
- 移除旧的 BufferLogHandler 和 `/admin/logs/stream` SSE 端点
- 移除前端 EventSource 日志流

## [0.6.0] - 2026-05-16

### Added
- 用量统计系统，持久化时序快照，重启不丢失历史数据
- `GET /admin/usage-stats/summary` 接口，返回累计请求数、错误率、平均延迟、轮换成功率
- `GET /admin/usage-stats/history` 接口，支持 raw/five_min/hourly/daily 粒度和自定义时间范围
- LiveMetricsCollector 单例，线程安全记录每次请求的模型、延迟和 Cookie 轮换事件
- 后台快照循环（默认 5 分钟），自动采集并持久化到 `data/usage-stats.json`
- 基线机制（baseline），账号池重置时吸收差值，保证历史数据单调递增
- 前端"使用统计"面板：Summary 卡片 + SVG 图表（请求柱状 + 延迟折线）+ 模型分布表格
- 粒度/时间范围选择器，支持 5 分钟/小时/天 粒度和 1h/6h/24h/7d 范围

### Changed
- `account_pool.generate()` 自动记录每次请求的模型和响应延迟
- `gemini_client._rotate_cookies()` 自动记录轮换成功/失败事件
- 配置新增 `USAGE_STATS_ENABLED`、`USAGE_STATS_INTERVAL`、`USAGE_STATS_RETENTION_DAYS`

## [0.5.2] - 2026-05-16

### Added
- batchexecute 心跳 RPC（`otAQ7b`），初始化和每次 auto-refresh 后自动发送，模拟浏览器活跃行为
- Cookie jar 增加 Set-Cookie 响应头解析，补充捕获 `response.cookies` 可能遗漏的 Cookie
- `cookie_names()` 调试方法，返回当前所有持久化 Cookie 名称

### Changed
- `update_from_response` 双通道捕获：先从 `response.cookies`，再从 `Set-Cookie` 头补充
- RotateCookies 现在自动携带完整 Cookie jar（SID/HSID/APISID/SAPISID 等）

## [0.5.1] - 2026-05-16

### Fixed
- 修复 curl_cffi AsyncSession 跨域 Cookie 累积导致 "Multiple cookies exist" 错误
- 每次 HTTP 请求前清除 session 内部 cookie jar，防止跨域名（google.com / gemini.google.com / accounts.google.com）Cookie 冲突
- 修复 `_obtain_session_token` 导航流程中 Cookie 在多个 Google 域名间累积的问题
- 修复 Cookie 热更新（reload）时仍可能触发域名冲突的问题
- 修复 Web 面板点击模型名称复制失败的问题（HTTP 环境下 navigator.clipboard 不可用）
- 修复 Playground 模型测试下拉列表硬编码、与实际可用模型不一致的问题

### Changed
- 新增 `_clear_session_cookies()` 方法，统一管理 curl_cffi 内部 cookie 清理
- `_obtain_session_token` 每步导航前刷新 cookies 变量，确保使用 PersistentCookieJar 的最新状态
- 验证 chrome124 为当前 curl_cffi 0.7.4 最高可用 impersonate 目标（chrome126+ 请求失败）
- `copyToClipboard` 增加 `document.execCommand` 降级方案，兼容非 HTTPS 环境
- Playground 模型列表改为从 API 动态加载

## [0.5.0] - 2026-05-15

### Added
- 反检测与协议伪装系统，大幅延长 session 存活时间
- 指纹配置管理（`data/fingerprint.json`），Chrome 版本/UA/TLS 指纹三者自动保持一致
- 动态请求头构建器，按 Chrome 真实顺序排列，根据请求类型（GET/POST）动态调整 Sec-Fetch-* 值
- 完整 Cookie 持久化（`data/cookies/`），自动捕获所有响应 Cookie 并持久化到磁盘
- Chrome 版本自动同步，每 24 小时轮询 Google 版本 API，检测到新版本自动更新指纹
- 请求时间抖动，模拟人类操作间隔（导航 200-800ms / API 50-300ms / Cookie 轮换 1-3s）
- 版本降级策略：当 curl_cffi 不支持最新 Chrome 版本时，自动使用最近的可用版本

### Changed
- GeminiWebClient 全面集成指纹系统，替换硬编码请求头和手动 Cookie 管理
- TLS 指纹从固定 Chrome 120 升级为动态版本（当前 Chrome 124，curl_cffi 0.7.4 最高可用），支持自动跟进
- 健康检查和 Cookie 刷新间隔加入随机因子（±20%），避免固定周期特征
- Docker 新增 `data` 卷挂载，指纹配置和 Cookie 跨容器重建持久化。

## [0.4.0] - 2026-05-15

### Changed
- 替换 httpx 为 curl_cffi，使用 Chrome TLS 指纹伪装，降低被 Google 识别为脚本流量的风险
- Cookie 轮换逻辑适配 curl_cffi 的 cookies 解析方式

### Removed
- 移除 httpx 依赖

## [0.3.0] - 2026-05-15

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

## [0.2.0] - 2026-05-15

### Added
- 账号状态定时检测功能，支持自定义检测间隔
- 健康检查历史记录 API（`GET /admin/health-history`）
- Cookie 热更新接口（`POST /admin/reload-cookies`），无需重启即可刷新凭证
- 账号状态实时检测接口（`GET /admin/check-account`）
- 连续失败自动标记不健康机制

### Changed
- 许可协议变更为 PolyForm Noncommercial 1.0.0

## [0.1.0] - 2026-05-14

### Added
- Deep Research 深度研究功能
- OpenAI / Claude / Gemini 三格式函数调用支持
- SSE 流式输出（OpenAI / Claude）+ Chunked JSON（Gemini）
- API Key 自动生成与认证（`sk-` 前缀）
- Cookie 后台自动刷新，无感续期
- Docker 一键部署
- 速率限制（可选）
- 完整的管理接口（`/admin`）

## [0.0.1] - 2026-05-13

### Added
- 项目初始化
- 基础 Gemini Web 反向代理功能
- FastAPI + httpx 异步架构搭建
- Pydantic 配置管理与数据模型
