import re
import json
import time
import uuid
import random
import asyncio
import logging
from enum import Enum
from pathlib import Path
from threading import Lock
from collections import deque
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession, RequestsError

from app.config import settings
from app.core.fingerprint.config import fingerprint_config
from app.core.fingerprint.header_builder import header_builder
from app.core.fingerprint.cookie_jar import PersistentCookieJar
from app.core.fingerprint.jitter import apply_jitter, random_delay_factor
from app.core.usage_metrics import live_metrics
from app.utils.tools import maybe_image_generation_intent

logger = logging.getLogger(__name__)

_IMAGE_DOWNLOAD_TIMEOUT = 25  # 单次 GET 超时（秒），避免 =s0 全分辨率拖垮整条链路
_IMAGE_SIZE_DEFAULT = "=s2048"  # 2048px 边长足够预览，字节/耗时远小于 =s0
_GENERATE_TIMEOUT_DEFAULT = 60  # 认不出模型族时的兜底
_GENERATE_TIMEOUT_IMAGE = 180  # 生图 POST 超时（pro 常 >60s，flash 通常 <60s）
# 非流式 POST 超时按模型族分层：同一道难题 flash-lite 几秒就回，pro / flash-thinking
# 经常 80 秒以上（实测 87s）。过去全族共用 60s，于是"模型越强越容易被我们自己掐断"，
# 而且掐断后还会被通用重试放大成 60→等1s→60→等2s→60，用户等 183 秒才看到失败。
# 两个参考实现都比我们宽：refs/gemini-web-to-api 5 分钟（gemini_service.go:620 +
# openai_controller.go:162），refs/gemini-web2api 180 秒。可用 GENERATE_TIMEOUTS 覆盖。
_GENERATE_TIMEOUT_BY_FAMILY = {
    "flash-lite": 60,
    "flash": 120,
    "flash-thinking": 120,
    "pro": 300,
}

# curl_cffi 0.7.4 只有一个 RequestsError，超时靠 code 区分（CURLE_OPERATION_TIMEDOUT）。
try:  # pragma: no cover - 取决于 curl_cffi 版本
    from curl_cffi.curl import CurlECode as _CurlECode

    _CURL_TIMEDOUT = int(_CurlECode.OPERATION_TIMEDOUT)
except Exception:  # pragma: no cover
    _CURL_TIMEDOUT = 28


def _parse_generate_timeouts(raw: str) -> dict:
    """解析 GENERATE_TIMEOUTS（形如 "pro=300,flash=120"）。写错的条目忽略。"""
    out: dict = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        fam, _, val = item.partition("=")
        try:
            seconds = float(val.strip())
        except ValueError:
            continue
        if seconds > 0:
            out[fam.strip().lower()] = seconds
    return out


def _generate_timeout(resolved_model: str, prompt: str) -> float:
    """这一次非流式 POST 该等多久（秒）。

    先按模型族分层（族认不出时用兜底值），"疑似生图"再单独抬一档（_GENERATE_TIMEOUT_IMAGE）。
    注意生图这一档是**取大**而不是覆盖：生图是整个产品里最慢的操作，让 pro 生一张图
    （180s）比 pro 答一道文字难题（300s）还短，等于把"模型越强给越久"这条分层用反了。
    何况这里的判定输入是拍平后的整段 prompt（含 system 与全部历史），多轮对话里任何一句
    含图像关键词的话都会命中（`maybe_image_generation_intent("想做个图像识别的方案")`
    就是 True）—— 一个关键词猜测只被允许"加时"，绝不允许"减时"。
    """
    info = GEMINI_MODELS.get(resolved_model)
    family = str(info["family"]) if info else ""
    overrides = _parse_generate_timeouts(getattr(settings, "generate_timeouts", "") or "")
    value = overrides.get(family) or _GENERATE_TIMEOUT_BY_FAMILY.get(family)
    timeout = float(value or _GENERATE_TIMEOUT_DEFAULT)
    if maybe_image_generation_intent(prompt):
        image_timeout = float(
            getattr(settings, "generate_timeout_image", None) or _GENERATE_TIMEOUT_IMAGE
        )
        timeout = max(timeout, image_timeout)
    return timeout


# curl 的 code 28 既是"读超时"也是"连接超时"（实测两者都是 28，无法用 code 区分）。
# 只有"耗时已经吃掉整个 POST 预算"才说明我们掐断的是一个还在生成的回答；几秒就回来的
# 28 是建连阶段的瞬断（网络瞬断 / Google 前端某台机器黑洞丢包），原样再发一次大概率就通了。
# 这个比例是"算不算生成期超时"的判据，见 _send_request。
_TIMEOUT_ELAPSED_RATIO = 0.9


def _is_timeout_error(exc: BaseException) -> bool:
    """这次失败是不是一个超时（不区分连接期 / 生成期，见 _TIMEOUT_ELAPSED_RATIO）。"""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return isinstance(exc, RequestsError) and getattr(exc, "code", None) == _CURL_TIMEDOUT


class GenerationTimedOut(TimeoutError):
    """我们自己把一个还在生成的回答掐断了（耗时已接近整个 POST 预算）。

    只有这一类超时才"不重试"：原样再发两遍不会有不同的结果，只会把用户的等待时间
    翻三倍。连接期的超时（同样是 curl code 28，但几秒就回来）仍走通用重试 ——
    过去二者混在一条 `_is_timeout_error` 判断里，于是一次短暂的建连超时既不重试、
    也不是 5xx（account_pool 不换号），用户直接拿到 500 硬失败。
    """

    def __init__(self, budget: float, elapsed: float, cause: BaseException):
        self.budget = budget
        self.elapsed = elapsed
        super().__init__(
            f"Generation timed out after {elapsed:.1f}s (budget {budget:.0f}s): {cause}"
        )


# ---------------------------------------------------------------------------
# PSIDTS 轮换循环的节流
# ---------------------------------------------------------------------------
# 轮换循环从"几乎不执行的旁路"变成了"启动就常驻"（见 initialize() 末尾），于是它的频率
# 第一次成了真实的后台流量：每一轮是 5 个上游请求（RotateCookies 1 个 POST +
# _obtain_session_token 的 3 个 GET + 心跳 1 个 POST）。
# 参考实现的默认是 1440 分钟、并把下限硬夹在 10 分钟，注释原文：
#   "Rotating cookies more often than this looks automated to Google and tends to get the
#    session flagged or blocked."
#   （refs/gemini-web-to-api internal/commons/configs/configs.go:55-58、86-89）
# 我们的默认降到 30 分钟（PSIDTS 是小时级轮换，半小时一轮仍有一倍余量），并在这里夹一道
# 下限 —— 既防运维把它调到秒级把账号打进风控，也防 REFRESH_INTERVAL=0 把循环变成热循环
# （asyncio.sleep(0) 不产生任何延迟，实测 0.25 秒就能打出 6 万多次请求）。
MIN_REFRESH_INTERVAL_MINUTES = 10

# 轮换循环连续多少次取不到 token 才把账号标成不健康。
# 过去是"一次失败就降级"：这条路径以前只在"启动就拿不到 token"的 client 上跑，碰不到健康
# 账号；现在每个账号每隔 refresh_interval 都要走一遍，于是 Google 侧一次 502 / 连接重置 /
# DNS 抖动就能把一个完全正常的账号踢出选号池（_find_available 要求 is_healthy），还触发一次
# 毫无必要的 reload_cookies 自愈，而这一下抖动原本对用户完全不可见。
# 阈值与 _health_check_loop 的 3 次对齐；参考实现更宽松（轮换与验证都失败才算不健康，
# refs/gemini-web-to-api internal/modules/providers/gemini_service.go:403-409）。
REFRESH_UNHEALTHY_STREAK = 3


# ---------------------------------------------------------------------------
# 启动时「配置值 vs 磁盘缓存」的取舍
# ---------------------------------------------------------------------------
# 这两个值长得一样却来源完全不同，必须分得开：
#   - 配置值（.env 的 GEMINI_PSIDTS / accounts.json 的条目）：运维手填，只在人去改它时变；
#   - 磁盘缓存（data/cookies/<hash>.json）：PSIDTS 轮换循环与面板的「更新 cookie」会不停写新值。
# 光比较「配置值 != 缓存值」分不出是哪一边变新了：轮换循环一跑起来，一小时内缓存就必然
# 与配置分叉，于是每次重启都会把轮换/面板换来的**新** PSIDTS 当成「陈旧缓存」丢掉、
# 退回当初 .env 里那份早已被 Google 轮换掉的值 —— 账号重启即死，而日志写的是
# "dropping the stale cache"。
# 所以把「上一次启动时生效的配置值」也存进 jar：只有它与当前配置值不同，才说明是**配置**
# 变了（运维改了 .env / accounts.json），这时才按配置值为准并清缓存。
# 这个条目用一个非 google 域，get_all("google.com") 取不到它，绝不会被发往上游。
_CFG_PSIDTS_SNAPSHOT = "__cfg-1PSIDTS"
_CFG_SNAPSHOT_DOMAIN = "config.local"


# ---------------------------------------------------------------------------
# 思考档位（reasoning_effort → Gemini 的 thinking level 枚举）
# ---------------------------------------------------------------------------
# 映射取自参考实现：refs/gemini-web-to-api internal/modules/providers/gemini_service.go
# 的 ParseThinkingLevel（"" / low → 1、medium → 4、high → 2，并有
# gemini_thinking_test.go:20 的断言兜底），以及 internal/modules/openai/openai_service.go
# 把 none/minimal 夹成 low、xhigh 夹成 high。
# ⚠️ 证据来自对方的测试断言，**我方尚未在真机复验**（受账号状态所限没拿到干净数据）。
# 所以做成常量：真机验证后直接改这里，不用动调用方。
THINKING_LEVEL_LOW = 1
THINKING_LEVEL_MEDIUM = 4
THINKING_LEVEL_HIGH = 2
# 不传 reasoning_effort（以及传了认不出的值）时用的档位 = 改动前写死的那个 2，
# 保证既有行为逐字节不变。
THINKING_LEVEL_DEFAULT = 2

_THINKING_LEVELS = {
    "low": THINKING_LEVEL_LOW,
    "medium": THINKING_LEVEL_MEDIUM,
    "high": THINKING_LEVEL_HIGH,
}
# Codex / Cursor 这类客户端会带 none/minimal/xhigh，夹到合法档位（同参考实现口径）。
_THINKING_ALIASES = {"none": "low", "minimal": "low", "xhigh": "high"}


def parse_thinking_level(effort: str | None) -> int:
    """reasoning_effort → thinking level。空值/认不出的值回默认档，绝不抛错。

    过去 reasoning_effort 被 bool 化（`bool(_eff)`）后一律写死最高档：客户端默认带
    "low" / "minimal" 的请求（Codex、Cursor）全部跑成最慢的档位 —— 用户要"快"，
    我们给最慢。
    """
    raw = (effort or "").strip().lower()
    if not raw:
        return THINKING_LEVEL_DEFAULT
    raw = _THINKING_ALIASES.get(raw, raw)
    return _THINKING_LEVELS.get(raw, THINKING_LEVEL_DEFAULT)


def thinking_level_of(extended_thinking) -> int:
    """从 extended_thinking 参数里取出思考档位。

    这个参数既是开关也是档位，形态有三种：
      False / None → 不走思考路径（调用方的 `if extended_thinking:` 为假）
      True         → 走思考路径、用默认档 THINKING_LEVEL_DEFAULT（改动前的唯一行为）
      1 / 2 / 4    → 走思考路径、并用这个档位

    为什么不另加一个平行的 thinking_level 参数：这个值要穿过 路由 → 账号池 →
    client 整条调用链，而账号池的 generate/generate_stream 对它只是透传。把档位搭在
    已有的参数上，账号池一行都不用改（它的选号/冷却/failover/自愈是另一条红线），
    调用方的真假判断也逐字节不变。
    """
    if extended_thinking is True:
        return THINKING_LEVEL_DEFAULT
    try:
        level = int(extended_thinking)
    except (TypeError, ValueError):
        return THINKING_LEVEL_DEFAULT
    return level or THINKING_LEVEL_DEFAULT


class HTTPStatusError(Exception):
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {text[:200]}")


