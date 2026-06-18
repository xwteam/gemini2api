import logging
import secrets
from pathlib import PurePosixPath

from fastapi import Request, HTTPException

from app.config import settings

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

    if not _key_matches(key, settings.api_key):
        raise _invalid_key_error()


async def verify_admin_key(request: Request):
    """管理面板/admin 路由鉴权。配置了 admin_api_key 则校验它，否则回退 api_key（默认单 key 全功能，零回归）。"""
    path = request.url.path

    if _is_public_path(path):
        return

    admin_key = (settings.admin_api_key or "").strip()
    expected = admin_key if admin_key else settings.api_key

    key = _extract_request_key(request)
    if not key:
        raise _missing_key_error()

    if not _key_matches(key, expected):
        raise _invalid_key_error()
