# 统一视图判定模型（Unified View Judgment）Implementation Plan

> Status: APPROVED
> Source: .claude/artifacts/designs/unified-view-judgment.md
> Mode: default
> Iterations: 2 / 3
> Author: 用户
> Last updated: 2026-09-23

## Requirements summary

统一看板完成标志判定与筛选体系的判定模型：done_flag 由「done_field + done_value 精确匹配」两键升级为「done_field + done_op + done_value」三键，op 复用 `fieldOps.ts` 的类型化操作符表（含 `is_empty`/`is_not_empty`），使 text/date 字段可表达"非空即完成"。旧数据 done_op 缺省按 `=` 回退，零迁移。

## Acceptance criteria

- AC-1 看板完成标志选 text/date 字段时可选"不为空"，不填值；该字段非空的行判定为完成（删除线 + 置底 + 隐藏倒计时）。
- AC-2 旧数据（无 done_op）判定结果与重构前逐例一致——现有 kanbanBoard 单测不改断言全通过。
- AC-3 新增判定纯函数单测覆盖 text/select/multiselect/date/boolean ×（等值, is_empty, is_not_empty）≥ 15 用例全绿。
- AC-4 done_flag 暴露的 op 集合是 `getOpsForField(fieldType)` 返回的子集（op 名称逐一对齐筛选契约，无自造 op）。
- AC-5 `pnpm check`、`pnpm test:coverage`、`pnpm build`、`pnpm bundle:budget` 全绿。

## RALPLAN-DR

### Principles

- 最小代码：不引入新抽象层，判定函数落在 fieldOps.ts 与 kanbanBoard.ts 现有职责边界内。
- 外科手术式改动：只动 spec In scope 的 4 个文件 + 测试，不碰日历/甘特/WBS。
- 契约单一来源：op 名称与语义只从 `FIELD_OPS_BY_TYPE` 取，done_flag 不自造第二张操作符表。
- 向后兼容优先：无 done_op 即 `=`，旧行为零变化（AC-2 是硬门禁）。

### Decision drivers

- 兼容风险（既有视图 view_options 已在线上数据中存在 done_value）
- 契约一致性（后端 filters API 是 op 语义的最终执行者）
- 改动面收敛（本轮不做日历/甘特条件化，方案 C 留口）

### Viable options

**Option A：done_op 独立三键（chosen）**
- 实现思路：view_options 增加 `done_op` 键（缺省 `=`）；DoneFlagFields 增加 op 下拉；isDoneRow 内部委托新的共享匹配纯函数。
- 改动文件：`frontend/src/pages/grid/cells/fieldOps.ts`、`frontend/src/pages/grid/views/DoneFlagFields.tsx`、`frontend/src/pages/grid/views/kanbanBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts` + 各测试。
- Pros：旧数据零迁移；后端 view_options 是 JSON 透传无需改；op 下拉与筛选 UI 语义天然对齐。
- Cons：DoneCtx 结构变更，kanbanBoard.ts 判定段需重写签名。

**Option B：语义复用 done_value 缺省即"非空"（无 done_op 键）**
- 实现思路：done_value === undefined/null 时按"非空"判定；配置值则等值。
- Pros：不加键，"零配置"更省一次点击。
- Cons：**被否决**——`value === undefined` 在现实现中是"未配置完成标志"的语义（kanbanBoard.ts:63 显式把 undefined/null 过滤为 null ctx），复用该哨兵会把"没配完"和"配了非空"两种状态合并，配置 UI 无法区分"用户故意选非空"和"选了字段还没填值"，且未来加"为空"判定无键可放。语义过载，不可回退成本低但歧义永久。

**Option C：done_flag 整体改存 FilterRule 结构（done_filter: {field_name, op, value}）**
- Pros：模型最统一，未来其他视图可复用同一存储形态。
- Cons：**本轮否决**——需要读旧键写新键的双写迁移逻辑，后端虽透传但公共 API 形态变化超出 spec In scope；收益仅在"未来更多视图复用"时兑现，符合三处相似原则前不做。留作 Follow-up。

### Implementation steps

