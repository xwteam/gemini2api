import json
import time
import asyncio
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.gemini_client import (
    GeminiFailureReply, GeminiWebClient, GenerationStalled, GenerationTimedOut, HTTPStatusError,
    NO_HEALTHY_ACCOUNT_MSG, BOUND_ACCOUNT_UNAVAILABLE_MSG, PinnedAccountUnavailable,
    is_timeout_error, model_family,
)
from app.core import keepalive_modes
from app.core.model_breaker import attempt_fingerprint, model_breaker
from app.core.access_context import current_bound_account_ids
from app.core.fallback import is_empty_result
from app.config import settings
from app.core.usage_metrics import live_metrics
from app.utils.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

# 自愈（reload_cookies）失败后的冷却秒数（issue #11 F2）。账号真的死了（cookie 被 Google
# 吊销、要人工换号）时，避免每个请求都去打一次 RotateCookies —— 既拖慢每个请求，
# 又平白抬高对 Google 的敲门频率（风控面）。
HEAL_RETRY_COOLDOWN = 60.0

# healing 单飞标志的陈旧阈值（issue #11 H1 belt-and-braces）。reload_cookies 是 60s 级
# 网络 I/O，正常情况下这个标志活不过那么久；万一某条路径（未来的新 bug）没能在结束时
# 清掉它，超过这个阈值就当陈旧、可回收 —— 双保险，绝不指望它成为常态触发路径。
HEALING_STALE_SECONDS = 120.0

# EXPIRED 账号恢复探测（check_account）的冷却秒数。只在「访问密钥绑定了账号」的请求上
# 生效：那种请求在池里别的账号都健康时也会走到恢复分支，没有冷却就等于每个请求一次
# 持锁网络 I/O —— 把别的租户（含 .env API_KEY 的请求）一起卡住，还对 Google 形成
# 逐请求的敲门风暴。无绑定的请求只有在"一个 ACTIVE 账号都没有"时才会走到那里，
# 行为保持改动前原样（见 _try_recover_expired）。
EXPIRED_RECOVER_COOLDOWN = 60.0

# 连续多少次空响应才允许在面板的 Errors 上留痕（issue #11）。单次空响应太常见
# （内容拒答、被安全策略拦下），不足以说明账号坏了，所以单次绝不降级账号。
EMPTY_STREAK_THRESHOLD = 3

# 非流式生成超时只在这次尝试几乎没收到数据时才算模型熔断的「疑似故障」（规格 I.4）。实测卡住时
# 收到的是 39～184 字节（响应头 + 一两个空心跳帧）；一个正常的长回答超过预算时早已收到成 KB 的正文。
BREAKER_TIMEOUT_MAX_BYTES = 1024


def _breaker_counts(exc: Exception) -> bool:
    """这次上游尝试的失败算不算模型族的「疑似故障」（熔断计数，规格 C.2 + I.4）。

    算：谷歌的失败套话；几乎没收到数据（< 1KB，解析不出字节数时照旧算）的非流式生成超时；一次进展都
    没有的流式无进展超时。不算：建连期超时重试用完（网络问题）、谷歌的拒绝块、4xx / 401 / 403、
    其它 5xx、池满、客户端断连、钉住的账号不可用、空响应 —— 以及「输出过内容之后才卡住」的超时：
    单个请求的超时分不清是卡住还是正常的慢回答（第 0 节第 3 条），两个正常的长回答不能误开熔断。
    """
    if isinstance(exc, GeminiFailureReply):
        return True
    if isinstance(exc, GenerationStalled):
        return not exc.progressed
    if isinstance(exc, GenerationTimedOut):
        received = getattr(exc, "bytes_received", None)
        return received is None or received < BREAKER_TIMEOUT_MAX_BYTES
    return False


def _is_5xx(exc: Exception) -> bool:
    """判断异常是否为 5xx（含 Google 503 限流），这类可换账号 failover 重试。"""
    return isinstance(exc, HTTPStatusError) and 500 <= exc.status_code < 600


def _is_retryable(exc: Exception) -> bool:
    """可换账号 failover 重试的错误集合（Issue#1-A）：
    - 5xx（含 Google 503 限流）：冷却该账号后换号
    - RuntimeError 且含 "not ready"：客户端会话未就绪，换健康账号
    - HTTPStatusError 401/403：凭据失效，换号并标记 EXPIRED
    """
    if _is_5xx(exc):
        return True
    if isinstance(exc, RuntimeError) and "not ready" in str(exc).lower():
        return True
    if isinstance(exc, HTTPStatusError) and exc.status_code in (401, 403):
        return True
    return False


def _is_empty_generation(result) -> bool:
    """这一次生成是不是「上游 200 但什么都没产出」。

    在 is_empty_result()（fallback 的口径：无 text 且无 images）之上多放过一种情况：
    只有思考链、没有正文。那种回复上游确实生成了东西、会话是活的，用户勾了 thinking
    时也确实会出现，不该记进空响应计数器 —— 这个计数器宁可漏报也不能误伤。
    is_empty_result() 本身一个字都不改：它还被 fallback 判定复用，口径不能动。
    """
    if not is_empty_result(result):
        return False
    return not (isinstance(result, dict) and (result.get("thoughts") or "").strip())


def _with_account_id(result, account: "Account"):
    """生成结果（非流式结果 / 流式 final 事件）带上实际服务的账号 id。

    多轮续接要把会话钉回这个账号（会话 id 是账号私有的）。拷一份再加，不改 client 给的原对象。
    """
    if isinstance(result, dict):
        return {**result, "account_id": account.id}
    return result


def _pinned_unavailable(account_id: str, gem_id) -> PinnedAccountUnavailable:
    """钉住的账号拿不到时的报错（generate / generate_stream 共用）。

    Gem 钉号的文案逐字不变；多轮续接钉回会话账号（没有 gem_id）时不再写成 "gem"，免得运维去查 Gem。
    """
    kind = "gem account" if gem_id else "account"
    return PinnedAccountUnavailable(
        f"Pinned {kind} '{account_id}' unavailable (expired/busy/cooldown)"
    )


def _error_summary(exc: Exception) -> str:
    """把异常压成「异常类型 + HTTP 状态码」的安全摘要，供 Account.last_error 存放。

    刻意丢掉 str(exc) 原文，理由是这个字段会经 /admin/status、/admin/accounts 原样返回
    并渲染进管理面板，而 admin.py 的 _masked_status() 只掩码 psid 一个键，响应层不会兜底：
    - HTTPStatusError 的消息里嵌着 Google 响应正文的前 200 字节（见 gemini_client），
      可能带登录态标识 / SNlM0e token / 账号邮箱；
    - ValueError（模型不可用）的消息里嵌着客户端可控的 model 名，会变成面板的存储型 XSS 入口。
    异常类型 + 状态码已经足够分辨"是限流、是凭据失效、还是客户端没就绪"，
    比现在完全空白的 last_error 强，且零泄露风险。
    """
    if isinstance(exc, HTTPStatusError):
        return f"{type(exc).__name__} (HTTP {exc.status_code})"
    return type(exc).__name__


class AccountStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"
    REFRESHING = "refreshing"


class RotationStrategy(str, Enum):
    ROUND_ROBIN = "round-robin"
    FAILOVER = "failover"


