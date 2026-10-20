"""管理面板改动的跨重启持久化（overrides 层）。

**为什么只写 .env 不够**：项目自带的 docker-compose.yml 用 ``env_file: .env`` 把宿主机
的 .env 注入成**真实环境变量**，而 pydantic-settings 里 ``os.environ`` 的优先级高于
dotenv 文件；同时 compose 只挂载了 ``./data`` 和 ``./api``，宿主机那份 .env 在容器里根本
不可见 —— ``_update_env_file`` 写的是容器内临时的 /app/.env。于是面板上改完提示"保存
成功"，``docker compose restart`` 之后值又变回宿主机 .env 里的旧值。对
LOG_BODIES_ENABLED 这种隐私开关来说，"以为关掉了、其实重启后又在记录用户完整提示词"
是不可接受的。

**修法**：面板改动同时落到 ``data/settings-overrides.json``。``data/`` 是 compose 里
bind-mount 的持久目录（``data/api-keys.json`` / ``data/logs.json`` /
``data/model-mapping.json`` 都住这儿），并在 ``app/config.py`` 构造完 ``Settings()``
之后立刻回放，优先级高于环境变量 —— 运行时的显式改动本来就应该压过部署期默认值。
被回放的字段会在启动日志里点名，方便运维排查"改了 .env 为什么不生效"。

本模块刻意不 import ``app.config`` / ``app.core.account_pool``（它们都反过来依赖本模块
或 config），只依赖标准库和 ``app.utils.atomic_io``，避免循环导入。
"""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# data/ 在 docker-compose 里是 bind mount（./data:/app/data），重启/升级都不丢。
OVERRIDES_PATH = Path("data/settings-overrides.json")

# 允许通过管理面板修改、并因此允许被持久化/回放的字段白名单。
EDITABLE_FIELDS = {
    "refresh_interval",
    "max_retries",
    "rate_limit_enabled",
    "rate_limit_window",
    "rate_limit_max",
    "health_check_enabled",
    "health_check_interval",
    "rotation_strategy",
    "max_concurrent_per_account",
    "usage_stats_enabled",
    "usage_stats_interval",
    "usage_stats_retention_days",
    "jitter_enabled",
    "version_sync_enabled",
    "chat_cleanup_enabled",
    "chat_cleanup_keep_hours",
    "chat_cleanup_interval_hours",
    "chat_cleanup_skip_pinned",
    "extended_thinking_enabled",
    "log_bodies_enabled",
}

# 字段声明类型，用于类型校验与 JSON 数值收敛。
FIELD_TYPES = {
    "refresh_interval": int,
    "max_retries": int,
    "rate_limit_enabled": bool,
    "rate_limit_window": int,
    "rate_limit_max": int,
    "health_check_enabled": bool,
    "health_check_interval": int,
    "rotation_strategy": str,
    "max_concurrent_per_account": int,
    "usage_stats_enabled": bool,
    "usage_stats_interval": int,
    "usage_stats_retention_days": int,
    "jitter_enabled": bool,
    "version_sync_enabled": bool,
    "chat_cleanup_enabled": bool,
    "chat_cleanup_keep_hours": float,
    "chat_cleanup_interval_hours": float,
    "chat_cleanup_skip_pinned": bool,
    "extended_thinking_enabled": bool,
    "log_bodies_enabled": bool,
}

# 这些字段语义上是计数/间隔，必须为非负（其中并发上限至少为 1）。
NON_NEGATIVE_FIELDS = {
    "max_retries",
    "rate_limit_window",
    "rate_limit_max",
    "health_check_interval",
    "usage_stats_interval",
    "usage_stats_retention_days",
    "chat_cleanup_keep_hours",
    "chat_cleanup_interval_hours",
}
POSITIVE_FIELDS = {
    "max_concurrent_per_account",  # 并发上限必须 >= 1
    # Cookie 刷新间隔也必须 >= 1：0 过去是合法值（面板上"填 0 表示关掉"是很自然的直觉），
    # 而 _auto_refresh_loop 的 `asyncio.sleep(0)` 不产生任何延迟 —— 那条循环会退化成以网络
    # RTT 为唯一节流的热循环，对每个账号无限制地重复 RotateCookies + 3 个 GET + 心跳。
    # client 侧还有 MIN_REFRESH_INTERVAL_MINUTES 的下限兜底（.env 不经过这里）。
    "refresh_interval",
}

# RotationStrategy 枚举的合法取值。这里刻意硬编码而不 import app.core.account_pool
# （那会循环导入 app.config）；tests/unit/test_settings_overrides.py 有守卫测试断言
# 本集合与 RotationStrategy 枚举一致，枚举一变就会红。
ROTATION_STRATEGIES = {"round-robin", "failover"}

