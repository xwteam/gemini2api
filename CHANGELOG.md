# Changelog

本文件记录项目的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [1.6.50] - 2026-10-27

### Fixed

- 🧷 **混合账号池：账号没有这个模型时换号**：有的账号有 Argon、有的没有时，请求落到没有的那个账号上过去直接回 400（`Model unavailable`），哪怕池里别的账号有。现在这种情况不计失败、不冷却、不算一次请求，直接换下一个账号；有这个模型的账号只是满载时按池忙回 529（客户端会重试），所有账号都没有才回 400；别的账号报过的真实错误（如 503）优先于这个 400。
- 📎 **附件上传重试**：上传遇到网络错误、5xx 或空响应时等 1 秒重试一次（4xx 是请求本身的问题，不重试）。过去一次失败就把附件静默丢掉，模型看不到图却照样回答。

### Added

- 🖼️ 一次生成多张图时并发下载（最多 4 张同时），顺序不变；过去逐张串行。
- `GET /v1/models/{model}`（也挂在 `/openai/v1` 下）：OpenAI SDK 的 `models.retrieve`，口径与模型列表一致（含白名单、访问密钥可见范围），查不到回 404 `model_not_found`。

### Docs

- 五语言 DEPLOY.md 的多账号章节改为 `data/accounts.json`（过去让 Docker 用户在项目根目录建 `accounts.json`，而 compose 只挂载 `./data`，容器里根本看不到）。

## [1.6.49] - 2026-10-26

### Fixed

- 🧩 **Gemini 路径不再丢 `developer` 消息**：Codex 和 OpenAI 新版 SDK 用 `developer` 角色代替 `system` 发说明（Codex 的权限、沙箱规则就在里面），过去拼提示词时没有这个分支，整段被丢掉（10-26 中转站复现：让模型「回答以喵开头」的 developer 说明完全没生效）。现在按 `System:` 拼进提示词；旧版 OpenAI 的 `function` 角色按工具结果处理。转给第三方时 `developer` 改成 `system`（严格的上游不认）。
- 🧩 **采样 / 格式参数转给第三方模型和兜底**：`top_p`、`stop`、`presence_penalty`、`frequency_penalty`、`seed`、`response_format`、`max_completion_tokens`、`parallel_tool_calls`、`stream_options` 过去在请求模型里没有字段、被直接丢弃（复现：`stop: ["5"]` 时 deepseek 照样数到 9）。现在原样转给 OpenAI 兼容上游（空值不带；`stream_options` 只在流式时带，兜底探测是非流式，带上会 400；`parallel_tool_calls` 只在带了工具时才带）。Anthropic 上游合并全部 system / developer（过去只留最后一条），并带上 `stop_sequences`；`temperature` / `top_p` 刻意不转（新版 Claude 不接受两者同时出现）。`/v1/responses` 走第三方时同样转 `top_p`、`parallel_tool_calls`，`text.format` 转成 `response_format`。
- 💾 **面板里加的账号升级不再丢**：`ACCOUNTS_FILE` 默认值从 `accounts.json` 改为 `data/accounts.json`。docker-compose 只挂载 `./data`，旧默认位置在容器层里，`docker compose pull && up -d` 重建容器后面板加的账号全丢。旧默认位置有文件时启动会复制过来（旧文件保留）；复制是原子写，失败（包括旧文件不是 UTF-8）不会留下半截文件，会退回读旧文件。显式配置照旧尊重，但在容器里配置的路径不在 `data/` 下时会打 WARNING，并给出 `docker cp` 的处置命令；旧文件还在、或 `.env` 的 `GEMINI_PSID` 对不上任何已载入账号时也会提醒。`.env.example` 与 README 的多账号说明同步改成 `data/accounts.json`。
- 💾 **面板的「第三方兜底」开关升级不再被顶回去**：这个开关过去只写容器内镜像层的 `/app/.env`（宿主机 `.env` 在容器里不可见），升级重建容器后就变回宿主机 `.env` 的值（10-26 中转站：面板 22:13 关掉兜底，宿主机 `.env` 仍是 true，下一次部署会悄悄重新打开）。现在与设置页同一套持久化：写进 `data/settings-overrides.json`（挂载卷、启动回放、优先级高于环境变量），任一步失败整体回滚。
- 🙅 拒答套话再收一句：`身为一个语言模型，我没办法提供这方面的帮助。`（10-26 22:23 gemini-pro 对一句「你好」回的）。

## [1.6.48] - 2026-10-26

### Fixed

- 🛠️ **`/v1/responses` 用第三方模型时，工具调用能跑通了**（Codex 等客户端）：
  - **流式不再丢工具调用**：过去流式只转发上游的文字增量，第三方模型发起的工具调用被整个丢掉，客户端只看到一句「我来列一下文件」就结束了；Codex 恒用流式，工具循环根本跑不起来（10-26 中转站用 deepseek-v4-flash 复现）。现在按 index 累积上游的 `tool_calls` 增量，收尾发出完整的 `function_call` 输出项（`output_item.added` → `function_call_arguments.delta/done` → `output_item.done`），`response.completed` 里也带上；只有工具调用的回合不再塞一个空 message；
  - **非流式文字和工具调用同时保留**（「我先看一下目录」+ 调用），过去有工具调用时文字被丢掉；上游没给调用 id 时补一个 `call_` id；
  - **历史按 OpenAI 原生格式发给第三方**：`function_call` → `assistant.tool_calls`（连续调用、紧跟在 assistant 文字后的调用并进同一条消息），`function_call_output` → 带 `tool_call_id` 的 `tool` 消息（`output` 为内容块数组时取其中文字）。过去是「(called tool X with arguments …)」纯文本 + 不带 `tool_call_id` 的 tool 消息，严格校验的上游会 400；
  - **只转发 `function` 类型的工具**：Codex 带的 `web_search` / `local_shell` / `custom` 等内置工具过去被转成空名字的函数，现在略过；没有可发的工具时不带 `tool_choice`。
  - 上游的并行工具调用（有的上游全给 `index: 0`、或干脆不给 `index`）不再被并成一个；攒工具调用参数期间按保活间隔发心跳，长补丁不被中间代理当空闲掐断；
  - `developer` 角色转成 `system`，assistant / system 的内容块数组拍成字符串（严格的 chat 上游不认）；
  - Gemini 路径（拍成文本的工具历史）不变。
- 🛠️ **Anthropic 类第三方上游的流式工具调用不再丢**：`tool_use` 块与 `input_json_delta` 过去没有转换，`/v1/chat/completions` 与 `/v1/responses` 走这类上游的流式工具调用都整个丢掉；现在转成 OpenAI 的 `tool_calls` 增量。

## [1.6.47] - 2026-10-26

### Fixed

