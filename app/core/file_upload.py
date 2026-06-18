"""
Gemini Web 文件/图片上传模块。

把二进制文件上传到 content-push.googleapis.com，返回文件标识符，
该标识符随后注入 StreamGenerate 的 f.req payload。

上传与对话必须用同一账号的同一会话（同 cookies），因此本模块的函数
都由 GeminiWebClient._send_request 在选定账号后调用，不在路由层单独上传。
"""
import asyncio
import logging

from app.utils.net_guard import is_safe_url

logger = logging.getLogger(__name__)

UPLOAD_URL = "https://content-push.googleapis.com/upload"

MAX_REMOTE_SIZE = 20 * 1024 * 1024  # 远程 URL 下载上限 20MB


async def _resolve_bytes(http, att: dict) -> tuple[bytes, str, str] | None:
    """把 attachment 描述解析为 (data, filename, mime)。
    data URI 已在 prompt.extract_attachments 解码为 bytes；
    http(s) URL 在这里下载（限制大小，防 SSRF 留给上层网络策略）。
    """
    filename = att.get("filename", "upload.bin")
    mime = att.get("mime", "") or "application/octet-stream"

    if "data" in att and att["data"] is not None:
        return att["data"], filename, mime

    url = att.get("url")
    if not url:
        return None
    # SSRF 防护（VULN-005）：拒绝指向内网/环回/链路本地/云元数据的远程附件 URL，公网 http(s) 正常放行
    if not is_safe_url(url):
        logger.warning(f"[upload] blocked unsafe remote url: {url[:80]}")
        return None
    try:
        resp = await http.get(url, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"[upload] remote fetch {resp.status_code}: {url[:80]}")
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


async def upload_file(http, cookies: dict, base_headers: dict, push_id: str,
                      data: bytes, filename: str, mime: str) -> str | None:
    """上传单个文件，返回 Gemini 的文件标识符（形如 /contrib_service/ttl_1d/...）。
    失败返回 None。
    """
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
            return None
        file_id = resp.text.strip()
        if not file_id:
            logger.error(f"[upload] {filename} empty response")
            return None
        logger.info(f"[upload] {filename} -> {file_id[:48]}")
        return file_id
    except Exception as e:
        logger.error(f"[upload] {filename} failed: {e}")
        return None


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
