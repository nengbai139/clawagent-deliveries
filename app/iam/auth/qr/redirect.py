"""redirect_uri 白名单校验。

规则（投标方案已定口径）：
- 只按「规范化后的完整 URL」比较（scheme、host、path、query），不做前缀匹配；
- host 不同但 path 相同 ⇒ 不在白名单；
- 多带 query 参数 ⇒ 不在白名单（除非白名单条目完全一致）；
- 白名单条目末尾带斜杠 ⇒ 先规范化再比较；
- 白名单为空 ⇒ fail-closed（不放行）。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app.core.errors import error_body


def normalize_redirect_uri(value: str | None) -> str | None:
    """把 redirect_uri 规范化；非法输入返回 None。"""
    if not value or not isinstance(value, str):
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    # fragment 不会发给服务端，比较时忽略
    return urlunsplit((scheme, host, path, parts.query, ""))


def normalize_allowlist(allowlist: tuple[str, ...] | list[str]) -> list[str]:
    normalized = []
    for item in allowlist:
        value = normalize_redirect_uri(item)
        if value:
            normalized.append(value)
    return normalized


def is_redirect_uri_allowed(value: str, allowlist: tuple[str, ...] | list[str]) -> bool:
    """value 是否在白名单内（按规范化后的完整值精确比较）。"""
    normalized = normalize_redirect_uri(value)
    if normalized is None:
        return False
    return normalized in normalize_allowlist(allowlist)


def allowlist_error(allowlist: tuple[str, ...] | list[str]) -> dict:
    """白名单为空时的错误体（fail-closed）。"""
    return error_body(
        "redirect_allowlist_not_configured",
        "redirect_uri 白名单未配置（APP_QR_REDIRECT_ALLOWLIST 为空），已按 fail-closed 拒绝",
    )


def redirect_not_allowed_error() -> dict:
    return error_body("redirect_uri_not_allowed", "redirect_uri 不在白名单内")
