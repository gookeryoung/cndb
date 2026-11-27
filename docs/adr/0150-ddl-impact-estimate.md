# ADR 0150: 大表 DDL 影响预估（抽样估算 + 可选强制确认）

Status: Accepted（2026-11-24 需求方指示「继续」实施，范围沿用已评审的路线图 0141 P2）
Date: 2026-11-24
Related: `src/cndb/plugins/tables/services/core/ddl_impact.py`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/core/config.py`、`src/cndb/plugins/tables/services/core/ddl.py`
需求卡片: `docs/requirements/0150-ddl-dry-run.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「预估影响行数」 | `GET /{wid}/tables/{tid}/fields/ddl-impact` 返回 `row_count` + `field_null_count`（改必填时的待补值行数） |
| C2 | 「预估耗时」 | 抽样实测（默认 200，上限 1000）：读一行 + 按目标类型转换，得到 `per_row_ms`；`estimated_ms = per_row_ms × row_count × 动作系数`（改类型 3.0 / 加字段 1.2 / 加索引 2.0），同时回 `sampled_rows` / `sample_ms` / `factor` 供判断可信度 |
| C3 | 「动作」 | `change_type` / `add_field` / `add_index`；未知动作、缺字段、缺目标类型、未知类型 → 400 |
| C4 | 「超阈值强制 force」 | `DDL_IMPACT_FORCE_THRESHOLD_ROWS`（默认 0 = 关闭）；开启后 `PATCH /fields/{id}` 改类型且 `row_count > 阈值` 且未带 `force=true` → 400，文案含行数与预计秒数 |
| C5 | 「兼容」 | 默认阈值 0 → 行为与改造前逐条一致（存量用例全绿验证） |
| C6 | 「只读」 | dry-run 端点只做 `COUNT` + `LIMIT` 抽样，不写库、不改元数据 |
| C7 | （前端） | 字段管理「切换类型」确认弹窗展示预估列为后续 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 字段改类型在 SQLite 上会重建整列（读全表 → 转换 → 写新列 → 换名 → 建索引） | `ddl.rebuild_column`、ADR 0038 | 百万行表可能几十秒到几分钟，界面无任何提示 | 新增 C1/C2 |
| 2 | 失败有原子回退（ADR 0038 I1） | `routers/fields.py` | 不会留半成品，但耗时与中断体验仍在 | 确认（不重复实现回滚） |
| 3 | 无任何"影响面提示"入口 | — | 用户点保存后只能干等 | 新增 C1 |
| 4 | 配置体系已有同类阈值（导出上限 / 保留期） | `core/config.py` | 阈值放配置，默认关闭最安全 | 确认 C4/C5 |

**核心缺陷（需求要补的）**：DDL 的"代价"对用户完全不可见 —— 既不知道影响多少行，也不知道要等多久，更没有任何"确认一下"的卡点。

设计目标（不变量）：

- **I1 预估只读**：预估路径不写库、不改元数据、不触发 DDL。
- **I2 默认不改变行为**：阈值 0 时与改造前逐条一致（不引入隐式强制确认）。
- **I3 估算可解释**：返回抽样量、抽样耗时、动作系数，用户能判断估算是否可信；不承诺精确秒数。

## Decision

### 1. 数据模型

无（纯计算 + 配置项 `DDL_IMPACT_FORCE_THRESHOLD_ROWS`）。

### 2. 判定算法（唯一入口）