- 🙅 **谷歌的「语言模型」类拒答套话不再当成回答**：谷歌有时整段只回一句「我只是一个语言模型，无法提供这方面的帮助。」「我无法提供这方面的帮助，因为我只是一个语言模型。」「由于程序代码的局限，我没法办到。」（中转站会话记录里的真机样本：问的是「17 是质数吗」「9.9 和 9.11 哪个大」「用两个字回答：你好」这种好答的问题，最后一句出现在 10-26 flash 故障期间），过去原样返回给客户端。现在内置识别这三句和英文同族原句（如 `I'm just a language model, so I can't help you with that.`），处理与 v1.6.46 的失败套话相同：
  - 整段回答恰好是其中一句才算（包含、前缀都不算）；用户本来就让模型复述这句时不算；流式同样先扣住疑似开头；
  - 换账号重试（不在同一账号上快速重试），`/v1/chat/completions` 走第三方兜底，否则回 502 `api_error`；账号只短暂冷却、不计连败；
  - **不计入模型熔断**：它也可能是某个问题每次都会触发的真拒答，两个这样的请求不该把整个模型族熔断掉。
- 套话比较时弯引号按直引号算（`I’m` 与 `I'm` 视为同一句）。

## [1.6.46] - 2026-10-26

### Fixed

- ⏳ **真流式请求不再被谷歌的心跳帧一直吊着**：谷歌某个模型排队 / 卡住时，响应头要 60 秒才到，之后每 60 秒发一个不带任何内容的心跳帧（`[{"37":[0]}]`）。过去流式请求按「两次收到数据之间最多等 120 秒」计时，心跳不断把它重置，于是会一直等下去（10-26 实测 flash 故障时客户端干等 239 秒）；流式会话的 180 秒超时在 curl_cffi 0.7.4 下也拦不住。现在流式与非流式用同一个族预算（flash-lite 60 秒、flash 120 秒、pro / argon 300 秒，生图取大，`GENERATE_TIMEOUTS` 同样生效）：
  - 心跳帧、会话元数据帧不算进展；超过预算还没有任何正文 / 思考 / 图片，就按超时处理（开了兜底的 `/v1/chat/completions` 先兜底，否则协议内的 `timeout_error`）；
  - 到期时**先中止与谷歌的连接再报错**，账号槽位当场释放（过去即使报错，也要等谷歌自己结束响应才退出）；
  - pro 慢思考不再被底层 180 秒的低速超时提前打断。
- 🩺 **谷歌的失败套话不再当成回答**：谷歌出故障时常常 1～2 秒就回一句固定的 `I seem to be encountering an error. Can I try something else for you?`，过去被当成正常回答返回给客户端，还写进了会话记录。现在整段回答恰好是这句（或 `GEMINI_FAILURE_REPLIES` 追加的套话）时，按上游错误处理：
  - 换账号重试（不在同一账号上快速重试），`/v1/chat/completions` 走第三方兜底，否则回 502 `api_error`（流式为各协议既有的错误事件）；
  - 账号只短暂冷却，不计连败，不会因此被标成过期；
  - 用户自己要求模型复述这句话时照常返回（只看用户 / 系统 / 工具内容，历史回答里出现过这句不影响识别）；
  - 流式在回答开头短暂扣住疑似套话的那几个字，一确认不是就立刻放出。

### Added

- 🔌 **模型级熔断**：同一个模型族在 5 分钟内有 2 个不同的请求「几乎没收到数据就超时」或回了失败套话，就判定谷歌那边这个模型出了故障。之后 60 秒内，开了第三方兜底（且确有兜底候选）的 `/v1/chat/completions` 请求直接走兜底，不再先白等一个预算（流式期间照常发保活帧）。到期后放一个真实请求去试谷歌：恢复了就关闭熔断，没恢复开放期翻倍（最长 5 分钟）。
  - 只计「疑似故障」：同一请求的换号、重试、客户端重发只算一次；已经收到大量内容后才超时的长回答不计；
  - 没开兜底的部署，以及 Claude / Gemini 原生 / Responses 等没有兜底的接口，照常走谷歌（它们的结果同样会更新熔断状态）；
  - 状态在 `/admin/status`、`/admin/accounts` 的 `model_breakers` 里；面板账号页在熔断期间显示提示；
  - 可用 `MODEL_BREAKER_ENABLED`、`MODEL_BREAKER_THRESHOLD`、`MODEL_BREAKER_WINDOW`、`MODEL_BREAKER_COOLDOWN`、`MODEL_BREAKER_MAX_COOLDOWN` 调整；状态只在内存里，重启后清空。
- `GEMINI_FAILURE_REPLIES`：追加需要识别的谷歌失败套话（`|` 分隔）。

## [1.6.45] - 2026-10-26

### Fixed

- ⏱️ **生成超时不再回纯文本 500**：谷歌那边卡住、超过生成预算时，超时异常漏出了各协议路由的错误处理，客户端拿到的是框架兜底的纯文本 `500 Internal Server Error`——SDK 解析不了、不会按超时重试，开了 `FALLBACK_ENABLED` 也不会转第三方兜底（10-26 下午谷歌的 Flash 卡了二十多分钟，线上就是这样）。现在超时统一回 **504**、错误类型 `timeout_error`，用各协议自己的错误体（OpenAI / Gemini 原生 / Responses 为 `{"error": {..., "type": "timeout_error"}}`，Anthropic 为 `{"type": "error", "error": {"type": "timeout_error", ...}}`）；流式请求（含带工具的伪流式）是协议内的错误事件。
  - `/v1/chat/completions` 开了兜底时，超时（还没向客户端发出正文前）先转第三方兜底，兜到了就不报错；另外三个协议没有第三方兜底，直接回上面的错误。
  - 超时不再退回不思考重试，也不再用完整 prompt 重试：这一轮的预算已经花完，再试只会让客户端再等一整轮。
  - 超时不计入账号的连续失败，不会因为谷歌卡顿把账号标成 `expired`；建连阶段的超时照旧先在同一账号上重试几次，重试用完也按超时处理。
  - 生图 `/v1/images/generations` 同样回 504 + `timeout_error`；深度研究接口超时回 504（`{"detail": "..."}`），过去是 500。
- 💬 **多轮对话真正续上同一个会话**：带 `conversation_id` 的多轮对话，续接元数据过去被存成 Python repr 字符串（`"['c_…', 'r_…']"`），也不记是哪个账号服务的，结果**每一轮其实都新开了一个会话、只发了最后一句**——模型能答出上一轮的内容，靠的是网页版「记得之前的聊天」碰巧想起来，对话一长、内容一复杂就会悄悄丢上下文。现在：
  - 续接元数据按 `[cid, rid, rcid]` 存成 JSON；开思考的请求也真正带上续接参数（过去思考请求根本不带）。
  - 会话记下服务它的账号，后续轮次**钉回同一个账号**（网页版的会话属于具体账号，换号接不上）；流式请求自带 `conversation_id` 时同样建会话记录并续接。
  - 账号不可用（过期 / 被删 / 不在访问密钥绑定的账号里 / 池里多账号时正好满载）、记下的元数据用不了（含升级前存下的旧会话）、上一轮由第三方兜底回答或上游没给续接点、新的一轮带着工具结果或不止一条用户消息时，**自动改发完整历史、新开会话**（成功后记下新会话与账号，下一轮照常续接），绝不只发最后一句而悄悄丢掉上下文；用 Gem 模型时以 Gem 绑定的账号为准。
  - 工具 JSON 畸形、重新生成的那一版被采用时，续接点改记它；改发完整历史时带上历史里的附件。
