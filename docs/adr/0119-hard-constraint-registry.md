# ADR 0119: 硬约束台账与 AGENTS 硬约束管理

Status: Implemented（2026-11-07 评审通过，P0-P2 全部落地）
Date: 2026-11-07
Related: `AGENTS.md`、`.trae/rules/dev-workflow.md`、`.trae/rules/design.md`、`.trae/rules/testing.md`、`docs/AI_DRIVEN_DEV_FLOW.md`、`docs/adr/TEMPLATE.md`、`scripts/check_adr_landing.py`
需求卡片: `docs/requirements/0119-hard-constraint-registry.md`（需求原文与约束编号的唯一副本）

> 无需求卡片（需求直接立项）时，本行写「无卡片」，「口径」中逐字粘贴原句并就地编号 C1..Cn；补卡片时再迁回卡片。
>
> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | "完善项目的AGENTS设计" | AGENTS.md 新增「硬约束」节：口径定义 + 唯一编号源指向 `docs/CONSTRAINTS.md` + 冲突处理（从严 / 先改台账再写码）+ 变更流程（人工确认）；「开工前」清单第 2 步后加入台账必读（见 Decision §5） |
| C2 | "增加硬约束的管理" | 建立 `docs/CONSTRAINTS.md` 台账：四类来源全量收编去重，H1..Hn 全局流水编号，四列表格（# / 约束 / 校验 / 来源），删除留缺口 + 「已删除」清单（见 Decision §1-§2） |
| C3 | "配合ADR" | TEMPLATE.md 不变量节 + design.md / AGENTS.md 删除流程补「先迁移仍生效 H 条目」；`check_constraints.py` 校验来源 ADR 存在（见 Decision §3、§6） |
| C4 | "实现更好的LLM驱动项目开发" | `scripts/check_constraints.py` 并入 `check-docs` / `check-fast`；rules 与 AI_DRIVEN_DEV_FLOW 的重复禁令改为「一句话 + H#」引用（见 Decision §3-§5） |

无需求卡片时，首列改为 `C1..Cn`（编号就地定义，见上方降级口径）。

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 流程禁令三处副本：禁 `--no-verify` / prek 在 AGENTS.md、dev-workflow.md、AI_DRIVEN_DEV_FLOW.md §5 各出现一次，措辞不完全一致 | `AGENTS.md:16`、`.trae/rules/dev-workflow.md`（禁令节）、`docs/AI_DRIVEN_DEV_FLOW.md:114` | 改一处漏一处，LLM 换会话后以哪份为准不明确 | 确认 |
| 2 | 阶段硬约束无编号：需求有 C1..Cn、决策有 D1..Dn、ADR 不变量有 I1..In，但护栏类约束（覆盖率 95% 不注水、迁移幂等 + downgrade、测试同轮）无编号体系 | `.trae/rules/testing.md`、`.trae/rules/design.md` | 无法被 ADR / 代码注释 / 测试引用，也无法机器校验引用完整性 | 确认 |
| 3 | ADR 长期不变量随 ADR 生死：ADR 0004 的 I1/I3/I6 被 AI_DRIVEN_DEV_FLOW.md §5 引用，但本仓策略是 ADR 作废即**直接删除**（不留 Superseded） | `docs/AI_DRIVEN_DEV_FLOW.md:122`、`.trae/rules/design.md`（需求移除节） | ADR 删除后仍在生效的不变量失去权威载体，引用悬空 | 确认 |
| 4 | 机器门禁可复用：`check_adr_landing.py` 已有 Markdown 表格解析、多基准路径解析、error/warning 双级与退出码约定 | `scripts/check_adr_landing.py:52-78` | 新校验脚本可复用解析约定，独立成文件不混职责 | 确认 |
| 5 | 开工前必读清单未含约束台账（尚无此文件） | `AGENTS.md:33-38` | 需在清单中加入 `docs/CONSTRAINTS.md` | 确认 |
| 6 | CHANGELOG / CONTEXT.md 均为收编去重的同步改动面 | `CHANGELOG.md`、`CONTEXT.md` | 新术语「硬约束台账」须入 CONTEXT.md（Accepted 前） | 新增 |

