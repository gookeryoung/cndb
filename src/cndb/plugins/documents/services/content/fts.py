"""全文检索索引同步（FTS5 主表与 trigram 影子表）（ADR 0180 D1）."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from cndb.plugins.documents.models import (
    Document,
)

logger = logging.getLogger("cndb.plugins.documents.services.content")


def sync_fts(db: Session, doc: Document, content: str) -> None:
    """将文档同步到 FTS5 索引（content 列截断到 64KB 防索引膨胀）.

    FTS5 虚拟表不支持标准 UPSERT，使用 INSERT OR REPLACE（自动删旧插新）。
    """
    from cndb.plugins.documents.services.search import ensure_fts_schema

    ensure_fts_schema(db)
    params = {
        "doc_id": doc.id,
        "title": doc.title,
        "content": content[:65536],
        "summary": doc.summary[:2000],
        "author": doc.author,
    }
    db.execute(_fts_upsert_sql("documents_fts"), params)
    # trigram 影子表（0171）与主表同 rowid 同步维护；两表内容一致，分词器不同。
    db.execute(_fts_upsert_sql("documents_fts_tri"), params)


def _fts_upsert_sql(table: str = "documents_fts"):
    from sqlalchemy import text

    # 表名来自本模块常量调用点，非用户输入；FTS 虚拟表名不接受 bind 参数。
    return text(
        f"""
        INSERT OR REPLACE INTO {table}(rowid, title, content, summary, author)
        VALUES (:doc_id, :title, :content, :summary, :author)
        """
    )


def _sync_fts_delete(db: Session, doc_id: int) -> None:
    """从 FTS5 索引移除文档：内容清空（FTS5 delete 命令需旧值，清空更简单可靠）."""
    empty = {"doc_id": doc_id, "title": "", "content": "", "summary": "", "author": ""}
    db.execute(_fts_upsert_sql("documents_fts"), empty)
    db.execute(_fts_upsert_sql("documents_fts_tri"), empty)