- 钉住的账号（Gem 绑定或多轮续接）到真正发请求时才不可用：OpenAI / Claude / Gemini 原生的非流式请求回 **503** 而不是 500，也不再白退一次不思考；多轮续接则改发完整历史，这一轮的思考档位保持不变。

### Changed

- 深度研究接口（`/gemini/v1beta/deepresearch*`）回给客户端的 `conversation_id` 从 Python repr 字符串改为 JSON 三元组字符串。
- 升级前存下的旧会话没有记账号：升级后第一轮发完整历史、新开会话，之后恢复续接。

## [1.6.44] - 2026-10-26

### Fixed

- 🔄 **浏览器保活插件重新生效**：会话已被谷歌打回登录页的账号，`/admin/status` 过去仍报 `status: "active"`（只把 `is_healthy` 置为 false），而保活插件只认 `expired`，于是一直不去救——线上两个账号因此掉线约 37 小时，插件一次都没推送。现在这类账号对外报 `expired`，`last_error` 写明 `Google session expired (login redirect)`，面板也显示为过期（此前面板不认识 `expired`，显示成灰色英文原词）。插件或面板换 cookie 成功后，账号在池内当场恢复可用，不再依赖随后的检查。账号池内部的调度与自愈逻辑不变。
- 🔁 **服务端不再和浏览器互相顶掉会话**：1.6.41 起服务端定时调用 RotateCookies 更换 PSIDTS；而使用保活插件时，浏览器和服务端共用同一个谷歌会话，两边各自更换，后换的一方拿着被对方换掉的旧值就会 401、被踢下线（「保活时间越来越短、经常要重登」）。现在**由浏览器保活插件推送 cookie 的账号自动改为「浏览器保活」**：服务端不再轮换它，只由浏览器一方更换。
  - 识别方式：插件 1.3.0 带 `X-Gemini2API-Keepalive` 请求头；旧版插件按 `Origin: chrome-extension://` 识别。只在 cookie 换上成功后才记录。
  - 面板手动「更新 Cookie」的账号仍由服务端轮换（cookie 取自无痕窗口的部署需要这样）；不用插件的部署行为不变。
  - 保活方式按谷歌会话（PSID 哈希）记录在 `data/keepalive-modes.json`，重启不丢，不含任何 cookie 值。
- 会话被打回登录页、且谷歌已对同一份 cookie 回过 401 时，服务端不再对它调用 RotateCookies（刷新循环、池自愈、请求内自愈都遵守）；只是 PSIDTS 过期、轮换一次就能救回的会话照常轮换，不会被晾死。
- 仓库自带的 refresher 续期边车推送 cookie 时也带 `X-Gemini2API-Keepalive`，同样按浏览器保活处理；面板「添加账号」也按请求来源记录保活方式，删掉再加回不再继承旧记录。

### Added

- `/admin/status` 每个账号新增 `keepalive_mode`（`browser` / `server`）；面板账号卡片对浏览器保活的账号显示「浏览器保活」标签。
- 配套浏览器插件 **gemini2api-plugin v1.3.0**：浏览器里的 cookie 一变化就主动推给中转站（不再等账号过期）；在 1.6.41～1.6.43 上 `is_healthy` 为 false 的账号也会救；只在确认是本浏览器负责的账号、且过了冷却后才刷新 Gemini 标签页；推送带 `X-Gemini2API-Keepalive` 请求头。建议在插件里绑定本浏览器负责的账号 ID。

## [1.6.43] - 2026-10-21

### Changed

- 🧠 **思考改为 `low` / `medium` / `high` 三档，对齐网页上的低 / 中 / 高**（此前只有「开 / 关」，开就是写死的一档）。
  - **默认档 `low`**：新增设置 `DEFAULT_THINKING_LEVEL` = `off` / `low` / `medium` / `high`（环境变量，或面板「设置 → 思考」，保存即时生效、无需重启）。客户端**没指定档位**时用它。
  - ⚠️ **速度代价**：实测默认 `low` 比不思考平均每个请求多约 5 秒，流式请求的正文要等思考做完才开始出（期间照发保活帧，连接不会被前置代理按空闲超时掐断）。最看重速度就设成 `off`：走不思考旧路径，发给上游的请求与旧版不传参数时逐字节一致。
  - 四个协议的档位参数都接上了：OpenAI `reasoning_effort`、Responses `reasoning.effort`、Anthropic `thinking` + `output_config.effort`、Gemini 原生 `generationConfig.thinkingConfig`（`thinkingLevel` / `thinkingBudget` / `includeThoughts`，此前被静默丢弃）。
  - **协议合规**：客户端完全没提思考、按默认档替它开的思考**只用于生成，绝不回传**——不出 `reasoning_content`、`reasoning` 项、`thinking` 块、`thought` part，响应结构与不思考时逐字段一致；客户端要了思考才回传。
  - **要了思考但没说几档的请求跟随默认档**（此前写死最深的 `high`）：Anthropic `{"type":"adaptive"}`、budget 无效、认不出的 effort、Gemini 未指定档位 / `thinkingBudget: -1` / 只给 `includeThoughts`。**Claude Code 每个请求都带 `adaptive` + `effort: high`**（2.1.296 抓包实测；`high` 是 Claude Code 的出厂值，不换档时每个请求都是它），所以过去 Claude Code 的每个请求都固定跑最深的一档，现在跟随你设的默认档；默认档设成 `off` 时这类请求同样不思考。
  - **Claude Code 的 `/effort` 生效了**：读取 Anthropic `output_config.effort`（此前被丢弃），`/effort low` / `medium` 照档，`xhigh` / `max` → `high`。
  - `reasoning_effort: "none"` → **不思考**（OpenAI 官方语义「不推理」，此前被当成 `low`）；`minimal` → low，`xhigh` → high。
  - 总闸 `EXTENDED_THINKING_ENABLED=false` = 一律不思考（连客户端明确指定档位的也忽略），是真正最快的模式；面板「设置 → 思考」里与默认档并排一直显示。
- 🤖 **对外模型收口为四个**：`gemini-pro` / `gemini-flash` / `gemini-flash-lite` / `gemini-argon`，各自按账号心跳自动映射到网页当前那一代（3.1 Pro / 3.8 Flash / 3.5 Flash-Lite / 4 Argon；`gemini-argon` 在账号上发现到才列出），Google 换代不用改客户端。
  - `gemini-flash-thinking` 这个「flash + 思考」的假模型下线：思考现在是每个模型都有的档位。`gemini-flash-thinking`、`gemini-2.5/2.0-flash-thinking`、`gemini-3-flash-thinking*` 仍可调用（隐藏别名，等同 `gemini-flash`，计价不变），只是不再出现在模型列表里；只勾了它的旧访问密钥仍会列出它。
  - ⚠️ 行为变化：不传档位调用 `gemini-flash-thinking` 时，v1.6.42 会回传思考内容，现在不再回传（没请求的思考一律不回传），想要思考内容请改传档位参数。
- 🧪 面板「模型测试」页的「思考」勾选框换成**档位选择**（低 / 中 / 高，默认低），另有「按默认档（不传参数）」一项，可实测默认档（含 `off`）的真实速度。

### Fixed