**核心缺陷（需求要补的）**：硬约束没有唯一编号源——分散四处、重复表述、无编号可引、ADR 删除即失载体，LLM 无法在开工前单点对表。

设计目标（不变量）：

- **I1 唯一编号源**：任何硬约束的权威表述只在 `docs/CONSTRAINTS.md` 一处；台账外的表述只允许「一句话摘要 + H#」引用（口径：全仓 grep，禁令类完整表述不得出现在台账之外）
- **I2 机器可判定**：标注「机器」校验的 H 条目必须绑定真实存在的 `make` 目标或测试文件（口径：`make constraint-check`）
- **I3 生命周期闭环**：来源为 ADR 的 H 条目，其 ADR 文件必须存在；ADR 删除前先迁移仍在生效的条目（口径：`make constraint-check` + 删除流程）
- **I4 人工卡点**：H 条目的新增 / 修改 / 删除须人工确认，LLM 不得自行放宽（口径：评审记录 + 提交信息可追溯）

## Decision

以下小节按需增减；不适用的小节保留标题写「无」，便于横向对照（范式见 `0004-row-level-permission-rules.md`）。

### 1. 数据模型

无（纯文档 + 校验脚本；台账为 Markdown 表格，不进数据库、无 alembic 迁移）。

### 2. 台账结构（唯一编号源）

`docs/CONSTRAINTS.md` 固定结构，三段式：

1. **头部约定**（blockquote）：唯一编号源声明、变更规则（增删改须人工确认）、编号不复用、`make constraint-check` 提示；
2. **使用方式（LLM 必读）**：开工前对表（设计触碰任一 H# 先核对口径）、提交前自查（机器条目跑命令、人工条目在收工清单标注）、冲突处理；
3. **分组表** + **已删除清单**。

分组表四列，列头固定：

| 列 | 取值 | 说明 |
|---|---|---|
| `#` | `H1`..`Hn` | 全局流水编号，不复用；删除后留缺口 |
| `约束` | 一句可判定口径 | 违反即可打回的表述，不写实现细节 |
| `校验` | `make <target>` / 测试文件路径 / `人工:<卡点名>` | 机器与人工两类，机器条目命令须真实存在 |
| `来源` | `全局` / `ADR NNNN D#` / `ADR NNNN I#` | 全局项写「全局」，ADR 沉淀项写 ADR 编号 + D/I 编号 |

初始分组（可增不可随意重排）：流程与门禁 / 覆盖率与测试 / 数据与迁移 / 权限与安全 / 发布与部署。

「已删除清单」三列：`#`（缺口编号）/ 原因 / 日期；正文中不得再出现该编号的行。

### 3. 校验脚本（唯一判定入口）

新增 `scripts/check_constraints.py`，解析约定复用 `check_adr_landing.py` 的表格 / 路径解析方式：

| 检查项 | 级别 |
|---|---|
| `docs/CONSTRAINTS.md` 存在且含四列固定列头 | error |
| H 编号格式合法（`H\d+`）且全局唯一 | error |
| `来源` 含 `ADR NNNN` 的：`docs/adr/NNNN-*.md` 存在（防孤儿约束） | error |
| `校验` 含 `make <t>` 的：`<t>` 在 Makefile 目标中存在 | error |
| `已删除清单` 中的编号仍出现在正文分组表 | warning |
| 使用方式节缺失「开工前 / 提交前 / 冲突处理」任一关键词 | warning |

退出码：有 error 退出 1；`--strict` 下 warning 也失败（与 adr-check 一致）。

### 4. 门禁接入

| 位置 | 变更 |
|---|---|
| `Makefile` | 新增 `constraint-check` 目标（调 `scripts/check_constraints.py`）；`check-docs` 与 `check-fast` 的依赖链中加入（与 `adr-check` 并列） |

CI 不需要单独改动：`check-docs` / `check-fast` 已在双 CI 与 `make check` 的组成里，随目标依赖自动生效。

### 5. 收编与去重规则

