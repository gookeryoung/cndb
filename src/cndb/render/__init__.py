"""跨插件渲染能力（无领域语义）.

这里只放「把一份结构化文档渲染成文件」的通用能力，不放任何领域规则：

- 谁产生内容（文档正文 / 数据字典 / 报表）由各自的插件决定；
- 谁提供渲染实现（docx / pdf）由具备该能力的插件在启动时注册（见
  :mod:`cndb.render.markdown_export`）。

依赖方向固定为「插件 → render」，render **不得** import 任何 `cndb.plugins.*`
（H69 单向无环）。因此渲染实现本身留在原插件内，通过注册表暴露 —— 而不是把
渲染代码搬到 core，那样会把「图表内联」「数据表引用」这些领域依赖一起拖进来。
"""

from __future__ import annotations

__all__: list[str] = []
