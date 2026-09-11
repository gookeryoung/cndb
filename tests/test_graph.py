"""表关系图模块测试."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.models.base import Base
from cndb.plugins.tables.graph import (
    build_table_graph,
    get_workspace_dependencies,
    topological_sort,
)
from cndb.plugins.tables.models import DataField, DataTable


@pytest.fixture
def graph_session(tmp_path):
    db_path = tmp_path / "test_graph.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    u = User(username="g_user")
    u.set_password("pass")
    session.add(u)
    session.flush()
    ws = Workspace(name="GWS", created_by_id=u.id)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    session.commit()

    try:
        yield engine, session, ws
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def simple_graph(graph_session):
    """构建简单依赖：C 无依赖, B 依赖 C, A 依赖 B."""
    _engine, db, ws = graph_session

    def make_table(name, fields):
        t = DataTable(workspace_id=ws.id, name=name)
        t.ensure_db_name()
        db.add(t)
        db.flush()
        for i, (fname, ftype, cfg) in enumerate(fields):
            f = DataField(table_id=t.id, name=fname, field_type=ftype, order=i, config=cfg or {})
            f.ensure_db_name()
            db.add(f)
            db.flush()
        return t

    table_c = make_table("TableC", [("name", "text", {})])
    table_b = make_table("TableB", [("name", "text", {}), ("ref_c", "link", {"target_table_id": table_c.id})])
    table_a = make_table("TableA", [("name", "text", {}), ("ref_b", "link", {"target_table_id": table_b.id})])
    db.commit()
    return {"A": table_a, "B": table_b, "C": table_c}, graph_session


class TestBuildTableGraph:
    def test_simple_deps(self, simple_graph):
        tables, (_, db, ws) = simple_graph
        graph = build_table_graph(db, ws.id)
        assert tables["C"].id in graph
        assert tables["B"].id in graph
        assert tables["A"].id in graph
        assert graph[tables["C"].id] == set()
        assert graph[tables["B"].id] == {tables["C"].id}
        assert graph[tables["A"].id] == {tables["B"].id}

    def test_excludes_trashed(self, simple_graph):
        tables, (_, db, ws) = simple_graph
        tables["C"].trashed = True
        db.commit()
        graph = build_table_graph(db, ws.id)
        assert tables["C"].id not in graph


class TestTopologicalSort:
    def test_linear(self):
        graph = {1: {2}, 2: {3}, 3: set()}
        order = topological_sort(graph)
        assert order.index(3) < order.index(2)
        assert order.index(2) < order.index(1)

    def test_no_deps(self):
        graph = {1: set(), 2: set(), 3: set()}
        order = topological_sort(graph)
        assert len(order) == 3
        assert set(order) == {1, 2, 3}

    def test_cycle_detected(self):
        graph = {1: {2}, 2: {3}, 3: {1}}
        assert topological_sort(graph) == []

    def test_empty(self):
        assert topological_sort({}) == []


class TestGetWorkspaceDependencies:
    def test_structure(self, simple_graph):
        _tables, (_, db, ws) = simple_graph
        deps = get_workspace_dependencies(db, ws.id)
        assert "forward" in deps
        assert "reverse" in deps
        assert "link_fields" in deps
        assert len(deps["link_fields"]) >= 2


__all__ = []
