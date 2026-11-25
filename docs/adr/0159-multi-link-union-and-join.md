# ADR 0159: 多链接汇总与跨工作区关联（分析数据源 P3）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/analytics/schemas.py`、`src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/services/formula.py`、`src/cndb/plugins/analytics/routers/run.py`、`src/cndb/plugins/workspaces/services/links.py`、`frontend/src/pages/analytics/AnalyticsPage.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0159-multi-link-union-and-join.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「多链接 union」 | `source.type="union"`：2–5 个输入按显式 `columns` 映射纵向拼接（`union all`）；每个输入先各自取数（各自行级 / 字段隐藏），合成后再进公式引擎 |
| C2 | 「跨工作区 join」 | `source.type="join"`：`left` = 本表 / 链接，`right` = 链接，`join_type ∈ {left, inner}`；`on` 声明关联键对 |
| C3 | 不新增授权面（H58） | 逐个输入调用 `resolve_link` / 表 READ；任一不可读 → 整体 403/404，**不返回部分结果** |
| C4 | 行级叠加 | union：各输入独立取数后拼接；join：两侧先各自过滤，再按键匹配；**右表未匹配行不出现**（无右外 / 全外） |
| C5 | 列冲突 | join 冲突列改名为 `{left|right}.字段`；union 同名列按映射合并，类型不兼容 → 400 |
| C6 | 有界 | 输入 ≤5；各输入累计扫描行 ≤ `ANALYTICS_MAX_SCAN_ROWS`；输出行沿用结果上限（`limit ≤ 10000`） |
| C7 | 不级联 | 复合数据源不可嵌套（无 union of join、无链接的链接）；结果不进 lookup / 流水线 / 文档引用 |
| C8 | 可解释 | 模板保存输入清单快照（`link_id` / 别名 / 源工作区 / 到期）；打开模板逐个校验，失效项显式标注 |
| C9 | 缓存 | 若引入缓存：键含 `user_id` + 全部输入 id + 各链接口径签名（H60 同轴） |
| C10 | 存量不变 | 单表 / 单链接路径逐条不变（0158 L6 继续有效） |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 数据源是单值 `AnalyticsSource`（`table` / `link`），经 `_resolve_compute_source` 解析 | `analytics/schemas.py`、`analytics/routers/run.py` | 需扩为「单源 / union / join」三态，解析层产出统一行集 | 确认（C1/C2） |
| 2 | `compute()` 只接受单个 `DataTable`，内部 `scan_rows` 取数后进公式引擎 | `analytics/services/compute.py` | 复合源需要「先合成行集 + 字段清单」，再复用公式 / 聚合 / 图表 | 确认 |
| 3 | 链接解析与字段白名单已成体系（0158 P1）：`resolve_link` / `link_fields` / `link_query` | `workspaces/services/links.py` | 每个输入复用同一入口，不另写裁剪 | 确认（C3/C4） |
| 4 | 公式引擎按「字段名 → 列值」求值，字段名集合由调用方给定 | `analytics/services/formula.py` | 合成后的字段名必须是**稳定、无冲突**的；冲突列改名规则要写进 D 行 | 确认（C5） |
| 5 | 模板校验 `normalize_config(config, field_names)` 只做单源字段白名单 | `analytics/services/templates.py` | 需扩列映射 / 关联键 / 输入数校验 | 确认（C1/C5/C7） |
| 6 | 前端数据源是单选 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | 需多选 + 列映射（P2） | 确认（C8） |
| 7 | 分析链路无跨请求结果缓存 | `analytics/` | H60 以「若引入」形式约束（0158 D6 附注） | 确认（C9） |

**核心缺陷（需求要补的）**：0158 只让分析页「一次读一个数据源」，**跨部门汇总（多链接）与跨工作区关联（join）都没有表达能力**；用户只能导出 CSV 后人工拼接，口径不可复现。

设计目标（不变量）：

- **L1 不新增授权面**：复合数据源的每个输入与单源同权（源工作区 `READ` + 行级 + 字段隐藏）；H58 原文不动。
- **L2 fail-closed**：任一输入不可读 / 失效，整个执行失败（403/404），不返回部分结果、不静默补空。
- **L3 行存在性不外泄**：只允许 `left` / `inner`；右表未匹配行、不可见行都不得影响结果行数或数值。
- **L4 列名稳定**：同一配置的列名与顺序在保存、执行、导出三处一致；冲突列按固定规则改名。
- **L5 有界**：输入 ≤5、累计扫描行 ≤ 上限、无嵌套。
- **L6 存量不变**：单表 / 单链接行为与升级前逐条一致。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0159 L#`（H27，ADR 0119）。登记状态（2026-11-25 人工确认）：L1/L2 → H61，L3 → H62，L4 → H63。

