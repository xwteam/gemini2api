"""共享限流器实例。

独立模块，供 app.main 与各业务路由共同导入，避免 main ↔ routers 循环导入。
默认 settings.rate_limit_enabled=False：限流装饰器经 exempt_when 全部旁路，
行为与未挂限流前完全一致（零回归）。仅当运维显式开启后才按 rate_limit_max/window 生效。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(key_func=get_remote_address)


def dynamic_rate_limit() -> str:
    """运行时动态限流值（每请求求值），格式 "<max>/<window> second"。

    用 callable 而非常量，使面板在线修改 rate_limit_max/window 后即时生效。
    """
    return f"{settings.rate_limit_max}/{settings.rate_limit_window} second"


def rate_limit_exempt(*args, **kwargs) -> bool:
    """限流未开启时旁路（默认 rate_limit_enabled=False → 返回 True → 不计数、不限流）。"""
    return not settings.rate_limit_enabled
