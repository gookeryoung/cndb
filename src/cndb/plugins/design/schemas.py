"""design 插件请求 / 响应模型（ADR 0079 D6 / D7、ADR 0086 §4）.

详情口径（ADR 0086 D10）：详情**移除** ``compiled``（唯一破坏性变更，打开
性能路径改为 ``GET /{id}/ir`` + ETag）；文件身份字段 kind / file_key / folder
与依赖陈旧标记为超集扩展。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DesignCreate(BaseModel):
    """新建设计文件：原文必经编译，失败 400（I2）；part 创建即 v1（ADR 0086 §4）."""

    title: str = Field(min_length=1, max_length=200, description="设计名称（同目录内唯一）")
    content: str = Field(default="", description="结构 DSL 原文（.cnmd），可为空（空为合法程序）")
    description: str = Field(default="", max_length=500, description="用途说明")
    kind: Literal["part", "assembly"] = Field(default="assembly", description="文件类型：part=零件 / assembly=装配")
    file_key: str | None = Field(
        default=None, min_length=1, max_length=64, description="稳定文件标识（缺省由标题生成并去重）"
    )
    folder: str = Field(default="", max_length=200, description="展示目录（相对路径 a/b，仅分组）")


class DesignUpdate(BaseModel):
    """改名 / 描述 / 目录（None = 不改；不触发重编译；file_key 不可改）."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    folder: str | None = Field(default=None, max_length=200)


class DesignContentSave(BaseModel):
    """保存原文：编译通过才落库并生成新版本（失败旧 IR 不动，边界 #2）.

    ``change_type``（ADR 0113 D10）：客户端仅可请求 ``manual`` / ``auto``；
    ``refresh`` / ``rollback`` 由服务端在对应端点强制赋值。
    """

    content: str = Field(description="结构 DSL 原文")
    comment: str = Field(default="", max_length=200, description="版本备注")
    change_type: Literal["manual", "auto"] = Field(
        default="manual", description="版本来源：manual 主动保存 / auto 自动保存"
    )


class PreviewRequest(BaseModel):
    """即时编译（无落库）：编辑器防抖与参数面板共用（D3）.

    ``design_id``（ADR 0086 §4）：编辑中的文件，用于解析 ``use`` 引用与
    kind 语义；缺省仅接受无 ``use`` 的单文件内容。
    """

    content: str = Field(description="结构 DSL 原文")
    overrides: dict[str, float] | None = Field(default=None, description="参数覆盖（param 面板改参重编译）")
    design_id: int | None = Field(default=None, description="编辑中的设计文件（同工作区），用于解析引用")


class DesignPublishRequest(BaseModel):
    """发布为复用模块（ADR 0118 §4）：默认私有，公开需显式选择."""

    visibility: Literal["public", "workspace"] = Field(default="workspace", description="可见性：public / workspace")
    name: str | None = Field(default=None, min_length=1, max_length=200, description="模块展示名（缺省用设计标题）")
    description: str | None = Field(default=None, max_length=500, description="模块说明")
    comment: str = Field(default="", max_length=200, description="本次发布备注")


class DesignPublishResponse(BaseModel):
    """发布结果：稳定 module_key + 新版本号（ADR 0118 §4）."""

    module_id: int
    module_key: str
    version_number: int
    visibility: str
    name: str


class LibraryModuleItem(BaseModel):
    """复用模块列表项（ADR 0118 §6）：最新版本与可见性标记."""

    id: int
    module_key: str
    name: str
    description: str = ""
    visibility: str
    owner_workspace_id: int | None = None
    is_archived: bool = False
    version_count: int = 0
    latest_version: int = 0
    params: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: Any = None


class LibraryVersionItem(BaseModel):
    """模块版本列表项：哈希 / 备注 / 时间（不含原文与依赖包全文）."""

    id: int
    version_number: int
    content_hash: str
    bundle_hash: str = ""
    comment: str = ""
    created_by_id: int | None = None
    created_at: Any = None


class LibraryModuleDetail(LibraryModuleItem):
    """模块详情：版本列表 + 当前版本参数签名 + 是否可管理."""

    versions: list[LibraryVersionItem] = Field(default_factory=list)
    can_manage: bool = False


class LibraryFileItem(BaseModel):
    """版本依赖包条目元数据（只回传 key / kind / 哈希，不回传全文）."""

    file_key: str
    kind: str = "part"
    content_hash: str = ""


class LibraryVersionDetail(LibraryVersionItem):
    """版本详情：根原文 + 依赖包元数据（ADR 0118 §6）."""

    content: str
    params: list[dict[str, Any]] = Field(default_factory=list)
    files: list[LibraryFileItem] = Field(default_factory=list)


class LibraryPreviewRequest(BaseModel):
    """模块版本只读预览：参数覆盖，无落库（与设计预览同口径）."""

    overrides: dict[str, float] | None = Field(default=None, description="参数覆盖")


