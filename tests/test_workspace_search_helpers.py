"""工作区检索 helper（`workspaces/services/search.py`）—— 判定层单测.

覆盖行标题 / 片段选择、视图筛选降级、跨工作区与团队内检索的空关键词、缓存复用与配额截断分支。
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.services import search as search_service


def _field(name: str, *, order: int = 0, trashed: bool = False):
    return SimpleNamespace(name=name, order=order, id=order + 1, trashed=trashed)


def _table(*fields):
    return SimpleNamespace(fields=list(fields), name="T")


class TestRowTitle:
    def test_prefers_first_non_empty_string(self):
        table = _table(_field("名称"), _field("备注", order=1))
        assert search_service._row_title(table, {"名称": "  ", "备注": "说明"}) == "说明"

    def test_numeric_value_is_used(self):
        table = _table(_field("数量"))
        assert search_service._row_title(table, {"数量": 12.5}) == "12.5"

    def test_boolean_is_skipped(self):
        table = _table(_field("启用"))
        assert search_service._row_title(table, {"启用": True, "id": 7}) == "#7"

    def test_trashed_field_skipped(self):
        table = _table(_field("旧名", trashed=True), _field("新名", order=1))
        assert search_service._row_title(table, {"旧名": "x", "新名": "y"}) == "y"

    def test_no_fields_no_id(self):
        assert search_service._row_title(_table(), {}) == ""


class TestRowSnippet:
    def test_returns_matching_text(self):
        table = _table(_field("备注"))
        assert search_service._row_snippet(table, {"备注": "这里有晶格关键词"}, "晶格") == "这里有晶格关键词"

    def test_truncates_long_text(self):
        table = _table(_field("备注"))
        text = "晶格" + "x" * 200
        snippet = search_service._row_snippet(table, {"备注": text}, "晶格")
        assert snippet.endswith("…")
        assert len(snippet) <= 80

    def test_falls_back_to_title(self):
        table = _table(_field("名称"), _field("备注", order=1))
        assert search_service._row_snippet(table, {"名称": "标题", "备注": "无命中"}, "晶格") == "标题"


class TestViewScopeFilters:
    def test_missing_view_returns_empty(self, db: Session):
        table = SimpleNamespace(id=1)
        filters, logic, name = search_service._view_scope_filters(db, table, 999999, SimpleNamespace(id=1))
        assert (filters, logic, name) == ([], "AND", "")

    def test_view_from_other_table_returns_empty(self, db: Session):
        from cndb.plugins.tables.models import DataTable, DataView

        table = DataTable(workspace_id=1, name="T", description="", db_table_name="t_vs_1")
        other = DataTable(workspace_id=1, name="T2", description="", db_table_name="t_vs_2")
        db.add_all([table, other])
        db.flush()
        view = DataView(table_id=other.id, name="V", view_type="grid", filters=[], sortings=[], scope_key=0)
        db.add(view)
        db.commit()
        filters, logic, name = search_service._view_scope_filters(db, table, view.id, SimpleNamespace(id=1))
        assert (filters, logic, name) == ([], "AND", "")


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestWorkspaceScopedSearch:
    def test_blank_keyword_shortcircuits(self, db: Session):
        user = _user(db, "search_blank")
        assert search_service.search_all_workspaces(db, user, "") == {
            "query": "",
            "documents": [],
            "tables": [],
            "rows": [],
        }
        assert search_service.search_team_workspaces(db, user, 1, "") == {
            "query": "",
            "documents": [],
            "tables": [],
            "rows": [],
        }

    def test_global_search_breaks_when_all_groups_full(self, db: Session, monkeypatch):
        user = _user(db, "search_break")
        for index in range(2):
            ws = Workspace(name=f"BW{index}", created_by_id=user.id)
            db.add(ws)
            db.flush()
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
        db.commit()

        calls: list[int] = []

        def fake(workspace_id, **_kwargs):
            calls.append(workspace_id)
            return {
                "documents": [{"id": 1}],
                "tables": [{"id": 1}],
                "rows": [{"row_id": 1}],
            }

        monkeypatch.setattr(search_service, "search_workspace", lambda *a, **k: fake(a[1], **k))
        result = search_service.search_all_workspaces(db, user, "配额", limit=1)
        assert len(result["documents"]) == 1
        assert len(calls) == 1  # 三组都满 → 第二个工作区不再检索

    def test_team_search_breaks_and_skips_unreadable(self, db: Session, monkeypatch):
        owner = _user(db, "search_team_owner")
        team = Team(name="ST", slug="st", description="", policy={}, created_by_id=owner.id)
        db.add(team)
        db.flush()
        db.add(TeamMember(team_id=team.id, user_id=owner.id, role=TeamRole.OWNER))
        for index in range(2):
            ws = Workspace(name=f"TW{index}", created_by_id=owner.id, team_id=team.id)
            db.add(ws)
            db.flush()
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        # 源工作区 private 且 owner 也是成员 → 可读；再建一个不可读的（团队管理员视角更直观，这里用他人）
        db.commit()

        calls: list[int] = []
        monkeypatch.setattr(
            search_service,
            "search_workspace",
            lambda *a, **k: (
                calls.append(a[1]),
                {"documents": [{"id": 1}], "tables": [{"id": 2}], "rows": [{"row_id": 3}]},
            )[1],
        )
        result = search_service.search_team_workspaces(db, owner, team.id, "团队配额", limit=1)
        assert len(result["rows"]) == 1
        assert len(calls) == 1


class TestSearchCacheReuse:
    def test_second_call_hits_cache(self, db: Session, monkeypatch):
        user = _user(db, "search_cache")
        ws = Workspace(name="CW", created_by_id=user.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
        db.commit()

        calls: list[int] = []
        monkeypatch.setattr(
            search_service,
            "search_workspace",
            lambda *a, **k: (calls.append(a[1]), {"documents": [], "tables": [], "rows": []})[1],
        )
        search_service.search_all_workspaces(db, user, "缓存键", limit=3)
        search_service.search_all_workspaces(db, user, "缓存键", limit=3)
        assert len(calls) == 1
