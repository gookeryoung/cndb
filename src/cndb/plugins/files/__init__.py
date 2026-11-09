"""附件归属数据层（**不是插件**）.

本包只提供 ``FileOwner`` 模型与归属 / 访问校验服务，供 documents、tables、workspaces 等插件引用；
按设计没有 ``plugin.py``（无路由、无导航、无注册入口），插件发现会把它当作共享模块目录跳过。
未补 ``plugin.py`` 时不要在此包下放路由，否则会绕过插件注册与权限边界。
"""

from __future__ import annotations

from .models import FileOwner

__all__ = ["FileOwner"]
