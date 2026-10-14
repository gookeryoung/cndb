"""用户管理命令的数据库辅助：会话获取、用户解析、工作区归属与成员计数."""

from __future__ import annotations

from sqlalchemy.orm import Session

from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember


def _get_session():
    """打开一个 DB session。

    每次调用都根据当前 settings.DATABASE_URL 新建 engine + SessionLocal，
    这样 monkeypatch settings 的测试能正确拿到独立 DB。
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas

    _connect_args: dict[str, object] = {}
    if "sqlite" in settings.DATABASE_URL:
        _connect_args = {"check_same_thread": False}

    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=_connect_args,
        echo=settings.DEBUG,
    )
    # 开启 foreign_keys 等 pragma：保证 ondelete=CASCADE/SET NULL 真正生效，
    # 否则删除用户后 WorkspaceMember/TableMember 行残留为孤儿，成员计数虚高。
    register_sqlite_pragmas(engine)

    insp = inspect(engine)
    if not insp.has_table("accounts_user"):
        Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def _resolve_user(db: Session, target: str) -> User | None:
    """按用户名或用户 ID 解析用户."""
    if target.isdigit():
        return db.get(User, int(target))
    return db.query(User).filter(User.username == target).first()


def _list_owned_workspaces(db: Session, user_id: int) -> list[Workspace]:
    """返回用户作为 OWNER 的工作区列表."""
    return (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role == "owner",
        )
        .all()
    )


def _list_member_count(db: Session, user_id: int) -> int:
    """返回用户作为成员的工作区数量（含 OWNER + 非 OWNER）."""
    return db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).count()
