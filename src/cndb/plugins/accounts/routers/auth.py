"""认证路由：注册 / 登录 / 当前用户.

三员权限设计：
- 公开注册 /auth/register: 仅允许注册 user (普通用户) 角色
- 管理员创建 /auth/admin-register: 仅超级管理员可调用，可指定任意角色
- 用户管理（列表/编辑/批量/启禁用/操作日志）已迁移至 routers/users.py
  （/api/v1/accounts/users/*，仅超级管理员写、审计管理员可读日志）
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.errors import TooManyRequestsError, UnauthorizedError
from cndb.core.events import (
    ACTION_AUTH_LOGIN,
    ACTION_AUTH_LOGIN_FAILED,
    ACTION_AUTH_LOGOUT,
    ACTION_AUTH_PASSWORD_CHANGED,
    ACTION_AUTH_SESSION_REVOKED,
    ACTION_AUTH_TOKEN_REUSE,
    TARGET_SESSION,
    TARGET_USER,
    record_event,
)
from cndb.core.ratelimit import LoginRateLimiter
from cndb.core.security import hash_password, verify_password
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.accounts.schemas.auth import (
    AdminRegisterRequest,
    AuthModeResponse,
    LoginRequest,
    LogoutRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
    TokenResponse,
    UserResponse,
)
from cndb.plugins.accounts.services import sessions as session_service

router = APIRouter(prefix="/auth", tags=["auth"])

# 登录失败限流（进程内滑动窗口）：单机部署下与 Redis 等价，多实例才需要共享存储
_login_limiter = LoginRateLimiter(settings.LOGIN_MAX_FAILURES, settings.LOGIN_WINDOW_SECONDS)


def _reset_login_limiter() -> None:
    """重置限流计数（测试隔离用）."""
    _login_limiter.user_limiter.reset_all()
    _login_limiter.ip_limiter.reset_all()


def _limiter() -> LoginRateLimiter:
    """取限流器并按**当前**设置同步阈值（支持运行时调整与单测 monkeypatch）."""
    _login_limiter.configure(settings.LOGIN_MAX_FAILURES, settings.LOGIN_WINDOW_SECONDS)
    return _login_limiter


def _reject_in_local_mode(action: str) -> None:
    """单机模式下拒绝多用户网络行为（注册/登录等），统一 403.

    Args:
        action: 被禁用的行为中文名（用于错误明细）

    Raises:
        HTTPException: 403，detail 格式「单机模式已禁用<行为>」
    """
    if settings.LOCAL_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"单机模式已禁用{action}",
        )


def _validate_role(role: str) -> UserRole:
    """校验 role 值是否合法，返回 UserRole 枚举."""
    try:
        return UserRole(role)
    except ValueError as exc:
        valid = ", ".join(r.value for r in UserRole)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的角色 '{role}'，可选值: {valid}",
        ) from exc


def _ensure_unique(db: Session, username: str, email: str | None) -> None:
    """检查用户名/邮箱去重，冲突则 raise 400."""
    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=400, detail="用户名已被使用")
    if email and db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=400, detail="邮箱已被使用")


def _create_user(db: Session, user: User, password: str) -> None:
    """设置密码、写入并提交用户.

    并发竞态下（两个请求同时通过 _ensure_unique 检查）唯一约束冲突会
    在 commit 时抛 IntegrityError，此处降级为 400 明确提示，而非 500。
    """
    user.set_password(password)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="用户名或邮箱已被使用") from exc


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """公开注册新用户.

    公开注册入口已收窄为"只允许普通用户"，不接受 role 参数；
    角色由 User 模型默认值（user）自动填充。管理员创建三员账号
    请使用 /auth/admin-register（需要超级管理员权限）。

    Args:
        payload: 注册请求体（用户名/邮箱/昵称/密码）
        db: 数据库会话

    Returns:
        创建后的 User 对象
    """
    _reject_in_local_mode("注册")
    _ensure_unique(db, payload.username, payload.email)

    user = User(
        username=payload.username,
        email=payload.email,
        nickname=payload.nickname,
    )
    _create_user(db, user, payload.password)
    db.refresh(user)
    return user


@router.post(
    "/admin-register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="管理员创建用户",
)
def admin_register(
    payload: AdminRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """由超级管理员创建用户，可指定任意角色（含三员）.

    Args:
        payload: 管理员创建请求体（role 必填）
        db: 数据库会话
        current_user: 当前登录用户，必须是超级管理员

    Returns:
        创建后的 User 对象
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅超级管理员可创建用户",
        )

    _ensure_unique(db, payload.username, payload.email)
    validated = _validate_role(payload.role)

    user = User(
        username=payload.username,
        email=payload.email,
        nickname=payload.nickname,
        role=validated.value,
    )
    # 指定角色对应的语义化 nickname（如果没填）
    if not user.nickname:
        user.nickname = validated.display_name
    _create_user(db, user, payload.password)
    db.refresh(user)
    return user


