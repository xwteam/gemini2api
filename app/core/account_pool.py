import json
import time
import asyncio
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.gemini_client import GeminiWebClient
from app.config import settings
from app.core.usage_metrics import live_metrics

logger = logging.getLogger(__name__)


class AccountStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"
    REFRESHING = "refreshing"


class RotationStrategy(str, Enum):
    ROUND_ROBIN = "round-robin"
    LEAST_USED = "least-used"


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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    client: GeminiWebClient | None = field(default=None, repr=False)


class AccountPool:
    def __init__(self):
        self._accounts: list[Account] = []
        self._lock = asyncio.Lock()
        self._robin_index = 0
        self._strategy = RotationStrategy(settings.rotation_strategy)
        self._max_concurrent = settings.max_concurrent_per_account

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

    async def acquire(self) -> Account:
        async with self._lock:
            available = [
                a for a in self._accounts
                if a.status == AccountStatus.ACTIVE
                and a.active_requests < self._max_concurrent
            ]
            if not available:
                raise RuntimeError("No available accounts")

            if self._strategy == RotationStrategy.ROUND_ROBIN:
                account = self._pick_round_robin(available)
            else:
                account = self._pick_least_used(available)

            account.active_requests += 1
            account.last_used = datetime.now(timezone.utc)
            return account

    def release(self, account: Account, success: bool):
        account.active_requests = max(0, account.active_requests - 1)
        account.request_count += 1
        if success:
            account.consecutive_failures = 0
        else:
            account.error_count += 1
            account.consecutive_failures += 1
            if account.consecutive_failures >= 3:
                account.status = AccountStatus.EXPIRED
                logger.warning(f"Account {account.id} marked expired after 3 consecutive failures")

    def _pick_round_robin(self, available: list[Account]) -> Account:
        self._robin_index = self._robin_index % len(available)
        account = available[self._robin_index]
        self._robin_index = (self._robin_index + 1) % len(available)
        return account

    def _pick_least_used(self, available: list[Account]) -> Account:
        return min(available, key=lambda a: (a.active_requests, a.request_count))

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

    def set_strategy(self, strategy: str):
        self._strategy = RotationStrategy(strategy)

    def set_max_concurrent(self, value: int):
        self._max_concurrent = value

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
                "models": list(a.client.models) if a.client else [],
                "models_count": len(a.client.models) if a.client else 0,
            })
        return {
            "total": self.total_count,
            "active": self.active_count,
            "strategy": self._strategy.value,
            "max_concurrent_per_account": self._max_concurrent,
            "accounts": accounts_info,
        }

    async def generate(self, prompt: str, model: str, conversation_id: str = "") -> dict:
        account = await self.acquire()
        t0 = time.time()
        try:
            result = await account.client.generate(prompt, model, conversation_id)
            latency_ms = (time.time() - t0) * 1000
            live_metrics.record_request(model, latency_ms)
            self.release(account, success=True)
            return result
        except Exception as e:
            latency_ms = (time.time() - t0) * 1000
            live_metrics.record_request(model, latency_ms)
            self.release(account, success=False)
            raise

    @property
    def models(self) -> list[str]:
        all_models = set()
        for a in self._accounts:
            if a.status == AccountStatus.ACTIVE and a.client:
                all_models.update(a.client.models)
        if not all_models:
            from app.core.gemini_client import _load_models_cache, KNOWN_MODELS
            cached = _load_models_cache()
            return cached if cached else list(KNOWN_MODELS)
        return sorted(all_models)

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
