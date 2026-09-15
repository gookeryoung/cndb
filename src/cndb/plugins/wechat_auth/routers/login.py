"""微信登录路由 —— 核心逻辑."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.security import create_access_token
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.wechat_auth.client import code2session
from cndb.plugins.wechat_auth.models import WechatAccount
from cndb.plugins.wechat_auth.schemas.auth import (
    WechatLoginRequest,
    WechatLoginResponse,
)

router = APIRouter()


def _serialize_user(user: User) -> dict[str, object]:
    """返回给前端的用户信息 —— 脱敏（不含 hashed_password）."""
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname or user.username,
        "role": user.role,
        "is_superuser": user.is_superuser,
    }


@router.post(
    "/login",
    response_model=WechatLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="微信小程序登录",
)
def wechat_login(
    payload: WechatLoginRequest,
    db: Session = Depends(get_db),
) -> WechatLoginResponse:
    """小程序端登录入口.

    流程：
    1. 用 code 向微信换 openid / session_key
    2. openid 是否已在 wechat_accounts 表存在？
       ├── 是 → 查对应 User → 直接签发 JWT
       └── 否 → 自动创建 User（username=wx_{openid前8位}）+ WechatAccount → 签 JWT

    Args:
        payload: 包含 code + 可选昵称头像
        db: 数据库会话

    Returns:
        access_token + user 信息
    """
    if not settings.WECHAT_AUTH_ENABLED:
        raise HTTPException(status_code=403, detail="微信登录未启用")

    # Step 1: code → openid
    try:
        wx_session = code2session(payload.code)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    openid: str = wx_session["openid"]

    # Step 2: 查找或创建 WechatAccount
    account = db.query(WechatAccount).filter(WechatAccount.openid == openid).first()

    if account is None:
        # —— 首次出现 ——
        if not settings.WECHAT_LOGIN_AUTO_REGISTER:
            raise HTTPException(
                status_code=403,
                detail="请先通过 Web 端注册账号，再在个人中心绑定微信",
            )

        # 创建 User（避免极端碰撞：已存在则加随机后缀）
        username = f"wx_{openid[:8]}"
        base_username = username
        suffix = 0
        while db.query(User).filter(User.username == username).first() is not None:
            suffix += 1
            username = f"{base_username}_{suffix}"

        user = User(
            username=username,
            nickname=payload.nickname or "微信用户",
            role=UserRole.USER.value,
        )
        user.set_password(uuid.uuid4().hex)  # 随机密码，永不回显给前端
        db.add(user)
        db.flush()

        # 绑定 WechatAccount
        account = WechatAccount(
            openid=openid,
            unionid=wx_session.get("unionid"),
            session_key=wx_session.get("session_key"),
            user_id=user.id,
            nickname=payload.nickname,
            avatar_url=payload.avatar_url,
            last_login_at=datetime.now(UTC),
        )
        db.add(account)
    else:
        # —— 已有绑定 ——
        user = db.query(User).filter(User.id == account.user_id).first()
        if user is None or not user.is_active:
            raise HTTPException(status_code=400, detail="账号已被禁用")

        # 更新 session_key 和登录时间
        account.session_key = wx_session.get("session_key")
        account.last_login_at = datetime.now(UTC)
        if payload.nickname and not account.nickname:
            account.nickname = payload.nickname
        if payload.avatar_url and not account.avatar_url:
            account.avatar_url = payload.avatar_url

    db.commit()
    db.refresh(user)

    # Step 3: 签发 JWT —— 完全复用 accounts 插件的 token 体系
    access_token = create_access_token(
        subject=user.id,
        extra={"username": user.username},
    )

    return WechatLoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=_serialize_user(user),
    )
