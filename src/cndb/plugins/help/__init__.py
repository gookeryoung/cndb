"""帮助文档插件 —— 典型示例清单与 CSV 下载（ADR 0029）.

示例资产来自随包发布的 `cndb/datasets`（源码开发版为仓库根 `examples/datasets`），
与 `cndb seed` 完全解耦：本插件不 import seed、不查询数据库、不假设演示工作区存在。
"""

from __future__ import annotations

__all__: list[str] = []
