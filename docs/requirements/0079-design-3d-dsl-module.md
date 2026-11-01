# 需求卡片：新增【设计】模块与结构 DSL（3D 机械制图实时预览与生成）

- 编号：0079（与 ADR `docs/adr/0079-design-3d-dsl-module.md` 同号）
- 来源 / 提出人：用户（2026-11-01 会话）
- 日期：2026-11-01
- 关联 ADR：`docs/adr/0079-design-3d-dsl-module.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请基于当前项目设计的架构，在数据表和文档同级，新增【设计】模块（在文档之后）。设计DSL专用语言，用于描述产品结构设计，能够支持典型3D机械制图的实时预览和生成。请制定开发计划。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「在数据表和文档同级，新增【设计】模块（在文档之后）」 | 工作区级新插件 `design`（与 tables / documents 同级），顶部工作区页签「设计」排布在「文档」之后；路由 `/w/:wid/design`；按工作区类型门控 | `src/cndb/plugins/design/`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/utils/workspaceType.ts` | `make flow` + 页签可见性单测 |
| C2 | 「设计DSL专用语言，用于描述产品结构设计」 | 自研文本 DSL（`.cnmd`）：参数（param）、模块复用（module）、图元（box/cyl/sphere/cone/torus/tube）、变换（translate/rotate/scale/mirror）、布尔运算（union/difference/intersection）、算术表达式；长度 mm、角度 deg | `src/cndb/plugins/design/services/dsl/` | 判定层单测（`tests/test_design_dsl.py`） |
| C3 | 「支持典型3D机械制图的实时预览」 | 编辑器（CodeMirror 6）+ 防抖实时编译端点（无落库）+ WebGL 3D 预览（three.js + 客户端 CSG 布尔求值）+ 结构化诊断（行/列）+ 参数面板实时改参重编译 | `frontend/src/pages/design/`、`design/routers/` | 前端单测 + e2e（`design-3d-preview.spec.ts`） |
| C4 | 「和生成」 | 从编译产物（IR）求值结果生成可下载产物：网格模型导出（STL / OBJ / GLB）与正交三视图（前 / 上 / 右）PNG；不承诺 STEP / DWG 等 BREP 交换格式 | `frontend/src/pages/design/` | 前端单测（导出行）+ e2e |
| C5 | 「请制定开发计划」 | ADR 0079 含 P0（DSL 引擎 + 数据模型）/ P1（API + 实时预览前端）/ P2（生成导出 + 备份 + 帮助与示例）分期、测试清单与风险 | `docs/adr/0079-design-3d-dsl-module.md` | ADR 评审通过（人工卡点） |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 插件架构（PluginBase + 自动发现注册） | `src/cndb/plugins/base.py`、`src/cndb/core/plugin_registry.py`、`src/cndb/app.py:138` | 新模块以插件接入，挂 `workspaces` 路由前缀 |
| 2 | 工作区页签与类型门控 | `frontend/src/layouts/MainLayout.tsx:241-276`、`frontend/src/utils/workspaceType.ts:44` | 新增 `design` feature key 与页签 |
| 3 | 文档模块范式（版本化 / 权限 / 编辑器） | `src/cndb/plugins/documents/models.py:67`、`frontend/src/pages/documents/` | 版本表、CodeMirror 6 既有依赖复用 |
| 4 | 流水线 DSL 编译快照范式（原文 + compiled IR） | `docs/adr/0076-pipeline-check-dsl.md`、`src/cndb/plugins/pipeline/` | DSL 载体与保存期编译口径对齐 |
| 5 | 工作区全量备份（当前 v10，含 pipelines） | `src/cndb/plugins/workspaces/services/workspace_backup.py:37` | 设计与版本需定备份口径（v11） |
| 6 | Chrome 81 兼容基线 + 前端体积预算 | `docs/adr/0026-chrome81-compat.md`、`docs/BUNDLE_BUDGET.md` | three.js 为新依赖，须 lazy chunk + 新基线 + 冒烟 |
| 7 | 权限判定与 403 文案 | `docs/adr/0047-permission-denied-message.md` | viewer 写入口径 |
| 8 | alembic 迁移链 | `src/cndb/alembic/versions/y3z4a5b6c7d8_add_pipeline_plugin.py:20` | 当前链头，新迁移挂其后 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 产物格式范围：STEP / DWG 等 BREP 交换格式是否必须？——本轮结论：v1 不做，仅网格格式（STL / OBJ / GLB）与三视图；如后续有 CAM / BREP 交换需求再立项。
- [x] DSL 是否要求离线服务端生成（如 CLI 批量导出）？——本轮结论：v1 生成在前端完成，后端零新依赖；服务端批量生成无现实需求，暂不建设。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
