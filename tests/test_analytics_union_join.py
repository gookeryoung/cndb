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

    def test_float_source_accepts_numeric_declared_type(self, client, db, env):
        """float（小数）是字段 registry 真实数值类型：声明 number 应视为同族（与前端 fieldFamily 同口径）."""
        ws = env.sources[0]
        auth = _login(client, env.owner.username)
        tid = client.post(f"{WS}/{ws.id}/tables", json={"name": "金额明细"}, headers=auth).json()["id"]
        for order, (name, ftype) in enumerate((("区域", "text"), ("金额", "float"))):
            r = client.post(
                f"{WS}/{ws.id}/tables/{tid}/fields",
                json={"name": name, "field_type": ftype, "order": order},
                headers=auth,
            )
            assert r.status_code in (200, 201), r.text
        r = client.post(
            f"{WS}/{ws.id}/tables/{tid}/records",
            json={"values": {"区域": "上海", "金额": 12.5}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text

        other = _make_source_table(client, env, 1, [("广州", 30)])
        links = [_link(client, env, 0, tid), _link(client, env, 1, other)]
        source = {
            "type": "union",
            "inputs": [{"link_id": link["id"]} for link in links],
            "columns": [
                {"name": "金额", "type": "number", "map": {str(links[0]["id"]): "金额"}},
            ],
        }
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": [{"key": "合计", "expr": "sum([金额])"}]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["table_fields"] == ["金额"]
        # 另一输入未映射该列 → 按空值补齐（ADR 0159 C1）
        assert payload["total"] == 2

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


class TestJoinCompute:
    """ADR 0159 P1：跨工作区关联（left / inner，左表驱动）。"""

    def _setup(self, client, env) -> dict:
        """左侧 = 消费方本地客户表（客户编号 / 客户名 / 金额），右侧 = 链接的回款表（客户号 / 回款）。"""
        auth = _login(client, env.owner.username)
        # 右：源工作区
        ws = env.sources[0]
        tid = client.post(f"{WS}/{ws.id}/tables", json={"name": "回款"}, headers=auth).json()["id"]
        for order, (name, ftype) in enumerate((("客户号", "text"), ("回款", "number"), ("金额", "number"))):
            client.post(
                f"{WS}/{ws.id}/tables/{tid}/fields",
                json={"name": name, "field_type": ftype, "order": order},
                headers=auth,
            )
        for code, amount in (("C1", 100), ("C2", 200), ("C9", 900)):
            client.post(
                f"{WS}/{ws.id}/tables/{tid}/records",
                json={"values": {"客户号": code, "回款": amount, "金额": 1}},
                headers=auth,
            )
        link = _link(client, env, 0, tid)

        # 左：消费方本地表（只有 C1 / C2，C9 在右表存在但不该出现）
        local = client.post(f"{WS}/{env.consumer.id}/tables", json={"name": "客户"}, headers=auth).json()["id"]
        for order, (name, ftype) in enumerate((("客户编号", "text"), ("客户名", "text"), ("金额", "number"))):
            client.post(
                f"{WS}/{env.consumer.id}/tables/{local}/fields",
                json={"name": name, "field_type": ftype, "order": order},
                headers=auth,
            )
        for code, name in (("C1", "甲"), ("C2", "乙"), ("C3", "丙")):
            client.post(
                f"{WS}/{env.consumer.id}/tables/{local}/records",
                json={"values": {"客户编号": code, "客户名": name, "金额": 5}},
                headers=auth,
            )
        return {"link": link, "local_table_id": local}

    def _source(self, ctx: dict, join_type: str = "left") -> dict:
        return {
            "type": "join",
            "join_type": join_type,
            "left": {"table_id": ctx["local_table_id"]},
            "right": {"link_id": ctx["link"]["id"]},
            "on": [{"left_field": "客户编号", "right_field": "客户号"}],
        }

    def test_left_join_keeps_all_left_rows(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": self._source(ctx), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3  # C1 / C2 匹配 + C3 未匹配（右列补空）
        names = {row.get("客户名") for row in body["rows"]}
        assert names == {"甲", "乙", "丙"}
        # 冲突列「金额」消歧；右表关联键「客户号」不重复输出
        assert set(body["table_fields"]) == {
            "客户编号",
            "客户名",
            "left.金额",
            "回款",
            "right.金额",
        }
        # C9 只在右表存在 → 绝不能出现（行存在性不外泄）
        assert all("C9" not in str(row) for row in body["rows"])
        matched = [row for row in body["rows"] if row.get("回款") is not None]
        assert {row["客户名"] for row in matched} == {"甲", "乙"}

    def test_inner_join_drops_unmatched_left_rows(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": self._source(ctx, "inner"), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 2
        assert {row.get("客户名") for row in r.json()["rows"]} == {"甲", "乙"}

    def test_join_formula_can_aggregate_right_column(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        body = {
            "source": self._source(ctx, "inner"),
            "formulas": [{"key": "回款合计", "expr": "sum([回款])"}],
        }
        r = client.post(f"{ANALYTICS.format(wid=env.consumer.id)}/compute", json=body, headers=auth)
        assert r.status_code == 200, r.text
        assert all(row["回款合计"] == 300 for row in r.json()["rows"])

    def test_right_only_rejected(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        source = self._source(ctx)
        source["join_type"] = "right"
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 422

    def test_hidden_join_key_rejected(self, client, db, env):
        ctx = self._setup(client, env)
        db.add(TablePermission(table_id=ctx["local_table_id"], hidden_fields={"owner": ["客户编号"]}))
        db.commit()
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": self._source(ctx), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "关联键不可用" in r.json()["detail"]

    def test_revoked_right_link_fails_whole_join(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        client.delete(f"{LINKS.format(wid=env.consumer.id)}/{ctx['link']['id']}", headers=auth)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": self._source(ctx), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 404

    def test_save_template_with_join_source(self, client, db, env):
        ctx = self._setup(client, env)
        auth = _login(client, env.owner.username)
        body = {
            "name": "客户回款关联",
            "config": {
                "source": self._source(ctx),
                "formulas": [{"key": "回款合计", "expr": "sum([回款])"}],
            },
        }
        r = client.post(f"{ANALYTICS.format(wid=env.consumer.id)}/templates", json=body, headers=auth)
        assert r.status_code == 201, r.text
        saved = r.json()
        assert saved["table_id"] is None
        assert saved["config"]["source"]["join_type"] == "left"
        assert saved["config"]["source"]["on"][0] == {"left_field": "客户编号", "right_field": "客户号"}


class TestUnionEdgeCases:
    """边界：扫描额度截断、非法映射输入、未知类型族、公式语法错误."""

    def _setup_two(self, client, env) -> list[dict]:
        t1 = _make_source_table(client, env, 0, [("上海", 10), ("杭州", 20)])
        t2 = _make_source_table(client, env, 1, [("广州", 30)])
        return [_link(client, env, 0, t1), _link(client, env, 1, t2)]

    def test_scan_budget_truncates(self, client, db, env, monkeypatch):
        from cndb.core.config import settings

        links = self._setup_two(client, env)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_SCAN_ROWS", 2)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["truncated"] is True

    def test_mapping_unknown_input_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"][0]["map"]["999"] = "区域"
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "不属于该汇总" in r.json()["detail"]

    def test_unknown_type_family_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        source = _union_source(links)
        source["columns"][0]["type"] = "weirdtype"  # 未知声明类型 → 与 text 不同族
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 400
        assert "类型不兼容" in r.json()["detail"]

    def test_formula_syntax_error_rejected(self, client, db, env):
        links = self._setup_two(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": _union_source(links), "formulas": [{"key": "x", "expr": "sum("}]},
            headers=auth,
        )
        assert r.status_code == 400


class TestValidateCompositeSource:
    """ADR 0159 P2：公式校验按复合源合成字段清单判定（保存期 / 编辑期同口径）."""

    def _setup_union(self, client, env) -> list[dict]:
        t1 = _make_source_table(client, env, 0, [("上海", 10)])
        t2 = _make_source_table(client, env, 1, [("广州", 20)])
        return [_link(client, env, 0, t1), _link(client, env, 1, t2)]

    def test_union_validate_uses_composite_fields(self, client, db, env):
        links = self._setup_union(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/validate",
            json={"source": _union_source(links), "formulas": [{"key": "x", "expr": "sum([销售额])"}]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["table_fields"] == ["区域", "销售额"]
        assert body["results"][0]["fields"] == ["销售额"]

    def test_union_validate_rejects_unmapped_column(self, client, db, env):
        links = self._setup_union(client, env)
        source = _union_source(links)
        source["columns"] = [source["columns"][0]]  # 只声明「区域」，销售额被丢弃
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/validate",
            json={"source": source, "formulas": [{"key": "x", "expr": "sum([销售额])"}]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "销售额" in body["results"][0]["error"]

    def test_union_validate_revoked_input_404(self, client, db, env):
        links = self._setup_union(client, env)
        auth = _login(client, env.owner.username)
        client.delete(f"{LINKS.format(wid=env.consumer.id)}/{links[0]['id']}", headers=auth)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/validate",
            json={"source": _union_source(links), "formulas": []},
            headers=auth,
        )
        assert r.status_code == 404

    def test_join_validate_accepts_disambiguated_columns(self, client, db, env):
        join = TestJoinCompute()
        ctx = join._setup(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/validate",
            json={
                "source": join._source(ctx),
                "formulas": [
                    {"key": "a", "expr": "sum([left.金额])"},
                    {"key": "b", "expr": "sum([回款])"},
                ],
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "left.金额" in body["table_fields"]
        assert "right.金额" in body["table_fields"]
        assert "客户号" not in body["table_fields"]  # 右表关联键不重复输出

    def test_join_validate_rejects_right_key_reference(self, client, db, env):
        join = TestJoinCompute()
        ctx = join._setup(client, env)
        auth = _login(client, env.owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/validate",
            json={
                "source": join._source(ctx),
                "formulas": [{"key": "x", "expr": "sum([客户号])"}],
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "客户号" in body["results"][0]["error"]


class TestJoinEdgeCases:
    def test_left_side_can_be_link(self, client, db, env):
        """左 = 链接、右 = 链接的组合也要能跑（左表驱动不变）."""
        auth = _login(client, env.owner.username)
        # 两个源的字段名一致（区域 / 销售额），用「区域」关联
        t1 = _make_source_table(client, env, 0, [("上海", 10), ("广州", 30)])
        t2 = _make_source_table(client, env, 1, [("上海", 20), ("北京", 40)])
        left = _link(client, env, 0, t1)
        right = _link(client, env, 1, t2)
        source = {
            "type": "join",
            "join_type": "inner",
            "left": {"link_id": left["id"]},
            "right": {"link_id": right["id"]},
            "on": [{"left_field": "区域", "right_field": "区域"}],
        }
        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/compute",
            json={"source": source, "formulas": []},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1  # 只有「上海」两侧都有
        assert "北京" not in {row.get("区域") for row in body["rows"]}
        # 冲突列（销售额 / 销售额、备注 / 备注）双侧加前缀
        assert set(body["table_fields"]) == {
            "left.区域",
            "left.销售额",
            "left.备注",
            "right.销售额",
            "right.备注",
        }