1. **fieldOps.ts 新增共享判定纯函数** — `frontend/src/pages/grid/cells/fieldOps.ts`（`getOpsForField` L183 之后）：
   - 新增 `matchValueCondition(raw: unknown, op: string, value: unknown, fieldDef?: Pick<Field,'field_type'|'config'>): boolean`，内部按 field_type 分派 `=`/`is_empty`/`is_not_empty`（select 的 value/label 双匹配、multiselect 归一交集逻辑从 kanbanBoard.ts:84-113 迁入，is_empty 判空口径与 compareField L173 一致：null/undefined/''）。
   - 新增 `DONE_FLAG_OPS = ['=', 'is_empty', 'is_not_empty']` 常量（done_flag 允许的 op 子集，元素名必须存在于 FIELD_OPS_BY_TYPE 各类型组）。
2. **kanbanBoard.ts 判定段重构** — `frontend/src/pages/grid/views/kanbanBoard.ts`：
   - `DoneCtx`（L49-56）增加 `op: string` 字段。
   - `resolveDoneCtx`（L59-65）：读取 `opts.done_op`，缺省 `=`；op ∈ {is_empty, is_not_empty} 时**不再要求 value 非空**（L63 的 value 校验改为仅对需要值的 op 生效）。
   - `isDoneRow`（L75-114）：类型分派逻辑整体替换为 `matchValueCondition(raw, ctx.op, ctx.value, ctx.fieldDef)` 调用；`=` 分支行为与现实现逐例等价（AC-2）。
   - `buildDoneToggleValue`（L122-146）：`ctx.op` 为 is_empty/is_not_empty 时返回哨兵 `undefined` 表示"无确定 toggle 值"，调用方（KanbanView 完成勾选）据此隐藏该交互（spec Edge case：不可逆操作禁用）。
3. **DoneFlagFields.tsx 增加 op 下拉** — `frontend/src/pages/grid/views/DoneFlagFields.tsx`：
   - props 增加 `doneOp?: string`，onChange patch 增加 `done_op?: string`。
   - 选定字段后、值控件之前渲染操作符 Select：候选 = `getOpsForField(ft)` 过滤 `op ∈ DONE_FLAG_OPS`；切换 op 为 needValue===true（无值直通型）时 `onChange({ done_value: undefined })` 并隐藏值控件。
   - 切换字段时（handleFieldChange L28-34）重置 `done_op: undefined`（回退 `=`）并保留既有"boolean 默认 true"逻辑。
4. **viewOptionSchema.ts 提示更新** — `frontend/src/pages/grid/view-config/viewOptionSchema.ts` L103-105 done_field 项：tooltip 追加"文本/日期等字段可选『不为空』作为完成条件"；`resolveOpts`（L302-323）无需改——done_op 不在 schema 中定义、走"额外字段原样保留"分支。
5. **调用方接线** — `KanbanView.tsx`（及 ViewConfigDialog/CreateEditViewForm 中 DoneFlagFields 的挂载点）：传入/回写 `done_op`；完成勾选 onClick 处增加 `buildDoneToggleValue === undefined` 时禁用分支。
6. **测试**：
   - `frontend/src/pages/grid/cells/fieldOps.test.ts`：新增 matchValueCondition describe 块（AC-3 的 ≥15 用例参数表）。
   - `frontend/src/pages/grid/views/kanbanBoard.test.ts`：现有 isDoneRow/buildDoneToggleValue 断言不动（AC-2）；追加 is_empty/is_not_empty 分支用例与 toggle 哨兵用例。
   - `DoneFlagFields.test.tsx`（若存在则扩展）：op 切换清值、needValue 隐藏值控件。

### Workspace setup

- 实施前运行 `git status --short` 和 `git branch --show-current`。
- 若 working tree 干净且当前在 `main`/`master`/`release/*`，先询问用户是否建 worktree：`git worktree add -b codex/unified-view-judgment ../cndb-uvj`。
- 若 tree dirty，先与用户确认现有改动归属，不混入本 plan 改动。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| isDoneRow 重构引入行为回归 | AC-2 硬门禁：现有单测断言零修改；`=` 分支实现逐例对照 kanbanBoard.ts:80-113 旧逻辑迁移 |
| done_op 与后端 filters op 语义漂移 | AC-4：DONE_FLAG_OPS 逐项断言存在于 FIELD_OPS_BY_TYPE；不自造 op 名 |
| needValue 命名反直觉（true=无值直通） | matchValueCondition 实现处加中文注释点明，且以 fieldOps.ts:38 既有注释口径为准 |
| toggle 哨兵 undefined 与"未配置"混淆 | 哨兵仅存在于 buildDoneToggleValue 返回值（运行时），不落入 view_options 存储；调用方用 `=== undefined` 显式分支 |
| 旧视图 UI 不显示 op 下拉导致误读 | DoneFlagFields 对 doneOp 缺省渲染 `=` 选中态，保存时补写 done_op |

