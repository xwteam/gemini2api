import logging
import secrets
from pathlib import PurePosixPath

from fastapi import Request, HTTPException

from app.config import settings
from app.core import access_key_store as access_key_store_module
from app.core.access_context import set_current_access_key

logger = logging.getLogger(__name__)


STATIC_EXTENSIONS = {".html", ".css", ".js", ".ico", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ttf"}

# 所有管理类路由统一挂在 /admin/* 前缀下；这些路径由 verify_admin_key 负责校验，
# 全局 verify_api_key 对其放行以避免双重校验冲突（设置独立 admin_api_key 后两把 key 不同会互相误拒）。
ADMIN_PATH_PREFIX = "/admin"


def _is_public_path(path: str) -> bool:
    """无需鉴权即可访问的路径（与原 verify_api_key 放行逻辑逐字节一致）。"""
    if path == "/health":
        return True
    if path in ("/", "/login.html", "/index.html"):
        return True
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in STATIC_EXTENSIONS:
        return True
    if path.startswith("/app/") or path.startswith("/components/"):
        return True
    return False


def _extract_request_key(request: Request) -> str:
    """按既有优先级提取调用方提供的 key：Bearer → x-api-key → ?token=。"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:].strip()
        if key:
            return key

    key = request.headers.get("x-api-key", "").strip()
    if key:
        return key

    return request.query_params.get("token", "").strip()


def _key_matches(provided: str, expected: str) -> bool:
    """恒定时间比较，避免时序侧信道（VULN-011）。非 ASCII 也安全（按 utf-8 字节比较）。"""
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _missing_key_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"error": {"message": "Missing API key. Use Authorization: Bearer sk-xxx or x-api-key header.", "type": "auth_error"}},
    )


def _invalid_key_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"error": {"message": "Invalid API key.", "type": "auth_error"}},
    )


# 访问密钥的非法状态 → (status, message, type)。各态文案不同，运维/用户一眼能看出
# 是"被停用"还是"过期了"还是"额度用完了"，而不是一律 "Invalid API key" 猜半天。
_ACCESS_KEY_ERRORS = {
    access_key_store_module.STATE_DISABLED: (
        403, "This access key has been disabled.", "access_key_disabled",
    ),
    access_key_store_module.STATE_EXPIRED: (
        403, "This access key has expired.", "access_key_expired",
    ),
    access_key_store_module.STATE_QUOTA_EXCEEDED: (
        429, "This access key has reached its request limit.", "access_key_quota_exceeded",
    ),
}


def _access_key_error(state: str) -> HTTPException:
    status, message, error_type = _ACCESS_KEY_ERRORS[state]
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": error_type}},
    )


async def verify_api_key(request: Request):
    """业务 API 全局鉴权。管理类路径(/admin/*)交由 verify_admin_key 校验，此处放行避免双重校验。"""
    path = request.url.path

    if _is_public_path(path):
        return

    # 管理类路由由 verify_admin_key（在 include_router 时挂载）负责，避免与独立 admin_api_key 冲突
    if path.startswith(ADMIN_PATH_PREFIX):
        return

    key = _extract_request_key(request)
    if not key:
        raise _missing_key_error()

    # .env 的 API_KEY 永远全权有效，且命中后立刻返回：不查访问密钥库、不挂上下文、
    # 不计任何用量 —— 这条路径与本功能引入前逐字节一致。
    if _key_matches(key, settings.api_key):
        return

    store = access_key_store_module.access_key_store
    if not store.has_keys():
        # 一把访问密钥都没签发：异常类型/文案/状态码与改动前完全相同。
        raise _invalid_key_error()

    # 计数口径是「这把 key 已发起的请求数」：在入口原子 +1，单调不减、不退还。
    # 本服务没有成本概念（网页版反代），单次消费恒为 1、入口即已知，所以不需要
    # kiro2api 那套「预留-对账」；也就不存在"上游 5xx 要不要退款""流式中途断要不要退"
    # 这类扯皮，以及预留泄漏需要超时回收的新故障面。
    state, entry = store.validate_and_consume(key)
    if state == access_key_store_module.STATE_NOT_FOUND:
        raise _invalid_key_error()
    if state in _ACCESS_KEY_ERRORS:
        raise _access_key_error(state)

    set_current_access_key(entry)
    request.state.access_key = entry


async def verify_admin_key(request: Request):
    """管理面板/admin 路由鉴权。配置了 admin_api_key 则校验它，否则回退 api_key（默认单 key 全功能，零回归）。

    这里**绝不能**像 verify_api_key 那样对 _is_public_path() 放行：那个函数是按文件后缀
    白名单判的（.js/.css/.png/...），而本依赖只挂在 /admin/* 路由上。最后一段路径由
    调用方控制的管理端点（例如 DELETE /admin/model-mapping/{name}）只要把名字写成
    `evil.js`，就能无凭据执行——管理面的那道门直接开着。静态资源不走这个依赖，
    去掉这段放行不影响面板加载。
    """
    admin_key = (settings.admin_api_key or "").strip()
    expected = admin_key if admin_key else settings.api_key

    key = _extract_request_key(request)
    if not key:
        raise _missing_key_error()

    if not _key_matches(key, expected):
        raise _invalid_key_error()
