"""API 数据抓取模块 — SSRF 防护 + httpx 请求封装.

核心职责：
1. 安全地从用户给定的 URL 抓取 JSON 数据
2. 防御 SSRF（禁止访问内网 / localhost / 保留网段 / file:// 等）
3. 限制响应体大小、超时时间、重定向次数
4. 解析 JSON，支持 JSONPath-like 路径提取嵌套数据

对外统一入口：fetch_json()
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx2

logger = logging.getLogger(__name__)

# ── 配置常量 ──────────────────────────────────────

DEFAULT_TIMEOUT = 15.0  # 秒
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_REDIRECTS = 5
USER_AGENT = "cndb-api-importer/1.0 (+https://github.com/cndb)"

# JSON 数组候选路径（如果顶层不是数组，尝试这些字段名）
ARRAY_CANDIDATE_KEYS = (
    "data",
    "items",
    "results",
    "records",
    "list",
    "rows",
    "result",
    "payload",
    "entries",
)


# ── SSRF 防护 ────────────────────────────────────


def _is_private_or_reserved_ip(host: str) -> bool:
    """判断 host 解析后的所有 IP 是否有任何一个命中 SSRF 黑名单.

    精确的黑名单（不依赖 Python 的 is_private，避免误杀 Teredo/6to4 等公网可达的 IPv6）：

    IPv4:
    - 127.0.0.0/8 loopback
    - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (RFC1918 私有)
    - 169.254.0.0/16 link-local
    - 100.64.0.0/10 carrier-grade NAT
    - 0.0.0.0/8 当前网络
    - 224.0.0.0/4 multicast
    - 240.0.0.0/4 reserved

    IPv6:
    - ::1 loopback
    - fc00::/7 unique local (私有)
    - fe80::/10 link-local
    - ff00::/8 multicast
    - ::/8 unspecified
    - 注意：2001::/32 (Teredo) 和 2002::/16 (6to4) 虽 Python 判 is_private，
      但可以经由公网路由，不拦截.
    """
    # 黑名单网络集合
    BLOCKED_V4 = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
    ]
    BLOCKED_V6 = [
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("::/8"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("ff00::/8"),
    ]

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        logger.debug("DNS 解析失败: %s", host)
        return False

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        blocked_list = BLOCKED_V6 if isinstance(ip, ipaddress.IPv6Address) else BLOCKED_V4
        for net in blocked_list:
            if ip in net:
                logger.warning("SSRF 拦截：host=%s -> %s 命中 %s", host, ip_str, net)
                return True
    return False


def validate_url(url: str) -> None:
    """校验 URL 合法性 + SSRF 防护.

    Raises:
        ValueError: URL 不合法或命中 SSRF 黑名单.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL 必须是非空字符串")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https，当前 scheme={parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise ValueError("URL 缺少主机名")

    # 直接字面 IP 检查（用精确黑名单）
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if isinstance(ip, ipaddress.IPv4Address):
            blocked_networks = [
                ipaddress.ip_network("0.0.0.0/8"),
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("100.64.0.0/10"),
                ipaddress.ip_network("127.0.0.0/8"),
                ipaddress.ip_network("169.254.0.0/16"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("224.0.0.0/4"),
                ipaddress.ip_network("240.0.0.0/4"),
            ]
        else:
            blocked_networks = [
                ipaddress.ip_network("::1/128"),
                ipaddress.ip_network("::/8"),
                ipaddress.ip_network("fc00::/7"),
                ipaddress.ip_network("fe80::/10"),
                ipaddress.ip_network("ff00::/8"),
            ]
        for net in blocked_networks:
            if ip in net:
                raise ValueError(f"禁止访问保留 IP: {host}")
        return  # 合法公网 IP，放行

    # 不是 IP 字面量 — 域名
    if host.lower() in ("localhost", "0.0.0.0"):
        raise ValueError(f"禁止访问 {host}")
    # 也拦截指向内网的域名
    if _is_private_or_reserved_ip(host):
        raise ValueError(f"禁止访问解析到内网的主机: {host}")


# ── 数据类 ────────────────────────────────────────


@dataclass
class FetchConfig:
    """API 抓取配置."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: Any = None  # dict / str / bytes；dict 会自动 JSON 序列化
    timeout: float = DEFAULT_TIMEOUT
    max_bytes: int = MAX_BODY_BYTES
    max_redirects: int = MAX_REDIRECTS
    # 响应数据路径：如果响应不是直接的数组，用这个 path 定位数组
    # 支持 a.b.c 或 data[0].items 这样的简化语法
    data_path: str | None = None
    # 额外尝试的候选路径（当 data_path 未指定时）
    try_candidate_paths: bool = True


# ── 内部辅助 ─────────────────────────────────────


def _resolve_path(data: Any, path: str) -> Any:
    """用简化的 a.b.c[0].x 语法提取嵌套值.

    不处理复杂的 filter/wildcard，只做 attr + index 链式访问.
    """
    node = data
    for part in path.split("."):
        if not part:
            continue
        # 处理 part 内部的 [idx]
        while "[" in part:
            name, rest = part.split("[", 1)
            if name:
                if isinstance(node, dict):
                    node = node.get(name)
                else:
                    return None
            idx_str, rest = rest.split("]", 1)
            try:
                idx = int(idx_str)
            except ValueError:
                return None
            if not isinstance(node, list) or idx >= len(node):
                return None
            node = node[idx]
            part = rest
        if part:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        if node is None:
            return None
    return node


def _extract_array(payload: Any, data_path: str | None, try_candidates: bool) -> list[dict[str, Any]]:
    """从任意 JSON 响应中提取对象数组.

    策略：
    1. 若 payload 本身就是对象数组 → 直接返回
    2. 若指定 data_path → 用 path 提取
    3. 否则依次尝试 data/items/results/... 等常见字段
    4. 以上均不命中 → 把 payload 包成 [{...}] 单行返回（退化处理）

    关键设计：一旦**明确找到**了数组容器（哪怕空的），就返回（空数组），
    不再退化。退化仅用于"整个响应根本不是数组"的情况。
    """
    explicit_list_found = False

    if isinstance(payload, list):
        explicit_list_found = True
        rows = [r for r in payload if isinstance(r, dict)]
        if rows:
            return rows

    if data_path:
        found = _resolve_path(payload, data_path)
        if isinstance(found, list):
            explicit_list_found = True
            rows = [r for r in found if isinstance(r, dict)]
            if rows:
                return rows

    if try_candidates and isinstance(payload, dict):
        for key in ARRAY_CANDIDATE_KEYS:
            val = payload.get(key)
            if isinstance(val, list):
                explicit_list_found = True
                rows = [r for r in val if isinstance(r, dict)]
                if rows:
                    return rows
            # 递归一层：对所有顶级 key 的 dict 值，再尝试候选 key
            if isinstance(val, dict):
                for sub_key in ARRAY_CANDIDATE_KEYS:
                    sub_val = val.get(sub_key)
                    if isinstance(sub_val, list):
                        explicit_list_found = True
                        rows = [r for r in sub_val if isinstance(r, dict)]
                        if rows:
                            return rows

        # 补充：对所有顶级 key 做一次递归候选查找（覆盖 response.results 这类）
        for key, val in payload.items():
            if key in ARRAY_CANDIDATE_KEYS:
                continue  # 已处理
            if isinstance(val, dict):
                for sub_key in ARRAY_CANDIDATE_KEYS:
                    sub_val = val.get(sub_key)
                    if isinstance(sub_val, list):
                        explicit_list_found = True
                        rows = [r for r in sub_val if isinstance(r, dict)]
                        if rows:
                            return rows

    # 明确找到数组容器但过滤后为空 → 返回空数组（表示真的没有数据）
    if explicit_list_found:
        return []

    # 退化处理：非数组顶层对象 → 包成单行返回
    if isinstance(payload, dict):
        return [payload]
    return []


# ── 主入口 ────────────────────────────────────────


def fetch_json(config: FetchConfig) -> list[dict[str, Any]]:
    """按配置发起 HTTP 请求并返回对象数组.

    Returns:
        对象数组（空数组代表响应未包含有效数据）

    Raises:
        ValueError: URL 非法 / SSRF / 响应解析失败
        httpx2.HTTPError: 网络层错误
    """
    validate_url(config.url)

    method = config.method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ValueError(f"不支持的 HTTP 方法: {method}")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.1"}
    headers.update(config.headers or {})

    # body 处理
    content: str | bytes | None = None
    json_body: Any = None
    if config.body is not None:
        if isinstance(config.body, (dict, list)):
            json_body = config.body
        elif isinstance(config.body, str):
            content = config.body
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif isinstance(config.body, bytes):
            content = config.body
        else:
            raise ValueError("body 必须是 dict / list / str / bytes")

    with httpx2.Client(
        timeout=config.timeout,
        max_redirects=config.max_redirects,
        headers=headers,
    ) as client:
        try:
            resp = client.request(
                method=method,
                url=config.url,
                params=config.params or None,
                content=content,
                json=json_body,
            )
        except httpx2.TooManyRedirects as exc:
            raise ValueError(f"重定向次数过多（>{config.max_redirects}）: {exc}") from exc
        except httpx2.RequestError as exc:
            raise ValueError(f"请求失败: {exc}") from exc

        # 检查状态码
        if resp.status_code >= 400:
            raise ValueError(
                f"API 返回 {resp.status_code}: {resp.text[:200]}"
            )

        # 检查响应大小
        body = resp.content
        if len(body) > config.max_bytes:
            raise ValueError(
                f"响应体过大 ({len(body)} bytes > {config.max_bytes})"
            )

        # Content-Type 软检查
        ct = (resp.headers.get("content-type") or "").lower()
        if ct and "json" not in ct and "javascript" not in ct:
            logger.warning("响应 Content-Type=%s，尝试仍按 JSON 解析", ct)

        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"响应不是合法 JSON: {exc}") from exc

        return _extract_array(payload, config.data_path, config.try_candidate_paths)


__all__ = [
    "ARRAY_CANDIDATE_KEYS",
    "DEFAULT_TIMEOUT",
    "MAX_BODY_BYTES",
    "MAX_REDIRECTS",
    "USER_AGENT",
    "FetchConfig",
    "_extract_array",
    "_is_private_or_reserved_ip",
    "_resolve_path",
    "fetch_json",
    "validate_url",
]
