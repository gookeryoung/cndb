"""embed_document_charts — 正文图表引用展开为内嵌块（ADR 0052 D5）.

存量正文（最新 / 历史版本、个人草稿、待审修改申请）里的
``{{chart:<id>|width=N}}`` 展开为 `` ```chart `` JSON 内嵌块（带 ``legacy_id``
供 downgrade 还原）；实例不存在 / 跨工作区的引用写成降级文字。

要点：

- **无 DDL**：数据迁移，覆盖三种正文存储形态（内联 / ``gz:`` / 外存 ``v{n}.md.gz``）；
- 迁移脚本自包含（不 import 应用服务），解码 / 编码 / 哈希逻辑就地复刻；
- 幂等：第二次运行已无旧引用，全部跳过；
- downgrade：仅把含 ``legacy_id`` 的块还原为旧占位符，原生块保持原样。

Revision ID: x2y3z4a5b6c7
Revises: e0f1a2b3c4d5
Create Date: 2026-10-27 12:00:00.000000
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "x2y3z4a5b6c7"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None

_INLINE_MAX_SIZE = 50 * 1024
_EXTERNAL_MIN_SIZE = 2 * 1024 * 1024
_COMPRESSED_PREFIX = "gz:"
_FTS_CONTENT_LIMIT = 65536

_LEGACY_RE = re.compile(r"^\{\{chart:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$")
_PARAM_RE = re.compile(r"\|([a-zA-Z]+)=([^|}]+)")
_PARAGRAPH_RE = re.compile(r"(\n\n+)")
_FENCE_START_RE = re.compile(r"^[ \t]{0,3}(`{3,})chart[ \t]*$")
_FENCE_END_RE = re.compile(r"^[ \t]{0,3}(`{3,})[ \t]*$")


def _docs_root() -> Path:
    from cndb.core.config import settings

    if settings.DATABASE_URL.startswith("sqlite:///"):
        return Path(settings.DATABASE_URL.replace("sqlite:///", "")).parent / "docs"
    return Path("data/docs")


def _external_path(doc_id: int, version_number: int) -> Path:
    return _docs_root() / str(doc_id) / f"v{version_number}.md.gz"


def _decode(raw: str, content_size: int, doc_id: int, version_number: int | None) -> str:
    if raw == "" and content_size > 0 and version_number is not None:
        path = _external_path(doc_id, version_number)
        if not path.is_file():
            return ""
        try:
            return _gzip_decompress(path.read_bytes()).decode("utf-8")
        except (OSError, EOFError, ValueError):
            return ""
    if raw.startswith(_COMPRESSED_PREFIX):
        try:
            return _gzip_decompress(base64.b64decode(raw[len(_COMPRESSED_PREFIX) :])).decode("utf-8")
        except (OSError, EOFError, ValueError):
            return ""
    return raw


def _gzip_decompress(data: bytes) -> bytes:
    import gzip

    return gzip.decompress(data)


def _encode(content: str, doc_id: int, version_number: int | None) -> tuple[str, int]:
    """按分级存储策略编码，返回 ``(DB content 值, content_size)``；外存原地重写."""
    import gzip

    raw = content.encode("utf-8")
    size = len(raw)
    if size <= _INLINE_MAX_SIZE:
        return content, size
    compressed = gzip.compress(raw, compresslevel=6)
    if size > _EXTERNAL_MIN_SIZE and version_number is not None:
        path = _external_path(doc_id, version_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        return "", size
    return _COMPRESSED_PREFIX + base64.b64encode(compressed).decode("ascii"), size


def _width(value: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 75
    return n if 25 <= n <= 100 else 75


def _serialize_block(
    template_key: str,
    config: object,
    width: int,
    title: str,
    legacy_id: int,
) -> str:
    payload: dict[str, object] = {
        "version": 1,
        "template": template_key,
        "title": title,
        "width": width,
        "config": config if isinstance(config, dict) else {},
        "legacy_id": legacy_id,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    return f"```chart\n{body}\n```"


def _normalize_config(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _expand_legacy(
    content: str, charts: dict[int, tuple[int, str, str, object]], docs: dict[int, int], doc_id: int
) -> tuple[str, int]:
    """旧引用 → 内嵌块；返回 ``(新正文, 改动数)``."""
    if not content or "{{chart:" not in content:
        return content, 0
    workspace_id = docs.get(doc_id)
    parts = _PARAGRAPH_RE.split(content)
    changed = 0
    for index, part in enumerate(parts):
        if index % 2 == 1 or not part:
            continue
        match = _LEGACY_RE.match(part.strip())
        if match is None:
            continue
        chart_id = int(match.group(1))
        width = 75
        for key, value in _PARAM_RE.findall(match.group(2) or ""):
            if key == "width":
                width = _width(value)
        chart = charts.get(chart_id)
        if chart is None or chart[0] != workspace_id:
            parts[index] = f"[图表引用无效：图表 #{chart_id} 不存在或无访问权限]"
        else:
            _ws, title, template_key, config = chart
            parts[index] = _serialize_block(template_key, _normalize_config(config), width, title, chart_id)
        changed += 1
    return "".join(parts), changed


def _collapse_legacy(content: str) -> tuple[str, int]:
    """内嵌块（含 legacy_id）→ 旧占位符；原生块保持原样."""
    segments = _PARAGRAPH_RE.split(content)
    changed = 0
    for index, part in enumerate(segments):
        if index % 2 == 1 or not part:
            continue
        lines = part.strip("\n").split("\n")
        if len(lines) < 2:
            continue
        start = _FENCE_START_RE.match(lines[0])
        end = _FENCE_END_RE.match(lines[-1])
        if start is None or end is None or len(end.group(1)) < len(start.group(1)):
            continue
        try:
            payload = json.loads("\n".join(lines[1:-1]).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        legacy_id = payload.get("legacy_id")
        if not isinstance(legacy_id, int):
            continue
        width = payload.get("width")
        width = width if isinstance(width, int) and 25 <= width <= 100 else 75
        suffix = "" if width == 75 else f"|width={width}"
        segments[index] = f"{{{{chart:{legacy_id}{suffix}}}}}"
        changed += 1
    return "".join(segments), changed


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _fts_upsert(bind: sa.Connection, doc_id: int) -> None:
    row = (
        bind.execute(
            sa.text("SELECT title, summary, author FROM documents_document WHERE id = :id"),
            {"id": doc_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return
    version = (
        bind.execute(
            sa.text(
                "SELECT id, version_number, content, content_size FROM documents_documentversion "
                "WHERE document_id = :id ORDER BY version_number DESC LIMIT 1"
            ),
            {"id": doc_id},
        )
        .mappings()
        .first()
    )
    if version is None:
        return
    text = _decode(version["content"] or "", int(version["content_size"] or 0), doc_id, version["version_number"])
    bind.execute(
        sa.text(
            "INSERT OR REPLACE INTO documents_fts(rowid, title, content, summary, author) "
            "VALUES (:doc_id, :title, :content, :summary, :author)"
        ),
        {
            "doc_id": doc_id,
            "title": row["title"],
            "content": text[:_FTS_CONTENT_LIMIT],
            "summary": (row["summary"] or "")[:2000],
            "author": row["author"] or "",
        },
    )


def _has_table(bind: sa.Connection, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    required = (
        "documents_chart",
        "documents_document",
        "documents_documentversion",
        "documents_draft",
        "documents_changerequest",
    )
    if not all(_has_table(bind, name) for name in required):
        # 部分测试 / 早期库缺表：启动 create_all 会补齐，本迁移无可展开的正文
        return
    charts = {
        int(row["id"]): (
            int(row["workspace_id"]),
            row["title"] or "",
            row["template_key"],
            row["config"],
        )
        for row in bind.execute(
            sa.text("SELECT id, workspace_id, title, template_key, config FROM documents_chart")
        ).mappings()
    }
    docs = {
        int(row["id"]): int(row["workspace_id"])
        for row in bind.execute(sa.text("SELECT id, workspace_id FROM documents_document")).mappings()
    }

    # 历史版本（含最新）：展开旧引用并回写存储
    versions = (
        bind.execute(
            sa.text("SELECT id, document_id, version_number, content, content_size FROM documents_documentversion")
        )
        .mappings()
        .all()
    )
    touched_docs: set[int] = set()
    latest_changed: dict[int, tuple[int, int]] = {}
    for row in versions:
        doc_id = int(row["document_id"])
        version_number = int(row["version_number"])
        text = _decode(row["content"] or "", int(row["content_size"] or 0), doc_id, version_number)
        new_text, changed = _expand_legacy(text, charts, docs, doc_id)
        if not changed:
            continue
        stored, size = _encode(new_text, doc_id, version_number)
        bind.execute(
            sa.text(
                "UPDATE documents_documentversion SET content = :content, content_size = :size, "
                "content_hash = :hash WHERE id = :id"
            ),
            {"content": stored, "size": size, "hash": _hash(new_text), "id": row["id"]},
        )
        touched_docs.add(doc_id)
        previous = latest_changed.get(doc_id)
        if previous is None or version_number > previous[0]:
            latest_changed[doc_id] = (version_number, size)

    for doc_id, (_version, size) in latest_changed.items():
        bind.execute(
            sa.text("UPDATE documents_document SET content_size = :size WHERE id = :id"),
            {"size": size, "id": doc_id},
        )

    # 个人草稿（内联）
    for row in bind.execute(sa.text("SELECT id, document_id, content FROM documents_draft")).mappings():
        doc_id = int(row["document_id"])
        new_text, changed = _expand_legacy(row["content"] or "", charts, docs, doc_id)
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE documents_draft SET content = :content, content_size = :size, "
                "content_hash = :hash WHERE id = :id"
            ),
            {"content": new_text, "size": len(new_text.encode("utf-8")), "hash": _hash(new_text), "id": row["id"]},
        )

    # 待审修改申请（内联）
    for row in bind.execute(
        sa.text("SELECT id, document_id, proposed_content FROM documents_changerequest")
    ).mappings():
        doc_id = int(row["document_id"])
        new_text, changed = _expand_legacy(row["proposed_content"] or "", charts, docs, doc_id)
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE documents_changerequest SET proposed_content = :content, proposed_size = :size WHERE id = :id"
            ),
            {"content": new_text, "size": len(new_text.encode("utf-8")), "id": row["id"]},
        )
        touched_docs.add(doc_id)

    for doc_id in sorted(touched_docs):
        _fts_upsert(bind, doc_id)


def downgrade() -> None:
    bind = op.get_bind()
    if not all(
        _has_table(bind, name)
        for name in ("documents_documentversion", "documents_document", "documents_draft", "documents_changerequest")
    ):
        return
    latest_changed: dict[int, tuple[int, int]] = {}
    touched_docs: set[int] = set()
    versions = (
        bind.execute(
            sa.text("SELECT id, document_id, version_number, content, content_size FROM documents_documentversion")
        )
        .mappings()
        .all()
    )
    for row in versions:
        doc_id = int(row["document_id"])
        version_number = int(row["version_number"])
        text = _decode(row["content"] or "", int(row["content_size"] or 0), doc_id, version_number)
        new_text, changed = _collapse_legacy(text)
        if not changed:
            continue
        stored, size = _encode(new_text, doc_id, version_number)
        bind.execute(
            sa.text(
                "UPDATE documents_documentversion SET content = :content, content_size = :size, "
                "content_hash = :hash WHERE id = :id"
            ),
            {"content": stored, "size": size, "hash": _hash(new_text), "id": row["id"]},
        )
        touched_docs.add(doc_id)
        previous = latest_changed.get(doc_id)
        if previous is None or version_number > previous[0]:
            latest_changed[doc_id] = (version_number, size)

    for doc_id, (_version, size) in latest_changed.items():
        bind.execute(
            sa.text("UPDATE documents_document SET content_size = :size WHERE id = :id"),
            {"size": size, "id": doc_id},
        )

    for row in bind.execute(sa.text("SELECT id, document_id, content FROM documents_draft")).mappings():
        new_text, changed = _collapse_legacy(row["content"] or "")
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE documents_draft SET content = :content, content_size = :size, "
                "content_hash = :hash WHERE id = :id"
            ),
            {"content": new_text, "size": len(new_text.encode("utf-8")), "hash": _hash(new_text), "id": row["id"]},
        )

    for row in bind.execute(
        sa.text("SELECT id, document_id, proposed_content FROM documents_changerequest")
    ).mappings():
        new_text, changed = _collapse_legacy(row["proposed_content"] or "")
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE documents_changerequest SET proposed_content = :content, proposed_size = :size WHERE id = :id"
            ),
            {"content": new_text, "size": len(new_text.encode("utf-8")), "id": row["id"]},
        )
        touched_docs.add(int(row["document_id"]))

    for doc_id in sorted(touched_docs):
        _fts_upsert(bind, doc_id)
