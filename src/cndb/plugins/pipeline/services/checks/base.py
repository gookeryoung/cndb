"""检查动作基类与运行上下文（ADR 0076 D4 / D7）.

扩展点：检查动作由注册表登记（``services/checks/registry.py``），以 ``域/动作`` 命名
并在 DSL 的 ``uses:`` 中引用。新增检测格式 = 新增一个动作模块并注册，引擎零改动（I5）。

``CheckContext`` 只暴露**只读**能力（反射物理表、分页扫描、读取文档正文），
不提供任何写路径，保证检查不修改业务数据（I1）；发现物不携带字段值（D7）。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.documents.models import (
    CONTENT_TYPE_MARKDOWN,
    DOC_STATUS_ARCHIVED,
    Document,
    DocumentVersion,
)
from cndb.plugins.documents.services.content import latest_version, load_content
from cndb.plugins.pipeline.services.errors import CheckError
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.ddl import get_reflected_table
from cndb.plugins.tables.services.core.links import is_link_field

#: 检查动作输入类型（与 ``with:`` 的静态值校验 / 运行期强制转换共用）
INPUT_STRING = "string"
INPUT_INTEGER = "integer"
INPUT_NUMBER = "number"
INPUT_BOOLEAN = "boolean"
INPUT_STRING_LIST = "string_list"
INPUT_TYPES = (INPUT_STRING, INPUT_INTEGER, INPUT_NUMBER, INPUT_BOOLEAN, INPUT_STRING_LIST)

#: 分页扫描批大小（与治理判重同量级）
SCAN_BATCH_SIZE = 5000


@dataclass(frozen=True)
class CheckInput:
    """检查动作的一个 ``with:`` 参数声明（声明式 schema，保存期逐键校验）."""

    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class FindingDraft:
    """检查产出的单条发现物；``severity`` 为空时取 step 声明的默认严重度."""

    message: str
    target_type: str = ""
    target_id: int | None = None
    locator: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)
    severity: str | None = None


@dataclass(frozen=True)
class CheckSpec:
    """检查动作声明：目录展示 + ``with:`` schema + 默认严重度."""

    uses: str
    title: str
    category: str
    inputs: tuple[CheckInput, ...]
    default_severity: str = "warn"
    target_types: tuple[str, ...] = ()


@dataclass
class ScanResult:
    """分页扫描结果（行值 + 是否因上限截断）."""

    rows: list[tuple[Any, ...]]
    truncated: bool


class CheckContext:
    """检查执行上下文：只读数据库访问 + 目标解析（I1）."""

    def __init__(self, db: Session, workspace_id: int, *, max_scan_rows: int | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        # get_bind() 的静态类型为 Engine | Connection；检查只读且始终走连接池，按引擎处理
        self.engine: Engine = cast(Engine, db.get_bind())
        self.max_scan_rows = int(max_scan_rows or settings.ANALYTICS_MAX_SCAN_ROWS)

    # ── 数据表 ──

    def resolve_table(self, name: str) -> DataTable:
        """按表名解析工作区内未进回收站的数据表.

        Raises:
            CheckError: 表不存在 / 已进回收站。
        """
        table = (
            self.db.query(DataTable)
            .filter(
                DataTable.workspace_id == self.workspace_id,
                DataTable.name == name,
                DataTable.trashed == False,  # noqa: E712 - SQLAlchemy 表达式
            )
            .first()
        )
        if table is None:
            raise CheckError(f"数据表不存在或已进回收站：{name}")
        return table

    def reflect(self, table: DataTable) -> Any:
        """反射数据表物理结构（缺失时抛 ``CheckError``）."""
        try:
            return get_reflected_table(
                self.engine,
                table.db_table_name,
                missing_message=f"物理表 {table.db_table_name} 不存在",
            )
        except RuntimeError as exc:
            raise CheckError(str(exc)) from exc

    def scan_rows(
        self,
        table: DataTable,
        columns: list[DataField],
        *,
        batch_size: int = SCAN_BATCH_SIZE,
    ) -> ScanResult:
        """按 id 分页扫描物理表（跳过回收站行），最多 ``max_scan_rows`` 行.

        Returns:
            ``ScanResult``：每行 ``(id, col1, col2, ...)`` 与截断标记。
        """
        sa_table = self.reflect(table)
        select_cols = [sa_table.c.id, *[sa_table.c[f.db_column_name] for f in columns]]
        rows: list[tuple[Any, ...]] = []
        last_id = 0
        truncated = False
        while True:
            query = (
                select(*select_cols)
                .where(sa_table.c.id > last_id, sa_table.c._trashed.is_(False))
                .order_by(sa_table.c.id)
                .limit(min(batch_size, self.max_scan_rows - len(rows)))
            )
            with self.engine.connect() as conn:
                batch = [tuple(row) for row in conn.execute(query).all()]
            if not batch:
                break
            rows.extend(batch)
            last_id = int(batch[-1][0])
            if len(rows) >= self.max_scan_rows:
                truncated = True
                break
            if len(batch) < batch_size:
                break
        return ScanResult(rows=rows, truncated=truncated)

    # ── 文档 ──

    def iter_documents(self) -> Iterator[tuple[Document, str]]:
        """迭代工作区内参与检查的 Markdown 文档（排除文件夹 / 回收站 / 归档）."""
        rows = self.db.execute(
            select(Document)
            .where(
                Document.workspace_id == self.workspace_id,
                Document.is_deleted == False,  # noqa: E712 - SQLAlchemy 表达式
                Document.is_folder == False,  # noqa: E712 - SQLAlchemy 表达式
                Document.content_type == CONTENT_TYPE_MARKDOWN,
                Document.status != DOC_STATUS_ARCHIVED,
            )
            .order_by(Document.sort_order, Document.id)
        ).scalars()
        for doc in rows:
            version: DocumentVersion | None = latest_version(self.db, doc.id)
            yield doc, load_content(version, doc)


def resolve_fields(
    table: DataTable,
    names: list[str],
    *,
    field_types: set[str] | None = None,
) -> list[DataField]:
    """把 ``with.fields`` 解析为字段列表（``all`` 表示全部有物理列的字段）.

    Raises:
        CheckError: 字段不存在 / 无物理列 / 类型不符合检查要求。
    """
    active = table.active_fields()
    all_mode = not names or names == ["all"]
    if all_mode:
        fields = [f for f in active if _has_physical_column(f)]
        if field_types is not None:
            # ``all`` 是"全部适用字段"的意图，不适用类型直接跳过；显式字段名才报错
            fields = [f for f in fields if f.field_type in field_types]
    else:
        field_map = {f.name: f for f in active}
        fields = []
        for name in names:
            f = field_map.get(name)
            if f is None:
                raise CheckError(f"字段不存在或已进回收站：{name}")
            if not _has_physical_column(f):
                raise CheckError(f"字段 {name} 不支持该检查（无物理列）")
            fields.append(f)
    if field_types is not None:
        invalid = [f.name for f in fields if f.field_type not in field_types]
        if invalid:
            raise CheckError(f"字段类型不支持该检查：{', '.join(invalid)}")
    return fields


def _has_physical_column(field: DataField) -> bool:
    """字段是否有可扫描的物理列（附件 / 关联 / 查找等派生字段没有）."""
    ft = default_registry.get(field.field_type)
    return ft is not None and ft.has_physical_column and not is_link_field(field)


__all__ = [
    "INPUT_BOOLEAN",
    "INPUT_INTEGER",
    "INPUT_NUMBER",
    "INPUT_STRING",
    "INPUT_STRING_LIST",
    "INPUT_TYPES",
    "SCAN_BATCH_SIZE",
    "CheckContext",
    "CheckInput",
    "CheckSpec",
    "FindingDraft",
    "ScanResult",
    "resolve_fields",
]
