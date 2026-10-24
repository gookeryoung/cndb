"""workspaces 插件 ORM 模型：Workspace + WorkspaceMember.

设计来源：cndb Django workspaces 模块，改用 SQLAlchemy 2.0 重写。
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import TYPE_CHECKING, override

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


class WorkspaceType(enum.StrEnum):
    """工作区类型：决定工作区提供哪些功能模块.

    - DATA_DOC：数据 + 文档（数据表 / 数据分析 / 文档），默认
    - DATA：仅数据（数据表 / 数据分析，不提供文档）
    - DOC：仅文档（不提供数据表与数据分析）
    """

    DATA_DOC = "data_doc"
    DATA = "data"
    DOC = "doc"


# 工作区类型中文显示名
WORKSPACE_TYPE_LABELS: dict[str, str] = {
    WorkspaceType.DATA_DOC.value: "数据 + 文档",
    WorkspaceType.DATA.value: "数据",
    WorkspaceType.DOC.value: "文档",
}


# 角色等级映射：数值越大权限越高
ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.OWNER: 2,
    WorkspaceRole.EDITOR: 1,
    WorkspaceRole.VIEWER: 0,
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
    workspace_type: Mapped[WorkspaceType] = mapped_column(
        Enum(WorkspaceType),
        nullable=False,
        default=WorkspaceType.DATA_DOC,
        # SQLAlchemy Enum 落库为枚举成员名（DATA_DOC），故 server_default 用 name
        server_default=WorkspaceType.DATA_DOC.name,
        comment="工作区类型：数据+文档 / 数据 / 文档",
    )
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=DEFAULT_STORAGE_QUOTA_BYTES,
        server_default=str(DEFAULT_STORAGE_QUOTA_BYTES),
        comment="工作区存储配额（字节），默认 100MB，由管理员在管理台分配",
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
    "ROLE_RANK",
    "WORKSPACE_TYPE_LABELS",
    "Role",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceRole",
    "WorkspaceStorageSnapshot",
    "WorkspaceType",
    "WorkspaceVisibility",
]