- 🔌 **「API 管理」第三方转发修复（书生端砚等）**：转发时把消息里的可选字段（`name` / `tool_calls` / `tool_call_id`）以 `null` 原样发出，按 OpenAI SDK 严格校验的上游（书生端砚的 deepseek / glm / kimi / minimax / qwen）一律 400「Input should be a valid string」，这几个模型经网关**全部不可用**。现在转发前去掉 `null` 字段（非流式、流式、兜底、Responses 转发都走同一处）。
  - 全部 key 都失败时不再固定回最后一个 key 的错误：此前前几个 key 是「参数被拒」、最后一个恰好额度用完，客户端只看到 429「quota exceeded」，**被误导成额度问题**。现在优先回能说明原因的那个（参数被拒 > 上游故障 > 额度 > 鉴权）。
  - 请求本身被拒（400 / 404 / 413 / 422）时，只有同一次请求里别的 key 成功了才把被拒的 key 排到后面，全都被拒就谁也不冷却（此前一个格式不对的请求就能把所有好 key 冷却一遍）；上游 200 空内容按 502 报；网关自己的配置错误（如 base_url 没配）不再盖住真实的上游错误。`/v1/responses` 的第三方转发同样适用。
  - 日志带 key 标签、模型、上游状态码与错误类型（开了 `LOG_BODIES_ENABLED` 才带错误正文，校验类错误会回显用户原文）。
- Anthropic `budget_tokens` 的整数值浮点（`1024.0`）照整数认，与 Gemini 原生同口径。
- ⚡ **真流式的思考路径失败时也会退回不思考重试一次**（此前只有非流式会）：只在还没发出正文时退回，重试期间照发保活帧；顺带修掉 OpenAI 续接会话重试拿到的正文从未发给客户端的旧缺陷。

## [1.6.42] - 2026-10-21

### Added

- 🤖 **接上 4 Argon，并让模型发现变成账号驱动的**。账号心跳本来就会返回真实可用的模型清单，但此前只认代码里写死的表，认不出的**连日志都不打就丢掉** —— 这正是 Argon 一直用不了的原因（v1.6.41 加的日志已经在生产上把它指出来了：`model_id=95a4c0abcba24364 display_name='4 Argon' model_number=8`）。
  - 现在心跳发现的模型可以被自动采纳，Google 换代不必再等改代码发版。
  - **对外的稳定公开名契约不变**：`gemini-pro` / `gemini-flash` / `gemini-flash-thinking` / `gemini-flash-lite` 行为逐字节不变，Argon 以新的公开名 **`gemini-argon`** 并列加入（`gemini-4-argon` 作别名），`/v1/models` 里能列出来。
  - ⚠️ **混合账号池注意**：模型只在「心跳里发现过它的账号」上可路由。若池里有的账号没有 Argon，请求落到那个账号会返回 400（暂不自动换号，下一版处理）。
  - ⚠️ 自动采纳带校验：model id 形态、编号、档位逐项检查，不合格的条目仍然丢弃但**打日志**，避免异常响应把请求路由到意外模型。写死的表保留为兜底（心跳拿不到时照常工作）。
- 💵 **每把访问密钥的 token 用量与美元估算**（只统计、**不限额**）。面板「访问密钥」页新增累计 input/output token 与估算金额，价格表用 `TOKEN_PRICES` 配置（每百万 token 的输入/输出美元价）。
  - ⚠️ **这是估算，不是账单**，两重近似都已在界面标注：①本服务走网页版、**本身不花钱**，这个数字是「若走官方 API 大约要多少钱」的参考值；②token 数是按字符估的，不是真正的分词器。
  - 额度限制仍然只用请求次数（`request_limit`），token 与金额不参与任何拒绝判定。

### Fixed

- 📋 `/v1beta/models` 不再列出写死的三条假模型（其中 `gemini-2.0-flash-exp` 根本调不通），改为与另外三个协议同源。旧名 `gemini-1.5-pro` / `gemini-1.5-flash` 仍可正常请求。
- 📄 **Canvas 正文不再整段丢失**。Gemini 写较长代码/文档时会自动放进 Canvas 面板，正文只留一个 `googleusercontent.com/immersive_entry_chip/N` 占位链接。此前我们既不读真实内容也不剥这个链接，**客户端拿到的答案就是一条打不开的 URL**。现在会还原真实内容；取不到时至少剥掉死链并给出可读说明。
- 🧼 **清理正文里的控制标记**：`<ctrl94>thought…<ctrl95>`（**思考内容泄漏进答案**，现在归入思考通道而不是丢弃）、`code_reference` / `code_stdout` 伪代码围栏、`card_content` 死链。清理带锚定，用户正文里恰好出现这些字样时不会被误删。
- 🧠 **Anthropic 协议补上思考链**。`/v1/messages` 此前既不读 `thinking` 入参也不回 `thinking` 块，Claude Code 发的思考参数被静默丢弃 —— **Anthropic 协议的用户永远锁死在「不思考」**，而 OpenAI 协议用户可以用 `reasoning_effort` 选档，同一个后端两种协议表现相反。现在两边一致。不传 `thinking` 时响应结构逐字节不变。

## [1.6.41] - 2026-10-21

