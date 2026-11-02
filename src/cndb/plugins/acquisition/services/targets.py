"""落点分发：表落点走既有 upsert + 逐条写台账（ADR 0085 §2 / D4 / D13）.

本模块只做「候选 → 目标行 → 幂等落表 → 台账」，不新增写路径：

- 表：``datasource.services.write.upsert_rows``（``match_keys`` 幂等 + 轻量模式），
  空表时允许自动补字段（对齐 ADR 0019 的自动建表口径）；
- 文档：复用 ``documents.services.content`` 的 ``create_document`` / ``update_content``
  （``change_type=auto_import``），同 ``dedupe_key`` 恒定指向同一 ``document_id``；
  **人工改过的文档不覆盖**，转 issue 建议（I6 / D8）。

台账 ``acquisition_item`` 是跨运行去重与来源追溯的唯一依据：同 ``(strategy, dedupe_key)``
至多一行，落点 id 记在 ``target_id``。
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import AcquisitionItem, AcquisitionStrategy
from cndb.plugins.acquisition.services.rules.dedupe import content_digest, dedupe_key
from cndb.plugins.datasource.services.auto_table import is_table_empty
from cndb.plugins.datasource.services.normalize import apply_field_mapping
from cndb.plugins.datasource.services.runner import field_mapping_from_payload
from cndb.plugins.datasource.services.write import upsert_rows

__all__ = [
    "TargetReport",
    "dispatch_document_target",
    "dispatch_table_target",
    "document_targets",
    "existing_keys",
    "table_targets",
]

#: 台账 / 表行都不接收的候选内部键
_INTERNAL_KEYS = ("match_score", "channel", "raw")


@dataclass(slots=True)
class TargetReport:
    """一次落点的计数结果（并入 ``acquisition_run``）."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    docs_created: int = 0
    docs_updated: int = 0
    docs_skipped: int = 0
    written: int = 0
    table_id: int | None = None
    #: 语义辅助用量（``item_summary`` 的调用数 / 降级数 / token），并入 ``run.detail.llm``
    llm: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> int:
        """本轮实际产生变化的行 / 文档数（停止判定用）."""
        return self.inserted + self.updated + self.docs_created + self.docs_updated


def table_targets(strategy: AcquisitionStrategy) -> list[dict[str, Any]]:
    """策略声明里的表落点."""
    return [dict(target) for target in list(strategy.targets or []) if str(target.get("kind")) == "table"]


def document_targets(strategy: AcquisitionStrategy) -> list[dict[str, Any]]:
    """策略声明里的文档落点."""
    return [dict(target) for target in list(strategy.targets or []) if str(target.get("kind")) == "document"]


def existing_keys(db: Session, strategy_id: int, keys: Sequence[str]) -> set[str]:
    """查台账中已存在的去重键（分批查询，避免超长 IN）."""
    from sqlalchemy import select

    found: set[str] = set()
    unique = list(dict.fromkeys(keys))
    for start in range(0, len(unique), 500):
        chunk = unique[start : start + 500]
        stmt = select(AcquisitionItem.dedupe_key).where(
            AcquisitionItem.strategy_id == strategy_id,
            AcquisitionItem.dedupe_key.in_(chunk),
        )
        found.update(db.execute(stmt).scalars())
    return found


def _load_ledger(
    db: Session,
    strategy_id: int,
    items: Sequence[Mapping[str, Any]],
    identity: Sequence[str] = (),
) -> dict[str, AcquisitionItem]:
    """按本批去重键取已有台账行（分批查询，避免超长 IN）."""
    from sqlalchemy import select

    keys = list(dict.fromkeys(dedupe_key(item, str(item.get("channel") or ""), identity) for item in items))
    found: dict[str, AcquisitionItem] = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start : start + 500]
        stmt = select(AcquisitionItem).where(
            AcquisitionItem.strategy_id == strategy_id,
            AcquisitionItem.dedupe_key.in_(chunk),
        )
        for row in db.execute(stmt).scalars():
            found[row.dedupe_key] = row
    return found


