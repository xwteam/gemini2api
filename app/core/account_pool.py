import json
import time
import asyncio
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.gemini_client import GeminiWebClient, HTTPStatusError
from app.config import settings
from app.core.usage_metrics import live_metrics

logger = logging.getLogger(__name__)


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
    last_error: str = ""
    # 被 5xx/503 限流后的冷却截止时间戳（loop.time()）；冷却期内不优先选，但不算 expired
    cooldown_until: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    client: GeminiWebClient | None = field(default=None, repr=False)


class AccountPool:
    def __init__(self):
        self._accounts: list[Account] = []
        # Condition 自带一把锁，既保护账号列表的并发访问，又用于并发满载时排队等待。
        self._cond = asyncio.Condition()
        self._robin_index = 0
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
        data = json.loads(path.read_text())
        accounts_data = data if isinstance(data, list) else data.get("accounts", [])
        for i, item in enumerate(accounts_data):
            account = Account(
                id=item.get("id", f"account-{i}"),
                psid=item["psid"].strip().strip('"').strip("'").rstrip(";"),
                psidts=item.get("psidts", "").strip().strip('"').strip("'").rstrip(";"),
                label=item.get("label", f"account-{i}"),
            )
            self._accounts.append(account)

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

    def _find_available(self, exclude: set | None = None) -> Account | None:
        """在已持有 self._cond 锁的前提下，挑一个未满载的 ACTIVE 账号；没有则返回 None。
        exclude: 本次 failover 中已试过失败的账号 id，跳过。
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
        ]
        if not candidates:
            return None
        fresh = [a for a in candidates if a.cooldown_until <= now]
        pool = fresh if fresh else candidates  # 优先非冷却；全冷却则用冷却的兜底
        if self._strategy == RotationStrategy.ROUND_ROBIN:
            return self._pick_round_robin(pool)
        return self._pick_failover(pool)

    async def _try_recover_expired(self):
        """无可用账号时，尝试恢复 EXPIRED 账号（已持有锁）。"""
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

    async def acquire(self, exclude: set | None = None) -> Account:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._acquire_timeout
        async with self._cond:
            while True:
                account = self._find_available(exclude)
                if account is not None:
                    account.active_requests += 1
                    account.last_used = datetime.now(timezone.utc)
                    return account

                # failover 场景：主动排除了部分账号后没有候选了 → 不排队不救活，
                # 立即报错让 failover 循环停止（已无其他账号可试）
                if exclude:
                    raise RuntimeError("No more accounts to failover to")

                # 没有空闲槽位。区分两种情况：
                #   ① 有 ACTIVE 账号但都满载 → 排队等 release 唤醒（不要跑网络恢复，
                #      否则高并发满载时每次唤醒都串行跑 check_account 把整个池卡死）
                #   ② 完全没有 ACTIVE 账号 → 才尝试救活 EXPIRED（网络 I/O，低频路径）
                has_active = any(a.status == AccountStatus.ACTIVE for a in self._accounts)
                if not has_active:
                    await self._try_recover_expired()
                    account = self._find_available()
                    if account is not None:
                        account.active_requests += 1
                        account.last_used = datetime.now(timezone.utc)
                        return account
                    # 救不活，且没有 ACTIVE → 排队也没意义，立即报错
                    raise RuntimeError("No available accounts")

                # 有 ACTIVE 账号但都满载 → 排队等可用槽位，而非直接拒绝
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

    async def release(self, account: Account, success: bool, cooldown: bool = False):
        async with self._cond:
            account.active_requests = max(0, account.active_requests - 1)
            account.request_count += 1
            if success:
                account.consecutive_failures = 0
            elif cooldown:
                # 5xx/503 限流：不是账号坏，只是被 Google 临时限流。
                # 设短期冷却（期间降级不优先选），不累积失败、不标 expired。
                account.error_count += 1
                account.cooldown_until = asyncio.get_event_loop().time() + settings.failover_cooldown
                logger.warning(
                    f"Account {account.id} cooled down for {settings.failover_cooldown}s (5xx rate-limit)"
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

    def _pick_round_robin(self, available: list[Account]) -> Account:
        self._robin_index = self._robin_index % len(available)
        account = available[self._robin_index]
        self._robin_index = (self._robin_index + 1) % len(available)
        return account

    def _pick_failover(self, available: list[Account]) -> Account:
        for a in self._accounts:
            if a in available:
                return a
        return available[0]

    async def add_account(self, psid: str, psidts: str, label: str = "") -> Account:
        account_id = f"account-{len(self._accounts)}"
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
        for a in self._accounts:
            accounts_info.append({
                "id": a.id,
                "label": a.label,
                "psid": a.psid,
                "status": a.status.value,
                "request_count": a.request_count,
                "error_count": a.error_count,
                "active_requests": a.active_requests,
                "last_used": a.last_used.isoformat() if a.last_used else None,
                "cooling_down": a.cooldown_until > asyncio.get_event_loop().time(),
                "models": self.models if a.client else [],
                "models_count": len(self.models) if a.client else 0,
            })
        return {
            "total": self.total_count,
            "active": self.active_count,
            "strategy": self._strategy.value,
            "max_concurrent_per_account": self._max_concurrent,
            "accounts": accounts_info,
        }

    async def generate(self, prompt: str, model: str, conversation_id: str = "",
                       attachments: list | None = None) -> dict:
        # failover：某账号被可重试错误（5xx/未就绪/401·403）打回时，换下一个 active 账号重试，
        # 直到成功或无更多账号可试。5xx 限流账号进入冷却，401/403 标 expired。
        tried: set = set()
        last_err = None
        while True:
            try:
                account = await self.acquire(exclude=tried if tried else None)
            except RuntimeError:
                # 没有（更多）账号可用：抛出最后一次可重试错误（若有），否则抛 acquire 的错
                if last_err is not None:
                    raise last_err
                raise
            t0 = time.time()
            released = False
            try:
                result = await account.client.generate(prompt, model, conversation_id, attachments)
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                await self.release(account, success=True)
                released = True
                return result
            except Exception as e:
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                if _is_retryable(e):
                    # 可重试：5xx 冷却该账号、401/403 标 expired，换下一个账号重试
                    last_err = e
                    tried.add(account.id)
                    await self.release(account, success=False, cooldown=_is_5xx(e))
                    released = True
                    if isinstance(e, HTTPStatusError) and e.status_code in (401, 403):
                        account.status = AccountStatus.EXPIRED
                    logger.warning(f"Account {account.id} got {e}; failing over (tried={len(tried)})")
                    continue
                await self.release(account, success=False)
                released = True
                raise
            finally:
                # 兜底：CancelledError/GeneratorExit 等未走上面分支的路径也归还槽位（P0-4 防泄漏死锁）
                if not released:
                    await self.release(account, success=False)

    async def generate_stream(self, prompt: str, model: str, conversation_id: str = "",
                              attachments: list | None = None):
        """真流式：持有账号槽位直到整个流结束，再 release。
        逐块产出 {"type":"delta","text":增量} ，最后产出 {"type":"final", ...}（含会话ID/图片）。

        failover：仅在「尚未向客户端 yield 任何内容前」遇到可重试错误（5xx/未就绪/401·403）才换账号重试
        （已经吐出部分内容后再换账号会导致重复，故此时只能终止）。
        """
        tried: set = set()
        last_err = None
        while True:
            try:
                account = await self.acquire(exclude=tried if tried else None)
            except RuntimeError:
                if last_err is not None:
                    raise last_err
                raise
            t0 = time.time()
            emitted_any = False
            failover = False
            released = False
            try:
                async for evt in account.client.generate_stream(prompt, model, conversation_id, attachments):
                    emitted_any = True
                    yield evt
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                await self.release(account, success=True)
                released = True
                return
            except Exception as e:
                live_metrics.record_request(model, (time.time() - t0) * 1000)
                # 只有「还没吐任何内容」+「可重试」+「还有别的账号」才 failover
                if _is_retryable(e) and not emitted_any:
                    last_err = e
                    tried.add(account.id)
                    await self.release(account, success=False, cooldown=_is_5xx(e))
                    released = True
                    if isinstance(e, HTTPStatusError) and e.status_code in (401, 403):
                        account.status = AccountStatus.EXPIRED
                    logger.warning(f"Account {account.id} got {e} before first chunk; stream failing over (tried={len(tried)})")
                    failover = True
                else:
                    await self.release(account, success=False)
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
        # 对外永远是固定的公开模型名（API 稳定契约），
        # 内部由 _resolve_model 按账号真实可用模型动态映射。
        from app.core.gemini_client import PUBLIC_MODELS
        return list(PUBLIC_MODELS)

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
        path.write_text(json.dumps({"accounts": accounts_data}, indent=2, ensure_ascii=False))

    async def shutdown(self):
        for account in self._accounts:
            if account.client:
                await account.client.shutdown()
        logger.info("Account pool shut down")


account_pool = AccountPool()