| 入口 | 语义 |
|---|---|
| `estimate_ddl_impact(db, table, action=, field=, target_type=, sample=)` | 唯一估算入口：行数 + 空值行数 + 抽样耗时 → 预计耗时与 `force_required` |
| `ACTION_FACTORS` | 动作系数常量（改类型 3.0 / 加字段 1.2 / 加索引 2.0），集中维护 |

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/fields/ddl-impact` | **新增**：`action` / `field_id` / `field_type` / `sample`，要求 `EDIT_SCHEMA` |
| `PATCH /{wid}/tables/{tid}/fields/{field_id}` | 新增可选 `force` 查询参数；阈值开启且超限时 400 |

### 4. 边界与例外

1. 空表：`row_count = 0`、`estimated_ms = 0`（不抽样）。
2. 虚拟字段作 `field`（lookup / formula）：`field_null_count` 返回 `null`（无物理列），估算仍可按行数给出。
3. 抽样里目标类型转换失败的单元格只影响计时，不影响预估成功（真 DDL 会走默认值或中断）。
4. 阈值判定只看行数，不看耗时（行数是稳定量，耗时是估算量）。
5. `force=true` 只跳过本阈值检查，不跳过必填 / 唯一的数据预检与原子回退。

### 5. 迁移

无（无表结构变更、无数据回填）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 本期 | 无 | 只交付接口；字段管理「切换类型」弹窗展示预估与 `force` 确认列为后续（C7） |

### 7. 测试清单

**判定层**：三类动作形状、空表 0 估算、抽样上限、字段空值行数、四类非法入参、只读（行数与字段类型不变）。

**接口层**：端点 200 形状、非法动作 400、未知字段 404；阈值默认关闭不拦截、开启后超阈值 400（文案含行数与 `force=true`）、带 `force=true` 通过。

**迁移 / 备份**：无变更（存量用例全绿）。

**前端**：本期无。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 估算服务 + 只读端点 | 低 |
| **P1** | 阈值配置 + `force` 拦截 | 中（触及字段更新路径，默认关闭以保兼容） |
| **P2** | 前端预估值展示与确认弹窗（**未开始**） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 估算方法 | **抽样实测 × 动作系数** | 不引依赖、量级正确；返回抽样细节让用户判断 | 纯常量估算法（不反映机器与数据形态）；实测全表（估算本身就要跑几十秒） | `estimate_ddl_impact` |
| D2 | 是否默认强制 | **默认关闭（阈值 0）** | 避免突然改变既有升级路径；前端尚未展示预估 | 默认开启（老前端会突然被 400 拦住） | `config.DDL_IMPACT_FORCE_THRESHOLD_ROWS` |
| D3 | 阈值判定依据 | **只看行数** | 行数稳定可预期，耗时是估算 | 按估算耗时判定（估算误差会让拦截不稳定） | `estimate_ddl_impact` |
| D4 | 抽样上限 | **1000 行** | 估算精度与只读成本折中；返回实际抽样量 | 无上限（大表上估算本身变慢） | `MAX_SAMPLE` |

门禁：`Proposed → Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：DDL 代价可见（行数 / 空值行数 / 预计耗时）；需要时可用环境变量开启强制确认，避免误点重建百万行表。
- **负向**：估算本身要读最多 1000 行（有界）；动作系数是经验值，跨机器会有偏差（已在返回里暴露抽样细节）。
- **风险与缓解**：系数偏小导致低估 → 用户只当"参考"；偏大导致过度拦截 → 阈值默认关闭，需要时才开。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| DDL 原子回退 | `ddl.rebuild_column` | 估算不改变回退语义；`force` 只跳过阈值检查 | ADR 0038 |
| 导出上限 / 保留期 | `core/config.py` | 同类阈值放配置、默认关闭/保守 | ADR 0139 / 0148 |
| 字段规则 | `field_rules` | 改类型后的数据校验仍走既有预检（必填 / 唯一） | 需求 0146 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/ddl_impact.py`、`src/cndb/plugins/tables/routers/fields.py` | `tests/test_ddl_impact.py` | `8b28a317` |
| P1 | 已落地 | `src/cndb/plugins/tables/routers/fields.py`、`src/cndb/core/config.py` | `tests/test_ddl_impact.py` | `8b28a317` |
| P2 | 已落地 | `frontend/src/pages/fields/FieldManager/index.tsx`（改类型前调 ddl-impact 弹确认，force_required 时带 force 提交，预估失败不阻断）、`frontend/src/api/tables.ts`（fieldApi.ddlImpact） | `frontend/src/pages/fields/FieldManager/FieldManager.test.tsx`（预估请求参数 / 确认弹窗读数与抽样标注 / force 透传与不透传 / 预估失败回退提交 / 类型未变不取预估） | `9a287b7a` |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部已落地。
- 已完成：抽样估算服务、只读端点、阈值配置与 `force` 拦截；前端改类型前预估确认（影响行数 / 空值行数 / 预计耗时 + 抽样标注，`force_required` 时提示并带 `force` 提交，预估失败回退原路径）。
- 下一步：大表 DDL 走后台任务（当前仍是同步请求）——属独立事项，不在本 ADR 分期内；`DDL_IMPACT_FORCE_THRESHOLD_ROWS` 默认 0（关闭），要启用强制确认需在部署配置里显式打开（已知坑 ②）。
- 已知坑：
  - 动作系数是经验值，跨机器偏差明显；判断阈值应看行数（D3）。
  - 阈值默认 0：要让前端真正用起来，需在部署配置里打开 `DDL_IMPACT_FORCE_THRESHOLD_ROWS`；前端已按 `force_required` 分支实现，阈值关闭时永远不会走到强制确认分支（不报错，只少了那个卡点）。
- 最近一次全绿：`make flow` @ `8b28a317`（2026-11-24，P0-P1）；P2 前端用例 5 例 @ 2026-11-27（`FieldManager.test.tsx` 65 例全绿，含反向验证：去掉 `force` 透传 / 去掉预估失败回退分支均会被抓到）。
