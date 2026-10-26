import math
import string
import secrets
import logging
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import ValidationInfo, field_validator, model_validator

from app.core.settings_overrides import THINKING_DEFAULT_LEVELS, apply_overrides

logger = logging.getLogger(__name__)

APP_VERSION = "1.6.48"


def _generate_api_key() -> str:
    chars = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(32))
    return f"sk-{suffix}"


# 模型级熔断（v1.6.46 规格 C.4）的出厂值。字段名 = Settings 的属性名。
MODEL_BREAKER_DEFAULTS = {
    "model_breaker_enabled": True,
    "model_breaker_threshold": 2,
    "model_breaker_window": 300.0,
    "model_breaker_cooldown": 60.0,
    "model_breaker_max_cooldown": 300.0,
}
# 秒数类（WINDOW / COOLDOWN / MAX_COOLDOWN）的上限。超过一天的窗口 / 开放期没有意义（多半是把毫秒
# 写成了秒）；更要紧的是荒唐但有限的值（1e12）原先照样过校验，熔断一打开，状态里 retry_at 的墙钟 +
# timedelta 越界抛 OverflowError，/admin/status 与 /admin/accounts 整个开放期都 500（面板账号页打不开）。
MODEL_BREAKER_MAX_SECONDS = 86400.0
_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def coerce_model_breaker_value(field: str, value):
    """MODEL_BREAKER_* 的宽容解析 → (值, 是否合法)。解析失败或越界（≤0、阈值不是正整数、秒数超过
    MODEL_BREAKER_MAX_SECONDS）一律 (出厂值, False)。

    启动时的校验器（会打 WARNING）和熔断器每次调用现读 settings（运行时覆盖 / 测试 monkeypatch
    塞进来的值不经过校验器）共用这一份口径：一个手写错的 .env 值绝不能让服务起不来，也不能让熔断器
    拿着 0 秒的开放期或 0 的阈值乱跳。
    """
    default = MODEL_BREAKER_DEFAULTS[field]
    if field == "model_breaker_enabled":
        if isinstance(value, bool):
            return value, True
        raw = str(value if value is not None else "").strip().lower()
        if raw in _TRUE_WORDS:
            return True, True
        if raw in _FALSE_WORDS:
            return False, True
        return default, False
    if isinstance(value, bool):
        return default, False
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default, False
    if not math.isfinite(number) or number <= 0:
        return default, False
    if field == "model_breaker_threshold":
        if not number.is_integer():
            return default, False
        return int(number), True
    if number > MODEL_BREAKER_MAX_SECONDS:
        return default, False
    return number, True


def mask_secret(value: str) -> str:
    """对密钥/凭据做日志/响应安全掩码，仅保留首尾少量字符。空值返回空串。"""
    if not value:
        return ""
    v = str(value)
    if len(v) <= 8:
        return "****"
    return f"{v[:4]}****{v[-4:]}"