class RotationResult(Enum):
    """_rotate_cookies() 的三态结果。

    Google 的 RotateCookies 在「现有 __Secure-1PSIDTS 还有效」时会回 HTTP 200 **但不下发
    新 Cookie** —— 这不是失败（参考实现 refs/gemini-web-to-api
    internal/modules/providers/gemini_service.go:461-467 的注释原文：
    "Google returns 200 but omits a new cookie when the existing one is still valid —
    not an error"）。把它算成失败有两个后果：面板上的轮换成功率是假的；reload_cookies()
    里 `if rotated:` 为假就跳过第二次取 token，一个重试就能救回的账号被直接判死并进冷却。

    STILL_VALID 与 RENEWED 都是真值，FAILED 为假值 —— 调用方既有的 `if rotated:` 写法
    语义不变、无需改动。
    """

    FAILED = "failed"
    RENEWED = "renewed"
    STILL_VALID = "still_valid"

    def __bool__(self) -> bool:
        return self is not RotationResult.FAILED


# account_pool.acquire() 抛出的三种"池打满/耗尽"RuntimeError 消息（均为动态拼接，故用子串匹配）。
# 之前的 "retry" in str(e).lower() 判断是死代码：这三条消息都不含 "retry"，导致池打满被误判成
# 400（客户端当成不可重试的请求错误），而不是应该重试的 5xx/529。
_POOL_EXHAUSTED_HINTS = (
    "No more accounts to failover to",
    "No available accounts",
    "All accounts busy",
)

# 池打满时建议客户端等待的秒数（排队时长无法精确预测，给一个保守的固定值）。
POOL_EXHAUSTED_RETRY_AFTER = 30

# acquire() 在「账号 status 还是 ACTIVE、但其 client 会话已失效」时抛出的消息（issue #11）。
# 这**不是**池打满：并发槽位是空的，排队再久也不会好转，只有刷新/更换 Cookie 才能恢复。
# 故映射成 503 api_error 而不是 529 overloaded_error —— 529 的语义是"过载了，等会儿再来"，
# 会让所有客户端不停重试一个永远不会自行恢复的池，还把真实原因（会话过期）藏了起来。
NO_HEALTHY_ACCOUNT_MSG = "No healthy account (session expired, cookie refresh required)"

# 访问密钥绑定了账号，但绑定集合里一个可用账号都没有。fail-closed：绝不悄悄回退到
# 别的账号（那等于绕过绑定）。映射成 503 而不是 529：池里别的账号可能很空闲，
# 让客户端无限重试也等不到绑定账号好转，529 "稍后重试" 的语义是误导。
BOUND_ACCOUNT_UNAVAILABLE_MSG = "Access key bound account(s) unavailable"


def classify_error(exc: Exception) -> tuple[int, str, int | None]:
    """把 generate()/generate_stream() 抛出的异常统一映射成
    (http_status, error_type, retry_after_seconds)。

    error_type 用 Anthropic 风格命名（overloaded_error/rate_limit_error/api_error/
    invalid_request_error）；OpenAI/Gemini 路由各自用自己的错误信封包裹同一个 type 字符串。
    三个协议路由的非流式错误响应，以及 Claude 真流式的 error 帧，全部复用这一个函数，
    避免同一类失败在不同入口给出不一致（甚至互相矛盾）的状态码/类型。
    """
    if isinstance(exc, HTTPStatusError):
        status = exc.status_code
        if status == 429:
            error_type = "rate_limit_error"
        elif 400 <= status < 500:
            # 4xx 都是请求侧的问题（含 400），不该跟 5xx 混用同一个 api_error。
            error_type = "invalid_request_error"
        else:
            error_type = "api_error"
        return status, error_type, None
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        # 先判"会话失效"再判"池打满"：前者槽位是空的，重试不会好转，529 是误导（issue #11）。
        if NO_HEALTHY_ACCOUNT_MSG in msg:
            return 503, "api_error", None
        if BOUND_ACCOUNT_UNAVAILABLE_MSG in msg:
            return 503, "api_error", None
        if any(hint in msg for hint in _POOL_EXHAUSTED_HINTS):
            return 529, "overloaded_error", POOL_EXHAUSTED_RETRY_AFTER
        return 500, "api_error", None
    if isinstance(exc, ValueError):
        return 400, "invalid_request_error", None
    return 500, "api_error", None


# ---------------------------------------------------------------------------
# Google 在 HTTP 200 正文里返回的拒绝块（BardErrorInfo）
# ---------------------------------------------------------------------------
# Gemini 拒绝一个请求时 HTTP 状态码仍然是 200，错误藏在正文的一个嵌套块里，形如
#   [["wrb.fr",null,null,null,null,[13,null,
#     [["type.googleapis.com/assistant.boq.bard.application.BardErrorInfo",[1152]]]]],["di",2461]]
# （实据：refs/gemini-web-to-api internal/modules/providers/gemini_service_test.go:125）
# 这种帧的第 2 格是 null，于是我们的解析器既取不到文本也不报错，整条请求被当成"空响应"：
# 账号不会被标不健康、cookie 自愈永远不触发、健康检查一直绿，而用户一直收到空回复。
#
# 只用 type URL 锚定标记，不用裸的 "BardErrorInfo" 子串：用户问"BardErrorInfo 是什么"
# 时模型回答里就带这个词，裸子串匹配会把一次正常回答判成拒绝（两个参考实现都有这个
# 假阳性，我们不抄）。另外 wrb.fr/er 帧的第 2 格是模型回答的 JSON 字符串，解析时整格跳过。
_BARD_ERROR_TYPE_RE = re.compile(r"type\.googleapis\.com/[\w.]*BardErrorInfo")

BARD_CATEGORY_RATE_LIMIT = "rate_limit"
BARD_CATEGORY_SESSION_EXPIRED = "session_expired"
BARD_CATEGORY_CONTEXT_TOO_LONG = "context_too_long"
BARD_CATEGORY_CAPTCHA = "captcha"
BARD_CATEGORY_UNKNOWN = "unknown"

# category → HTTP 状态码。刻意复用 HTTPStatusError 的既有语义，这样 classify_error 和
# account_pool 的 failover / 冷却 / 自愈 一行都不用改：
#   rate_limit        → 503 与 account_pool 既有口径一致（"5xx（含 Google 503 限流）"）：
#                       冷却该账号 + 换号重试
#   session_expired   → 401 client 自己置 _healthy=False、pool 标 EXPIRED 并换号，
#                       下一次请求走既有的 reload_cookies 自愈
#   captcha           → 403 同上。人机验证只能人工处理，先把账号让出去
#   context_too_long  → 400 请求侧问题，给客户端明确错误，绝不换号重试
#   unknown           → 503 同 rate_limit：走既有的"冷却 + 换号"口径。
#                       这里原本是 429，想的是"既不冷却也不 failover，至少给客户端一个
#                       稍后再试的信号"——但 429 既不在 account_pool._is_retryable 也不是
#                       5xx，于是它走的是 release(success=False) 那条"3 连败即 EXPIRED"的
#                       通道。而 BARD_ERROR_CODES 默认是空的，**默认配置下所有拒绝块都是
#                       unknown**：实测 9 个请求就能把 3 个账号全部标 EXPIRED（基线里同样的
#                       响应被当成"空响应"、走 release(success=True, empty=True) 把
#                       consecutive_failures 清零，账号始终 ACTIVE）。
#                       503 的冷却只是"30 秒内不优先选它"（_find_available 里全冷却也仍可
#                       兜底选），既不累计失败也不标 EXPIRED —— 比把账号踢出轮换轻得多。
_BARD_CATEGORY_STATUS = {
    BARD_CATEGORY_RATE_LIMIT: 503,
    BARD_CATEGORY_SESSION_EXPIRED: 401,
    BARD_CATEGORY_CAPTCHA: 403,
    BARD_CATEGORY_CONTEXT_TOO_LONG: 400,
    BARD_CATEGORY_UNKNOWN: 503,
}

# code→语义的对照表**默认为空**：BardErrorInfo 的 code 语义 Google 没有公开文档，两个
# 参考实现也都只是把 code 原样透出（refs/gemini-web-to-api 的 extractBardError 把四种
# 可能成因一起写进文案；refs/gemini-web2api 直接把 code 拼进消息），我们手上唯一有实据的
# 样本是 [13, 1152]，成因不明。所以这里不内置任何猜测：运维在真机抓到样本后用
# BARD_ERROR_CODES="1152=rate_limit,404=session_expired" 配进来，认不出的 code 一律按
# BARD_CATEGORY_UNKNOWN 的保守口径处理。
_BARD_CATEGORIES = frozenset(_BARD_CATEGORY_STATUS)


