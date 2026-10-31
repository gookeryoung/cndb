"""``document/broken-refs`` —— 文档引用失效检查（ADR 0076 C5）.

覆盖三类引用（``with.scopes`` 可裁剪）：

- ``table``：独占段落的 ``{{table:<表ID>|view=<视图ID>}}`` 指向不存在 / 已进回收站的
  数据表或不存在的视图；
- ``chart``：内嵌图表块引用的模板不存在 / 已下线；
- ``file``：``![alt](file:<file_key>)`` 指向工作区内不存在的上传文件。

发现物只携带引用原文与定位信息（表 ID / 块序号 / 文件键），不携带正文值（D7）。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from cndb.core.config import settings
from cndb.plugins.documents.services.charts import get_template
from cndb.plugins.documents.services.charts.inline import (
    ERROR_TEMPLATE_MISSING,
    iter_inline_chart_blocks,
)
from cndb.plugins.documents.services.export.images import INLINE_IMAGE_RE, resolve_upload_path
from cndb.plugins.documents.services.export.table_refs import parse_table_ref_line
from cndb.plugins.files.models import FileOwner
from cndb.plugins.pipeline.services.checks.base import (
    INPUT_STRING_LIST,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
)
from cndb.plugins.pipeline.services.checks.registry import register_check
from cndb.plugins.pipeline.services.errors import CheckError
from cndb.plugins.tables.models import DataTable, DataView

#: 支持的引用域
SCOPES = ("chart", "table", "file")

SPEC = CheckSpec(
    uses="document/broken-refs",
    title="文档引用失效检查",
    category="document",
    inputs=(
        CheckInput(
            "scopes",
            INPUT_STRING_LIST,
            description="检查范围：chart / table / file",
            default=("chart", "table", "file"),
        ),
    ),
    default_severity="warn",
    target_types=("document",),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """逐文档检查引用可解析性."""
    scopes = set(params.get("scopes") or SCOPES)
    unknown = sorted(scopes - set(SCOPES))
    if unknown:
        raise CheckError(f"document/broken-refs 不支持的范围：{', '.join(unknown)}")
    findings: list[FindingDraft] = []
    for doc, content in ctx.iter_documents():
        if "table" in scopes:
            findings.extend(_check_table_refs(ctx, doc.id, content))
        if "chart" in scopes:
            findings.extend(_check_chart_refs(doc.id, content))
        if "file" in scopes:
            findings.extend(_check_file_refs(ctx, doc.id, content))
    return findings


def _check_table_refs(ctx: CheckContext, doc_id: int, content: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    tables: dict[int, DataTable | None] = {}
    views: dict[int, DataView | None] = {}
    for line in content.splitlines():
        spec = parse_table_ref_line(line)
        if spec is None:
            continue
        if spec.table_id not in tables:
            tables[spec.table_id] = (
                ctx.db.query(DataTable)
                .filter(
                    DataTable.id == spec.table_id,
                    DataTable.workspace_id == ctx.workspace_id,
                    DataTable.trashed == False,  # noqa: E712 - SQLAlchemy 表达式
                )
                .first()
            )
        table = tables[spec.table_id]
        if table is None:
            findings.append(
                FindingDraft(
                    message=f"数据表引用失效：表 ID {spec.table_id} 不存在或已进回收站",
                    target_type="document",
                    target_id=doc_id,
                    locator={"scope": "table", "table_id": spec.table_id, "ref": line.strip()},
                )
            )
            continue
        if spec.view_id is None:
            continue
        if spec.view_id not in views:
            views[spec.view_id] = ctx.db.execute(
                select(DataView).where(DataView.id == spec.view_id, DataView.table_id == table.id)
            ).scalar_one_or_none()
        if views[spec.view_id] is None:
            findings.append(
                FindingDraft(
                    message=f"数据表视图引用失效：视图 ID {spec.view_id} 不属于表「{table.name}」",
                    target_type="document",
                    target_id=doc_id,
                    locator={"scope": "table", "table_id": spec.table_id, "view_id": spec.view_id},
                )
            )
    return findings


def _check_chart_refs(doc_id: int, content: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    for index, block in enumerate(iter_inline_chart_blocks(content)):
        missing = block.error == ERROR_TEMPLATE_MISSING or (
            block.template_key and get_template(block.template_key) is None
        )
        if not missing:
            continue
        findings.append(
            FindingDraft(
                message=f"图表模板引用失效：{block.template_key or '（未声明模板）'}",
                target_type="document",
                target_id=doc_id,
                locator={"scope": "chart", "block_index": index, "template": block.template_key},
            )
        )
    return findings


def _check_file_refs(ctx: CheckContext, doc_id: int, content: str) -> list[FindingDraft]:
    findings: list[FindingDraft] = []
    upload_dir = Path(settings.UPLOAD_DIR)
    seen: dict[str, bool] = {}
    for match in INLINE_IMAGE_RE.finditer(content):
        file_key = match.group("key")
        if file_key not in seen:
            seen[file_key] = _file_exists(ctx, upload_dir, file_key)
        if seen[file_key]:
            continue
        findings.append(
            FindingDraft(
                message=f"附件引用失效：{file_key}",
                target_type="document",
                target_id=doc_id,
                locator={"scope": "file", "file_key": file_key},
            )
        )
    return findings


def _file_exists(ctx: CheckContext, upload_dir: Path, file_key: str) -> bool:
    """文件归属记录存在，或工作区上传目录中真实存在."""
    if resolve_upload_path(upload_dir, ctx.workspace_id, file_key) is not None:
        return True
    owner = (
        ctx.db.query(FileOwner)
        .filter(FileOwner.workspace_id == ctx.workspace_id, FileOwner.file_key == file_key)
        .first()
    )
    return owner is not None


register_check(SPEC, run)

__all__ = ["SCOPES", "SPEC", "run"]