def _scalar_row(item: Mapping[str, Any]) -> dict[str, Any]:
    """无字段映射时直接取标量键（嵌套对象 / 内部键 / 以下划线开头的临时键丢弃）."""
    return {
        str(key): value
        for key, value in item.items()
        if not str(key).startswith("_")
        and key not in _INTERNAL_KEYS
        and (isinstance(value, (str, int, float, bool)) or value is None)
    }


def _rows_from_items(
    items: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """候选 → 目标行；声明了 ``field_mapping`` 时按同一套归一逻辑换名 / 转类型."""
    if not mapping:
        return [_scalar_row(item) for item in items]
    transforms = field_mapping_from_payload(mapping)
    return apply_field_mapping(items, transforms).rows


def _record_item(
    db: Session,
    *,
    strategy_id: int,
    run_id: int | None,
    round_no: int,
    item: Mapping[str, Any],
    key: str,
    target_id: int | None,
    existing: dict[str, AcquisitionItem],
) -> None:
    """写一条台账（同键已存在则更新，保证唯一约束不冲突且留最新一次运行）."""
    payload = {
        "run_id": run_id,
        "round_no": round_no,
        "channel": str(item.get("channel") or "")[:64],
        "title": str(item.get("title") or "")[:500],
        "source_url": str(item.get("url") or item.get("source_url") or "")[:1000],
        "published_at": str(item.get("published_at") or "")[:64],
        "match_score": int(item.get("match_score") or 0),
        "target_kind": "table",
        "target_id": target_id,
        "payload_digest": content_digest(item.get("title"), item.get("summary") or item.get("content")),
    }
    row = existing.get(key)
    if row is None:
        db.add(AcquisitionItem(strategy_id=strategy_id, dedupe_key=key[:512], **payload))
        return
    for field_name, value in payload.items():
        setattr(row, field_name, value)
    db.add(row)


def dispatch_table_target(
    db: Session,
    *,
    strategy: AcquisitionStrategy,
    items: Sequence[Mapping[str, Any]],
    run_id: int | None,
    round_no: int,
    user: Any = None,
    identity: Sequence[str] = (),
) -> TargetReport:
    """把通过筛选的候选写入策略声明的表落点并记账."""
    from cndb.plugins.tables.models import DataTable

    report = TargetReport()
    targets = table_targets(strategy)
    if not targets:
        report.skipped = len(items)
        return report

    for target in targets:
        table_id = target.get("table_id")
        if table_id is None:
            report.errors.append({"target": "table", "error": "table 落点缺少 table_id"})
            continue
        table = db.get(DataTable, int(table_id))
        if table is None or table.workspace_id != strategy.workspace_id:
            report.errors.append({"target": f"table:{table_id}", "error": "目标表不存在或不属于当前工作区"})
            continue

        rows = _rows_from_items(items, target.get("field_mapping"))
        if not rows:
            report.skipped += len(items)
            continue
        match_keys = tuple(str(key) for key in (target.get("match_keys") or ()) if str(key).strip())
        try:
            outcome = upsert_rows(
                db.get_bind(),
                db,
                table,
                rows,
                match_keys=match_keys,
                user=user,
                auto_add_fields=not match_keys and is_table_empty(db, table),
                auto_match_keys=not match_keys,
                light=True,
            )
        except Exception as exc:  # 落点失败不影响台账之外的数据，按 partial 留痕
            db.rollback()
            report.errors.append({"target": f"table:{table_id}", "error": str(exc)[:300]})
            continue

        report.table_id = int(table_id)
        report.inserted += outcome.inserted
        report.updated += outcome.updated
        report.skipped += outcome.skipped
        report.written += outcome.changed

        fields = tuple(identity) or match_keys
        ledger = _load_ledger(db, strategy.id, items, fields)
        for item in items:
            key = dedupe_key(item, str(item.get("channel") or ""), fields)
            _record_item(
                db,
                strategy_id=strategy.id,
                run_id=run_id,
                round_no=round_no,
                item=item,
                key=key,
                target_id=int(table_id),
                existing=ledger,
            )
    db.commit()
    return report


# ── 文档落点 ──────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{(\w+)(?::([^}]+))?\}")


def _render_template(template: str, item: Mapping[str, Any]) -> str:
    """把 ``{field}`` / ``{published_at:%Y-%m-%d}`` 渲染成文本；未知字段留空串."""

    def _replace(match: Any) -> str:
        field_name, spec = match.group(1), match.group(2)
        value = item.get(field_name)
        if value is None:
            return ""
        text = str(value)
        if spec:
            parsed = _parse_day(text)
            if parsed is not None:
                return parsed.strftime(spec)
        return text

    return _TEMPLATE_RE.sub(_replace, template or "")


def _parse_day(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:19], text[:10]):
        try:
            return dt.datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _resolve_tag_ids(db: Session, workspace_id: int, names: Sequence[Any]) -> list[int]:
    """按名称解析已有标签 id（**不新建标签**，避免自动流程污染标签体系）."""
    from sqlalchemy import select

    from cndb.plugins.documents.models import Tag

    wanted = [str(name).strip() for name in names if str(name).strip()]
    if not wanted:
        return []
    stmt = select(Tag.id).where(Tag.workspace_id == workspace_id, Tag.name.in_(wanted))
    return [int(row) for row in db.execute(stmt).scalars()]


