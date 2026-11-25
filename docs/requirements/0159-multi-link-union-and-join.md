# 需求卡片：多链接汇总与跨工作区关联（分析数据源 P3）

> 需求原文与约束编号的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0159（与 ADR `docs/adr/0159-multi-link-union-and-join.md` 同号）
- 来源 / 提出人：产品负责人（ADR 0158 P3 单独立项，2026-11-25 会话确认「继续」）
- 日期：2026-11-25
- 关联 ADR：[ADR 0159](../adr/0159-multi-link-union-and-join.md)（承接 [ADR 0158](../adr/0158-link-as-analytics-datasource.md) P3 与 [ADR 0154](../adr/0154-workspace-link.md)）

## 需求原句（逐字）

> 继续

ADR 0158 交接（2026-11-25）对应留痕：

> 下一步：无（本期收尾）。若要继续：P3（多链接 union / 跨工作区 join）另立 ADR，须先定义行级叠加与列冲突口径

生产场景：总部每月要出「华东 + 华南 + 华北各区销售汇总」——现在只能分别选三个链接、各跑一次、人工对齐列再相加；另一类是「本部门客户表 × 另一工作区的回款明细」按客户编号关联，目前完全做不到。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「多链接（union）」 | `source.type="union"`：2–5 个链接按**显式列映射**纵向拼接（`union all`，不去重）；列名 / 类型由映射声明，缺失列补空 | `analytics` + `workspaces`(links) | 接口测试 + 模板校验 |
| C2 | 「跨工作区 join」 | `source.type="join"`：左输入 = 本工作区表或链接，右输入 = 链接；支持 `left` / `inner`；关联键必须两侧都存在且**可见** | 同上 | 接口测试 |
| C3 | （承接 0158 L1 / H58） | **不新增授权面**：每个输入（表 / 链接）**逐个** `resolve_link` + 行级 + 字段隐藏；任一输入不可读 → 整体 **fail-closed**（403/404），不做「部分结果」 | `workspaces/services/links.py` | 判定层单测：任一链接撤回 → 整体失败 |
| C4 | （行级叠加口径） | union：各输入按自身读范围取行后拼接；join：两侧先各自按读范围过滤，再按关联键匹配，**右表未匹配行不出现**；不得用 join 反推不可见行是否存在 | `analytics` | 判定层单测：右表规则外行不贡献结果 |
| C5 | （列冲突） | 同名列在 join 中按 `{左/右}.字段` 消歧；union 同名列按映射合并，类型不兼容直接 400（不做隐式转换） | `analytics` | 模板校验用例 |
| C6 | （有界） | 单模板最多 5 个输入；扫描行数上限沿用 `ANALYTICS_MAX_SCAN_ROWS`（各输入累计）；join 结果行数上限同分析结果上限 | `analytics` | 接口测试：超限 400 |
| C7 | （不级联） | 汇总 / 关联结果不可再作为输入（无嵌套 union/join，无「链接的链接」）；不接 lookup / 流水线 / 文档引用 | 全局 | 模板校验：嵌套 → 400 |
| C8 | （可解释） | 模板保存输入清单（每项 `link_id` / 别名 / 源工作区 / 到期）；打开时逐个校验，失效项显式标注而不是静默剔除 | `analytics` + 前端 | 单测 + e2e 文案 |
| C9 | （缓存） | 若引入结果缓存：键含 `user_id` + 全部输入 id + 各自链接口径签名（H60 同轴） | `analytics` | 单测 |
| C10 | （存量不变） | 单表 / 单链接数据源行为逐条不变（0158 L6 继续有效） | `analytics` | 既有用例全绿 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 数据源描述目前是单值 `source` | `src/cndb/plugins/analytics/schemas.py`、`services/templates.py` | 需扩为 `union` / `join` 两种复合形态 |
| 2 | 取数唯一入口 `compute()` 只接受单表 | `src/cndb/plugins/analytics/services/compute.py` | 复合数据源要先合成行集，再进公式引擎 |
| 3 | 链接解析与字段白名单 | `src/cndb/plugins/workspaces/services/links.py` | 逐输入复用，不另写 |
| 4 | 模板校验 `normalize_config` | `services/templates.py` | 需校验列映射 / 关联键 / 输入数量 |
| 5 | 前端数据源选择 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | 需多选与映射 UI（或先只读展示） |
| 6 | 导出与结果渲染 | `analytics` 导出端点 | 列名消歧后仍要稳定 |

## 未决问题

- [x] union 去重语义 → **`union all`**（不去重；去重会隐式依赖全部列，语义与性能都更差）
- [x] 部分输入不可读时如何表现 → **整体 fail-closed**（不做部分结果，避免「看起来是全部数据」）
- [x] join 是否允许右外 / 全外 → **不允许**（右表未匹配行出现会让「行存在性」外泄，与 H17 冲突）
- [ ] 待人工确认：union 的列类型兼容规则是「严格同类型」还是「数值族可互转（number/integer/percent/currency）」——ADR 决策记录定

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论（剩 1 条：union 列类型兼容规则，归 ADR D 行）
