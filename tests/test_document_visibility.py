"""可见性与权限收口测试 —— 草稿/未发布内容不得在成员之间互相可见.

覆盖目标（对应"数据表 + 文档 + 问题清单"三处的权限/可见性/协作模式优化）：

文档
- 他人草稿：列表 / 目录树 / 全文搜索 / 详情 / 正文 全部不可见（404 或不在结果里）
- 自己草稿可见；工作区 OWNER 可见他人草稿；已发布文档对全体成员可见；归档对他人不可见
- 目录树保留可见节点的祖先文件夹（不断链）
- 回收站不暴露他人草稿的删除记录；标签计数只统计可见文档
- 分享：草稿不可创建分享；已发布可分享；取消发布后公开链接立即失效
- 文档问题清单：不可见文档上的问题不出现在列表、详情 404、不能在他人草稿上提问题

数据表（列表）
- 表列表只展示当前用户**可读**的表（无权限表的名称/元数据不泄露）
- 无 READ 权限时，表的问题清单同样 404
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
TABLES = "/api/v1/workspaces/{ws}/tables"
DI = "/api/v1/workspaces/{ws}/document-issues"
SHARE_API = "/api/v1/documents/share"

DRAFT_TITLE = "他人的草稿-可见性用例"
PUB_TITLE = "已发布文档-可见性用例"
SECRET = "uniquetoken-visibility-9f3a"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _add_member(db: Session, ws: Workspace, username: str, role: WorkspaceRole) -> User:
    u = _make_user(db, username)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    return u


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "vis_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="VisWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws) -> User:
    return _add_member(db, ws, "vis_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "vis_viewer", WorkspaceRole.VIEWER)


def _create_doc(client, ws: Workspace, auth: dict[str, str], *, title: str, status: str, content: str = "") -> dict:
    r = client.post(
        DOCS.format(ws=ws.id),
        json={"title": title, "content": content or f"# {title}\n", "status": status},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestDocumentVisibility:
    """草稿/归档仅创建者与工作区所有者可见；已发布对全体成员可见."""

    @pytest.fixture
    def draft(self, client, ws, owner) -> dict:
        return _create_doc(client, ws, _login(client, owner.username), title=DRAFT_TITLE, status="draft")

    @pytest.fixture
    def published(self, client, ws, owner) -> dict:
        return _create_doc(
            client, ws, _login(client, owner.username), title=PUB_TITLE, status="published", content=SECRET
        )

    def test_other_member_list_excludes_draft(self, client, ws, owner, viewer, draft):
        auth = _login(client, viewer.username)
        items = client.get(DOCS.format(ws=ws.id), headers=auth).json()["items"]
        assert all(i["id"] != draft["id"] for i in items)

    def test_creator_list_contains_own_draft(self, client, ws, owner, draft):
        auth = _login(client, owner.username)
        items = client.get(DOCS.format(ws=ws.id), headers=auth).json()["items"]
        assert any(i["id"] == draft["id"] for i in items)

    def test_owner_sees_others_draft(self, client, ws, owner, editor, db):
        """工作区 OWNER 需要能审阅/清理他人草稿."""
        other = _create_doc(client, ws, _login(client, editor.username), title="editor 的草稿", status="draft")
        items = client.get(DOCS.format(ws=ws.id), headers=_login(client, owner.username)).json()["items"]
        assert any(i["id"] == other["id"] for i in items)

    def test_other_member_tree_excludes_draft(self, client, ws, owner, viewer, draft):
        auth = _login(client, viewer.username)
        titles = [i["title"] for i in client.get(f"{DOCS.format(ws=ws.id)}/tree", headers=auth).json()["items"]]
        assert DRAFT_TITLE not in titles

    def test_tree_keeps_ancestor_folder_of_visible_published_doc(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        # 文件夹走 is_folder（草稿文件夹本身对普通成员不可见，但作为可见文档的祖先必须补链）
        r_folder = client.post(
            DOCS.format(ws=ws.id),
            json={"title": "草稿文件夹", "status": "draft", "is_folder": True},
            headers=auth_owner,
        )
        assert r_folder.status_code == 201, r_folder.text
        folder = r_folder.json()
        # 文件夹下的已发布文档：普通成员应能看到该文档，并看到其路径上的文件夹
        r = client.post(
            DOCS.format(ws=ws.id),
            json={"title": "夹内已发布", "content": "# 夹内\n", "status": "published", "parent_id": folder["id"]},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text

        items = client.get(f"{DOCS.format(ws=ws.id)}/tree", headers=_login(client, viewer.username)).json()["items"]
        by_id = {i["id"]: i for i in items}
        assert r.json()["id"] in by_id
        # 祖先文件夹必须在结果里，否则前端树会出现孤儿节点
        assert folder["id"] in by_id

    def test_other_member_detail_and_content_404(self, client, ws, owner, viewer, draft):
        auth = _login(client, viewer.username)
        assert client.get(f"{DOCS.format(ws=ws.id)}/{draft['id']}", headers=auth).status_code == 404
        assert client.get(f"{DOCS.format(ws=ws.id)}/{draft['id']}/content", headers=auth).status_code == 404
        assert client.get(f"{DOCS.format(ws=ws.id)}/{draft['id']}/versions", headers=auth).status_code == 404

    def test_published_visible_to_every_member(self, client, ws, owner, viewer, published):
        auth = _login(client, viewer.username)
        assert client.get(f"{DOCS.format(ws=ws.id)}/{published['id']}", headers=auth).status_code == 200
        detail = client.get(f"{DOCS.format(ws=ws.id)}/{published['id']}/content", headers=auth)
        assert detail.status_code == 200
        assert SECRET in detail.json()["content"]

    def test_archived_hidden_from_others(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        archived = _create_doc(client, ws, auth_owner, title="已归档文档", status="archived")
        assert (
            client.get(f"{DOCS.format(ws=ws.id)}/{archived['id']}", headers=_login(client, viewer.username)).status_code
            == 404
        )
        # 创建者自己仍可见（可继续整理）
        assert client.get(f"{DOCS.format(ws=ws.id)}/{archived['id']}", headers=auth_owner).status_code == 200

    def test_search_excludes_others_draft(self, client, ws, owner, viewer, draft, published):
        auth = _login(client, viewer.username)
        r = client.get(f"{DOCS.format(ws=ws.id)}/search", params={"q": DRAFT_TITLE}, headers=auth)
        assert r.status_code == 200, r.text
        assert all(i["id"] != draft["id"] for i in r.json()["items"])

        r2 = client.get(f"{DOCS.format(ws=ws.id)}/search", params={"q": SECRET}, headers=auth)
        assert r2.status_code == 200, r2.text
        assert any(i["id"] == published["id"] for i in r2.json()["items"])

    def test_trash_hides_others_draft(self, client, ws, owner, viewer, draft):
        auth_owner = _login(client, owner.username)
        assert client.delete(f"{DOCS.format(ws=ws.id)}/{draft['id']}", headers=auth_owner).status_code in (200, 204)

        other = client.get(f"{DOCS.format(ws=ws.id)}/trash", headers=_login(client, viewer.username)).json()
        assert all(i["id"] != draft["id"] for i in other["items"])
        mine = client.get(f"{DOCS.format(ws=ws.id)}/trash", headers=auth_owner).json()
        assert any(i["id"] == draft["id"] for i in mine["items"])

    def test_tag_count_only_counts_visible_docs(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        tag = client.post(
            f"/api/v1/workspaces/{ws.id}/document-tags", json={"name": "vis-tag"}, headers=auth_owner
        ).json()
        doc = _create_doc(client, ws, auth_owner, title="带标签的草稿", status="draft")
        client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=auth_owner)

        mine = client.get(f"{DOCS.format(ws=ws.id)}/tags", headers=auth_owner).json()["items"]
        assert any(t["id"] == tag["id"] and t["doc_count"] == 1 for t in mine)

        other = client.get(f"{DOCS.format(ws=ws.id)}/tags", headers=_login(client, viewer.username)).json()["items"]
        assert all(t["id"] != tag["id"] for t in other)


class TestShareVisibility:
    """未发布内容不得通过分享链接外泄；取消发布后既有链接立即失效."""

    def test_draft_cannot_be_shared(self, client, ws, owner):
        auth = _login(client, owner.username)
        draft = _create_doc(client, ws, auth, title="待分享草稿", status="draft")
        r = client.post(f"{DOCS.format(ws=ws.id)}/{draft['id']}/share", json={"permission": "viewer"}, headers=auth)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "conflict"

    def test_published_share_revoked_after_unpublish(self, client, ws, owner):
        auth = _login(client, owner.username)
        doc = _create_doc(client, ws, auth, title="可分享文档", status="published", content=SECRET)
        share = client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/share", json={"permission": "viewer"}, headers=auth)
        assert share.status_code == 201, share.text
        token = share.json()["token"]
        assert client.get(f"{SHARE_API}/{token}").status_code == 200

        # 取消发布（回到草稿）→ 公开链接立即失效
        r = client.patch(f"{DOCS.format(ws=ws.id)}/{doc['id']}", json={"status": "draft"}, headers=auth)
        assert r.status_code == 200, r.text
        assert client.get(f"{SHARE_API}/{token}").status_code == 404


class TestDocumentIssueVisibility:
    """文档问题清单同样受文档可见性约束（问题标题/描述可能引用未发布内容）."""

    @pytest.fixture
    def secret_issue(self, client, ws, owner, viewer) -> dict:
        auth_owner = _login(client, owner.username)
        secret = _create_doc(client, ws, auth_owner, title="草稿-有问题", status="draft")
        r = client.post(
            DI.format(ws=ws.id),
            json={"document_id": secret["id"], "title": "草稿上的问题", "category": "question"},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text
        return {"doc": secret, "issue": r.json()}

    def test_issue_list_excludes_invisible_document(self, client, ws, owner, viewer, secret_issue):
        items = client.get(DI.format(ws=ws.id), headers=_login(client, viewer.username)).json()["items"]
        assert all(i["id"] != secret_issue["issue"]["id"] for i in items)

    def test_issue_detail_404_when_document_invisible(self, client, ws, owner, viewer, secret_issue):
        auth = _login(client, viewer.username)
        r = client.get(f"{DI.format(ws=ws.id)}/{secret_issue['issue']['id']}", headers=auth)
        assert r.status_code == 404

    def test_cannot_create_issue_on_others_draft(self, client, ws, owner, viewer, secret_issue):
        r = client.post(
            DI.format(ws=ws.id),
            json={"document_id": secret_issue["doc"]["id"], "title": "越权提问", "category": "question"},
            headers=_login(client, viewer.username),
        )
        assert r.status_code == 404

    def test_list_by_document_id_404_for_invisible(self, client, ws, owner, viewer, secret_issue):
        auth = _login(client, viewer.username)
        r = client.get(DI.format(ws=ws.id), params={"document_id": secret_issue["doc"]["id"]}, headers=auth)
        assert r.status_code == 404


class TestTableListVisibility:
    """数据表列表按 READ 权限过滤；问题清单要求表的 READ 权限."""

    def _make_table(self, client, ws, auth, name: str) -> dict:
        r = client.post(TABLES.format(ws=ws.id), json={"name": name, "description": ""}, headers=auth)
        assert r.status_code == 201, r.text
        return r.json()

    def test_list_hides_table_without_read_permission(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        self._make_table(client, ws, auth_owner, "人人可读")
        restricted = self._make_table(client, ws, auth_owner, "仅所有者可读")

        # read_role 提升到 OWNER：viewer 不再具备 READ
        r = client.put(
            f"{TABLES.format(ws=ws.id)}/{restricted['id']}/permissions",
            json={"read_role": "OWNER"},
            headers=auth_owner,
        )
        assert r.status_code in (200, 201), r.text

        auth_viewer = _login(client, viewer.username)
        names = [t["name"] for t in client.get(TABLES.format(ws=ws.id), headers=auth_viewer).json()]
        assert "人人可读" in names
        assert "仅所有者可读" not in names

        # 权限判定与详情接口一致（详情本就 404/403，此处确认不可读）
        detail = client.get(f"{TABLES.format(ws=ws.id)}/{restricted['id']}", headers=auth_viewer)
        assert detail.status_code in (403, 404)
        # 所有者仍能看到
        owner_names = [t["name"] for t in client.get(TABLES.format(ws=ws.id), headers=auth_owner).json()]
        assert "仅所有者可读" in owner_names

    def test_issue_list_requires_table_read(self, client, ws, owner, viewer):
        auth_owner = _login(client, owner.username)
        restricted = self._make_table(client, ws, auth_owner, "问题清单受限表")
        client.put(
            f"{TABLES.format(ws=ws.id)}/{restricted['id']}/permissions",
            json={"read_role": "OWNER"},
            headers=auth_owner,
        )
        # 所有者提交一个问题
        r = client.post(
            f"{TABLES.format(ws=ws.id)}/{restricted['id']}/issues",
            json={"title": "受限表上的问题", "category": "question"},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text

        auth_viewer = _login(client, viewer.username)
        assert client.get(f"{TABLES.format(ws=ws.id)}/{restricted['id']}/issues", headers=auth_viewer).status_code in (
            403,
            404,
        )