def _has_human_edit(db: Session, document_id: int) -> bool:
    """文档在自动版本之后是否有人工改动：最新版本非自动导入，或存在任何人草稿."""
    from sqlalchemy import select

    from cndb.plugins.documents.models import (
        CHANGE_TYPE_IMPORT,
        DocumentDraft,
    )
    from cndb.plugins.documents.services.content import latest_version

    version = latest_version(db, document_id)
    if version is None or version.change_type != CHANGE_TYPE_IMPORT:
        return True
    draft = db.execute(select(DocumentDraft.id).where(DocumentDraft.document_id == document_id).limit(1)).first()
    return draft is not None


def dispatch_document_target(
    db: Session,
    *,
    strategy: AcquisitionStrategy,
    items: Sequence[Mapping[str, Any]],
    run_id: int | None,
    round_no: int,
    user: Any = None,
) -> TargetReport:
    """把通过筛选的候选写入文档落点：新建 / 新版本 / 人工保护转 issue.

    ``llm.actions`` 含 ``item_summary`` 时先用模型把单条候选压成摘要 / 标签 / 分类，
    再作为 ``create_document`` / ``update_content`` 的入参 —— 模型输出**不直写业务表**（L8），
    单次运行最多摘要 ``llm.max_item_summaries``（默认 20）条，超额度直接回落原文摘要。
    """
    from cndb.plugins.acquisition.services import ai as acquisition_ai
    from cndb.plugins.documents.models import CHANGE_TYPE_IMPORT
    from cndb.plugins.documents.services import issues as document_issues
    from cndb.plugins.documents.services.content import (
        create_document,
        get_document_or_404,
        update_content,
    )

    report = TargetReport()
    targets = document_targets(strategy)
    if not targets:
        return report
    if user is None:
        report.errors.append({"target": "document", "error": "文档落点需要有效用户上下文（策略创建人）"})
        return report

    llm_conf = dict(strategy.llm or {})
    summary_enabled = bool(llm_conf.get("enabled")) and (
        not (isinstance(llm_conf.get("actions"), list) and llm_conf.get("actions"))
        or "item_summary" in {str(item) for item in llm_conf.get("actions") or []}
    )
    summary_budget = int(llm_conf.get("max_item_summaries") or acquisition_ai.DEFAULT_MAX_SUMMARIES)
    summary_meta: dict[str, Any] = {"calls": 0, "degraded": 0, "tokens": 0}

    for target in targets:
        parent_id = target.get("parent_id")
        title_template = str(target.get("title_template") or "{title}")
        body_template = str(target.get("body_template") or "# {title}\n\n{summary}\n\n> 来源：{url}")
        tag_ids = _resolve_tag_ids(db, strategy.workspace_id, list(target.get("tags") or []))
        ledger = _load_ledger(db, strategy.id, items, ())

        for item in items:
            key = dedupe_key(item, str(item.get("channel") or ""))
            render_item: Mapping[str, Any] = item
            extra_tag_names: list[str] = []
            if summary_enabled and summary_meta["calls"] < summary_budget:
                summary, meta = acquisition_ai.summarize_item(
                    db,
                    user,
                    item=item,
                    workspace_id=strategy.workspace_id,
                    strategy_id=strategy.id,
                )
                summary_meta["calls"] += 1
                summary_meta["tokens"] += int(meta.get("tokens") or 0)
                if meta.get("degraded"):
                    summary_meta["degraded"] += 1
                render_item = {**dict(item), "summary": summary["summary"]}
                if summary.get("category"):
                    render_item = {**dict(render_item), "category": summary["category"]}
                extra_tag_names = list(summary.get("tags") or [])
            title = _render_template(title_template, render_item).strip()[:200] or "未命名采集条目"
            body = _render_template(body_template, render_item).strip()
            digest = content_digest(title, body)
            row = ledger.get(key)

            row_tag_ids = tag_ids
            if extra_tag_names:
                extra_ids = _resolve_tag_ids(db, strategy.workspace_id, extra_tag_names)
                row_tag_ids = list(dict.fromkeys([*tag_ids, *extra_ids]))

            try:
                if row is None or row.target_kind != "document" or row.target_id is None:
                    doc = create_document(
                        db,
                        strategy.workspace_id,
                        user,
                        title=title,
                        content=body,
                        parent_id=int(parent_id) if parent_id is not None else None,
                        tag_ids=row_tag_ids,
                        change_type=CHANGE_TYPE_IMPORT,
                    )
                    report.docs_created += 1
                    _record_document_item(
                        db,
                        strategy_id=strategy.id,
                        run_id=run_id,
                        round_no=round_no,
                        item=item,
                        key=key,
                        document_id=doc.id,
                        digest=digest,
                    )
                    continue

                document_id = int(row.target_id)
                doc = get_document_or_404(db, strategy.workspace_id, document_id)
                if _has_human_edit(db, document_id):
                    document_issues.create_issue(
                        db,
                        strategy.workspace_id,
                        document_id,
                        user,
                        title="自动采集建议更新",
                        description=(
                            f"采集策略「{strategy.name}」抓到更新内容但本文档有人工修改，未覆盖。\n\n"
                            f"建议正文：\n\n{body[:1500]}"
                        ),
                    )
                    report.docs_skipped += 1
                    continue
                if row.payload_digest == digest:
                    report.docs_skipped += 1
                    continue
                update_content(
                    db,
                    strategy.workspace_id,
                    doc.id,
                    user,
                    content=body,
                    change_summary=f"自动采集更新（{strategy.name}）",
                    change_type=CHANGE_TYPE_IMPORT,
                )
                report.docs_updated += 1
                _record_document_item(
                    db,
                    strategy_id=strategy.id,
                    run_id=run_id,
                    round_no=round_no,
                    item=item,
                    key=key,
                    document_id=doc.id,
                    digest=digest,
                )
            except Exception as exc:  # 单条文档失败不拖垮整轮（I5）
                db.rollback()
                report.errors.append({"target": f"document:{key[:24]}", "error": str(exc)[:300]})
    if summary_meta["calls"]:
        report.llm = summary_meta
    db.commit()
    return report


def _record_document_item(
    db: Session,
    *,
    strategy_id: int,
    run_id: int | None,
    round_no: int,
    item: Mapping[str, Any],
    key: str,
    document_id: int,
    digest: str,
) -> None:
    """写 / 更新文档落点的台账行（同键更新，保留最新运行与落点 id）."""
    from sqlalchemy import select

    row = db.execute(
        select(AcquisitionItem).where(
            AcquisitionItem.strategy_id == strategy_id,
            AcquisitionItem.dedupe_key == key[:512],
        )
    ).scalar_one_or_none()
    if row is None:
        row = AcquisitionItem(strategy_id=strategy_id, dedupe_key=key[:512])
        db.add(row)
    row.run_id = run_id
    row.round_no = round_no
    row.channel = str(item.get("channel") or "")[:64]
    row.title = str(item.get("title") or item.get("name") or "")[:500]
    row.source_url = str(item.get("url") or item.get("source_url") or "")[:1000]
    row.published_at = str(item.get("published_at") or "")[:64]
    row.match_score = int(item.get("match_score") or 0)
    row.target_kind = "document"
    row.target_id = document_id
    row.payload_digest = digest
