# 需求卡片：硬约束台账与 AGENTS 硬约束管理

- 编号：0119（与 ADR `docs/adr/0119-hard-constraint-registry.md` 同号）
- 来源 / 提出人：用户（2026-11-07 会话）
- 日期：2026-11-07
- 关联 ADR：[docs/adr/0119-hard-constraint-registry.md](../adr/0119-hard-constraint-registry.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请完善项目的AGENTS设计，增加硬约束的管理，配合ADR实现更好的LLM驱动项目开发

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | "完善项目的AGENTS设计" | [AGENTS.md](../../AGENTS.md) 新增「硬约束」节（与门禁分级 / 方案分级并列）：定义硬约束口径（违反即打回）、指向唯一编号源 `docs/CONSTRAINTS.md`、冲突处理（两条约束冲突从严；约束与 ADR 口径冲突先改 ADR + 台账再写码）、变更流程（H 条目增删改须人工确认，LLM 不得自行放宽）；「开工前」必读清单加入台账 | `AGENTS.md` | `make check-docs` + 人工评审 |
| C2 | "增加硬约束的管理" | 建立台账 `docs/CONSTRAINTS.md`：全量收编四类来源（AGENTS 禁令 / `.trae/rules/agent.md` 执行卡 / [AI_DRIVEN_DEV_FLOW.md](../AI_DRIVEN_DEV_FLOW.md) §5 护栏 / ADR 长期不变量如 0004 I1/I3/I6）并去重；统一编号 H1..Hn（全局流水、不复用、删除留缺口）；每条标注「校验」（机器命令 / 人工卡点）与「来源」（全局 / `ADR NNNN D#/I#`） | `docs/` | `make constraint-check` |
| C3 | "配合ADR" | ADR 生命周期联动：[TEMPLATE.md](../adr/TEMPLATE.md)「设计目标（不变量）」节约定长期不变量在 ADR Accepted 前登记入台账；ADR 删除流程（design.md / AGENTS.md「需求移除 / 变更」）补「先迁移仍在生效的 H 条目再删文件」；脚本校验来源 ADR 文件存在（防孤儿约束） | `docs/adr/`、`.trae/rules/agent.md` | `make constraint-check` |
| C4 | "实现更好的LLM驱动项目开发" | 机器门禁与上下文收敛：新增 `scripts/check_constraints.py`（格式 / 编号唯一 / 来源 ADR 存在 / 机器命令在 Makefile 存在）并入 `check-docs` 与 `check-fast`；`.trae/rules/agent.md` 与 AI_DRIVEN_DEV_FLOW 的重复禁令改为「一句话 + H#」引用，不再各自维护副本 | `scripts/`、`Makefile`、`.trae/rules/` | `tests/test_check_constraints.py` + `make check-fast` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 流程禁令（禁 `--no-verify`、conventional commits 等）多处重复表述 | `AGENTS.md`、`.trae/rules/agent.md`、`docs/AI_DRIVEN_DEV_FLOW.md` §5 | 同一约束三处副本，改一处漏一处 |
| 2 | 阶段硬约束（覆盖率 95% 不注水、迁移幂等、测试同轮） | `.trae/rules/{testing,design,dev-workflow}.md` | 无编号，无法被 ADR / 测试 / 注释引用 |
| 3 | 项目特定护栏（权限不变量 I1/I3/I6、backup_io 收编、部署串行） | `docs/AI_DRIVEN_DEV_FLOW.md` §5、`docs/adr/0004-*.md` | ADR 按策略直接删除（不留 Superseded）后长期不变量失去载体 |
| 4 | 机器门禁基础（表格解析、路径解析、退出码约定） | `scripts/check_adr_landing.py`、`Makefile` | 可复用解析约定，新脚本独立成文件 |
| 5 | 开工前必读清单 | `AGENTS.md`「开工前」 | 需加入 `docs/CONSTRAINTS.md` |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 台账载体：`docs/CONSTRAINTS.md`（用户拍板，2026-11-07）
- [x] 机器校验强度：新增 `check_constraints.py` 并入 `check-docs` / `check-fast`（用户拍板）
- [x] 收录口径：全量收编去重（用户拍板）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