## Decision

### 1. 数据源模型（仍为配置 JSON，无迁移）

```jsonc
// 单源（0158，保持不变）
{ "type": "table", "table_id": 12 }
{ "type": "link", "link_id": 800 }

// 汇总（union all）
{
  "type": "union",
  "inputs": [
    { "link_id": 801, "alias": "华东" },
    { "link_id": 802, "alias": "华南" }
  ],
  "columns": [
    { "name": "区域", "type": "text",  "map": { "801": "区域", "802": "区域" } },
    { "name": "销售额", "type": "number", "map": { "801": "销售额", "802": "金额" } }
  ]
}

// 关联（left / inner）
{
  "type": "join",
  "join_type": "left",
  "left":  { "link_id": 803 },              // 或 { "table_id": 12 }
  "right": { "link_id": 804 },
  "on": [ { "left_field": "客户编号", "right_field": "客户号" } ]
}
```

- 落库仍为模板 `config.source`（JSON），**无表结构变更、无迁移**；
- `union.columns[].map` 显式声明「输出列 ← 各输入字段」，未声明的输入列丢弃（防误带隐藏字段）；
- `join` 不声明列映射：左表全部可见字段 + 右表可见字段（冲突列按 §2 改名）。

### 2. 列名规则（L4）

| 场景 | 规则 | 例 |
|---|---|---|
| join 无冲突 | 原名 | `客户编号` |
| join 冲突 | `左.字段` / `右.字段` | `left.金额`、`right.金额` |
| union | 取 `columns[].name`（声明名） | `销售额` |
| 系统列 | 保留 `id` 仅代表合成行序号（不来自任何源） | `id` |

- 关联键在结果中只保留左表列（右表键列不重复输出，除非用户显式声明为普通列——MVP 不支持，简化口径）；
- 列名一旦保存即固定在 `config`，执行不再重新推导（避免源表改字段名导致列漂移）。

### 3. 执行链路（唯一入口）

```
_resolve_compute_source(...):
  single  → 现状（table / link）
  union   → 逐 input: resolve_link + link_fields + link_rows(全部行)
            → 按 columns 映射投影 → 拼接（union all）
            → 返回 (合成行集, 合成字段清单)
  join    → 逐 side: table/link 解析取数
            → 按 on 建索引 → left/inner 匹配（右表未匹配行丢弃）
            → 字段消歧 → 返回 (合成行集, 合成字段清单)

compute(...) 接受「行集 + 字段清单」后，公式 / 分组 / 图表 / 导出全部复用
```