- **权威长表述**只写台账；`AGENTS.md`、`.trae/rules/*`、`AI_DRIVEN_DEV_FLOW.md` 原有重复处保留「一句话 + H#」，保留行为叙述但不再各自维护完整口径（例：「禁止 `--no-verify`、禁止跳过 prek（H1）」）。
- 收编范围：AGENTS 禁令（`--no-verify` / prek / conventional commits / git config / force push / tag）、门禁分级 fail-safe（拿不准按 L2）、testing 规则（95% 不注水 / 同轮 / 分层 / e2e 硬门禁）、design 规则（先方案后代码 / 人工卡点 / ADR 直接删除不留 Superseded）、AI_DRIVEN_DEV_FLOW §5 全部护栏（权限 I1/I3/I6、backup_io 收编、规则变更清缓存、部署串行回滚、bundle budget +5%）、迁移三性（幂等 / downgrade / 存量零迁移）。
- AGENTS.md 新增「硬约束」节（C1），「开工前」清单加入台账必读；「收工前」自查表述对齐 H# 引用。
- P0 收编时逐条核对四源措辞，取最严口径入台账；冲突处以最严为准并记录于决策 D6。

### 6. 与 ADR 的联动

- `docs/adr/TEMPLATE.md`「设计目标（不变量）」节补一句：长期不变量（跨需求仍生效的 I 条目）须在 ADR `Proposed → Accepted` 前登记入台账，来源写 `ADR NNNN I#`。
- `.trae/rules/design.md` 与 `AGENTS.md`「需求移除 / 变更」节补：删除 ADR 前**先迁移仍在生效的 H 条目**（改来源或并入其他 H 条目），再删文件；`constraint-check` 拦截孤儿。
- 存量回填（P2）：ADR 0004 I1/I3/I6（权限不变量）、0025 只读守卫、0086 引用闭包等长期不变量登记入台账；一次性人工确认。

### 7. 测试清单

**判定层（单测）**（`tests/test_check_constraints.py`）：

- 合法台账样例通过（无 error / warning）
- 台账缺失 / 列头不完整 → error
- 编号重复、格式非法 → error
- 来源 ADR 不存在 → error
- `make` 目标不存在 → error
- 已删除清单编号仍出现在正文 → warning；`--strict` 下退出 1
- 临时目录 fixture 构造台账样例，不依赖真实仓库文件

**接口层**：`make check-docs` / `make check-fast` 集成回归（依赖链含 `constraint-check`）。

**迁移 / 备份**：无。

