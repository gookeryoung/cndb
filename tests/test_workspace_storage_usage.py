"""工作区存储用量统计口径测试.

背景（回归）：``workspace_storage_bytes`` 早期只汇总磁盘上的附件与文档外存
版本文件，看不到直接落库的内容 —— 有数据表记录、内联文档正文的工作区
「已用空间」显示为 0。本文件覆盖修正后的口径：

- 数据表记录（物理表逐行单元格字节数）计入用量；
- 内联文档正文 / 个人草稿计入用量；
- 外存文档正文按文件实际大小计入，且**不**被重复统计为内联正文；
- 管理台「空间分配」与工作区详情两处展示的 used_bytes 不再为 0。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentDraft
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.workspaces.services.storage import (
    workspace_document_bytes,
    workspace_storage_bytes,
    workspace_table_bytes,
)

TABLES = "/api/v1/workspaces/{ws}/tables"
DOCS = "/api/v1/workspaces/{ws}/documents"


def _create_workspace(client: TestClient, auth: dict[str, str], name: str = "storage-ws") -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_table(client: TestClient, auth: dict[str, str], ws_id: int, *, name: str = "存储表") -> int:
    r = client.post(TABLES.format(ws=ws_id), json={"name": name, "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    r = client.post(
        f"{TABLES.format(ws=ws_id)}/{tid}/fields",
        json={"name": "名称", "field_type": "text", "order": 0},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    return tid


def _add_rows(client: TestClient, auth: dict[str, str], ws_id: int, tid: int, values: list[str]) -> None:
    for value in values:
        r = client.post(
            f"{TABLES.format(ws=ws_id)}/{tid}/records",
            json={"values": {"名称": value}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text


@pytest.fixture
def superuser_headers(client: TestClient, auth_headers: dict[str, str], db) -> dict[str, str]:
    """把已登录的 testuser 提升为 superuser（token 每请求查库，即时生效）."""
    user = db.query(User).filter(User.username == "testuser").one()
    user.is_superuser = True
    db.commit()
    return auth_headers


class TestEmptyWorkspace:
    def test_no_data_reports_zero(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "empty-ws")
        assert workspace_table_bytes(db, ws_id) == 0
        assert workspace_document_bytes(db, ws_id) == 0
        assert workspace_storage_bytes(db, ws_id) == 0


class TestTableRecordsCounted:
    def test_rows_add_to_usage(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "table-ws")
        tid = _create_table(client, auth_headers, ws_id)

        assert workspace_table_bytes(db, ws_id) == 0, "空表不应产生占用"

        values = ["第一行", "第二行数据", "third"]
        _add_rows(client, auth_headers, ws_id, tid, values)

        used = workspace_table_bytes(db, ws_id)
        assert used > 0
        # 逐行单元格字节数之和必然不小于业务值本身的字节数
        assert used >= sum(len(v.encode("utf-8")) for v in values)

    def test_storage_total_includes_table_bytes(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "table-total-ws")
        tid = _create_table(client, auth_headers, ws_id)
        _add_rows(client, auth_headers, ws_id, tid, ["甲", "乙"])
        # 无附件、无外存文档时，总占用 = 表记录 + 文档内联正文
        assert workspace_storage_bytes(db, ws_id) == workspace_table_bytes(db, ws_id)


class TestDocumentContentCounted:
    def test_inline_content_counted_exactly(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "doc-ws")
        content = "# 标题\n\n这是内联正文。"
        r = client.post(DOCS.format(ws=ws_id), json={"title": "内联文档", "content": content}, headers=auth_headers)
        assert r.status_code == 201, r.text

        assert workspace_document_bytes(db, ws_id) == len(content.encode("utf-8"))
        assert workspace_storage_bytes(db, ws_id) >= len(content.encode("utf-8"))

    def test_draft_content_counted(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "draft-ws")
        r = client.post(DOCS.format(ws=ws_id), json={"title": "草稿文档", "content": "正文"}, headers=auth_headers)
        assert r.status_code == 201, r.text
        doc_id = int(r.json()["id"])
        owner = db.query(User).filter(User.username == "testuser").one()

        draft_content = "尚未提交的个人草稿内容"
        db.add(
            DocumentDraft(
                document_id=doc_id,
                user_id=owner.id,
                content=draft_content,
                content_size=len(draft_content.encode("utf-8")),
                content_hash="hash",
                base_version_number=1,
            )
        )
        db.commit()

        assert workspace_document_bytes(db, ws_id) >= len(draft_content.encode("utf-8"))

    def test_external_content_not_double_counted(
        self, client: TestClient, auth_headers: dict[str, str], db, monkeypatch, tmp_path
    ):
        docs_dir = tmp_path / "docs"
        monkeypatch.setattr(content_service, "_DOCS_DIR", docs_dir)

        ws_id = _create_workspace(client, auth_headers, "ext-ws")
        big = "A" * (content_service.EXTERNAL_MIN_SIZE + 4096)
        r = client.post(DOCS.format(ws=ws_id), json={"title": "外存文档", "content": big}, headers=auth_headers)
        assert r.status_code == 201, r.text
        doc_id = int(r.json()["id"])

        external_file = docs_dir / str(doc_id) / "v1.md.gz"
        assert external_file.is_file()
        file_size = external_file.stat().st_size

        # 外存版本正文内联字段为空 → 文档内联统计为 0（不重复计数）
        assert workspace_document_bytes(db, ws_id) == 0
        # 文件实际大小计入总占用
        assert workspace_storage_bytes(db, ws_id) >= file_size
        assert workspace_storage_bytes(db, ws_id) > 0


class TestStorageSurfaces:
    def test_admin_storage_overview_reports_usage(self, client: TestClient, superuser_headers: dict[str, str], db):
        ws_id = _create_workspace(client, superuser_headers, "admin-usage-ws")
        tid = _create_table(client, superuser_headers, ws_id)
        _add_rows(client, superuser_headers, ws_id, tid, ["甲", "乙"])
        client.post(
            DOCS.format(ws=ws_id),
            json={"title": "文档", "content": "文档正文内容"},
            headers=superuser_headers,
        )

        # 管理台列表只读用量快照（ADR 0024）：先让后台刷新跑一轮再取
        from cndb.plugins.workspaces.services.storage_snapshot import refresh_all

        refresh_all(db)

        r = client.get("/api/v1/admin/workspaces/storage", headers=superuser_headers)
        assert r.status_code == 200, r.text
        item = next(it for it in r.json()["items"] if it["workspace_id"] == ws_id)
        assert item["used_bytes"] > 0
        assert item["computed_at"], "快照应带计算时间，供页面展示新鲜度"
        assert item["is_stale"] is False

    def test_workspace_detail_reports_usage(self, client: TestClient, auth_headers: dict[str, str], db):
        ws_id = _create_workspace(client, auth_headers, "detail-usage-ws")
        tid = _create_table(client, auth_headers, ws_id)
        _add_rows(client, auth_headers, ws_id, tid, ["甲"])

        r = client.get(f"/api/v1/workspaces/{ws_id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["storage_bytes"] > 0
