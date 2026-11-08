"""workspaces 插件 ORM 模型：Workspace + WorkspaceMember.

设计来源：cndb Django workspaces 模块，改用 SQLAlchemy 2.0 重写。
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import TYPE_CHECKING, Any, override

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cndb.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


# ── 动作常量：与 tables.access.TableAction 对齐 ──

# 动作集合（管理员维护角色时勾选的权限项）
ACTION_KEYS: tuple[str, ...] = (
    "READ",
    "EDIT_RECORDS",
    "EDIT_VIEWS",
    "EDIT_SCHEMA",
    "MANAGE_DATA",
)

# 动作中文显示名
ACTION_LABELS: dict[str, str] = {
    "READ": "读取数据",
    "EDIT_RECORDS": "编辑数据行",
    "EDIT_VIEWS": "编辑视图",
    "EDIT_SCHEMA": "编辑结构（字段）",
    "MANAGE_DATA": "数据治理（合并/清洗）",
}

# 内置角色 code（由迁移种子写入，管理员可修改但不可删除）
BUILTIN_ROLE_CODES: tuple[str, ...] = ("read", "write", "admin")

# 单工作区默认存储配额（字节）：100 MB
DEFAULT_STORAGE_QUOTA_BYTES: int = 100 * 1024 * 1024


class WorkspaceRole(enum.StrEnum):
    """工作区成员角色，权限从高到低：owner > editor > viewer."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class WorkspaceVisibility(enum.StrEnum):
    """工作区可见性枚举."""

    # 公开：任何人可查看工作区数据表结构和数据（只读）
    PUBLIC = "public"
    # 成员可见：仅工作区成员可访问
    MEMBER = "member"
    # 私有：仅 OWNER 可见，其他成员被排除
    PRIVATE = "private"


class WorkspaceModule(enum.StrEnum):
    """工作区功能模块（ADR 0080）：可任意勾选组合，替代旧 workspace_type 枚举."""

    TABLES = "tables"
    DOCUMENTS = "documents"
    DESIGN = "design"


# 模块清单（有序，决定校验归一化顺序与前端页签顺序）
WORKSPACE_MODULES: tuple[str, ...] = ("tables", "documents", "design")


# 新建工作区默认模块：三模块全选（ADR 0080 D8，等价旧默认 data_doc）。
# 字面量工厂（不走 list() 拷贝），schema 自愈层可据此合成 server_default 字面量。
def default_workspace_modules() -> list[str]:
    """Workspace.modules 列的 Python 端默认值（全三模块）."""
    return ["tables", "documents", "design"]


DEFAULT_WORKSPACE_MODULES: list[str] = list(WORKSPACE_MODULES)

# 模块中文显示名
MODULE_LABELS: dict[str, str] = {
    WorkspaceModule.TABLES.value: "数据表",
    WorkspaceModule.DOCUMENTS.value: "文档",
    WorkspaceModule.DESIGN.value: "设计",
}


# 角色等级映射：数值越大权限越高
ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.OWNER: 2,
    WorkspaceRole.EDITOR: 1,
    WorkspaceRole.VIEWER: 0,
}

# 工作区角色中文显示名（ADR 0047 单一来源：403 文案、帮助图示等均引用此处）
WORKSPACE_ROLE_LABELS: dict[str, str] = {
    WorkspaceRole.OWNER.value: "所有者",
    WorkspaceRole.EDITOR.value: "编辑者",
    WorkspaceRole.VIEWER.value: "查看者",
}


class Workspace(TimestampMixin, Base):
    """工作区：数据与权限的隔离边界."""

    __tablename__ = "workspaces_workspace"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 工作区扩展字段
    visibility: Mapped[WorkspaceVisibility] = mapped_column(
        Enum(WorkspaceVisibility),
        nullable=False,
        default=WorkspaceVisibility.MEMBER,
        comment="可见性：公开/成员可见/私有",
    )
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="工作区标签列表",
    )
    allow_edit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否允许成员（EDITOR 及以下）编辑数据",
    )
    modules: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=default_workspace_modules,
        # 自愈/兜底建表路径需要可编译的 DEFAULT（工厂调用不可依赖），与迁移回填口径一致
        server_default='["tables", "documents", "design"]',
        comment="启用的功能模块集合（tables/documents/design，ADR 0080）",
    )
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=DEFAULT_STORAGE_QUOTA_BYTES,
        server_default=str(DEFAULT_STORAGE_QUOTA_BYTES),
        comment="工作区存储配额（字节），默认 100MB，由管理员在管理台分配",
    )

    # 工作区模板（需求 0094）：模板是全局定义，工作区只持有引用与生命周期快照
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces_template.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="创建工作区时选用的模板；NULL = 自由工作区",
    )
    template_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="工作区最近一次同步的模板版本",
    )
    template_stage: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="当前所处生命周期阶段 key（模板 stages[].key）",
    )
    template_state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="模板实例化映射与阶段履历：{form_tables, documents, history}",
    )
    project_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="workspace",
        server_default="workspace",
        comment="项目上下文模式：workspace（工作区级单实例）/ project（按根表单项目行隔离，ADR 0122）",
    )

    # 关系
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])
    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Workspace(id={self.id}, name={self.name!r})"


class WorkspaceMember(TimestampMixin, Base):
    """工作区成员：用户在工作区内的角色."""

    __tablename__ = "workspaces_workspacemember"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uniq_workspace_member"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[WorkspaceRole] = mapped_column(Enum(WorkspaceRole), nullable=False, default=WorkspaceRole.VIEWER)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 关系
    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"WorkspaceMember(workspace_id={self.workspace_id}, user_id={self.user_id}, role={self.role.value})"