- **不新增第二套 `compute`**：把「取数」与「计算」拆开，复合源只负责产出 `(rows, field_names)`；
- 每个输入的 `resolve_link` 失败 → 直接抛出（404/403），**不捕获后继续**；
- 扫描额度：各输入 `link_rows` 共享 `ANALYTICS_MAX_SCAN_ROWS` 预算（先到先扣，累计超限 400）。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/analytics/compute` | `source.type` 增 `union` / `join`；`union` 必带 `columns`、`join` 必带 `on` 与 `join_type` |
| `POST /api/v1/workspaces/{wid}/analytics/validate` | 支持复合源的字段清单（校验公式引用的字段是否在合成清单内） |
| `POST/PUT /api/v1/workspaces/{wid}/analytics/templates` | 保存期校验：输入存在且可读、列映射字段存在且可见、关联键两侧可见、输入 ≤5、无嵌套 |
| `GET /api/v1/workspaces/{wid}/analytics/datasources` | 不变（仍返回单表 / 单链接清单；复合源由前端组合） |

### 5. 边界与例外

1. 输入不可读 / 失效：`resolve_link` 的 404/403 原样透出，文案指向**具体某个输入**（别名 + 源工作区）。
2. union 列类型：MVP **严格同类型**（`text` / `number` / `date` / `boolean` 分组），跨族 → 400；数值族内（number / integer / currency / percent）视为兼容。
3. join 关联键：两侧字段必须可见（隐藏字段作键 → 400，避免以隐藏列做侧信道）；类型不兼容 → 400。
4. 右外 / 全外连接：不支持（L3）。
5. 嵌套：`union` 的输入只允许 `link`；`join` 的两侧只允许 `table` / `link`，不允许复合源（L5/C7）。
6. 无匹配的 left join：右表列补 `null`（不补空字符串，避免与真实空值混淆）。
7. 链接过期 / 撤回：执行时逐个解析 → 整体 404；模板打开时逐项标注。
8. 导出：CSV / PNG 与页面同源；CSV 列顺序 = 合成字段清单顺序（L4）。

### 6. 迁移

**无迁移**（配置 JSON 扩展，旧单源配置按原语义解释，L6）。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 数据源 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | 数据源选择增「多链接汇总 …」入口：多选链接 → 列映射表（每个输出列选各输入的来源字段）；「关联 …」入口：选左 / 右输入 + 关联键 + join 类型 |
| 失效提示 | 同页 | 复合源逐项展示输入状态（可读 / 已失效 / 到期），失效项不可运行并给出「联系源工作区拥有者」 |
| 字段候选 | 同页 | 公式 / 图表 / 汇总候选 = 合成字段清单（含 `left.` / `right.` 消歧名） |

### 8. 测试清单

**判定层（单测）** `tests/test_analytics_union_join.py`
- union：两个链接字段映射 + 类型不兼容 400 + 未映射列被丢弃；
- join：left / inner 行数差异、右表未匹配行不出现、右表行级规则外行不贡献、隐藏字段作键 400；
- 输入失效（撤销 / 过期）→ 整体 404；用户对某输入无读权 → 403；
- 嵌套 / 超过 5 个输入 → 400；扫描额度累计超限 → 400；
- 列名消歧：`left.金额` / `right.金额` 稳定且导出顺序一致。

**接口层** `tests/test_analytics_union_join_api.py`
- `compute` 复合源成功路径（含公式 + 分组汇总）；
- 模板保存期校验失败路径（映射字段不可见 / 关联键不可见 / 输入失效）；
- 结果导出 CSV 列与页面一致；既有单源用例全绿（L6 回归）。

**前端 / e2e**
- `AnalyticsPage.test.tsx`：复合源入口、失效项标注、运行载荷形状；
- `frontend/tests/e2e/critical/analytics-union-join.spec.ts`：两条链接批准 → 建 union → 出结果 → 撤回其一 → 整体失败。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | union（2–5 链接、显式列映射、严格类型）+ 判定层/接口用例 | 中（列映射校验与类型规则） |
| **P1** | join（left / inner，左 = 表或链接，右 = 链接）+ 行级叠加用例 | 高（行存在性外泄是最大风险点，需 H17 回归） |
| **P2** | 前端多选 / 映射 UI + 失效逐项提示 + e2e | 中 |
| ~~P3~~ | 右外 / 全外、嵌套复合源、跨库 join —— **明确不做**（会破 L3 / L5 / D4 / D9） | — |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 是否支持复合数据源 | 支持，但限定 union / join 且**无嵌套** | C1/C2；跨部门汇总是真实高频需求 | 只做 union（join 场景仍需导 CSV）；允许嵌套（组合爆炸，校验与解释成本失控） | `analytics/schemas.py` |
| D2 | union 去重 | `union all`，不去重 | 去重要按全部列比较，语义与性能都更差，且用户可用分组汇总自己聚合 | `union`（去重）：隐式语义、大表代价高 | `analytics/services/compute.py` |
| D3 | 部分输入失效 | **整体 fail-closed** | L2；「部分结果」看起来像全量，比报错更危险 | 部分成功 + 警告：用户容易把不完整汇总当全量 | `analytics/routers/run.py` |
| D4 | join 类型 | 仅 `left` / `inner` | L3；右外 / 全外会让「右表行是否存在」外泄（H17 同轴） | 右外 / 全外：行存在性侧信道 | `analytics/services/compute.py` |
| D5 | 列冲突 | join 冲突列 `left.` / `right.` 前缀；union 用声明名 | L4；列名必须在保存 / 执行 / 导出三处一致 | 自动加序号（`金额_2`）：与源字段改名后无法稳定解释 | `analytics/services/templates.py` |
| D6 | union 类型兼容 | 严格同族；数值族（number/integer/currency/percent）互认 | C5；隐式字符串化会让聚合结果不可解释 | 全量字符串化（`"1"` 与 `1` 混用后 sum 失效） | `analytics/services/compute.py` |
| D7 | 关联键字段 | 必须两侧可见；隐藏字段作键 → 400 | C3 / H17；隐藏列当键可被反推 | 允许隐藏字段作键：等于给了侧信道 | `analytics/services/templates.py` |
| D8 | 扫描额度 | 各输入共享 `ANALYTICS_MAX_SCAN_ROWS` 预算，累计超限 400 | C6；否则 5 个输入可放大 5 倍内存 | 每输入独立额度：内存放大不可控 | `analytics/services/compute.py` |
| D9 | 嵌套 | 禁止（输入只能是 table / link） | C7 / L5 | 允许嵌套：组合数与解释成本指数上升 | `analytics/schemas.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：跨部门汇总与跨工作区关联都能在分析页表达且可复现；权限口径零新增（逐输入复用 0154 / 0158 的判定）；无迁移。
- **负向**：列映射需要用户显式配置（多一步）；join 只支持 left/inner 且右侧必须是链接；大表 union 会更快撞到扫描上限。
- **风险与缓解**：① 行存在性外泄 → D4 禁右外 + 左表为驱动的匹配实现；② 隐藏字段从映射 / 键泄露 → 保存期与执行期双重校验；③ 内存放大 → D8 共享额度 + 输入数上限。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 链接只读语义 | `workspaces_link` | 逐输入复用 `resolve_link`，不新增授权面 | ADR 0154 L1 / H53 |
| 链接作分析源 | `analytics` 单源 | 单源行为不变，复合源在其上叠加 | ADR 0158 L1 / L6 / H58 |
| 行级权限 | `tables_rowpermission` | 每个输入先按自身读范围过滤，再合成 | ADR 0004（H15 / H17） |
| 字段隐藏 | `hidden_fields` | 映射 / 关联键 / 输出列都只能取可见字段 | ADR 0003 / 0158 C3 |
| 缓存 | 分析结果（若有） | 键含全部输入 id 与各自口径签名 | ADR 0158 L5 / H60 |
| 硬约束台账 | `docs/CONSTRAINTS.md` | L1 / L2 / L3 待评审后登记 | ADR 0119（H27） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/analytics/schemas.py`、`src/cndb/plugins/analytics/services/union_source.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/analytics/routers/run.py` | `tests/test_analytics_union_join.py` | `9fdb6780` |
| P1 | 已落地 | `src/cndb/plugins/analytics/services/join_source.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/routers/run.py`、`src/cndb/plugins/analytics/services/templates.py` | `tests/test_analytics_union_join.py` | 未提交 |
| P2 | 未开始 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | `frontend/src/pages/analytics/AnalyticsPage.test.tsx`、`frontend/tests/e2e/critical/analytics-union-join.spec.ts` | — |


## 交接（会话结束更新）

- 当前阶段：P0（union）/ P1（join）已落地；P2（前端）未开始
- 已完成：需求卡片 0159（C1-C10）；ADR 决策记录 D1-D9、不变量 L1-L6；P0（`union`：列映射、类型严格同族、fail-closed、共享扫描额度、列名固化、模板校验；`compute_rows` 抽出复用）；P1（`join`：左 = 表 / 链接、右 = 链接，仅 `left` / `inner`，**左表驱动**，右表未匹配行不出现（H62），冲突列 `left.` / `right.`、右表关联键不重复输出，关联键必须可见（隐藏 → 400），表侧同样按字段隐藏裁剪）；H61-H63 已登记
- 下一步：开 P2（前端：分类数据源入口 + 列映射 / 关联配置 UI + 失效逐项提示 + e2e）
- 已知坑：① **join 必须由左表驱动**（`left` / `inner` 都用左表行集迭代），否则右表未匹配行会泄露存在性；② 列映射 / 关联键的可见性校验要在保存期做（执行期只兜底），否则模板存下来必然失败；③ 复合源的字段清单要固化进 `config`（L4），不要执行期重新推导；④ 扫描额度是**共享预算**，实现时先扣再取，避免 5 个输入各自取满；⑤ 单源路径不要顺手重构（0158 的既有用例是回归基线）
- 最近一次全绿：`make check-fast` + `make cov`（7611 passed，95.01%）+ `tests/test_analytics_union_join.py`（P0 12 + P1 12）24 passed @ 未提交（2026-11-25）
