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
    # form 为历史存量类型（公开表单功能已移除），仅为兼容既有行保留；
    # 已无前端渲染入口，禁止新视图使用
    FORM = "form"


class FilterType(enum.StrEnum):
    """多条件组合方式."""

    AND = "AND"
    OR = "OR"


class ViewVisibility(enum.StrEnum):
    """视图可见性档位（ADR 0003 决策 D1/D2）.

    - ``TABLE``   继承表权限（表内公开）：读 = 表 ``READ``，改 = 表 ``EDIT_VIEWS``
    - ``SHARED``  指定成员：仅 ``tables_dataviewpermission`` 名单内可见
    - ``PRIVATE`` 仅创建者可见（**新建默认**，对非创建者含管理员一律 404）

    约束：视图授权永不放行表外的人，也不提升改权 —— 生效权 = min(视图授权, 表权限)。
    """

    TABLE = "table"
    SHARED = "shared"
    PRIVATE = "private"


class ViewGrantSubject(enum.StrEnum):
    """视图授权主体类型（**当前只有成员一种**）.

    按工作区角色共享的 ``role`` 型授权曾在模型与判定层预留，因从未有任何写入端点、
    生产数据零依赖，已于 ADR 0003 D6 移除。``subject_type`` 列保留（值恒为 ``user``），
    以免为抹掉一个无害列而做 SQLite 重建表的破坏性迁移。
    """

    USER = "user"  # subject_id = user.id


class ViewGrantRole(enum.StrEnum):
    """视图授权角色（无 owner —— 创建者天然全权）."""

    VIEWER = "viewer"
    EDITOR = "editor"


