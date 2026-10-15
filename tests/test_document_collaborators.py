"""文档协作者（文档级权限）测试 —— 让草稿"只对指定同事开放".

可见性策略把草稿限制为「创建者 + 工作区所有者」可见（避免互相偷看未发布内容），
但协作需要显式中间档：把草稿授权给指定同事（viewer 只读 / editor 可直编）。
本文件锁定这套授权的完整语义：

- 授权后可见（列表 / 目录树 / 详情 / 正文），撤销后立即收回；
- viewer 协作者的写入仍走工作区策略（修改申请 202），不会因授权而绕过流程；
- editor 协作者可直接编辑**未发布**文档；已发布文档不因授权而绕过发布/审核策略；
- 只有创建者 / 工作区 OWNER / 超管能授权；被授权者必须是工作区成员；不能给自己或创建者授权；
- 协作者可参与段落锁协作（跨用户并发编辑的前提）；
- 彻底删除时授权行一并清理（无孤儿）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DocumentPermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"


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


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "collab_owner")
        self.ws = Workspace(name="CollabWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.viewer = _add_member(db, self.ws, "collab_viewer", WorkspaceRole.VIEWER)
        self.editor = _add_member(db, self.ws, "collab_editor", WorkspaceRole.EDITOR)
        self.outsider = _make_user(db, "collab_outsider")
        db.commit()


def _env(db: Session) -> Env:
    return Env(db)


def _create_draft(client: TestClient, env: Env, *, status: str = "draft") -> dict:
    auth = _login(client, env.owner.username)
    r = client.post(
        DOCS.format(ws=env.ws.id),
        json={"title": "协作者用例草稿", "content": "# v1\n", "status": status},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _grant(client: TestClient, env: Env, doc: dict, user: User, role: str) -> dict:
    auth = _login(client, env.owner.username)
    r = client.post(
        f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/permissions",
        json={"user_id": user.id, "role": role},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestGrantVisibility:
    def test_viewer_grant_makes_draft_visible_and_revocable(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        auth_viewer = _login(client, env.viewer.username)
        url = f"{DOCS.format(ws=env.ws.id)}/{doc['id']}"

        # 授权前：不可见
        assert client.get(url, headers=auth_viewer).status_code == 404
        titles = [i["title"] for i in client.get(DOCS.format(ws=env.ws.id), headers=auth_viewer).json()["items"]]
        assert "协作者用例草稿" not in titles

        granted = _grant(client, env, doc, env.viewer, "viewer")
        assert granted["role"] == "viewer"

        # 授权后：列表 / 目录树 / 详情 / 正文均可见
        assert client.get(url, headers=auth_viewer).status_code == 200
        assert client.get(f"{url}/content", headers=auth_viewer).status_code == 200
        titles = [
            i["title"] for i in client.get(f"{DOCS.format(ws=env.ws.id)}/tree", headers=auth_viewer).json()["items"]
        ]
        assert "协作者用例草稿" in titles

        # 名单可见（协作者之间互相知悉）
        listed = client.get(f"{url}/permissions", headers=auth_viewer).json()["items"]
        assert [i["user_id"] for i in listed] == [env.viewer.id]

        # 撤销后立即收回
        r = client.delete(f"{url}/permissions/{env.viewer.id}", headers=_login(client, env.owner.username))
        assert r.status_code == 204, r.text
        assert client.get(url, headers=auth_viewer).status_code == 404

    def test_editor_grant_can_write_draft_directly(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        _grant(client, env, doc, env.editor, "editor")

        auth = _login(client, env.editor.username)
        r = client.put(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/content",
            json={"content": "# 协作者直编\n"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["version_number"] == 2

    def test_viewer_grant_still_goes_through_change_request(self, client, db):
        """viewer 协作者能读，但写入仍走工作区策略（不因授权绕过流程）."""
        env = _env(db)
        doc = _create_draft(client, env)
        _grant(client, env, doc, env.viewer, "viewer")

        auth = _login(client, env.viewer.username)
        r = client.put(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/content",
            json={"content": "# viewer 的修改\n"},
            headers=auth,
        )
        assert r.status_code == 202, r.text
        assert r.json()["change_request"]["status"] == "open"

    def test_editor_grant_does_not_bypass_policy_on_published_doc(self, client, db):
        """已发布文档不因文档级授权而绕过 allow_edit / 修改申请策略."""
        env = _env(db)
        doc = _create_draft(client, env, status="published")
        env.ws.allow_edit = False
        db.commit()
        _grant(client, env, doc, env.viewer, "editor")

        auth = _login(client, env.viewer.username)
        r = client.put(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/content",
            json={"content": "# 绕过尝试\n"},
            headers=auth,
        )
        assert r.status_code == 202, r.text


class TestGrantGuards:
    def test_only_creator_or_owner_can_grant(self, client, db):
        env = _env(db)
        auth_editor = _login(client, env.editor.username)

        # 草稿：非创建者/所有者连"看得到"都做不到 → 404（不泄露存在性，优先于 403）
        draft = _create_draft(client, env)
        r = client.post(
            f"{DOCS.format(ws=env.ws.id)}/{draft['id']}/permissions",
            json={"user_id": env.viewer.id, "role": "viewer"},
            headers=auth_editor,
        )
        assert r.status_code == 404, r.text

        # 已发布：可见，但没有管理协作者名单的权限 → 403
        published = _create_draft(client, env, status="published")
        r = client.post(
            f"{DOCS.format(ws=env.ws.id)}/{published['id']}/permissions",
            json={"user_id": env.viewer.id, "role": "viewer"},
            headers=auth_editor,
        )
        assert r.status_code == 403, r.text

    def test_cannot_grant_to_non_member(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/permissions",
            json={"user_id": env.outsider.id, "role": "viewer"},
            headers=auth,
        )
        assert r.status_code == 400, r.text

    def test_cannot_grant_to_self_or_creator(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        auth = _login(client, env.owner.username)
        for target in (env.owner.id,):
            r = client.post(
                f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/permissions",
                json={"user_id": target, "role": "editor"},
                headers=auth,
            )
            assert r.status_code == 400, r.text

    def test_invalid_role_rejected(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/permissions",
            json={"user_id": env.viewer.id, "role": "owner"},
            headers=auth,
        )
        assert r.status_code == 422, r.text


class TestCollaborationAndCleanup:
    def test_collaborator_can_take_paragraph_lock(self, client, db):
        """跨用户协作编辑的前提：协作者能看见文档并参与段落锁."""
        env = _env(db)
        doc = _create_draft(client, env)
        _grant(client, env, doc, env.viewer, "editor")

        auth = _login(client, env.viewer.username)
        r = client.post(
            f"{DOCS.format(ws=env.ws.id)}/{doc['id']}/paragraph-locks",
            json={"keys": ["p1"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["locks"][0]["key"] == "p1"

    def test_purge_removes_permission_rows(self, client, db):
        env = _env(db)
        doc = _create_draft(client, env)
        _grant(client, env, doc, env.viewer, "viewer")
        auth = _login(client, env.owner.username)
        base = f"{DOCS.format(ws=env.ws.id)}/{doc['id']}"

        assert client.delete(base, headers=auth).status_code in (200, 204)
        assert client.delete(f"{base}/purge", headers=auth).status_code == 200
        assert db.query(DocumentPermission).filter(DocumentPermission.document_id == doc["id"]).count() == 0