@dataclass
class Account:
    id: str
    psid: str
    psidts: str
    label: str = ""
    status: AccountStatus = AccountStatus.ACTIVE
    request_count: int = 0
    error_count: int = 0
    consecutive_failures: int = 0
    active_requests: int = 0
    last_used: datetime | None = None
    # 最近一次「真的吐出了内容」的时间。刻意与 last_used（派活时间）分开：cookie 死透的
    # 账号每来一个请求 last_used 都会刷新，面板照样一片绿，issue #11 的截图就毁在这上面。
    last_success_at: datetime | None = None
    # 最近一次失败的安全摘要（见 _error_summary：只留异常类型 + HTTP 状态码，不留原文）
    last_error: str = ""
    last_error_at: datetime | None = None
    # 空响应（上游 HTTP 200 却解析不出任何内容）计数。issue #11：这类响应过去被
    # release(success=True) 当成成功，Errors 纹丝不动、consecutive_failures 还被清零，
    # 于是"每次都吐空"的账号在面板上完全看不出来。
    consecutive_empty: int = 0
    empty_count: int = 0
    # 被 5xx/503 限流后的冷却截止时间戳（loop.time()）；冷却期内不优先选，但不算 expired
    cooldown_until: float = 0.0
    # 会话自愈（reload_cookies）的单飞标志：为真表示已有请求在锁外跑自愈，其余并发请求
    # 不再重复触发（issue #11 F2）
    healing: bool = False
    # healing 置为 True 时的 loop.time() 时间戳，供 _pick_heal_candidate() 做陈旧回收
    # 判断（issue #11 H1 belt-and-braces）
    healing_started_at: float = 0.0
    # 自愈失败后的冷却截止时间戳（loop.time()）；冷却期内不再触发自愈
    heal_cooldown_until: float = 0.0
    # EXPIRED 恢复探测失败后的冷却截止时间戳（loop.time()）；只有绑定账号的请求会读它
    recover_cooldown_until: float = 0.0
    # EXPIRED 恢复探测的单飞标志（照 healing 的样子：锁外跑、只允许一个请求在跑）
    recovering: bool = False
    recovering_started_at: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    client: GeminiWebClient | None = field(default=None, repr=False)


# 会话被谷歌打回登录页时，对外 last_error 为空就补上这句（见 get_status）。
SESSION_EXPIRED_ERROR = "Google session expired (login redirect)"


def _session_expired(a: Account) -> bool:
    """client 已判定不健康、且原因是会话被谷歌打回登录页（GeminiWebClient.auth_expired）。

    getattr 兜底：池对 client 只要求 is_healthy，没有 auth_expired 的实现一律按「不是」处理。
    """
    client = a.client
    return (
        client is not None
        and not client.is_healthy
        and bool(getattr(client, "auth_expired", False))
    )


def _keepalive_mode(a: Account) -> str:
    """这个账号的 cookie 由谁保活（browser / server，见 app/core/keepalive_modes.py）。

    以 client **当前**的 PSID 为准（POST /admin/reload-cookies 换了 PSID 不回写 Account.psid）；
    没有 client、或 client 不提供这个属性时，按账号配置里的 PSID 查。
    """
    mode = getattr(a.client, "keepalive_mode", None) if a.client is not None else None
    if mode in keepalive_modes.MODES:
        return mode
    return keepalive_modes.get_mode(a.psid)


