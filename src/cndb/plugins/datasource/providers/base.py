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

from cndb.core.http import DEFAULT_TIMEOUT, FetchConfig

# 增量策略（M2 落地实现，M1 仅作为 provider 元信息对外暴露）
# backfill_date（ADR 0034 D2）：按标的回补水位——每 entrant 独立记「已回补到的最早日期」，
# 请求按水位生成 end 锚点，响应内最早日期推进水位（只向更早前移、不后退），backfill_start 截断收敛
CursorStrategy = Literal["date", "datetime", "key_set", "none", "backfill_date"]
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
    # 候选主机（ADR 0053 D4）：声明后 url_template 用 {host} 占位，按序尝试，
    # 主主机网络错误 / 429 / 5xx 时切下一个；空 = 单 URL 旧行为
    url_hosts: tuple[str, ...] = ()
    headers_template: Mapping[str, str] = field(default_factory=dict)
    params_template: Mapping[str, Any] = field(default_factory=dict)
    body_template: Any = None
    # 响应路径：支持 {entrant} 等模板占位符（按标的嵌套的响应，如 data.{entrant}.qfqday）
    data_path: str | None = None
    # 记录形态：
    # - rows        响应里直接是对象数组
    # - columns     响应是「列名 → 数组」的对象（Open-Meteo / 部分行情接口的
    #               daily.time[] / daily.temp[] 形态），需按列拼行
    # - rows_array  响应数组的每一项是**行数组**（如腾讯日线 [["日期","开","收",...]]），
    #               需按 record_layout 的位置索引拼成对象
    record_mode: Literal["rows", "columns", "rows_array"] = "rows"
    # 列式映射：
    # - columns 模式 {目标列名: 源键}
    # - rows_array 模式 {目标列名: 位置索引(int)}
    # 缺省（columns）把 data_path 对象下的所有数组键当列
    record_layout: Mapping[str, str | int] = field(default_factory=dict)
    # 行级常量列（响应不回显来源维度时使用，如多源同表补「来源 / 复权方式」）；
    # 语义为 setdefault：响应自带同名值优先，不被配置覆盖；
    # 值支持 {today} 等模板变量（ADR 0034 D4，快照写当日行用）
    row_defaults: Mapping[str, Any] = field(default_factory=dict)
    # 行过滤（ADR 0034 D4）：{"field","op","value"} 单个数值条件，归一后剔除不满足的行
    # （如停牌标的零值快照行）；None = 不过滤
    row_filter: Mapping[str, Any] | None = None
    # 请求并发数（ADR 0034 D5）：>1 时 plans 组间并发抓取；默认 1 行为与串行一致
    workers: int = 1
    encoding: str = "utf-8"
    timeout: float = DEFAULT_TIMEOUT
    paging: PagingSpec = field(default_factory=PagingSpec)
    time_window: TimeWindowSpec = field(default_factory=TimeWindowSpec)
    # 大模型专用声明（其它 provider 忽略）：提示词与模型参数，见 ADR 0014
    prompt: Mapping[str, Any] = field(default_factory=dict)
    llm: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url_template:
            raise ProviderError("request.url_template 不能为空")
        _validate_url_hosts(self.url_template, self.url_hosts)
        if self.workers < 1:
            raise ProviderError("request.workers 必须 >= 1")
        if self.row_filter is not None:
            _validate_row_filter(self.row_filter)


def _validate_url_hosts(url_template: str, url_hosts: tuple[str, ...]) -> None:
    """校验 URL 模板与候选主机声明（ADR 0053 D4）.

    单 URL：模板本身必须是 http(s) 地址；
    声明 ``url_hosts``：模板须含 ``{host}``，每个候选必须是 http(s) 基地址。
    """
    if not url_hosts:
        if not url_template.startswith(("http://", "https://")):
            raise ProviderError("request.url_template 必须是 http/https URL")
        return
    if "{host}" not in url_template:
        raise ProviderError("声明 url_hosts 时 request.url_template 必须含 {host} 占位符")
    for host in url_hosts:
        text = str(host or "").strip()
        if not text.startswith(("http://", "https://")):
            raise ProviderError(f"request.url_hosts 中的主机必须是 http/https 基地址: {host!r}")