class LibraryModulePatch(BaseModel):
    """模块元数据 / 可见性 / 归档（None = 不改，ADR 0118 §6）."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    visibility: Literal["public", "workspace"] | None = None
    is_archived: bool | None = None


class DesignLibraryDependencyItem(BaseModel):
    """设计当前直接引用的库模块（依赖面板数据源）."""

    module_id: int
    module_key: str
    name: str
    version_number: int
    latest_version: int = 0
    has_update: bool = False
    visibility: str = "workspace"
    is_archived: bool = False
    owner_workspace_id: int | None = None
    bundle_hash: str = ""


class DesignRefreshRequest(BaseModel):
    """依赖刷新重编译（ADR 0086 §4）：以最新依赖落新版本并清 stale."""

    comment: str = Field(default="依赖更新", max_length=200, description="版本备注")


class DiagnosticItem(BaseModel):
    """编译诊断：编辑器 gutter 按行 / 列定位（D2）."""

    severity: str
    line: int
    col: int
    message: str


class PreviewResponse(BaseModel):
    """即时编译结果：``ok=false`` 时 ``ir`` 为空、诊断非空（I6 不出半截 IR）."""

    ok: bool
    ir: dict[str, Any] | None = None
    diagnostics: list[DiagnosticItem] = Field(default_factory=list)


class DesignListItem(BaseModel):
    """设计文件列表项（不含原文与 IR，降低响应体量）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    title: str
    description: str
    kind: str = "assembly"
    file_key: str = ""
    folder: str = ""
    dependencies_stale: bool = False
    created_at: Any
    updated_at: Any
    version_count: int = 0


class DesignDetail(BaseModel):
    """设计文件详情：原文唯一真相源 + 文件身份（**不含** compiled，ADR 0086 D10）.

    ``content_hash`` 为原文 SHA-256，与 ``GET /{id}/ir`` 的 ETag 同源。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    title: str
    description: str
    content: str
    kind: str = "assembly"
    file_key: str = ""
    folder: str = ""
    dependencies_stale: bool = False
    content_hash: str = ""
    version_number: int = 0
    created_at: Any
    updated_at: Any


class DesignIRResponse(BaseModel):
    """``GET /{id}/ir`` 响应：IR 快照直用（首屏不重复编译，I6）.

    ``ETag = "<content_hash>-<version_number>"``，``If-None-Match`` 命中回 304。
    """

    design_id: int
    version_number: int
    content_hash: str
    ir: dict[str, Any]


class DesignDependencyItem(BaseModel):
    """依赖 / 引用方条目（``GET /{id}/dependencies``）."""

    design_id: int
    file_key: str
    title: str
    folder: str = ""
    kind: str = "assembly"
    version_number: int = 0
    dependencies_stale: bool = False


class DesignDependenciesResponse(BaseModel):
    """当前直接引用（``items`` / ``library_items``）与引用方清单（``referrers``）."""

    design_id: int
    items: list[DesignDependencyItem] = Field(default_factory=list)
    library_items: list[DesignLibraryDependencyItem] = Field(default_factory=list)
    referrers: list[DesignDependencyItem] = Field(default_factory=list)


class DesignVersionItem(BaseModel):
    """版本列表项（不含原文，降低响应体量）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    design_id: int
    version_number: int
    change_type: str = "manual"
    comment: str
    created_by_id: int | None
    created_at: Any


class DesignVersionDetail(DesignVersionItem):
    """版本回看：该版原文、编译快照与依赖闭包（I5）."""

    content: str
    compiled: dict[str, Any]
    dependencies: list[dict[str, Any]] = Field(default_factory=list)


class DesignDiffParamChange(BaseModel):
    """参数变化项（同名参数值不同）."""

    name: str
    base: Any
    head: Any


class DesignDiffParamSummary(BaseModel):
    """参数增删改摘要."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[DesignDiffParamChange] = Field(default_factory=list)


class DesignDiffNodeSummary(BaseModel):
    """节点数摘要."""

    base: int = 0
    head: int = 0


class DesignDiffAssemblySummary(BaseModel):
    """顶层装配增删摘要."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class DesignVersionDiffSummary(BaseModel):
    """结构变化摘要（ADR 0113 D5 / D8）：快照缺失时 ``available=false``."""

    available: bool = False
    params: DesignDiffParamSummary = Field(default_factory=DesignDiffParamSummary)
    nodes: DesignDiffNodeSummary = Field(default_factory=DesignDiffNodeSummary)
    assemblies: DesignDiffAssemblySummary = Field(default_factory=DesignDiffAssemblySummary)


class DesignVersionDiffResponse(BaseModel):
    """两版本对比响应：unified diff + 增删行数 + 结构摘要（ADR 0113 §3）."""

    base_version: int
    head_version: int
    diff: str
    added: int
    removed: int
    summary: DesignVersionDiffSummary


class DesignOutlineResult(BaseModel):
    """单设计装配大纲（ADR 0083 D4）。

    ``source`` 口径（D5）：``compiled`` = 快照已含 ``outline``（IR v2）；
    ``content`` = 历史快照（IR v1）缺大纲，按原文即时编译派生（只读不落库）。
    """

    design_id: int
    version_number: int
    outline: dict[str, Any]
    source: Literal["compiled", "content"]


__all__ = [
    "DesignContentSave",
    "DesignCreate",
    "DesignDependenciesResponse",
    "DesignDependencyItem",
    "DesignDetail",
    "DesignDiffAssemblySummary",
    "DesignDiffNodeSummary",
    "DesignDiffParamChange",
    "DesignDiffParamSummary",
    "DesignIRResponse",
    "DesignLibraryDependencyItem",
    "DesignListItem",
    "DesignOutlineResult",
    "DesignPublishRequest",
    "DesignPublishResponse",
    "DesignRefreshRequest",
    "DesignUpdate",
    "DesignVersionDetail",
    "DesignVersionDiffResponse",
    "DesignVersionDiffSummary",
    "DesignVersionItem",
    "DiagnosticItem",
    "LibraryFileItem",
    "LibraryModuleDetail",
    "LibraryModuleItem",
    "LibraryModulePatch",
    "LibraryPreviewRequest",
    "LibraryVersionDetail",
    "LibraryVersionItem",
    "PreviewRequest",
    "PreviewResponse",
]
