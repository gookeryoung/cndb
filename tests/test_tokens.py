"""API 令牌测试：认证器行为与令牌管理端点."""

from __future__ import annotations

from typing import Any

from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.tokens.models import ApiToken, generate_api_token, hash_token
from cndb.workspaces.models import Workspace, WorkspaceMember


class TestTokenAuthentication:
    """认证器：请求头解析、命中与拒绝路径."""

    def test_token_authenticates(self, api: APIClient, user: User) -> None:
        """有效令牌以属主身份通过认证."""
        _, token = ApiToken.issue(user, "脚本")
        api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        response = api.get("/api/auth/me/")
        assert response.status_code == 200
        assert response.data["username"] == "alice"

    def test_invalid_token_rejected(self, api: APIClient, db: object) -> None:
        """未知令牌摘要返回 401."""
        api.credentials(HTTP_AUTHORIZATION=f"Token {generate_api_token()}")
        assert api.get("/api/auth/me/").status_code == 401

    def test_empty_token_rejected(self, api: APIClient) -> None:
        """Token 关键字后为空返回 401."""
        api.credentials(HTTP_AUTHORIZATION="Token ")
        assert api.get("/api/auth/me/").status_code == 401

    def test_other_keyword_falls_through(self, api: APIClient) -> None:
        """非 Token 关键字不处理，交由后续认证器（无凭证被拒）."""
        api.credentials(HTTP_AUTHORIZATION="Bearer whatever")
        response = api.get("/api/auth/me/")
        assert response.status_code in (401, 403)

    def test_last_used_updated(self, api: APIClient, user: User) -> None:
        """认证成功后刷新最近使用时间."""
        obj, token = ApiToken.issue(user, "脚本")
        assert obj.last_used_on is None
        api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        assert api.get("/api/auth/me/").status_code == 200
        obj.refresh_from_db()
        assert obj.last_used_on is not None

    def test_token_carries_role(self, api: APIClient, viewer: User, workspace: Workspace) -> None:
        """令牌请求沿用属主角色：viewer 可读行、写行 403（策略链照常裁决）."""
        owner = User.objects.get(username="alice")
        _, token = ApiToken.issue(viewer, "只读脚本")
        api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        base = f"/api/workspaces/{workspace.pk}/tables/"
        # owner 建表（建表接口要求内联字段定义），viewer 通过令牌访问
        owner_api = APIClient()
        owner_api.force_authenticate(user=owner)
        table = owner_api.post(
            base,
            {"name": "令牌表", "fields": [{"name": "标题", "field_type": "text"}]},
            format="json",
        ).data
        owner_api.post(f"{base}{table['id']}/records/", {"标题": "第一条"}, format="json")
        assert api.get(f"{base}{table['id']}/records/").status_code == 200
        assert api.post(f"{base}{table['id']}/records/", {"标题": "x"}, format="json").status_code == 403


class TestTokenAPI:
    """令牌管理端点：签发、列表、撤销与隔离."""

    def test_create_returns_token_once(self, auth_client: APIClient, user: User) -> None:
        """POST 签发返回 201 与明文，摘要落库、明文不可再取."""
        response = auth_client.post("/api/tokens/", {"name": "CI 集成"}, format="json")
        assert response.status_code == 201
        token = response.data["token"]
        assert token.startswith("cndb_")
        assert ApiToken.objects.filter(digest=hash_token(token), user=user).exists()
        detail = auth_client.get(f"/api/tokens/{response.data['id']}/")
        detail_data = detail.data
        assert isinstance(detail_data, dict)
        assert "token" not in detail_data
        assert "digest" not in detail_data

    def test_create_requires_name(self, auth_client: APIClient) -> None:
        """缺少名称返回 400."""
        response = auth_client.post("/api/tokens/", {}, format="json")
        assert response.status_code == 400

    def test_list_hides_secret(self, auth_client: APIClient, user: User) -> None:
        """列表只含识别字段，不含明文与摘要."""
        ApiToken.issue(user, "列表项")
        response = auth_client.get("/api/tokens/")
        assert response.status_code == 200
        results: list[dict[str, Any]] = response.data["results"]
        assert len(results) == 1
        assert results[0]["name"] == "列表项"
        assert results[0]["prefix"].startswith("cndb_")
        assert "token" not in results[0]
        assert "digest" not in results[0]

    def test_delete_revokes(self, auth_client: APIClient, user: User) -> None:
        """DELETE 撤销后令牌即刻失效（401）."""
        _, token = ApiToken.issue(user, "待撤销")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        assert api.get("/api/auth/me/").status_code == 200
        token_id = ApiToken.objects.get(user=user).pk
        assert auth_client.delete(f"/api/tokens/{token_id}/").status_code == 204
        assert api.get("/api/auth/me/").status_code == 401

    def test_only_own_tokens_visible(self, auth_client: APIClient, viewer: User, user: User) -> None:
        """他人令牌不可见：列表为空、详情 404、不可撤销."""
        obj, _token = ApiToken.issue(viewer, "别人的")
        response = auth_client.get("/api/tokens/")
        assert response.data["count"] == 0
        assert auth_client.get(f"/api/tokens/{obj.pk}/").status_code == 404
        assert auth_client.delete(f"/api/tokens/{obj.pk}/").status_code == 404
        assert ApiToken.objects.filter(pk=obj.pk, user=user).count() == 0
        assert ApiToken.objects.filter(pk=obj.pk).exists()


class TestWorkspaceMemberTokens:
    """令牌与工作区成员体系协作：撤销令牌不影响其他成员."""

    def test_issue_for_member_keeps_others(self, auth_client: APIClient, workspace: Workspace) -> None:
        """给成员签发令牌不影响工作区成员关系."""
        editor = User.objects.create_user(username="editor-t", password="Str0ng-Pass-42")
        WorkspaceMember.objects.create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)
        obj, token = ApiToken.issue(editor, "编辑脚本")
        assert token.startswith("cndb_")
        assert obj.user == editor
        assert workspace.members.filter(user=editor).exists()