def _bard_error_code_map() -> dict[int, str]:
    """解析 BARD_ERROR_CODES（形如 "1152=rate_limit,42=captcha"）。

    配置写错的条目直接忽略（一个拼错的分类名不该把请求变成 500），认得的才生效。
    """
    raw = (getattr(settings, "bard_error_codes", "") or "").strip()
    if not raw:
        return {}
    out: dict[int, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        code_s, _, cat = item.partition("=")
        cat = cat.strip().lower()
        if cat not in _BARD_CATEGORIES:
            logger.warning(f"BARD_ERROR_CODES: 未知分类 {cat!r}，已忽略该条")
            continue
        try:
            out[int(code_s.strip())] = cat
        except ValueError:
            logger.warning(f"BARD_ERROR_CODES: 无法解析 code {code_s!r}，已忽略该条")
    return out


def _bard_category(codes) -> str:
    """按配置表把 code 列表映射成分类；一个都认不出就是 unknown。"""
    mapping = _bard_error_code_map()
    for code in codes:
        cat = mapping.get(code)
        if cat:
            return cat
    return BARD_CATEGORY_UNKNOWN


class GeminiRejectionError(HTTPStatusError):
    """Gemini 在 HTTP 200 正文里返回的拒绝块（BardErrorInfo）。

    故意做成 HTTPStatusError 的子类：既有的 classify_error、account_pool 的
    failover / 冷却 / 自愈全部按 status_code 工作，一行都不用改。
    """

    def __init__(self, codes, category: str = BARD_CATEGORY_UNKNOWN):
        self.codes = tuple(codes)
        self.category = category
        super().__init__(
            _BARD_CATEGORY_STATUS.get(category, _BARD_CATEGORY_STATUS[BARD_CATEGORY_UNKNOWN]),
            f"Gemini rejected the request inside a 200 body "
            f"(BardErrorInfo codes {list(self.codes)}, category={category}); "
            f"usual causes: session expired, rate limit, context too long, or CAPTCHA",
        )


def _bard_walk(node, codes: list) -> bool:
    """递归找拒绝标记，顺手把同一棵子树里的整数收进 codes（与参考实现
    refs/gemini-web-to-api 的 extractBardError 同算法，只是标记换成 type URL 锚定）。"""
    if isinstance(node, list):
        found = False
        for child in node:
            if _bard_walk(child, codes):
                found = True
        return found
    if isinstance(node, str):
        return bool(_BARD_ERROR_TYPE_RE.search(node))
    if isinstance(node, bool):
        return False  # JSON 的 true/false 不是 code
    if isinstance(node, int):
        codes.append(node)
    elif isinstance(node, float):
        codes.append(int(node))
    return False


def _extract_bard_error(elem) -> "GeminiRejectionError | None":
    """从一个顶层响应元素里识别拒绝块；识别到就返回已经造好的异常，否则 None。"""
    if not isinstance(elem, list):
        return None
    framed = bool(elem) and elem[0] in ("wrb.fr", "er")
    for idx, child in enumerate(elem):
        # 第 2 格是模型回答的 JSON 字符串（可能本身就在谈 BardErrorInfo），整格跳过；
        # 真正的错误块在第 5 格。
        if framed and idx == 2:
            continue
        codes: list = []
        if _bard_walk(child, codes):
            return GeminiRejectionError(codes, _bard_category(codes))
    return None


GEMINI_APP_URL = "https://gemini.google.com/app"
GEMINI_HOME_URL = "https://gemini.google.com/?hl=en"
GEMINI_APP_EN_URL = "https://gemini.google.com/app?hl=en"
GOOGLE_HOME_URL = "https://www.google.com/"
ROTATE_COOKIES_URL = "https://accounts.google.com/RotateCookies"
GENERATE_URL = (
    "https://gemini.google.com/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)
BATCHEXECUTE_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"

MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"

GEMINI_MODELS = {
    "gemini-3-pro": {"id": "9d8ca3786ebdfbea", "capacity": 1, "pro_only": False, "family": "pro", "model_number": 3},
    "gemini-3-flash": {"id": "fbb127bbb056c959", "capacity": 1, "pro_only": False, "family": "flash", "model_number": 1},
    "gemini-3-flash-thinking": {"id": "5bf011840784117a", "capacity": 1, "pro_only": False, "family": "flash-thinking", "model_number": 1},
    "gemini-3-flash-lite": {"id": "cf41b0e0dd7d53e5", "capacity": 1, "pro_only": False, "family": "flash-lite", "model_number": 6},
    "gemini-3-pro-plus": {"id": "e6fa609c3fa255c0", "capacity": 4, "pro_only": True, "family": "pro", "model_number": 3},
    "gemini-3-flash-plus": {"id": "56fdd199312815e2", "capacity": 4, "pro_only": True, "family": "flash", "model_number": 1},
    "gemini-3-flash-thinking-plus": {"id": "e051ce1aa80aa576", "capacity": 4, "pro_only": True, "family": "flash-thinking", "model_number": 1},
    "gemini-3-flash-lite-plus": {"id": "8c46e95b1a07cecc", "capacity": 4, "pro_only": True, "family": "flash-lite", "model_number": 6},
    "gemini-3-pro-advanced": {"id": "e6fa609c3fa255c0", "capacity": 2, "pro_only": True, "family": "pro", "model_number": 3},
    "gemini-3-flash-advanced": {"id": "56fdd199312815e2", "capacity": 2, "pro_only": True, "family": "flash", "model_number": 1},
    "gemini-3-flash-thinking-advanced": {"id": "e051ce1aa80aa576", "capacity": 2, "pro_only": True, "family": "flash-thinking", "model_number": 1},
    "gemini-3-flash-lite-advanced": {"id": "8c46e95b1a07cecc", "capacity": 2, "pro_only": True, "family": "flash-lite", "model_number": 6},
}

# 对外暴露的稳定模型名（永不变，API 契约）。客户端只认这 4 个，
# 内部按账号当前真实可用的模型动态映射，账号订阅等级/Google 灰度怎么变都不影响 API。
PUBLIC_MODELS = ["gemini-pro", "gemini-flash", "gemini-flash-thinking", "gemini-flash-lite"]
_PUBLIC_FAMILY = {
    "gemini-pro": "pro",
    "gemini-flash": "flash",
    "gemini-flash-thinking": "flash-thinking",
    "gemini-flash-lite": "flash-lite",
}
# 每个 family 的默认内部模型（账号没拉到真实模型时的兜底，按基础版）
_FAMILY_DEFAULT = {
    "pro": "gemini-3-pro",
    "flash": "gemini-3-flash",
    "flash-thinking": "gemini-3-flash-thinking",
    "flash-lite": "gemini-3-flash-lite",
}

MODEL_ALIASES = {
    # 旧版别名 → 公开名（再由公开名按账号动态解析），保留兼容
    "gemini-2.5-pro": "gemini-pro",
    "gemini-2.5-flash": "gemini-flash",
    "gemini-2.5-flash-thinking": "gemini-flash-thinking",
    "gemini-2.5-pro-preview-05-06": "gemini-pro",
    "gemini-2.5-flash-preview-04-17": "gemini-flash",
    "gemini-2.5-flash-preview-05-20": "gemini-flash",
    "gemini-2.0-flash": "gemini-flash",
    "gemini-2.0-flash-thinking": "gemini-flash-thinking",
    "gemini-2.0-flash-lite": "gemini-flash-lite",
    "gemini-1.5-pro": "gemini-pro",
    "gemini-1.5-flash": "gemini-flash",
}

KNOWN_MODELS = list(GEMINI_MODELS.keys())


def _build_id_alias_map() -> dict[str, str]:
    """内部 model_id -> 内部模型名（用于状态接口解析）。"""
    return {info["id"]: name for name, info in GEMINI_MODELS.items()}


def _entry_field(entry: list, idx: int):
    """取心跳模型条目的第 idx 格，越界/类型不对回 None（只用于日志，绝不能自己抛）。

    字段口径取自参考实现 refs/gemini-web-to-api internal/modules/providers/gemini_models.go：
    display_name 在第 11 格（它另有 19/1 两个兜底位），model_number 在第 17 格（兜底第 9 格）。
    第 4 格按本轮任务给的口径一并打出来作线索 —— 参考实现的 capacity 取自账号级
    status[16]/[17]、不是条目级，所以这里只叫 field4，不声称它就是档位。
    """
    try:
        if isinstance(entry, list) and -len(entry) <= idx < len(entry):
            return entry[idx]
    except TypeError:
        pass
    return None


def _entry_display_name(entry: list):
    """心跳模型条目的显示名：第 11 格优先，兜底第 19 / 第 1 格。

    参考实现接受这三个位置（refs/gemini-web-to-api internal/modules/providers/
    gemini_models.go:205 `display := geminiFirstString(fields, 11, 19, 1)`）。只读第 11 格
    的话，Google 把名字放在另外两格的条目会打出 display_name=None —— 日志里除了一串
    不可读的十六进制 id 什么都没有，而"让日志说清楚是哪个模型"正是这条日志的全部价值。
    """
    for idx in (11, 19, 1):
        value = _entry_field(entry, idx)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _entry_model_number(entry: list):
    """心跳模型条目的编号：第 17 格，兜底第 9 格（参考实现 gemini_models.go:217-219 同口径）。"""
    value = _entry_field(entry, 17)
    return value if value is not None else _entry_field(entry, 9)


def _model_number(model_name: str) -> int:
    """Resolved model's PR#310 model-type code (pro=3/flash=1/flash-lite=6); default 1."""
    resolved = _resolve_model(model_name)
    info = GEMINI_MODELS.get(resolved)
    return int(info["model_number"]) if info and "model_number" in info else 1


def _resolve_model(model_name: str, family_model: dict[str, str] | None = None) -> str:
    """把用户请求的模型名解析为账号当前真实可用的内部模型名。
    1. 旧别名 → 公开名
    2. 公开名（gemini-pro/flash/flash-thinking）→ 账号当前该 family 真实可用的内部模型
       （family_model 为账号实例映射，缺省/未命中则用 family 默认）
    3. 已经是内部模型名（gemini-3-*）→ 原样

    family_model: 账号实例的 family→真实模型映射（P0-5：避免模块级全局被多账号污染）。
                  路由层仅做模型名校验时不传，退回 _FAMILY_DEFAULT。
    """
    name = MODEL_ALIASES.get(model_name, model_name)
    if name in _PUBLIC_FAMILY:
        family = _PUBLIC_FAMILY[name]
        fm = family_model or {}
        return fm.get(family) or _FAMILY_DEFAULT[family]
    return name


def _build_model_header(model_name: str) -> dict[str, str]:
    resolved = _resolve_model(model_name)
    model_info = GEMINI_MODELS.get(resolved)
    if not model_info:
        return {}
    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_info["id"]}",null,null,0,[4],null,null,{model_info["capacity"]}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


def _build_model_header_thinking(model_name: str, session_uuid: str,
                                 thinking_level: int | None = None) -> dict[str, str]:
    """PR#310 17-element model header；第 15 位是思考档位（见 parse_thinking_level）。"""
    resolved = _resolve_model(model_name)
    info = GEMINI_MODELS.get(resolved)
    if not info:
        return {}
    mn = int(info.get("model_number", 1))
    arr = [1, None, None, None, info["id"], None, None, 0, [4, 5, 6, 8],
           None, None, info["capacity"], None, None, mn]
    arr.append(int(thinking_level or THINKING_LEVEL_DEFAULT))
    arr.append(session_uuid)
    return {
        MODEL_HEADER_KEY: json.dumps(arr),
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0,0,0]",
    }


MODELS_CACHE_FILE = Path("data/models_cache.json")

# 生图/找图时模型回复文本里会带这种 googleusercontent 占位 URL（无实际意义，
# 真图在 images 字段里；image_retrieval/image_collection 是检索占位，客户端访问无效）。
# 流式与非流式都要过滤掉，避免显示成网址。预编译复用。
_IMAGE_GEN_PLACEHOLDER_RE = re.compile(
    r'https?://googleusercontent\.com/(?:image_generation_content|image_retrieval|image_collection)[/\w]*\d*'
)

# 流式时占位 URL 是逐字符到达的，半截 URL（如 `http://googleusercontent.com/image_gen`、
# 甚至刚到 `http://googleuser`）既不被上面的完整正则匹配，substring 守卫又为真——
# 直接 emit 会把半截网址流给客户端。占位 URL 的完整起始模板（host 段固定）：
_IMAGE_GEN_PLACEHOLDER_PREFIX = "http://googleusercontent.com/"
_IMAGE_GEN_PLACEHOLDER_PREFIX_S = "https://googleusercontent.com/"

# 剥掉占位 URL 之后文本空了、而且一张真图都没有：Gemini 走的是「图片检索」而不是「生成」
# （模糊措辞如"来张X图"易触发）。占位链接客户端用不了，给一句友好提示引导用明确的生图
# 措辞，而不是返回空。流式与非流式共用同一句，两条路径的收尾必须一致。
_IMAGE_RETRIEVAL_HINT = "（没有生成图片。试试更明确的生成指令，如「画一张…」「生成一张…的图片」。）"
_IMAGE_PLACEHOLDER_MARKER = "googleusercontent.com/image"


def _strip_image_placeholders(text: str, images: list) -> str:
    """把文本里的 googleusercontent 占位 URL 剥干净（流式/非流式同一套口径）。

    过去流式收尾只在"真的拿到图"时才做这件事（`if images:` 里面），于是 Gemini 走图片检索
    而非生成（images 为空）时，那条客户端必定访问失败的死链被原样流给客户端 —— 而同一个
    请求走 buffered 是会被 _parse_output 无条件剥掉的。
    """
    if _IMAGE_PLACEHOLDER_MARKER not in text:
        return text
    had_placeholder = bool(_IMAGE_GEN_PLACEHOLDER_RE.search(text))
    cleaned = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text).strip()
    if had_placeholder and not cleaned and not images:
        return _IMAGE_RETRIEVAL_HINT
    return cleaned


def _stable_placeholder_prefix(text: str) -> str:
    """返回 text 中"可安全 emit 的稳定前缀"（已剥离完整占位 URL，并 hold 住尚未成形的占位 URL 尾部）。

    流式逐字符到达时，占位 URL 可能只到一半（甚至只到协议头）。策略：
    1. 先把所有【已完整】的占位 URL 用正则剥掉（与非流式 _parse_output 一致）。
    2. 再扫描剩余文本的尾部：若某个 `http://`/`https://` 起点之后的内容仍是占位 URL 模板
       `http(s)://googleusercontent.com/...` 的真前缀（即还可能补全成占位串），就把从该起点
       起的尾部整段 hold 住不 emit；若已和模板分叉（是别的真实 URL），则正常放行。
       同时处理尾部刚到一半的协议头（如以 `htt`/`http:/` 结尾）。
    这样既不会泄露半截网址，也不会因为后续帧把占位串删掉而破坏 append-only 前缀关系。
    """
    cleaned = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text)
    cut = len(cleaned)
    # 1) 扫描所有 `http` 起点：其后内容若仍是占位模板的前缀（或反过来模板是其前缀），
    #    说明还可能补全成占位 URL，从该起点 hold 住。
    search_from = 0
    while True:
        p = cleaned.find("http", search_from)
        if p == -1:
            break
        tail = cleaned[p:]
        for tmpl in (_IMAGE_GEN_PLACEHOLDER_PREFIX, _IMAGE_GEN_PLACEHOLDER_PREFIX_S):
            if tmpl.startswith(tail) or tail.startswith(tmpl):
                cut = min(cut, p)
                break
        search_from = p + 1
    # 2) 末尾刚到一半的协议头（`h`/`ht`/`htt`，长度 < 4 时上面 find('http') 找不到）：
    #    若结尾是 `http` 的真前缀，也 hold 住，等下一帧确认是不是占位 URL 起点。
    for k in (3, 2, 1):
        if cut == len(cleaned) and cleaned.endswith("http"[:k]):
            cut = len(cleaned) - k
            break
    return cleaned[:cut]


