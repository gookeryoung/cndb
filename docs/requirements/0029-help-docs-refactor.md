# 需求卡片：帮助功能重构为独立「帮助文档」

- 编号：0029（与 ADR `docs/adr/0029-help-docs-refactor.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0029-help-docs-refactor.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对帮助功能制定重构计划。1.名称改为帮助文档。2.设置独立路由进入，而不是弹出DRAWER。3.采用两级侧边栏导航。4.按照快速入门、教程&最佳实践、典型示例、系统配置、问题排查等部分进行组织。5.典型示例请融入MAKE SEED对应的示例，后续将移除MAKE SEED的内容，仅保留帮助中的示例。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 名称改为帮助文档 | 所有用户可见文案（页面标题、顶栏入口、移动端菜单、文档元信息）与标题常量统一为「帮助文档」；前端源码中不再出现面向用户的「帮助中心」 | `frontend/src/pages/help/`、`frontend/src/layouts/MainLayout.tsx` | 单测断言标题常量与入口文案；前端源码检索「帮助中心」为零（历史 CHANGELOG / ADR 引用不计） |
| C2 | 设置独立路由进入，而不是弹出DRAWER | 新增登录后可访问的整页路由 `/help`（含主题深链），入口按钮改为路由跳转；删除 `HelpCenterDrawer` 组件、`helpOpen` 状态与抽屉渲染 | `frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/components/HelpCenterDrawer.tsx` | 路由/主布局单测：点击入口 URL 变为 `/help` 且无 Drawer |
| C3 | 采用两级侧边栏导航 | 一级为部分（可折叠分组），二级为具体主题；当前主题由 URL 驱动、可深链、可前进后退；窄屏下侧栏收为抽屉 | `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/HelpDocsPage.tsx` | 单测：分组/主题选中态与 URL 同步；e2e：深链与返回 |
| C4 | 按照快速入门、教程&最佳实践、典型示例、系统配置、问题排查等部分进行组织 | 导航一级固定且顺序为：快速入门、教程&最佳实践、典型示例、系统配置、问题排查；每个部分至少 1 个主题；现有 6 个主题内容全部有归属（无孤儿内容） | `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/content/` | 单测：一级 key/标题/顺序断言，主题归属映射完整 |
| C5 | 典型示例请融入MAKE SEED对应的示例，后续将移除MAKE SEED的内容，仅保留帮助中的示例 | 典型示例内容取自 `examples/datasets` 对应的三套演示场景，但帮助的读取路径不得依赖 seed 命令、演示账号或数据库中的演示工作区；seed 本期保留不动，移除另立需求 | `src/cndb/plugins/help/`、`frontend/src/pages/help/` | 接口测试：无 seed 库也能返回清单与文件；代码检查：help 不 import seed 模块 |
| C6 | （需求澄清）典型示例形态 | 每个示例提供：场景说明、数据表与字段要点、推荐视图/分析、导入步骤、CSV 下载链接；本期不做一键导入工作区 | `src/cndb/plugins/help/`、`frontend/src/pages/help/` | 接口测试：清单字段完整、下载 200；组件测试：下载链接可点击 |
| C7 | （需求澄清）帮助路由访问范围 | `/help` 注册在 `ProtectedRoute` 内，仅登录用户可访问；示例接口同样要求登录 | `frontend/src/App.tsx`、`src/cndb/plugins/help/routers/examples.py` | 路由单测；接口 401 用例 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 帮助内容以抽屉承载，宽度 620，桌面左菜单 / 移动胶囊 | `frontend/src/components/HelpCenterDrawer.tsx:32` | 需改为整页两级侧栏 |
| 2 | 桌面顶栏「帮助」按钮与移动端用户菜单入口 | `frontend/src/layouts/MainLayout.tsx:453`、`:302` | 改为路由跳转 |
| 3 | 扁平 6 主题内容与标题常量 | `frontend/src/components/helpContent.tsx:234`、`:244` | 需按 5 部分重组并更名 |
| 4 | SPA 路由表无 `/help`，未知路径统一回 `/w` | `frontend/src/App.tsx:79`、`:136` | 新增路由，避免被兜底重定向 |
| 5 | MainLayout 侧栏渲染规则（管理台隐藏侧栏） | `frontend/src/layouts/MainLayout.tsx:319`、`:489` | `/help` 需同款整幅内容区 |
| 6 | 抽屉与内容测试 | `frontend/src/components/HelpCenterDrawer.test.tsx`、`helpContent.test.tsx`、`MainLayout.test.tsx:34` | 测试需重写/迁移 |
| 7 | seed 演示数据与服务 | `src/cndb/cli/seed/runner.py:22`、`datasets.py:145` | 本期不改，仅解耦 |
| 8 | datasets 已随 wheel 打包为 `cndb/datasets` | `pyproject.toml:84`、`src/cndb/cli/seed/paths.py:12` | 可作为帮助示例资产源 |
| 9 | 新手引导重放入口在抽屉底部 | `frontend/src/components/HelpCenterDrawer.tsx:50` | 迁到帮助文档页 |
| 10 | `HelpTip` 行内问号提示 | `frontend/src/components/HelpTip.tsx` | 排除：与帮助中心无耦合，保持不动 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- 无。已确认：典型示例采用「图文说明 + CSV 下载」；帮助路由仅登录用户；seed 本期只解耦、移除另开一期。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
