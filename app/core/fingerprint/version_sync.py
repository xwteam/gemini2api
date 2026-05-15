"""Chrome 版本自动同步 — 后台定期检查并更新指纹配置"""

import asyncio
import logging

from app.core.fingerprint.config import fingerprint_config

logger = logging.getLogger(__name__)

VERSION_CHECK_URL = (
    "https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/stable/versions"
    "?filter=version>100&order_by=version%20desc&page_size=1"
)

CHECK_INTERVAL = 24 * 3600


async def check_latest_chrome_version() -> tuple[int, str] | None:
    """查询 Google 版本 API 获取最新稳定版 Chrome 版本号"""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(timeout=15) as session:
            resp = await session.get(VERSION_CHECK_URL)
            if resp.status_code != 200:
                logger.warning(f"版本检查失败: HTTP {resp.status_code}")
                return None
            data = resp.json()
            versions = data.get("versions", [])
            if not versions:
                return None
            full_version = versions[0]["version"]
            major = int(full_version.split(".")[0])
            return major, full_version
    except Exception as e:
        logger.error(f"Chrome 版本检查异常: {e}")
        return None


async def validate_impersonate_target(target: str) -> bool:
    """验证 curl_cffi AsyncSession 是否真正支持该 impersonate 目标（发起实际请求）"""
    try:
        from curl_cffi.requests import AsyncSession
        s = AsyncSession(impersonate=target, timeout=10)
        resp = await s.get("https://www.google.com/")
        await s.close()
        return resp.status_code == 200
    except Exception:
        return False


async def find_best_target(major: int) -> str | None:
    """为给定 Chrome 版本找到最佳 impersonate 目标（精确匹配 > 最近低版本）"""
    cfg = fingerprint_config.config
    target = cfg.version_map.get(str(major))
    if target and await validate_impersonate_target(target):
        return target
    for v in sorted((int(k) for k in cfg.version_map.keys()), reverse=True):
        if v <= major:
            fallback = cfg.version_map[str(v)]
            if await validate_impersonate_target(fallback):
                logger.info(f"Chrome {major} 无精确目标，降级使用 {fallback}")
                return fallback
    return None


async def version_sync_loop():
    """后台版本同步循环"""
    await asyncio.sleep(60)

    while True:
        try:
            result = await check_latest_chrome_version()
            if result:
                major, full = result
                current = fingerprint_config.config.chrome.major
                if major > current:
                    target = await find_best_target(major)
                    if target:
                        fingerprint_config.config.version_map[str(major)] = target
                        fingerprint_config.update_chrome_version(major, full)
                        logger.info(f"Chrome 版本已更新: {current} -> {major} (target: {target})")
                    else:
                        logger.info(f"检测到 Chrome {major}，但 curl_cffi 暂不支持，保持 {current}")
                else:
                    logger.debug(f"Chrome 版本无变化: {current}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"版本同步异常: {e}")

        await asyncio.sleep(CHECK_INTERVAL)