class AccountPool:
    def __init__(self):
        self._accounts: list[Account] = []
        # Condition 自带一把锁，既保护账号列表的并发访问，又用于并发满载时排队等待。
        self._cond = asyncio.Condition()
        self._robin_index = 0
        # 单调递增的 id 计数器：用 len() 生成 id 在删除中间账号后会与现存 id 撞号，
        # 故改用永不回退的计数器，确保 id 全程唯一（见 add_account）。
        self._next_id_seq = 0
        self._strategy = RotationStrategy(settings.rotation_strategy)
        self._max_concurrent = settings.max_concurrent_per_account
        # 并发满载时排队等待上限（秒）。等不到可用槽位才报错，而不是立即拒绝，
        # 让 agent 的高并发请求排队通过而非撞 "No available accounts" 失败。
        self._acquire_timeout = settings.acquire_timeout
        # 持有后台 fire-and-forget task 的强引用，防止被 GC 中途回收
        self._bg_tasks: set = set()

    @property
    def accounts(self) -> list[Account]:
        return list(self._accounts)

    @property
    def active_count(self) -> int:
        return sum(1 for a in self._accounts if a.status == AccountStatus.ACTIVE)

    @property
    def total_count(self) -> int:
        return len(self._accounts)

    async def initialize(self):
        accounts_path = Path(settings.accounts_file)
        if accounts_path.exists():
            self._load_from_file(accounts_path)
            logger.info(f"Loaded {len(self._accounts)} accounts from {accounts_path}")
        else:
            self._add_from_env()

        for account in self._accounts:
            await self._init_account_client(account)

        active = self.active_count
        logger.info(f"Account pool ready: {active}/{self.total_count} active")

    def _load_from_file(self, path: Path):
        # 整文件损坏（半截 JSON/断电）时容错：记录日志后当作空池，绝不让单个坏文件
        # 在 initialize() 期间抛异常把整个进程启动卡死（VULN-010 读容错）。
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            logger.error(f"accounts file {path} is corrupt, starting with empty pool: {e}")
            return
        accounts_data = data if isinstance(data, list) else data.get("accounts", [])
        for i, item in enumerate(accounts_data):
            # 单条坏记录（非 dict / 缺 psid）跳过并告警，保留其余有效账号。
            try:
                if not isinstance(item, dict):
                    raise TypeError("not an object")
                psid = item.get("psid")
                if not psid:
                    raise KeyError("psid")
                account = Account(
                    id=item.get("id", f"account-{i}"),
                    psid=psid.strip().strip('"').strip("'").rstrip(";"),
                    psidts=(item.get("psidts") or "").strip().strip('"').strip("'").rstrip(";"),
                    label=item.get("label", f"account-{i}"),
                )
            except Exception as e:
                logger.warning(f"Skipping corrupt account entry #{i} in {path}: {e}")
                continue
            self._accounts.append(account)
        # 把计数器推到所有现存 account-N 后端的下一位，避免后续 add_account 撞号。
        self._sync_id_seq()

    def _sync_id_seq(self):
        """让 _next_id_seq 大于所有现存 'account-<n>' 的数字后缀，保证后续生成的 id 唯一。"""
        max_seq = -1
        for a in self._accounts:
            if a.id.startswith("account-"):
                suffix = a.id[len("account-"):]
                if suffix.isdigit():
                    max_seq = max(max_seq, int(suffix))
        self._next_id_seq = max(self._next_id_seq, max_seq + 1)

    def _add_from_env(self):
        account = Account(
            id="account-0",
            psid=settings.gemini_psid,
            psidts=settings.gemini_psidts,
            label="Default (env)",
        )
        self._accounts.append(account)

    async def _init_account_client(self, account: Account):
        client = GeminiWebClient(psid=account.psid, psidts=account.psidts)
        await client.initialize()
        account.client = client
        if client.is_healthy:
            account.status = AccountStatus.ACTIVE
            logger.info(f"Account {account.id} ({account.label}) initialized")
        else:
            account.status = AccountStatus.EXPIRED
            logger.warning(f"Account {account.id} ({account.label}) failed to initialize")

    def _find_available(self, exclude: set | None = None, only: set | None = None) -> Account | None:
        """在已持有 self._cond 锁的前提下，挑一个未满载的 ACTIVE 账号；没有则返回 None。
        exclude: 本次 failover 中已试过失败的账号 id，跳过。
        only: 访问密钥绑定的账号 id 白名单；None = 不限制（热路径只多一次 is None 短路）。
        冷却中的账号（被 5xx 限流）降级为兜底：优先选非冷却的，全冷却了才选冷却的。
        """
        exclude = exclude or set()
        now = asyncio.get_event_loop().time()
        candidates = [
            a for a in self._accounts
            if a.status == AccountStatus.ACTIVE
            and a.client is not None and a.client.is_healthy
            and a.active_requests < self._max_concurrent
            and a.id not in exclude
            and (only is None or a.id in only)
        ]
        if not candidates:
            return None
        fresh = [a for a in candidates if a.cooldown_until <= now]
        pool = fresh if fresh else candidates  # 优先非冷却；全冷却则用冷却的兜底
        if self._strategy == RotationStrategy.ROUND_ROBIN:
            return self._pick_round_robin(pool)
        return self._pick_failover(pool)

    def _unhealthy_active(self, only: set | None = None) -> list[Account]:
        """status 仍是 ACTIVE、但 client 会话已失效的账号（需已持有 self._cond 锁）。

        这些账号对 _find_available() 不可见（它要求 client.is_healthy），却又不是 EXPIRED，
        是 issue #11 里池"永久卡死"的那批账号。
        only: 访问密钥绑定的账号白名单；None = 不限制。
        """
        return [
            a for a in self._accounts
            if a.status == AccountStatus.ACTIVE
            and a.client is not None and not a.client.is_healthy
            and (only is None or a.id in only)
        ]

    def _pick_heal_candidate(self, only: set | None = None) -> Account | None:
        """挑一个可尝试自愈的账号，并就地打上 healing 单飞标志（需已持有 self._cond 锁）。

        单飞：同一账号同一时刻最多只有一个请求在跑 reload_cookies，其余并发请求直接拿到
        准确报错，而不是排队陪等一次 60s 级网络 I/O（issue #11 F2）。
        失败过的账号在 HEAL_RETRY_COOLDOWN 内不再被选中，避免永久失效的账号把每个请求
        都变成一次对 Google 的 RotateCookies。

        H1 belt-and-braces：healing 标志本身已经被设计成不依赖锁就能清掉（见
        _try_heal_unhealthy 的 finally），但这里仍加一道陈旧回收保险——万一某条未来路径
        还是没能清掉它，超过 HEALING_STALE_SECONDS 就当作陈旧、重新可选，绝不让单个 bug
        把自愈通道永久焊死。
        """
        now = asyncio.get_event_loop().time()
        for a in self._unhealthy_active(only):
            if a.healing:
                if now - a.healing_started_at <= HEALING_STALE_SECONDS:
                    continue
                logger.warning(
                    f"Account {a.id} healing flag stale for "
                    f"{now - a.healing_started_at:.0f}s, reclaiming it (H1 staleness guard)"
                )
            elif a.heal_cooldown_until > now:
                continue
            a.healing = True
            a.healing_started_at = now
            return a
        return None

    async def _try_heal_unhealthy(self, account: Account) -> bool:
        """对单个「ACTIVE 但会话失效」的账号跑一次 reload_cookies（issue #11 F2）。

        **必须在 self._cond 之外调用**：reload_cookies 会重建 HTTP 会话并访问 Google，
        超时是 60s 级别；持锁执行会把整个池——包括所有健康账号的请求——一起卡死。
        调用方须先用 _pick_heal_candidate() 打好 healing 标志；本函数负责清除它。

        用 reload_cookies 而不是 check_account：后者只拿现有 cookie 重读，不会轮换，
        救不了已经被 Google 轮换掉的 PSIDTS（这正是 issue #11 里"换新 cookie 才恢复"的成因）。

        M3：过 client 自己的 _heal_lock（而不是只靠池级 Account.healing）——两把锁保护的
        并发面不一样：Account.healing 只挡同一账号的池级并发请求，挡不住 client 内部
        generate()/generate_stream() 开头那段自愈逻辑走另一条调用链同时跑 reload_cookies，
        两次并发 reload_cookies 会互相踩会话状态（_http 被关两次、cookie/token 写串）。
        拿到 _heal_lock 后二次确认健康状态：可能在等锁期间已经被另一条路径治好了。
        """
        client = account.client
        ok = False
        cancelled = False
        try:
            if client is not None:
                async with client._heal_lock:
                    if client.is_healthy:
                        ok = True
                    else:
                        result = await client.reload_cookies()
                        ok = bool(result and result.get("success")) and client.is_healthy
        except asyncio.CancelledError:
            # H1（reviewer FIX_FIRST）：取消不是"自愈失败"——不知道 reload_cookies 本来
            # 会不会成功，不该给账号判 HEAL_RETRY_COOLDOWN。跳过下面需要锁的记账部分，
            # 只清标志、原样把取消传播出去。
            cancelled = True
            raise
        except Exception as e:
            logger.warning(f"Account {account.id} self-heal failed: {e}")
        finally:
            # H1：healing 标志是不需要锁的普通属性写，必须无条件、同步地放在这里——不能
            # 包进下面 `async with self._cond:` 里面。Starlette 客户端断连触发的取消会在
            # finally 内的每个 await 点反复注入 CancelledError；若清标志这一步本身要先抢一把
            # 被占用的锁，取消就能让它永远跑不到，自愈通道被永久焊死——等于把 issue #11
            # 换个姿势报出来（这正是本次修复要堵的洞）。
            account.healing = False
            if not cancelled:
                heal_cooldown_until = (
                    0.0 if ok else asyncio.get_event_loop().time() + HEAL_RETRY_COOLDOWN
                )
                # 计数器归零/冷却时间/notify_all 都需要锁，做成 best-effort：shield 保证
                # "这次调用又被取消一次"也不会让它半途而废，但也绝不会因为抢不到锁就拖住
                # 取消的传播——拿不到就在后台慢慢拿，前台该抛的取消照抛不误。
                await asyncio.shield(self._finish_heal(account, ok, heal_cooldown_until))
        return ok

    async def _finish_heal(self, account: Account, ok: bool, heal_cooldown_until: float) -> None:
        """_try_heal_unhealthy 结果落盘中需要锁的部分（计数器 + notify_all）。

        故意与 healing 标志的清除（不需要锁）分开：调用方用 asyncio.shield 包裹本函数，
        取消不会让它半途而废，也不会阻塞取消本身的传播。
        """
        async with self._cond:
            if ok:
                account.consecutive_failures = 0
                # 换了新 cookie 就是换了个会话，旧会话的空响应 streak 不该继承
                account.consecutive_empty = 0
                logger.info(f"Account {account.id} self-healed: cookies reloaded")
                # 多出了可用槽位，唤醒所有排队者重新评估
                self._cond.notify_all()
            else:
                account.heal_cooldown_until = heal_cooldown_until

    def _check_pinned_account(self, account_id: str) -> None:
        """Gem 锁定账号的前置校验（generate/generate_stream 共用）。

        账号必须存在，且必须在本次请求的访问密钥绑定白名单里。第二条必须在这里就
        fail-closed 报准确原因：否则 acquire 会因为"其它账号全被 exclude"而报
        「No more accounts to failover to」，再被改写成「Pinned gem account ...
        unavailable (expired/busy/cooldown)」—— 运维会去查一个其实很健康的账号，
        而且那条文案不被 classify_error 认成 503，会以 500 面世。
        """
        if self._get_account(account_id) is None:
            raise ValueError(f"Account {account_id} not found")
        bound = current_bound_account_ids()
        if bound is not None and account_id not in bound:
            raise RuntimeError(
                f"{BOUND_ACCOUNT_UNAVAILABLE_MSG}: "
                f"the pinned gem account is not bound to this access key"
            )

    def _pick_recover_candidates(self, only: set) -> list[Account]:
        """挑出绑定集合里值得探测的 EXPIRED 账号，并就地打上 recovering 单飞标志
        （需已持有 self._cond 锁）。

        单飞 + 冷却的理由同 _pick_heal_candidate：绑定账号真的死了的时候，不能让每个
        请求都去对 Google 敲一次门；陈旧回收（HEALING_STALE_SECONDS）同样是双保险。
        """
        now = asyncio.get_event_loop().time()
        picked: list[Account] = []
        for a in self._accounts:
            if a.status != AccountStatus.EXPIRED or a.client is None:
                continue
            if a.id not in only:
                continue
            if a.recovering:
                if now - a.recovering_started_at <= HEALING_STALE_SECONDS:
                    continue
                logger.warning(
                    f"Account {a.id} recovering flag stale for "
                    f"{now - a.recovering_started_at:.0f}s, reclaiming it"
                )
            elif a.recover_cooldown_until > now:
                continue
            a.recovering = True
            a.recovering_started_at = now
            picked.append(a)
        return picked

    async def _recover_expired_unlocked(self, targets: list[Account], deadline: float) -> None:
        """锁外探测 EXPIRED 账号是否已恢复（绑定账号路径专用）。

        为什么不能复用 _try_recover_expired：那条路径是**持锁**跑 check_account() 的。
        一把绑定到 EXPIRED 账号的密钥会在池子整体健康的情况下每个请求都撞进恢复分支，
        持锁做网络 I/O 就等于让别的租户（含 .env API_KEY 的请求）跟着一起卡住。
        这里照 F2 自愈那条路子办：锁外、单飞、带冷却，结果落盘时才短暂取锁。
        """
        loop = asyncio.get_event_loop()
        for a in targets:
            ok = False
            try:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    continue
                result = await asyncio.wait_for(a.client.check_account(), timeout=remaining)
                ok = bool(result.get("valid"))
            except Exception:
                ok = False
            finally:
                # 照 H1 的教训：单飞标志是不需要锁的普通属性写，必须无条件同步清掉，
                # 绝不能放进下面需要抢锁的 async with 里（取消会让它永远跑不到）。
                a.recovering = False
            async with self._cond:
                if ok:
                    a.status = AccountStatus.ACTIVE
                    a.consecutive_failures = 0
                    a.recover_cooldown_until = 0.0
                    logger.info(f"Account {a.id} recovered during acquire")
                    self._cond.notify_all()
                else:
                    a.recover_cooldown_until = (
                        asyncio.get_event_loop().time() + EXPIRED_RECOVER_COOLDOWN
                    )

    async def _try_recover_expired(self):
        """无可用账号时，尝试恢复 EXPIRED 账号（已持有锁）。

        只有「没有访问密钥绑定」的请求会走到这里，且只在池里一个 ACTIVE 账号都不剩时
        才会走到 —— 与本功能引入前逐字节一致。绑定账号的恢复走锁外的
        _recover_expired_unlocked（持锁扫全池会把别的租户一起卡住，见那里的说明）。
        """
        for a in self._accounts:
            if a.status == AccountStatus.EXPIRED and a.client:
                try:
                    result = await a.client.check_account()
                    if result.get("valid"):
                        a.status = AccountStatus.ACTIVE
                        a.consecutive_failures = 0
                        logger.info(f"Account {a.id} recovered during acquire")
                except Exception:
                    pass

    async def acquire(self, exclude: set | None = None, only: set | None = None) -> Account:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._acquire_timeout
        # 访问密钥绑定账号：调用方没显式传 only 时，从请求上下文里取。没有访问密钥
        # （env API_KEY 直连 / 一把都没签发）时恒为 None，整条链路零开销、零行为变化。
        if only is None:
            only = current_bound_account_ids()
        if only is not None:
            known = {a.id for a in self._accounts}
            unknown = only - known
            if unknown:
                # 绑定的账号已被删除/改名：fail-closed，绝不静默回退到剩下的账号。
                logger.warning("Access key bound to unknown account(s): %s", sorted(unknown))
            if not (only & known):
                raise RuntimeError(
                    f"{BOUND_ACCOUNT_UNAVAILABLE_MSG}: {sorted(only)} not in pool"
                )
        # 每次 acquire 最多触发一次自愈：失败了就按 F3 诚实报错，绝不在这里反复重试自旋。
        heal_attempted = False
        # 绑定账号的 EXPIRED 恢复探测同理：每次 acquire 最多一轮
        recover_attempted = False
        while True:
            heal_target: Account | None = None
            recover_targets: list[Account] = []
            async with self._cond:
                while True:
                    account = self._find_available(exclude, only)
                    if account is not None:
                        account.active_requests += 1
                        account.last_used = datetime.now(timezone.utc)
                        return account

                    # failover 场景：主动排除了部分账号后没有候选了 → 不排队不救活，
                    # 立即报错让 failover 循环停止（已无其他账号可试）
                    if exclude:
                        raise RuntimeError("No more accounts to failover to")

                    # 没有空闲槽位。区分两种情况：
                    #   ① 有「可用账号」但都满载 → 排队等 release 唤醒（不要跑网络恢复，
                    #      否则高并发满载时每次唤醒都串行跑 check_account 把整个池卡死）
                    #   ② 一个可用账号都没有 → 才尝试救活（网络 I/O，低频路径）
                    # F1（issue #11）：这里的谓词必须与 _find_available() 完全一致——也要求
                    # client.is_healthy。否则 status=ACTIVE 但会话已失效的账号会被当成"只是忙"，
                    # 每个请求都白等满 acquire_timeout(60s) 再报 "All accounts busy"，而实际
                    # 占用槽位是 0；那条 529 是假的，且因为恢复路径永远够不着而变成永久卡死。
                    has_available_account = any(
                        a.status == AccountStatus.ACTIVE
                        and a.client is not None and a.client.is_healthy
                        and (only is None or a.id in only)
                        for a in self._accounts
                    )
                    if not has_available_account:
                        unhealthy = self._unhealthy_active(only)
                        if not unhealthy:
                            if only is not None:
                                # 绑定账号路径：绝不在这里持锁跑 check_account()。池里别人的
                                # 账号可能正健康着，持锁做网络 I/O 会把所有其他请求（含
                                # .env API_KEY 的）一起卡住，而且没有冷却就是逐请求敲门。
                                # 跳出临界区，到锁外单飞探测一轮（见 _recover_expired_unlocked）。
                                if not recover_attempted:
                                    recover_targets = self._pick_recover_candidates(only)
                                    if recover_targets:
                                        break
                                # 没有可探测的目标（已试过/正被别的请求跑/还在冷却）：
                                # fail-closed，绝不回退到池里其他账号。
                                raise RuntimeError(
                                    f"{BOUND_ACCOUNT_UNAVAILABLE_MSG}: {sorted(only)}"
                                )
                            # 真正的"一个 ACTIVE 账号都没有"（其余是 EXPIRED/DISABLED）：
                            # 这是修复前就存在的持锁网络恢复路径，不是本次改动引入的新东西，
                            # 对无绑定的请求维持原样——check_account 比 reload_cookies 轻量
                            # 得多，且只有在彻底没有 ACTIVE 账号时才会走到这里。
                            await self._try_recover_expired()
                            account = self._find_available()
                            if account is not None:
                                account.active_requests += 1
                                account.last_used = datetime.now(timezone.utc)
                                return account
                            raise RuntimeError("No available accounts")
                        # H2（reviewer FIX_FIRST）：这里绝不能再调 _try_recover_expired()。
                        # F1 把 has_available_account 的判定收紧成"ACTIVE 且健康"后，池里
                        # 只要同时存在 EXPIRED 账号和 ACTIVE-但-不健康 账号，就会撞进这个分支；
                        # _try_recover_expired 对每个 EXPIRED 账号跑 check_account() 是持锁
                        # 网络 I/O，没有冷却/单飞保护，会把整个池卡住，还对 Google 形成
                        # 逐请求重试的敲门风暴。ACTIVE-但-不健康 的账号已经有 F2 那条锁外、
                        # 单飞、带冷却的自愈路径，直接走它，不碰 EXPIRED 账号的恢复。
                        if not heal_attempted:
                            heal_target = self._pick_heal_candidate(only)
                            if heal_target is not None:
                                break
                        # 自愈已试过/正被别的请求跑/还在冷却 → F3：给出准确文案，
                        # 让 classify_error 映射成 503，而不是会诱发无限重试的 529。
                        raise RuntimeError(NO_HEALTHY_ACCOUNT_MSG)

                    # 有可用账号但都满载 → 排队等可用槽位，而非直接拒绝
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise RuntimeError(
                            f"All accounts busy (max_concurrent={self._max_concurrent}), "
                            f"waited {self._acquire_timeout}s"
                        )
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"All accounts busy (max_concurrent={self._max_concurrent}), "
                            f"waited {self._acquire_timeout}s"
                        )

            # ↑ 到这里锁已释放。reload_cookies / check_account 都是网络 I/O，绝不能持锁跑。
            if recover_targets:
                recover_attempted = True
                await self._recover_expired_unlocked(recover_targets, deadline)
                # 回到外层循环重新取锁：恢复成功 → 直接拿到槽位；失败 → 下一轮按
                # BOUND_ACCOUNT_UNAVAILABLE_MSG fail-closed。
                continue
            heal_attempted = True
            # M1（reviewer MEDIUM）：不能让自愈把 acquire() 的总耗时顶穿 operator 配置的
            # acquire_timeout（最多可能多等一整个 reload_cookies 时长，~60s）。用剩余预算
            # 给它设一个硬上限；预算已经耗尽就干脆不发起，直接报准确错误。
            remaining = deadline - loop.time()
            if remaining <= 0:
                heal_target.healing = False
                raise RuntimeError(NO_HEALTHY_ACCOUNT_MSG)
            try:
                # shield：即使这次 wait_for 超时/被取消，_try_heal_unhealthy 也会在后台
                # 跑完——healing 标志的清除、冷却时间的落盘都不会因为我们不再等它而丢失。
                await asyncio.wait_for(
                    asyncio.shield(self._try_heal_unhealthy(heal_target)), timeout=remaining
                )
            except asyncio.TimeoutError:
                pass  # 没在预算内跑完：这次 acquire() 按预算诚实超时，不再空等
            # 回到外层循环重新取锁、重新 _find_available()：
            # 自愈成功 → 直接拿到槽位；失败/超预算 → 下一轮走上面的 NO_HEALTHY_ACCOUNT_MSG 分支。

    async def release(self, account: Account, success: bool, cooldown: bool = False, *,
                      error: str = "", empty: bool = False, reason: str = "5xx rate-limit"):
        """error / empty / reason 都是 keyword-only 且有默认值，既有调用点行为逐字节不变。

        error：_error_summary() 出来的安全摘要。
        empty：这次生成上游返回了 200 但没产出任何内容（见 _is_empty_generation）。
        reason：cooldown 那条日志里写的冷却原因（默认就是原来那句 5xx 限流）。
        """
        async with self._cond:
            account.active_requests = max(0, account.active_requests - 1)
            account.request_count += 1
            if not success and error:
                account.last_error = error
                account.last_error_at = datetime.now(timezone.utc)
            if success and empty:
                # 空响应：只累计，单次绝不降级账号（内容拒答之类的正常情况长得一模一样）。
                # 刻意不碰 status / cooldown_until，也刻意不打 last_success_at ——
                # 吐了个空并不能证明这个会话真的还能生成内容。
                #
                # 但 consecutive_failures 必须照旧清零：这一批「只做可观测性」，不许动
                # failover 语义。基线里空响应走的是 release(success=True)，会清零；
                # 若这里不清零，「偶发失败 / 空 / 偶发失败 / 空 / 偶发失败」这种混合序列
                # 会在第 5 次把 cf 顶到 3、把一个 cookie 完好的账号标成 EXPIRED 踢出轮换，
                # 而基线下它始终 ACTIVE。空响应的可见性由下面 consecutive_empty /
                # empty_count / Errors 三个新计数器负责，不靠改降级阈值来表达。
                account.consecutive_failures = 0
                account.consecutive_empty += 1
                account.empty_count += 1
                if account.consecutive_empty >= EMPTY_STREAK_THRESHOLD:
                    # 连着空到阈值才在面板可见的 Errors 上留痕，并持续增长，
                    # 让"卡在空响应里"的账号一眼看得出还在恶化。
                    account.error_count += 1
                    account.last_error = (
                        f"Empty response x{account.consecutive_empty} (upstream 200, no content)"
                    )
                    account.last_error_at = datetime.now(timezone.utc)
                    logger.warning(
                        f"Account {account.id} returned {account.consecutive_empty} consecutive "
                        f"empty responses (upstream 200, no content)"
                    )
            elif success:
                account.consecutive_failures = 0
                # 只有真吐出了内容才算证明会话是活的 —— 这是唯一的清零点
                account.consecutive_empty = 0
                account.last_success_at = datetime.now(timezone.utc)
            elif cooldown:
                # 5xx/503 限流：不是账号坏，只是被 Google 临时限流。
                # 设短期冷却（期间降级不优先选），不累积失败、不标 expired。
                account.error_count += 1
                account.cooldown_until = asyncio.get_event_loop().time() + settings.failover_cooldown
                logger.warning(
                    f"Account {account.id} cooled down for {settings.failover_cooldown}s ({reason})"
                )
            else:
                account.error_count += 1
                account.consecutive_failures += 1
                if account.consecutive_failures >= 3:
                    account.status = AccountStatus.EXPIRED
                    logger.warning(f"Account {account.id} marked expired after 3 consecutive failures")
            # 释放了一个槽位，只唤醒一个排队的等待者即可（notify(1) 避免惊群：
            # notify_all 会让所有等待者一起醒来争抢同一个空位，落败者再重新 wait，
            # 在高并发满载时造成无谓的反复唤醒/竞争）
            self._cond.notify(1)

    async def _release_failed(self, account: Account, exc: Exception):
        """一次不换号重试的失败怎么记账（generate / generate_stream 共用）。

        生成超时（GenerationTimedOut、真流式等不到下一个 chunk 的 TimeoutError、curl code 28）
        是谷歌那边卡住，不是 cookie 失效：照 5xx 限流那条瞬时故障口径记账 —— 记一次错误、
        短暂冷却，不累计 consecutive_failures、不标 EXPIRED。过去它走的是下面那条「连败 3 次
        即 EXPIRED」的通道，谷歌卡一阵子就能把单账号池整个打掉。
        也不换号重试（_is_retryable 不认超时）：这一轮的预算已经花完，再试只会让客户端再等一整轮。
        谷歌的失败套话（GeminiFailureReply）同样是谷歌那边的瞬时故障（规格 H.2）：真流式里它往往在
        思考事件之后才判出来，池这时已经不能换号（emitted_any）而走到这里；过去落进下面那条「连败
        3 次即 EXPIRED」的通道，flash 故障期间会把账号一个个踢出轮换，连带同账号的 pro / flash-lite。
        其它失败照旧。
        """
        if is_timeout_error(exc):
            await self.release(account, success=False, cooldown=True, error=_error_summary(exc),
                               reason="generation timeout")
            return
        if isinstance(exc, GeminiFailureReply):
            logger.warning(f"Account {account.id} got {exc} after the stream had started; "
                           f"not failing over")
            await self.release(account, success=False, cooldown=True, error=_error_summary(exc),
                               reason="generic failure reply")
            return
        await self.release(account, success=False, error=_error_summary(exc))

    async def release_disconnected(self, account: Account):
        """中性释放：客户端断连/请求被取消时只归还槽位，不计成功也不计失败（issue #11 F6）。

        断连是客户端的行为，不是账号的错。走 release(success=False) 会累加
        consecutive_failures，满 3 次就把账号标成 EXPIRED —— 用户连点 3 次"停止"
        就能把单账号池打死。也不能走 success=True：那会把之前真实的连续失败清零。
        """
        async with self._cond:
            account.active_requests = max(0, account.active_requests - 1)
            account.request_count += 1
            self._cond.notify(1)

    def _pick_round_robin(self, available: list[Account]) -> Account:
        # 在「稳定的全量账号顺序」self._accounts 上做轮转，而不是在每次调用都变长度的
        # 过滤子集 available 上取模——后者会因 busy/cooldown/exclude 的成员变动让同一个
        # _robin_index 映射到不同位置，破坏轮转公平性（同号被反复选中或别的号被跳过）。
        # 这里从上次位置之后开始扫描稳定列表，返回第一个属于 available 的账号，
        # 并把 _robin_index 钉到它在稳定列表中的位置，使轮转跨成员变化保持稳定。
        n = len(self._accounts)
        if n == 0:
            return available[0]
        available_set = set(id(a) for a in available)
        start = (self._robin_index + 1) % n
        for offset in range(n):
            idx = (start + offset) % n
            cand = self._accounts[idx]
            if id(cand) in available_set:
                self._robin_index = idx
                return cand
        # 理论不可达（available 至少含一个 self._accounts 中的账号）；兜底返回首个候选。
        return available[0]

    def _pick_failover(self, available: list[Account]) -> Account:
        for a in self._accounts:
            if a in available:
                return a
        return available[0]

    async def add_account(self, psid: str, psidts: str, label: str = "") -> Account:
        # 用单调计数器生成 id，删除中间账号后也绝不撞号（不再用易撞号的 len()）。
        self._sync_id_seq()
        account_id = f"account-{self._next_id_seq}"
        self._next_id_seq += 1
        account = Account(
            id=account_id,
            psid=psid.strip().strip('"').strip("'").rstrip(";"),
            psidts=psidts.strip().strip('"').strip("'").rstrip(";"),
            label=label or account_id,
        )
        await self._init_account_client(account)
        self._accounts.append(account)
        self._save_to_file()
        return account

    def persist_account_cookies(self, account_id: str, psid: str, psidts: str) -> bool:
        """把面板换上的新 cookie 回写到 accounts.json（只碰凭据字段，不碰账号状态）。

        面板的「更新 cookie」走 client.reload_cookies()，它只改运行态 + data/cookies 缓存，
        从不回写 accounts.json —— 全仓找不到任何 `.psidts = ` 的赋值点。于是 accounts.json
        里的 psidts 永远是"添加账号那一刻"的值：面板上刚救活的账号，下次重启又拿着那份
        早已失效的 cookie 起来，而运维完全看不出为什么。
        """
        for account in self._accounts:
            if account.id != account_id:
                continue
            cleaned_psid = (psid or "").strip().strip('"').strip("'").rstrip(";")
            cleaned_psidts = (psidts or "").strip().strip('"').strip("'").rstrip(";")
            if cleaned_psid:
                account.psid = cleaned_psid
            # psidts 允许被清空（运维刻意只给 PSID 时），所以不做真值判断
            account.psidts = cleaned_psidts
            self._save_to_file()
            return True
        return False

    async def mark_cookies_reloaded(self, account: Account) -> None:
        """换上的新 cookie 已经 reload 成功：池内状态当场回到可用（持锁）。

        PUT /admin/accounts/{id}/cookies 与 POST /admin/reload-cookies 成功后调用，效果与
        check_account 判定 valid 时一致（status=ACTIVE、consecutive_failures=0），别的计数一概不动。
        过去这一步要靠调用方随后再调一次 GET /admin/accounts/{id}/check：浏览器保活插件会调，
        面板的「更新 Cookie」和脚本不会 —— 一个已被池标成 EXPIRED 的账号换上了好 cookie、client
        也健康了，却仍对 _find_available 不可见，直到有人去点「检测」。
        """
        async with self._cond:
            account.status = AccountStatus.ACTIVE
            account.consecutive_failures = 0
            logger.info(f"Account {account.id} is active again after a cookie reload")
            # 多出了一个可用账号，唤醒所有排队者重新评估
            self._cond.notify_all()

    async def remove_account(self, account_id: str) -> bool:
        for i, account in enumerate(self._accounts):
            if account.id == account_id:
                if account.client:
                    await account.client.shutdown()
                self._accounts.pop(i)
                self._save_to_file()
                return True
        return False

    async def check_account(self, account_id: str) -> dict:
        for account in self._accounts:
            if account.id == account_id:
                if account.client:
                    result = await account.client.check_account()
                    if result["valid"]:
                        account.status = AccountStatus.ACTIVE
                        account.consecutive_failures = 0
                    else:
                        account.consecutive_failures += 1
                        if account.consecutive_failures >= 3:
                            account.status = AccountStatus.EXPIRED
                    return {**result, "account_id": account.id, "status": account.status.value}
                return {"valid": False, "error": "No client", "account_id": account.id}
        raise ValueError(f"Account {account_id} not found")

    async def check_all(self) -> list[dict]:
        results = []
        for account in self._accounts:
            try:
                result = await self.check_account(account.id)
                results.append(result)
            except Exception as e:
                results.append({"account_id": account.id, "valid": False, "error": str(e)})
        return results

    async def list_web_chats(self, recent: int = 300) -> list[dict]:
        """列出所有 active 账号的网页端会话（只读，用于验证/排查）。"""
        out = []
        for account in self._accounts:
            if account.status != AccountStatus.ACTIVE or not account.client:
                continue
            try:
                chats = await account.client.list_web_chats(recent=recent)
                out.append({"account_id": account.id, "count": len(chats), "chats": chats})
            except Exception as e:
                out.append({"account_id": account.id, "error": str(e)})
        return out

    async def cleanup_web_chats(self, keep_hours: float = 24.0, skip_pinned: bool = True) -> list[dict]:
        """对所有 active 账号清理超过 keep_hours 的网页会话（置顶可保留）。"""
        out = []
        for account in self._accounts:
            if account.status != AccountStatus.ACTIVE or not account.client:
                continue
            try:
                res = await account.client.cleanup_old_web_chats(
                    keep_hours=keep_hours, skip_pinned=skip_pinned
                )
                out.append({"account_id": account.id, **res})
            except Exception as e:
                out.append({"account_id": account.id, "error": str(e)})
        return out

    def account_pinnable(self, account_id: str | None) -> bool:
        """多轮续接用：这个账号此刻能不能被钉住（generate(..., account_id=) 会不会当场判它不可用）。

        要求：账号存在、ACTIVE、会话健康、在本次请求的访问密钥绑定白名单里；池里还有别的账号
        时还得有空槽位 —— 钉住 = 排除其它所有账号，满载的账号会被 acquire 当场判「不可用」
        而不是排队（只有它一个账号时 acquire 照常排队，满载不算不可钉）。
        只读快照、不占槽位：真正发请求时仍可能因竞态报 unavailable，调用方要有改发完整历史的兜底。
        """
        if not account_id:
            return False
        account = self._get_account(account_id)
        if account is None or account.status != AccountStatus.ACTIVE:
            return False
        if account.client is None or not account.client.is_healthy:
            return False
        bound = current_bound_account_ids()
        if bound is not None and account_id not in bound:
            return False
        if account.active_requests >= self._max_concurrent and len(self._accounts) > 1:
            return False
        return True

    def _get_account(self, account_id: str):
        for a in self._accounts:
            if a.id == account_id:
                return a
        return None

    async def list_gems(self, account_id: str) -> list[dict]:
        acc = self._get_account(account_id)
        if not acc or not acc.client:
            raise ValueError(f"Account {account_id} not found or no client")
        return await acc.client.list_gems()

    async def create_gem(self, account_id: str, name: str, prompt: str, description: str = "") -> str | None:
        acc = self._get_account(account_id)
        if not acc or not acc.client:
            raise ValueError(f"Account {account_id} not found or no client")
        return await acc.client.create_gem(name, prompt, description)

    async def update_gem(self, account_id: str, gem_id: str, name: str, prompt: str, description: str = "") -> bool:
        acc = self._get_account(account_id)
        if not acc or not acc.client:
            raise ValueError(f"Account {account_id} not found or no client")
        return await acc.client.update_gem(gem_id, name, prompt, description)

    async def delete_gem(self, account_id: str, gem_id: str) -> bool:
        acc = self._get_account(account_id)
        if not acc or not acc.client:
            raise ValueError(f"Account {account_id} not found or no client")
        return await acc.client.delete_gem(gem_id)

    def set_strategy(self, strategy: str):
        self._strategy = RotationStrategy(strategy)

    def set_max_concurrent(self, value: int):
        self._max_concurrent = value
        # 提高上限后，唤醒排队等槽位的请求让它们重新检查（notify(1) 会逐个传递，
        # 这里用 notify_all 一次性放行，让所有等待者重新评估新上限）
        async def _wake():
            async with self._cond:
                self._cond.notify_all()
        try:
            task = asyncio.get_running_loop().create_task(_wake())
            # 存强引用防止 task 被 GC 中途回收，完成后自动移除
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            pass

    def get_status(self) -> dict:
        accounts_info = []
        # 循环外取一次即可（循环里反复取 event loop 纯属浪费）。
        # get_running_loop 而不是 get_event_loop：后者在没有运行中 loop 的同步上下文
        # （诊断脚本 / 测试）里会直接抛 RuntimeError，把一个纯只读的状态导出搞崩。
        # 取不到时钟就按"未冷却"处理 —— 新建 loop 的 time() 本来也是从 0 起算。
        try:
            loop_now = asyncio.get_running_loop().time()
        except RuntimeError:
            loop_now = 0.0
        for a in self._accounts:
            # 对外的 status 是**派生口径**，不改池内部状态机（_find_available / 自愈 /
            # _try_recover_expired 仍按 a.status 走）：池里还标着 ACTIVE、但会话已被谷歌打回
            # 登录页的账号报 expired。浏览器保活插件只认 expired —— 过去这种账号一直报 active，
            # 插件看不见、一次都不去救（线上两个账号死了 37 小时）。client 恢复健康就回到 active；
            # 别的原因（网络抖动、5xx）造成的不健康仍报 active，由下面的 is_healthy 体现。
            status = a.status.value
            last_error = a.last_error
            if _session_expired(a):
                if a.status == AccountStatus.ACTIVE:
                    status = AccountStatus.EXPIRED.value
                if status == AccountStatus.EXPIRED.value and not last_error:
                    last_error = SESSION_EXPIRED_ERROR
            accounts_info.append({
                "id": a.id,
                "label": a.label,
                "psid": a.psid,
                "status": status,
                "request_count": a.request_count,
                "error_count": a.error_count,
                "active_requests": a.active_requests,
                "last_used": a.last_used.isoformat() if a.last_used else None,
                "cooling_down": a.cooldown_until > loop_now,
                # issue #11：下面这几个才是有鉴别力的健康信号。status 只有连挂 3 次或撞 401/403
                # 才会变 EXPIRED，所以"cookie 已经死透但面板一直绿着 ACTIVE"是常态；
                # models_count 只要 client 对象在就恒等于公开模型数，同样证明不了会话还活着。
                "is_healthy": bool(a.client is not None and a.client.is_healthy),
                "consecutive_failures": a.consecutive_failures,
                "consecutive_empty": a.consecutive_empty,
                "empty_count": a.empty_count,
                "last_success_at": a.last_success_at.isoformat() if a.last_success_at else None,
                # 安全摘要，不含上游原文（见 _error_summary）；会话失效时补上原因（见上）
                "last_error": last_error,
                "last_error_at": a.last_error_at.isoformat() if a.last_error_at else None,
                "models": self.models if a.client else [],
                "models_count": len(self.models) if a.client else 0,
                # browser = cookie 由浏览器保活插件推送、服务端不轮换；server = 服务端轮换（默认）
                "keepalive_mode": _keepalive_mode(a),
            })
        return {
            "total": self.total_count,
            # 与上面逐个账号的对外 status 同口径：会话已失效的不算可用
            "active": sum(1 for info in accounts_info if info["status"] == AccountStatus.ACTIVE.value),
            "strategy": self._strategy.value,
            "max_concurrent_per_account": self._max_concurrent,
            "accounts": accounts_info,
        }

    def family_of(self, model: str) -> str | None:
        """模型名 → 模型族（gemini_client.model_family；心跳发现的族要看各账号自己的模型表）。"""
        return model_family(model, (a.client for a in self._accounts if a.client is not None))

    # 模型熔断的记录点放在池里（规格 C.5 / I.3）：一次上游尝试的结果（成功 / 换号 / 不换号的失败）
    # 都在这里落地，池手里也正好有 model、prompt 与 conversation_id。client 层的同号快速重试不单独
    # 记；路由层的「退回不思考」「完整历史」重试是新的上游尝试，照常各记各的（同一请求的指纹相同，
    # 计数只 +1：退回不思考是同一个 prompt；完整历史换了 prompt，路由在 same_request_as 里发它，
    # 这里经 attempt_fingerprint 沿用第一次尝试的指纹）。每次尝试只记一个结果（规格 I.6）。
    def _breaker_failure(self, model: str, prompt: str, conversation_id: str,
                         started_at: float, exc: Exception) -> None:
        if not _breaker_counts(exc):
            return
        model_breaker.record_failure(
            self.family_of(model), started_at=started_at,
            fingerprint=attempt_fingerprint(prompt, conversation_id),
            reason=_error_summary(exc),
        )

    def _breaker_success(self, model: str, started_at: float) -> None:
        model_breaker.record_success(self.family_of(model), started_at=started_at)

    async def generate(self, prompt: str, model: str, conversation_id: str = "",
                       attachments: list | None = None, gem_id: str | None = None,
                       account_id: str | None = None, extended_thinking: bool = False) -> dict:
        # failover：某账号被可重试错误（5xx/未就绪/401·403）打回时，换下一个 active 账号重试，
        # 直到成功或无更多账号可试。5xx 限流账号进入冷却，401/403 标 expired。
        tried: set = set()
        # 绑定账号：排除其他所有账号，使 acquire/failover 只可能选中目标账号
        if account_id:
            self._check_pinned_account(account_id)
            tried.update({a.id for a in self._accounts if a.id != account_id})
        last_err = None
        while True:
            try:
                account = await self.acquire(exclude=tried if tried else None)
            except RuntimeError:
                # 没有（更多）账号可用：抛出最后一次可重试错误（若有），否则抛 acquire 的错
                if last_err is not None:
                    raise last_err
                # 锁定账号场景：其它账号已被全部 exclude，acquire 报「无更多账号可故障切换」
                # 其实是绑定账号本身不可用（expired/busy/cooldown），换更准确的文案。
                if account_id:
                    raise _pinned_unavailable(account_id, gem_id)
                raise
            t0 = time.time()
            attempt_started = model_breaker.now()
            released = False
            try:
                result = await account.client.generate(prompt, model, conversation_id, attachments, gem_id,
                                                        extended_thinking)
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                empty = _is_empty_generation(result)
                await self.release(account, success=True, empty=empty)
                released = True
                if not empty:
                    # 拿到了正文 / 思考 / 图片：这个族此刻是好的（空响应既不算成功也不算失败）
                    self._breaker_success(model, attempt_started)
                return _with_account_id(result, account)
            except (asyncio.CancelledError, GeneratorExit):
                # F6：客户端断连/取消不是账号失败，只归还槽位（否则点 3 次"停止"就能把
                # 单账号池标成 EXPIRED）。必须放在 except Exception 之前显式处理。
                await self.release_disconnected(account)
                released = True
                raise
            except Exception as e:
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                # 换号分支与 _release_failed 分支都要记（规格 I.1），所以记在分叉之前
                self._breaker_failure(model, prompt, conversation_id, attempt_started, e)
                if _is_retryable(e):
                    # 可重试：5xx 冷却该账号、401/403 标 expired，换下一个账号重试
                    last_err = e
                    tried.add(account.id)
                    await self.release(account, success=False, cooldown=_is_5xx(e), error=_error_summary(e))
                    released = True
                    if isinstance(e, HTTPStatusError) and e.status_code in (401, 403):
                        account.status = AccountStatus.EXPIRED
                    logger.warning(f"Account {account.id} got {e}; failing over (tried={len(tried)})")
                    continue
                await self._release_failed(account, e)
                released = True
                raise
            finally:
                # 兜底：CancelledError/GeneratorExit 等未走上面分支的路径也归还槽位（P0-4 防泄漏死锁）
                if not released:
                    await self.release(account, success=False)

    async def generate_stream(self, prompt: str, model: str, conversation_id: str = "",
                              attachments: list | None = None, gem_id: str | None = None,
                              account_id: str | None = None, extended_thinking: bool = False):
        """真流式：持有账号槽位直到整个流结束，再 release。
        逐块产出 {"type":"delta","text":增量} ，最后产出 {"type":"final", ...}（含会话ID/图片）。

        failover：仅在「尚未向客户端 yield 任何内容前」遇到可重试错误（5xx/未就绪/401·403）才换账号重试
        （已经吐出部分内容后再换账号会导致重复，故此时只能终止）。
        """
        tried: set = set()
        # 绑定账号：排除其他所有账号，使 acquire/failover 只可能选中目标账号
        if account_id:
            self._check_pinned_account(account_id)
            tried.update({a.id for a in self._accounts if a.id != account_id})
        last_err = None
        while True:
            try:
                account = await self.acquire(exclude=tried if tried else None)
            except RuntimeError:
                if last_err is not None:
                    raise last_err
                # 锁定账号场景：其它账号已被全部 exclude，真实原因是绑定账号本身不可用
                if account_id:
                    raise _pinned_unavailable(account_id, gem_id)
                raise
            t0 = time.time()
            attempt_started = model_breaker.now()
            breaker_recorded = False     # 这次尝试已经给熔断记过结果了（每次尝试只记一个，规格 I.6）
            emitted_any = False
            failover = False
            released = False
            # 判空只看这三个，且必须等流跑完再判：帧是累积式的，中途任何一帧都可能没文本，
            # 而 final.text 才是过滤完占位串的权威全文。emitted_any 不能复用来判空——
            # 它对任何事件（包括 text="" 的 final）都置 True，零鉴别力。
            saw_text = False
            saw_thoughts = False
            final_evt = None
            try:
                async for evt in account.client.generate_stream(prompt, model, conversation_id, attachments, gem_id,
                                                                  extended_thinking):
                    emitted_any = True
                    evt_type = evt.get("type") if isinstance(evt, dict) else None
                    if evt_type == "delta" and (evt.get("text") or "").strip():
                        saw_text = True
                        if not breaker_recorded:
                            # 第一个正文增量就是决定性信号：它已经过了失败套话的扣留检查（规格 A.5），
                            # 不可能是套话。只有思考不算 —— 套话可以出现在思考之后。
                            self._breaker_success(model, attempt_started)
                            breaker_recorded = True
                    elif evt_type == "thoughts" and (evt.get("text") or "").strip():
                        saw_thoughts = True
                    elif evt_type == "final":
                        evt = _with_account_id(evt, account)
                        final_evt = evt
                    yield evt
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                # final 事件压根没来（上游中途静默截断）也算空：is_empty_result(None) 为真
                stream_empty = not saw_text and not saw_thoughts and _is_empty_generation(final_evt)
                await self.release(account, success=True, empty=stream_empty)
                released = True
                if not breaker_recorded and not stream_empty:
                    self._breaker_success(model, attempt_started)
                return
            except (asyncio.CancelledError, GeneratorExit):
                # F6：客户端在流中途断连（生成器被 aclose → GeneratorExit）或请求被取消，
                # 都不是账号的错：只归还槽位，不累加 consecutive_failures/error_count。
                await self.release_disconnected(account)
                released = True
                raise
            except Exception as e:
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                if not breaker_recorded:
                    # 换号分支与 _release_failed 分支都要记（规格 I.1）；已经记过成功的不再记失败
                    self._breaker_failure(model, prompt, conversation_id, attempt_started, e)
                # 只有「还没吐任何内容」+「可重试」+「还有别的账号」才 failover
                if _is_retryable(e) and not emitted_any:
                    last_err = e
                    tried.add(account.id)
                    await self.release(account, success=False, cooldown=_is_5xx(e), error=_error_summary(e))
                    released = True
                    if isinstance(e, HTTPStatusError) and e.status_code in (401, 403):
                        account.status = AccountStatus.EXPIRED
                    logger.warning(f"Account {account.id} got {e} before first chunk; stream failing over (tried={len(tried)})")
                    failover = True
                else:
                    await self._release_failed(account, e)
                    released = True
                    raise
            finally:
                # 兜底：客户端断连(GeneratorExit)/取消(CancelledError) 等路径也归还槽位（P0-4 防泄漏死锁）
                if not released:
                    await self.release(account, success=False)
            if failover:
                continue

    @property
    def models(self) -> list[str]:
        # 3 个固定公开模型名（pro / flash / flash-lite，API 稳定契约）恒在最前、顺序不变，
        # 内部由 _resolve_model 按账号真实可用模型动态映射。
        # 之后追加「池里至少一个账号真的拿到了」的新 family 的公开名（如 Argon）：
        # 心跳没发现它的部署看不到这个名字，不给用户一个调不通的选项。
        from app.core.gemini_client import PUBLIC_MODELS, _BASE_FAMILIES, _FAMILY_PUBLIC
        names = list(PUBLIC_MODELS)
        for account in self._accounts:
            family_model = getattr(account.client, "_family_model", None) or {}
            for family, internal in family_model.items():
                if family in _BASE_FAMILIES:
                    continue
                public = _FAMILY_PUBLIC.get(family) or internal
                if public not in names:
                    names.append(public)
        return names

    @property
    def is_healthy(self) -> bool:
        return self.active_count > 0

    def _save_to_file(self):
        accounts_data = []
        for a in self._accounts:
            accounts_data.append({
                "id": a.id,
                "psid": a.psid,
                "psidts": a.psidts,
                "label": a.label,
            })
        path = Path(settings.accounts_file)
        # 原子写：accounts.json 存 PSID 凭据，写入中途崩溃/断电不得截断成半截 JSON（VULN-010）。
        atomic_write_text(path, json.dumps({"accounts": accounts_data}, indent=2, ensure_ascii=False))

    async def shutdown(self):
        for account in self._accounts:
            if account.client:
                await account.client.shutdown()
        logger.info("Account pool shut down")


account_pool = AccountPool()
