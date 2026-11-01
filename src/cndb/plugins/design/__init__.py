"""design 插件 —— 【设计】模块：结构 DSL 与 3D 机械制图（ADR 0079）.

模块职责：

- ``models.py``：``design_design`` / ``design_designversion`` 两表；
- ``services/dsl/``：结构 DSL（``.cnmd``）→ 校验过的 IR（唯一真相源为原文）；
- ``routers/``：定义 CRUD / 即时编译预览 / 版本查询（P1 起挂载）。

判定唯一入口：``services/dsl/compile.py::compile_design``（I1，D3）。
"""
