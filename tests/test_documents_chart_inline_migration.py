"""迁移 x2y3z4a5b6c7（embed_document_charts）回归测试（ADR 0052 D5 / D12）.

覆盖：最新版本 / 历史版本 / 草稿 / 修改申请的旧引用展开、外存版本原地重写、
失效实例降级文字、FTS 同步、幂等、downgrade 经 ``legacy_id`` 还原。
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.core.migrations import _build_config, upgrade_to_head
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import Document, DocumentChart, DocumentDraft, DocumentVersion
from cndb.plugins.workspaces.models import Workspace

PRE_REVISION = "e0f1a2b3c4d5"
MIGRATION = importlib.import_module("cndb.alembic.versions.x2y3z4a5b6c7_embed_document_charts")

BLOCK_MARK = "```chart"
TEMPLATE = "stacked-bar-horizontal"


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'inline.db').as_posix()}"


def _make_session(url: str) -> Session:
    engine = create_engine(url)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session: Session, tmp_path: Path, content: str) -> dict[str, int]:
    user = User(username="mig_owner", nickname="mig")
    user.set_password("passw0rd")
    session.add(user)
    session.flush()
    ws = Workspace(name="MigWS", created_by_id=user.id)
    session.add(ws)
    session.flush()

    chart = DocumentChart(
        workspace_id=ws.id, title="旧图", template_key=TEMPLATE, config={"a": 1}, created_by_id=user.id
    )
    session.add(chart)
    session.flush()

    doc = Document(
        workspace_id=ws.id,
        title="迁移文档",
        created_by_id=user.id,
        status="draft",
    )
    session.add(doc)
    session.flush()

    body = content.replace("{CHART}", str(chart.id))
    v1 = DocumentVersion(document_id=doc.id, version_number=1, content=body, content_size=len(body.encode("utf-8")))
    doc_id, chart_id = doc.id, chart.id
    session.add(v1)
    session.flush()
    doc.content_size = len(body.encode("utf-8"))
    session.add(
        DocumentDraft(
            document_id=doc_id,
            user_id=user.id,
            content=body,
            content_size=len(body.encode("utf-8")),
            content_hash="0" * 64,
            base_version_number=1,
        )
    )
    session.commit()
    return {"doc": doc_id, "chart": chart_id}


def _ready(tmp_path: Path, content: str) -> tuple[str, dict[str, int]]:
    """建全量库 → 落数据 → stamp 到迁移前 revision（等待 upgrade 触发数据迁移）."""
    url = _url(tmp_path)
    upgrade_to_head(url)  # 建全量结构（含 FTS / 各插件表）
    session = _make_session(url)
    ids = _seed(session, tmp_path, content)
    session.close()
    command.stamp(_build_config(url), PRE_REVISION)  # 回退版本号，等待 upgrade 触发数据迁移
    return url, ids


def _fetch(url: str, doc_id: int) -> tuple[str, str, str]:
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    try:
        version = conn.execute(
            "SELECT content FROM documents_documentversion WHERE document_id = ? ORDER BY version_number DESC",
            (doc_id,),
        ).fetchone()[0]
        draft = conn.execute("SELECT content FROM documents_draft WHERE document_id = ?", (doc_id,)).fetchone()[0]
        fts = conn.execute("SELECT content FROM documents_fts WHERE rowid = ?", (doc_id,)).fetchone()
    finally:
        conn.close()
    return version, draft, (fts[0] if fts else "")


def test_upgrade_expands_legacy_reference(tmp_path: Path) -> None:
    url, ids = _ready(tmp_path, "前文\n\n{{chart:{CHART}|width=60}}\n\n后文")
    upgrade_to_head(url)

    version, draft, fts = _fetch(url, ids["doc"])
    for text in (version, draft):
        assert BLOCK_MARK in text
        assert "{{chart:" not in text
        assert '"legacy_id": ' + str(ids["chart"]) in text
        assert '"width": 60' in text
    assert BLOCK_MARK in fts


def test_missing_chart_degrades(tmp_path: Path) -> None:
    url, ids = _ready(tmp_path, "前文\n\n{{chart:999999}}\n\n后文")
    upgrade_to_head(url)
    version, _draft, _fts = _fetch(url, ids["doc"])
    assert "图表引用无效" in version
    assert "999999" in version


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    url, ids = _ready(tmp_path, "{{chart:{CHART}}}")
    upgrade_to_head(url)
    first, _draft, _fts = _fetch(url, ids["doc"])
    upgrade_to_head(url)
    second, _draft2, _fts2 = _fetch(url, ids["doc"])
    assert first == second
    assert first.count(BLOCK_MARK) == 1


def test_downgrade_restores_legacy_reference(tmp_path: Path) -> None:
    url, ids = _ready(tmp_path, "前文\n\n{{chart:{CHART}|width=60}}\n\n后文")
    upgrade_to_head(url)
    command.downgrade(_build_config(url), PRE_REVISION)
    version, draft, _fts = _fetch(url, ids["doc"])
    assert f"{{{{chart:{ids['chart']}|width=60}}}}" in version
    assert f"{{{{chart:{ids['chart']}|width=60}}}}" in draft
    assert BLOCK_MARK not in version


def test_external_version_rewritten_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs_root = tmp_path / "docs"
    url, ids = _url(tmp_path), {}
    monkeypatch.setattr(settings, "DATABASE_URL", url)

    big = "填充" * (400 * 1024)  # ~2.4MB → 外存
    url, ids = _ready(tmp_path, big + "\n\n{{chart:{CHART}}}\n\n尾部")
    upgrade_to_head(url)
    path = docs_root / str(ids["doc"]) / "v1.md.gz"
    assert path.is_file()
    import gzip

    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    assert BLOCK_MARK in text
    assert gzip.decompress(path.read_bytes()).decode("utf-8") == text
