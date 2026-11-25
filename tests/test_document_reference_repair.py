"""跨工作区移动后的引用修复（ADR 0156）测试.

覆盖：
- 诊断两方向：被移动文档内指向源工作区的 `[[双链]]` / `{{table:…}}`；源工作区文档指向被移动文档；
- 原因分类：`target_left_behind` / `target_not_found` / `target_moved` /
  `table_in_other_workspace` / `table_deleted`；同一子树内的引用不算失效；
- 预览不落库；`annotate` 文案与 `snapshot` 静态表格；
- 执行生成新版本（`change_type=move_repair`）、事件、幂等（二次 0 变更）；
- 代码围栏内文本不被改写；
- 移动端点携带 `repair_strategy` 时一次完成「移动 + 修复」；
- 快照失败（表已删）降级为注释；上限 400。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData
from sqlalchemy.orm import Session

from cndb.core.events import CoreEvent
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import CHANGE_TYPE_MOVE_REPAIR, Document, DocumentVersion
from cndb.plugins.documents.services import references as refs_service
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl as table_ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
MOVE = "/api/v1/workspaces/{ws}/documents/move-to-workspace"
PREVIEW = "/api/v1/workspaces/{ws}/documents/references/preview"
REPAIR = "/api/v1/workspaces/{ws}/documents/references/repair"


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_workspace(db: Session, owner: User, name: str) -> Workspace:
    ws = Workspace(name=name, created_by_id=owner.id, modules=["tables", "documents"])
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return ws


def _make_table(db: Session, ws: Workspace, name: str) -> DataTable:
    engine = db.get_bind()
    table = DataTable(workspace_id=ws.id, owner_id=ws.created_by_id, name=name)
    table.ensure_db_name()
    db.add(table)
    db.flush()
    field = DataField(table_id=table.id, name="指标", field_type="text", order=0)
    other = DataField(table_id=table.id, name="数值", field_type="text", order=1)
    field.ensure_db_name()
    other.ensure_db_name()
    db.add_all([field, other])
    db.commit()
    db.refresh(table)
    table_ddl.create_table(engine, table)
    meta = MetaData()
    meta.reflect(bind=engine, only=[table.db_table_name])
    sa_table = meta.tables[table.db_table_name]
    with engine.begin() as conn:
        conn.execute(
            sa_table.insert(),
            [
                {field.db_column_name: "覆盖率", other.db_column_name: "95.2"},
                {field.db_column_name: "用例数", other.db_column_name: "7319"},
            ],
        )
    return table


def _create_doc(
    client: TestClient, ws: Workspace, headers: dict[str, str], *, title: str, content: str = "正文\n"
) -> dict:
    resp = client.post(
        f"{DOCS.format(ws=ws.id)}",
        json={"title": title, "content": content, "status": "published"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _versions(db: Session, doc_id: int) -> list[DocumentVersion]:
    return (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number)
        .all()
    )


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "rep_owner")


@pytest.fixture
def source(db, owner) -> Workspace:
    return _make_workspace(db, owner, "引用源工作区")


@pytest.fixture
def target(db, owner) -> Workspace:
    return _make_workspace(db, owner, "引用目标工作区")


@pytest.fixture
def headers(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


class TestDiagnose:
    def test_wikilink_directions_and_reasons(self, client, db, source, target, headers):
        left_behind = _create_doc(client, source, headers, title="留在源工作区")
        moved = _create_doc(
            client,
            source,
            headers,
            title="被移动文档",
            content="[[留在源工作区]] 与 [[不存在的标题]]\n\n另见 [[被移动文档]]\n",
        )
        referrer = _create_doc(client, source, headers, title="源侧引用者", content="参见 [[被移动文档]]\n")

        moved_ids = [moved["id"]]
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": moved_ids, "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )

        issues = refs_service.diagnose_move_references(
            db, source_workspace_id=source.id, target_workspace_id=target.id, moved_doc_ids=moved_ids
        )
        by_reason: dict[str, list] = {}
        for issue in issues:
            by_reason.setdefault(issue.reason, []).append(issue)

        # 指向留在源工作区的文档
        left = by_reason[refs_service.REASON_TARGET_LEFT_BEHIND][0]
        assert left.document_id == moved["id"]
        assert left.target_workspace_id == source.id
        assert left.target_workspace_name == source.name
        # 指向不存在的标题
        missing = by_reason[refs_service.REASON_TARGET_NOT_FOUND][0]
        assert missing.target_title == "不存在的标题"
        # 源侧残留文档指向被移动文档
        moved_ref = by_reason[refs_service.REASON_TARGET_MOVED][0]
        assert moved_ref.document_id == referrer["id"]
        assert moved_ref.target_workspace_id == target.id
        assert moved_ref.target_workspace_name == target.name
        # 同一子树内（[[被移动文档]] 自引用）不算失效
        assert all(issue.document_id != moved["id"] or issue.target_title != "被移动文档" for issue in issues)
        assert left_behind["id"] != left.document_id

    def test_table_refs_reasons(self, client, db, source, target, headers):
        source_table = _make_table(db, source, "源表")
        target_table = _make_table(db, target, "目标表")
        moved = _create_doc(
            client,
            source,
            headers,
            title="表格引用文档",
            content=f"{{{{table:{source_table.id}}}}}\n\n{{{{table:{target_table.id}}}}}\n\n{{{{table:999999}}}}\n",
        )
        move_resp = client.post(
            MOVE.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
            headers=headers,
        )
        assert move_resp.status_code == 200, move_resp.text

        issues = refs_service.diagnose_move_references(
            db, source_workspace_id=source.id, target_workspace_id=target.id, moved_doc_ids=[moved["id"]]
        )
        table_issues = [issue for issue in issues if issue.kind == "table_ref"]
        assert len(table_issues) == 2
        reasons = {issue.reason for issue in table_issues}
        assert reasons == {
            refs_service.REASON_TABLE_IN_OTHER_WORKSPACE,
            refs_service.REASON_TABLE_DELETED,
        }


class TestPreview:
    def test_preview_does_not_write(self, client, db, source, target, headers):
        left = _create_doc(client, source, headers, title="预览目标")
        moved = _create_doc(client, source, headers, title="预览文档", content=f"[[预览目标]]\n\n{left['title']}\n")
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )
        before = len(_versions(db, moved["id"]))

        resp = client.post(
            PREVIEW.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "annotate"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["strategy"] == "annotate"
        assert any(preview["next"] == f"预览目标（已移至「{source.name}」）" for preview in body["previews"])
        # 预览不落库
        assert len(_versions(db, moved["id"])) == before

    def test_snapshot_renders_static_table(self, client, db, source, target, headers):
        table = _make_table(db, source, "快照表")
        moved = _create_doc(client, source, headers, title="快照文档", content=f"{{{{table:{table.id}|width=60}}}}\n")
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )

        resp = client.post(
            PREVIEW.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "snapshot"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        previews = resp.json()["previews"]
        table_preview = next(item for item in previews if item["kind"] == "table_ref")
        assert "| 指标 | 数值 |" in table_preview["next"]
        assert "覆盖率" in table_preview["next"]
        assert "{{table:" not in table_preview["next"]


class TestApply:
    def test_annotate_creates_version_and_event(self, client, db, source, target, headers):
        _create_doc(client, source, headers, title="留在源")
        moved = _create_doc(client, source, headers, title="执行文档", content="见 [[留在源]]\n")
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )

        resp = client.post(
            REPAIR.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "annotate"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["changed_documents"] == 1
        assert body["changed_references"] == 1

        versions = _versions(db, moved["id"])
        assert versions[-1].change_type == CHANGE_TYPE_MOVE_REPAIR
        assert versions[-1].change_summary == "跨工作区移动引用修复"
        from cndb.plugins.documents.services import content as content_service

        text = content_service.load_content(versions[-1], db.get(Document, moved["id"]))
        assert f"留在源（已移至「{source.name}」）" in text
        assert "[[留在源]]" not in text

        events = db.query(CoreEvent).filter(CoreEvent.action == "documents.references_repaired").all()
        assert len(events) == 1
        assert events[0].workspace_id == target.id

        # 幂等：二次执行无变更、不再生成版本
        again = client.post(
            REPAIR.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "annotate"},
            headers=headers,
        )
        assert again.status_code == 200
        assert again.json()["changed_documents"] == 0
        assert len(_versions(db, moved["id"])) == len(versions)

    def test_code_fence_untouched(self, client, db, source, target, headers):
        _create_doc(client, source, headers, title="围栏目标")
        moved = _create_doc(
            client,
            source,
            headers,
            title="围栏文档",
            content="正文 [[围栏目标]]\n\n```md\n[[围栏目标]]\n```\n",
        )
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                REPAIR.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "annotate"},
                headers=headers,
            ).status_code
            == 200
        )

        from cndb.plugins.documents.services import content as content_service

        versions = _versions(db, moved["id"])
        text = content_service.load_content(versions[-1], db.get(Document, moved["id"]))
        assert "正文 围栏目标（已移至" in text
        # 围栏内保持原样
        assert "```md\n[[围栏目标]]\n```" in text

    def test_snapshot_failure_degrades_to_annotation(self, client, db, source, target, headers):
        table = _make_table(db, source, "待删表")
        moved = _create_doc(client, source, headers, title="降级文档", content=f"{{{{table:{table.id}}}}}\n")
        assert (
            client.post(
                MOVE.format(ws=source.id),
                json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
                headers=headers,
            ).status_code
            == 200
        )
        # 表被彻底删除后再修复（快照拿不到数据 → 降级为注释）
        db.delete(db.get(DataTable, table.id))
        db.commit()
        resp = client.post(
            REPAIR.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id, "strategy": "snapshot"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        from cndb.plugins.documents.services import content as content_service

        versions = _versions(db, moved["id"])
        text = content_service.load_content(versions[-1], db.get(Document, moved["id"]))
        assert "数据表引用已失效" in text


class TestMoveWithStrategy:
    def test_move_and_repair_in_one_request(self, client, db, source, target, headers):
        table = _make_table(db, source, "移动快照表")
        _create_doc(client, source, headers, title="移动留下")
        moved = _create_doc(
            client,
            source,
            headers,
            title="移动修复文档",
            content=f"[[移动留下]]\n\n{{{{table:{table.id}}}}}\n",
        )
        referrer = _create_doc(client, source, headers, title="源侧引用", content="见 [[移动修复文档]]\n")

        resp = client.post(
            MOVE.format(ws=source.id),
            json={
                "document_ids": [moved["id"]],
                "target_workspace_id": target.id,
                "repair_strategy": "snapshot",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        repair = resp.json()["reference_repair"]
        assert repair is not None
        assert repair["changed_documents"] >= 1

        from cndb.plugins.documents.services import content as content_service

        moved_versions = _versions(db, moved["id"])
        moved_text = content_service.load_content(moved_versions[-1], db.get(Document, moved["id"]))
        assert f"移动留下（已移至「{source.name}」）" in moved_text
        assert "| 指标 | 数值 |" in moved_text

        referrer_versions = _versions(db, referrer["id"])
        referrer_text = content_service.load_content(referrer_versions[-1], db.get(Document, referrer["id"]))
        assert f"移动修复文档（已移至「{target.name}」）" in referrer_text

    def test_strategy_none_leaves_content_untouched(self, client, db, source, target, headers):
        _create_doc(client, source, headers, title="不动目标")
        moved = _create_doc(client, source, headers, title="不动文档", content="见 [[不动目标]]\n")
        before = len(_versions(db, moved["id"]))
        resp = client.post(
            MOVE.format(ws=source.id),
            json={"document_ids": [moved["id"]], "target_workspace_id": target.id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "reference_repair" not in resp.json() or resp.json()["reference_repair"] is None
        assert len(_versions(db, moved["id"])) == before
        moved_row = db.get(Document, moved["id"])
        assert moved_row is not None and moved_row.workspace_id == target.id


class TestGuards:
    def test_unsupported_strategy_rejected(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="非法策略")
        resp = client.post(
            PREVIEW.format(ws=source.id),
            json={"document_ids": [doc["id"]], "target_workspace_id": target.id, "strategy": "auto"},
            headers=headers,
        )
        assert resp.status_code in (400, 422)

    def test_too_many_documents_rejected(self, client, source, target, headers):
        doc = _create_doc(client, source, headers, title="超限")
        resp = client.post(
            PREVIEW.format(ws=source.id),
            json={"document_ids": [doc["id"]] * 201, "target_workspace_id": target.id, "strategy": "annotate"},
            headers=headers,
        )
        assert resp.status_code in (400, 422)

    def test_viewer_cannot_repair(self, client, db, source, target, headers):
        doc = _create_doc(client, source, headers, title="只读用户")
        viewer = _make_user(db, "rep_viewer")
        db.add(WorkspaceMember(workspace_id=source.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_headers = _login(client, viewer.username)
        resp = client.post(
            REPAIR.format(ws=source.id),
            json={"document_ids": [doc["id"]], "target_workspace_id": target.id, "strategy": "annotate"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403
        assert db.query(DocumentVersion).filter(DocumentVersion.document_id == doc["id"]).count() == 1