> 两件事：**可分发的访问密钥**，以及对照两个开源同类实现（[gemini-web-to-api](https://github.com/ntthanh2603/gemini-web-to-api)、[gemini-web2api](https://github.com/Sophomoresty/gemini-web2api)）做的一轮稳定性与速度修复。后者治的是 [issue #11](https://github.com/xwteam/gemini2api/issues/11) 那类「跑一阵就死、面板还显示正常」的老毛病。

### Added

- 🔑 **访问密钥（可分发）**：面板新增「访问密钥」页，可签发任意多把 `sk-` 密钥分发给不同的人，每把独立配置：
  - **启用/停用**、**绝对有效期**、**惰性激活**（发出去先不计时，对方首次使用才开始算 N 天）
  - **请求数上限**（用完即停，可一键重置）、**绑定账号**（这把 key 只准用池里指定的账号）、**限定模型**
  - 状态一目了然：有效 / 停用 / 未激活 / 已过期 / 超额；每把 key 各自的用量与最后使用时间
  - 端点 `GET|POST /admin/access-keys`、`PATCH|DELETE /admin/access-keys/{id}`、`POST /admin/access-keys/{id}/reset-usage`
  - ⚠️ **三条边界**：`.env` 的 `API_KEY` 仍然全权有效（一把都不建时行为与旧版完全一致）；**访问密钥只能调业务 API、绝对进不了 `/admin/*`**；每个业务请求都计数，**包括 `GET /v1/models`**（有些客户端每轮对话前会列一次模型，等于消耗 2 次，设上限时留余量）。
- ⚙️ **三个新配置**：`BARD_ERROR_CODES`（Gemini 拒绝块 code→语义对照表，默认空=全部按安全兜底处理）、`GENERATE_TIMEOUTS`（非流式超时按模型族覆盖）、`GENERATE_TIMEOUT_IMAGE`（生图超时，默认 180 秒）。

### Changed

- ⚠️ **`REFRESH_INTERVAL` 默认值 5 → 30 分钟，并加了 10 分钟硬下限**（配得更小会被自动抬到 10 并打日志）。
  原因：cookie 轮换循环此前**只在「启动时拿不到 token」才启动**，正常启动的网关从不轮换 → cookie 过几小时就死（issue #11）。本版改成**启动就跑**，间隔必须相应放宽，否则对 Google 的后台请求量会涨到约 3.5 倍、更容易触发风控。
- 🧠 **思考档位不再一律走最高档**：`reasoning_effort` 的 `low` / `medium` / `high` 现在映射到不同的思考深度（`none`/`minimal` 归 low、`xhigh` 归 high）。此前只要传了任何值就一律按最高档处理 —— 而 Codex、Cursor 这类客户端**默认就带 `low` 或 `minimal`**，等于用户要「快」、我们给最慢。不传时行为与旧版一致。
- ⏱️ **非流式超时按模型族分层**（flash-lite 60s / flash 120s / pro 300s / 生图 180s），**且超时不再重试三遍**。此前是 60 秒硬掐 + 重试放大，用户要等约 183 秒才看到失败；而 Pro 做难题经常 80 秒以上，必然被自己掐断。
  - ⚠️ 运维注意：pro 非流式最长等 300 秒且全程零字节，**会超过常见前置代理的首字节上限**（EdgeOne 免费版 15 秒、不少反代 60 秒）。这类场景建议用流式。

### Fixed

- 🩺 **cookie 轮换循环现在启动就跑**（issue #11 的代码级根因）。此前正常启动的实例永不轮换，而 Google 的 `__Secure-1PSIDTS` 是小时级更换的 —— 账号必然在几小时后整体死掉，只能人工换 cookie。
- 🍪 **「HTTP 200 但没下发新 cookie」不再算失败**。Google 在旧 cookie 仍有效时就是这么返回的。此前记成轮换失败，导致①面板轮换成功率是假数字；②一个重试就能救回的账号被直接判死并进冷却。
- 🔁 **手动改过的 cookie 不再被磁盘缓存覆盖**：只有「配置真的变了」才压过缓存，且面板「更新 Cookie」现在会**回写 `accounts.json`**，改完跨重启生效。此前改 `.env` 重启后会被磁盘上的旧值覆盖，账号依旧是过期的。
- 🚨 **认出 Gemini 在 HTTP 200 正文里返回的拒绝块**。会话过期、限流、上下文超长、人机验证这四类，Google 都是用 **200** 返回的，错误藏在正文里。此前它们被当成「空回复」吞掉 —— **既不标账号不健康，也不触发任何自愈**，于是出现最难受的死法：健康检查一直绿、自愈永远不触发、用户一直收到空回复。现在会转成明确错误并走冷却/换号。
- 🔍 **被丢弃的模型条目现在留日志**（带 model_id / 显示名 / 编号）。账号心跳本来就会返回真实可用的模型清单，但此前认不出的条目**连日志都不打就丢掉** —— 这正是新模型无法使用的原因。
- 🧹 删掉已失效的 HTML 抓模型正则（它要求「数字·点·数字」，匹配不到当代的模型名，恒为空，还会让健康检查把好账号报成 `models_count=0`）。
- 🌊 **带附件的请求恢复真流式**（四个协议路由全部）。此前带附件一律要等全文生成完才吐第一个字；带工具的仍走 buffered —— 工具调用需要完整 JSON 才能解析。
- 🖼️ **「疑似生图」不再影响流式分流**，只用于决定超时。此前靠关键词猜测，误判面很大，一猜中就把真流式掐掉。真流式收尾现在也会无条件剥掉 `googleusercontent` 占位链接（此前只在真拿到图时才剥，图片检索场景会把死链原样发给客户端）。
- 🔐 `/admin` 不再对「看起来像静态资源」的路径免鉴权。
- 🗂️ 对话上下文按访问密钥隔离；访问密钥落盘失败不再假成功，后台 flush 不再覆盖管理员的增删改。

## [1.6.40] - 2026-09-12

> 来自 [issue #11](https://github.com/xwteam/gemini2api/issues/11) 追加反馈的排查成果。报告人贴出的面板截图显示账号 **ACTIVE / Errors 0 / Models 4**、聊天框却只有一句「无响应内容」——排查后发现**这四个数字没有一个能用**，面板在故障时会掩盖真实原因。本版专治这一点。

### Fixed
- 🔍 **模型测试页不再把真实错误显示成「无响应内容」**：流式响应的 HTTP 状态在第一个字节发出时就定死为 200，之后的失败只能以流内 error 帧表达。后端一直在发（`{"error":{"message","type","code"}}`），但前端只读 `chunk.choices[0].delta`，error 帧没有 `choices` → 取不到内容 → 落到「无响应内容」。
  **于是 `503 会话已失效`、`529 账号池打满`、`500`、`400` 全部长得一模一样**，用户和维护者都无从判断。现在会显示 `网关错误 (503): <真实原因>`；若错误发生在已经输出内容之后，**已收到的内容会保留**，错误追加在后面。错误文本走安全渲染，上游消息不会被当 HTML 执行。
- 🪵 **启动时明说 cookie 轮换循环有没有起来**：`Auto-refresh loop started / NOT started (原因)`。此前无论跑没跑，日志里都看不出来——而它**只在「启动时拿不到 token」或「手动重载 cookie」之后才启动**，正常启动的网关根本不跑它。这一行是排查「cookie 过一阵就失效」类问题的关键线索。

### Added
- 🩺 **账号卡片显示真实健康信息**：新增导出 `is_healthy`、`consecutive_failures`、`last_success_at`、`last_error`(+发生时间)。
  此前面板上的绿色 `ACTIVE` 徽章读的是池里的 `status` 枚举，**不是**客户端的健康位——cookie 已经彻底失效的账号照样显示绿色（`status` 只在连续 3 次计数失败或 401/403 时才变 `EXPIRED`）。现在「状态是 active 但客户端不健康」会给出醒目提示，并显示最近一次成功生成的时间。
  - `last_error` **只保留异常类型 + HTTP 状态码，刻意丢弃原文**：原文里可能嵌着 Google 响应正文的前 200 字节（含登录态标识 / token / 账号邮箱），而模型不可用类异常的消息里带客户端可控的 model 名，原样渲染会变成面板的存储型 XSS 入口。
- 📉 **空响应单独计数，不再被当成成功悄悄咽下去**：上游返回 HTTP 200 但正文解析不出内容时，此前会走 `release(success=True)` —— 错误计数不动、连续失败计数还被清零，账号永远不会因此被标记异常，面板上完全看不出来。现在单独统计连续空响应，面板可见。
  - **单次空响应绝不降级账号**（用户确实可能问出一次空回答），连续 **3** 次才计入错误计数；任何一次非空成功立即清零。
  - 「只有思考过程没有正文」「只有图片没有文字」**不算空**。
  - ⚠️ **这扩展了 `error_count` 的含义**：连续空响应达阈值后每多一次会给它 +1，而该字段同时喂着「用量统计」页的错误率曲线。一个卡在空响应里的账号会把那条曲线顶起来，尽管一次异常都没抛——看历史曲线时请知悉。

### Notes
- 本版**未**改动 PSIDTS 轮换的启动时机（见上面那条日志说明的现状）。让它常驻会增加对 Google 的请求频次与风控面，需要先在真实账号上做长时间验证，故单独评估。

## [1.6.39] - 2026-09-01

### Changed

- ⚠️ **行为变更：面板改过的设置项优先级高于环境变量。** Web 面板「设置」页保存过的项现在会写进
  `data/settings-overrides.json`（`data/` 是 docker-compose 的持久 bind mount），并在每次启动时回放，
  **覆盖**同名环境变量。此前 compose 用 `env_file: .env` 注入的是**真实环境变量**，其优先级高于容器内的
  dotenv 文件，而宿主机 `.env` 根本没挂进容器 —— 面板写的是容器内临时的 `/app/.env`，于是"面板上关掉
  `LOG_BODIES_ENABLED`、提示保存成功、`docker compose restart` 之后又在记录用户完整提示词"。
  该行为对全部 20 个面板可编辑字段生效。
  **升级影响**：若你依赖 `.env` / compose 环境变量来设定这些字段，而该字段曾在面板里被保存过，
  环境变量将不再生效。启动日志会点名被覆盖的字段
  （`Applied N panel setting override(s) from data/settings-overrides.json: ...`）；
  删除 `data/settings-overrides.json` 可把控制权交回环境变量。

### Added

- ⚙️ **`LOG_BODIES_ENABLED` 接入管理面板**：新增「日志」分组，可在面板直接开关请求/响应体记录，无需改配置重启。

### Fixed

- 🧊 **面板静态资源改为每次回源校验**：给面板的 `.js` / `.css` / `.html` / `.json` 加上
  `Cache-Control: no-cache`（仍保留 ETag，命中即 304）。此前 `index.html` 只给 `app.js` 等挂了 `?v=` 版本串，
  而 `import './settings.js'` 这类裸模块说明符带不上查询串，升级后可能拿到"新 settings.js + 旧 i18n.js"
  的半旧状态，界面直接显示 `settings.field.logBodiesEnabled` 这种原始 i18n 键。
  裸地址 `/`（管理员实际收藏的入口）同样纳入 —— 它此前会落到 StaticFiles 挂载而拿不到该响应头，GET 与 HEAD 都已覆盖。
- 🔢 **面板里的小数字段不再被静默截断**：`CHAT_CLEANUP_KEEP_HOURS` / `CHAT_CLEANUP_INTERVAL_HOURS`
  后端声明为 float，但前端一律 `parseInt`，输入 `0.5` 会变成 `0`（`0` 能通过 `>= 0` 校验，于是"保存成功"
  地存成 0，而运行时被 `max(1.0, x)` 兜成 1 小时）。改为按后端字段类型判定 `parseInt` / `parseFloat`。
- 🛡️ **拒绝 NaN / ±Infinity 写入设置**：二者都是合法 Python float 且 `inf < 0` 为假，会绕过全部取值域校验
  被持久化并每次启动回放；`chat_cleanup_interval_hours=inf` 会让清理循环 `asyncio.sleep(inf)` 永不唤醒。
- 💾 **保存设置改为「全有或全无」**：`data/` 或 `.env` 不可写（自定 compose `user:`、rootless podman uid 映射、
  只读卷）时接口返回 500，但改动此前已经落在内存和优先级最高的覆盖文件里 —— 管理员看到"保存失败"，
  **隐私开关其实已经被打开，并且会在下次重启时生效**。现在内存 / `data/settings-overrides.json` / `.env`
  三层中任何一层失败，都会按写入逆序还原全部已完成的步骤（包括删掉本来不存在、刚被创建出来的覆盖文件），
  接口才返回 500。同时 500 的错误详情不再把容器内绝对路径和原子写临时文件名回给浏览器。

## [1.6.38] - 2026-09-01

### Fixed
- 🍪 **修复「同名 Cookie 跨域并存」导致会话获取整体失败（issue #10 追加反馈）**：当 Google 把你重定向到国家域名（`.google.com.hk` / `.com.tw` / `.co.jp` 等）时，`NID` 之类的 Cookie 会同时存在于两个域，而底层 HTTP 库在按名取值时会直接抛 `CookieConflict`。该异常会中断整个 Cookie 更新流程并冒泡到会话令牌获取，日志表现为 `Token extraction failed: Multiple cookies exist with name=NID ...` → 账号被标记为不健康。
  - 现改为逐个 Cookie 对象读取（天然无同名冲突），同名多域时**确定性**优先采用规范域（`*.google.com`）的值；并给整个 Cookie 更新加了兜底，**Cookie 层的问题不再有机会打断会话获取**。
  - 这也是 [issue #11](https://github.com/xwteam/gemini2api/issues/11) 里「跑一阵就卡死」的一个真实触发源；且 v1.6.37 的按需自愈**救不了这一条**（自愈同样要走会话获取，会撞同一个异常），因此本版是该场景的必要补充。
- 🔁 **工具调用 JSON 畸形时自动重新生成一次**：Gemini 网页版没有原生 function calling，工具调用靠提示词模拟，模型偶尔会输出被截断或转义错误的 JSON，此前直接放弃并回复「模型返回的工具调用格式有误」。现在会**自动重新生成一次**再解析（仅一次、仅在声明了工具且判定为畸形时；重试期间流式连接有保活心跳，不会静默断开）。
  - 明确**不做**「截断 JSON 自动补全」——补全等于拿猜出来的参数去执行工具，风险远大于收益。
- 🛡️ 日志记录失败不再截断响应：响应体在任何情况下都完整返回给客户端，记录失败只会丢掉日志字段。

### Added
- 🔍 **可开关的完整请求/响应记录**（`LOG_BODIES_ENABLED`，**默认关**）：开启后可在面板「实时日志」的详情里看到 `/v1/messages` 等接口的完整请求参数与响应内容，便于排查工具调用等问题。
  - **只记 body、不记任何请求头**（Authorization 等凭据不进日志）；**流式响应只记一个标记、绝不缓冲整个流**；单条上限 4KB。
  - **body 只存在于内存中，不写入磁盘**：`data/logs.json` 不会包含用户提示词，重启后不留痕，磁盘占用与开关关闭时一致。

## [1.6.37] - 2026-08-30

### Fixed
- 🩺 **修复账号池永久卡死并误报「All accounts busy」（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）**：当账号的会话失效（Google 轮换 `__Secure-1PSIDTS` 后拿不到 session token）时，账号在池里的状态仍是 `active`（所以面板看着 cookie 正常），但挑选账号时会因「不健康」而跳过它。旧代码判断「是不是只是忙」时**只看状态、不看健康**，于是每个请求都去排队等满 `ACQUIRE_TIMEOUT`（默认 60 秒），最后抛出 `All accounts busy (max_concurrent=8)` → HTTP 529。**这条信息是错的：并发槽位占用其实是 0。**
  - 现在两处判断口径一致；这种情况会**立即**返回准确的 `503 No healthy account (session expired, cookie refresh required)`，不再让人误以为是并发或 cookie 过期问题。
  - 并且会**自动尝试自愈**：检测到「活跃但会话失效」的账号时，池会在**不持锁**的前提下调用一次 cookie 重载来恢复会话（单账号也能自己爬起来）。自愈是单飞的（并发请求只触发一次）、失败后有冷却（不会对上游形成请求潮）、且受本次请求的剩余超时预算约束。
  - 此前这种状态**无法自愈**：池的恢复逻辑只在「完全没有活跃账号」时才跑；客户端自带的自愈代码因为池从不把账号交出去而是死代码。
- 🛑 **客户端断连不再被算作账号失败**：中途断开（例如点「停止」）此前会走失败计数，**连续 3 次就把账号标记为 EXPIRED**——单账号部署点三次停止就会瘫痪。现在断连只归还并发槽位并唤醒排队者，不累加失败计数；真实的上游失败仍照常计数与过期。
- 🔄 **cookie 重载失败不再永久拉黑一个本来健康的账号**：重载会在开始前快照会话状态，失败时完整回滚（不再出现「标记为健康但没有 session token」的中间态）。

### Notes
- 若你的账号池是**健康但真的满载**，行为完全不变：仍然排队等待、仍在有槽位时被唤醒、超时仍返回原来的 `All accounts busy` → 529。
- 本版**未**改动 PSIDTS 自动轮换的启动时机（目前仅在启动失败或手动重载 cookie 后启动）。让它在正常启动时也常驻会显著增加对 Google 的请求频次与风控面，已有的按需自愈已能解决卡死问题，故此项留作单独评估。

## [1.6.36] - 2026-08-28

### Fixed
- 🚨 **OpenAI 流式的上游错误不再伪装成正常回答**：此前失败会以 `content: "Error: ..."` + `finish_reason: "stop"` 发出，官方 SDK 视为一次**成功完成**、不抛异常、无法重试。现改为发出标准的 `data: {"error": {...}}` 帧（openai-python 会据此抛 `APIError`），错误类型沿用统一的 `classify_error`。v1.6.35 只修了 Anthropic 侧，本版补齐 OpenAI 侧。
- 🚦 上游 4xx 的错误类型细化：400/401/403/404 → `invalid_request_error`（此前一律 `api_error`），429 仍为 `rate_limit_error`，5xx 仍为 `api_error`；状态码透传不变。
- 📐 Anthropic 响应的 `citations` 字段在流式与非流式之间保持一致（此前只有流式帧带）；同时 v1.6.35 去掉的 `id/name/input/source` null 噪音**保持不变**。
- 🛡️ `build_prompt_from_messages` 对非字符串 `content`（dict/数字等）不再抛 `TypeError`（此前一次模型放宽就会变成 500）；既有字符串/数组输入的输出逐字节不变。

### Notes
- 生图意图检测的习语排除表**维持 v1.6.35 的内容**（`draw a line/map/card` 等仍视为习语）。本版曾尝试放宽以提高真实画图请求的召回，但评审实测发现：编程语境里 `"draw a line under this discussion"` 这类句子会让**客户端声明的 tools 被静默丢弃**。两种误判代价不对称——误判为图片会让 agent 循环无声损坏，漏判只是当次不走生图分支且用户可改述——故按"宁可保住工具"的方向回退。

## [1.6.35] - 2026-08-28

### Fixed
- 🛠️ **修复「生图意图误判导致客户端工具被静默丢弃」**（影响全部四个协议）：意图检测此前扫描整个拍平后的 prompt 且无词边界，系统提示词、历史消息、甚至**工具执行结果正文**里出现「image / 绘制」等字样就会命中，进而丢掉客户端声明的 tools、并把请求甩到错误处理更差的分支。现改为**只看最后一轮用户消息**（跳过工具结果/附件块）+ 英文词边界与习语排除（`draw a conclusion` 之类不再误判），真实画图请求（`draw a cat` 等）照常识别。
- 🚨 **上游错误不再伪装成正常回答**：Anthropic 流式路径此前把上游失败渲染成一段助手文本并以 `stop_reason: end_turn` 收尾，客户端既不抛异常也无法重试，错误文本还会被写进对话历史。现改为发出标准的 `event: error` 帧并终止。
- 🚦 **错误状态码映射修正**：`HTTPStatusError` 不是 `RuntimeError` 子类，此前在三个路由里都逃逸成裸 500（还会跳过第三方兜底）。现统一由 `classify_error` 映射：上游 429 → 429 `rate_limit_error`、账号池满/忙 → **529 `overloaded_error` + `Retry-After`**（此前是不可重试的 400）、其它 → 500 / 400。
- 🌊 **补齐两条漏掉的流式保活**：`/v1/responses` 与 native Gemini 的 **buffered 分支**此前没有心跳（v1.6.31 只覆盖了 real-stream 分支）。Codex 恒带 tools 必走前者；后者更是**首字节零输出**，会被网关首字节超时直接掐断。
- 🔌 **原生 Gemini 路由现在接受官方 SDK 的 camelCase 报文**：此前 `systemInstruction` / `generationConfig` / `inlineData` 会被静默丢弃（系统提示词与附件直接消失），`functionCall` / `functionResponse` 也不进 prompt。snake_case 写法保持兼容。
- 🧰 **OpenAI 的 `tool_calls` 不再在拍平时被整体丢弃**，`content: null` 也不再渲染成字面量 `None`；**第三方 Anthropic 转发**补上请求侧格式转换（`role:"tool"` → `tool_result`、`tool_calls` → `tool_use`），工具循环不再第二轮硬失败。
- 📐 **Anthropic 响应结构对齐规范**：不再发送非标准的 assistant `image` 块（官方 SDK 无此类型，会把图片吞掉），生成的图片改为以 Markdown 形式并入文本；内容块不再携带 `id/name/input/source` 等 null 噪音；`usage` 补上 `cache_creation_input_tokens` / `cache_read_input_tokens` / `service_tier`；流式帧补上 `stop_sequence` / `stop_reason` / `citations`；空回答不再产生空内容块或零长度增量。

## [1.6.34] - 2026-08-28

### Fixed
- 🧹 **Anthropic 协议细节与健壮性打磨**（v1.6.33 Claude Code 修复的收尾）：
  - 响应补上 Anthropic 规范的 `stop_sequence` 字段（未命中停止序列时为 `null`），并同步补齐 en / ko / zh-TW 三份 API 文档（此前只有 zh-CN / ja 写了）。
  - 工具调用块的 `name` 显式为 `null` 时不再渲染出 Python 字面量 `None`。
  - 客户端断开时的保活守卫补上异常取回，避免极端时序下 asyncio 打印 "Task exception was never retrieved"。
- 🧪 测试加固：补上工具渲染格式的精确断言、`tool_result` 内容各种退化形态的覆盖、以及 OpenAI buffered 流式断连取消（主路径 + 重试路径）的测试；修正一条恒真的空转断言与一处被不必要放宽的源码守卫。

## [1.6.33] - 2026-08-28

### Fixed
- 🔌 **修复 Claude Code 无法接入（issue #10）**，共三处：
  - `/v1/messages` 的 `system` 现在同时接受**字符串**与 Anthropic 合法的**文本块数组**形态（Claude Code 发的是数组、块上带 `cache_control`），不再返回 422。
  - 会话中的 `tool_use` / `tool_result` 内容块不再被丢弃：此前工具调用与工具结果都拿不到，导致 agent 工具循环从第二轮起就是空的。
  - Anthropic 流式改为标准的 `event:` + `data:` 两行制（此前只发 `data:`，按 `event` 字段分发的官方客户端会解析不到事件）。
- 🌊 Claude 的 buffered 流式路径（带工具/附件时走这条，Claude Code 恒命中）补上 SSE 保活心跳，长响应不再被网关空闲超时掐断；三处保活循环在客户端断开时会取消上游任务并及时归还账号槽位。
- 🛡️ 消息内容块中 `text` 字段为非字符串（如 `null`）时不再 500，改为优雅跳过（四协议共用路径）。

## [1.6.32] - 2026-08-14

### Fixed
- 🧠 **思考内容逐帧流式（修复「答案早于思考」）**：原生 Gemini 是「先生成完整思考、再生成答案」；此前思考只在收尾一次性带出、答案却逐帧流式，导致面板上答案先显示、思考后到。现在思考在生成阶段就作为 `reasoning_content` **逐帧增量流出**（`/v1/chat/completions`），思考先于答案显示、并带打字机效果。收尾仍带完整思考作兜底；不开思考 / 普通对话零回归（responses、native Gemini 等接口不受影响）。

## [1.6.31] - 2026-08-14

### Fixed
- 🌊 **流式连接偶发中断修复**：Gemini 是网页反代，流式响应在等待模型生成整段答案时会有一段无字节的静默期；跨境/网关的空闲超时会在此期间掐断连接（面板表现为「连接中断」误报，与生图无关）。现为全部四条流式接口（`/v1/chat/completions`、`/v1/responses`、`/v1/messages`、native Gemini `streamGenerateContent`）在静默期补发保活心跳（SSE 接口用 `: ping` 注释帧，native Gemini 的 NDJSON 用空行），保持连接不空闲、不再被掐断。心跳是纯附加旁路，不改任何生成/解析逻辑，普通与生图请求零回归。
- 📝 修正「模型测试」面板误导的网络错误文案（原文案会提「图片可能已在后台生成」，对文本请求属误导），改为中性的「连接中断，请重试」。

## [1.6.30] - 2026-08-14

### Added
- 🧠 **模型测试面板「思考」开关**：在「模型测试」页勾选「思考」即可对原生 Gemini 开启扩展思考，模型的思考过程以可折叠的「💭 思考过程」块显示在答案上方。未勾选或无思考内容时与原来完全一致。

## [1.6.29] - 2026-08-14

### Added
- 🧠 **原生 Gemini 扩展思考**：请求带 `reasoning_effort` 即可让 Gemini（pro/flash/flash-lite）开启扩展思考，并把思考过程作为 `reasoning_content`（Responses 为 reasoning 项）返回。默认开启，可在设置里 `extended_thinking_enabled` 一键关闭；仅在请求思考时启用、失败自动退回普通格式，不影响普通聊天。

### Fixed
- 修正 `gemini-flash-lite` 免费档内部模型 ID（付费档不变）。

## [1.6.28] - 2026-07-30

### Added
- 🆕 **新增 `gemini-flash-lite` 模型**：暴露 Gemini 最轻量的 Flash-Lite 档（3.5 Flash-Lite），在 Pro/Flash 被限额时仍有可用模型可选。内部按账号真实可用模型动态映射，沿用固定公开名的抽象。

## [1.6.27] - 2026-07-25

### Changed
- 🎨 **管理面板品牌 Logo 更换**：左上角图标改为自定义品牌 Logo 图片（`static/components/logo.png`），并将其压缩到 128×128（约 16KB，较原图缩小约 97%）以减小体积。
- 🔖 **新增控制台 Favicon**：管理面板与登录页现在使用该 Logo 作为浏览器标签页图标。

## [1.6.26] - 2026-07-07

### Added
- 🔌 **OpenAI Responses API 支持**（`/v1/responses` 或 `/openai/v1/responses`）：让需要新版 Responses 协议的客户端（如 2026 年 2 月起砍掉 Chat Completions 支持的 Codex CLI）能正常接入 gemini2api——支持文本对话、流式输出、工具（函数）调用，Gemini 模型和 API 管理配置的第三方模型均可使用。
- 流式事件严格遵循官方协议顺序，修正了参考实现已知会漏发的两个关键事件：`response.output_text.done` / `response.function_call_arguments.done`。

### Notes
- 不支持服务端多轮状态（`previous_response_id` 会明确返回 400 `invalid_request_error`，而不是悄悄忽略）——因为 Codex CLI 等客户端本身会重发完整对话历史，无需服务端保存状态。
- `tools` 使用 Responses API 的扁平格式（`{"type":"function","name",...}`），与 Chat Completions 的嵌套格式不同。

## [1.6.25] - 2026-06-23

### Added
- 🎚️ **「API 管理」页 Gemini 兜底开关**：一键开/关「Gemini→第三方兜底」，即时生效并持久化（原来只能改 `.env` 且需重启）。开关**只控制兜底**——无论开关状态，你在 API 管理里配置的第三方模型都照常直连调用、照常出现在 `/v1/models`。

## [1.6.24] - 2026-06-22

### Added
- 🧩 **自定义 Gem 支持**：管理面板新增「Gem 管理」页，可列出 / 新建 / 修改 / 删除账号下你自己创建的自定义 Gem；支持把任意 Gem「暴露为模型名」——之后任何 OpenAI 兼容客户端只需使用该模型名即可以该 Gem 的人设进行对话。
  - Gem 绑定其所属账号，调用时只走绑定账号、不参与多账号轮询，确保人设一致性。
  - 调用解析：模型名命中 Gem 映射后，请求自动路由至绑定账号并携带对应 Gem 配置发起会话。
  - 删除 Gem 时自动清理对应的模型名映射，无需手动维护。

## [1.6.23] - 2026-06-22

### Added
- 🧠 **第三方「每模型思考(reasoning_effort)」设置**:API 管理里可为每条第三方模型配置思考等级（默认不设 / none / low / medium / high / 自定义），转发时按设置自动注入——OpenAI 兼容上游注入 `reasoning_effort`，Anthropic 上游换算成 `thinking`（budget_tokens）并把响应 thinking 映射回 `reasoning_content`。默认不设时零回归;不支持思考的模型留默认即可。

### Fixed
- `reasoning_content` 纳入"空响应"判定:仅返回思考内容（content 暂空）不再被误判为空而触发切换/兜底。

## [1.6.22] - 2026-06-22

### Added
- 🔁 **第三方直连「同名多家」自动故障切换**：当同一模型 ID 在「API 管理」中配置了多家第三方时，直连调用固定优先用第一家，遇报错 / 限流 / 额度耗尽 / 超时 / 空响应即自动切换下一家同名第三方，全部失败才返回最后错误；客户端只用一个模型名、无感。
  - 流式请求在「首字节前」即可无缝换家（已开始下发的流不中途切换）；坏家进入内存冷却（`THIRDPARTY_FAILOVER_COOLDOWN`，默认 180 秒，设 0 关闭），冷却期内优先跳过、到期自动恢复；某模型候选全部冷却或仅一家时仍照常尝试，绝不饿死。
  - 默认生效、无单独开关：仅当配置了同名多家时才有可见行为变化，单家场景零回归。Gemini→第三方兜底链不受影响。新增单元测试覆盖选择/冷却/分发/流式 pre-flight，`.env.example` 同步。

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