# ── Role（全局数据角色，管理员维护） ──


class Role(TimestampMixin, Base):
    """全局数据角色：管理员自定义的角色，由表拥有者分配给表成员.

    与工作区角色（WorkspaceRole）解耦：
    - WorkspaceRole 决定用户能进入哪些工作区、在工作区里做什么（边界 + 粗粒度）
    - Role 决定用户进入某张表后能执行哪些具体动作（细粒度）
    """

    __tablename__ = "workspaces_role"
    __table_args__ = (UniqueConstraint("code", name="uniq_role_code"), {"extend_existing": True})

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 权限位：{action_key: bool}，action_key 见 ACTION_KEYS
    permissions: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False, default=dict)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Role(code={self.code!r}, name={self.name!r})"

    # ── 便捷访问 ──

    def has_action(self, action_key: str) -> bool:
        """判定角色是否拥有指定动作权限."""
        return bool(self.permissions.get(action_key, False))

    def ensure_permissions(self) -> None:
        """补齐缺失的 action_key（向后兼容）."""
        perms = dict(self.permissions or {})
        for key in ACTION_KEYS:
            perms.setdefault(key, False)
        self.permissions = perms


class WorkspaceTemplate(TimestampMixin, Base):
    """工作区模板（需求 0094）：定义表单、文档规则与生命周期阶段.

    模板是全局资源（不挂工作区），``spec`` 为经过校验的 JSON 规格；
    每次保存都会复制一份到 ``WorkspaceTemplateRevision``，用于 diff 与回滚追溯。
    """

    __tablename__ = "workspaces_template"
    __table_args__ = (
        UniqueConstraint("name", name="uniq_workspace_template_name"),
        {"extend_existing": True},
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    modules: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=default_workspace_modules,
        server_default='["tables", "documents", "design"]',
        comment="使用该模板创建的工作区默认启用的功能模块",
    )
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    revisions: Mapped[list[WorkspaceTemplateRevision]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WorkspaceTemplate(id={self.id}, name={self.name!r}, version={self.version})"


class WorkspaceTemplateRevision(TimestampMixin, Base):
    """模板版本快照：每保存一次落一版，供 diff / 影响预览与审计."""

    __tablename__ = "workspaces_templaterevision"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uniq_workspace_template_version"),
        {"extend_existing": True},
    )

    template_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_template.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    template: Mapped[WorkspaceTemplate] = relationship(back_populates="revisions")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WorkspaceTemplateRevision(template_id={self.template_id}, version={self.version})"


class WorkspaceProjectState(TimestampMixin, Base):
    """项目级生命周期状态（ADR 0122 D3）.

    ``project_row_id`` 是模板根表单（``project.root_form``）的行 ID；动态表无法建
    跨表 FK，归属由服务层 ``resolve_project_row`` 校验。唯一键保证同一项目只有
    一条状态，推进用 upsert 语义。
    """

    __tablename__ = "workspaces_workspace_project_state"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_row_id", name="uniq_workspace_project_state"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_row_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment="项目级阶段推进履历",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"WorkspaceProjectState(workspace_id={self.workspace_id}, project_row_id={self.project_row_id})"


class WorkspaceProjectDocument(TimestampMixin, Base):
    """项目级文档映射（ADR 0122 D4）：文档本体不加项目列，映射独立备份与清理."""

    __tablename__ = "workspaces_workspace_project_document"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_row_id", "doc_key", name="uniq_workspace_project_document"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_row_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    doc_key: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"WorkspaceProjectDocument(workspace_id={self.workspace_id}, "
            f"project_row_id={self.project_row_id}, doc_key={self.doc_key!r})"
        )


class WorkspaceStorageSnapshot(Base):
    """工作区存储用量快照（ADR 0024）.

    由后台刷新器按周期重算 ``workspace_storage_bytes`` 后 upsert；管理台
    「空间分配」、工作区详情与上传配额预判只读本表，不在请求内做全量统计。

    缺行 = 该工作区**尚未统计**（前端显示「统计中」，不拿 0 冒充）。
    """

    __tablename__ = "workspaces_storage_snapshot"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        primary_key=True,
    )
    used_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="快照用量（字节）：附件 + 文档外存/内联正文 + 数据表记录",
    )
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="计算完成时刻（UTC）",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="本次统计耗时（毫秒），用于排障与调参",
    )

    @override
    def __repr__(self) -> str:  # pragma: no cover
        return f"WorkspaceStorageSnapshot(workspace_id={self.workspace_id}, used_bytes={self.used_bytes})"


__all__ = [
    "ACTION_KEYS",
    "ACTION_LABELS",
    "BUILTIN_ROLE_CODES",
    "DEFAULT_STORAGE_QUOTA_BYTES",
    "DEFAULT_WORKSPACE_MODULES",
    "MODULE_LABELS",
    "ROLE_RANK",
    "WORKSPACE_MODULES",
    "WORKSPACE_ROLE_LABELS",
    "Role",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceModule",
    "WorkspaceProjectDocument",
    "WorkspaceProjectState",
    "WorkspaceRole",
    "WorkspaceStorageSnapshot",
    "WorkspaceTemplate",
    "WorkspaceTemplateRevision",
    "WorkspaceVisibility",
    "default_workspace_modules",
]
