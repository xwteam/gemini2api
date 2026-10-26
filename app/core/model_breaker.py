"""模型级熔断（v1.6.46 规格 C，按 I 节的预审裁定细化）。

背景（北京 2026-10-26，中转站三账号）：gemini-flash 谷歌侧至少两段故障，三个账号都中招，同账号同
格式的 flash-lite / pro 正常。表现要么是排队卡住（+60 秒才回响应头、之后每 60 秒一个空心跳帧），要么
是 1.2 秒就回一句固定的失败套话。单个请求里「60 秒没内容」分不清是卡住还是正常的慢思考（第 0 节
第 3 条），所以不能提前掐断单个请求 —— 但同一族上不同请求接连「疑似故障」地失败，就足以说明这个
族此刻整体不行了。这时带第三方兜底的请求不该每次先白等一个预算。

每个模型族（flash / flash-lite / pro / argon / 心跳发现的其它族）一个状态机，进程内全局、不持久化：

  closed     计数：窗口内「疑似故障」失败的**不同请求**个数（I.3：同一请求的换号、思考重试、续接失败后
             改发完整历史、客户端重发都只 +1，指纹见 request_fingerprint / same_request_as）。距上一次
             计入的失败超过 WINDOW 才从 1 重新计 —— 按「这次失败尝试的开始时刻」判断（I.2：失败要满一个
             预算才记得下来，pro 的预算 300 秒 = 默认窗口，按记下的时刻判，pro 在顺序流量下永远凑不齐
             两次）。够 THRESHOLD → open。
  open       开放期内 should_bypass 为真：开了兜底的 /v1/chat/completions 请求直接走兜底。期间记到的
             失败只更新 last_reason / last_failure_at（不续期、不翻倍）。到期转 half_open。
  half_open  放行恰好一个探测请求（第一个调用者占住探测位，其它调用者照样绕开）。这一轮里第一个计入的
             失败 → 重新 open、开放期翻倍（封顶 MAX_COOLDOWN）；结果不计入（4xx、池满、被取消……）→
             调用方释放探测位、仍是 half_open，下一个请求接着探测。

任何（不过期的）成功 → closed，计数清零、开放期复位。「过期」（I.6）：open / half_open 只接受熔断最近
一次打开之后才开始的尝试的结果（故障前就在流的长回答结束时不能把熔断关掉）；closed 下只有最近一次
计入失败之后才开始的尝试成功才清零计数。所以记录接口都带尝试的开始时刻。

探测位用票据 + epoch（I.5）：每次状态转换 epoch+1 并清空探测位；release 只在同一个 half_open epoch
里、探测位仍被这张票据占着时才生效（慢探测不会把下一轮的探测位放掉）。探测位占用超过调用方给的时限
（该请求实际预算 + acquire_timeout + 30 秒）视为已放弃、自动释放（防泄漏）。should_bypass / record_* /
snapshot 都先做 open→half_open 的惰性转换。整个接口是同步的：检查和占位之间没有 await。

MODEL_BREAKER_ENABLED=false：照常记录（状态与日志可看），但 should_bypass 恒假、不占探测位，状态里
enabled=false（面板据此不显示「绕开」横幅）。配置每次调用现读 settings（I.12）。
"""

import hashlib
import itertools
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, NamedTuple

from app.config import MODEL_BREAKER_DEFAULTS, coerce_model_breaker_value, settings

logger = logging.getLogger(__name__)

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


class BreakerConfig(NamedTuple):
    enabled: bool
    threshold: int
    window: float
    cooldown: float
    max_cooldown: float


@dataclass(frozen=True)
class BreakerTicket:
    """should_bypass 的结果。bypass=真：这次请求直接走兜底；is_probe=真：这次请求是探测，谷歌调用一
    结束（兜底开始之前）就要 release。token 区分同一 epoch 里先后占过探测位的不同请求。"""

    family: str | None
    bypass: bool = False
    is_probe: bool = False
    epoch: int = 0
    token: int = 0