def scope_key_for(visibility: str, owner_id: int | None) -> int:
    """视图命名空间：``private`` 落创建者空间，其余（``table``/``shared``）落共享空间.

    共享命名空间（0）= 会出现在表的公共视图栏里，因此 ``shared`` 与 ``table`` 同空间，
    同名冲突直接 400；``private`` 只在创建者自己的命名空间内唯一（修 ADR 0003 缺陷 #7）。
    """
    if visibility == ViewVisibility.PRIVATE:
        return int(owner_id) if owner_id is not None else 0
    return 0


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
    row_permissions: Mapped[list[RowPermission]] = relationship(back_populates="table", cascade="all, delete-orphan")

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
    """数据表视图：保存筛选/排序/字段显隐等展示规则.

    可见性由 ``visibility`` 独立表达（不再借用 ``owner_id IS NULL`` 编码公共），
    ``owner_id`` 恒为**创建者**语义（I4：授权不转移归属）。
    唯一键按命名空间划分：``scope_key=0`` 为共享命名空间（``table`` 档），
    ``scope_key=user_id`` 为创建者私有命名空间 —— 私有视图只在本人命名空间内唯一，
    两个用户可各建同名「我的待办」而互不冲突。
    """

    __tablename__ = "tables_dataview"
    __table_args__ = (
        UniqueConstraint("table_id", "scope_key", "name", name="uniq_table_view_scope_name"),
        {"extend_existing": True},
    )

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 创建者。SET NULL（而非 CASCADE）：创建者删号后视图作为「孤儿」保留（ADR 0003 §7-2 D3）
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"),
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
    # 可见性档位：新建默认 private（I2：主动开放才扩大范围）
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default=ViewVisibility.PRIVATE, index=True)
    # 命名空间：0 = 共享（table 档）；创建者 user_id = 私有（private/shared 档）
    scope_key: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="views")
    owner: Mapped[User | None] = relationship("User")
    grants: Mapped[list[DataViewPermission]] = relationship(
        back_populates="view", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DataView(id={self.id}, name={self.name!r}, type={self.view_type!r})"


# ── DataViewPermission ──


class DataViewPermission(TimestampMixin, Base):
    """视图级授权名单（仅 ``visibility=shared`` 时参与判定，ADR 0003 §2）.

    与 ``documents_permission`` 同构的**白名单**模式：表权限是硬天花板，
    名单只决定「表内谁还能看到」，不构成放行表外主体或提升改权的旁路。

    - ``subject_type`` 恒为 ``user`` → ``subject_id`` 为用户 id 字符串（D6 后仅此一种主体）

    切回 ``private``/``table`` 档时数据保留但失效（便于来回切换不丢名单）。
    """

    __tablename__ = "tables_dataviewpermission"
    __table_args__ = (
        UniqueConstraint("view_id", "subject_type", "subject_id", name="uniq_view_grant_subject"),
        {"extend_existing": True},
    )

    view_id: Mapped[int] = mapped_column(
        ForeignKey("tables_dataview.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(8), nullable=False, default=ViewGrantSubject.USER)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ViewGrantRole.VIEWER)
    # 审计入口：谁授的权（授权人删号后置空，不影响授权本身）
    granted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    # 关系
    view: Mapped[DataView] = relationship(back_populates="grants")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"DataViewPermission(view_id={self.view_id}, {self.subject_type}:{self.subject_id}={self.role})"


# ── 默认视图辅助 ──


#: 默认视图名（每张表的「全部」视图，恒为 ``table`` 档，保证新成员进表不空白）
DEFAULT_VIEW_NAME = "全部"


def _normalize_default_view(db: Any, view: DataView) -> bool:
    """把已存在的「全部」视图修正为 ``table`` 档 + 默认位.

    Returns:
        是否发生了改动（调用方据此决定是否 commit）.
    """
    changed = False
    if view.visibility != ViewVisibility.TABLE or view.scope_key != 0:
        # 共享命名空间若已有同名视图，说明名字被占用 → 不强行抢占唯一键位，
        # 也不把默认位留在非 table 档（默认位是表级标记，见 ADR 0003 §2）
        collision = (
            db.query(DataView)
            .filter(
                DataView.table_id == view.table_id,
                DataView.scope_key == 0,
                DataView.name == view.name,
                DataView.id != view.id,
            )
            .first()
        )
        if collision is not None:
            return changed
        view.visibility = ViewVisibility.TABLE
        view.scope_key = 0
        changed = True
    if not view.is_default:
        db.query(DataView).filter(DataView.table_id == view.table_id).update(
            {"is_default": False}, synchronize_session=False
        )
        view.is_default = True
        view.order = view.order or 0
        changed = True
    return changed


def ensure_default_view(
    db: Any,
    table: DataTable,
    owner_id: int | None = None,
    commit: bool = True,
) -> DataView | None:
    """确保表存在一个默认视图「全部」（grid 类型，is_default=True, order=0, ``table`` 档）.

    同名视图已存在时跳过创建，但会把它修正为 ``table`` 档 + 默认位（不覆盖业务自定义的
    「全部」视图配置）；存在但非默认时补齐 is_default=True 并把同表其它视图的默认标志清掉.

    ``visibility='table'`` + ``scope_key=0`` 是 D1 的硬约束：每张表至少保留一个表内可见
    视图，否则其他成员进表看到空白（ADR 0003 §5）.

    db 需为 SQLAlchemy ``Session``，此处用 ``Any`` 以避免 models 层反向依赖.

    Returns:
        新建的 DataView；或 None（已存在同名，无需新建）.
    """
    existing = (
        db.query(DataView)
        .filter(DataView.table_id == table.id, DataView.name == DEFAULT_VIEW_NAME)
        .order_by(DataView.id)
        .first()
    )
    if existing is not None:
        if _normalize_default_view(db, existing) and commit:
            db.commit()
            db.refresh(existing)
        return None

    # 首次创建：清掉同表可能残留的其它默认标记（应该没有，但保险）
    db.query(DataView).filter(DataView.table_id == table.id).update({"is_default": False}, synchronize_session=False)
    dv = DataView(
        table_id=table.id,
        owner_id=owner_id or table.owner_id,
        name=DEFAULT_VIEW_NAME,
        view_type=ViewType.GRID,
        filter_type=FilterType.AND,
        filters=[],
        sortings=[],
        field_options={},
        field_order=[],
        view_options={},
        is_default=True,
        order=0,
        visibility=ViewVisibility.TABLE,
        scope_key=0,
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
    # 数据治理（重复合并/清洗）角色阈值；空 = 未配置，回退工作区角色默认
    manage_data_role: Mapped[str] = mapped_column(String(16), nullable=False, default="")
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


# ── RowPermission（行级权限规则，ADR 0004） ──


class RowSubject(enum.StrEnum):
    """行级权限规则的授权主体类型（ADR 0004 D1）."""

    USER = "user"  # 指定成员：subject_id = accounts_user.id 字符串
    MEMBER_ROLE = "member_role"  # 表级成员档：subject_id ∈ {"read", "write"}


class RowAction(enum.StrEnum):
    """行级权限规则授予的动作（ADR 0004 §1）.

    ``EDIT`` 隐含可查看（I4：读 ⊇ 写）。
    """

    VIEW = "view"  # 命中行对该主体可查看
    EDIT = "edit"  # 命中行对该主体可编辑（隐含可查看）


class RowPermission(TimestampMixin, Base):
    """行级权限规则：给定主体 + 动作 + 一组筛选条件，命中行受此规则约束.

    与 ``TablePermission.row_filters``（默认档）**扩展并存**（ADR 0004 D7）：
    判定时先取默认档，再把命中的规则并集叠加（ADR 0004 §3）。
    每主体每动作至多一条（唯一键 D6），多段行范围用 ``filter_type=OR`` 合进一条。
    """

    __tablename__ = "tables_rowpermission"
    __table_args__ = (
        UniqueConstraint(
            "table_id",
            "subject_type",
            "subject_id",
            "action",
            name="uniq_rowpermission_subject_action",
        ),
        {"extend_existing": True},
    )

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # user id 字符串，或 member_role 的 "read"/"write"（非 FK：可能是常量，ADR 0004 §7-10）
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    # 条件列表 [{field_name, op, value}, ...]，与 row_filters / 视图 filters 同构
    filters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    filter_type: Mapped[str] = mapped_column(String(3), nullable=False, default="AND")
    # 审计入口：谁授的权（授权人删号后置空，不影响规则本身）
    granted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    # 关系
    table: Mapped[DataTable] = relationship(back_populates="row_permissions")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"RowPermission(table_id={self.table_id}, {self.subject_type}:{self.subject_id}={self.action})"


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
    # 列映射（ADR 0020 P2/P3）：{源列名: 目标字段名}；确认导入时按映射写入目标字段
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 用户在确认导入时勾选的清洗动作列表（来自 analyze 阶段的 cleaning_suggestions）
    # 每条格式：{column, action, strategy?, on_fail?}
    cleaning_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


class GovernanceTask(TimestampMixin, Base):
    """异步治理任务：重复检测 / 合并 / 清洗的统一任务记录.

    状态机：
        pending -> running -> done / failed
    """

    __tablename__ = "tables_governancetask"
    __table_args__ = {"extend_existing": True}

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 任务类型：detect（重复检测）/ merge（合并）/ clean（清洗）
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="detect")
    # 状态
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0-100
    # 任务配置快照（detect: match_fields/选项；merge: 组配置；clean: 动作列表）
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 结果报告（JSON 字符串）：检测报告 / 合并结果 / 清洗结果
    report: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 检测/合并分组进度
    total_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_groups: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "AuditLog",
    "DataField",
    "DataTable",
    "DataView",
    "FilterType",
    "GovernanceTask",
    "ImportTask",
    "RowAction",
    "RowPermission",
    "RowSubject",
    "TableMember",
    "TablePermission",
    "ViewType",
    "generate_db_column_name",
    "generate_db_table_name",
]
