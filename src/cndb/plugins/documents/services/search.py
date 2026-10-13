"""FTS5 全文检索服务.

基于 SQLite FTS5 虚拟表（documents_fts），支持：
- 关键词搜索（unicode61 分词）
- 前缀匹配（``abc*``）
- 精确短语（``"exact phrase"``）
- 布尔组合（AND / OR / NOT）
- 内置 highlight() 高亮与 rank 相关性排序
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError

# FTS5 保留的特殊 token（用户输入中的裸字符需要转义处理）
_FTS5_SYNTAX_HINT = {"AND", "OR", "NOT", "NEAR"}

_fts_state = {"ready": False}

_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, content, summary, author,
    tokenize='unicode61'
)
"""


def ensure_fts_schema(db: Session) -> None:
    """幂等创建 FTS5 虚拟表（进程内只执行一次）.

    生产路径由 alembic 迁移创建；本函数兜底 create_all 场景
    （全新数据库首次启动时 alembic 只 create_all ORM 表，不含虚拟表）。
    """
    if _fts_state["ready"]:
        return
    db.execute(text(_FTS_CREATE_SQL))
    db.commit()
    _fts_state["ready"] = True


def escape_query(query: str) -> str:
    """将用户输入转为安全的 FTS5 MATCH 表达式.

    规则：
    - 保留用户有意使用的 "..."（短语）、*（前缀）
    - AND/OR/NOT/NEAR 大写保留为布尔语法
    - 其它裸引号转义；空词条拆分为 AND 隐式组合
    """
    query = query.strip()
    if not query:
        raise BadRequestError("搜索关键词不能为空")

    tokens: list[str] = []
    buf = ""
    in_phrase = False
    for ch in query:
        if ch == '"':
            buf += ch
            if in_phrase and buf.strip('"'):
                tokens.append(buf)
                buf = ""
            in_phrase = not in_phrase
            continue
        if not in_phrase and ch == " " and buf:
            tokens.append(buf)
            buf = ""
            continue
        if not in_phrase and ch in "():^{}":
            continue  # 丢弃特殊字符（保留 * 前缀语法）
        buf += ch
    if buf:
        tokens.append(buf)

    parts: list[str] = []
    for tok in tokens:
        bare = tok.strip('"')
        if bare in _FTS5_SYNTAX_HINT or tok.endswith("*") or tok.startswith('"'):
            parts.append(tok)
        else:
            parts.append(f'"{bare}"')  # 普通词加引号防语法注入
    if not parts:
        raise BadRequestError("搜索关键词无效")
    return " ".join(parts)


def search_documents(
    db: Session,
    query: str,
    *,
    workspace_id: int | None = None,
    tag_ids: list[int] | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """执行 FTS5 搜索.

    Returns:
        (命中列表 [{...字段 + title_hit/summary_hit/rank}], 总命中数)
    """
    match_expr = escape_query(query)

    where_parts = ["documents_fts MATCH :q", "d.is_deleted = 0"]
    params: dict[str, Any] = {"q": match_expr}

    if workspace_id is not None:
        where_parts.append("d.workspace_id = :wid")
        params["wid"] = workspace_id
    if status:
        where_parts.append("d.status = :status")
        params["status"] = status
    if tag_ids:
        placeholders = ",".join(f":t{i}" for i in range(len(tag_ids)))
        where_parts.append(f"d.id IN (SELECT document_id FROM documents_documenttag WHERE tag_id IN ({placeholders}))")
        params.update({f"t{i}": tid for i, tid in enumerate(tag_ids)})

    where_clause = " AND ".join(where_parts)

    total = int(
        db.execute(
            text(
                f"SELECT count(*) FROM documents_fts "
                f"JOIN documents_document d ON documents_fts.rowid = d.id "
                f"WHERE {where_clause}"
            ),
            params,
        ).scalar_one()
    )

    rows = db.execute(
        text(
            f"""
            SELECT d.id, d.title, d.workspace_id, d.status, d.updated_at,
                   highlight(documents_fts, 1, '<mark>', '</mark>') AS content_hit,
                   highlight(documents_fts, 2, '<mark>', '</mark>') AS summary_hit,
                   bm25(documents_fts) AS rank
            FROM documents_fts
            JOIN documents_document d ON documents_fts.rowid = d.id
            WHERE {where_clause}
            ORDER BY rank
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()

    items = []
    for row in rows:
        content_hit = row.content_hit or ""
        # content 命中片段裁剪：取首个 <mark> 前后各 80 字符
        snippet = _snippet(content_hit)
        items.append(
            {
                "id": row.id,
                "title": row.title,
                "title_hit": f"<mark>{row.title}</mark>" if _query_hit_title(match_expr, row.title) else row.title,
                "summary_hit": row.summary_hit or snippet,
                "workspace_id": row.workspace_id,
                "status": row.status,
                "updated_at": row.updated_at,
                "rank": float(row.rank) if row.rank is not None else 0.0,
            }
        )
    return items, total


def _query_hit_title(match_expr: str, title: str) -> bool:
    """粗判标题是否命中（用于标题高亮展示）。"""
    for tok in match_expr.replace('"', " ").split():
        tok = tok.strip("*")
        if tok and tok.lower() in title.lower():
            return True
    return False


def _snippet(content_hit: str, pad: int = 80) -> str:
    """裁剪长内容命中片段到首个 mark 标记附近."""
    idx = content_hit.find("<mark>")
    if idx == -1:
        return content_hit[: pad * 2]
    start = max(0, idx - pad)
    end = min(len(content_hit), idx + pad * 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content_hit) else ""
    return f"{prefix}{content_hit[start:end]}{suffix}"


def rebuild_fts_index(db: Session) -> int:
    """全量重建 FTS5 索引（修复索引不一致时的兜底任务）.

    Returns:
        重建的文档数。
    """
    from sqlalchemy import select

    from cndb.plugins.documents.models import Document

    db.execute(text("INSERT INTO documents_fts(documents_fts) VALUES ('delete-all')"))
    docs = (
        db.execute(
            select(Document).where(
                Document.is_deleted == False,  # noqa: E712
                Document.is_folder == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )

    from cndb.plugins.documents.services.content import latest_version, load_content

    count = 0
    for doc in docs:
        v = latest_version(db, doc.id)
        content = load_content(v, doc)
        db.execute(
            text(
                "INSERT INTO documents_fts(rowid, title, content, summary, author) "
                "VALUES (:id, :title, :content, :summary, :author)"
            ),
            {
                "id": doc.id,
                "title": doc.title,
                "content": content[:65536],
                "summary": doc.summary[:2000],
                "author": doc.author,
            },
        )
        count += 1
    db.commit()
    return count


__all__ = ["ensure_fts_schema", "escape_query", "rebuild_fts_index", "search_documents"]
