"""pipeline 插件 —— 工作区质量检查流水线（ADR 0076）.

模块职责：
- 流水线定义：YAML DSL 原文 + 保存期编译出的 IR 快照（``services/dsl``）；
- 检查动作注册表：``域/动作`` 命名空间，数据表 / 文档内置检查（``services/checks``）；
- 执行器：手动触发、后台线程、单飞与结构化发现物落库（``services/runner``）；
- REST API：定义 CRUD / 编译校验 / 检查目录 / 运行与结果查询（``routers``）。
"""

from __future__ import annotations

__all__: list[str] = []