**e2e（前端）**：无。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 台账建立 + 四源收编去重（约 20-30 条）+ AGENTS「硬约束」节 / 开工前清单 + rules 与 AI_DRIVEN_DEFLOW 引用改造（纯文档，L0） | 低 |
| **P1** | `scripts/check_constraints.py` + Makefile 接入 `check-docs` / `check-fast` + 判定层单测 | 低 |
| **P2** | TEMPLATE.md 不变量登记约定 + design.md / AGENTS.md 删除流程补迁移步骤 + 存量 ADR 长期不变量回填台账（人工确认） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 台账载体 | `docs/CONSTRAINTS.md`（用户拍板 2026-11-07） | 与 docs 门禁体系同处，ADR / rules 引用路径一致，`check-docs` 天然覆盖 | `.trae/rules/`（自动常驻 LLM 上下文，但与文档门禁体系割裂，且 rules 目录语义是阶段行为约束）；两层「rules 索引 + docs 明细」（双处同步成本高，违背唯一编号源 I1） | `docs/CONSTRAINTS.md` |
| D2 | 收录口径 | 全量收编去重（用户拍板） | 消灭四源重复与漂移，LLM 单点对表 | 仅收 ADR 领域不变量（流程禁令继续双轨漂移，不解决核心缺陷） | `docs/CONSTRAINTS.md` |
| D3 | 编号体系 | `H1..Hn` 全局流水、不复用、删除留缺口 | 与 ADR 编号文化一致（缺口合法、不复用） | 按域前缀（`PERM-1` 等，跨域移动需改号，引用不稳定） | 全仓引用处 |
| D4 | 机器校验载体 | 新增独立脚本 `check_constraints.py`，并入 `check-docs` + `check-fast` | 职责单一；文档级门禁即可拦截，秒级成本 | 并入 `check_adr_landing.py`（ADR 校验与约束校验职责混杂）；纯文档约定（无机器裁判，违背「门禁即裁判」原则） | `scripts/check_constraints.py`、`Makefile` |
| D5 | 变更流程 | H 条目增删改须人工确认，LLM 不得自行放宽 | 硬约束本质是护栏；放宽即口径变更，视同 S2 | 允许 LLM 自行登记 / 放宽（护栏失去意义，与「人工卡点」原则冲突） | `AGENTS.md`「硬约束」节 |
| D6 | 冲突处理 | 两条约束冲突从严执行；约束与 ADR 口径冲突先改 ADR + 台账再写码 | 与门禁分级 fail-safe（拿不准按 L2）一致 | 以最新文档为准（时间序不可靠，漂移源头） | `AGENTS.md`「硬约束」节、`docs/CONSTRAINTS.md` 使用方式节 |
| D7 | ADR 删除联动 | 删除 ADR 前先迁移仍在生效的 H 条目；脚本校验来源 ADR 存在 | 兑现「ADR 直接删除不留 Superseded」策略下长期不变量不失载体（I3） | 保留 Superseded / Deprecated 文档承载旧不变量（违反本仓既定删除策略） | `docs/adr/TEMPLATE.md`、`.trae/rules/design.md` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：硬约束单点可引用（H#）、机器可校验、LLM 换会话开工前单点对表；ADR 删除不再丢失长期不变量；四源去重后改一处生效；「门禁即裁判」延伸到约束层。
- **负向**：新增一条门禁链（`constraint-check`，秒级）；约束变更多一道人工确认；P0 一次性整理约 20-30 条需逐条核对四源措辞。
- **风险与缓解**：台账与原文漂移 → 台账外只允许「一句话 + H#」，`constraint-check` 拦孤儿引用；LLM 上下文成本 → 台账控制在约 60 行表格，不进 `.trae/rules` 常驻上下文（D1）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 硬约束编号 | `docs/CONSTRAINTS.md` | 唯一编号源，ADR / rules / AGENTS 引用 H# | ADR 0119 |
| ADR 生命周期 | `docs/adr/` + `.trae/rules/design.md` | 删除前迁移仍生效 H 条目，脚本拦截孤儿 | ADR 0119 |
| 权限不变量表述 | `docs/adr/0004` I1/I3/I6 | 长期不变量回填台账（来源标 ADR 0004 I#），ADR 正文仍是判定细节权威 | ADR 0119 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `docs/CONSTRAINTS.md`、`AGENTS.md`、`.trae/rules/design.md`、`.trae/rules/dev-workflow.md`、`.trae/rules/testing.md`、`docs/AI_DRIVEN_DEV_FLOW.md`、`CONTEXT.md` | `scripts/check_constraints.py` | f0525ff2 |
| P1 | 已落地 | `scripts/check_constraints.py`、`Makefile` | `tests/test_check_constraints.py` | f0525ff2 |
| P2 | 已落地 | `docs/adr/TEMPLATE.md`、`.trae/rules/design.md`、`AGENTS.md` | `scripts/check_constraints.py` | f0525ff2 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地（2026-11-07 用户评审通过后实现）
- 已完成：台账 H1..H25（H1..H23 收编四源，H24 为设计系统选中态对比度、H25 为 GitHub 式 1px 线条硬约束）；`make constraint-check` 并入 `check-docs` / `check-fast`；TEMPLATE.md 与删除流程联动；CONTEXT.md 术语「硬约束台账」
- 下一步：无（后续新增长期不变量按 TEMPLATE.md 约定随 ADR 登记；H 条目变更走人工确认）
- 已知坑：台账列头须与 `check_constraints.py` 严格一致（单测锁定）；`校验` 列只识别 `make <t>` 形态的机器命令，脚本 / workflow 路径不做存在性校验
- 最近一次全绿：`make flow` @ 本提交（2026-11-07）