def request_fingerprint(prompt: str, conversation_id: str = "") -> str:
    """一次请求的指纹（I.3）：sha256(prompt + "\\0" + conversation_id) 截断。只在内存里比对，不进日志。

    surrogatepass：JSON 里的孤立代理码（"\\ud800"）解出来是合法的 Python str，却编不成严格 UTF-8。
    """
    raw = f"{prompt or ''}\0{conversation_id or ''}".encode("utf-8", "surrogatepass")
    return hashlib.sha256(raw).hexdigest()[:16]


# 路由对同一个客户端请求的「改写重试」—— 续接失败后改发完整历史（openai.py 的非流式 / buffered /
# 真流式三处）—— prompt 与 conversation_id 都变了，按公式是另一个指纹：一个请求就能凑够默认阈值 2、
# 自己把熔断打开（之后一个开放期里开了兜底的请求全被送去第三方）。所以这类重试在 same_request_as
# 里发，池记失败时沿用第一次尝试的指纹。用 ContextVar 而不是给池加参数：池、
# generate_with_thinking_fallback 与所有测试替身的签名都不用动。路由的重试多半包成 task 跑（保活），
# task 建立时复制当时的上下文 —— task 要建在块里面，块结束之后它照样带着这个指纹。
_SAME_REQUEST: ContextVar[str | None] = ContextVar("model_breaker_same_request", default=None)


@contextmanager
def same_request_as(prompt: str, conversation_id: str = ""):
    """块里（含块里建的 task）发出的上游尝试，熔断一律按 (prompt, conversation_id) 那次尝试的指纹计数。"""
    token = _SAME_REQUEST.set(request_fingerprint(prompt, conversation_id))
    try:
        yield
    finally:
        _SAME_REQUEST.reset(token)


def attempt_fingerprint(prompt: str, conversation_id: str = "") -> str:
    """池记失败时用的指纹：在 same_request_as 里就是那次尝试的，否则按公式现算。"""
    return _SAME_REQUEST.get() or request_fingerprint(prompt, conversation_id)


def family_label(family: str) -> str:
    """日志里给人看的族名：gemini-flash / gemini-flash-lite / gemini-argon……"""
    return family if family.startswith("gemini-") else f"gemini-{family}"


@dataclass
class _Family:
    state: str = STATE_CLOSED
    epoch: int = 0
    fingerprints: set = field(default_factory=set)   # 当前窗口里已计数的不同请求
    last_counted_at: float | None = None             # 最近一次计入（计数 +1）的失败记下的时刻
    opened_at: float | None = None                   # 最近一次打开的时刻
    open_until: float = 0.0
    cooldown: float = 0.0                            # 本次（或下一次）开放期的长度
    probe_token: int | None = None
    probe_since: float = 0.0
    probe_timeout: float = 0.0
    last_reason: str = ""
    last_failure_at: datetime | None = None          # 墙钟 UTC（展示用，与单调钟分开）


