"""插件基类定义.

继承自 endo 的通用 PluginBase 抽象（见 endo.plugins.base），
为 pyweb-template 所有插件提供统一接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter


@dataclass
class NavItem:
    """侧边栏导航菜单项."""

    key: str
    label: str
    icon: str = ""
    path: str = ""
    children: list[NavItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好的字典结构."""
        result: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "icon": self.icon,
            "path": self.path,
        }
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


@dataclass
class AppItem:
    """APP 功能模块入口（通过应用中心访问，不在侧边栏）.

    用于将工具型/分析型功能模块以可扩展的 APP 形式暴露。
    """

    key: str
    label: str
    description: str = ""
    icon: str = "AppstoreOutlined"
    path: str = ""
    category: str = "tool"  # tool / analysis / integration

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好的字典结构."""
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "path": self.path,
            "category": self.category,
        }


class PluginBase(ABC):
    """插件抽象基类，所有功能模块必须继承此类.

    子类需定义：
    - name / description / version / icon 等类属性
    - register_routes() 抽象方法（必选）
    - register_models() / register_navigation() / register_apps() 可选覆写
    """

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    icon: str = "AppstoreOutlined"

    @abstractmethod
    def register_routes(self, router: APIRouter) -> None:
        """注册 API 路由到给定的 router.

        每个插件的路由会被挂到 `/api/v1/<plugin_name>/...` 前缀下。
        """

    # B027: ABC 钩子，允许空实现（与 endo 项目约定一致）
    def register_models(self) -> None:  # noqa: B027
        """注册数据模型（可选覆写，导入模型类确保被 SQLAlchemy 发现）."""

    def register_navigation(self) -> list[NavItem]:
        """返回该插件的侧边栏导航菜单项（可选）."""
        return []

    def register_apps(self) -> list[AppItem]:
        """返回该插件的 APP 功能模块入口（可选）."""
        return []

    def get_info(self) -> dict[str, str]:
        """获取插件元信息（供 /api/plugins 端点返回）."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "icon": self.icon,
        }
