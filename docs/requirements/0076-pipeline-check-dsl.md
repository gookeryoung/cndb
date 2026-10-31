# 需求卡片：流水线检查系统与专用 DSL

- 编号：0076（与 ADR `docs/adr/0076-pipeline-check-dsl.md` 同号）
- 来源 / 提出人：用户（2026-10-31）
- 日期：2026-10-31
- 关联 ADR：`docs/adr/0076-pipeline-check-dsl.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请参考GITHUB，设计一套流水线检查系统，制定专用DSL，用于数据表、文档内容的检测，并且为未来更多格式的检测支持预留功能。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | "请参考GITHUB" | 流水线模型参照 GitHub Actions 的工作流形态：声明式定义（name/on/jobs/steps）、`uses:` 复用动作、`if:` 条件表达式、`needs:` 作业依赖（DAG）、手动 / 事件 / 定时三类触发 | 新插件 `pipeline` | DSL 解析与 DAG 执行单测 |
| C2 | "设计一套流水线检查系统" | 完整系统闭环：定义存储（workflow）+ 执行引擎（后台运行、单飞、进度）+ 运行记录与结果（run / finding）+ REST API + 前端页面 | `pipeline` 插件、`frontend/src/pages/pipelines/` | 接口层测试 + 前端单测 + e2e |
| C3 | "制定专用DSL" | 专用声明式 DSL：YAML 子集文本入库，保存期完整编译校验（未知动作 / 非法参数即时拒绝）；`${{ }}` 白名单表达式子集（无 eval、无任意代码） | `pipeline/services/dsl/` | DSL 解析 / 表达式单测 |
| C4 | "用于数据表……的检测" | 内置数据表检查族 `table/*`：空值率、重复行、值域 / 类型符合度、数据陈旧（复用字段类型注册表与治理判重口径） | `pipeline/checks/table/` | 判定层单测 |
| C5 | "……文档内容的检测" | 内置文档检查族 `document/*`：引用失效（图表 / 数据表 / 附件引用）、图表块合法性与上限、外链可达性登记 | `pipeline/checks/document/` | 判定层单测 |
| C6 | "为未来更多格式的检测支持预留功能" | 扩展点是**检查动作注册表**：动作名 `域/动作` 命名空间 + 输入 schema；新格式（图表实例、附件、仪表盘等）只注册新动作，引擎零改动；对外提供只读检查目录 API | `pipeline/checks/registry` | 注册表单测 + 目录端点测试 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 治理任务（重复检测 / 清洗 / 合并） | `src/cndb/plugins/tables/services/governance/detect.py:44`、`governance/tasks.py:55` | 单点任务，非可编排流水线；判重归一化可复用 |
| 2 | 图表块校验（上限 / 非法块） | `src/cndb/plugins/documents/services/charts/inline.py:255` | 硬编码于保存 / 渲染路径，未形成可配置检查 |
| 3 | 导入期校验报告 | `src/cndb/plugins/tables/services/importing/importer.py:172` | 仅导入时刻生效，口径可参考但不复用为运行期检查 |
| 4 | 统一事件流 | `src/cndb/core/events.py:139` | 触发留痕载体（pipeline.run 事件） |
| 5 | 行级权限判定 | `src/cndb/plugins/tables/services/core/row_access.py` | 检查执行的数据读取口径需明确（工作区视角 vs 个人视角） |
| 6 | 数据源同步租约 / 单飞 | `src/cndb/plugins/datasource/services/runner.py:125` | 并发单飞范式参照 |
| 7 | 工作区全量备份 | `docs/adr/0075-workspace-full-backup.md` | workflow 是否随备份导出需定口径 |
| 8 | 工作区级功能页签 | `frontend/src/layouts/MainLayout.tsx` | 新页签「质量检查」入口 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

以下问题给出建议结论（合理默认），**待用户复核**；复核即 ADR 评审的一部分，复核前 ADR 保持 `Proposed`。

- [x] DSL 文本载体选 YAML 还是结构化表单 → 建议 YAML 文本（可读性 / 注释 / 与 GitHub Actions 形态一致；保存期编译为校验过的 IR）
- [x] 检查执行是否套行级权限 → 建议按工作区视角运行（不套个人行级权限），但 finding 只携带计数 / ID / 字段名，不携带字段值（防侧信道，对齐 ADR 0004 口径）
- [x] 是否包含自动修复 → 建议本期不做（只读检测；自动修复属独立动作类型，未来另行立项）
- [x] 触发方式范围 → P0 手动触发；P1 事件触发（文档保存 / 记录批量变更 / 同步完成）；P2 定时触发（cron tick，参照 `cndb sync tick` 范式）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（已给建议默认，待人工复核）