class ModelBreaker:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] | None = None,
                 config: Callable[[], BreakerConfig] | None = None):
        self._clock = clock
        self._wall = wall_clock or (lambda: datetime.now(timezone.utc))
        self._config_source = config
        self._families: dict[str, _Family] = {}
        self._tokens = itertools.count(1)

    # -- 时钟与配置 -----------------------------------------------------------------

    def now(self) -> float:
        """熔断器自己的单调钟。记录接口的 started_at 必须用它取（池在每次尝试开始时取一次）。"""
        return self._clock()

    def _config(self) -> BreakerConfig:
        if self._config_source is not None:
            return self._config_source()
        # 每次现读 settings；运行时塞进来的值不经过启动校验器，这里用同一份口径兜住
        vals = {name: coerce_model_breaker_value(name, getattr(settings, name, default))[0]
                for name, default in MODEL_BREAKER_DEFAULTS.items()}
        cooldown = vals["model_breaker_cooldown"]
        return BreakerConfig(
            enabled=vals["model_breaker_enabled"],
            threshold=vals["model_breaker_threshold"],
            window=vals["model_breaker_window"],
            cooldown=cooldown,
            max_cooldown=max(vals["model_breaker_max_cooldown"], cooldown),
        )

    def reset(self) -> None:
        """清空全部状态（测试用；进程重启本来就是清空）。"""
        self._families.clear()

    # -- 状态转换 -------------------------------------------------------------------

    def _transition(self, st: _Family, state: str) -> None:
        st.state = state
        st.epoch += 1
        st.probe_token = None

    def _lazy(self, family: str, st: _Family, now: float) -> None:
        """open 到期 → half_open；half_open 里占得太久的探测位视为已放弃、收回。"""
        if st.state == STATE_OPEN and now >= st.open_until:
            self._transition(st, STATE_HALF_OPEN)
            logger.info(f"[breaker] {family_label(family)} 开放期已到，下一个请求去试探谷歌")
        if st.state == STATE_HALF_OPEN and st.probe_token is not None \
                and now - st.probe_since > st.probe_timeout:
            logger.warning(f"[breaker] {family_label(family)} 的探测请求占位 "
                           f"{now - st.probe_since:.0f}s 仍没有结果，视为已放弃，让下一个请求接着探测")
            st.probe_token = None

    def _open(self, family: str, st: _Family, now: float, cooldown: float, cfg: BreakerConfig,
              reason: str) -> None:
        self._transition(st, STATE_OPEN)
        st.cooldown = cooldown
        st.opened_at = now
        st.open_until = now + cooldown
        if cfg.enabled:
            logger.warning(
                f"[breaker] {family_label(family)} 谷歌侧故障中（最近一次：{reason}）：熔断打开 "
                f"{cooldown:.0f}s，开了兜底的 /v1/chat/completions 请求暂时直接走兜底"
            )
        else:
            logger.warning(
                f"[breaker] {family_label(family)} 谷歌侧故障中（最近一次：{reason}）：按规则本该熔断 "
                f"{cooldown:.0f}s，但 MODEL_BREAKER_ENABLED=false，只记录、照常调谷歌"
            )

    def _close(self, family: str, st: _Family, cfg: BreakerConfig) -> None:
        was = st.state
        self._transition(st, STATE_CLOSED)
        st.fingerprints = set()
        st.last_counted_at = None
        st.opened_at = None
        st.open_until = 0.0
        st.cooldown = cfg.cooldown
        logger.info(f"[breaker] {family_label(family)} 谷歌已恢复（{was} → closed），请求照常调谷歌")

    # -- 对外接口（全部同步，检查与占位之间没有 await） ------------------------------------

    def should_bypass(self, family: str | None, *, probe_timeout: float) -> BreakerTicket:
        """这个族此刻要不要绕开谷歌。half_open 时第一个调用者拿到探测票据（bypass=假、is_probe=真）。

        probe_timeout：探测位的兜底时限（调用方传入：该请求实际预算 + acquire_timeout + 30 秒）。
        """
        if not family:
            return BreakerTicket(None)
        cfg = self._config()
        st = self._families.get(family)
        if st is None:
            return BreakerTicket(family)
        now = self._clock()
        self._lazy(family, st, now)
        if not cfg.enabled:
            return BreakerTicket(family, epoch=st.epoch)
        if st.state == STATE_OPEN:
            return BreakerTicket(family, bypass=True, epoch=st.epoch)
        if st.state == STATE_HALF_OPEN:
            if st.probe_token is None:
                token = next(self._tokens)
                st.probe_token = token
                st.probe_since = now
                st.probe_timeout = float(probe_timeout)
                return BreakerTicket(family, is_probe=True, epoch=st.epoch, token=token)
            return BreakerTicket(family, bypass=True, epoch=st.epoch)
        return BreakerTicket(family, epoch=st.epoch)

    def release(self, ticket: BreakerTicket | None) -> None:
        """探测请求的谷歌调用结束了：释放探测位。只在同一个 half_open epoch、探测位仍被这张票据占着时生效。"""
        if ticket is None or not ticket.is_probe or not ticket.family:
            return
        st = self._families.get(ticket.family)
        if st is not None and st.state == STATE_HALF_OPEN and st.epoch == ticket.epoch \
                and st.probe_token == ticket.token:
            st.probe_token = None

    def record_failure(self, family: str | None, *, started_at: float, fingerprint: str,
                       reason: str) -> None:
        """一次计入熔断的失败（调用方已经按 I.4 筛过：只有「疑似故障」才调这里）。

        started_at：这次上游尝试开始的时刻（now() 取的）；fingerprint：request_fingerprint；
        reason：固定的安全摘要（异常类型 + 状态码，不含上游原文）。
        """
        if not family:
            return
        cfg = self._config()
        now = self._clock()
        st = self._families.get(family)
        if st is None:
            st = self._families[family] = _Family(cooldown=cfg.cooldown)
        self._lazy(family, st, now)
        st.last_reason = reason
        st.last_failure_at = self._wall()

        if st.state == STATE_OPEN:
            logger.info(f"[breaker] {family_label(family)} 熔断中又一次失败（{reason}），只记原因")
            return
        if st.state == STATE_HALF_OPEN:
            if st.opened_at is not None and started_at < st.opened_at:
                logger.info(f"[breaker] {family_label(family)} 收到熔断打开之前就开始的尝试的失败"
                            f"（{reason}），不算这一轮的探测结果")
                return
            # 这一轮里第一个计入的失败：重开、翻倍（之后同一轮的失败看到的已经是 open）
            self._open(family, st, now, min(st.cooldown * 2, cfg.max_cooldown), cfg, reason)
            return

        if st.last_counted_at is None or started_at - st.last_counted_at > cfg.window:
            st.fingerprints = set()
        if fingerprint in st.fingerprints:
            logger.info(f"[breaker] {family_label(family)} 同一请求又失败一次（{reason}），不重复计数"
                        f"（{len(st.fingerprints)}/{cfg.threshold}）")
            return
        st.fingerprints.add(fingerprint)
        st.last_counted_at = now
        logger.info(f"[breaker] {family_label(family)} 计入一次疑似故障（{reason}）："
                    f"窗口内 {len(st.fingerprints)}/{cfg.threshold} 个不同请求")
        if len(st.fingerprints) >= cfg.threshold:
            self._open(family, st, now, cfg.cooldown, cfg, reason)

    def record_success(self, family: str | None, *, started_at: float) -> None:
        """一次上游尝试拿到了正文 / 思考 / 图片。没有状态的族不建状态。"""
        if not family:
            return
        st = self._families.get(family)
        if st is None:
            return
        cfg = self._config()
        now = self._clock()
        self._lazy(family, st, now)
        if st.state in (STATE_OPEN, STATE_HALF_OPEN):
            if st.opened_at is not None and started_at < st.opened_at:
                return          # 过期成功：熔断打开之前就开始的尝试
            self._close(family, st, cfg)
            return
        if st.fingerprints and (st.last_counted_at is None or started_at >= st.last_counted_at):
            st.fingerprints = set()
            st.last_counted_at = None

    def snapshot(self) -> dict:
        """/admin/status 的 model_breakers：每个有过状态的族一项。时间字段是墙钟 UTC isoformat。"""
        cfg = self._config()
        now = self._clock()
        wall = self._wall()
        out: dict = {}
        for family in sorted(self._families):
            st = self._families[family]
            self._lazy(family, st, now)
            remaining = max(0.0, st.open_until - now) if st.state == STATE_OPEN else 0.0
            out[family] = {
                "state": st.state,
                "enabled": cfg.enabled,
                "consecutive_failures": len(st.fingerprints),
                "open_remaining_seconds": round(remaining, 1),
                # open 时给绝对时间（面板显示「几点几分再试谷歌」，不是打开页面那一刻的倒计时快照）
                "retry_at": (wall + timedelta(seconds=remaining)).isoformat()
                if st.state == STATE_OPEN else None,
                "cooldown_seconds": st.cooldown or cfg.cooldown,
                "probe_in_flight": st.state == STATE_HALF_OPEN and st.probe_token is not None,
                "last_reason": st.last_reason,
                "last_failure_at": st.last_failure_at.isoformat() if st.last_failure_at else None,
            }
        return out


model_breaker = ModelBreaker()
