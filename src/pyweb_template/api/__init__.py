"""FastAPI 依赖注入包.

集中定义 Depends() 里用到的可调用对象，避免散落在各路由文件里。
"""

from __future__ import annotations

from pyweb_template.api.deps import get_request_id

__all__ = ["get_request_id"]
