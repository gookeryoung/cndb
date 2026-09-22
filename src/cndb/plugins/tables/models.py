"""tables 插件 ORM 模型：DataTable / DataField / DataView / TablePermission.

设计来源：cndb Django tables 模块，改用 SQLAlchemy 2.0 重写.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from operator import attrgetter
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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
    from cndb.plugins.workspaces.models import Workspace


# ── 标识符生成（杜绝用户输入进入 SQL 标识符） ──


def generate_db_table_name() -> str:
    """生成物理表名：table_ 前缀 + 12 位十六进制随机串."""
    return f"table_{uuid.uuid4().hex[:12]}"


def generate_db_column_name() -> str:
    """生成物理列名：field_ 前缀 + 12 位十六进制随机串."""
    return f"field_{uuid.uuid4().hex[:12]}"


def _trash_table_name(db_table_name: str) -> str:
    """行回收站影子表名：trash_ 前缀 + 原随机段."""
    return f"trash_{db_table_name[len('table_') :]}"


def _link_table_name(db_column_name: str) -> str:
    """关联字段关联表名：link_ 前缀 + 列名随机段."""
    return f"link_{db_column_name[len('field_') :]}"


# ── DataView 枚举 ──


class ViewType(enum.StrEnum):
    """视图形态."""

    GRID = "grid"
    KANBAN = "kanban"
    CALENDAR = "calendar"
    FORM = "form"


class FilterType(enum.StrEnum):
    """多条件组合方式."""

    AND = "AND"
    OR = "OR"


# ── DataTable ──


class DataTable(TimestampMixin, Base):
    """用户自定义表的元数据，物理表由 DDL 引擎按 db_table_name 创建."""

    __tablename__ = "tables_datatable"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    db_table_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    workspace: Mapped[Workspace] = relationship("Workspace")
    owner: Mapped[User | None] = relationship("User", foreign_keys=[owner_id])
    fields: Mapped[list[DataField]] = relationship(back_populates="table", cascade="all, delete-orphan")
    views: Mapped[list[DataView]] = relationship(back_populates="table", cascade="all, delete-orphan")
    permission: Mapped[TablePermission | None] = relationship(
        back_populates="table", cascade="all, delete-orphan", uselist=False
    )
    members: Mapped[list[TableMember]] = relationship(back_populates="table", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DataTable(id={self.id}, name={self.name!r}, db_table_name={self.db_table_name!r})"

    @property
    def trash_table_name(self) -> str:
        """行回收站影子表名."""
        return _trash_table_name(self.db_table_name)

    def active_fields(self) -> list[DataField]:
        """返回未进回收站的字段（按展示顺序），行读写与查询编译共用."""
        active = [f for f in self.fields if not f.trashed]
        active.sort(key=attrgetter("order", "id"))
        return active

    def ensure_db_name(self) -> None:
        """首次保存前生成物理表名（类似 Django 的 save 钩子，显式调用）."""
        if not self.db_table_name:
            self.db_table_name = generate_db_table_name()


# ── DataField ──


class DataField(TimestampMixin, Base):
    """用户自定义字段的元数据，config 由字段类型系统解释与校验."""

    __tablename__ = "tables_datafield"
    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uniq_table_field_name"),
        {"extend_existing": True},
    )

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False)
    db_column_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="fields")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DataField(id={self.id}, name={self.name!r}, type={self.field_type!r})"

    @property
    def link_table_name(self) -> str:
        """关联字段对应的关联物理表名."""
        return _link_table_name(self.db_column_name)

    def ensure_db_name(self) -> None:
        """首次保存前生成物理列名."""
        if not self.db_column_name:
            self.db_column_name = generate_db_column_name()


# ── DataView ──


class DataView(TimestampMixin, Base):
    """数据表视图：保存筛选/排序/字段显隐等展示规则."""

    __tablename__ = "tables_dataview"
    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uniq_table_view_name"),
        {"extend_existing": True},
    )

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    view_type: Mapped[str] = mapped_column(String(32), nullable=False, default=ViewType.GRID)
    filter_type: Mapped[str] = mapped_column(String(3), nullable=False, default=FilterType.AND)
    filters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    sortings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    field_options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    field_order: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    view_options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 公开分享（P4）
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_slug: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True, index=True)

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="views")
    owner: Mapped[User | None] = relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DataView(id={self.id}, name={self.name!r}, type={self.view_type!r})"


# ── 默认视图辅助 ──


def ensure_default_view(
    db: Any,
    table: DataTable,
    owner_id: int | None = None,
    commit: bool = True,
) -> DataView | None:
    """确保表存在一个默认视图「全部」（grid 类型，is_default=True, order=0）.

    同名视图已存在时跳过（不覆盖业务自定义的「全部」视图配置）；
    存在但非默认时补齐 is_default=True 并把同表其它视图的默认标志清掉.

    db 需为 SQLAlchemy ``Session``，此处用 ``Any`` 以避免 models 层反向依赖.

    Returns:
        新建的 DataView；或 None（已存在同名，无需新建）.
    """
    existing = db.query(DataView).filter(DataView.table_id == table.id, DataView.name == "全部").first()
    if existing is not None:
        if not existing.is_default:
            db.query(DataView).filter(DataView.table_id == table.id).update(
                {"is_default": False}, synchronize_session=False
            )
            existing.is_default = True
            existing.order = existing.order or 0
            if commit:
                db.commit()
                db.refresh(existing)
        return None

    # 首次创建：清掉同表可能残留的其它默认标记（应该没有，但保险）
    db.query(DataView).filter(DataView.table_id == table.id).update({"is_default": False}, synchronize_session=False)
    dv = DataView(
        table_id=table.id,
        owner_id=owner_id or table.owner_id,
        name="全部",
        view_type=ViewType.GRID,
        filter_type=FilterType.AND,
        filters=[],
        sortings=[],
        field_options={},
        field_order=[],
        view_options={},
        is_default=True,
        order=0,
    )
    db.add(dv)
    if commit:
        db.commit()
        db.refresh(dv)
    return dv


# ── TablePermission ──


class TablePermission(TimestampMixin, Base):
    """表级访问控制：角色覆盖、行级过滤与字段级隐藏."""

    __tablename__ = "tables_tablepermission"
    __table_args__ = {"extend_existing": True}

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    read_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    edit_records_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    edit_views_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    edit_schema_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    hidden_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    row_filters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    row_filter_type: Mapped[str] = mapped_column(String(3), nullable=False, default="AND")

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="permission")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"TablePermission(table_id={self.table_id})"


# ── TableMember ──


class TableMember(TimestampMixin, Base):
    """表级成员授权：按用户授予 read/write 两级权限."""

    __tablename__ = "tables_tablemember"
    __table_args__ = (
        UniqueConstraint("table_id", "user_id", name="uniq_tablemember_user"),
        {"extend_existing": True},
    )

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("accounts_user.id", ondelete="CASCADE"), nullable=False, index=True)
    # 角色 code：兼容 "read"/"write" 内置值，或引用 Role.code（自定义角色）
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="read")

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="members")
    user: Mapped[User] = relationship("User")


# AuditLog
class AuditLog(TimestampMixin, Base):
    __tablename__ = "tables_auditlog"
    __table_args__ = {"extend_existing": True}
    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


# ImportTask
class ImportTask(TimestampMixin, Base):
    """异步导入任务：状态机 + 进度追踪 + 校验报告.

    状态机（扩展后）：
        pending_validation -> pending_confirm -> running -> done / failed
        pending_validation -> pending_confirm -> running -> failed
        pending -> running -> done / failed      （兼容旧流程）
    """

    __tablename__ = "tables_importtask"
    __table_args__ = {"extend_existing": True}

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="json")
    # 文件内容存为 JSON 字符串（UTF-8 编码）
    file_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 状态
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0-100
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    # 校验报告（JSON 字符串） —— analyze 阶段产出，pending_confirm / running 时只读
    validation_report: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ── 导入选项（两阶段导入 · upsert 扩展） ──
    # 用户选择的参考列名列表（upsert 匹配键）；为空时全部追加
    match_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 未知列处理策略："drop"（默认丢弃）/ "add_text_field"（自动新增基础类型字段）
    unknown_cols_strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="drop")
    # 用户在预览阶段勾选丢弃的未知字段名列表（planned_columns 里被取消勾选的那些）
    dropped_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 用户在确认导入时勾选的清洗动作列表（来自 analyze 阶段的 cleaning_suggestions）
    # 每条格式：{column, action, strategy?, on_fail?}
    cleaning_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


__all__ = [
    "AuditLog",
    "DataField",
    "DataTable",
    "DataView",
    "FilterType",
    "ImportTask",
    "TableMember",
    "TablePermission",
    "ViewType",
    "generate_db_column_name",
    "generate_db_table_name",
]
