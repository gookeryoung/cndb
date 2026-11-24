# 需求卡片：大表 DDL 影响预估（dry-run）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0150（规划卡 `0141` 的 P2 项；**S2**）
- 来源 / 提出人：用户（会话 2026-11-24，「继续」）
- 日期：2026-11-24
- 关联 ADR：`docs/adr/0150-ddl-impact-estimate.md`

## 需求原句（逐字）

> 继续

对应 `docs/requirements/0141-table-robustness-roadmap.md` P2 表项：「大表 DDL dry-run（预估影响行数与耗时、超阈值强制 force）」。

## 可实施约束（C1..C7）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「预估影响行数」 | `GET /{wid}/tables/{tid}/ddl-impact` 返回 `row_count`（该表总行数）与 `field_null_count`（改必填 / 唯一约束时的待补值行数） | `services/core/ddl_impact.py` | 单测：行数 / 空值行数正确 |
| C2 | 「预估耗时」 | 用**抽样实测**推算：对 `sample`（默认 200，上限 1000）行计时读 + 目标类型转换，按 `per_row_ms × row_count × 动作系数` 给出 `estimated_ms`（系数：改类型 3 / 加字段 1.2 / 加索引 2.0），并返回 `sampled_rows` 与 `sample_ms` 便于判断可信度 | 同上 | 单测：空表 0ms、行数与估算随数据量增长、抽样上限生效 |
| C3 | 「动作」 | 支持 `change_type`（需 `field_id` + `field_type`）/ `add_field`（需 `field_type`）/ `add_index`；未知动作 / 缺参数 → 400 | 同上、`routers/fields.py` | 单测：三类动作 + 三类非法入参 |
| C4 | 「超阈值强制 force」 | `DDL_IMPACT_FORCE_THRESHOLD_ROWS`（默认 **0 = 关闭**）：开启后，改类型时若 `row_count > 阈值` 且请求未带 `force=true` → 400，文案含行数与预估耗时 | `routers/fields.py`、`core/config.py` | 接口测试：关闭时不受影响 / 开启且超阈值 400 / 带 force 通过 |
| C5 | 「兼容」 | 默认关闭（阈值 0）⇒ 现有行为逐条不变；不改前端调用也能跑 | 全仓 | 存量用例全绿 |
| C6 | 「只读」 | dry-run 端点不写库、不改元数据；抽样只读 `LIMIT` | 同上 | 单测：调用前后行数与字段不变 |
| C7 | （前端） | 字段管理的「切换类型」确认弹窗展示预估（行数 / 预计耗时 / 是否需 force）列为后续；本期交付后端能力 | — | 记入 ADR「已知限制」 |

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 字段更新（改类型 / 改必填 / 改唯一） | `routers/fields.py::update_field` | 超阈值时拦截 |
| 2 | 字段类型 DDL | `ddl.rebuild_column`（ADR 0038 原子回退） | 耗时主要在整列重写 |
| 3 | 配置 | `core/config.py` | 新增阈值配置 |

## 未决问题

- [x] ① 预估方法：抽样实测 + 动作系数（不引入新依赖，也不假装精确到秒）。
- [x] ② 默认是否强制：**默认关闭**（阈值 0），避免突然改变既有升级路径；需要时用环境变量开启。
- [x] ③ 前端展示：本期不做。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论
