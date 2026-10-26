import re
import ast
import json
import time
import uuid
import random
import asyncio
import logging
from enum import Enum
from typing import NamedTuple
from pathlib import Path
from threading import Lock
from collections import deque
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession, RequestsError

from app.config import settings
from app.core import keepalive_modes
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
# 非流式 POST 超时按模型族分层：同一道难题 flash-lite 几秒就回，pro / 开了思考的 flash
# 经常 80 秒以上（实测 87s）。过去全族共用 60s，于是"模型越强越容易被我们自己掐断"，
# 而且掐断后还会被通用重试放大成 60→等1s→60→等2s→60，用户等 183 秒才看到失败。
# 两个参考实现都比我们宽：refs/gemini-web-to-api 5 分钟（gemini_service.go:620 +
# openai_controller.go:162），refs/gemini-web2api 180 秒。可用 GENERATE_TIMEOUTS 覆盖。
_GENERATE_TIMEOUT_BY_FAMILY = {
    "flash-lite": 60,
    "flash": 120,
    "pro": 300,
    # Argon 的心跳描述是 "Complex tasks"，和 pro 同级，所以给 pro 档的时间。
    # 给兜底值（60s）的话，一道复杂题会在还在生成时被我们自己掐断。
    "argon": 300,
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


def _generate_timeout(resolved_model: str, prompt: str, models: dict | None = None) -> float:
    """这一次非流式 POST 该等多久（秒）。

    先按模型族分层（族认不出时用兜底值），"疑似生图"再单独抬一档（_GENERATE_TIMEOUT_IMAGE）。

    models 默认 None = 模块级写死表。**调用方必须传账号实例表**（_model_table()）：
    心跳发现来的模型在写死表里没有行，查不到 family 就退到兜底值 60s，于是一个
    "Complex tasks" 档的新模型（M1 的全部目的就是自动接上这种模型）会在还在生成时
    被我们自己掐断 —— 正是这张分层表存在的理由。
    注意生图这一档是**取大**而不是覆盖：生图是整个产品里最慢的操作，让 pro 生一张图
    （180s）比 pro 答一道文字难题（300s）还短，等于把"模型越强给越久"这条分层用反了。
    何况这里的判定输入是拍平后的整段 prompt（含 system 与全部历史），多轮对话里任何一句
    含图像关键词的话都会命中（`maybe_image_generation_intent("想做个图像识别的方案")`
    就是 True）—— 一个关键词猜测只被允许"加时"，绝不允许"减时"。
    """
    info = (models or GEMINI_MODELS).get(resolved_model)
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


def is_timeout_error(exc: BaseException) -> bool:
    """这次失败是不是一个超时（不区分连接期 / 生成期，见 _TIMEOUT_ELAPSED_RATIO）。

    覆盖 GenerationTimedOut（及任何 TimeoutError / asyncio.TimeoutError，真流式里 wait_for
    等不到下一个 chunk 抛的就是它）和 curl 的 code 28。路由用它决定「超时不重试」与
    classify_error 的 504 映射。
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return isinstance(exc, RequestsError) and getattr(exc, "code", None) == _CURL_TIMEDOUT


# 旧名：_send_request 与既有测试一直用它。
_is_timeout_error = is_timeout_error


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
# 真机实测（gemini-pro、需要推理的题、每档 2 次）：
#   low(1)    思考 411 / 707 字，36～47 秒
#   medium(4) 思考 524 / 450 字，30～34 秒
#   high(2)   思考 1256 / 562 字，42～65 秒 —— **已证实是最深的一档**
# low 与 medium 两次采样区分不开（噪声大），这两档沿用参考实现的映射。
# 做成常量：哪天拿到更干净的数据直接改这里，不用动调用方。
THINKING_LEVEL_LOW = 1
THINKING_LEVEL_MEDIUM = 4
THINKING_LEVEL_HIGH = 2
# 底层编码器（model header 第 15 位 / payload 第 80 格）拿到空档位、或 extended_thinking
# 传了裸 True 时的静态兜底档，保持改动前写死的那个 2。正常请求走不到这里：四个协议的
# 入参都先经 resolve_thinking 落成 1/2/4。
# ⚠️ 它**不是**"客户端没传思考参数"或"要了思考但没给档位"时用哪一档：这两种都跟随
# 面板/环境变量的"默认思考档位"（出厂 low，见 default_thinking_level），面板改了即时生效。
THINKING_LEVEL_DEFAULT = 2

_THINKING_LEVELS = {
    "low": THINKING_LEVEL_LOW,
    "medium": THINKING_LEVEL_MEDIUM,
    "high": THINKING_LEVEL_HIGH,
}
# Codex / Cursor 这类客户端会带 minimal/xhigh，夹到合法档位（同参考实现口径）。
# none 不在这里：OpenAI 官方语义是"不推理"，parse_effort_request 直接把它落成不思考。
_THINKING_ALIASES = {"minimal": "low", "xhigh": "high"}


# ---------------------------------------------------------------------------
# 思考请求的统一决策（四个协议共用）
# ---------------------------------------------------------------------------
# 各协议的解析器只负责把入参翻成"客户端要了什么"（requested），四态：
#   None                    = 客户端没说（没传 / 空值） → 用"默认思考档位"设置，**思考内容不回传**
#   False                   = 客户端明确不要思考         → 不思考旧路径
#   1/2/4                   = 客户端明确要了某一档       → 按这个档位走，回传
#   THINKING_FOLLOW_DEFAULT = 明确要了思考、但没给出可认的档位（Anthropic adaptive、budget
#                             无效、effort 认不出、Gemini 只给 includeThoughts……）
#                             → 档位跟随"默认思考档位"设置（设成 off 就不思考），回传
# 后一种过去写死成 high：Claude Code 默认发 adaptive，于是每个请求都跑最慢的一档。
# 然后统一交给 resolve_thinking 做决定。决策逻辑只有这一份。


class ThinkingRequest(Enum):
    """requested 里"档位"之外的特殊取值（见上）。"""
    FOLLOW_DEFAULT = "follow_default"


THINKING_FOLLOW_DEFAULT = ThinkingRequest.FOLLOW_DEFAULT

# 默认思考档位设置值 → 档位（None = 不思考）。键集合必须与
# settings_overrides.THINKING_DEFAULT_LEVELS 一致（有守卫测试）。
_DEFAULT_THINKING_CHOICES = {
    "off": None,
    "low": THINKING_LEVEL_LOW,
    "medium": THINKING_LEVEL_MEDIUM,
    "high": THINKING_LEVEL_HIGH,
}


def default_thinking_level() -> int | None:
    """当前"默认思考档位"设置对应的档位；off → None。每次请求现读，面板改了即时生效。"""
    raw = str(getattr(settings, "default_thinking_level", "low") or "").strip().lower()
    return _DEFAULT_THINKING_CHOICES.get(raw, THINKING_LEVEL_LOW)


class ThinkingPlan(NamedTuple):
    """一次请求的思考决策。

    level：发给上游的档位，None = 走不思考旧路径（payload/header 与改动前逐字节一致）。
    show： 是否把思考内容回传给客户端。**只有客户端明确要了才回传**：按默认档替客户端
           开的思考只用于上游生成 —— 官方 API 不请求就不返回思考，严格的客户端（含部分
           Claude Code 版本）收到未请求的 thinking 块会报错。
    """
    level: int | None
    show: bool

    @property
    def upstream(self):
        """原样喂给 generate / generate_stream 的 extended_thinking（False 或 1/2/4）。"""
        return self.level or False


THINKING_OFF = ThinkingPlan(None, False)


def resolve_thinking(requested, *, show: bool | None = None) -> ThinkingPlan:
    """requested（见上面四态）→ ThinkingPlan。show 只在"明确要了"时生效，None = 回传。"""
    if not getattr(settings, "extended_thinking_enabled", True):
        return THINKING_OFF            # 总闸：一律不思考，连明确请求也忽略
    if requested is None:
        return ThinkingPlan(default_thinking_level(), False)
    if requested is False:
        return THINKING_OFF
    show = True if show is None else bool(show)
    if requested is THINKING_FOLLOW_DEFAULT:
        level = default_thinking_level()
        # 默认档设成 off = 运维要的是快：没给档位的思考请求同样不思考
        return THINKING_OFF if level is None else ThinkingPlan(level, show)
    return ThinkingPlan(thinking_level_of(requested), show)


def parse_effort_request(effort) -> int | bool | ThinkingRequest | None:
    """OpenAI reasoning_effort / Responses reasoning.effort → requested（见上）。

    - 空值/纯空白 → None（视同没传、走默认档）
    - none        → False（OpenAI 官方语义"不推理"：走最快的不思考旧路径）
    - low/medium/high 及别名（minimal → low、xhigh → high）→ 对应档位
    - 认不出的非空值 → THINKING_FOLLOW_DEFAULT（跟随默认档），绝不 500
    """
    raw = str(effort if effort is not None else "").strip().lower()
    if not raw:
        return None
    if raw == "none":
        return False
    raw = _THINKING_ALIASES.get(raw, raw)
    return _THINKING_LEVELS.get(raw, THINKING_FOLLOW_DEFAULT)


# Anthropic 的 thinking 入参形态（官方现行规范）：
#   {"type":"enabled","budget_tokens":N}   旧式。N 最小 1024、且必须小于 max_tokens。
#                                          我方 api_forwarder 出站用的也正是这个形态。
#   {"type":"adaptive", "display":...}     4.6 起的新式写法，没有 budget。
#   {"type":"disabled"} / {"type":"between_tools"}   明确要求不思考。
# 只认 budget_tokens 的话，新版 Claude Code / SDK 发的 adaptive 请求会继续被锁在"不思考"。
_ANTHROPIC_THINKING_OFF = ("disabled", "between_tools")
# budget → 档位的切点，取 api_forwarder.py 的 LEVEL_BUDGET{low:1024,medium:2048,high:4096}
# 的**反函数**（相邻两档的下界作切点），这样"我方网关 → 第三方 Anthropic"再转回来时
# 档位往返一致，不会因为两处各写一套阈值而漂移。
_ANTHROPIC_BUDGET_MEDIUM = 2048
_ANTHROPIC_BUDGET_HIGH = 4096


def _budget_level(budget) -> int | ThinkingRequest:
    """正整数 budget → 档位；无效 budget → THINKING_FOLLOW_DEFAULT（跟随默认档）。

    整数值的浮点（有的 SDK 把 1024 序列化成 1024.0）照整数认，与 Gemini 解析器同口径。
    """
    if isinstance(budget, float) and budget.is_integer():
        budget = int(budget)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        return THINKING_FOLLOW_DEFAULT
    if budget >= _ANTHROPIC_BUDGET_HIGH:
        return THINKING_LEVEL_HIGH
    if budget >= _ANTHROPIC_BUDGET_MEDIUM:
        return THINKING_LEVEL_MEDIUM
    return THINKING_LEVEL_LOW


# Anthropic 的 output_config.effort → 档位。Claude Code 每个请求都带
# thinking:{"type":"adaptive"} + output_config.effort，出厂值是 high（2.1.296 抓包实测，
# 不换档时每个请求都是 high），所以 high 视同"没专门选档"、跟随默认档；用户在 Claude Code
# 里 /effort 换成 low / medium / xhigh / max 才会真正改到这里（同样抓包实测）。
# xhigh / max 夹到本仓最高的 high。
_ANTHROPIC_EFFORT_LEVELS = {
    "low": THINKING_LEVEL_LOW,
    "medium": THINKING_LEVEL_MEDIUM,
    "xhigh": THINKING_LEVEL_HIGH,
    "max": THINKING_LEVEL_HIGH,
}


def _anthropic_effort_level(output_config) -> int | ThinkingRequest:
    """output_config.effort → 档位；high / 没给 / 认不出 / 形态不对 → THINKING_FOLLOW_DEFAULT。"""
    effort = output_config.get("effort") if isinstance(output_config, dict) else None
    key = str(effort or "").strip().lower()
    return _ANTHROPIC_EFFORT_LEVELS.get(key, THINKING_FOLLOW_DEFAULT)


def parse_anthropic_thinking(thinking, output_config=None) -> int | bool | ThinkingRequest | None:
    """Anthropic 的 thinking（+ output_config.effort）入参 → requested（四态，见 resolve_thinking 上方说明）。

    - 没传 / 非 dict / 没有 type → None（视同没传：上游按默认档，**不出 thinking 块**；
                                   只给 effort 不开 thinking 也算没传）
    - disabled / between_tools  → False（effort 给了什么都不思考）
    - adaptive                  → 档位看 output_config.effort：low / medium 照档，xhigh / max →
                                   high；high（Claude Code 出厂值，视同没专门选档）/ 没给 → THINKING_FOLLOW_DEFAULT
                                   （跟随默认思考档位，出厂 low，面板设成 off 就不思考）
    - enabled + 合法 budget     → 按切点分档（budget 是专管思考的参数，优先于 effort）；
                                   budget 缺失/无效 → 同 adaptive
    - 认不出的 type             → None（同"没传"：不凭猜测去开 thinking 块）
    budget_tokens 不做 "< max_tokens" 校验、不 400 —— 宽容比正确性在这里更有用。
    """
    if not isinstance(thinking, dict):
        return None
    kind = str(thinking.get("type") or "").strip().lower()
    if not kind:
        return None
    if kind in _ANTHROPIC_THINKING_OFF:
        return False
    if kind == "adaptive":
        return _anthropic_effort_level(output_config)
    if kind != "enabled":
        logger.info("Unrecognized Anthropic thinking type %r; treating as not passed", kind)
        return None
    level = _budget_level(thinking.get("budget_tokens"))
    if level is THINKING_FOLLOW_DEFAULT:
        return _anthropic_effort_level(output_config)
    return level


# Gemini 原生 generationConfig.thinkingConfig（字段语义取自官方 SDK
# googleapis/python-genai google/genai/types.py 的 ThinkingConfig）：
#   includeThoughts: bool  —— 是否在响应里返回思考（true 才返回）
#   thinkingBudget:  int   —— token 预算，0 = 关闭，-1 = 自动；取值范围官方只写 "model dependent"
#   thinkingLevel:   enum  —— MINIMAL / LOW / MEDIUM / HIGH（另有 THINKING_LEVEL_UNSPECIFIED）
# 本仓只有三档，MINIMAL 夹到 low。budget 沿用 Anthropic 那张切点表（2048 / 4096），
# 不另起一套阈值 —— 官方没给各模型的 budget 范围，单独定切点也只是另一种猜测。
# 两个都传时：官方会回 400（ai.google.dev/gemini-api/docs/gemini-3 原文 "You cannot use both
# thinking_level and the legacy thinking_budget parameter in the same request. Doing so will
# return a 400 error."）。本仓**刻意宽容**、不 400：v1.6.42 根本不读 thinkingConfig，这类请求
# 一直是 200，现在改成 400 会让能用的客户端突然报错。取 level 为准（新字段，官方推荐）——
# 包括 thinkingBudget:0 + thinkingLevel:HIGH 这种自相矛盾的组合也按 level 走。
_GEMINI_THINKING_LEVELS = {
    "minimal": THINKING_LEVEL_LOW,
    "low": THINKING_LEVEL_LOW,
    "medium": THINKING_LEVEL_MEDIUM,
    "high": THINKING_LEVEL_HIGH,
}


def _pick(d: dict, camel: str, snake: str):
    return d.get(camel) if camel in d else d.get(snake)


def parse_gemini_thinking_config(config) -> tuple[int | bool | ThinkingRequest | None, bool]:
    """thinkingConfig → (requested, show)。show = includeThoughts is True（照官方语义）。

    非 dict（或没传）→ (None, False)：视同没传，上游按默认档、响应里不加思考部分。
    明确要了但档位认不出（UNSPECIFIED / 未知 level / budget=-1 自动 / 只给了
    includeThoughts）→ THINKING_FOLLOW_DEFAULT（跟随默认档），与另外两个协议"明确要了
    没给档"同口径。
    """
    if not isinstance(config, dict):
        return None, False
    show = _pick(config, "includeThoughts", "include_thoughts") is True
    level = _pick(config, "thinkingLevel", "thinking_level")
    if isinstance(level, str) and level.strip():
        key = level.strip().lower()
        if key.startswith("thinking_level_"):
            key = key[len("thinking_level_"):]
        return _GEMINI_THINKING_LEVELS.get(key, THINKING_FOLLOW_DEFAULT), show
    budget = _pick(config, "thinkingBudget", "thinking_budget")
    # 有的 SDK / 语言把数字统一序列化成浮点（JSON 里的 0.0、1024.0）。整数值的浮点照整数认，
    # 否则 0.0（= 关闭）会掉进"没传"、被默认档开成思考。带小数的预算不是合法 token 数，
    # 仍按"没给出可认的预算"处理。
    if isinstance(budget, float) and budget.is_integer():
        budget = int(budget)
    if isinstance(budget, int) and not isinstance(budget, bool):
        if budget == 0:
            return False, False
        if budget < 0:                  # -1 = AUTOMATIC
            return THINKING_FOLLOW_DEFAULT, show
        return _budget_level(budget), show
    if show:
        return THINKING_FOLLOW_DEFAULT, True
    return None, False


def should_retry_without_thinking(exc: BaseException, extended_thinking) -> bool:
    """这次失败是否该退回不思考重试：走了思考路径，且是 THINKING_RETRYABLE_ERRORS。"""
    return bool(extended_thinking) and isinstance(exc, THINKING_RETRYABLE_ERRORS)


async def generate_with_thinking_fallback(client, prompt, model, *args,
                                         extended_thinking=False, **kwargs):
    """client.generate；思考路径失败时原样退回不思考重试一次（非流式/buffered 路径共用）。

    开思考 = 走另一套 payload + header，失败率与普通路径不同。默认档上线后几乎每个请求
    都走思考路径，没有这一退回就会比改动前多出一类硬失败。不思考的请求失败照旧直接抛
    （不白打第二次上游）。
    """
    try:
        return await client.generate(prompt, model, *args,
                                     extended_thinking=extended_thinking, **kwargs)
    except THINKING_RETRYABLE_ERRORS as e:
        if not should_retry_without_thinking(e, extended_thinking):
            raise
        logger.warning(f"extended-thinking request failed, retrying normal: {e}")
        return await client.generate(prompt, model, *args, extended_thinking=False, **kwargs)


def thinking_level_of(extended_thinking) -> int:
    """从 extended_thinking 参数里取出思考档位。

    这个参数既是开关也是档位，形态有三种：
      False / None → 不走思考路径（调用方的 `if extended_thinking:` 为假）
      True         → 走思考路径、用静态兜底档 THINKING_LEVEL_DEFAULT
      1 / 2 / 4    → 走思考路径、并用这个档位

    为什么不另加一个平行的 thinking_level 参数：这个值要穿过 路由 → 账号池 →
    client 整条调用链，而账号池的 generate/generate_stream 对它只是透传。把档位搭在
    已有的参数上，账号池一行都不用改（它的选号/冷却/failover/自愈是另一条红线），
    调用方的真假判断也逐字节不变。
    """
    if isinstance(extended_thinking, ThinkingRequest):
        # 哨兵必须先经 resolve_thinking 落档；走到这里是调用方漏了那一步。静默兜底会把
        # "跟随默认档"变成写死的 high（正是这个哨兵要修掉的老症状），所以直接报错。
        raise TypeError(f"{extended_thinking!r} must be resolved by resolve_thinking() first")
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


# 思考路径失败后值得"原样退回不思考再试一次"的异常（非流式 / buffered / 真流式共用一份）。
# 超时（GenerationTimedOut 等 TimeoutError）刻意不在里面：生成期超时已经吃掉了整个 POST
# 预算，再打一次只会把用户的等待时间翻倍。
THINKING_RETRYABLE_ERRORS = (RuntimeError, ValueError, HTTPStatusError)

# 路由的非流式 / buffered 路径要接住的「生成失败」= 上面那几类 + 超时。超时过去不在这里，
# 一路冒到 ASGI 层，客户端拿到纯文本的 500 Internal Server Error（SDK 解析不了、不会按超时
# 重试、开了兜底也不兜）。接住之后走与其它生成失败同一条收尾：兜底（如开）→ 否则按
# classify_error 回 504 / timeout_error。
GENERATION_ERRORS = (*THINKING_RETRYABLE_ERRORS, TimeoutError)


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
    invalid_request_error/timeout_error）；OpenAI/Gemini 路由各自用自己的错误信封包裹同一个
    type 字符串。三个协议路由的非流式错误响应，以及 Claude 真流式的 error 帧，全部复用这一个
    函数，避免同一类失败在不同入口给出不一致（甚至互相矛盾）的状态码/类型。
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
    if is_timeout_error(exc):
        # 生成期超时（谷歌那边卡住、我们按预算掐断）：504 + timeout_error。过去落到最后的
        # 500 api_error，客户端分不出「网关坏了」和「上游太慢」，也不会按超时去重试。
        # timeout_error 是 Anthropic SDK 认识的类型；504 对应它的 GatewayTimeoutError。
        return 504, "timeout_error", None
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
    "gemini-3-flash-lite": {"id": "cf41b0e0dd7d53e5", "capacity": 1, "pro_only": False, "family": "flash-lite", "model_number": 6},
    "gemini-3-pro-plus": {"id": "e6fa609c3fa255c0", "capacity": 4, "pro_only": True, "family": "pro", "model_number": 3},
    "gemini-3-flash-plus": {"id": "56fdd199312815e2", "capacity": 4, "pro_only": True, "family": "flash", "model_number": 1},
    "gemini-3-flash-lite-plus": {"id": "8c46e95b1a07cecc", "capacity": 4, "pro_only": True, "family": "flash-lite", "model_number": 6},
    "gemini-3-pro-advanced": {"id": "e6fa609c3fa255c0", "capacity": 2, "pro_only": True, "family": "pro", "model_number": 3},
    "gemini-3-flash-advanced": {"id": "56fdd199312815e2", "capacity": 2, "pro_only": True, "family": "flash", "model_number": 1},
    "gemini-3-flash-lite-advanced": {"id": "8c46e95b1a07cecc", "capacity": 2, "pro_only": True, "family": "flash-lite", "model_number": 6},
    # 4 Argon（心跳条目 [11]="4 Argon" / [0]=95a4c0abcba24364 / [17]=8）。
    # 只登记真机实证过的那一个档位（capacity 2，真机 generate 已返回正常回答）：
    # cap 1 / cap 4 的 Argon 没有任何实证，按命名惯例编出来只会把请求发错档位，
    # 而发错档位的表现是"回答质量下降"，不报错、几周都发现不了。
    # 这一行只是兜底：心跳跑通后会被 _parse_models_from_status 采纳到的真实条目覆盖
    # （同名、同 id，capacity 换成账号级实测值）。
    "gemini-4-argon": {"id": "95a4c0abcba24364", "capacity": 2, "pro_only": True, "family": "argon", "model_number": 8},
}

# 对外暴露的稳定模型名（永不变，API 契约）。这 3 个恒定列出，
# 内部按账号当前真实可用的模型动态映射（心跳认出的网页模型：3.1 Pro / 3.8 Flash /
# 3.5 Flash-Lite），账号订阅等级/Google 灰度怎么变都不影响 API。
# 第 4 个对外名 gemini-argon 走"心跳发现到才列"（见 _public_model_names），没有 Argon
# 的账号不列、不路由。
# 过去还有第 5 个 gemini-flash-thinking：它只是"flash + 思考模式"的假模型。思考现在是
# 每个模型都有的 low/medium/high 档位（见 THINKING_LEVEL_*），这个名字就不再列出，
# 只作为隐藏别名指向 gemini-flash（见 MODEL_ALIASES），老客户端照样能调通。
PUBLIC_MODELS = ["gemini-pro", "gemini-flash", "gemini-flash-lite"]
# 这 3 个 family 是上面那 3 个契约公开名的唯一来源。心跳自动发现（见
# _describe_discovered_model）**绝不允许**往这几个 family 里写东西：一条被污染/异常的
# 心跳响应最大的危害不是多出一个模型，而是顶掉 gemini-pro 的映射、把用户请求路由到
# 意外模型。把这几个名字的来源和"发现"彻底隔开，它就顶不掉。
_BASE_FAMILIES = frozenset({"pro", "flash", "flash-lite"})
_PUBLIC_FAMILY = {
    "gemini-pro": "pro",
    "gemini-flash": "flash",
    "gemini-flash-lite": "flash-lite",
    # Argon 的公开名刻意不带版本号，和上面 3 个一个规矩：Google 下次改叫 4.1 就不用再
    # 加一个对外名字（"gemini-4-argon" 作为内部名/别名仍然可用，见 GEMINI_MODELS）。
    "gemini-argon": "argon",
}
# 每个**契约** family 的默认内部模型（账号没拉到真实模型时的兜底，按基础版）。
# ⚠️ 这张表的键必须恰好是 _BASE_FAMILIES，一个都不能多：它是"账号没有这个 family 时
# 照样放行"的唯一来源。3 个契约 family 每个账号都有，退兜底是安全的；心跳发现来的
# family（argon 及将来的新 family）**只有发现到它的那个账号**有，给它配一个兜底行
# 等于"任何账号都能路由 Argon"——混合池里 (N-1)/N 的请求会带着 Argon 的 model id
# 发给一个没有 Argon 的账号，而那既可能是 4xx/空回复，也可能是 Google 按账号默认模型
# 回答（HTTP 200、正文正常、客户端看不出被换了模型，见 _model_table 的 docstring）。
_FAMILY_DEFAULT = {
    "pro": "gemini-3-pro",
    "flash": "gemini-3-flash",
    "flash-lite": "gemini-3-flash-lite",
}
assert set(_FAMILY_DEFAULT) == set(_BASE_FAMILIES)
# family → 对外公开名（_PUBLIC_FAMILY 的反向表）。心跳发现到的 family 若在这里有登记，
# 就用这个稳定名字对外暴露；没登记的（将来某个全新 family）用发现到的名字本身。
_FAMILY_PUBLIC = {fam: name for name, fam in _PUBLIC_FAMILY.items()}

MODEL_ALIASES = {
    # 旧版别名 → 公开名（再由公开名按账号动态解析），保留兼容
    "gemini-2.5-pro": "gemini-pro",
    "gemini-2.5-flash": "gemini-flash",
    "gemini-2.5-pro-preview-05-06": "gemini-pro",
    "gemini-2.5-flash-preview-04-17": "gemini-flash",
    "gemini-2.5-flash-preview-05-20": "gemini-flash",
    "gemini-2.0-flash": "gemini-flash",
    "gemini-2.0-flash-lite": "gemini-flash-lite",
    "gemini-1.5-pro": "gemini-pro",
    "gemini-1.5-flash": "gemini-flash",
    # 已下线的假模型 flash-thinking（"flash + 思考模式"）：**不列出、但必须继续能调**，
    # 已经有客户端在用这些名字，绝不能让它们突然 400。一律落到 gemini-flash，思考按
    # 档位走（请求没带思考参数就用"默认思考档位"，同 gemini-flash）。
    # 内部名也要收：过去 gemini-3-flash-thinking* 是 GEMINI_MODELS 的真条目、可以直接调
    # （token_pricing 也按它们归一计价），删了条目不给别名，openai/responses 的闸门会把它们
    # 当成第三方模型 → 400。
    "gemini-flash-thinking": "gemini-flash",
    "gemini-2.5-flash-thinking": "gemini-flash",
    "gemini-2.0-flash-thinking": "gemini-flash",
    "gemini-3-flash-thinking": "gemini-flash",
    "gemini-3-flash-thinking-plus": "gemini-flash",
    "gemini-3-flash-thinking-advanced": "gemini-flash",
}
# 已下线、但仍作隐藏别名可调的旧公开名。只用来派生 _DISCOVER_RESERVED_WORDS（见下）。
_RETIRED_PUBLIC_MODELS = ("gemini-flash-thinking",)

KNOWN_MODELS = list(GEMINI_MODELS.keys())

# 写死表里**契约 family** 的那些行。它们在每个账号上都存在，所以可以无条件路由。
# 非契约 family 的写死行（当前只有 gemini-4-argon）刻意不在这里：那一行的作用是
# "id / model_number / 超时档位的口径兜底"，不是"任何账号都能调它"。要调它，必须由
# 该账号自己的心跳发现过（见 GeminiClient._model_table）。
_BASE_MODELS = {name: info for name, info in GEMINI_MODELS.items()
                if info["family"] in _BASE_FAMILIES}


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


def _entry_category(entry: list):
    """心跳模型条目的类别名：第 1 格优先，兜底第 10 格（参考实现 gemini_models.go:205
    `category := geminiFirstString(fields, 1, 10)` 同口径）。

    真实 Argon 条目这两格都是 "Argon" —— 这是**不带版本号**的产品族名字，所以用它当
    family 键；display（"4 Argon"）带版本号，Google 改一次版本号就会变成另一个 family。
    """
    for idx in (1, 10):
        value = _entry_field(entry, idx)
        if isinstance(value, str) and value.strip():
            return value
    return None


_DISCOVER_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_DISCOVER_SLUG_SEP_RE = re.compile(r"[^a-z0-9.]+")
_DISCOVER_FAMILY_RE = re.compile(r"^[a-z][a-z0-9.\-]{0,31}$")
_DISCOVER_NAME_RE = re.compile(r"^gemini-[a-z0-9][a-z0-9.\-]{0,39}$")
# 铸新公开名时不许出现的词：契约公开名（含已下线、仍作隐藏别名的旧公开名）里的每一个成分。
# 见 _describe_discovered_model。旧公开名也算进来：PUBLIC_MODELS 去掉 flash-thinking 后，
# "thinking" 若随之退出保留词，心跳就能铸出 gemini-thinking-xxx 这类"看着像官方思考模型"
# 的公开名。
_DISCOVER_RESERVED_WORDS = frozenset(
    part for name in (*PUBLIC_MODELS, *_RETIRED_PUBLIC_MODELS)
    for part in name.split("-") if part != "gemini"
)
# 一轮心跳最多采纳几条。畸形/被污染的响应可能塞几百条进来，而每条都要进实例态字典。
_DISCOVER_MAX_PER_ROUND = 8
# _discovered_models 的**累计**上限。上面那条只约束单轮，而心跳按 MIN_REFRESH_INTERVAL_MINUTES
# 一轮一轮地跑：只要上游（或被污染的响应）每轮给出新的合法条目，这张实例态字典就会一直长。
# 真实账号一共 4 个模型，32 已经是真相的 8 倍，到这个数只能说明解析口径出了问题。
_DISCOVER_MAX_TOTAL = 32


def _discover_slug(value: str) -> str:
    """参考实现 gemini_models.go:306-309 的 slug：小写 → 非 [a-z0-9.] 换成 '-' → 去首尾 '-'。"""
    return _DISCOVER_SLUG_SEP_RE.sub("-", str(value).strip().lower()).strip("-")


def _describe_discovered_model(entry: list, capacity: int) -> dict | None:
    """把一条"表里没有"的心跳模型条目解析成可采纳的模型描述；不合格返回 None。

    公开名的生成口径照参考实现 gemini_models.go:296-343 的 geminiModelNames：
    `prefix(slug(display))`。真实样本 display="4 Argon" → "gemini-4-argon"。

    capacity **不取条目级的 entry[4]**：参考实现的 geminiAccountCapacity
    (gemini_models.go:269-294) 是从账号级 status[16]/[17] 的标志位推出来的，条目级
    那一格的含义从来没被确认过（真实样本里 entry[4]=2 恰好等于账号档位，那是巧合不是
    口径）。所以 capacity 由调用方传入"同一次心跳里已认出的模型的 capacity"。

    校验链（任一不过就返回 None，由调用方照旧打那条 WARNING）：
      - model_id 必须是 16 位小写十六进制（真实 id 全是这个形态）
      - 必须有 category，且 slug 后是合法 family，且**不在 _BASE_FAMILIES 里**
      - 必须有 display，且 slug 后是合法公开名，且不顶掉任何既有对外名字
      - model_number 必须是正整数（bool 不算）。参考实现缺这一格时默认 1，我们不猜：
        对一个完全不认识的模型猜错编号就是"静默发成另一个模型"，而这正是最该防的事。
    """
    mid = _entry_field(entry, 0)
    if not isinstance(mid, str) or not _DISCOVER_ID_RE.match(mid):
        return None

    category = _entry_category(entry)
    if not isinstance(category, str):
        return None
    family = _discover_slug(category)
    if not _DISCOVER_FAMILY_RE.match(family) or family in _BASE_FAMILIES:
        return None
    # family 也不许含契约词：category="Flash Thinking" 会得到 family "flash-thinking" ——
    # 那是已下线的旧 family，它的公开名已经是指向 gemini-flash 的隐藏别名，不该被心跳
    # 重新"复活"成一个独立模型；同理 "Pro Max" 这类也不是一个新产品族。
    if _DISCOVER_RESERVED_WORDS.intersection(family.split("-")):
        return None

    display = _entry_display_name(entry)
    if not isinstance(display, str):
        return None
    slug = _discover_slug(display)
    name = slug if slug.startswith("gemini-") else f"gemini-{slug}"
    if not _DISCOVER_NAME_RE.match(name):
        return None
    # 名字空间隔离：不许顶掉契约公开名、公开名→family 映射、或任何老别名。
    if name in PUBLIC_MODELS or name in _PUBLIC_FAMILY or name in MODEL_ALIASES:
        return None
    # 也不许铸出"长得像契约名"的新公开名：category="Argon" + display="Pro 4" 会铸出
    # gemini-pro-4 —— 它不顶掉 gemini-pro，但会和它一起列在 /v1/models 里，看着像个
    # 官方 Gemini 名字、其实指向心跳给的任意 id。新 family 的名字不该含契约 family 的词。
    if _DISCOVER_RESERVED_WORDS.intersection(name.split("-")):
        return None
    # 与写死表同名只有一种情况是安全的：它就是同一个 family 的兜底行（Argon 正是如此），
    # 此时采纳等于用账号实测值刷新那一行。family 不一致说明解析口径已经和表对不上了。
    existing = GEMINI_MODELS.get(name)
    if existing is not None and existing.get("family") != family:
        return None

    raw_number = _entry_model_number(entry)
    if isinstance(raw_number, bool) or not isinstance(raw_number, int) or raw_number <= 0:
        return None

    return {
        "name": name,
        "family": family,
        "display_name": display,
        "info": {
            "id": mid,
            "capacity": int(capacity),
            "pro_only": True,
            "family": family,
            "model_number": raw_number,
        },
    }


def _model_number(model_name: str, models: dict | None = None,
                  family_model: dict[str, str] | None = None) -> int:
    """Resolved model's PR#310 model-type code (pro=3/flash=1/flash-lite=6); default 1.

    models / family_model 默认 None = 用模块级写死表（既有调用方行为逐字节不变）。
    传了实例表时才能看见心跳发现到的模型 —— 不传的话 Argon 的 model_number(8) 会退回
    默认值 1（= flash），thinking payload 的 inner[79] 就发错了。
    """
    resolved = _resolve_model(model_name, family_model)
    info = (models or GEMINI_MODELS).get(resolved)
    return int(info["model_number"]) if info and "model_number" in info else 1


def _resolve_model(model_name: str, family_model: dict[str, str] | None = None) -> str:
    """把用户请求的模型名解析为账号当前真实可用的内部模型名。
    1. 旧别名 → 公开名
    2. 公开名（gemini-pro/flash/flash-lite/argon）→ 账号当前该 family 真实可用的内部模型
       （family_model 为账号实例映射，缺省/未命中则用 family 默认）
    3. 已经是内部模型名（gemini-3-*）→ 原样

    family_model: 账号实例的 family→真实模型映射（P0-5：避免模块级全局被多账号污染）。
                  路由层仅做模型名校验时不传，退回 _FAMILY_DEFAULT。
    """
    name = MODEL_ALIASES.get(model_name, model_name)
    if name in _PUBLIC_FAMILY:
        family = _PUBLIC_FAMILY[name]
        fm = family_model or {}
        # 账号没有这个 family 时只有契约 family 退兜底行（见 _FAMILY_DEFAULT）。
        # 非契约 family 原样返回公开名，它不在任何账号的 _model_table() 里，
        # 于是 generate/generate_stream/_send_request 的闸门会抛 ValueError → 干净的 400，
        # 而不是静默把请求发成另一个模型。
        return fm.get(family) or _FAMILY_DEFAULT.get(family) or name
    return name


def _build_model_header(model_name: str, models: dict | None = None) -> dict[str, str]:
    """models 默认 None = 模块级写死表（既有调用方逐字节不变）；传实例表才看得见发现到的模型。"""
    resolved = _resolve_model(model_name)
    model_info = (models or GEMINI_MODELS).get(resolved)
    if not model_info:
        # 调用方必须先过 `resolved not in self._model_table()` 那道闸门，所以生产路径
        # 走不到这里。真走到了就是最隐蔽的事故形态：调用点的 `if model_headers:` 跳过
        # → 请求不带模型头发出 → Google 用账号默认模型回答、HTTP 200、客户端看不出。
        # 宁可留一条 WARNING 也不要静默。
        logger.warning("No model header for %r (resolved=%r): the request would go out "
                       "without a model id", model_name, resolved)
        return {}
    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_info["id"]}",null,null,0,[4],null,null,{model_info["capacity"]}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


def _build_model_header_thinking(model_name: str, session_uuid: str,
                                 thinking_level: int | None = None,
                                 models: dict | None = None) -> dict[str, str]:
    """PR#310 17-element model header；第 15 位是思考档位（见 THINKING_LEVEL_LOW/MEDIUM/HIGH）。

    models 默认 None = 模块级写死表（既有调用方逐字节不变）。
    """
    resolved = _resolve_model(model_name)
    info = (models or GEMINI_MODELS).get(resolved)
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


# ---------------------------------------------------------------------------
# Canvas 正文还原（M3）与正文里的控制标记清理（M4）
# ---------------------------------------------------------------------------
# Gemini 网页端写较长代码/文档时会自动把内容放进 Canvas 面板，正文里只留一个
# `http://googleusercontent.com/immersive_entry_chip/N` 占位链接 —— 既不读真实内容、
# 也不剥这个链接的话，客户端拿到的"答案"就是一条打不开的 URL，正文全丢。
# 真实内容在 candidate[30]，口径同参考实现 refs/gemini-web-to-api
# internal/modules/providers/gemini_canvas.go 的 extractCanvases / renderCanvasPlaceholders
# （那边的抽取是**无条件**跑的，说明普通对话里也会出现 Canvas）。
_CANVAS_CHIP_RE = re.compile(r'https?://googleusercontent\.com/immersive_entry_chip/(\d+)')
# 取不到真实内容时的说明文案。**绝不能只把死链删成空白**：正文变空会被
# fallback.is_empty_result / account_pool._is_empty_generation 判成"空响应"，
# 累加空响应计数器甚至触发换号。生图那句提示（_IMAGE_RETRIEVAL_HINT）语义完全不对，
# 不能复用。
# 这句会被**拼进正文**交给客户端（不是日志、不是面板文案），所以中英双语：英文/日文/
# 韩文会话里甩一句纯中文很突兀，而 chip 就是整个正文时它还会是全部答案。
_CANVAS_MISSING_NOTE = ("（这段内容 Gemini 放进了 Canvas 面板，本次没能取回正文。"
                        "/ This part was moved into Gemini's Canvas panel and could "
                        "not be retrieved.）")
_CANVAS_CODE_KIND = 2

# card_content 是和生图占位同族的死链（客户端访问无效），纯删除即可。
# 参考实现 B 不处理，参考实现 A（refs/gemini-web2api gemini.py:165）按同一形状删。
_CARD_CONTENT_RE = re.compile(r'https?://googleusercontent\.com/card_content/\d+\n?')

# ```python?code_reference&code_event_index=3 这种伪代码围栏的 info string。
# 参考实现 A（gemini.py:161-164）把整个围栏连正文一起 DOTALL 删掉；我们**只摘标记、
# 保留正文**：那个围栏里装的到底是空壳、是前文代码的重复、还是模型真写的代码/真实
# stdout，手上没有真机样本，删错就是又一次"正文丢失"。宁可多留一个围栏，不可少给一段代码。
_CODE_EVENT_MARK_RE = re.compile(r'\?code_(?:reference|stdout)&code_event_index=\d+')
# 流式时这个标记是逐字符到达的。半截标记（`?code_ref`）既不被上面的完整正则匹配、
# 又会在 final 里被清掉 —— 一旦 emit 出去就破坏了 append-only 前缀关系，四个路由的
# "补发缺失尾部"分支（final_text.startswith(已流出的内容)）直接走不到，客户端丢内容。
# 所以和占位 URL 一样，需要一组"完整起始模板"用来 hold。
_CODE_EVENT_MARK_PREFIXES = (
    "?code_reference&code_event_index=",
    "?code_stdout&code_event_index=",
)

# <ctrl94>thought…<ctrl95>：思考内容泄漏进正文。
# **只处理成对出现的**。参考实现 B（refs/gemini-web-to-api internal/commons/utils/
# utils.go:318-332）在只有起始标记、没有结束标记时把起始之后的**全部内容**都当思考、
# 正文只留起始之前那段 —— 那是一条数据丢失路径（用户正文里出现一次字面量 `<ctrl94>`
# 就会丢掉后面所有回答）。我们反过来：未闭合一律原样保留。
_CTRL_THOUGHT_RE = re.compile(r'<ctrl94>(?:thought)?(.*?)<ctrl95>', re.S)
_CTRL_MARKERS = ("<ctrl94>", "<ctrl95>")


def _extract_canvases(candidate: list) -> list[dict]:
    """从 candidate[30] 取出本帧的 Canvas 条目（结构不对/无内容一律返回 []，绝不抛）。

    条目布局（参考实现 gemini_canvas.go:83-123 实证）：
      [id, _, title, _, content, …, fileName(9), kind(10), …, details(14), …]
      kind == 2 → 代码，否则文档；details 的第 1 格或第 4 格是语言，都没有就用
      fileName 的扩展名。
    """
    try:
        if not isinstance(candidate, list) or len(candidate) <= 30:
            return []
        entries = candidate[30]
        if not isinstance(entries, list):
            return []
        out: list[dict] = []
        for entry in entries:
            if not isinstance(entry, list) or len(entry) < 11:
                continue
            content = entry[4]
            if not isinstance(content, str) or not content:
                continue
            file_name = entry[9] if isinstance(entry[9], str) else ""
            language = ""
            details = entry[14] if len(entry) > 14 else None
            if isinstance(details, list):
                for idx in (1, 4):
                    if idx < len(details) and isinstance(details[idx], str) and details[idx]:
                        language = details[idx]
                        break
            if not language and "." in file_name:
                language = file_name.rsplit(".", 1)[-1]
            out.append({
                "id": entry[0] if isinstance(entry[0], str) else "",
                "title": entry[2] if isinstance(entry[2], str) else "",
                "file_name": file_name,
                "is_code": entry[10] == _CANVAS_CODE_KIND,
                "language": language,
                "content": content,
            })
        return out
    except (IndexError, TypeError, KeyError):
        return []


def _warn_if_canvas_list_shrank(previous: list, current: list) -> None:
    """后一帧带的 Canvas 条目比前一帧少时留一条 WARNING。

    两条解析路径都是"保留最新非空帧"（参考实现 gemini_canvas.go:1093 同口径）。可是
    chip 里的 N 是不是 canvases 数组下标，真机上还没有定论：如果是，而最后一个非空帧
    少了几条，那么一个**下标没越界**的 chip 就会渲染成另一个 Canvas 的内容 —— 正文被
    张冠李戴，而且不像越界那样有日志。这条告警就是为了让真机流量来裁决这件事。
    """
    if previous and current and len(current) < len(previous):
        logger.warning(
            "Canvas list shrank between frames: %d -> %d; an in-range chip index may now "
            "resolve to a different canvas", len(previous), len(current),
        )


def _canvas_markdown(canvas: dict) -> str:
    """把一个 Canvas 渲染成官方 API 返回生成文件时的那种形态（文档原样、代码加围栏）。"""
    content = str(canvas.get("content") or "").strip()
    if not canvas.get("is_code") or content.startswith("```"):
        return content
    return f"```{canvas.get('language') or ''}\n{content}\n```"


def _render_canvas_chips(text: str, canvases: list) -> str:
    """把正文里的 immersive_entry_chip 占位链接换成它代表的 Canvas 真实内容。

    取不到对应 Canvas 时换成 _CANVAS_MISSING_NOTE（而不是删成空白）：死链不能当答案
    交付，但正文也不能变空。chip 里的 N 按参考实现是 canvases 数组下标，真机上是否
    还有别的口径没有定论，所以越界时打一条日志把 N 和条目数都写出来，方便核对。
    """
    if not text or not _CANVAS_CHIP_RE.search(text):
        return text

    def _one(m: "re.Match[str]") -> str:
        try:
            index = int(m.group(1))
        except ValueError:          # pragma: no cover - 正则已保证是数字
            index = -1
        if 0 <= index < len(canvases):
            return _canvas_markdown(canvases[index])
        logger.warning(
            "Canvas placeholder has no content to render: index=%s canvases=%d",
            m.group(1), len(canvases),
        )
        return _CANVAS_MISSING_NOTE

    return _CANVAS_CHIP_RE.sub(_one, text)


def _clean_control_markers(text: str) -> tuple[str, str]:
    """清掉正文里的控制标记，返回 (清理后的正文, 抽出来的思考文本)。

    三类：
      1. 成对的 <ctrl94>thought…<ctrl95> —— 内容**归到思考链**，不是直接扔掉
         （我们有 reasoning_content / thinking 通道，扔掉就是白丢模型的思考过程）。
         未闭合的 <ctrl94> 原样保留（见 _CTRL_THOUGHT_RE 的注释）。
      2. code_reference / code_stdout 伪围栏的 info string —— 只摘标记、留正文。
      3. card_content 死链 —— 删掉。
    """
    if not text:
        return text, ""
    thoughts: list[str] = []
    if "<ctrl94>" in text and "<ctrl95>" in text:
        def _take(m: "re.Match[str]") -> str:
            piece = (m.group(1) or "").strip()
            if piece:
                thoughts.append(piece)
            return ""
        text = _CTRL_THOUGHT_RE.sub(_take, text)
    if "code_event_index=" in text:
        text = _CODE_EVENT_MARK_RE.sub("", text)
    if "card_content/" in text:
        text = _CARD_CONTENT_RE.sub("", text)
    return text, "\n\n".join(thoughts)


def _restore_body(text: str, canvases: list, thoughts: str) -> tuple[str, str]:
    """正文还原 + 控制标记清理，返回 (正文, 合并后的思考链)。

    流式收尾（_finalize_stream）与非流式（_parse_output）**必须调同一个函数**：两条
    路径对同一段正文产出不一致，就是本仓最难查的一类 bug（同一个请求走 buffered 和走
    真流式拿到不同答案）。

    顺序是定死的：Canvas 还原 → 控制标记清理。Canvas 的真实内容本身也可能带 ctrl
    标记，所以必须先还原再清理。生图占位的剥除**不在这里**：两条路径在"真的拿到图"
    时的收尾口径本来就不同（见 _finalize_stream），那是改动前就有的区别。
    """
    text = _render_canvas_chips(text, canvases or [])
    text, ctrl_thoughts = _clean_control_markers(text)
    return text, _merge_thoughts(thoughts, ctrl_thoughts)


def _merge_thoughts(primary: str, extra: str) -> str:
    """candidate[37] 的思考链在前，ctrl94 抽出来的在后。

    顺序不能反：openai.py 的流式收尾只在 `final_thoughts.startswith(emitted_thoughts)`
    时补发差量，否则明确不重发 —— 把 ctrl 那段放前面会让前缀关系断裂、整段 reasoning
    被静默丢掉。
    """
    if not extra:
        return primary
    if not primary:
        return extra
    return f"{primary}\n\n{extra}"


def _hold_from_marker(cleaned: str, templates: tuple) -> int:
    """`cleaned` 里最早一个"该 hold 住"的下标；没有就返回 len(cleaned)。

    命中条件和逐位置扫描完全一样：某个起点 p 之后的尾巴 `cleaned[p:]` 要么是某个模板的
    真前缀（还可能补全成完整标记），要么以某个模板开头（标记已完整但正则还没清掉它，
    例如 `?code_reference&code_event_index=` 的数字还没到）。

    为什么不逐位置扫：那条路要对每个候选字符切一次尾巴（`tail = cleaned[p:]` 是一次
    O(剩余长度) 的复制），代价 = 候选字符数 x 正文长度。`http` 在散文里罕见，但 `<` 和
    `?` 在 HTML/JSX/XML/代码里遍地都是 —— 而那正是 Canvas 还原与控制标记清理要处理的
    内容。实测 118KB 的代码类回答、1000 帧要烧 8 秒**同步** CPU，而这段代码跑在流式
    生成器里，等于把整个事件循环连带同实例上所有并发请求一起堵住。

    两种命中各自有 O(n) 的算法，不必逐位置切片：
      - 模板是尾巴的延长（半截标记）只可能出现在**末尾**，查后缀即可，代价只跟模板长度
        有关、与正文长度无关；
      - 已完整的标记用 str.find 一次定位。
    """
    cut = len(cleaned)
    for tmpl in templates:
        # a) 尾部半截：cleaned 以 tmpl 的某个真前缀结尾（k 从长到短，取最早的起点）
        for k in range(min(len(tmpl), len(cleaned)), 0, -1):
            if cleaned.endswith(tmpl[:k]):
                cut = min(cut, len(cleaned) - k)
                break
        # b) 完整标记（含"模板到齐、可变部分还没到"）
        p = cleaned.find(tmpl)
        if p != -1:
            cut = min(cut, p)
    return cut


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
    # 成对的 ctrl 标记整段剥掉继续放行（收尾 _restore_body 会把同一段归进思考链）。
    if "<ctrl94>" in cleaned and "<ctrl95>" in cleaned:
        cleaned = _CTRL_THOUGHT_RE.sub("", cleaned)
    # ⚠️ 下面两步的顺序必须和 _clean_control_markers 里**完全一致**，而且 card_content
    # 必须在 code_event 之后：_CARD_CONTENT_RE 会连带吃掉紧跟的一个 `\n`，所以两步不可
    # 交换 —— card_content 链接后面紧跟 `?code_stdout&...` 时，先剥 card_content 的那
    # 一侧下一个字符是 `?`（`\n?` 不匹配，`\n` 留下），先剥 code_event 的那一侧 `\n` 会
    # 被吃掉。两条路径对同一段正文产出不一致，流出去的文本就不再是 final 的前缀，四个
    # 路由"补发缺失尾部"的分支（final_text.startswith(已流出的内容)）直接走不到，
    # 整段还原出来的 Canvas 正文会被静默丢掉。
    # 已完整的 code_reference / code_stdout 标记一起剥掉（与 _clean_control_markers 同口径）。
    if "code_event_index=" in cleaned:
        cleaned = _CODE_EVENT_MARK_RE.sub("", cleaned)
    # card_content 死链和生图占位同族（纯删除、没有"剥空给提示"的语义），一起在这里剥掉，
    # 否则它后面的正文会被下面的 host 前缀 hold 白白压到 final 才发。
    if "card_content/" in cleaned:
        cleaned = _CARD_CONTENT_RE.sub("", cleaned)
    # 1) 占位 URL：尾部刚到一半的（含只到 `h`/`ht`/`htt` 的协议头）与已完整但数字还没
    #    到的，都从起点 hold 住。
    cut = _hold_from_marker(cleaned, (_IMAGE_GEN_PLACEHOLDER_PREFIX,
                                      _IMAGE_GEN_PLACEHOLDER_PREFIX_S))
    # 2) 刚到一半的 code_event 标记（`=` 到了但数字还没到时模板恰好等于尾巴，也要 hold）。
    cut = min(cut, _hold_from_marker(cleaned, _CODE_EVENT_MARK_PREFIXES))
    # 3) 尚未闭合（或刚到一半）的 ctrl 控制标记：等 final 决断。没有这道 hold，
    #    `<ctrl94>` 会被原样流给客户端，而 final 里它要么被清掉（成对）、要么留着
    #    （未闭合）—— 前一种会直接破坏 append-only 前缀关系。
    cut = min(cut, _hold_from_marker(cleaned, _CTRL_MARKERS))
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


# ---------------------------------------------------------------------------
# 多轮续接的会话元数据 [cid, rid, rcid]
# ---------------------------------------------------------------------------
# Gemini 网页版续接一个会话靠三个 id（口径同参考实现 refs/gemini-web-to-api
# internal/modules/providers/gemini_chat_session.go 的 buildMetadata、HanaokaYuzu Gemini-API
# 的 ChatSession.metadata）：
#   cid   会话 id（c_…）            响应 payload[1][0]（实测 payload[1] 是 ["c_…", "r_…"]）
#   rid   这一轮回答的 id（r_…）     响应 payload[1][1]
#   rcid  被采用的候选的 id（rc_…）  响应 payload[4][0][0]（候选数组第 0 位）
# 请求时放在内层数组第 2 格，**必须是列表**（缺的位置 None）。v1.6.44 及以前存的是
# str(payload[1])（Python repr "['c_…', 'r_…']"），下一轮把这个字符串原样塞进第 2 格，
# 思考路径（默认档上线后几乎所有请求）干脆不带；两种谷歌都当成新会话 —— 第二轮起每一轮
# 其实都开了新会话、只发了最后一句。
_CID_RE = re.compile(r"^c_[0-9A-Za-z_.-]{1,128}$")
_RID_RE = re.compile(r"^r_[0-9A-Za-z_.-]{1,128}$")
_RCID_RE = re.compile(r"^rc_[0-9A-Za-z_.-]{1,128}$")
# 存储里的值超过这个长度一律当坏值：三个 id 加起来远到不了，也免得 literal_eval 去啃大输入。
_CONV_META_MAX_LEN = 1024


def _normalize_conversation_metadata(value) -> list | None:
    """列表 / 元组 → [cid, rid, rcid]（rid、rcid 不合格的位置填 None）；cid 不合格 → None。

    只认长得像 Gemini id 的值：一个坏 cid 塞进 payload，谷歌多半静默开新会话 —— 正是要堵的
    「悄悄丢上下文」。不记日志（流式每帧都会走这里）。
    """
    if not isinstance(value, (list, tuple)) or not value:
        return None
    cid = value[0]
    if not (isinstance(cid, str) and _CID_RE.match(cid)):
        return None
    rid = value[1] if len(value) > 1 else None
    rcid = value[2] if len(value) > 2 else None
    return [
        cid,
        rid if isinstance(rid, str) and _RID_RE.match(rid) else None,
        rcid if isinstance(rcid, str) and _RCID_RE.match(rcid) else None,
    ]


def parse_conversation_metadata(raw) -> list | None:
    """续接元数据 → [cid, rid, rcid]；没有可续接的会话 → None。

    读取一律走这里（路由决定续不续接、两个 payload 编码器决定第 2 格放什么）。认：
      - JSON 列表 '["c_…", "r_…", "rc_…"]'（v1.6.45 起的存储格式，见 encode_conversation_metadata）
      - 旧的 Python repr "['c_…', 'r_…']"（v1.6.44 及以前存的；ast.literal_eval 只认字面量）
      - 纯 "c_…" 字符串 → [cid, None, None]
      - 已经是列表 / 元组
    空值 → None（不记日志）；其它坏值 → None 并记一行日志：调用方据此改发完整历史、新开会话，
    绝不把坏值塞进 payload 让谷歌静默开新会话。
    """
    if not raw:
        return None
    value = raw
    if isinstance(raw, str):
        text = raw.strip()
        if _CID_RE.match(text):
            return [text, None, None]
        value = None
        if text.startswith("[") and len(text) <= _CONV_META_MAX_LEN:
            try:
                value = json.loads(text)
            except (ValueError, RecursionError):
                try:
                    value = ast.literal_eval(text)
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    value = None
    meta = _normalize_conversation_metadata(value)
    if meta is None:
        logger.warning("Unusable conversation metadata %r; not resuming, starting a new conversation",
                       str(raw)[:120])
    return meta


def encode_conversation_metadata(meta) -> str:
    """[cid, rid, rcid] → 存储用的 JSON 字符串（Conversation.gemini_conv_id）；没有有效 cid → ""。"""
    meta = _normalize_conversation_metadata(meta)
    return json.dumps(meta) if meta else ""


def _response_conversation_metadata(payload: list) -> list | None:
    """从一帧响应 payload 里取续接三元组（流式与非流式共用，口径必须一致）。

    payload[1] 实测是 ["c_…", "r_…"]，个别帧只给一个 "c_…" 字符串（参考实现
    gemini_video.go 的 conversationIDFromPayload 两种都认）；rcid 取被采用的候选
    payload[4][0] 的第 0 格。
    """
    head = payload[1] if len(payload) > 1 else None
    if isinstance(head, str):
        cid, rid = head, None
    elif isinstance(head, list) and head:
        cid = head[0]
        rid = head[1] if len(head) > 1 else None
    else:
        return None
    rcid = None
    cands = payload[4] if len(payload) > 4 else None
    if isinstance(cands, list) and cands and isinstance(cands[0], list) and cands[0]:
        rcid = cands[0][0]
    return _normalize_conversation_metadata([cid, rid, rcid])


def _extract_text_from_wrb(elem: list) -> tuple[str | None, str, str]:
    """从单个 wrb.fr 帧提取 (累积文本, 会话元数据, 思维链)。非文本帧返回 (None, "", "")。
    文本路径 payload[4][0][1][0]；会话元数据是 encode_conversation_metadata 编出来的
    [cid, rid, rcid] JSON，与非流式 _parse_output 逐字节一致（它会存进 conversation_store，
    下轮回传给 payload 编码器续接会话，流式与非流式必须同格式，否则多轮对话续接会错乱）。
    思维链路径 payload[4][0][37][0][0]（extended thinking 开启时才有，与 _parse_output 保持一致）。
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
        conv = encode_conversation_metadata(_response_conversation_metadata(payload))
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
    # 类级默认值：测试替身常用 __new__ 绕开 __init__ 造实例，刷新循环 / 状态导出照样读得到它。
    _auth_expired = False
    _rotation_rejected_for: tuple | None = None
    _browser_pushes_in_flight = 0

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
        # 会话已被谷歌打回登录页（见 auth_expired）。与 _healthy 分开记：不健康的原因很多
        # （网络抖动、5xx、页面解析失败……），只有这一种必须换 cookie 才能恢复。
        self._auth_expired = False
        # 谷歌对哪一份 cookie（PSID, PSIDTS）的 RotateCookies 明确回过 401（见 _rotation_futile）。
        self._rotation_rejected_for: tuple | None = None
        # 正在进行中的「浏览器保活插件推来的」reload 个数（见 reload_cookies 的 keepalive_mode）。
        self._browser_pushes_in_flight = 0
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
        # 心跳自动发现并采纳的模型：内部名 → 与 GEMINI_MODELS 同形状的 info。
        # 刻意**只存在实例态**（P0-5 实例隔离）：A 账号发现的模型绝不能喂给 B 账号。
        # 也刻意不持久化（data/models_cache.json 那对死函数不要复活，它是全局单文件）：
        # 重启后第一次心跳之前走 GEMINI_MODELS 的兜底行，行为与改动前一致。
        self._discovered_models: dict[str, dict] = {}

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
        if self.keepalive_mode == keepalive_modes.MODE_BROWSER:
            # 循环照起（token 探测、心跳照旧），只是 RotateCookies 交给浏览器（见 _rotate_cookies）。
            logger.info(
                "Cookies of this account are kept alive by the browser plugin; server-side "
                "RotateCookies is off (update the cookie from the panel to hand it back)"
            )
        self._ensure_refresh_task()

        if settings.health_check_enabled:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def auth_expired(self) -> bool:
        """会话已被谷歌打回登录页（cookie 已失效，换新的才能恢复）。只读。

        只在**产生**「打回登录页」判定的地方置位（_detect_login_redirect：_obtain_session_token
        与 check_account 读的是同一个 /app 页面）；成功拿到 SNlM0e、reload_cookies 成功时清掉。
        RotateCookies 回 401 本身不置位 —— 以随后的 token 获取结果为准。

        用途：①AccountPool.get_status 把「池里还标着 ACTIVE、其实会话已死」的账号对外报成
        expired（浏览器保活插件只认 expired）；②置位、且谷歌已对这同一份 cookie 回过 401 之后，
        不再白敲 RotateCookies（见 _rotation_futile）。光置位不停轮换：PSIDTS 过期的会话同样会被
        打回登录页，而它往往一次轮换就能救回来。
        """
        return self._auth_expired

    @property
    def keepalive_mode(self) -> str:
        """这个账号的 cookie 由谁保活：browser（浏览器保活插件推送，服务端不轮换）/ server（默认）。

        按**当前** PSID 查 data/keepalive-modes.json（PSID 在轮换中不变、重新登录才变）。每次都读盘，
        运维手改记录不用重启。getattr 兜底：测试替身常用 __new__ 造实例、不一定有 _psid。
        """
        return keepalive_modes.get_mode(getattr(self, "_psid", ""))

    def set_keepalive_mode(self, mode: str) -> bool:
        """把**当前** PSID 记成 mode（admin 接口在 reload 成功之后按请求来源调用）。落盘失败返回 False。"""
        return keepalive_modes.set_mode(self._psid, mode)

    def _model_table(self) -> dict:
        """**本账号**当前可路由的模型表：契约 family 的写死行 + 本账号心跳发现到的。

        header / payload 构造必须用这个而不是模块级 GEMINI_MODELS，否则发现到的模型
        会在 _build_model_header 里查不到 → 返回 {} → 调用点的 `if model_headers:`
        跳过 → 请求**不带模型头**发出 → Google 用账号默认模型回答，HTTP 200、正文正常、
        客户端完全看不出被换了模型。这是整条链路上最隐蔽的事故形态。

        为什么不是整张 GEMINI_MODELS：非契约 family 的写死行（gemini-4-argon）是口径
        兜底，不代表"这个账号有这个模型"。混合池里 account_pool.models 是跨账号聚合的，
        一个账号发现了 Argon，/v1/models 就会列出 gemini-argon，而选号是轮转的 —— 把
        写死那一行也算进"可路由"，(N-1)/N 的 Argon 请求就会带着 Argon 的 model id 发给
        一个没有 Argon 的账号，一个错都不报。所以这张表只收"该账号真的有"的行：契约
        family（每个账号都有）+ 这个账号自己心跳发现到的。
        """
        discovered = self.__dict__.get("_discovered_models") or {}
        if not discovered:
            return _BASE_MODELS
        return {**_BASE_MODELS, **discovered}

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
                    self._adopt_session_token(token_match.group(1), body)
                    self._healthy = True
                    await self._send_heartbeat()  # 拉取账号真实可用模型
                else:
                    # 与 _obtain_session_token 同一判定：健康检查循环、/check 看到登录页也要记下来
                    self._detect_login_redirect(body)

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

    def _adopt_session_token(self, token: str, body: str) -> None:
        """拿到了 SNlM0e：换上新 token。能拿到 token 就说明会话没被打回登录页。

        上一次失效期间记下的「谷歌拒绝过这份 cookie」也一并作废：会话活过来了，下一次再被
        打回登录页时照旧先试一次轮换（见 _rotation_futile）。
        """
        self._session_token = token
        self._push_id = _extract_push_id(body)
        self._auth_expired = False
        self._rotation_rejected_for = None

    @staticmethod
    def _session_cookie_pair(cookies: dict) -> tuple:
        """一份 cookie 的身份：(__Secure-1PSID, __Secure-1PSIDTS)。只在内存里比对，不落盘、不进日志。"""
        return (cookies.get("__Secure-1PSID"), cookies.get("__Secure-1PSIDTS"))

    def _rotation_futile(self) -> bool:
        """这次轮换注定白敲：会话已被打回登录页（auth_expired），且谷歌已经对**这同一份** cookie
        （按 PSID + PSIDTS 比对）的 RotateCookies 明确回过 401。

        两个条件缺一不可：
        - 光 auth_expired 不够：PSIDTS 过期的会话同样会被打回登录页，而它往往一次轮换就能救回来
          （issue #11 的自愈）。复审复现过死锁：一置位就永久停轮换，启动那一次就地轮换碰上网络
          抖动，之后就再也救不回来。
        - 光 401 不够：401 本身不说明会话死了（规格：以随后的 token 获取结果为准）。
        cookie 一变（换上新 cookie、某个响应 Set-Cookie 下发了新 PSIDTS）旧记录就不再命中，给新
        cookie 一次机会；拿到 token（_adopt_session_token）、reload 成功都会清掉它。
        """
        rejected = self._rotation_rejected_for
        if not self._auth_expired or rejected is None:
            return False
        try:
            return self._session_cookie_pair(self._get_cookies()) == rejected
        except Exception:
            return False

    def _detect_login_redirect(self, body: str) -> bool:
        """/app 页面被谷歌打回了登录页 → 置 auth_expired 并返回 True。

        这是 auth_expired 唯一的置位点（_obtain_session_token 与 check_account 都经过这里）。
        """
        if "accounts.google.com" in body or "ServiceLogin" in body:
            self._auth_expired = True
            return True
        return False

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
                self._adopt_session_token(token_match.group(1), body)
                logger.info("Session token acquired")
            else:
                self._session_token = ""
                if self._detect_login_redirect(body):
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
        # 浏览器保活的账号服务端一律不轮换。闸口只设在这一处：刷新循环、reload 兜底、启动重试、
        # 自愈都经过这里，不必逐个改调用方。浏览器和服务端共用同一个谷歌会话，两边各自调
        # RotateCookies，后一方拿着被对方换掉的旧 PSIDTS 去换就 401、整个会话被踢下线
        # （见 app/core/keepalive_modes.py）。不发任何网络请求（轮换抖动也免了），按「现有 cookie
        # 仍有效」返回：既不算成功也不算失败，调用方的 `if rotated:` 照旧往下走去取 token。
        # 插件推来的 reload 进行中也算：新 PSID 的记录要等 reload 成功后才写，这期间按记录查会是
        # 默认的 server，reload 自己的兜底轮换（或同时插进来的刷新循环 / 自愈）就会替浏览器轮换它
        # 正在用的会话。
        if self._browser_pushes_in_flight or self.keepalive_mode == keepalive_modes.MODE_BROWSER:
            logger.debug("RotateCookies skipped: cookies are kept alive by the browser plugin")
            return RotationResult.STILL_VALID
        # 第二道闸口，同样对所有调用方生效（刷新循环、reload 兜底、池 / generate 的自愈）：会话已被
        # 打回登录页、谷歌又已经对这同一份 cookie 回过 401，再敲也是 401（线上一个死账号 37 小时敲了
        # 220+ 次），白敲谷歌还平添风控面。按失败返回：调用方不该接着当成「cookie 仍有效」去重取 token。
        if self._rotation_futile():
            logger.info(
                "RotateCookies skipped: Google already rejected these cookies (401) and the "
                "session is redirected to the login page; waiting for fresh cookies"
            )
            return RotationResult.FAILED
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
                if resp.status_code == 401:
                    # 谷歌明确拒绝了这份 cookie。只记下来、不置 auth_expired（以随后的 token 获取
                    # 结果为准）；两者同时成立时 _rotation_futile 才会挡住后续的轮换。
                    self._rotation_rejected_for = self._session_cookie_pair(cookies)
                live_metrics.record_rotation(False)
                return RotationResult.FAILED

            self._rotation_rejected_for = None
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

    def _public_model_names(self) -> list[str]:
        """对外暴露的公开模型名：3 个契约名恒在最前且顺序不变，再追加本账号真实拿到的新 family。

        为什么不把新名字直接写进 PUBLIC_MODELS：那样"一把 Argon 都没有的部署"也会在
        /v1/models 里看到一个调不通的选项。3 个契约名的存在性与顺序**不依赖任何运行时
        状态**，契约不破。
        """
        names = list(PUBLIC_MODELS)
        for family, internal in (self.__dict__.get("_family_model") or {}).items():
            if family in _BASE_FAMILIES:
                continue
            public = _FAMILY_PUBLIC.get(family) or internal
            if public not in names:
                names.append(public)
        return names

    def _adopt_discovered_models(self, entries: list, caps: set) -> dict[str, str]:
        """把心跳里"表外"的模型条目按白名单采纳，返回 {family: 内部名}。

        caps 必须恰好一个元素才允许采纳：账号档位不唯一说明心跳结构和我们的理解已经
        不一致了，这时候宁可什么都不采纳（照旧只打 WARNING），也不要拿一个猜来的
        capacity 去发请求 —— 错 capacity 的表现是"回答质量下降"，不报错。
        """
        if len(caps) != 1:
            return {}
        capacity = next(iter(caps))
        table = self.__dict__.setdefault("_discovered_models", {})
        out: dict[str, str] = {}
        # 上限按"**通过校验的**条数"计，不是对原始列表切片：切片的话，Google 在 Argon
        # 前面排进 8 个我们不认识的条目（实验性模型、缺字段的占位条目都算）就能把 Argon
        # 的发现彻底饿死 —— 日志里还看得到它被丢，功能却静默失效。
        for entry in entries:
            if len(out) >= _DISCOVER_MAX_PER_ROUND:
                break
            desc = _describe_discovered_model(entry, capacity)
            if desc is None:
                continue
            name, family = desc["name"], desc["family"]
            if family in out:
                continue
            if name not in table and len(table) >= _DISCOVER_MAX_TOTAL:
                logger.warning(
                    "Heartbeat model discovery capped: already holding %d models, "
                    "refusing to adopt %r (model_id=%s)", len(table), name, desc["info"]["id"],
                )
                break
            table[name] = desc["info"]
            out[family] = name
            logger.info(
                "Heartbeat model adopted: model_id=%s display_name=%r public=%s "
                "family=%s model_number=%s capacity=%s",
                desc["info"]["id"], desc["display_name"],
                _FAMILY_PUBLIC.get(family) or name, family,
                desc["info"]["model_number"], capacity,
            )
        return out

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
                    unknown: list = []
                    for entry in discovered:
                        mid = entry[0]
                        name = id_to_name.get(mid)
                        fam = GEMINI_MODELS.get(name or "", {}).get("family")
                        # 只有**基础** family 走写死表这条老路（逐字节不变）。
                        # 其余一律走自动发现：心跳带的 model_number / capacity 才是这个
                        # 账号此刻的真相，写死表那一行只是"心跳拿不到时"的兜底。
                        if name and fam in _BASE_FAMILIES:
                            family_model.setdefault(fam, name)
                            continue
                        unknown.append(entry)
                    # 认出来的那些模型的 capacity：既是下面同档补全的依据，也是"自动采纳"
                    # 唯一允许用的 capacity 来源（参考实现把 capacity 当账号级属性，
                    # 见 _describe_discovered_model 的 docstring）。
                    caps = {GEMINI_MODELS[n]["capacity"] for n in family_model.values()}
                    adopted = self._adopt_discovered_models(unknown, caps) if unknown else {}
                    family_model.update(adopted)
                    adopted_ids = {info["id"] for info in
                                   (self.__dict__.get("_discovered_models") or {}).values()}
                    for entry in unknown:
                        mid = entry[0]
                        if mid in adopted_ids:
                            continue   # 已被采纳，不是"被丢掉的条目"
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
                            "Heartbeat model entry dropped "
                            "(unknown model id, or discovery validation failed): "
                            f"model_id={mid} display_name={_entry_display_name(entry)!r} "
                            f"model_number={_entry_model_number(entry)!r} "
                            f"field4={_entry_field(entry, 4)!r}"
                        )
                    if family_model:
                        # 按同 capacity 等级补全本轮心跳里缺失的基础 family
                        # （心跳没给到某个基础 family 的条目时，只能按同档补）。
                        # ⚠️ 只补这几个基础 family：不加这个限制的话，任何 capacity=2 的
                        # 账号（真实账号正是 cap 2）都会被自动补上 family_model["argon"]，
                        # 哪怕它的心跳里根本没有 Argon 条目 —— 然后把 Argon 的 id 发给
                        # Google，症状是偶发空回复/4xx，且只在多账号池里出现。
                        for name, info in GEMINI_MODELS.items():
                            if info["family"] not in _BASE_FAMILIES:
                                continue
                            if info["capacity"] in caps:
                                family_model.setdefault(info["family"], name)
                        # 非契约 family 按"本轮发现到的"整体替换，不做累加：update 的话
                        # 账号失去的模型会永远留在 /v1/models 里、还继续可路由 —— 上一轮
                        # 发现了 Argon、这一轮 Google 收回，用户看到的就是一个"列表里有、
                        # 调起来坏"的模型，直到进程重启。契约 family 不参与清理：
                        # 它们的存在性与顺序不依赖任何运行时状态（见 _public_model_names）。
                        for fam in [f for f in self._family_model
                                    if f not in _BASE_FAMILIES and f not in family_model]:
                            removed = self._family_model.pop(fam)
                            logger.info(
                                "Heartbeat no longer reports family %s (was %s); "
                                "dropping it from the public model list", fam, removed,
                            )
                        self._family_model.update(family_model)
                        self._available_models = self._public_model_names()
                        logger.info(
                            f"Account models resolved: {family_model} "
                            f"-> public {self._available_models}"
                        )
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
                if self._rotation_futile():
                    # 会话已被打回登录页，且谷歌已对这同一份 cookie 回过 401：死会话换 PSIDTS 也是
                    # 401（线上一个死账号 37 小时敲了 220+ 次），白敲谷歌还平添风控面。只做下面的
                    # token 探测：瞬时故障能自己恢复；换上好 cookie（reload_cookies 成功）也会清掉
                    # 判定，下一轮恢复轮换。只是被打回登录页、谷歌还没拒绝过的会话照旧轮换（见
                    # _rotation_futile：PSIDTS 过期的会话往往一次轮换就能救回来）。
                    logger.info(
                        "Auto-refresh: session expired (login redirect) and Google already "
                        "rejected these cookies; skipping RotateCookies, probing the token only"
                    )
                else:
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
        # 续接：第 2 格放 [cid, rid, rcid] 列表（缺的位置 None）；新会话 / 坏值放 null，与改动前
        # 逐字节一致。绝不放字符串（见 parse_conversation_metadata）。
        conv_param = parse_conversation_metadata(conversation_id)
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
        mn = _model_number(model, self._model_table(), self.__dict__.get("_family_model"))
        uuid_val = str(uuid.uuid4()).upper()
        conv_meta = parse_conversation_metadata(conversation_id)
        inner: list = [None] * 81
        inner[0] = message_content
        inner[1] = ["en"]
        # 续接时第 2 格放 [cid, rid, rcid]（参考实现 refs/gemini-web-to-api gemini_service.go 的
        # generateContent：同一种 81 格 payload，metadata 非空就覆盖 inner[2]）；新会话保持原来的
        # DEFAULT_METADATA，逐字节不变。过去这里不管传什么都发 DEFAULT_METADATA —— 思考路径
        # （默认档上线后几乎所有请求）根本没在续接。
        inner[2] = conv_meta if conv_meta else DEFAULT_METADATA
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
        if resolved not in self._model_table():
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(self._available_models or PUBLIC_MODELS)}"
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
        if resolved not in self._model_table():
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(self._available_models or PUBLIC_MODELS)}"
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
            model_headers = _build_model_header_thinking(resolved, self._session_uuid, level,
                                                         self._model_table())
        else:
            encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids, gem_id)
            model_headers = _build_model_header(resolved, self._model_table())
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
        last_canvases: list = []  # Canvas 只出现在部分帧，保留最新非空（同 last_images）
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
                            cvs = self._canvases_from_wrb(elem)
                            if cvs:
                                _warn_if_canvas_list_shrank(last_canvases, cvs)
                                last_canvases = cvs
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

        yield await self._finalize_stream(last_text, last_conv, last_images, last_thoughts,
                                          last_canvases)

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

    def _canvases_from_wrb(self, elem: list) -> list:
        """从单个 wrb.fr 帧提取 Canvas 条目（复用 _extract_canvases）。

        刻意不改 _extract_text_from_wrb 的三元组签名：那个函数有既有调用点与测试，
        为了多带一格把签名改掉不划算。
        """
        try:
            if not isinstance(elem, list) or len(elem) < 3 or elem[0] != "wrb.fr":
                return []
            payload = json.loads(elem[2]) if isinstance(elem[2], str) else None
            if not isinstance(payload, list) or len(payload) < 5:
                return []
            cands = payload[4]
            if not isinstance(cands, list) or not cands:
                return []
            return _extract_canvases(cands[0])
        except Exception:
            return []

    async def _finalize_stream(self, text: str, conv_id: str, images: list, thoughts: str = "",
                               canvases: list | None = None) -> dict:
        """流式收尾：下载/存生成图、过滤占位 URL，组装与 _send_request 一致的 final 结果。
        thoughts 增量已由 generate_stream 循环内逐帧 yield（`{"type": "thoughts"}` 事件）；
        这里的 thoughts 是完整累积思维链，作为收尾兜底一次性带上（防漏发/防中途断连丢失）。
        """
        result_images: list = []
        # Canvas 还原 + 控制标记清理必须在剥生图占位**之前**跑，且与 _parse_output
        # 共用同一个 _restore_body —— 两条路径对同一段正文必须逐字节一致。
        text, thoughts = _restore_body(text, canvases, thoughts)
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
        # generate() 入口有这道闸门，_send_request 过去没有 —— 而 _send_request 是
        # 真流式之外另一条直接发请求的路。认不出的模型名在这里不报错的话，
        # _build_model_header 返回 {}、下面的 `if model_headers:` 跳过，请求就**不带
        # 模型头**发出，Google 用账号默认模型回答，客户端拿到的是另一个模型的答案却
        # 毫无感知。宁可 400，不要静默换模型。
        if resolved not in self._model_table():
            raise ValueError(
                f"Model '{model}' unavailable. "
                f"Options: {', '.join(self._available_models or PUBLIC_MODELS)}"
            )
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
            model_headers = _build_model_header_thinking(resolved, self._session_uuid, level,
                                                         self._model_table())
        else:
            encoded = self._encode_payload(prompt, resolved, conversation_id, file_ids, gem_id)
            model_headers = _build_model_header(resolved, self._model_table())
        form_data = {"at": self._session_token, "f.req": encoded}
        headers = self._get_headers("POST", content_type="application/x-www-form-urlencoded")
        if model_headers:
            headers.update(model_headers)
        if extended_thinking:
            headers["x-goog-ext-525005358-jspb"] = f'["{uuid_val}",1]'

        gen_timeout = _generate_timeout(resolved, prompt, self._model_table())
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
        conv_meta = None
        images: list[dict] = []
        canvases: list[dict] = []

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
                # Canvas 同理：参考实现注释明说 Canvas 只出现在部分帧、最后一帧常常
                # 只有文本，所以必须"保留最新非空"而不是每帧覆盖。
                cvs = _extract_canvases(candidate)
                if cvs:
                    _warn_if_canvas_list_shrank(canvases, cvs)
                    canvases = cvs
                meta = _response_conversation_metadata(payload)
                if meta:
                    conv_meta = meta

        # 生图/找图时模型文本里会带 googleusercontent 占位 URL（无实际意义，真图在 images 里；
        # image_retrieval/image_collection 是检索占位客户端访问无效），无条件过滤，避免显示成网址。
        # 与真流式收尾（_finalize_stream）共用同一套口径。
        # Canvas 还原 + 控制标记清理（与真流式收尾共用 _restore_body），再剥生图占位
        text_content, thoughts_content = _restore_body(text_content, canvases, thoughts_content)
        text_content = _strip_image_placeholders(text_content, images)

        return {"text": text_content, "conversation_id": encode_conversation_metadata(conv_meta),
                "images": images, "thoughts": thoughts_content}

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

    def _restore_session_state(self, prev: tuple, *, cookies_changed: bool = False) -> None:
        """把会话状态回滚到 reload_cookies 调用前（调用前是健康的，或者这次推来了新 cookie）。

        只还原 _healthy 是不够的：函数开头会清空 _session_token 并把新 Cookie 写进 jar，
        一个"健康但没有 SNlM0e token / 拿着别人 Cookie"的 client 会被池照常派活、然后每个
        请求都失败，3 次就被标 EXPIRED —— 比不还原更糟。所以整组状态一起回滚。
        auth_expired 与「谷歌拒绝过哪份 cookie」同理：失败的 reload 拿死 cookie 取 token、兜底
        轮换时会改写它们，不还原的话一个好好的会话会被当成「已被打回登录页」，或者旧 cookie 的
        拒绝记录被新 cookie 的顶掉、刷新循环拿旧 cookie 再白敲一次 401。

        调用前就不健康时：推来了新 cookie（cookies_changed）却没换上，同样回到原来那份 cookie，
        账号仍不健康 —— 推送失败不留痕。否则 client 会留着这份没验证过的新 PSID：保活方式按
        client 当前 PSID 查，一个浏览器保活的账号会因为一次失败的推送变回 server，之后池自愈 /
        刷新循环就会对浏览器正在用的新 PSID 调 RotateCookies（复审发现的双方轮换漏洞）。不带新
        cookie 的自愈失败则不回滚：兜底轮换若刚换来新 PSIDTS，那是谷歌刚签发的，旧值已被替换。
        """
        psid, psidts, session_token, was_healthy, auth_expired, rotation_rejected_for = prev
        if not was_healthy and not cookies_changed:
            return
        self._psid = psid
        self._psidts = psidts
        self._session_token = session_token
        self._healthy = was_healthy
        self._auth_expired = auth_expired
        self._rotation_rejected_for = rotation_rejected_for
        if self._cookie_jar is not None:
            self._cookie_jar.set("__Secure-1PSID", psid)
            if psidts:
                self._cookie_jar.set("__Secure-1PSIDTS", psidts)
        if was_healthy:
            logger.warning("Cookie reload failed; restored the previous working session")
        else:
            logger.warning("Cookie reload failed; kept the previous cookies (account stays unhealthy)")

    async def reload_cookies(self, psid: str | None = None, psidts: str | None = None, *,
                             keepalive_mode: str | None = None) -> dict:
        """换上 cookie 并重新取会话：要么换上新会话，要么原样不动（见 _restore_session_state）。

        keepalive_mode：这份 cookie 由谁保活，admin 接口按请求来源算好传进来（keepalive_modes.
        mode_from_headers）。browser 时，这次 reload 进行期间 _rotate_cookies 一律不轮换 —— 新 PSID
        的记录要等 reload 成功后才写，不传进来的话闸口会按默认 server 放行，reload 自己的兜底轮换
        就会拿浏览器正在用的 PSIDTS 调 RotateCookies、把浏览器顶下线。自愈等内部调用不传。
        """
        if keepalive_mode != keepalive_modes.MODE_BROWSER:
            return await self._reload_cookies(psid, psidts)
        self._browser_pushes_in_flight += 1
        try:
            return await self._reload_cookies(psid, psidts)
        finally:
            self._browser_pushes_in_flight -= 1

    async def _reload_cookies(self, psid: str | None, psidts: str | None) -> dict:
        # F4（issue #11）：先快照重载前的会话状态。reload 的语义应是"要么换上新会话、
        # 要么原样不动"：旧实现在任何网络操作之前就无条件 self._healthy = False，失败返回
        # 路径却从不恢复，于是一次失败的刷新（面板误填 cookie、Google 临时 5xx、多账号池里
        # /reload-cookies 拿同一份 cookie 挨个试）就把一个本来健康的 client 永久拉黑。
        prev_state = (
            self._psid, self._psidts, self._session_token, self._healthy, self._auth_expired,
            self._rotation_rejected_for,
        )

        if psid:
            self._psid = psid.strip().strip('"').strip("'").rstrip(";")
        if psidts:
            self._psidts = psidts.strip().strip('"').strip("'").rstrip(";")
        # 这次是不是推来了另一份 cookie（失败时据此决定要不要回到原来那份，见 _restore_session_state）
        cookies_changed = (self._psid, self._psidts) != prev_state[:2]

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
                self._auth_expired = False
                self._rotation_rejected_for = None
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
                    self._auth_expired = False
                    self._rotation_rejected_for = None
                    self._ensure_refresh_task()
                    logger.info("Cookies reloaded after rotation")
                    return {"success": True}

            error_msg = self._last_reload_error or first_error
            logger.error(f"Cookie reload failed: {error_msg}")
            self._restore_session_state(prev_state, cookies_changed=cookies_changed)
            return {"success": False, "error": error_msg}
        except Exception:
            # 已经换上新会话之后才炸的（如 _send_heartbeat 抛错）不回滚，新会话是好的
            if not self._healthy:
                self._restore_session_state(prev_state, cookies_changed=cookies_changed)
            raise

    def _ensure_refresh_task(self):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
            logger.info("Auto-refresh loop started")


gemini_client = GeminiWebClient()
