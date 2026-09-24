"""API 数据抓取模块 — SSRF 防护 + httpx 请求封装.

核心职责：
1. 安全地从用户给定的 URL 抓取数据（JSON 或自定义格式）
2. 防御 SSRF（禁止访问内网 / localhost / 保留网段 / file:// 等）
3. 限制响应体大小、超时时间、重定向次数
4. 内置响应处理器机制：默认 JSON 处理器 + 腾讯股票等专用处理器

响应处理器（response_handler）机制：
- 默认: "json" — 标准 JSON 响应（现有逻辑）
- "tencent_stock": 腾讯实时股票快照的 "v_xxx=\"a~b~c~...\"" 格式
- 也可传自定义 callable(response_text, fetch_config) -> list[dict]

对外统一入口：fetch_json()
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx2

logger = logging.getLogger(__name__)

# ── 配置常量 ──────────────────────────────────────

DEFAULT_TIMEOUT = 15.0  # 秒
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_REDIRECTS = 5
USER_AGENT = "cndb-api-importer/1.0 (+https://github.com/cndb)"

# 查询间隔常量（秒）
DEFAULT_QUERY_INTERVAL = 60  # 默认每分钟 1 次
MIN_QUERY_INTERVAL = 6  # 最短每 6 秒 1 次（每分钟不超过 10 次）

# ── 响应处理器注册表 ──────────────────────────────

ResponseHandler = Callable[[str, "FetchConfig"], list[dict[str, Any]]]

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
    if host.lower() in ("localhost", "0.0.0.0"):  # nosec B104 - 仅做本机地址字符串比较，非绑定
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
    # 响应处理器：
    # - 字符串 "json"（默认）：标准 JSON 解析
    # - 字符串 "tencent_stock"：腾讯实时股票快照格式
    # - 自定义 callable(text, FetchConfig) -> list[dict]
    response_handler: str | ResponseHandler = "json"
    # 响应编码：默认 utf-8；腾讯股票为 gbk
    encoding: str = "utf-8"
    # 查询间隔（秒），用于定时刷新场景；默认 60 秒
    query_interval: float = DEFAULT_QUERY_INTERVAL


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


# ── 响应处理器 ─────────────────────────────────────

# 腾讯股票快照字段定义（按 ~ 分隔的索引位置）
# 参考：https://blog.csdn.net/u013326689/article/details/126557827
TENCENT_STOCK_FIELDS = [
    ("unknown", "text"),  # 0: 恒为 1
    ("stock_name", "text"),  # 1: 股票名称
    ("stock_code", "text"),  # 2: 股票代码
    ("current_price", "float"),  # 3: 当前价格
    ("prev_close", "float"),  # 4: 昨收
    ("open_price", "float"),  # 5: 今开
    ("volume_lots", "number"),  # 6: 成交量（手）
    ("outer_volume", "number"),  # 7: 外盘
    ("inner_volume", "number"),  # 8: 内盘
    ("bid1_price", "float"),  # 9: 买一价
    ("bid1_volume", "number"),  # 10: 买一量
    ("bid2_price", "float"),  # 11: 买二价
    ("bid2_volume", "number"),  # 12: 买二量
    ("bid3_price", "float"),  # 13: 买三价
    ("bid3_volume", "number"),  # 14: 买三量
    ("bid4_price", "float"),  # 15: 买四价
    ("bid4_volume", "number"),  # 16: 买四量
    ("bid5_price", "float"),  # 17: 买五价
    ("bid5_volume", "number"),  # 18: 买五量
    ("ask1_price", "float"),  # 19: 卖一价
    ("ask1_volume", "number"),  # 20: 卖一量
    ("ask2_price", "float"),  # 21: 卖二价
    ("ask2_volume", "number"),  # 22: 卖二量
    ("ask3_price", "float"),  # 23: 卖三价
    ("ask3_volume", "number"),  # 24: 卖三量
    ("ask4_price", "float"),  # 25: 卖四价
    ("ask4_volume", "number"),  # 26: 卖四量
    ("ask5_price", "float"),  # 27: 卖五价
    ("ask5_volume", "number"),  # 28: 卖五量
    ("unknown2", "text"),  # 29: 空
    ("timestamp", "datetime"),  # 30: 时间戳 YYYYMMDDHHmmss
    ("change_amount", "float"),  # 31: 涨跌额
    ("change_percent", "float"),  # 32: 涨跌幅 %
    ("high_price", "float"),  # 33: 最高
    ("low_price", "float"),  # 34: 最低
    ("summary", "text"),  # 35: 价格/成交量/成交额 合成串
    ("volume", "number"),  # 36: 成交量（手）
    ("amount_wan", "float"),  # 37: 成交额（万元）
    ("turnover_rate", "float"),  # 38: 换手率 %
    ("pe_ratio", "float"),  # 39: 市盈率
    ("unknown3", "text"),  # 40: 空
    ("high52w", "float"),  # 41: 52周最高
    ("low52w", "float"),  # 42: 52周最低
    ("amplitude", "float"),  # 43: 振幅 %
    ("circulating_mv", "float"),  # 44: 流通市值（亿）
    ("total_mv", "float"),  # 45: 总市值（亿）
    ("pb_ratio", "float"),  # 46: 市净率
]

# 编译正则：v_sh600519="..." 或 v_sz000001="..."
_TENCENT_STOCK_RE = re.compile(r'v_(\w+)="([^"]*)"')


def _parse_tencent_stock(text: str, _config: FetchConfig) -> list[dict[str, Any]]:
    """解析腾讯实时股票快照响应.

    响应格式：
        v_sh600519="1~贵州茅台~600519~1277.96~...";
        v_sz000001="1~平安银行~000001~12.34~...";

    Returns:
        股票数据字典数组
    """
    results: list[dict[str, Any]] = []
    for match in _TENCENT_STOCK_RE.finditer(text):
        raw_code = match.group(1)  # e.g. "sh600519"
        raw_values = match.group(2)  # e.g. "1~贵州茅台~600519~..."

        if not raw_values:
            continue

        parts = raw_values.split("~")
        row: dict[str, Any] = {}

        # 先放股票标识符
        row["symbol"] = raw_code  # sh600519 / sz000001
        row["market"] = raw_code[:2].upper()  # SH / SZ

        # 按字段定义映射
        for idx, (field_name, field_type) in enumerate(TENCENT_STOCK_FIELDS):
            if idx >= len(parts):
                break
            raw_val = parts[idx]
            if raw_val == "" or raw_val is None:
                row[field_name] = None
                continue
            # 类型转换
            try:
                if field_type == "number":
                    row[field_name] = int(float(raw_val))
                elif field_type == "float":
                    row[field_name] = float(raw_val)
                elif field_type == "datetime":
                    # YYYYMMDDHHmmss → YYYY-MM-DD HH:mm:ss
                    ts = raw_val
                    if len(ts) == 14:
                        row[field_name] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
                    else:
                        row[field_name] = raw_val
                else:
                    row[field_name] = raw_val
            except (ValueError, TypeError):
                row[field_name] = raw_val  # 转换失败保留原值

        results.append(row)

    return results


# 响应处理器注册表
RESPONSE_HANDLERS: dict[str, ResponseHandler] = {
    "tencent_stock": _parse_tencent_stock,
}


def _get_response_handler(name_or_callable: str | ResponseHandler) -> ResponseHandler:
    """根据名称或 callable 获取响应处理器.

    - "json": 返回 None（表示走 fetch_json 原有的 JSON 解析逻辑）
    - 已注册名称: 返回对应 handler
    - callable: 直接返回
    """
    if callable(name_or_callable):
        return name_or_callable
    if name_or_callable == "json":
        return None  # type: ignore[return-value]  # 标记：使用默认 JSON 逻辑
    if name_or_callable in RESPONSE_HANDLERS:
        return RESPONSE_HANDLERS[name_or_callable]
    raise ValueError(f"未知的响应处理器: {name_or_callable!r}，可选: 'json', {list(RESPONSE_HANDLERS)}")


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
        follow_redirects=False,
        headers=headers,
    ) as client:
        try:
            current_url = config.url
            resp: httpx2.Response | None = None
            params_value = config.params or None
            redirect_count = 0
            while True:
                resp = client.request(
                    method=method,
                    url=current_url,
                    params=params_value,
                    content=content,
                    json=json_body,
                )
                # 3xx 重定向：手动跟随 + 每步 validate_url（防 SSRF via open redirect）
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    if redirect_count > config.max_redirects:
                        raise ValueError(f"重定向次数过多（>{config.max_redirects}）")
                    location = resp.headers.get("location")
                    if not location:
                        raise ValueError(f"重定向响应缺少 Location 头（status={resp.status_code}）")
                    # 相对 URL 转绝对
                    next_url = urljoin(current_url, location)
                    validate_url(next_url)
                    current_url = next_url
                    # 303 一律降级为 GET；301/302 多数客户端也降级为 GET（兼容）
                    if resp.status_code == 303 or (
                        resp.status_code in (301, 302) and method in ("POST", "PUT", "PATCH", "DELETE")
                    ):
                        method = "GET"
                        content = None
                        json_body = None
                    continue
                break
        except httpx2.RequestError as exc:
            raise ValueError(f"请求失败: {exc}") from exc
        resp = cast(httpx2.Response, resp)  # 上面循环至少执行一次并 break，必非空

        # 检查状态码
        if resp.status_code >= 400:
            raise ValueError(f"API 返回 {resp.status_code}: {resp.text[:200]}")

        # 检查响应大小
        body = resp.content
        if len(body) > config.max_bytes:
            raise ValueError(f"响应体过大 ({len(body)} bytes > {config.max_bytes})")

        # 按指定编码解码（腾讯股票用 gbk）
        text = body.decode(config.encoding, errors="replace")

        # 根据 response_handler 选择解析策略
        handler = _get_response_handler(config.response_handler)
        if handler is not None:
            # 自定义处理器（如腾讯股票）
            return handler(text, config)

        # 默认 JSON 解析
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"响应不是合法 JSON: {exc}") from exc

        return _extract_array(payload, config.data_path, config.try_candidate_paths)


def validate_query_interval(interval: float | int) -> float:
    """校验查询间隔并夹取到合法范围.

    规则：
    - 默认值 DEFAULT_QUERY_INTERVAL（60秒 / 每分钟1次）
    - 最小值 MIN_QUERY_INTERVAL（6秒 / 每分钟不超过10次）
    - 传入 0 或负数 → 使用默认值

    Returns:
        夹取后的有效间隔（float）
    """
    if interval is None or interval <= 0:
        return DEFAULT_QUERY_INTERVAL
    clamped = max(MIN_QUERY_INTERVAL, float(interval))
    if clamped != float(interval):
        logger.info("查询间隔 %.1fs 被夹取到最小值 %.1fs", interval, MIN_QUERY_INTERVAL)
    return clamped


__all__ = [
    "ARRAY_CANDIDATE_KEYS",
    "DEFAULT_QUERY_INTERVAL",
    "DEFAULT_TIMEOUT",
    "MAX_BODY_BYTES",
    "MAX_REDIRECTS",
    "MIN_QUERY_INTERVAL",
    "RESPONSE_HANDLERS",
    "TENCENT_STOCK_FIELDS",
    "USER_AGENT",
    "FetchConfig",
    "_extract_array",
    "_get_response_handler",
    "_is_private_or_reserved_ip",
    "_parse_tencent_stock",
    "_resolve_path",
    "fetch_json",
    "validate_query_interval",
    "validate_url",
]