class Settings(BaseSettings):
    gemini_psid: str = ""
    gemini_psidts: str = ""
    api_key: str = ""
    # Cookie（PSIDTS）轮换循环的间隔（分钟）。这个循环现在启动就常驻，每一轮是 5 个上游
    # 请求，所以默认值直接决定后台自动化流量的规模；参考实现默认 1440 分钟、下限 10 分钟。
    # PSIDTS 是小时级轮换，30 分钟一轮仍有一倍余量。实际生效值还会被
    # gemini_client.MIN_REFRESH_INTERVAL_MINUTES 夹一道下限。
    refresh_interval: int = 30
    max_retries: int = 3
    # 遇到 5xx（尤其 Google 数据中心 IP 的 503 "Sorry" 限流）时：
    # - 同账号只快速重试 same_account_5xx_retries 次（应对瞬时抖动），不长退避空耗
    # - 仍失败则换下一个 active 账号重试（failover），单账号无可换则报错
    # - 被 5xx 限流的账号进入 failover_cooldown 秒冷却，期间不优先选它（不标 expired）
    same_account_5xx_retries: int = 1
    failover_cooldown: float = 30.0
    port: int = 5918
    log_level: str = "info"
    rate_limit_enabled: bool = False
    rate_limit_window: int = 60
    rate_limit_max: int = 10
    health_check_enabled: bool = True
    health_check_interval: int = 5
    accounts_file: str = "accounts.json"
    rotation_strategy: str = "round-robin"
    max_concurrent_per_account: int = 8
    # 并发满载时，acquire 排队等待可用槽位的上限（秒）。等不到才报错，
    # 避免 agent 高并发请求直接撞 "No available accounts" 失败。
    acquire_timeout: float = 60.0
    fingerprint_config_path: str = "data/fingerprint.json"
    version_sync_enabled: bool = True
    version_sync_interval: int = 24
    jitter_enabled: bool = True
    usage_stats_enabled: bool = True
    usage_stats_interval: int = 300
    usage_stats_retention_days: int = 30
    model_whitelist: str = ""
    chat_cleanup_enabled: bool = True
    chat_cleanup_keep_hours: float = 24.0
    chat_cleanup_interval_hours: float = 6.0
    chat_cleanup_skip_pinned: bool = True
    # 「允许思考」总闸。true = 允许思考；false = 一律不思考、连客户端明确指定档位的思考也忽略
    # （四个协议都走"不思考"的旧路径，真正最快）。与下面的"默认思考档位"分工不同：默认档
    # off 管不到明确指定了档位的请求（Codex 选 high、budget_tokens、Claude Code /effort max），
    # 那些要靠这个总闸。面板「设置 → 思考」里两个都显示。
    extended_thinking_enabled: bool = True
    # 默认思考档位：客户端**没指定档位**时用哪一档（off / low / medium / high）——没传思考
    # 参数的，和要了思考但没说几档的（Claude Code 出厂的 adaptive + effort high、认不出的值，
    # 见 gemini_client.resolve_thinking）。出厂 low。实测 low 比不思考平均每请求多约 5 秒；
    # 最看重速度就设 off（= 不思考旧路径）。客户端明确指定了档位时按客户端的走。
    # 客户端完全没提思考时，按默认档替它开的思考只用于上游生成，**绝不**回传给客户端。
    default_thinking_level: str = "low"
    # 管理面板/admin 路由的独立访问密钥。默认空 → 回退到 api_key（保持单 key 全功能的原行为，零回归）。
    # 设置非空后，/admin/* 改用该 key 校验，业务 API 仍用 api_key，实现权限分离。
    admin_api_key: str = ""
    # CORS 可配置（默认保持原行为：允许所有来源 + 允许凭据）。多个来源用英文逗号分隔；"*" 表示全部。
    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = True
    # 生图代下载尺寸后缀。默认 =s2048（画质足够且显著减小体积/耗时）；设 =s0 为全分辨率原图。
    image_download_size_suffix: str = "=s2048"
    # 单次图片下载 HTTP 超时（秒），独立于主 session 的 60s 默认值。
    image_download_timeout: float = 25.0
    # Gemini→第三方 兜底链（默认关闭，零回归）。开启后：任意 Gemini 模型（flash/pro/thinking）
    # 请求报错或返回空响应时，自动改用 API Key 池中的第三方模型原生重试，客户端无感、仍只用一个模型名。
    # 选择策略：默认自动取池中所有“适合聊天”的第三方（排除 image/video/audio/embedding 等非聊天模型），
    # 随机轮询、一个失败换下一个。FALLBACK_MODELS 为可选的精确指定（逗号分隔、按序尝试）；留空即自动。
    fallback_enabled: bool = False
    fallback_models: str = ""
    # 第三方直连「同名多家」故障切换的坏家冷却时长（秒）。某第三方报错/额度耗尽/返回空后，
    # 该时长内新请求优先跳过它，到期自动恢复参与。设 0 关闭冷却（每次都从第一家重试）。
    # 该特性默认生效、无单独开关：仅当某 model 配置了同名多家时才有可见行为变化，单家零回归。
    thirdparty_failover_cooldown: float = 180.0
    # 完整请求/响应体记录（面板日志详情视图）。**默认关**：请求体含用户完整提示词，
    # 属隐私 + 体积敏感，只有运维明确需要排障时才开。开启后也只记 body、绝不记任何
    # 请求头（Authorization 等凭据不进日志），且流式响应只记一个标记、绝不缓冲整个流。
    log_bodies_enabled: bool = False
    # Gemini 在 HTTP 200 正文里返回的拒绝块（BardErrorInfo）的 code→语义对照表，
    # 形如 "1152=rate_limit,404=session_expired"。可用分类：rate_limit / session_expired /
    # context_too_long / captcha。**默认空**：这些 code 的语义 Google 没有公开文档，
    # 我们也还没在真机抓到四类的完整样本，所以不内置任何猜测——认不出的 code 一律按
    # unknown 处理（映射成 429：给客户端明确的"稍后再试"，且不冷却/不换号，
    # 避免一个系统性的未知拒绝把整池账号拖进冷却）。抓到样本后往这里配即可生效。
    bard_error_codes: str = ""
    # 谷歌用来代替回答的「失败套话」，用 | 分隔追加（内置的那句始终生效，空条目忽略）。
    # 谷歌侧故障时 Gemini 会秒回 HTTP 200、正文恰好是一句
    # "I seem to be encountering an error. Can I try something else for you?"（北京 2026-10-26
    # 线上实测）。整段正文规范化后**恰好等于**其中一条才算失败（换号 / 兜底），包含、前缀都不算。
    # 运维在别的语言 / 别的措辞上抓到样本时往这里加。见 gemini_client.is_generic_failure_reply。
    gemini_failure_replies: str = ""
    # 对话的生成超时，按模型族分层（秒）。形如 "flash-lite=60,flash=120,pro=300"。
    # 留空=用代码里的默认分层（flash-lite 60 / flash 120 / pro 300 / argon 300）。
    # 非流式按它掐断整个 POST；真流式（v1.6.46 起）按它约束「第一次进展」与「相邻两次进展的间隔」，
    # 谷歌的心跳帧不算进展（见 gemini_client.generate_stream）。
    # 旧配置里的 flash-thinking=... 已无对应模型族（该模型已下线为 gemini-flash 的别名），被忽略、无害。
    # 同一道难题 flash-lite 几秒就回、pro 经常 80 秒以上，全族共用一个 60s 会让越强的模型
    # 越容易被我们自己掐断。认不出的模型族回落到 60s。
    generate_timeouts: str = ""
    # 疑似生图时把上面的预算抬到至少这个值（秒，取大不覆盖）。生图在 pro 上常超过 60s。流式同口径。
    generate_timeout_image: float = 180.0
    # 访问密钥用量的**美元估算**价格表。形如
    # "gemini-pro=2.0/12.0,gemini-flash=0.75/3.75"（公开模型名=输入价/输出价，
    # 单位 USD / 百万 token）。留空=用 app/core/token_pricing.py 的内置默认值。
    # ⚠️ 这只是"同样的内容若走官方 API 大约要多少钱"的参考值：本服务走网页版、本身
    # 不花钱，且 token 数是 estimate_tokens（len//4）估出来的，不是真分词器。
    # 配不到价格的模型在面板上显示 "—"，绝不回落到某个"差不多"的价。
    # **不参与任何限额判定** —— 额度限制只有 request_limit（计次）这一条。
    token_prices: str = ""
    # 模型级熔断（v1.6.46 规格 C）：谷歌某个模型族整体故障时（北京 2026-10-26 gemini-flash 至少两段，
    # 三个账号都中招），带第三方兜底的 /v1/chat/completions 请求不再每次先白等一个预算。
    # 窗口内 THRESHOLD 个**不同请求**在同一族上「疑似故障」地失败（谷歌的失败套话、几乎没收到数据的
    # 生成超时、一次进展都没有的流式超时）→ 打开 COOLDOWN 秒：开了兜底的 chat 请求直接走兜底；到期后
    # 放一个真实请求去试探谷歌，试探失败开放期翻倍（封顶 MAX_COOLDOWN），任何成功都关闭熔断。
    # 没开兜底的请求、其它协议一律照常调谷歌（它们的结果照样更新熔断状态）。进程重启后状态清空。
    # 非法值（解析失败、≤0、阈值 <1、秒数超过一天）回退出厂值并 WARNING；MAX_COOLDOWN 至少等于 COOLDOWN。
    model_breaker_enabled: bool = True
    model_breaker_threshold: int = 2
    model_breaker_window: float = 300.0
    model_breaker_cooldown: float = 60.0
    model_breaker_max_cooldown: float = 300.0

    @field_validator("gemini_psid")
    @classmethod
    def psid_clean(cls, v: str) -> str:
        return v.strip().strip('"').strip("'").rstrip(";")

    @field_validator("gemini_psidts")
    @classmethod
    def clean_psidts(cls, v: str) -> str:
        return v.strip().strip('"').strip("'").rstrip(";")

    @field_validator("api_key")
    @classmethod
    def ensure_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return _generate_api_key()
        return v

    @field_validator("default_thinking_level", mode="before")
    @classmethod
    def thinking_level_choice(cls, v) -> str:
        # .env 手写错（大小写、空格、拼错）绝不能让服务起不来：先归一，认不出就回出厂 low。
        raw = str(v if v is not None else "").strip().lower()
        if raw in THINKING_DEFAULT_LEVELS:
            return raw
        logger.warning(
            f"DEFAULT_THINKING_LEVEL={v!r} is not one of {sorted(THINKING_DEFAULT_LEVELS)}; "
            "falling back to 'low'"
        )
        return "low"

    @field_validator("model_breaker_enabled", "model_breaker_threshold", "model_breaker_window",
                     "model_breaker_cooldown", "model_breaker_max_cooldown", mode="before")
    @classmethod
    def model_breaker_value(cls, v, info: ValidationInfo):
        # 仿照 default_thinking_level：先宽容解析，认不出 / 越界就回出厂值，绝不让服务起不来
        # （pydantic 对 bool / int 字段的严格解析遇到 "maybe" / "abc" 会在 Settings() 里直接抛错）。
        value, ok = coerce_model_breaker_value(info.field_name, v)
        if not ok:
            logger.warning(f"{info.field_name.upper()}={v!r} is invalid; falling back to {value!r}")
        return value

    @model_validator(mode="after")
    def model_breaker_max_cooldown_floor(self):
        # 开放期翻倍「封顶」MAX_COOLDOWN：它比 COOLDOWN 还小的话，翻倍反而会把开放期缩短。
        if self.model_breaker_max_cooldown < self.model_breaker_cooldown:
            logger.warning(
                f"MODEL_BREAKER_MAX_COOLDOWN={self.model_breaker_max_cooldown!r} is below "
                f"MODEL_BREAKER_COOLDOWN={self.model_breaker_cooldown!r}; raising it to match"
            )
            self.model_breaker_max_cooldown = self.model_breaker_cooldown
        return self

    @field_validator("port")
    @classmethod
    def port_range(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("PORT must be between 1 and 65535")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# 回放管理面板做过的改动（data/settings-overrides.json），优先级**高于**环境变量。
# 必须紧跟在 Settings() 之后：account_pool 等模块在 import 期就会读 settings 的值，
# 放到 lifespan 里回放就晚了。启动日志由 app/main.py 的 lifespan 打印（那时 logging
# 才配置完），运维排查"改了 .env 为什么不生效"时能一眼看到被覆盖的字段。
APPLIED_OVERRIDES = apply_overrides(settings)


def _persist_api_key():
    # 仅当 API_KEY 未由真实环境变量显式提供（即本次为自动生成）时才落盘，
    # 避免覆盖运维通过 env 注入的固定 key。
    import os
    if os.environ.get("API_KEY", "").strip():
        return

    env_path = Path(".env")
    if not env_path.exists():
        # 无 .env 时此前直接 return，导致自动生成的 key 从不持久化，每次重启都换新 key，
        # 静默失效所有客户端凭据（修复 #33）。这里创建 .env 并写入，使其跨重启存活。
        try:
            env_path.write_text(f"API_KEY={settings.api_key}\n")
            logger.info(
                f"API Key generated and saved to new .env: {mask_secret(settings.api_key)}"
            )
        except Exception as e:
            # 只读文件系统等无法落盘时给出醒目告警，避免运维难以排查的"每次重启换 key"。
            logger.warning(
                f"API Key generated but could NOT be persisted (.env unwritable: {e}); "
                f"它会在重启后重新生成。请显式设置 API_KEY 环境变量。"
            )
        return
    content = env_path.read_text()
    if "API_KEY=" in content:
        for line in content.splitlines():
            if line.startswith("API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return
    if "API_KEY=" in content:
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("API_KEY="):
                new_lines.append(f"API_KEY={settings.api_key}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines) + "\n")
    else:
        content = content.rstrip("\n") + f"\nAPI_KEY={settings.api_key}\n"
        env_path.write_text(content)
    logger.info(f"API Key generated and saved to .env: {mask_secret(settings.api_key)}")


_persist_api_key()
