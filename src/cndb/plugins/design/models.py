"""design 插件 ORM 模型：设计文件 / 版本 / 引用（ADR 0079 P0 / ADR 0086 D1）.

设计要点：

- ``design_design`` 以 **DSL 原文（``.cnmd``）为唯一真相源**，保存期编译出的
  IR 快照存 ``compiled`` 列；预览 / 渲染只读 IR，运行期不出现语法错误（I2）。
  ADR 0086 起升级为「设计文件」：``kind`` 区分零件 / 装配、``file_key``
  承载跨文件引用、``folder`` 仅做展示分组、``dependencies`` 记录当前编译
  的依赖闭包快照。
- 每次保存落一条 ``design_designversion``（对齐 ``DocumentVersion`` 范式，D7），
  版本另存 ``dependencies`` 闭包（历史可复现编译，I5）。
- ``design_designref`` 是当前直接引用索引（删除阻断与「谁引用了我」查询）。
- 各表均工作区级（``workspace_id`` 级联删除）；权限完全继承工作区角色（D6/I8）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin

#: 版本来源类型（ADR 0113 D10）：客户端只可请求 manual / auto，refresh / rollback 由服务端强制
CHANGE_TYPE_MANUAL = "manual"
CHANGE_TYPE_AUTO = "auto"
CHANGE_TYPE_REFRESH = "refresh"
CHANGE_TYPE_ROLLBACK = "rollback"
CHANGE_TYPE_VALUES = (CHANGE_TYPE_MANUAL, CHANGE_TYPE_AUTO, CHANGE_TYPE_REFRESH, CHANGE_TYPE_ROLLBACK)


class DesignDesign(TimestampMixin, Base):
    """一份设计文件：工作区内 (folder, title) 唯一，绑定一份 DSL 原文与编译产物."""

    __tablename__ = "design_design"
    __table_args__ = (
        UniqueConstraint("workspace_id", "folder", "title", name="uniq_design_design_folder_title"),
        UniqueConstraint("workspace_id", "file_key", name="uniq_design_design_file_key"),
        Index("ix_design_design_ws_updated", "workspace_id", "updated_at"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 文件类型：part = 零件文件（顶层 param + 几何）；assembly = 装配 / 系统文件（ADR 0086 D1）
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="assembly")
    #: 稳定文件标识：工作区内唯一、创建后不可变；DSL ``use`` 引用它（ADR 0086 D1/I2）
    file_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: 展示目录（相对路径，仅分组；禁止绝对路径 / ..，ADR 0086 C10）
    folder: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: DSL 原文（.cnmd），用户可读可编辑的唯一真相源
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 保存期编译出的 IR 快照（JSON）；编译不通过拒绝落库，预览 / 渲染只读此列
    compiled: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: 当前编译对应的依赖闭包 [{file_id, file_key, version_number, content_hash}]（I5）
    dependencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    #: 被引用零件保存后置 true；打开只读旧快照并提示刷新（ADR 0086 C4）
    dependencies_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 旧设计重构迁移前的最后版本号（downgrade 还原用，ADR 0086 I9）
    refactored_from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 软删（列表过滤）；回收站 UI 不在本期范围（ADR 0079 §1）
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DesignDesign(id={self.id}, title={self.title!r}, ws={self.workspace_id})"


class DesignDesignVersion(TimestampMixin, Base):
    """设计版本：每次保存原文即落一版（对齐 DocumentVersion）."""

    __tablename__ = "design_designversion"
    __table_args__ = (
        UniqueConstraint("design_id", "version_number", name="uniq_design_version_number"),
        Index("ix_design_designversion_ws_created", "workspace_id", "created_at"),
        {"extend_existing": True},
    )

    design_id: Mapped[int] = mapped_column(
        ForeignKey("design_design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 版本来源：manual 主动保存 / auto 自动小版本 / refresh 依赖刷新 / rollback 版本恢复（ADR 0113）
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, default=CHANGE_TYPE_MANUAL)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    compiled: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 保存时的依赖闭包快照：历史版本按此解析编译（缺失依赖报错，I5）
    dependencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    comment: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DesignDesignVersion(id={self.id}, design={self.design_id}, no={self.version_number})"


class DesignDesignref(TimestampMixin, Base):
    """设计文件直接引用索引：design 引用 target（当前态，非版本快照，ADR 0086 D1）."""

    __tablename__ = "design_designref"
    __table_args__ = (
        UniqueConstraint("design_id", "target_design_id", name="uniq_design_ref_pair"),
        Index("ix_design_designref_target", "target_design_id"),
        Index("ix_design_designref_ws", "workspace_id"),
        {"extend_existing": True},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    design_id: Mapped[int] = mapped_column(
        ForeignKey("design_design.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_design_id: Mapped[int] = mapped_column(
        ForeignKey("design_design.id", ondelete="CASCADE"),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DesignDesignref(design={self.design_id}, target={self.target_design_id})"


__all__ = [
    "CHANGE_TYPE_AUTO",
    "CHANGE_TYPE_MANUAL",
    "CHANGE_TYPE_REFRESH",
    "CHANGE_TYPE_ROLLBACK",
    "CHANGE_TYPE_VALUES",
    "DesignDesign",
    "DesignDesignVersion",
    "DesignDesignref",
]
