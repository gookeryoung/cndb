"""ADR 0159 P0：多链接汇总（union all）判定层 + 接口层.

锁定口径：
- 逐输入同权：任一输入失效 404 / 无读权 403 → 整体失败（**不返回部分结果**，L2）；
- 显式列映射：未映射的输入列丢弃；映射不可用字段 400；
- 类型严格同族（数值族互认）；输入 2–5 个；列名不可重复；输入不可重复；
- 存量单源路径不变（L6）。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceLink,
    WorkspaceMember,
    WorkspaceRole,
)

WS = "/api/v1/workspaces"
LINKS = "/api/v1/workspaces/{wid}/links"
ANALYTICS = "/api/v1/workspaces/{wid}/analytics"


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
    """两个源工作区（各一张销售表）+ 一个消费方工作区，全部归同一 owner。"""

    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "uj_owner")
        # 只看不写的消费方成员：链接批准后会被批量加为源工作区 viewer，
        # 用于验证「字段隐藏 / 行级」在汇总链路上同样生效（owner 会豁免隐藏字段）
        self.viewer = _user(db, "uj_viewer")
        self.consumer = Workspace(name="总部", created_by_id=self.owner.id)
        db.add(self.consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.consumer.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.consumer.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        self.sources: list[Workspace] = []
        for name in ("华东区", "华南区"):
            ws = Workspace(name=name, created_by_id=self.owner.id)
            db.add(ws)
            db.flush()
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
            self.sources.append(ws)
        db.commit()
        db.refresh(self.consumer)
        for ws in self.sources:
            db.refresh(ws)


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


def _make_source_table(client: TestClient, env: Env, index: int, rows: list[tuple[str, int]]) -> int:
    """在源工作区建「区域 / 销售额 / 备注」表并写数据，返回 table_id."""
    ws = env.sources[index]
    auth = _login(client, env.owner.username)
    tid = client.post(f"{WS}/{ws.id}/tables", json={"name": f"{ws.name}销售"}, headers=auth).json()["id"]
    for order, (name, ftype) in enumerate((("区域", "text"), ("销售额", "number"), ("备注", "text"))):
        r = client.post(
            f"{WS}/{ws.id}/tables/{tid}/fields",
            json={"name": name, "field_type": ftype, "order": order},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    for region, amount in rows:
        r = client.post(
            f"{WS}/{ws.id}/tables/{tid}/records",
            json={"values": {"区域": region, "销售额": amount, "备注": "x"}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    return tid


def _link(client: TestClient, env: Env, index: int, table_id: int) -> dict:
    ws = env.sources[index]
    auth = _login(client, env.owner.username)
    link = client.post(
        LINKS.format(wid=env.consumer.id),
        json={"source_workspace_id": ws.id, "target_table_id": table_id, "ttl_days": 30},
        headers=auth,
    ).json()
    r = client.post(f"{LINKS.format(wid=ws.id)}/{link['id']}/approve", json={}, headers=auth)
    assert r.status_code == 200, r.text
    return link


def _union_source(links: list[dict]) -> dict:
    """默认两列映射：区域（text）+ 销售额（number）."""
    return {
        "type": "union",
        "inputs": [{"link_id": link["id"]} for link in links],
        "columns": [
            {"name": "区域", "type": "text", "map": {str(link["id"]): "区域" for link in links}},
            {"name": "销售额", "type": "number", "map": {str(link["id"]): "销售额" for link in links}},
        ],
    }


class TestUnionCompute:
    def _setup_two(self, client, env) -> list[dict]:
        t1 = _make_source_table(client, env, 0, [("上海", 10), ("杭州", 20)])
        t2 = _make_source_table(client, env, 1, [("广州", 30)])
        return [_link(client, env, 0, t1), _link(client, env, 1, t2)]

    def test_union_rows_and_formula(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        body = {"source": _union_source(links), "formulas": [{"key": "合计", "expr": "sum([销售额])"}]}
        r = client.post(f"{ANALYTICS.format(wid=env.consumer.id)}/compute", json=body, headers=auth)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["total"] == 3
        assert payload["table_fields"] == ["区域", "销售额"]
        assert sorted(row["区域"] for row in payload["rows"]) == ["上海", "广州", "杭州"]
        assert all(row["合计"] == 60 for row in payload["rows"])

    def test_unmapped_input_column_is_dropped(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"] = [source["columns"][0]]  # 只声明「区域」
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["table_fields"] == ["区域"]
        assert all("销售额" not in row for row in r.json()["rows"])

    def test_single_input_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links[:1]), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "输入" in r.json()["detail"]

    def test_type_mismatch_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"][1]["type"] = "date"  # 声明 date，来源是 number
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "类型不兼容" in r.json()["detail"]

    def test_hidden_field_in_mapping_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        tid = db.get(WorkspaceLink, links[0]["id"]).target_table_id
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["销售额"]}))
        db.commit()
        auth = _login(client, env.viewer.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "不可用字段" in r.json()["detail"]

    def test_revoked_link_fails_whole_union(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/{links[0]['id']}", headers=auth).status_code == 204
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 404

    def test_expired_link_fails_whole_union(self, client, db, env):
        links = self._setup_two(client, env)
        stored = db.get(WorkspaceLink, links[1]["id"])
        stored.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        db.commit()
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 404

    def test_duplicate_input_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["inputs"].append({"link_id": links[0]["id"]})
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "不能重复" in r.json()["detail"]

    def test_formula_referencing_dropped_column_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"] = [source["columns"][0]]  # 只有「区域」
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": [{"key": "x", "expr": "sum([销售额])"}]},
            headers=auth,
        )
        assert r.status_code == 400
        assert "字段不可用于该数据源" in r.json()["detail"]


class TestUnionTemplate:
    def _setup_two(self, client, env) -> list[dict]:
        t1 = _make_source_table(client, env, 0, [("上海", 10)])
        t2 = _make_source_table(client, env, 1, [("广州", 20)])
        return [_link(client, env, 0, t1), _link(client, env, 1, t2)]

    def test_save_template_with_union_source(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        body = {
            "name": "各区汇总",
            "config": {
                "source": _union_source(links),
                "formulas": [{"key": "合计", "expr": "sum([销售额])"}],
            },
        }
        r = client.post(f"{ANALYTICS.format(wid=env.consumer.id)}/templates", json=body, headers=auth)
        assert r.status_code == 201, r.text
        saved = r.json()
        assert saved["table_id"] is None
        # 列名与顺序固化进配置（L4）
        assert [c["name"] for c in saved["config"]["source"]["columns"]] == ["区域", "销售额"]
        assert saved["config"]["source"]["inputs"][0]["link_id"] == links[0]["id"]

    def test_save_rejects_revoked_input(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        client.delete(f"{LINKS.format(wid=env.consumer.id)}/{links[1]['id']}", headers=auth)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/templates",
            json={"name": "坏汇总", "config": {"source": _union_source(links), "formulas": []}},
            headers=auth,
        )
        assert r.status_code == 404

    def test_save_rejects_type_mismatch(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"][1]["type"] = "boolean"
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/templates",
            json={"name": "类型不符", "config": {"source": source, "formulas": []}},
            headers=auth,
        )
        assert r.status_code == 400
