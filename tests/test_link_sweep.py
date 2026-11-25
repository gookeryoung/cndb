"""ADR 0154 D10 / C10：`cndb link sweep` 回收过期链接创建的只读成员.

口径：
1. 只回收 `created_member_ids` 里的成员（原本就是成员的不动，L9）；
2. 链接置 `expired`，写 `workspace.link_expired` 事件；
3. 幂等：重复执行不会再动任何成员；
4. 角色被提升过的成员（不再 viewer）不删，避免误降级他人协作关系。
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from cndb.cli.link import cmd_sweep
from cndb.core.events import CoreEvent
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceLink,
    WorkspaceLinkStatus,
    WorkspaceMember,
    WorkspaceRole,
)
from cndb.plugins.workspaces.services.links import sweep_expired_links


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "sweep_owner")
        self.granted = _user(db, "sweep_granted")
        self.pre_existing = _user(db, "sweep_preexisting")
        self.promoted = _user(db, "sweep_promoted")

        self.source = Workspace(name="源", created_by_id=self.owner.id)
        self.consumer = Workspace(name="消费", created_by_id=self.owner.id)
        db.add_all([self.source, self.consumer])
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.pre_existing.id, role=WorkspaceRole.EDITOR))
        # 链接创建的两个 viewer：一个保持只读，一个后来被提升为 editor
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.granted.id, role=WorkspaceRole.VIEWER))
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.promoted.id, role=WorkspaceRole.EDITOR))
        self.table = DataTable(
            workspace_id=self.source.id,
            owner_id=self.owner.id,
            name="明细",
            description="",
            db_table_name="t_sweep_sales",
        )
        db.add(self.table)
        db.commit()
        db.refresh(self.source)
        db.refresh(self.consumer)
        db.refresh(self.table)

    def make_link(self, db: Session, *, expired: bool, status=WorkspaceLinkStatus.ACTIVE) -> WorkspaceLink:
        now = dt.datetime.now(dt.UTC)
        link = WorkspaceLink(
            workspace_id=self.consumer.id,
            source_workspace_id=self.source.id,
            target_type="table",
            target_table_id=self.table.id,
            alias=f"链接-{int(now.timestamp() * 1000)}-{expired}",
            status=status,
            ttl_days=1,
            granted_member_ids=[self.granted.id, self.pre_existing.id, self.promoted.id],
            created_member_ids=[self.granted.id, self.promoted.id],
            expires_at=now - dt.timedelta(minutes=5) if expired else now + dt.timedelta(days=1),
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return link


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


def _source_members(db: Session, env: Env) -> set[int]:
    db.expire_all()
    return {
        row[0] for row in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == env.source.id).all()
    }


class TestSweep:
    def test_expired_link_revokes_created_members_only(self, db, env):
        link = env.make_link(db, expired=True)
        payload = sweep_expired_links(db)

        assert payload["expired"] == 1
        assert payload["details"][0]["link_id"] == link.id
        # granted 被回收；原本就在的 pre_existing 与已提升的 promoted 保留（L9）
        assert _source_members(db, env) == {env.owner.id, env.pre_existing.id, env.promoted.id}
        db.expire_all()
        assert db.get(WorkspaceLink, link.id).status is WorkspaceLinkStatus.EXPIRED

    def test_active_link_is_untouched(self, db, env):
        link = env.make_link(db, expired=False)
        payload = sweep_expired_links(db)
        assert payload["expired"] == 0
        assert _source_members(db, env) >= {env.granted.id, env.promoted.id}
        db.expire_all()
        assert db.get(WorkspaceLink, link.id).status is WorkspaceLinkStatus.ACTIVE

    def test_sweep_is_idempotent(self, db, env):
        env.make_link(db, expired=True)
        assert sweep_expired_links(db)["expired"] == 1
        assert sweep_expired_links(db)["expired"] == 0

    def test_sweep_writes_event(self, db, env):
        env.make_link(db, expired=True)
        sweep_expired_links(db)
        actions = {row[0] for row in db.query(CoreEvent.action).filter(CoreEvent.action.like("workspace.link%")).all()}
        assert "workspace.link_expired" in actions

    def test_sweep_respects_limit(self, db, env):
        for _ in range(2):
            env.make_link(db, expired=True)
        assert sweep_expired_links(db, limit=1)["expired"] == 1

    def test_cli_cmd_sweep_runs(self, db, env, monkeypatch):
        """CLI 入口只做会话装配：这里替换会话工厂，验证命令链路能跑通."""
        env.make_link(db, expired=True)
        monkeypatch.setattr("cndb.cli.link._get_session", lambda: db)

        class Args:
            limit = 200
            json = False

        payload = cmd_sweep(Args())
        assert payload["expired"] >= 1
