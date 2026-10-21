"""Provider 抽象 —— 请求构造 / 响应解析 / 字段归一的接口与配置数据结构.

四层抽象（见 ADR 0006「分层与唯一入口」）：

    SourceProvider  代码级适配器，注册进 PROVIDERS
    SyncJobSpec     一次同步的完整声明（M1 为纯内存对象，M2 由 datasource_sync_job 还原）
    Cursor          增量位置（M2 落地，本阶段只用 TimeWindowSpec 表达区间）
    Normalizer      字段映射 + 类型归一（services/normalize.py）

本模块只依赖 tables 插件的抓取内核（FetchConfig），不出现任何领域词
（symbol / city / stock），领域差异一律由 job 配置表达。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from cndb.plugins.tables.services.importing.api_fetch import DEFAULT_TIMEOUT, FetchConfig

# 增量策略（M2 落地实现，M1 仅作为 provider 元信息对外暴露）
CursorStrategy = Literal["date", "datetime", "key_set", "none"]
# 分页方式：none / page（页码递增）/ offset（偏移量递增）
PagingMode = Literal["none", "page", "offset"]
# 时间区间方式：none / range（按 start/end 参数注入，可再按 chunk_days 切片）
TimeWindowMode = Literal["none", "range"]


class ProviderError(ValueError):
    """Provider 配置或解析错误（请求模板缺参、响应格式不符等）."""


@dataclass(frozen=True, slots=True)
class PagingSpec:
    """声明式分页参数.

    ``max_pages`` 是硬上限，防止对不限页码的源无限翻页；运行期遇到空页会提前终止。
    """

    mode: PagingMode = "none"
    page_param: str = "page"
    size_param: str = "page_size"
    page_size: int = 50
    start_page: int = 1
    max_pages: int = 100

    def __post_init__(self) -> None:
        if self.mode != "none" and self.max_pages < 1:
            raise ProviderError("paging.max_pages 必须 >= 1")
        if self.mode != "none" and self.page_size < 1:
            raise ProviderError("paging.page_size 必须 >= 1")


@dataclass(frozen=True, slots=True)
class TimeWindowSpec:
    """声明式时间区间.

    ``start`` / ``end`` 是本轮的抓取区间（M2 由 cursor 推进得出）；
    ``chunk_days > 0`` 时按天切片逐个请求，用于接口对单次区间长度有限制的场景。
    """

    mode: TimeWindowMode = "none"
    start_param: str = "start_date"
    end_param: str = "end_date"
    date_format: str = "%Y-%m-%d"
    chunk_days: int = 0
    start: str = ""
    end: str = ""

    def __post_init__(self) -> None:
        if self.mode == "none":
            return
        if not self.start or not self.end:
            raise ProviderError("time_window 为 range 时必须提供 start 与 end")
        if self.chunk_days < 0:
            raise ProviderError("time_window.chunk_days 不能为负")


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """请求模板：占位符在运行时由 SyncJobSpec 求值（只做字面替换，不求值表达式）."""

    url_template: str
    method: str = "GET"
    headers_template: Mapping[str, str] = field(default_factory=dict)
    params_template: Mapping[str, Any] = field(default_factory=dict)
    body_template: Any = None
    data_path: str | None = None
    # 记录形态：rows = 响应里直接是对象数组；columns = 响应是「列名 → 数组」的对象
    # （Open-Meteo / 部分行情接口的 daily.time[] / daily.temp[] 形态），需按列拼行
    record_mode: Literal["rows", "columns"] = "rows"
    # 列式映射：{目标列名: 源键}；缺省把 data_path 对象下的所有数组键当列
    record_layout: Mapping[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"
    timeout: float = DEFAULT_TIMEOUT
    paging: PagingSpec = field(default_factory=PagingSpec)
    time_window: TimeWindowSpec = field(default_factory=TimeWindowSpec)

    def __post_init__(self) -> None:
        if not self.url_template:
            raise ProviderError("request.url_template 不能为空")
        # baostock:// 是非 HTTP 传输（provider 自带 fetch_plan，不走 fetch_json），
        # 只作为「任务声明入口」的占位协议，白名单显式列出，不放任意 scheme
        if not self.url_template.startswith(("http://", "https://", "baostock://")):
            raise ProviderError("request.url_template 必须是 http/https/baostock URL")


@dataclass(frozen=True, slots=True)
class FieldTransform:
    """字段归一指令：改名 + 目标类型."""

    name: str
    field_type: str = "text"

    def __post_init__(self) -> None:
        if not self.name:
            raise ProviderError("field_mapping 的目标字段名不能为空")


@dataclass(frozen=True, slots=True)
class SyncJobSpec:
    """一次同步任务的完整声明（与数据库模型解耦，便于单测直接构造）.

    Attributes:
        entrant_param: 标的占位符名（如 ``symbol`` / ``city``）；留空表示单次全量请求。
        entrant_values: 标的取值集合；每个取值各自成组抓取、共用同一份游标区间。
        match_keys: 幂等键（目标字段名），交由 Importer 做 upsert 判定。
        field_mapping: 源字段 → 目标字段（``None`` 表示丢弃该字段）。
    """

    request: RequestSpec
    provider: str = "http_json"
    entrant_param: str | None = None
    entrant_values: tuple[str, ...] = ()
    match_keys: tuple[str, ...] = ()
    field_mapping: Mapping[str, FieldTransform | None] = field(default_factory=dict)
    parser: str = "json"
    # 额外模板变量（M5：凭证会话的密钥，如 {"api_key": "..."}）；内置变量优先，避免被配置覆盖
    extra_variables: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entrant_values and not self.entrant_param:
            raise ProviderError("配置了 entrant_values 时必须同时给出 entrant_param")
        # 容忍 {"字段": {"name": .., "field_type": ..}} 这种 JSON 形态（DB / API 直传），
        # 统一规范成 FieldTransform，避免下游拿到 dict 才炸
        if self.field_mapping:
            object.__setattr__(self, "field_mapping", normalize_field_mapping(self.field_mapping))


@dataclass(frozen=True, slots=True)
class RequestPlan:
    """一次具体请求：已求值的 FetchConfig + 追溯标签（运行记录 / 错误定位用）.

    ``variables`` 是本请求求值后的模板变量快照，供自带传输的 provider
    （如 ``baostock_kline`` 走 TCP 而非 HTTP）在 ``fetch_plan`` 里取参，
    避免再从 URL 字符串反解。
    """

    config: FetchConfig
    label: str
    entrant: str | None = None
    page: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    variables: Mapping[str, Any] = field(default_factory=dict)


def normalize_field_mapping(
    mapping: Mapping[str, FieldTransform | Mapping[str, Any] | None],
) -> dict[str, FieldTransform | None]:
    """把 JSON 形态的字段映射规范成 ``FieldTransform``；``None`` 表示丢弃该字段."""
    normalized: dict[str, FieldTransform | None] = {}
    for source, transform in mapping.items():
        if transform is None or isinstance(transform, FieldTransform):
            normalized[source] = transform
            continue
        normalized[source] = FieldTransform(
            name=str(transform.get("name") or source),
            field_type=str(transform.get("field_type") or "text"),
        )
    return normalized


class SourceProvider(Protocol):
    """数据源适配器协议.

    实现只需三步中的一到两步：默认的 ``normalize`` 已能覆盖声明式场景，
    专用 provider 可覆写 ``parse``（特殊响应格式）或 ``build_requests``（特殊鉴权 / 分页）。

    非 HTTP 数据源（如 baostock 的 TCP 会话）额外实现 ``fetch_plan(plan)``：
    管线检测到该方法即优先调用它，不再执行 ``fetch_json(plan.config)``。
    """

    name: str
    label: str
    params_schema: Mapping[str, Any]
    default_cursor: CursorStrategy
    supports_paging: bool

    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]:
        """把 job 声明展开成一组具体请求（含分页 / 时间切片）."""
        ...

    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        """响应文本 → 对象数组；格式不符抛 ProviderError."""
        ...

    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeLike:
        """字段映射 + 类型归一；转换失败按字段降级为 None 并留痕."""
        ...


class NormalizeLike(Protocol):
    """normalize 返回值的最小契约（避免 base 反向依赖 services 实现）."""

    @property
    def rows(self) -> list[dict[str, Any]]: ...

    @property
    def dropped(self) -> int: ...

    @property
    def failures(self) -> Sequence[Any]: ...


FetchFn = Callable[["FetchConfig"], list[dict[str, Any]]]


__all__ = [
    "CursorStrategy",
    "FetchFn",
    "FieldTransform",
    "NormalizeLike",
    "PagingMode",
    "PagingSpec",
    "ProviderError",
    "RequestPlan",
    "RequestSpec",
    "SourceProvider",
    "SyncJobSpec",
    "TimeWindowMode",
    "TimeWindowSpec",
    "normalize_field_mapping",
]
