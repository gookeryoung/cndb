"""文档读取面的整体可见性回归 —— 他人草稿在**所有**读取入口都不可达.

单点测试容易被"补了一个入口、漏了另一个入口"绕过（历史上修改申请就是这样漏掉的）。
本文件以**参数化清单**覆盖文档读取面的每个入口，并对创建者做正向对照，
防止出现"全 404 也算过"的假绿：

- 元数据 / 正文 / 版本列表 / 单版本 / 差异 / 导出 / 反链 / 出链 /
  分享链接列表 / 问题清单 / 修改申请；
- 集合类入口（列表 / 目录树 / 搜索）必须**不包含**该草稿；
- 两类角色都要被挡住：普通成员（viewer）与工作区编辑者（editor，非创建者）；
- 创建者对这些入口必须全部可用（正向对照）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
ISSUES = "/api/v1/workspaces/{ws}/document-issues"
CRS = "/api/v1/workspaces/{ws}/document-change-requests"

# (名称, 方法, 相对路径, 查询参数, JSON body)
READ_ENDPOINTS: list[tuple[str, str, str, dict | None, dict | None]] = [
    ("详情", "GET", "/{id}", None, None),
    ("正文", "GET", "/{id}/content", None, None),
    ("版本列表", "GET", "/{id}/versions", None, None),
    ("单版本", "GET", "/{id}/versions/1", None, None),
    ("差异", "GET", "/{id}/diff", {"base": 1, "head": 1}, None),
    ("导出 Markdown", "GET", "/{id}/export", {"format": "md"}, None),
    ("反链", "GET", "/{id}/backlinks", None, None),
    ("出链", "GET", "/{id}/links", None, None),
    ("分享链接列表", "GET", "/{id}/share", None, None),
]


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "surf_owner")
        self.ws = Workspace(name="SurfaceWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "surf_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "surf_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _setup(client: TestClient, db: Session) -> tuple[Env, dict, dict[str, str], dict[str, str], dict[str, str]]:
    env = Env(db)
    r = client.post(
        DOCS.format(ws=env.ws.id),
        json={"title": "地表敏感草稿唯一标题", "content": "# 机密草稿正文\n", "status": "draft"},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return (
        env,
        r.json(),
        _login(client, env.owner.username),
        _login(client, env.editor.username),
        _login(client, env.viewer.username),
    )


class TestDraftReadSurfaceLocked:
    def test_every_read_endpoint_404_for_non_creator_roles(self, client, db):
        env, doc, _auth_owner, auth_editor, auth_viewer = _setup(client, db)
        base = DOCS.format(ws=env.ws.id)

        for name, method, path, params, body in READ_ENDPOINTS:
            url = base + path.format(id=doc["id"])
            for role, auth in (("viewer", auth_viewer), ("editor", auth_editor)):
                resp = client.request(method, url, params=params, json=body, headers=auth)
                assert resp.status_code == 404, f"{name} 对 {role} 应 404，实际 {resp.status_code}: {resp.text[:120]}"

    def test_creator_control_endpoints_are_available(self, client, db):
        """正向对照：同一个清单对创建者必须可用（否则上面的 404 断言没有意义）."""
        env, doc, auth_owner, _auth_editor, _auth_viewer = _setup(client, db)
        base = DOCS.format(ws=env.ws.id)

        for name, method, path, params, body in READ_ENDPOINTS:
            url = base + path.format(id=doc["id"])
            resp = client.request(method, url, params=params, json=body, headers=auth_owner)
            assert resp.status_code == 200, f"{name} 对创建者应 200，实际 {resp.status_code}: {resp.text[:120]}"

    def test_collection_endpoints_exclude_foreign_draft(self, client, db):
        env, doc, _auth_owner, auth_editor, auth_viewer = _setup(client, db)
        base = DOCS.format(ws=env.ws.id)

        for role, auth in (("viewer", auth_viewer), ("editor", auth_editor)):
            listed = client.get(base, headers=auth).json()["items"]
            assert doc["id"] not in [i["id"] for i in listed], f"列表泄露给 {role}"

            tree = client.get(f"{base}/tree", headers=auth).json()["items"]
            assert doc["id"] not in [i["id"] for i in tree], f"目录树泄露给 {role}"

            found = client.get(f"{base}/search", params={"q": "地表敏感草稿"}, headers=auth).json()
            assert doc["id"] not in [i["id"] for i in found.get("items", [])], f"搜索泄露给 {role}"

            # 标题/正文不得出现在任何集合响应里（全文兜底）
            for endpoint in (base, f"{base}/tree", f"{base}/search?q=地表敏感"):
                body = client.get(endpoint, headers=auth).text
                assert "机密草稿正文" not in body, f"正文泄露给 {role} via {endpoint}"

    def test_related_resources_locked(self, client, db):
        """挂在草稿下的问题清单 / 修改申请同样不可达（历史上修改申请漏过）."""
        env, doc, auth_owner, auth_editor, auth_viewer = _setup(client, db)

        # 创建者先建一条问题与一条修改申请
        issue = client.post(
            ISSUES.format(ws=env.ws.id),
            json={"document_id": doc["id"], "title": "草稿问题", "category": "question"},
            headers=auth_owner,
        )
        assert issue.status_code == 201, issue.text
        issue_id = issue.json()["id"]
        cr = client.post(
            CRS.format(ws=env.ws.id),
            json={"document_id": doc["id"], "content": "# 待审正文\n"},
            headers=auth_owner,
        )
        assert cr.status_code == 201, cr.text
        cr_id = cr.json()["id"]

        for role, auth in (("viewer", auth_viewer), ("editor", auth_editor)):
            assert client.get(f"{ISSUES.format(ws=env.ws.id)}/{issue_id}", headers=auth).status_code == 404, (
                f"问题详情泄露给 {role}"
            )
            assert (
                client.get(
                    f"{ISSUES.format(ws=env.ws.id)}", params={"document_id": doc["id"]}, headers=auth
                ).status_code
                == 404
            ), f"问题列表可按 document_id 窥探（{role}）"
            assert client.get(f"{CRS.format(ws=env.ws.id)}/{cr_id}", headers=auth).status_code == 404, (
                f"修改申请详情泄露给 {role}"
            )
            listed = client.get(
                f"{CRS.format(ws=env.ws.id)}", params={"document_id": doc["id"], "scope": "all"}, headers=auth
            )
            assert listed.status_code == 200 and listed.json()["total"] == 0, f"修改申请列表泄露给 {role}"
            # 也不能对不可见草稿发起申请
            assert (
                client.post(
                    CRS.format(ws=env.ws.id),
                    json={"document_id": doc["id"], "content": "# 窥探\n"},
                    headers=auth,
                ).status_code
                == 404
            ), f"可对不可见草稿发起修改申请（{role}）"