# 流式响应里的顶层帧标记。`er` 是 Google 放错误/状态块的另一个标记，参考实现对
# `wrb.fr` 和 `er` 都收（refs/gemini-web-to-api 的 collectGeminiModelRecords：
# `marker == "wrb.fr" || marker == "er"`）。只扫 wrb.fr 的话，以 `["er",...]` 形态下发的
# 拒绝块（BardErrorInfo）在流式侧永远切不出来，于是又退回 S4 要消灭的那个死法：
# 静默空响应、账号不标不健康、cookie 自愈永不触发。
# 注意这里匹配的是**原始 buffer 里的字面量**：帧的第 2 格是 JSON 字符串，里面的引号是
# 转义的（\"er\"），所以不会误把回答正文里的内容当成一个新帧的开头。
_STREAM_FRAME_MARKERS = ('["wrb.fr"', '["er"')


def _next_frame_start(buf: str, i: int) -> int:
    """从 i 开始找下一个顶层帧的起点；没有就返回 -1。"""
    starts = [pos for pos in (buf.find(m, i) for m in _STREAM_FRAME_MARKERS) if pos != -1]
    return min(starts) if starts else -1


def _scan_complete_wrb_frames(buf: str) -> tuple[list, int]:
    """从流式累积 buffer 中切出所有完整的 `["wrb.fr",...]` / `["er",...]` 顶层元素。

    Gemini StreamGenerate 的响应是 `)]}'\\n\\n` 前缀 + 一个不断增长的 JSON 数组，
    元素形如 `["wrb.fr",null,"<json字符串>",...]` 逐个流式追加（chunk 边界随意切，
    一帧可能跨多个 chunk）。这里用括号深度扫描（正确处理字符串与转义）切出每个
    已闭合的完整元素，返回 (已解析的元素列表, 已消费到的 buffer 偏移量)。
    未闭合的尾部留给下一个 chunk 继续累积。
    """
    frames: list = []
    consumed = 0
    i = 0
    n = len(buf)
    while i < n:
        start = _next_frame_start(buf, i)
        if start == -1:
            break
        # 从 start 开始做括号深度匹配，切出完整的 [...] 元素
        depth = 0
        in_str = False
        esc = False
        end = -1
        j = start
        while j < n:
            c = buf[j]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end == -1:
            # 这个元素还没接收完整，停在这里，下个 chunk 再来
            break
        elem_str = buf[start:end + 1]
        try:
            elem = json.loads(elem_str)
            frames.append(elem)
        except Exception:
            pass
        consumed = end + 1
        i = end + 1
    return frames, consumed


def _extract_text_from_wrb(elem: list) -> tuple[str | None, str, str]:
    """从单个 wrb.fr 帧提取 (累积文本, 会话ID, 思维链)。非文本帧返回 (None, "", "")。
    文本路径 payload[4][0][1][0]；会话ID 用 str(payload[1])，与非流式 _parse_output
    逐字节一致（会话ID 会存进 conversation_store，下轮回传给 _encode_payload 续接会话，
    流式与非流式必须同格式，否则多轮对话续接会错乱）。思维链路径 payload[4][0][37][0][0]
    （extended thinking 开启时才有，与 _parse_output 保持一致）。
    """
    try:
        if not isinstance(elem, list) or len(elem) < 3 or elem[0] != "wrb.fr":
            return None, "", ""
        rp = elem[2]
        if not isinstance(rp, str):
            return None, "", ""
        payload = json.loads(rp)
        if not isinstance(payload, list) or len(payload) < 5:
            return None, "", ""
        conv = str(payload[1]) if payload[1] else ""
        text = None
        cands = payload[4]
        c0 = None
        if isinstance(cands, list) and cands:
            c0 = cands[0]
            if isinstance(c0, list) and len(c0) > 1 and isinstance(c0[1], list) \
                    and c0[1] and isinstance(c0[1][0], str):
                text = c0[1][0]
        thoughts = ""
        if isinstance(c0, list) and len(c0) > 37 and isinstance(c0[37], list) and c0[37] \
                and isinstance(c0[37][0], list) and c0[37][0] and isinstance(c0[37][0][0], str):
            thoughts = c0[37][0][0]
        return text, conv, thoughts
    except Exception:
        return None, "", ""


def _load_models_cache() -> list[str]:
    try:
        if MODELS_CACHE_FILE.exists():
            with open(MODELS_CACHE_FILE, "r") as f:
                data = json.load(f)
            return data.get("models", [])
    except Exception:
        pass
    return []


def _save_models_cache(models: list[str]):
    try:
        MODELS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MODELS_CACHE_FILE, "w") as f:
            json.dump({"models": models, "updated_at": time.time()}, f)
    except Exception:
        pass


# 文件上传需要的 push_id；从 Gemini 页面 body 提取，抓不到用兜底值
_DEFAULT_PUSH_ID = "feeds/mcudyrk2a4khkz"


def _extract_push_id(body: str) -> str:
    """从 Gemini 页面 HTML 里提取 push_id（上传文件用）。
    常见形态为 feeds/<id>。抓不到回退到已知兜底值。
    """
    m = re.search(r'feeds/([a-zA-Z0-9_-]+)', body)
    if m:
        return f"feeds/{m.group(1)}"
    return _DEFAULT_PUSH_ID


def _rand_reqid() -> int:
    """batchexecute 需要的 _reqid 参数。"""
    return random.randint(10000, 99999)