@router.get("/auth-mode", response_model=AuthModeResponse)
def auth_mode() -> AuthModeResponse:
    """返回当前认证模式（无认证端点，供前端启动时探测）.

    local = 单机免登录模式（LOCAL_MODE=True），前端据此无头填充用户态；
    jwt = 常规 JWT 认证，走登录流程。独立于 /api/health，避免污染
    运维探针语义。

    Returns:
        AuthModeResponse（mode: "local" | "jwt"）
    """
    return AuthModeResponse(mode="local" if settings.LOCAL_MODE else "jwt")


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """用户登录，返回访问令牌 + 刷新令牌.

    支持用户名或邮箱作为登录标识。连续失败会触发限流（429 + Retry-After）：
    账号维度 ``LOGIN_MAX_FAILURES`` 次 / ``LOGIN_WINDOW_SECONDS`` 秒，来源 IP 维度为其 4 倍。
    """
    _reject_in_local_mode("登录")

    ip = request.client.host if request.client else None
    limiter = _limiter()
    retry_after = limiter.retry_after(payload.login, ip)
    if retry_after:
        raise TooManyRequestsError(
            f"登录失败次数过多，请在 {retry_after} 秒后重试",
            retry_after=retry_after,
        )

    user = db.query(User).filter((User.username == payload.login) | (User.email == payload.login)).first()
    if user is None or not user.is_active or not user.check_password(payload.password):
        limiter.record_failure(payload.login, ip)
        record_event(
            db,
            ACTION_AUTH_LOGIN_FAILED,
            summary=f"登录失败：{payload.login}",
            target_type=TARGET_USER,
            actor_id=getattr(user, "id", None),
            actor_name=getattr(user, "username", payload.login),
            detail={"login": payload.login, "ip": ip, "reason": "credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名/邮箱或密码错误",
        )

    limiter.reset(payload.login, ip)
    record_event(
        db,
        ACTION_AUTH_LOGIN,
        summary=f"登录成功：{user.username}",
        target_type=TARGET_USER,
        target_id=user.id,
        actor_id=user.id,
        actor_name=user.username,
        detail={"ip": ip, "user_agent": request.headers.get("user-agent")},
    )
    pair = session_service.issue_pair(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
    )
    return TokenResponse(**pair.as_dict())


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """用刷新令牌换取新的令牌对（一次性轮换）.

    旧刷新令牌立即失效；若**已轮换**的令牌再次被使用，视为泄露，吊销该用户全部会话后返回 401。
    """
    _reject_in_local_mode("刷新令牌")
    try:
        _user, pair = session_service.rotate(
            db,
            payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
        )
    except UnauthorizedError as exc:
        # 复用检测已吊销全部会话，额外落一条安全事件供审计
        if "重复使用" in str(getattr(exc, "detail", "")):
            record_event(
                db,
                ACTION_AUTH_TOKEN_REUSE,
                summary="检测到刷新令牌被重复使用，已吊销全部会话",
                target_type=TARGET_SESSION,
                detail={"ip": request.client.host if request.client else None},
            )
        raise
    return TokenResponse(**pair.as_dict())


@router.post("/logout")
def logout(
    payload: LogoutRequest | None = None,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """登出：吊销刷新令牌（单枚或全部）.

    仅带刷新令牌即可登出（即使访问令牌已过期）；``all=true`` 需要有效访问令牌进行身份确认。
    """
    _reject_in_local_mode("登出")
    body = payload or LogoutRequest()

    if body.all:
        # get_current_user 返回类型为 object | None（历史签名），此处收窄为 User
        current_user = cast(User, get_current_user(request, db))
        if current_user is None:
            raise UnauthorizedError("需要登录后才能下线全部会话")
        revoked = session_service.revoke_all(db, current_user.id, reason="logout_all")
        record_event(
            db,
            ACTION_AUTH_LOGOUT,
            summary=f"下线全部会话（{revoked} 个）",
            target_type=TARGET_SESSION,
            actor_id=current_user.id,
            actor_name=current_user.username,
            detail={"revoked": revoked},
        )
        return {"revoked": revoked, "scope": "all"}

    if not body.refresh_token:
        raise HTTPException(status_code=400, detail="请提供刷新令牌，或使用 all=true 下线全部会话")

    revoked = session_service.revoke_token(db, body.refresh_token)
    record_event(
        db,
        ACTION_AUTH_LOGOUT,
        summary="登出（吊销刷新令牌）" if revoked else "登出（令牌已失效）",
        target_type=TARGET_SESSION,
        detail={"revoked": int(revoked)},
    )
    return {"revoked": 1 if revoked else 0, "scope": "single"}


@router.post("/password")
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """修改自己的密码.

    校验当前密码 → 更新哈希 → 令牌代次 +1（既有 access token 立即失效）→ 吊销全部刷新令牌，
    因此改密后所有设备都需要重新登录。
    """
    if current_user is None:
        raise UnauthorizedError("未认证")
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.token_version = int(current_user.token_version or 0) + 1
    db.commit()
    revoked = session_service.revoke_all(db, current_user.id, reason="password_changed")
    record_event(
        db,
        ACTION_AUTH_PASSWORD_CHANGED,
        summary=f"修改密码：{current_user.username}",
        target_type=TARGET_USER,
        target_id=current_user.id,
        actor_id=current_user.id,
        actor_name=current_user.username,
        detail={"revoked_sessions": revoked},
    )
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionOut]:
    """列出当前用户仍有效的会话（新会话在前）."""
    if current_user is None:
        raise UnauthorizedError("未认证")
    return [SessionOut.model_validate(row) for row in session_service.list_sessions(db, current_user.id)]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """吊销指定会话（仅限本人）."""
    if current_user is None:
        raise UnauthorizedError("未认证")
    if not session_service.revoke_session(db, current_user.id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或已失效")
    record_event(
        db,
        ACTION_AUTH_SESSION_REVOKED,
        summary=f"下线会话 #{session_id}",
        target_type=TARGET_SESSION,
        target_id=session_id,
        actor_id=current_user.id,
        actor_name=current_user.username,
    )
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    """返回当前登录用户信息."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """当前用户自助更新个人资料（昵称/邮箱）.

    仅更新请求中显式提交的字段；邮箱传空字符串表示清空（置为 NULL）。
    邮箱全库唯一，冲突时返回 400 明细。

    Args:
        payload: 资料更新请求体（nickname/email 可选）
        db: 数据库会话
        current_user: 当前登录用户

    Returns:
        更新后的 User 对象
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")

    if payload.nickname is not None:
        current_user.nickname = payload.nickname
    if payload.email is not None:
        email = payload.email.strip() or None
        if email and email != current_user.email:
            exists = db.query(User).filter(User.email == email, User.id != current_user.id).first()
            if exists is not None:
                raise HTTPException(status_code=400, detail="邮箱已被使用")
        # email 列 nullable=True，空串会规整为 None 表示清空
        current_user.email = email

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="邮箱已被使用") from exc
    db.refresh(current_user)
    return current_user
