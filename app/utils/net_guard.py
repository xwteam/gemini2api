"""SSRF 防护（VULN-004 / VULN-005）。

校验出站 URL 的目标主机不指向私网 / 环回 / 链路本地（含云元数据 169.254.169.254）/
保留地址。对域名做 DNS 解析并逐个检查解析到的 IP，缓解 DNS rebinding。

注意：assert_safe_url 内部调用阻塞式 socket.getaddrinfo（DNS 一般很快、OS 有缓存），
在异步路径中是短暂阻塞；安全收益（拦截内网/元数据）大于该开销。
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """目标 URL 不允许：协议非法，或解析到内网/环回/链路本地/保留地址。"""


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # 取不到合法 IP，保守拦截
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_url(url: str, *, allowed_schemes=("http", "https")) -> None:
    """校验出站 URL；不安全抛 UnsafeURLError。公网 http(s) 地址正常放行（不误伤）。"""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("empty url")
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in allowed_schemes:
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("missing host")
    default_port = 443 if scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError:
        raise UnsafeURLError("invalid port")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"dns resolution failed: {e}")
    if not infos:
        raise UnsafeURLError("host did not resolve")
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            raise UnsafeURLError(f"target resolves to blocked address: {ip}")


def is_safe_url(url: str, *, allowed_schemes=("http", "https")) -> bool:
    """布尔版校验，便于在不想处理异常的调用点使用。"""
    try:
        assert_safe_url(url, allowed_schemes=allowed_schemes)
        return True
    except UnsafeURLError:
        return False
