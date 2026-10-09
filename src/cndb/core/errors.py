"""统一业务异常体系.

服务层用本模块异常表达业务失败语义，路由层/全局 handler 统一映射为
HTTP 响应，避免服务层异常裸穿成未映射 500。

约定：
- ``status_code``：HTTP 语义状态码（默认 400）
- ``code``：机器可读错误码（``业务域_错误类别`` 形式，如 ``import_validation``）
- ``detail``：面向调用方的中文错误说明（可直接展示）

错误响应体形状（全局 handler 统一）::

    {"detail": "<中文说明>", "code": "<错误码>"}
"""

from __future__ import annotations

from typing import Any


class CndbError(Exception):
    """cndb 业务异常基类.

    Attributes:
        detail: 面向调用方的中文错误说明。
        code: 机器可读错误码。
        status_code: HTTP 映射状态码。
        context: 附加上下文（不进入响应体，供日志排查）。
    """

    status_code: int = 400
    code: str = "cndb_error"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        **context: Any,
    ) -> None:
        """构造业务异常.

        Args:
            detail: 中文错误说明。
            code: 覆盖类默认错误码。
            status_code: 覆盖类默认 HTTP 状态码。
            **context: 附加日志上下文。
        """
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.context = context

    def to_payload(self) -> dict[str, str]:
        """构造统一错误响应体.

        Returns:
            ``{"detail": ..., "code": ...}`` 字典。
        """
        return {"detail": self.detail, "code": self.code}


class BadRequestError(CndbError):
    """业务校验失败（HTTP 400）。"""

    status_code = 400
    code = "bad_request"


class PermissionDeniedError(CndbError):
    """权限不足（HTTP 403）。"""

    status_code = 403
    code = "permission_denied"


class NotFoundError(CndbError):
    """目标资源不存在（HTTP 404）。"""

    status_code = 404
    code = "not_found"


class ConflictError(CndbError):
    """状态/唯一性冲突（HTTP 409）。"""

    status_code = 409
    code = "conflict"


__all__ = [
    "BadRequestError",
    "CndbError",
    "ConflictError",
    "NotFoundError",
    "PermissionDeniedError",
]