_PathLike = Optional[Union[str, Path]]


def _resolve(path: _PathLike) -> Path:
    return Path(path) if path is not None else OVERRIDES_PATH


def coerce_value(key: str, value: Any) -> Tuple[bool, Any]:
    """把外部（JSON）来的值收敛到字段声明的类型。返回 ``(是否合法, 收敛后的值)``。

    JSON 没有 int/float 之分：24 和 24.0 在线上都可能是 ``24``，所以 float 字段必须
    接受 int 并转成 float。bool 是 int 的子类但语义完全不同，对 int/float 字段必须
    显式拒绝，否则 JSON ``true`` 会被当成合法数字写进配置、破坏下次启动。
    """
    expected = FIELD_TYPES.get(key)
    if expected is None:
        return False, value
    if expected in (int, float) and isinstance(value, bool):
        return False, value
    if expected is float and isinstance(value, int):
        return True, float(value)
    if not isinstance(value, expected):
        return False, value
    return True, value


def check_domain(key: str, value: Any) -> Optional[str]:
    """取值域校验。合法返回 None，否则返回给用户看的错误原因。

    只做类型检查不够：type-correct 但取值非法的值（如 rotation_strategy='garbage'、
    负数间隔）会被持久化，并在下次启动时让 ``RotationStrategy(...)`` / ``Settings()``
    构造抛异常，永久 brick 启动。
    """
    # NaN / ±Infinity 都是合法的 Python float，且 `nan < 0` / `inf < 0` 都是 False，
    # 会一路通过下面的比较。json 模块两端都认这些非 RFC-8259 字面量，于是它们能
    # 原样写进 settings-overrides.json 并在每次启动被回放（还压过环境变量）：
    # chat_cleanup_interval_hours=inf 会让 asyncio.sleep(inf) 永不唤醒，清理循环
    # 从此静默停摆，而且改环境变量也救不回来。
    if isinstance(value, float) and not math.isfinite(value):
        return f"Setting '{key}' must be a finite number"
    if key in NON_NEGATIVE_FIELDS and value < 0:
        return f"Setting '{key}' must be >= 0"
    if key in POSITIVE_FIELDS and value < 1:
        return f"Setting '{key}' must be >= 1"
    if key == "rotation_strategy" and value not in ROTATION_STRATEGIES:
        return f"Setting 'rotation_strategy' must be one of {sorted(ROTATION_STRATEGIES)}"
    return None


def load_overrides(path: _PathLike = None) -> Dict[str, Any]:
    """读取持久化的面板改动。文件缺失/损坏/结构异常一律返回 {}，绝不阻断启动。"""
    target = _resolve(path)
    try:
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — 任何读取/解析失败都必须降级成"没有覆盖值"
        logger.warning(f"Ignoring unreadable settings overrides at {target}: {e}")
        return {}
    if not isinstance(data, dict):
        logger.warning(f"Ignoring settings overrides at {target}: expected a JSON object")
        return {}
    return {k: v for k, v in data.items() if k in EDITABLE_FIELDS}


def save_overrides(updates: Dict[str, Any], path: _PathLike = None) -> None:
    """把面板改动合并进持久化文件（原子写）。只接受白名单内字段。"""
    target = _resolve(path)
    merged = load_overrides(target)
    accepted = {k: v for k, v in updates.items() if k in EDITABLE_FIELDS}
    if not accepted:
        return
    merged.update(accepted)
    atomic_write_json(target, merged, indent=2)
    logger.info(f"Persisted {len(accepted)} panel setting(s) to {target}")


def apply_overrides(target_settings: Any, path: _PathLike = None) -> Dict[str, Any]:
    """把持久化的面板改动回放到 settings 单例上，返回实际生效的 {字段: 值}。

    每个值都重新过一遍类型收敛 + 取值域校验：手改坏的文件只会被逐条忽略并告警，
    不会把服务 brick 在启动阶段。
    """
    applied: Dict[str, Any] = {}
    for key, value in load_overrides(path).items():
        ok, coerced = coerce_value(key, value)
        if not ok:
            logger.warning(f"Ignoring settings override {key}={value!r}: wrong type")
            continue
        reason = check_domain(key, coerced)
        if reason is not None:
            logger.warning(f"Ignoring settings override {key}={value!r}: {reason}")
            continue
        if not hasattr(target_settings, key):
            logger.warning(f"Ignoring settings override {key!r}: not a known setting")
            continue
        # pydantic 模型默认不可变，绕过写入（与面板热更新走的是同一条路径）。
        object.__setattr__(target_settings, key, coerced)
        applied[key] = coerced
    return applied