def _validate_row_filter(row_filter: Mapping[str, Any]) -> None:
    """校验行过滤声明：``{"field","op","value"}``，op 限数值比较六种（ADR 0034 D4）."""
    field = str(row_filter.get("field") or "")
    if not field:
        raise ProviderError("row_filter.field 不能为空")
    op = str(row_filter.get("op") or "")
    if op not in (">", ">=", "<", "<=", "==", "!="):
        raise ProviderError(f"row_filter.op 非法: {op!r}")
    value = row_filter.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("row_filter.value 必须是数值")


@dataclass(frozen=True, slots=True)
class FieldTransform:
    """字段归一指令：改名 + 目标类型 + 可选数值缩放.

    ``scale`` 用于统一同一目标列的量纲（如腾讯成交量以「手」返回，表内存「股」则填 100）。
    只对 int / float 生效，其它类型原样归一（见 ``services/normalize.py``）。
    """

    name: str
    field_type: str = "text"
    scale: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ProviderError("field_mapping 的目标字段名不能为空")
        if self.scale is not None and not isinstance(self.scale, (int, float)):
            raise ProviderError("field_mapping.scale 必须是数值")


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
    # 标的集合已显式解析但为空（backfill_date 全部达 ``backfill_start`` / 来源清单尚无行）：
    # build_requests 应返回零请求，而不是回退成单条 entrant 为空的伪请求
    entrants_exhausted: bool = False
    # 按标的 end 锚点（ADR 0034 D2，backfill_date 游标）：entrant → 锚点日期串；
    # 非空时注入模板变量 {end}（该标的水位 − 1 天），达 backfill_start 的标的不出现在这里
    entrant_ends: Mapping[str, str] = field(default_factory=dict)
    match_keys: tuple[str, ...] = ()
    field_mapping: Mapping[str, FieldTransform | None] = field(default_factory=dict)
    # 行级常量列（setdefault 语义），由 run_pipeline 并入每行；缺省取 request.row_defaults
    row_defaults: Mapping[str, Any] = field(default_factory=dict)
    parser: str = "json"
    # 额外模板变量（M5：凭证会话的密钥，如 {"api_key": "..."}）；内置变量优先，避免被配置覆盖
    extra_variables: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entrant_values and not self.entrant_param:
            raise ProviderError("配置了 entrant_values 时必须同时给出 entrant_param")
        # 常量列未显式给出时，回落到 request 声明（build_job_spec 无需二次搬运）
        if not self.row_defaults and self.request.row_defaults:
            object.__setattr__(self, "row_defaults", dict(self.request.row_defaults))
        # 容忍 {"字段": {"name": .., "field_type": ..}} 这种 JSON 形态（DB / API 直传），
        # 统一规范成 FieldTransform，避免下游拿到 dict 才炸
        if self.field_mapping:
            object.__setattr__(self, "field_mapping", normalize_field_mapping(self.field_mapping))


@dataclass(frozen=True, slots=True)
class RequestPlan:
    """一次具体请求：已求值的 FetchConfig + 追溯标签（运行记录 / 错误定位用）."""

    config: FetchConfig
    label: str
    entrant: str | None = None
    page: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    # 响应元信息（模型名 / token 用量等），由 provider 的响应处理器写入，随运行记录留痕
    metadata: dict[str, Any] = field(default_factory=dict)
    # ADR 0020：plan 级抓取器；None = 走全局 fetch / fetch_json。LLM 请求经平台客户端注入，
    # 使重试 / SSRF 白名单只作用于该 provider，其它 provider 行为不变
    fetcher: FetchFn | None = None


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
            scale=_optional_float(transform.get("scale")),
        )
    return normalized


def _optional_float(value: Any) -> float | None:
    """把 JSON 里的可选数值声明转成 float；``None`` / 空串视为未声明."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ProviderError("field_mapping.scale 必须是数值")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"field_mapping.scale 必须是数值: {value!r}") from exc


class SourceProvider(Protocol):
    """数据源适配器协议.

    实现只需三步中的一到两步：默认的 ``normalize`` 已能覆盖声明式场景，
    专用 provider 可覆写 ``parse``（特殊响应格式）或 ``build_requests``（特殊鉴权 / 分页）。
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
