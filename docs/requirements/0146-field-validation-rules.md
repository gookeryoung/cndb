# 需求卡片：领域校验规则增强（模式匹配 + 条件必填）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0146（规划卡 `0141` 的 P2 项；S1）
- 来源 / 提出人：用户（会话 2026-11-24，「P1+P2」）
- 日期：2026-11-24
- 关联 ADR：无独立 ADR（S1）

## 需求原句（逐字）

> P1+P2

对应 `docs/requirements/0141-table-robustness-roadmap.md` P2 表项：「校验规则增强（条件必填 / 正则）」。

## 可实施约束（C1..C7）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「正则」 | 字段 `config.validation.pattern`（正则字符串）+ 可选 `message`：值非空且不匹配 → 400，文案优先用自定义 `message` | `field_types` config、`services/core/field_rules.py` | 单测：匹配通过 / 不匹配报错 / 自定义文案 |
| C2 | 「条件必填」 | 字段 `config.required_when = {field, op, value}`：当另一个字段的值满足条件时本字段必填；条件字段为空时不触发 | 同上 | 单测：条件命中未填 → 400；未命中可空 |
| C3 | 「写路径统一」 | 直编（create / update）与导入（RowValidator）共用同一判定函数，避免两套口径 | `records.py`、`importing/row_validator.py` | 接口测试：直编与导入对同一行给出一致结论 |
| C4 | 「更新语义」 | update 时条件判定基于**合并后的行值**（补丁 + 当前值），因此"把状态改成已完成但不填完成时间"能被拦住 | `records.py::update_row` | 单测：仅改状态触发条件必填 |
| C5 | 「容错」 | 非法正则（编译失败）不阻塞写入，记 warning 并在字段配置校验时提示；`required` 与 `required_when` 同时存在时以任一触发生效 | `field_rules.py` | 单测：坏正则降级为不校验 |
| C6 | 「多值字段」 | 模式校验只看标量（文本类）；list 类型逐项校验；空值 / 空串不参与模式校验（由 required / required_when 管） | 同上 | 单测：多值逐项 |
| C7 | （前端） | 本期只做服务端强制；字段管理里的规则编辑 UI 与前端即时提示列为后续 | — | 记入「已知限制」 |

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 字段配置 | `DataField.config` | 新增 `validation` / `required_when` 两个可选键，旧配置不受影响 |
| 2 | 直编写入 | `records.create_row` / `update_row` | 合并值后统一校验 |
| 3 | 导入校验 | `importing/row_validator.py` | 逐行校验复用同一函数 |
| 4 | 前端字段管理 | `pages/fields/FieldManager` | 本期不加编辑入口 |

## 未决问题

- [x] ① 规则存放位置：字段 `config`（不新增列，无损兼容）。
- [x] ② 判定时机：写路径（create / update / 导入）统一校验；读取不校验。
- [x] ③ 前端 UI：本期不做。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论
