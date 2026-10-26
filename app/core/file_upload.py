"""
Gemini Web 文件/图片上传模块。

把二进制文件上传到 content-push.googleapis.com，返回文件标识符，
该标识符随后注入 StreamGenerate 的 f.req payload。

上传与对话必须用同一账号的同一会话（同 cookies），因此本模块的函数
都由 GeminiWebClient._send_request 在选定账号后调用，不在路由层单独上传。
"""
import asyncio
import logging

from app.utils.net_guard import is_safe_url, resolve_redirect_location

logger = logging.getLogger(__name__)

UPLOAD_URL = "https://content-push.googleapis.com/upload"

MAX_REMOTE_SIZE = 20 * 1024 * 1024  # 远程 URL 下载上限 20MB
MAX_REMOTE_REDIRECTS = 5  # 手动跟随重定向的最大跳数，防 SSRF 重定向链绕过


async def _resolve_bytes(http, att: dict) -> tuple[bytes, str, str] | None:
    """把 attachment 描述解析为 (data, filename, mime)。
    data URI 已在 prompt.extract_attachments 解码为 bytes；
    http(s) URL 在这里下载（限制大小，防 SSRF）。
    """
    filename = att.get("filename", "upload.bin")
    mime = att.get("mime", "") or "application/octet-stream"

    if "data" in att and att["data"] is not None:
        return att["data"], filename, mime

    url = att.get("url")
    if not url:
        return None
    try:
        resp = await _safe_remote_get(http, url)
        if resp is None:
            return None
        if resp.status_code != 200:
            logger.warning(f"[upload] remote fetch {resp.status_code}: {url[:80]}")
            return None
        # 大小限制（VULN-005）：先看 Content-Length 头，再以实际字节兜底，
        # 防止超大响应被完整缓冲后才发现超限
        clen = resp.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > MAX_REMOTE_SIZE:
            logger.warning(f"[upload] remote file too large (content-length={clen}): {url[:80]}")
            return None
        data = resp.content
        if len(data) > MAX_REMOTE_SIZE:
            logger.warning(f"[upload] remote file too large ({len(data)} bytes): {url[:80]}")
            return None
        if not mime or mime == "application/octet-stream":
            ct = resp.headers.get("content-type", "")
            if ct:
                mime = ct.split(";")[0].strip()
        return data, filename, mime
    except Exception as e:
        logger.warning(f"[upload] remote fetch failed: {e}")
        return None


async def _safe_remote_get(http, url: str):
    """带 SSRF 防护地下载远程 URL：禁用自动重定向，对初始 URL 及每一跳的
    Location 都重新跑 assert_safe_url（VULN-005 重定向绕过修复）。

    curl_cffi 默认跟随重定向，攻击者可让一个公网 URL 302 到
    http://169.254.169.254/... 等内网/元数据地址绕过单次预检；
    因此这里 allow_redirects=False，把每一跳的目标重新校验后才手动跟随，
    并限制最大跳数。返回最终响应；任一跳不安全则返回 None。
    """
    current = url
    for _ in range(MAX_REMOTE_REDIRECTS + 1):
        # 对每个将要实际请求的 URL 做内网/环回/链路本地/元数据校验
        if not is_safe_url(current):
            logger.warning(f"[upload] blocked unsafe remote url: {current[:80]}")
            return None
        resp = await http.get(current, timeout=30, allow_redirects=False)
        # 3xx：取 Location，解析为绝对地址后回到循环顶部重新校验再跟随
        if 300 <= resp.status_code < 400:
            location = resp.headers.get("location")
            if not location:
                logger.warning(f"[upload] redirect without location: {current[:80]}")
                return None
            current = resolve_redirect_location(current, location)
            continue
        return resp
    logger.warning(f"[upload] too many redirects: {url[:80]}")
    return None


# 上传遇到网络错误 / 5xx 时再试的次数与间隔（4xx 是请求本身的问题，重试没用）。过去一次失败就把
# 附件静默丢掉，模型看不到图却照样回答。
UPLOAD_RETRIES = 1
UPLOAD_RETRY_DELAY = 1.0


async def upload_file(http, cookies: dict, base_headers: dict, push_id: str,
                      data: bytes, filename: str, mime: str) -> str | None:
    """上传单个文件，返回 Gemini 的文件标识符（形如 /contrib_service/ttl_1d/...）。
    失败返回 None；网络错误 / 5xx 会先重试 UPLOAD_RETRIES 次。
    """
    for attempt in range(UPLOAD_RETRIES + 1):
        file_id, retryable = await _upload_once(http, cookies, push_id, data, filename, mime)
        if file_id or not retryable or attempt >= UPLOAD_RETRIES:
            return file_id
        logger.warning(f"[upload] {filename} failed (transient), retrying in {UPLOAD_RETRY_DELAY:.0f}s")
        await asyncio.sleep(UPLOAD_RETRY_DELAY)
    return None


async def _upload_once(http, cookies: dict, push_id: str, data: bytes, filename: str,
                       mime: str) -> tuple[str | None, bool]:
    """传一次：返回 (file_id 或 None, 失败是否值得重试)。"""
    # 极简 header（对齐 HanaokaYuzu/Gemini-API 实测可用的协议）：
    # 只要 Origin/Referer/X-Tenant-Id/Push-ID，不要任何 X-Goog-Upload-* 和指纹基础头，
    # 否则 Google 按 resumable 协议解析导致 "Multipart body does not contain 2 or 3 parts"
    headers = {
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "X-Tenant-Id": "bard-storage",
        "Push-ID": push_id or "feeds/mcudyrk2a4khkz",
    }

    try:
        from curl_cffi import CurlMime
        mime_form = CurlMime()
        mime_form.addpart(
            name="file",
            content_type=mime,
            filename=filename,
            data=data,
        )
        resp = await http.post(
            UPLOAD_URL,
            multipart=mime_form,
            cookies=cookies,
            headers=headers,
            timeout=60,
        )
        if resp.status_code != 200:
            logger.error(f"[upload] {filename} returned {resp.status_code}: {resp.text[:160]}")
            return None, resp.status_code >= 500
        file_id = resp.text.strip()
        if not file_id:
            logger.error(f"[upload] {filename} empty response")
            return None, True
        logger.info(f"[upload] {filename} -> {file_id[:48]}")
        return file_id, False
    except Exception as e:
        logger.error(f"[upload] {filename} failed: {e}")
        return None, True


async def upload_files(http, cookies: dict, base_headers: dict, push_id: str,
                       attachments: list[dict]) -> list[tuple[str, str]]:
    """并发上传多个附件，返回 [(file_id, filename), ...]，顺序与输入一致。
    任一失败则跳过该文件（不中断其它）。
    """
    if not attachments:
        return []

    async def _one(att):
        resolved = await _resolve_bytes(http, att)
        if not resolved:
            return None
        data, filename, mime = resolved
        fid = await upload_file(http, cookies, base_headers, push_id, data, filename, mime)
        return (fid, filename) if fid else None

    results = await asyncio.gather(*[_one(a) for a in attachments])
    return [r for r in results if r]
