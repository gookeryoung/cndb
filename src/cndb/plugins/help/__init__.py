"""帮助文档插件 —— 典型示例、CSV 下载与图示例（ADR 0029 / 0030）.

示例资产来自随包发布的 `cndb/datasets`（源码开发版为仓库根 `examples/datasets`），
与 `cndb seed` 完全解耦：本插件不 import seed、不查询数据库、不假设演示工作区存在。

图示例同样不落库：SVG 由后端按「构建代码 + 真实数据源」生成，快照在
`CACHE_DIR/help-figures`，请求期按指纹即时重建、后台按周期全量重建。
"""

from __future__ import annotations

__all__: list[str] = []
