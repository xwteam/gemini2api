"""本次请求命中的访问密钥（AccessKey）的请求级上下文。

为什么用 ContextVar 而不是把 `allowed_account_ids` 一路透传给 generate/generate_stream：
那两个方法在 5 个协议路由里有 30+ 个调用点，其中 research.py 的几处连 FastAPI 的
Request 对象都拿不到（参数名被 Pydantic 模型遮蔽）。ContextVar 在 verify_api_key
（全局依赖）里设置一次，同一个 asyncio 任务里的端点函数、它 create_task 出来的子任务、
以及 StreamingResponse 的生成器迭代都能读到，且天然按请求隔离——每个请求在自己的
任务里跑，contextvars 在任务创建时复制，互不串写。

没有访问密钥（env API_KEY 直连，或一把访问密钥都没签发）时，取值恒为 None，
所有下游判断都是一次 `is None` 短路，零开销、零行为变化。
"""

from contextvars import ContextVar
from typing import Optional

from fastapi import HTTPException

from app.core.access_key_store import AccessKey

_current_access_key: ContextVar[Optional[AccessKey]] = ContextVar(
    "current_access_key", default=None
)


def set_current_access_key(entry: Optional[AccessKey]) -> None:
    _current_access_key.set(entry)


def get_current_access_key() -> Optional[AccessKey]:
    return _current_access_key.get()


def current_bound_account_ids() -> Optional[set]:
    """本次请求允许使用的账号 id 集合；None = 不限制。"""
    entry = _current_access_key.get()
    if entry is None:
        return None
    return entry.bound_account_set()


def current_allowed_models() -> Optional[set]:
    """本次请求允许使用的模型名集合；None = 不限制。"""
    entry = _current_access_key.get()
    if entry is None:
        return None
    return entry.allowed_model_set()


def _strip_models_prefix(name: str) -> str:
    return name[7:] if name.startswith("models/") else name


def ensure_model_allowed(*names: str) -> None:
    """访问密钥限定了模型时，本次请求的模型必须命中其中之一，否则 403。

    传入「客户端原样请求的模型名」和「别名/Gem 解析后的模型名」，任一命中即放行：
    管理员在面板上勾的是模型列表里的名字，而客户端可能用别名调用同一个模型。
    """
    allowed = current_allowed_models()
    if allowed is None:
        return
    candidates = {_strip_models_prefix(str(n)) for n in names if n}
    if candidates & allowed:
        return
    requested = next((str(n) for n in names if n), "")
    raise HTTPException(
        status_code=403,
        detail={
            "error": {
                "message": f"Model '{requested}' is not allowed for this access key.",
                "type": "access_key_model_denied",
            }
        },
    )


def filter_models_for_access_key(models) -> list:
    """按访问密钥的 allowed_models 过滤模型列表（在 MODEL_WHITELIST 之后再叠一层）。"""
    allowed = current_allowed_models()
    if allowed is None:
        return list(models)
    return [m for m in models if _strip_models_prefix(str(m)) in allowed]