class GeminiWebClient:
    def __init__(self, psid: str | None = None, psidts: str | None = None):
        self._psid = psid or settings.gemini_psid
        self._psidts = psidts or settings.gemini_psidts
        self._session_uuid: str = str(uuid.uuid4()).upper()
        self._session_token: str = ""
        self._push_id: str = ""
        self._available_models: list[str] = []
        self._lock = Lock()
        # 按账号实例存储 family→真实内部模型，避免模块级全局被多账号互相覆盖（P0-5）
        self._family_model: dict[str, str] = {}
        # 自愈单飞锁（asyncio）：并发命中 "not ready" 时只触发一次 reload_cookies（Issue#1-C）。
        # 注意：上面的 self._lock 是 threading.Lock，不支持 async with，故另设异步锁。
        self._heal_lock = asyncio.Lock()
        # 指纹换 session 单飞锁：多协程共享一个 client 并发调 _ensure_session_current 时，
        # 防止指纹轮换瞬间对同一个 _http 双重 close + 互相覆盖新 session 致泄漏（双重检查锁）。
        self._session_lock = asyncio.Lock()
        self._healthy = False
        self._refresh_task: asyncio.Task | None = None
        self._health_check_task: asyncio.Task | None = None
        self._http: AsyncSession | None = None
        self._cookie_jar: PersistentCookieJar | None = None
        self._current_target: str = ""
        self._check_history: deque[dict] = deque(maxlen=20)
        self._last_check_result: dict | None = None
        self._last_reload_error: str = ""
        # 已经警告过的"心跳返回了但不在 GEMINI_MODELS 表里"的 model_id（见 _parse_models_from_status）
        self._dropped_model_ids: set[str] = set()

    async def initialize(self):
        fingerprint_config.load()

        # 构造时传入的值（.env 的 GEMINI_PSID/PSIDTS，或 accounts.json 的条目）就是运维
        # 当前的意图。先留一份：下面要拿它跟"上一次启动时生效的配置值"比，判断是**配置**
        # 变了（该以配置值为准）还是只有缓存被轮换更新了（该用缓存里那个更新的值）。
        cfg_psid, cfg_psidts = self._psid, self._psidts

        self._cookie_jar = PersistentCookieJar(self._psid)
        # cookie_jar 启动时已从磁盘加载持久化 Cookie。
        persisted = self._cookie_jar.get_all()
        disk_psid = persisted.get("__Secure-1PSID")
        disk_psidts = persisted.get("__Secure-1PSIDTS")

        # **配置变了**才以配置值为准并清缓存（参考实现同口径：refs/gemini-web-to-api
        # internal/modules/providers/gemini_service.go Init() 里 "If config has a new PSIDTS
        # that differs from cache, clear cache and use config"）。
        # 过去这里无条件偏向磁盘，于是"照文档改 .env / accounts.json 再重启"——出事时最常用的
        # 恢复手法——完全失效：旧 PSIDTS 会覆盖刚换上的新值，重启后账号依旧是过期的。
        # 但只比较"配置值 != 缓存值"又会反过来每次重启都把轮换/面板换来的新值丢掉（见
        # _CFG_PSIDTS_SNAPSHOT 的说明），所以这里比的是**配置值自己变没变**。
        prev_cfg_psidts = self._cookie_jar.get(_CFG_PSIDTS_SNAPSHOT)
        psid_changed = bool(cfg_psid and disk_psid and disk_psid != cfg_psid)
        if prev_cfg_psidts is None:
            # 这份缓存是本版本之前写下的，没有快照可比 —— 只能沿用旧口径（配置值优先）。
            # 只会发生一次：下面就会把快照写进去，之后就能精确分辨了。而且启动取不到 token
            # 时现在会就地轮换重试一次，不像过去那样要空窗一个刷新周期。
            psidts_changed = bool(cfg_psidts and disk_psidts and disk_psidts != cfg_psidts)
        else:
            psidts_changed = bool(cfg_psidts and cfg_psidts != prev_cfg_psidts)
        if psid_changed or psidts_changed:
            logger.warning(
                "Configured cookies changed since last start; dropping the cache "
                "and using the configured PSID/PSIDTS"
            )
            self._cookie_jar.clear()
            disk_psid = disk_psidts = None

        if disk_psid:
            self._psid = disk_psid
            if disk_psidts:
                self._psidts = disk_psidts
            logger.info("Loaded persisted cookies from disk")
        else:
            self._cookie_jar.set("__Secure-1PSID", self._psid)
            if self._psidts:
                self._cookie_jar.set("__Secure-1PSIDTS", self._psidts)

        # 记下"这一次启动时生效的配置值"，供下一次启动分辨是配置变了还是缓存被轮换更新了。
        if cfg_psidts:
            self._cookie_jar.set(
                _CFG_PSIDTS_SNAPSHOT, cfg_psidts, domain=_CFG_SNAPSHOT_DOMAIN, secure=False
            )
        elif prev_cfg_psidts is not None:
            # 配置里的 PSIDTS 被清空了：快照留着会把"重新填上"误判成没变。
            self._cookie_jar.remove(_CFG_PSIDTS_SNAPSHOT)

        self._current_target = header_builder.get_impersonate_target()
        self._http = AsyncSession(
            impersonate=self._current_target,
            timeout=60,
        )

        await self._obtain_session_token()

        if not self._session_token:
            # 启动就拿不到 token：参考实现在 Init 里当场轮换一次 Cookie 再重取一次
            # （refs/gemini-web-to-api internal/modules/providers/gemini_service.go:147-157）。
            # 我们过去只打这一句日志就把它交给 _auto_refresh_loop —— 而那个循环第一行就是
            # sleep(refresh_interval)，于是整池至少空窗一个刷新周期（期间 acquire() 一个
            # ACTIVE 都找不到，每个请求都是 503），而账号早就被 _init_account_client 标 EXPIRED。
            # 就地重试一次几乎是免费的，且正好能救回"缓存里的会话 Cookie 脏了 / PSIDTS 刚过期"
            # 这类最常见的启动失败。
            logger.warning("Token not found, rotating cookies")
            if await self._rotate_cookies():
                await self._obtain_session_token()

        if self._session_token:
            self._healthy = True
            await self._send_heartbeat()
            logger.info("Gemini client ready")

        # 轮换循环必须**无条件**启动（issue #11 的代码级根因）。Google 的
        # __Secure-1PSIDTS 是小时级轮换的：启动时拿着一份好 cookie，不代表一小时后它还有效。
        # 过去只有"启动就拿不到 token"那条分支才调 _ensure_refresh_task()，
        # 也就是说正常启动的网关从来不跑 _auto_refresh_loop，几小时后整池账号一起失效、
        # 只能人工换 cookie。参考实现在 Init 末尾无条件起这个循环
        # （refs/gemini-web-to-api internal/modules/providers/gemini_service.go:167-170
        #   `if c.autoRefresh { go c.startAutoRefresh() }`）。
        # 日志由 _ensure_refresh_task() 自己打一句 "Auto-refresh loop started"，
        # 两条分支各恰好一句，不重复。
        self._ensure_refresh_task()

        if settings.health_check_enabled:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def models(self) -> list[str]:
        return list(self._available_models)

    @property
    def last_check_result(self) -> dict | None:
        return self._last_check_result

    @property
    def check_history(self) -> list[dict]:
        return list(self._check_history)

    async def _ensure_session_current(self):
        """检查 impersonate 目标是否需要更新（指纹轮换时换 session）。

        并发安全：多协程共享一个 client，指纹轮换瞬间可能同时进入。用单飞锁 +
        双重检查（拿锁后再比一次 target）保证只有一个协程 close+重建，其余协程拿锁后
        看到 target 已更新直接返回，避免对同一 session 双重 close、新 session 互相覆盖泄漏。
        """
        target = header_builder.get_impersonate_target()
        if self._current_target == target:
            return
        async with self._session_lock:
            # 双重检查：可能在等锁期间已被别的协程换好了
            if self._current_target == target:
                return
            logger.info(f"TLS 指纹更新: {self._current_target} -> {target}")
            old = self._http
            self._http = AsyncSession(impersonate=target, timeout=60)
            self._current_target = target
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass

    def _get_cookies(self) -> dict[str, str]:
        return self._cookie_jar.get_all()

    def _get_headers(self, method: str = "GET", content_type: str | None = None) -> dict:
        return dict(header_builder.build(url=GEMINI_APP_URL, method=method, content_type=content_type))

    async def check_account(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self._ensure_session_current()
            self._clear_session_cookies()
            cookies = self._get_cookies()
            headers = self._get_headers("GET")
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            if resp.status_code != 200:
                result = {
                    "valid": False,
                    "has_token": False,
                    "models_count": 0,
                    "checked_at": now,
                    "error": f"HTTP {resp.status_code}",
                }
            else:
                body = resp.text
                token_match = re.search(r'"SNlM0e":"([^"]+)"', body)

                if token_match:
                    self._session_token = token_match.group(1)
                    self._push_id = _extract_push_id(body)
                    self._healthy = True
                    await self._send_heartbeat()  # 拉取账号真实可用模型

                # models_count 只认 RPC 的结果：之前还会拿 HTML 正则抓一遍模型名兜底，
                # 而那条正则要求"数字.数字"（gemini-\d+\.\d+...），匹配不到 gemini-3-pro
                # 这类当代名字，恒为空 —— 兜不住任何东西，只会让人误以为有兜底。
                # 真实可用模型由上面的 _send_heartbeat 调 otAQ7b 状态接口解析。
                result = {
                    "valid": token_match is not None,
                    "has_token": token_match is not None,
                    "models_count": len(self._available_models),
                    "checked_at": now,
                }
        except Exception as e:
            result = {
                "valid": False,
                "has_token": False,
                "models_count": 0,
                "checked_at": now,
                "error": str(e),
            }

        self._last_check_result = result
        self._check_history.append(result)
        return result

    async def _health_check_loop(self):
        interval = settings.health_check_interval * 60
        consecutive_failures = 0
        while True:
            await asyncio.sleep(interval * random_delay_factor())
            try:
                result = await self.check_account()
                if result["valid"]:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"Health check failed ({consecutive_failures}x)")
                    if consecutive_failures >= 3:
                        self._healthy = False
                        logger.error("Account unhealthy: 3 consecutive check failures")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")

    def _clear_session_cookies(self):
        """Clear curl_cffi's internal cookie jar to prevent cross-domain accumulation."""
        try:
            self._http.cookies.clear()
        except Exception:
            pass

    async def _obtain_session_token(self):
        try:
            await self._ensure_session_current()
            cookies = self._get_cookies()
            headers = self._get_headers("GET")

            await apply_jitter("navigation")
            self._clear_session_cookies()
            resp = await self._http.get(GOOGLE_HOME_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            await apply_jitter("navigation")
            self._clear_session_cookies()
            cookies = self._get_cookies()
            resp = await self._http.get(GEMINI_HOME_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            await apply_jitter("navigation")
            self._clear_session_cookies()
            cookies = self._get_cookies()
            resp = await self._http.get(GEMINI_APP_EN_URL, cookies=cookies, headers=headers)
            self._cookie_jar.update_from_response(resp)

            if resp.status_code != 200:
                msg = f"Gemini returned HTTP {resp.status_code}"
                logger.error(msg)
                self._last_reload_error = msg
                self._session_token = ""
                return

            body = resp.text
            token_match = re.search(r'"SNlM0e":"([^"]+)"', body)
            if token_match:
                self._session_token = token_match.group(1)
                self._push_id = _extract_push_id(body)
                logger.info("Session token acquired")
            else:
                self._session_token = ""
                if "accounts.google.com" in body or "ServiceLogin" in body:
                    msg = "Cookie expired - redirected to Google login page"
                elif len(body) < 1000:
                    msg = f"Invalid response (body too short: {len(body)} bytes)"
                else:
                    msg = "SNlM0e token not found (cookie may be invalid or expired)"
                logger.error(msg)
                self._last_reload_error = msg
                return

            # 不再用正则从 HTML 抓模型（会抓到过时/不可用的脏数据）。
            # 真实可用模型由 _send_heartbeat 调 otAQ7b 状态接口解析。
            # 对外始终是固定公开名（API 稳定契约），状态接口只决定内部映射到哪个真实模型。
            if not self._available_models:
                self._available_models = list(PUBLIC_MODELS)
        except Exception as e:
            msg = f"Token extraction failed: {e}"
            logger.error(msg)
            self._last_reload_error = msg
            self._session_token = ""

    async def _rotate_cookies(self) -> RotationResult:
        try:
            await apply_jitter("cookie_rotate")
            await self._ensure_session_current()
            self._clear_session_cookies()
            cookies = self._get_cookies()
            cookie_names = sorted(cookies.keys())
            logger.debug(f"RotateCookies sending {len(cookies)} cookies: {cookie_names}")
            body = '[000,"-0000000000000000000"]'
            resp = await self._http.post(
                ROTATE_COOKIES_URL,
                data=body.encode(),
                cookies=cookies,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://accounts.google.com",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"RotateCookies returned {resp.status_code}")
                live_metrics.record_rotation(False)
                return RotationResult.FAILED

            self._cookie_jar.update_from_response(resp)

            new_ts = resp.cookies.get("__Secure-1PSIDTS")
            if new_ts:
                with self._lock:
                    self._psidts = new_ts
                self._cookie_jar.set("__Secure-1PSIDTS", new_ts)
                logger.info("PSIDTS rotated successfully")
                live_metrics.record_rotation(True)
                return RotationResult.RENEWED

            # 200 但没下发新 PSIDTS = 现有 Cookie 还有效，不是失败（见 RotationResult 的注释）。
            # 刻意既不记成功也不记失败：面板上的轮换成功率应当是"换新 vs 失败"的真实比例，
            # 把"无需更换"算进任何一边都会把那个数字变成装饰品。
            logger.info("RotateCookies 200 without a new PSIDTS; the existing one is still valid")
            return RotationResult.STILL_VALID
        except Exception as e:
            logger.error(f"Rotation failed: {e}")
            live_metrics.record_rotation(False)
            return RotationResult.FAILED

    async def _send_heartbeat(self) -> bool:
        """调 otAQ7b(GetUserStatus) RPC：既保活又拉取账号真实可用模型。
        必须带正确的 URL params 和 x-goog-ext header，否则 Google 返回 400。
        """
        if not self._session_token:
            return False
        try:
            await apply_jitter("api_call")
            await self._ensure_session_current()
            self._clear_session_cookies()

            rpc_id = "otAQ7b"
            # RPCData.serialize 格式：[rpcid, payload, null, "generic"]，外层再包一层 [[...]]
            req_data = json.dumps([[[rpc_id, "[]", None, "generic"]]])
            form_data = {"f.req": req_data, "at": self._session_token}

            params = {
                "rpcids": rpc_id,
                "hl": "en",
                "_reqid": str(_rand_reqid()),
                "rt": "c",
                "source-path": "/app",
            }

            cookies = self._get_cookies()
            headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
            headers.update({
                "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
                "x-goog-ext-73010989-jspb": "[0]",
                "X-Same-Domain": "1",
            })

            resp = await self._http.post(
                BATCHEXECUTE_URL, params=params, data=form_data, cookies=cookies, headers=headers
            )
            self._cookie_jar.update_from_response(resp)

            if resp.status_code == 200:
                logger.debug("Heartbeat OK")
                self._parse_models_from_status(resp.text)
                return True
            else:
                logger.warning(f"Heartbeat returned {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")
            return False

    async def _batchexecute(self, rpc_id: str, payload_str: str) -> str | None:
        """通用 batchexecute 调用，复用心跳的 URL params + headers 模板。
        成功返回响应文本，失败返回 None。payload_str 是已 json.dumps 的内层 payload。
        """
        if not self._session_token:
            return None
        try:
            await apply_jitter("api_call")
            await self._ensure_session_current()
            self._clear_session_cookies()

            req_data = json.dumps([[[rpc_id, payload_str, None, "generic"]]])
            form_data = {"f.req": req_data, "at": self._session_token}
            params = {
                "rpcids": rpc_id,
                "hl": "en",
                "_reqid": str(_rand_reqid()),
                "rt": "c",
                "source-path": "/app",
            }
            cookies = self._get_cookies()
            headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
            headers.update({
                "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
                "x-goog-ext-73010989-jspb": "[0]",
                "X-Same-Domain": "1",
            })
            resp = await self._http.post(
                BATCHEXECUTE_URL, params=params, data=form_data, cookies=cookies, headers=headers
            )
            self._cookie_jar.update_from_response(resp)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"batchexecute {rpc_id} returned {resp.status_code}")
            return None
        except Exception as e:
            logger.warning(f"batchexecute {rpc_id} error: {e}")
            return None

    @staticmethod
    def _parse_wrb_body(raw: str, rpc_id: str):
        """从 batchexecute 响应里取出指定 rpc 的 body（已 json.loads）。找不到返回 None。"""
        if not raw:
            return None
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line.startswith("[["):
                continue
            try:
                outer = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            for item in outer:
                if not (isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr"):
                    continue
                # item[1] 是 rpc id（有时为 None），item[2] 是 body 字符串
                if item[1] not in (rpc_id, None):
                    continue
                body_str = item[2]
                if not isinstance(body_str, str):
                    continue
                try:
                    return json.loads(body_str)
                except (json.JSONDecodeError, ValueError):
                    continue
        return None

    async def list_web_chats(self, recent: int = 300) -> list[dict]:
        """列出账号在 Gemini 网页端的会话（MaZiqc / LIST_CHATS）。
        发两次（[N,None,[1,None,1]] + [N,None,[0,None,1]]）合并去重，
        每项解析 cid=[0] title=[1] pinned=[2] timestamp=[5]([秒,纳秒])。
        返回 [{cid, title, pinned, ts}]，按 ts 降序。失败返回 []。
        """
        rpc_id = "MaZiqc"
        seen: dict[str, dict] = {}
        for flag in (1, 0):
            payload = json.dumps([recent, None, [flag, None, 1]])
            raw = await self._batchexecute(rpc_id, payload)
            body = self._parse_wrb_body(raw, rpc_id)
            if not isinstance(body, list) or len(body) < 3:
                continue
            chat_list = body[2]
            if not isinstance(chat_list, list):
                continue
            for chat in chat_list:
                if not (isinstance(chat, list) and chat and isinstance(chat[0], str)):
                    continue
                cid = chat[0]
                if cid in seen:
                    continue
                title = chat[1] if len(chat) > 1 and isinstance(chat[1], str) else ""
                pinned = bool(chat[2]) if len(chat) > 2 else False
                ts = 0.0
                if len(chat) > 5 and isinstance(chat[5], list) and chat[5]:
                    try:
                        sec = float(chat[5][0])
                        nanos = float(chat[5][1]) if len(chat[5]) > 1 else 0.0
                        ts = sec + nanos / 1e9
                    except (TypeError, ValueError, IndexError):
                        ts = 0.0
                seen[cid] = {"cid": cid, "title": title, "pinned": pinned, "ts": ts}
        return sorted(seen.values(), key=lambda c: c["ts"], reverse=True)

    async def list_gems(self) -> list[dict]:
        """列出账号的自定义 Gem（CNgdBe / LIST_GEMS）。
        payload [2,['en'],0] 专取用户自定义 gem（[3..]/[4..] 是预置 gem，本期不用）。
        响应 body[2] 是 gem 列表；每项 gem[0]=id, gem[1][0]=name, gem[1][1]=desc,
        gem[2][0]=prompt（可能缺省）。失败返回 []。
        """
        rpc_id = "CNgdBe"
        payload = json.dumps([2, ["en"], 0])
        raw = await self._batchexecute(rpc_id, payload)
        body = self._parse_wrb_body(raw, rpc_id)
        if not isinstance(body, list) or len(body) < 3:
            return []
        gem_list = body[2]
        if not isinstance(gem_list, list):
            return []
        out: list[dict] = []
        for gem in gem_list:
            if not (isinstance(gem, list) and gem and isinstance(gem[0], str)):
                continue
            meta = gem[1] if len(gem) > 1 and isinstance(gem[1], list) else []
            name = meta[0] if len(meta) > 0 and isinstance(meta[0], str) else ""
            desc = meta[1] if len(meta) > 1 and isinstance(meta[1], str) else ""
            prompt = ""
            if len(gem) > 2 and isinstance(gem[2], list) and gem[2] and isinstance(gem[2][0], str):
                prompt = gem[2][0]
            out.append({"id": gem[0], "name": name, "description": desc, "prompt": prompt})
        return out

    async def create_gem(self, name: str, prompt: str, description: str = "") -> str | None:
        """新建自定义 Gem（oMH3Zd）。成功返回新 gem id，失败返回 None。"""
        payload = json.dumps([[
            name, description, prompt,
            None, None, None, None, None, 0, None, 1, None, None, None, [],
        ]])
        raw = await self._batchexecute("oMH3Zd", payload)
        body = self._parse_wrb_body(raw, "oMH3Zd")
        if isinstance(body, list) and body and isinstance(body[0], str):
            return body[0]
        return None

    async def update_gem(self, gem_id: str, name: str, prompt: str, description: str = "") -> bool:
        """修改自定义 Gem（kHv0Vd）。返回 200 即视为成功。"""
        if not gem_id:
            return False
        payload = json.dumps([
            gem_id,
            [name, description, prompt,
             None, None, None, None, None, 0, None, 1, None, None, None, [], 0],
        ])
        raw = await self._batchexecute("kHv0Vd", payload)
        return raw is not None

    async def delete_gem(self, gem_id: str) -> bool:
        """删除自定义 Gem（UXcSJb）。返回 200 即视为成功。"""
        if not gem_id:
            return False
        raw = await self._batchexecute("UXcSJb", json.dumps([gem_id]))
        return raw is not None

    async def delete_web_chat(self, cid: str) -> bool:
        """删除一个网页端会话（两步 RPC：GzXR5e -> qWymEb，两步都必须执行）。
        cid 是 c_xxx 形式的会话 id。两步都返回 200 视为成功。
        """
        if not cid or not cid.startswith("c_"):
            logger.warning(f"delete_web_chat: 无效 cid {cid!r}")
            return False
        raw1 = await self._batchexecute("GzXR5e", json.dumps([cid]))
        if raw1 is None:
            return False
        raw2 = await self._batchexecute("qWymEb", json.dumps([cid, [1, None, 0, 1]]))
        if raw2 is None:
            return False
        return True

    async def cleanup_old_web_chats(self, keep_hours: float = 24.0,
                                    skip_pinned: bool = True) -> dict:
        """清理超过 keep_hours 的网页端会话（置顶可选跳过）。
        返回 {listed, deleted, skipped, failed}。

        循环拉取+删除直到没有可删的为止：list_web_chats 单轮有上限（默认300），
        重度账号堆积可能 >上限，最旧的会话排在列表外永远清不到。每轮删完重新拉，
        删空一轮（本轮 deleted=0）或达到安全上限就停。
        keep_hours 下界保护：至少保留 1 小时，防止误传 0/负值清空所有会话。
        """
        keep_hours = max(1.0, keep_hours)
        total_listed = total_deleted = total_skipped = total_failed = 0
        max_rounds = 50  # 安全上限：单账号最多清 50 轮（每轮最多 300），防极端情况死循环
        for _ in range(max_rounds):
            chats = await self.list_web_chats()
            if not chats:
                break
            cutoff = time.time() - keep_hours * 3600
            round_deleted = 0
            round_skipped = 0
            for chat in chats:
                if skip_pinned and chat.get("pinned"):
                    total_skipped += 1
                    round_skipped += 1
                    continue
                ts = chat.get("ts", 0.0)
                # ts<=0 说明时间戳没解析出来，保守跳过不删（避免误删）
                if ts <= 0 or ts >= cutoff:
                    total_skipped += 1
                    round_skipped += 1
                    continue
                ok = await self.delete_web_chat(chat["cid"])
                if ok:
                    total_deleted += 1
                    round_deleted += 1
                else:
                    total_failed += 1
                await asyncio.sleep(0.3)  # 轻微间隔，避免触发限流
            total_listed += len(chats)
            # 本轮没删任何会话（剩下的要么置顶、要么在保留窗口内）→ 没有更多可清的，停止
            if round_deleted == 0:
                break
        logger.info(f"网页会话清理：deleted={total_deleted} skipped={total_skipped} failed={total_failed}")
        return {"listed": total_listed, "deleted": total_deleted,
                "skipped": total_skipped, "failed": total_failed}

    def _parse_models_from_status(self, raw: str):
        """从 otAQ7b（GetUserStatus）响应解析账号真实可用模型。
        响应结构：part_body[15] 是模型数组，每项 [model_id, display_name, description]。
        把账号真实可用的内部模型按 family 记录到本实例 self._family_model，
        供 _resolve_model 把固定公开名映射到该账号真实模型（P0-5：实例隔离，避免全局污染）。
        _available_models 始终是固定的公开名（API 稳定契约），不随账号变化。
        """
        try:
            lines = raw.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line.startswith("[["):
                    continue
                try:
                    outer = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                for item in outer:
                    if not (isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr"):
                        continue
                    body_str = item[2]
                    if not isinstance(body_str, str):
                        continue
                    try:
                        body = json.loads(body_str)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    models_list = body[15] if isinstance(body, list) and len(body) > 15 else None
                    if not isinstance(models_list, list):
                        continue
                    discovered = []
                    for m in models_list:
                        if isinstance(m, list) and m and isinstance(m[0], str):
                            discovered.append(m)
                    # 内部 model_id -> 内部模型名 -> 按 family 记录账号真实可用模型
                    id_to_name = _build_id_alias_map()
                    # 已经警告过的未知 model_id（按 client 实例）。用 __dict__ 懒初始化，
                    # 这样 __new__ 造出来的实例也不会在这里炸。
                    seen_dropped = self.__dict__.setdefault("_dropped_model_ids", set())
                    family_model = {}
                    for entry in discovered:
                        mid = entry[0]
                        name = id_to_name.get(mid)
                        if name and name in GEMINI_MODELS:
                            fam = GEMINI_MODELS[name]["family"]
                            family_model.setdefault(fam, name)
                            continue
                        # 认不出的条目过去是静默 continue：零可观测性。账号心跳明明已经
                        # 返回了某个新模型的 id，只因为不在写死的 GEMINI_MODELS 表里就被
                        # 丢掉，而日志里一个字都没有 —— 排查"某个新模型用不了"时只能靠读源码。
                        # 参考实现对每个被丢掉的条目都有一条带原因的 warn
                        # （refs/gemini-web-to-api internal/modules/providers/gemini_models.go
                        #  的 skip(reason, entry)）。
                        # 按 model_id 在进程内去重：心跳每个刷新周期都跑一轮，而"表里没有
                        # 这个 id"是个稳定事实（S5 要暴露的新模型场景必然每轮命中），
                        # 逐轮重复同一行只会把日志里别的线索冲掉。
                        if mid in seen_dropped:
                            continue
                        seen_dropped.add(mid)
                        logger.warning(
                            "Heartbeat model entry dropped (model id not in GEMINI_MODELS): "
                            f"model_id={mid} display_name={_entry_display_name(entry)!r} "
                            f"model_number={_entry_model_number(entry)!r} "
                            f"field4={_entry_field(entry, 4)!r}"
                        )
                    if family_model:
                        # 账号拉到了 pro/flash，按同 capacity 等级补全 thinking
                        caps = {GEMINI_MODELS[n]["capacity"] for n in family_model.values()}
                        for name, info in GEMINI_MODELS.items():
                            if info["capacity"] in caps:
                                family_model.setdefault(info["family"], name)
                        self._family_model.update(family_model)
                        # 对外永远是固定公开名
                        self._available_models = list(PUBLIC_MODELS)
                        logger.info(f"Account models resolved: {family_model} -> public {PUBLIC_MODELS}")
                        return
        except Exception as e:
            logger.debug(f"Model parse from status skipped: {e}")

    async def _auto_refresh_loop(self):
        # 间隔夹下限：见 MIN_REFRESH_INTERVAL_MINUTES。配 0 / 配 1 分钟都不会把这个循环
        # 变成对 Google 的持续敲门。
        minutes = max(int(settings.refresh_interval or 0), MIN_REFRESH_INTERVAL_MINUTES)
        if minutes != settings.refresh_interval:
            logger.info(
                f"Auto-refresh interval clamped to {minutes} min "
                f"(configured {settings.refresh_interval}, minimum {MIN_REFRESH_INTERVAL_MINUTES})"
            )
        interval = minutes * 60
        consecutive_failures = 0
        token_failures = 0
        while True:
            await asyncio.sleep(interval * random_delay_factor())
            try:
                rotated = await self._rotate_cookies()
                if not rotated:
                    consecutive_failures += 1
                    logger.warning(f"Cookie rotation failed ({consecutive_failures}x)")
                else:
                    consecutive_failures = 0

                # _obtain_session_token() 失败时会把 token 清空（任何异常都被它吞掉），
                # 所以先留一份已知可用的 token：一次抖动不该既降级账号、又把好 token 丢掉
                # （"健康但没有 SNlM0e" 的 client 会被池照常派活、然后每个请求都失败）。
                prev_token = self._session_token
                await self._obtain_session_token()
                if self._session_token:
                    token_failures = 0
                    self._healthy = True
                    await self._send_heartbeat()
                    logger.info("Auto-refresh: token OK")
                else:
                    token_failures += 1
                    if token_failures >= REFRESH_UNHEALTHY_STREAK:
                        self._healthy = False
                        logger.error(
                            f"Auto-refresh: token fetch failed {token_failures}x, client unhealthy"
                        )
                    else:
                        # 还没到阈值：保留上一次拿到的会话，交给真实请求 / 健康检查去裁决。
                        if prev_token:
                            self._session_token = prev_token
                        logger.warning(
                            f"Auto-refresh: token fetch failed ({token_failures}x), "
                            f"keeping the current session until {REFRESH_UNHEALTHY_STREAK}x"
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Refresh loop error: {e}")

    def _encode_payload(self, prompt: str, model: str, conversation_id: str = "",
                        file_ids: list | None = None, gem_id: str | None = None) -> str:
        conv_param = conversation_id if conversation_id else None
        if file_ids:
            # 有附件：第 0 位用带文件的 message_content 替换纯 [prompt]
            file_data = [[[fid], fname] for fid, fname in file_ids]
            message_content = [prompt, 0, None, file_data, None, None, 0]
            inner_list = [message_content, None, conv_param, model]
        else:
            # 纯文本：保持原结构，逐字节不变（防回归）
            inner_list = [[prompt], None, conv_param, model]
        if gem_id:
            # 自定义 gem：内层数组扩展到第 19 格放 gem id（参考库 GEM_FLAG_INDEX=19）
            if len(inner_list) < 20:
                inner_list.extend([None] * (20 - len(inner_list)))
            inner_list[19] = gem_id
        inner = json.dumps(inner_list)
        outer = json.dumps([None, inner])
        return outer

    def _encode_payload_thinking(self, prompt: str, model: str, conversation_id: str = "",
                                 file_ids: list | None = None, gem_id: str | None = None,
                                 thinking_level: int | None = None) -> tuple[str, str]:
        """PR#310 81-element thinking-path payload encoder (isolated from _encode_payload)."""
        DEFAULT_METADATA = ["", "", "", None, None, None, None, None, None, ""]
        if file_ids:
            file_data = [[[fid], fname] for fid, fname in file_ids]
            message_content = [prompt, 0, None, file_data, None, None, 0]
        else:
            message_content = [prompt, 0, None, None, None, None, 0]
        mn = _model_number(model)
        uuid_val = str(uuid.uuid4()).upper()
        inner: list = [None] * 81
        inner[0] = message_content
        inner[1] = ["en"]
        inner[2] = DEFAULT_METADATA          # conversation continuation not used on thinking path (spec §4.3)
        inner[6] = [1]
        inner[7] = 1                          # STREAMING_FLAG_INDEX
        inner[10] = 1
        inner[11] = 0
        inner[17] = [[0]]
        inner[18] = 0
        if gem_id:
            inner[19] = gem_id                # GEM_FLAG_INDEX
        inner[27] = 1
        inner[30] = [4]
        inner[41] = [1]
        inner[53] = 0
        inner[59] = uuid_val
        inner[61] = []
        inner[68] = 1
        inner[79] = mn
        inner[80] = int(thinking_level or THINKING_LEVEL_DEFAULT)   # 思考档位
        outer = json.dumps([None, json.dumps(inner)])
        return outer, uuid_val

    async def generate(self, prompt: str, model: str, conversation_id: str = "",
                       attachments: list | None = None, gem_id: str | None = None,
                       extended_thinking=False) -> dict:
        if not self._healthy:
            # 单账号自愈：抛错前单飞重载一次 Cookie，缓解会话约 2h 到期后的硬失败（Issue#1-C）
            async with self._heal_lock:
                if not self._healthy:
                    try:
                        await self.reload_cookies()
                    except Exception as e:
                        logger.warning(f"Self-heal reload_cookies failed: {e}")
            if not self._healthy:
                raise RuntimeError("Client not ready")

        resolved = _resolve_model(model, self._family_model)
        if resolved not in GEMINI_MODELS:
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(PUBLIC_MODELS)}"
            )

        last_err = None
        # 5xx（含 Google 503 限流）同账号只快速重试少量次，不长退避空耗；
        # 仍失败则抛出（带 status_code），由 account_pool 换账号 failover。
        max_5xx = max(0, settings.same_account_5xx_retries)
        for attempt in range(settings.max_retries):
            try:
                return await self._send_request(prompt, model, conversation_id, attachments, gem_id,
                                                 extended_thinking)
            except HTTPStatusError as e:
                last_err = e
                status = e.status_code
                if 400 <= status < 500:
                    if status in (401, 403):
                        self._healthy = False
                    raise
                # 5xx：同账号快速重试上限内短退避；超过则直接抛给 pool 做 failover
                if attempt >= max_5xx:
                    raise
                wait = 0.5 * (attempt + 1)
                logger.warning(f"Attempt {attempt+1}: status {status}, quick retry in {wait}s (then failover)")
                await asyncio.sleep(wait)
            except Exception as e:
                last_err = e
                if isinstance(e, GenerationTimedOut):
                    # 生成期超时：我们自己把一个还在生成的回答掐断了。原样再发两遍不会有
                    # 不同的结果，只会把用户的等待时间翻三倍（60→等1s→60→等2s→60 =
                    # 183 秒才看到失败）。直接抛出去。
                    # 判定由 _send_request 按耗时做（见 _TIMEOUT_ELAPSED_RATIO）：连接期的
                    # 超时同样是 curl code 28，但它该走下面的通用重试。
                    logger.warning(f"Generate timed out, not retrying: {e}")
                    raise
                # 最后一次尝试失败后不再有重试，跳过退避空耗，立即抛错让上层 failover
                if attempt >= settings.max_retries - 1:
                    break
                wait = 2 ** attempt
                logger.warning(f"Attempt {attempt+1}: {e}, wait {wait}s")
                await asyncio.sleep(wait)

        raise RuntimeError(f"Exhausted {settings.max_retries} retries: {last_err}")

    async def generate_stream(self, prompt: str, model: str, conversation_id: str = "",
                              attachments: list | None = None, gem_id: str | None = None,
                              extended_thinking=False):
        """真流式：用独立临时 AsyncSession 流式读 StreamGenerate，逐帧产出文本增量。

        产出事件：
          {"type": "thoughts", "text": <思考增量>}      —— 流式过程中多次（同帧内先于 delta）
          {"type": "delta", "text": <新增文本>}        —— 流式过程中多次
          {"type": "final", "text": <完整文本>,
           "conversation_id": <会话ID>, "images": [...]}  —— 收尾一次

        关键约束（见记忆 gemini2api-project 真流式段）：
        - curl_cffi 0.7.4 并发流式会串号（#612），故每请求用独立 session（不复用 self._http）。
        - 流式 timeout 可能失效（#215），故用 asyncio.wait_for 兜底每个 chunk 的等待。
        - 帧是累积式，逐帧 diff 出增量。生图/附件场景在最后帧统一处理。
        """
        if not self._healthy:
            # 单账号自愈：抛错前单飞重载一次 Cookie（Issue#1-C）
            async with self._heal_lock:
                if not self._healthy:
                    try:
                        await self.reload_cookies()
                    except Exception as e:
                        logger.warning(f"Self-heal reload_cookies failed: {e}")
            if not self._healthy:
                raise RuntimeError("Client not ready")

        resolved = _resolve_model(model, self._family_model)
        if resolved not in GEMINI_MODELS:
            raise ValueError(
                f"Model '{model}' unavailable. Options: {', '.join(PUBLIC_MODELS)}"
            )

        await apply_jitter("api_call")
        await self._ensure_session_current()
        cookies = self._get_cookies()

        # 附件上传仍复用共享 session 的逻辑（与对话同账号同会话），上传完再走流式对话
        file_ids = None
        if attachments:
            from app.core.file_upload import upload_files
            base_headers = self._get_headers("POST")
            file_ids = await upload_files(
                self._http, cookies, base_headers, self._push_id, attachments
            )
            if not file_ids:
                logger.warning("All attachment uploads failed, streaming text-only")

        if extended_thinking:
            level = thinking_level_of(extended_thinking)
            encoded, uuid_val = self._encode_payload_thinking(prompt, resolved, conversation_id, file_ids,
                                                              gem_id, level)
            model_headers = _build_model_header_thinking(resolved, self._session_uuid, level)
        else:
            encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids, gem_id)
            model_headers = _build_model_header(resolved)
        form_data = {"at": self._session_token, "f.req": encoded}
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
        if model_headers:
            headers.update(model_headers)
        if extended_thinking:
            headers["x-goog-ext-525005358-jspb"] = f'["{uuid_val}",1]'

        buf = ""
        emitted = ""             # 已 yield 出去的完整文本（用于和新帧比前缀算增量）
        last_text = ""           # 最新一帧的完整文本
        last_conv = ""
        last_thoughts = ""       # 累积思维链（最新一帧的完整思考文本，final 兜底用）
        emitted_thoughts = ""    # 已 yield 出去的思维链前缀（逐帧增量用）
        last_images: list = []
        chunk_timeout = 120      # 单个 chunk 最长等待（兜底 #215 timeout 失效）

        session = AsyncSession(impersonate=self._current_target, timeout=180)
        try:
            async with session.stream(
                "POST", GENERATE_URL,
                data=form_data, cookies=cookies, headers=headers,
            ) as resp:
                try:
                    if resp.status_code >= 400:
                        body = await resp.atext()
                        raise HTTPStatusError(resp.status_code, body[:200])

                    aiter = resp.aiter_content()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=chunk_timeout)
                        except StopAsyncIteration:
                            break
                        if not chunk:
                            continue
                        buf += chunk.decode("utf-8", "replace")
                        frames, consumed = _scan_complete_wrb_frames(buf)
                        if consumed:
                            buf = buf[consumed:]
                        for elem in frames:
                            # 流式同样要识别 200 正文里的拒绝块（与非流式同一条识别路径）。
                            # 注意只覆盖 _scan_complete_wrb_frames 能切出的 wrb.fr 帧；
                            # 真·流式下拒绝块总在首帧，正常答案的增量帧也都是 wrb.fr。
                            rejection = _extract_bard_error(elem)
                            if rejection is not None:
                                logger.warning(f"Upstream rejected the stream: {rejection}")
                                raise rejection
                            text, conv, thoughts = _extract_text_from_wrb(elem)
                            if conv:
                                last_conv = conv
                            if thoughts:
                                last_thoughts = thoughts
                            if thoughts and len(thoughts) > len(emitted_thoughts) \
                                    and thoughts.startswith(emitted_thoughts):
                                t_delta = thoughts[len(emitted_thoughts):]
                                emitted_thoughts = thoughts
                                if t_delta:
                                    yield {"type": "thoughts", "text": t_delta}
                            imgs = self._images_from_wrb(elem)
                            if imgs:
                                last_images = imgs
                            if text is None:
                                continue
                            # last_text 始终存原始累积文本，供收尾 _finalize_stream 统一过滤占位串。
                            last_text = text
                            # 计算"可安全 emit 的稳定前缀"：剥掉已完整的占位 URL，并 hold 住任何
                            # 尚未接收完整的占位 URL 尾部（避免泄露半截 googleusercontent 网址）。
                            safe = _stable_placeholder_prefix(text)
                            # 帧是累积式：safe 应是 emitted 的扩展前缀。严格 append-only：
                            # 只在 safe 以 emitted 为前缀时追加新增尾部；非累积帧（思考/重排
                            # 导致 safe 不再以 emitted 为前缀，或占位串补全后变短）则 hold 住，
                            # 不发 _replace（append-only SSE 无法回退），由收尾的 final.text 兜底纠正。
                            if safe == emitted:
                                continue  # 没有新的稳定增量
                            if len(safe) > len(emitted) and safe.startswith(emitted):
                                delta = safe[len(emitted):]
                                emitted = safe
                                if delta:
                                    yield {"type": "delta", "text": delta}
                            # else: 非累积/缩短帧，本帧不 emit，等后续帧或 final 收尾
                finally:
                    # 无论正常结束/4xx/超时，都尝试更新 PSIDTS（流式下 resp 头部 cookie 可读），
                    # 避免流式错误路径漏掉 Cookie 轮换（与非流式 _send_request 行为对齐）
                    try:
                        self._cookie_jar.update_from_response(resp)
                    except Exception:
                        pass
        finally:
            try:
                await session.close()
            except Exception:
                pass

        yield await self._finalize_stream(last_text, last_conv, last_images, last_thoughts)

    def _images_from_wrb(self, elem: list) -> list:
        """从单个 wrb.fr 帧提取 AI 生成图片（复用 _extract_generated_images）。"""
        try:
            if not isinstance(elem, list) or len(elem) < 3 or elem[0] != "wrb.fr":
                return []
            payload = json.loads(elem[2]) if isinstance(elem[2], str) else None
            if not isinstance(payload, list) or len(payload) < 5:
                return []
            cands = payload[4]
            if not isinstance(cands, list) or not cands:
                return []
            return self._extract_generated_images(cands[0])
        except Exception:
            return []

    async def _finalize_stream(self, text: str, conv_id: str, images: list, thoughts: str = "") -> dict:
        """流式收尾：下载/存生成图、过滤占位 URL，组装与 _send_request 一致的 final 结果。
        thoughts 增量已由 generate_stream 循环内逐帧 yield（`{"type": "thoughts"}` 事件）；
        这里的 thoughts 是完整累积思维链，作为收尾兜底一次性带上（防漏发/防中途断连丢失）。
        """
        result_images: list = []
        if images:
            cookies = self._get_cookies()
            for img in images:
                entry = await self._build_image_entry(img, cookies)
                if entry:
                    result_images.append(entry)
            # 真的有图时，正文里的占位 URL 一定无意义（真图在 images 里）
            text = _IMAGE_GEN_PLACEHOLDER_RE.sub("", text).strip()
        else:
            # 没有真图也必须剥：图片检索（而非生成）的回答里只有占位死链，
            # 这正是 _parse_output 无条件做、而这里过去漏掉的那一半。
            text = _strip_image_placeholders(text, images)
        return {
            "type": "final",
            "text": text,
            "conversation_id": conv_id,
            "images": result_images,
            "thoughts": thoughts,
        }

    async def _send_request(self, prompt: str, model: str, conversation_id: str = "",
                           attachments: list | None = None, gem_id: str | None = None,
                           extended_thinking=False) -> dict:
        await apply_jitter("api_call")
        await self._ensure_session_current()
        self._clear_session_cookies()

        resolved = _resolve_model(model, self._family_model)
        cookies = self._get_cookies()

        # 上传附件（与对话同账号同会话），拿到文件标识符
        file_ids = None
        if attachments:
            from app.core.file_upload import upload_files
            base_headers = self._get_headers("POST")
            file_ids = await upload_files(
                self._http, cookies, base_headers, self._push_id, attachments
            )
            if not file_ids:
                logger.warning("All attachment uploads failed, falling back to text-only")

        if extended_thinking:
            level = thinking_level_of(extended_thinking)
            encoded, uuid_val = self._encode_payload_thinking(prompt, resolved, conversation_id, file_ids,
                                                              gem_id, level)
            model_headers = _build_model_header_thinking(resolved, self._session_uuid, level)
        else:
            encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids, gem_id)
            model_headers = _build_model_header(resolved)
        form_data = {"at": self._session_token, "f.req": encoded}
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
        if model_headers:
            headers.update(model_headers)
        if extended_thinking:
            headers["x-goog-ext-525005358-jspb"] = f'["{uuid_val}",1]'

        gen_timeout = _generate_timeout(resolved, prompt)
        started = time.monotonic()
        try:
            resp = await self._http.post(
                GENERATE_URL, data=form_data, cookies=cookies, headers=headers,
                timeout=gen_timeout,
            )
        except Exception as e:
            # curl 的 code 28 既是读超时也是连接超时（实测两者都是 28，无法用 code 区分）。
            # 只有"耗时已经吃掉整个预算"才说明我们掐断的是一个还在生成的回答 —— 那种情况
            # 原样再发两遍只会让用户多等。几秒就回来的 28 是建连阶段的瞬断，照旧交给通用
            # 重试：过去二者混在一起，于是一次短暂的连接超时既不重试、也不是 5xx
            # （account_pool 不换号），用户直接拿到 500 硬失败。
            elapsed = time.monotonic() - started
            if _is_timeout_error(e) and elapsed >= gen_timeout * _TIMEOUT_ELAPSED_RATIO:
                raise GenerationTimedOut(gen_timeout, elapsed, e) from e
            raise
        self._cookie_jar.update_from_response(resp)

        if resp.status_code >= 400:
            raise HTTPStatusError(resp.status_code, resp.text[:200])

        result = self._parse_output(resp.text)

        # AI 生成图片：lh3 URL 客户端直接访问会 403，服务端带 cookie 代下载，
        # 同时存盘（供对话接口返回可渲染 URL）+ 转 base64（供 images/generations 接口）
        if result.get("images"):
            cookies = self._get_cookies()
            downloaded = []
            for img in result["images"]:
                entry = await self._build_image_entry(img, cookies)
                if entry:
                    downloaded.append(entry)
            result["images"] = downloaded

        return result

    async def _build_image_entry(self, img: dict, cookies: dict) -> dict | None:
        """下载生成图、存盘并返回 entry；失败时回退占位提示，不静默丢图。"""
        import base64 as _b64
        from app.core import image_store

        url = img["url"]
        mime = img.get("mime", "image/png")
        data = await self._download_generated_image(url, cookies)
        if not data:
            data = await self._download_generated_image(url, cookies, size_suffix="=s512")
        if data:
            entry = {
                "b64": _b64.b64encode(data).decode(),
                "mime": mime,
                "width": img.get("width"),
                "height": img.get("height"),
            }
            try:
                entry["id"] = image_store.save_image(data, mime)
            except Exception as e:
                logger.warning(f"[imagegen] 存盘失败: {e}")
            return entry
        logger.warning(f"[imagegen] 下载失败，回退占位提示: {url[:60]}")
        return {"mime": mime, "fallback": True, "b64": "", "url": url}

    async def _download_generated_image(
        self, url: str, cookies: dict, size_suffix: str | None = None
    ) -> bytes | None:
        """下载 AI 生成的图片字节（默认 2048px 边长，超时收敛）。
        - lh3 URL 不加尺寸后缀时只给压缩缩略图（如 512px）；加 `=s2048` 平衡画质与耗时。
        - lh3 URL 会多级 302（lh3→fife→lh3），curl_cffi 默认跟随会在跨域时丢 cookie 致 403。
          正确方式：先 allow_redirects=False 拿首个 302 的 location，
          再对该 location 带 cookie allow_redirects=True 跟随到最终 PNG。
        """
        if size_suffix is None:
            size_suffix = getattr(settings, "image_download_size_suffix", None) or _IMAGE_SIZE_DEFAULT
        timeout = getattr(settings, "image_download_timeout", None) or _IMAGE_DOWNLOAD_TIMEOUT
        tail = url.rsplit("/", 1)[-1]
        full_url = url if ("=s" in tail or "=w" in tail) else url + size_suffix
        headers = {"Referer": "https://gemini.google.com/"}
        try:
            r1 = await self._http.get(
                full_url, cookies=cookies, headers=headers,
                allow_redirects=False, timeout=timeout,
            )
            loc = r1.headers.get("location", "")
            if r1.status_code == 200 and r1.headers.get("content-type", "").startswith("image/"):
                return r1.content  # 少数情况直接返回图
            if not loc:
                logger.warning(f"[imagegen] 无重定向且非图片: status={r1.status_code}")
                return None
            r2 = await self._http.get(
                loc, cookies=cookies, headers=headers,
                allow_redirects=True, timeout=timeout,
            )
            if r2.status_code == 200 and r2.headers.get("content-type", "").startswith("image/"):
                return r2.content
            logger.warning(f"[imagegen] 最终下载非图片: status={r2.status_code} type={r2.headers.get('content-type')}")
            return None
        except Exception as e:
            logger.warning(f"[imagegen] 下载异常: {e}")
            return None

    def _parse_output(self, raw: str) -> dict:
        lines = raw.strip().split("\n")
        text_content = ""
        thoughts_content = ""
        conv_id = ""
        images: list[dict] = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith(")]}'"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, list):
                    continue
                # Gemini 拒绝请求时 HTTP 仍是 200、错误藏在正文里（见 _extract_bard_error）。
                # 必须在"取文本"之前识别出来：这种帧没有文本，否则整条请求会被当成空响应。
                rejection = _extract_bard_error(item)
                if rejection is not None:
                    logger.warning(f"Upstream rejected the request: {rejection}")
                    raise rejection
                if len(item) < 3:
                    continue
                raw_payload = item[2]
                if not isinstance(raw_payload, str):
                    continue
                try:
                    payload = json.loads(raw_payload)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(payload, list) or len(payload) < 5:
                    continue

                candidates = payload[4]
                if not isinstance(candidates, list) or not candidates:
                    continue
                candidate = candidates[0]
                if isinstance(candidate, list) and len(candidate) > 1:
                    parts = candidate[1]
                    if isinstance(parts, list) and parts and isinstance(parts[0], str):
                        text_content = parts[0]
                    if len(candidate) > 37 and isinstance(candidate[37], list) and candidate[37] \
                            and isinstance(candidate[37][0], list) and candidate[37][0] \
                            and isinstance(candidate[37][0][0], str):
                        thoughts_content = candidate[37][0][0]
                # AI 生成图片：candidate[12][7][0] 是图片数组（实测确认）
                imgs = self._extract_generated_images(candidate)
                if imgs:
                    images = imgs  # 生图是流式响应，用含图的最新帧
                if payload[1]:
                    conv_id = str(payload[1])

        # 生图/找图时模型文本里会带 googleusercontent 占位 URL（无实际意义，真图在 images 里；
        # image_retrieval/image_collection 是检索占位客户端访问无效），无条件过滤，避免显示成网址。
        # 与真流式收尾（_finalize_stream）共用同一套口径。
        text_content = _strip_image_placeholders(text_content, images)

        return {"text": text_content, "conversation_id": conv_id, "images": images, "thoughts": thoughts_content}

    @staticmethod
    def _extract_generated_images(candidate: list) -> list[dict]:
        """从 candidate[12][7][0] 提取 AI 生成的图片（区别于用户上传的图）。
        实测结构：每张图 img[0][3] = [null,1,文件名,URL,...,"image/png",...,[宽,高,size]]
        返回 [{url, mime, width, height, filename}, ...]；无图返回 []。
        """
        try:
            if not isinstance(candidate, list) or len(candidate) <= 12:
                return []
            c12 = candidate[12]
            if not isinstance(c12, list) or len(c12) <= 7:
                return []
            arr = c12[7]
            if not isinstance(arr, list) or not arr:
                return []
            img_list = arr[0]
            if not isinstance(img_list, list):
                return []
            out = []
            for img in img_list:
                try:
                    meta = img[0][3]  # [null,1,文件名,URL,...,mime,...,[w,h,size]]
                    url = meta[3]
                    if not isinstance(url, str) or not url.startswith("http"):
                        continue
                    filename = meta[2] if len(meta) > 2 and isinstance(meta[2], str) else "generated.png"
                    mime = "image/png"
                    width = height = None
                    for el in meta:
                        if isinstance(el, str) and el.startswith("image/"):
                            mime = el
                        elif isinstance(el, list) and len(el) >= 2 \
                                and isinstance(el[0], int) and isinstance(el[1], int):
                            width, height = el[0], el[1]
                    out.append({"url": url, "mime": mime, "width": width,
                                "height": height, "filename": filename})
                except (IndexError, TypeError, KeyError):
                    continue
            return out
        except (IndexError, TypeError, KeyError):
            return []

    async def shutdown(self):
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.close()

    def _restore_session_state(self, prev: tuple) -> None:
        """把会话状态回滚到 reload_cookies 调用前（仅当调用前是健康的）。

        只还原 _healthy 是不够的：函数开头会清空 _session_token 并把新 Cookie 写进 jar，
        一个"健康但没有 SNlM0e token / 拿着别人 Cookie"的 client 会被池照常派活、然后每个
        请求都失败，3 次就被标 EXPIRED —— 比不还原更糟。所以整组状态一起回滚。
        """
        psid, psidts, session_token, was_healthy = prev
        if not was_healthy:
            return
        self._psid = psid
        self._psidts = psidts
        self._session_token = session_token
        self._healthy = True
        if self._cookie_jar is not None:
            self._cookie_jar.set("__Secure-1PSID", psid)
            if psidts:
                self._cookie_jar.set("__Secure-1PSIDTS", psidts)
        logger.warning("Cookie reload failed; restored the previous working session")

    async def reload_cookies(self, psid: str | None = None, psidts: str | None = None) -> dict:
        # F4（issue #11）：先快照重载前的会话状态。reload 的语义应是"要么换上新会话、
        # 要么原样不动"：旧实现在任何网络操作之前就无条件 self._healthy = False，失败返回
        # 路径却从不恢复，于是一次失败的刷新（面板误填 cookie、Google 临时 5xx、多账号池里
        # /reload-cookies 拿同一份 cookie 挨个试）就把一个本来健康的 client 永久拉黑。
        prev_state = (self._psid, self._psidts, self._session_token, self._healthy)

        if psid:
            self._psid = psid.strip().strip('"').strip("'").rstrip(";")
        if psidts:
            self._psidts = psidts.strip().strip('"').strip("'").rstrip(";")

        self._session_token = ""
        self._healthy = False
        self._last_reload_error = ""

        try:
            # Recreate HTTP session to avoid accumulated cookie conflicts
            if self._http:
                await self._http.close()
            self._http = AsyncSession(impersonate=self._current_target, timeout=60)

            self._cookie_jar.set("__Secure-1PSID", self._psid)
            if self._psidts:
                self._cookie_jar.set("__Secure-1PSIDTS", self._psidts)

            await self._obtain_session_token()
            if self._session_token:
                self._healthy = True
                self._ensure_refresh_task()
                await self._send_heartbeat()  # 拉取账号真实可用模型
                logger.info("Cookies reloaded successfully")
                return {"success": True}

            first_error = self._last_reload_error or "SNlM0e token not found"

            rotated = await self._rotate_cookies()
            if rotated:
                await self._obtain_session_token()
                if self._session_token:
                    self._healthy = True
                    self._ensure_refresh_task()
                    logger.info("Cookies reloaded after rotation")
                    return {"success": True}

            error_msg = self._last_reload_error or first_error
            logger.error(f"Cookie reload failed: {error_msg}")
            self._restore_session_state(prev_state)
            return {"success": False, "error": error_msg}
        except Exception:
            # 已经换上新会话之后才炸的（如 _send_heartbeat 抛错）不回滚，新会话是好的
            if not self._healthy:
                self._restore_session_state(prev_state)
            raise

    def _ensure_refresh_task(self):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
            logger.info("Auto-refresh loop started")


gemini_client = GeminiWebClient()
