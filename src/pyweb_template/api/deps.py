"""FastAPI 依赖注入工具函数.

集中放置 Depends() 可调用对象，避免散落在各路由文件。
"""

from __future__ import annotations

import uuid

from fastapi import Header


def get_request_id(x_request_id: str | None = Header(default=None)) -> str:
    """生成或透传请求 ID（链路追踪用）.

    若上游调用方已传入 X-Request-Id，则直接透传；否则生成一个新的 UUID。
    下游服务可通过依赖注入在任意位置拿到同一个 request_id。
    """
    if x_request_id:
        return x_request_id
    return uuid.uuid4().hex