## Verification steps

- AC-1：`pnpm test -- kanbanBoard` 新增"date 字段 + is_not_empty"用例绿；本地 dev 起服务在示例工作区手工验证一次（可选）。
- AC-2：`pnpm test -- kanbanBoard fieldOps` 全绿且 `git diff` 中 kanbanBoard.test.ts 现有断言行无修改。
- AC-3：fieldOps.test.ts 新 describe 用例数 ≥ 15 且全绿。
- AC-4：fieldOps.test.ts 中断言 `DONE_FLAG_OPS.every(op => Object.values(FIELD_OPS_BY_TYPE).some(group => group.some(o => o.op === op)))` 为真。
- AC-5：`pnpm check` → `pnpm test:coverage` → `pnpm build` → `pnpm bundle:budget` 顺序全绿（Windows 下前端命令关闭沙箱执行）。

## ADR

- **Decision**：done_flag 升级为三键（done_field + done_op + done_value），op 从 FIELD_OPS_BY_TYPE 取子集 DONE_FLAG_OPS（`=`/is_empty/is_not_empty），缺省 `=`；前端判定收敛到 fieldOps.ts 的 matchValueCondition 纯函数。
- **Drivers**：向后兼容（done_op 缺省 = 等值，AC-2 可验证）；契约单一来源（不自造 op）；改动面收敛（4 文件 + 测试）。
- **Alternatives considered**：Option B（value 缺省即非空）rejected——哨兵语义过载、"未配置"与"非空"不可区分；Option C（done_filter 结构化存储）rejected——需双写迁移，超出 In scope，留 Follow-up。
- **Why chosen**：三键显式表达判定条件，零迁移、可回退（删 done_op 即回旧行为）、与筛选契约同名对齐，是满足全部 AC 的最小方案。
- **Consequences**：正向——text/date 完成标志能力补齐，判定逻辑单点化；负向——DoneCtx/组件 props 签名变更触及 KanbanView 接线，PR 内需一次过完；后端仍按透传处理，无服务端改动。
- **Follow-ups**：①方案 C（日历/甘特条件化字段映射）待新 spec；②若未来更多视图需要判定条件，考虑把 done 三键整体升格为 done_filter 结构化存储（Option C）。

## Review trail

- Planner draft v1：三键方案 A，matchCondition 三入口共享。
- Architect challenge v1：指出"三入口共享执行函数"不成立——筛选执行在后端，前端一致性只能靠 op 名称契约；另指出 resolveDoneCtx L63 的 value 校验必须按 op 分派，否则 is_not_empty 永远判不成立。
- Planner v2：matchValueCondition 仅服务 done_flag；AC-4 改为 op 名称契约对齐；step 2 显式修改 L63 校验逻辑。
- Critic verdict v2：APPROVED，1 条 reservation（见下）。
- Final iterations: 2 / 3

### Critic verdict v2

| 维度 | 状态 | 备注 |
|---|---|---|
| Principle consistency | ✓ | favored option 与四条 Principles 逐条对齐 |
| Alternative exploration | ✓ | Option B/C 各有实质 invalidation rationale，非陪跑 |
| Risk mitigation clarity | ✓ | 5 条 risk 均有可执行 mitigation |
| AC testability | ✓ | AC-1~5 均二值可验证 |
| Verification concreteness | ✓ | 命令 + 测试名 + 断言表达式 |
| File/line coverage | ✓ | 步骤 1-6 全部 cite 文件与行号 |

**Verdict: APPROVED**

### Reservations

- Implementation step 2：`buildDoneToggleValue` 返回哨兵 undefined 依赖调用方（KanbanView 完成勾选处）正确分支——plan 未 cite 该调用点的具体文件行号。实施时若发现调用方不止一处（如 KanbanCard 拖拽到完成列路径），须逐一接线并在 PR 中列出，不得漏改。
