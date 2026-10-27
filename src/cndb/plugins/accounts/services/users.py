"""用户管理服务层：编辑 / 批量操作 / 操作日志.

业务规则（设计文档 .trae/designs/user-management-upgrade.md 第 3.2 节）：
- 禁止自我降权/自我禁用（防误锁）
- 末位超级管理员保护：系统至少保留 1 个可用超管
- 所有写操作记录 before/after 审计快照，审计失败不阻断主操作
- 校验失败抛 UserAdminError，由路由层映射为 400
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from cndb.core.events import TARGET_USER, record_event, summarize_user_action
from cndb.plugins.accounts.models import User, UserAuditLog, UserRole
from cndb.plugins.accounts.schemas.users import (
    BatchUserActionRequest,
    BatchUserActionResponse,
    BatchUserItemResult,
    UserAdminUpdateRequest,
)
from cndb.plugins.accounts.services import sessions as session_service
from cndb.plugins.accounts.services.user_bulk import generate_password

logger = logging.getLogger(__name__)


class UserAdminError(Exception):
    """用户管理业务校验失败（路由层统一映射为 400 + 中文明细）."""


def validate_role(role: str) -> UserRole:
    """校验 role 值是否合法，非法时抛 UserAdminError.

    Args:
        role: 角色字符串

    Returns:
        对应的 UserRole 枚举
    """
    try:
        return UserRole(role)
    except ValueError as exc:
        valid = ", ".join(r.value for r in UserRole)
        raise UserAdminError(f"无效的角色 '{role}'，可选值: {valid}") from exc


def _snapshot(user: User) -> dict[str, Any]:
    """提取用户关键字的 before/after 快照."""
    return {
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "nickname": user.nickname,
        "role": user.role,
        "is_active": user.is_active,
    }


def record_audit(
    db: Session,
    *,
    action: str,
    actor_id: int | None,
    target_user_id: int | None,
    detail: dict[str, Any],
) -> None:
    """追加一条用户管理操作日志（尽力而为，失败仅告警不回滚主操作）.

    Args:
        db: 数据库会话
        action: 动作（update / role_change / activate / deactivate / batch）
        actor_id: 操作人 ID
        target_user_id: 被操作用户 ID
        detail: 变更详情（before/after 快照、批量摘要）
    """
    try:
        db.add(
            UserAuditLog(
                action=action,
                actor_id=actor_id,
                target_user_id=target_user_id,
                detail=detail,
            )
        )
        db.commit()
        # 同步进统一事件流（域内查询仍走 accounts_userauditlog）
        record_event(
            db,
            f"user.{action}",
            summary=summarize_user_action(action),
            target_type=TARGET_USER,
            target_id=target_user_id,
            actor_id=actor_id,
            detail=detail,
        )
    except SQLAlchemyError:
        db.rollback()
        logger.warning("写入用户操作日志失败: action=%s actor=%s target=%s", action, actor_id, target_user_id)


def _ensure_username_free(db: Session, username: str, exclude_id: int) -> None:
    """用户名全库唯一，冲突抛 UserAdminError."""
    exists = db.query(User).filter(User.username == username, User.id != exclude_id).first()
    if exists is not None:
        raise UserAdminError("用户名已被使用")


def _ensure_email_free(db: Session, email: str, exclude_id: int) -> None:
    """邮箱全库唯一，冲突抛 UserAdminError."""
    exists = db.query(User).filter(User.email == email, User.id != exclude_id).first()
    if exists is not None:
        raise UserAdminError("邮箱已被使用")


def _ensure_not_last_active_superuser(db: Session, target: User) -> None:
    """末位超管保护：禁用最后一个可用超管时抛 UserAdminError.

    可用超管定义：is_superuser=True 且 is_active=True 且非目标本人。
    """
    other = (
        db.query(User)
        .filter(
            User.is_superuser.is_(True),
            User.is_active.is_(True),
            User.id != target.id,
        )
        .first()
    )
    if other is None:
        raise UserAdminError("不能禁用最后一个可用的超级管理员")


def get_user_or_none(db: Session, user_id: int) -> User | None:
    """按 ID 取用户，不存在返回 None."""
    return db.query(User).filter(User.id == user_id).first()


def update_user(db: Session, *, actor: User, target: User, data: UserAdminUpdateRequest) -> User:
    """管理员编辑用户（用户名/邮箱/电话/昵称/角色/状态），并写入审计.

    仅处理显式提交的字段；email/phone 空字符串表示清空（置 NULL）。

    Args:
        db: 数据库会话
        actor: 操作人（超级管理员）
        target: 被编辑用户
        data: 编辑请求体

    Returns:
        更新后的 User（已提交并刷新）

    Raises:
        UserAdminError: 校验失败（唯一性冲突 / 自我保护 / 末位超管保护）
    """
    if target.id == actor.id and (data.role is not None or data.is_active is not None):
        raise UserAdminError("不能修改自己的角色或启用状态")

    before = _snapshot(target)
    action = "update"

    if data.username is not None and data.username != target.username:
        _ensure_username_free(db, data.username, exclude_id=target.id)
        target.username = data.username
    if data.email is not None:
        email = data.email.strip() or None
        if email and email != target.email:
            _ensure_email_free(db, email, exclude_id=target.id)
        target.email = email
    if data.phone is not None:
        target.phone = data.phone.strip() or None
    if data.nickname is not None:
        target.nickname = data.nickname
    if data.role is not None:
        role = validate_role(data.role)
        if role.value != target.role:
            target.role = role.value
            action = "role_change"
    if data.is_active is not None and data.is_active != target.is_active:
        if not data.is_active:
            _ensure_not_last_active_superuser(db, target)
        target.is_active = data.is_active
        action = "activate" if data.is_active else "deactivate"

    after = _snapshot(target)
    if after == before:
        return target  # 无实际变更，不写审计

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise UserAdminError("用户名或邮箱已被使用") from exc
    db.refresh(target)
    record_audit(
        db, action=action, actor_id=actor.id, target_user_id=target.id, detail={"before": before, "after": after}
    )
    return target


def reset_user_password(
    db: Session,
    *,
    actor: User,
    target: User,
    new_password: str | None = None,
) -> tuple[str | None, int]:
    """管理员重置他人密码（不含自助改密路径）.

    ``new_password`` 留空时生成 12 位随机密码；返回值仅在自动生成时携带明文，供本次响应一次性展示。
    成功后目标用户 ``token_version`` +1（既有 access token 立即失效）并吊销全部刷新令牌。

    Args:
        db: 数据库会话
        actor: 操作人（超级管理员）
        target: 被重置用户
        new_password: 手工指定密码；None 表示自动生成

    Returns:
        (generated_password | None, revoked_sessions)

    Raises:
        UserAdminError: 重置自己，或手工密码长度不在 6-128 位
    """
    if target.id == actor.id:
        raise UserAdminError("不能重置自己的密码，请在个人设置中修改（需校验当前密码）")
    if new_password is not None and not 6 <= len(new_password) <= 128:
        raise UserAdminError("密码长度须为 6-128 位")

    generated = new_password is None
    plain = generate_password() if generated else new_password
    assert plain is not None  # 仅在 generated 为 True 时可能为 None，此处已收窄

    target.set_password(plain)
    target.token_version = int(target.token_version or 0) + 1
    db.commit()
    db.refresh(target)

    revoked = session_service.revoke_all(db, target.id, reason="password_reset_by_admin")
    record_audit(
        db,
        action="password_reset",
        actor_id=actor.id,
        target_user_id=target.id,
        detail={"generated": generated, "revoked_sessions": revoked},
    )
    return (plain if generated else None, revoked)


def batch_user_action(db: Session, *, actor: User, payload: BatchUserActionRequest) -> BatchUserActionResponse:
    """批量启用/禁用/设置角色，逐项独立提交并返回逐项结果.

    单项失败（不存在/自我保护/末位超管）不影响其他项。

    Args:
        db: 数据库会话
        actor: 操作人（超级管理员）
        payload: 批量操作请求体

    Returns:
        逐项结果汇总

    Raises:
        UserAdminError: action=set_role 缺少 role 或角色非法
    """
    new_role: UserRole | None = None
    if payload.action == "set_role":
        if not payload.role:
            raise UserAdminError("批量设置角色必须提供 role")
        new_role = validate_role(payload.role)

    results: list[BatchUserItemResult] = []
    for uid in payload.user_ids:
        user = get_user_or_none(db, uid)
        try:
            if user is None:
                raise UserAdminError("用户不存在")
            if user.id == actor.id:
                raise UserAdminError("不能对自己执行批量操作")
            if payload.action == "deactivate":
                _ensure_not_last_active_superuser(db, user)
            if payload.action == "activate":
                user.is_active = True
            elif payload.action == "deactivate":
                user.is_active = False
            else:
                assert new_role is not None
                user.role = new_role.value
            db.commit()
            results.append(BatchUserItemResult(user_id=uid, username=user.username, success=True))
        except UserAdminError as exc:
            db.rollback()
            results.append(
                BatchUserItemResult(user_id=uid, username=user.username if user else "", success=False, error=str(exc))
            )

    succeeded = sum(1 for r in results if r.success)
    record_audit(
        db,
        action="batch",
        actor_id=actor.id,
        target_user_id=None,
        detail={
            "action": payload.action,
            "role": payload.role,
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "results": [r.model_dump() for r in results],
        },
    )
    return BatchUserActionResponse(
        total=len(results), succeeded=succeeded, failed=len(results) - succeeded, results=results
    )


def query_audit_logs(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    action: str | None = None,
    actor_id: int | None = None,
    target_user_id: int | None = None,
) -> tuple[list[UserAuditLog], int]:
    """分页查询用户管理操作日志（时间倒序）.

    Args:
        db: 数据库会话
        page: 页码（1 起）
        page_size: 每页条数（1-100）
        action: 按动作筛选
        actor_id: 按操作人筛选
        target_user_id: 按被操作用户筛选

    Returns:
        (日志列表, 总数)
    """
    q = db.query(UserAuditLog)
    if action is not None:
        q = q.filter(UserAuditLog.action == action)
    if actor_id is not None:
        q = q.filter(UserAuditLog.actor_id == actor_id)
    if target_user_id is not None:
        q = q.filter(UserAuditLog.target_user_id == target_user_id)
    total = q.with_entities(sa_func.count()).scalar() or 0
    logs = (
        q.order_by(UserAuditLog.created_at.desc(), UserAuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return list(logs), int(total)


__all__ = [
    "UserAdminError",
    "batch_user_action",
    "get_user_or_none",
    "query_audit_logs",
    "record_audit",
    "reset_user_password",
    "update_user",
    "validate_role",
]
