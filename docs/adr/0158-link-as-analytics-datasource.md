# ADR 0158: 工作区链接作为分析数据源（跨工作区只读分析）

Status: Proposed（待评审）
Date: 2026-11-25
Related: `src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/services/formula.py`、`src/cndb/plugins/analytics/routers/run.py`、`src/cndb/plugins/analytics/schemas.py`、`src/cndb/plugins/workspaces/services/links.py`、`frontend/src/pages/analytics/AnalyticsPage.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0158-link-as-analytics-datasource.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「链接作为分析数据源」 | 分析模板数据源新增 `link` 类型：`{type:"link", link_id, alias}`；选中后按该链接的**可见字段**与**视图口径**建指标 / 分组 / 筛选 |
| C2 | 不新增授权面（H15） | 每次执行都重新 `resolve_link(...)`：链接失效 → 404；对源工作区无 `READ` → 403（ADR 0047 文案）。**绝不静默返回空数据**，也绝不回退到创建者身份 |
| C3 | 隐藏字段（H17） | 数据源字段清单 = `link_fields(...)`（已按 `get_hidden_field_names` 裁剪）；模板校验阶段就拒绝不在清单里的字段（指标 / 分组 / 筛选 / 排序 / 图表标签） |
| C4 | 行级规则（H15） | 取数唯一入口 `link_rows(...)` → `list_rows(db, table, user=…)`：默认档 + 命中规则 + 软删过滤全部同源；**聚合在内存完成**（MVP 不下推 SQL，见 D3） |
| C5 | 可解释 | 模板保存数据源描述（`link_id` / 别名 / 源工作区名 / 字段快照摘要）；分析页展示来源与到期，失效时给「联系源工作区拥有者」提示 |
| C6 | 不传递权限 | 模板只存定义；执行时按**打开者**身份解析链接与源权限。无权 → 明确失败（不降级、不借用创建者权限） |
| C7 | 缓存一致 | 分析结果缓存键追加 `link_id` + 链接口径签名（`expires_at` 桶 + 源表版本）+ `user_id`；`workspace.link_revoke|expire` 事件失效相关缓存 |
| C8 | 导出 | CSV 导出复用同一取数结果（不再二次查询），受 `EXPORT_MAX_ROWS` 与列裁剪；PNG 导出只含图表 |
| C9 | MVP 范围 | 单数据源；多链接 union / 跨工作区 join → 400（提示「暂不支持，请拆分模板」） |
| C10 | 不级联 | 链接仍不可再链接、不进 lookup / 流水线 / 文档 `{{table:}}`（沿用 0154 L5） |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 分析模板的数据源是单一 `table_id`（工作区内表） | `src/cndb/plugins/analytics/services/templates.py`、`schemas.py` | 需要把数据源抽象为「本表 / 链接」两种，配置与校验同步扩展 | 确认（C1） |
| 2 | 取数统一 `list_rows(..., db=db, user=user)`，行级与隐藏字段在同一条链路 | `src/cndb/plugins/analytics/services/compute.py` | 链接数据源可完全复用，不新增取数路径 | 确认（C4） |
| 3 | 公式引擎按字段名白名单求值（`analytics/services/formula.py`） | 同上 | 白名单来源改为「链接可见字段」即可满足 C3 | 确认（C3） |
| 4 | 链接判定与只读口径已成体系（P0-P3.1）：`resolve_link` / `link_fields` / `link_rows` | `src/cndb/plugins/workspaces/services/links.py`、`routers/links.py` | 直接复用；分析页不另写裁剪 | 确认（C2/C4） |
| 5 | 分析结果有进程内缓存，键含模板 / 用户等维度 | `src/cndb/plugins/analytics/`、`core/cache` | 链接数据源必须扩 `link_id` + 有效期桶，并在链接失效事件上清 | 确认（C7） |
| 6 | 分析导出 CSV / PNG 走同一份计算结果 | `analytics` 导出端点 | 无需新增口径，只需把数据源解析接上 | 确认（C8） |
| 7 | 链接在 0154 中**明确不接分析**（L5 / C7），当时为了先收敛授权边界 | `docs/adr/0154-workspace-link.md` | 本期是**受控放开**：仅把已受权限约束的读数入口扩到分析页，不新增授权主体 | 新增（C2/C9/C10） |
| 8 | 分析页数据源选择只列本工作区表 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | 需增「外部链接」分组 + 失效态 | 确认（C5） |

**核心缺陷（需求要补的）**：链接落地后，跨工作区数据**只能逐页翻看**；每月重复的汇总分析仍要人工导 CSV。需求补的是「让已受权限约束的链接读数进入分析链路」，**不是**放宽权限。

设计目标（不变量）：

- **L1 不新增授权面**：分析页读链接数据与只读网格**完全同权**（源工作区 `READ` + 行级 + 字段隐藏）；0154 L1 / H53 原文不变。
- **L2 不传递权限**：模板只共享定义，执行按打开者身份；无权 fail-closed（403 / 404），不降级为空结果。
- **L3 失效显式**：链接撤回 / 过期 / 源表删除时，执行结果为明确错误（文案指向源工作区拥有者），绝不静默返回部分数据。
- **L4 单源与无级联**：MVP 只允许单数据源；链接的链接、join、union 一律拒绝（400）。
- **L5 缓存不串味**：缓存键含 `user_id` + `link_id` + 链接口径签名；链接事件使相关分析缓存失效。
- **L6 存量不变**：只分析本工作区表时，行为与升级前逐条一致（含缓存命中与导出）。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0158 L#`（H27，ADR 0119）。登记状态（2026-11-25 人工确认）：L1 → H58，L2 → H59，L5 → H60。

## Decision

### 1. 数据源模型

模板配置里原有 `table_id` 扩展为**联合描述**（向后兼容：旧模板只带 `table_id` → 解释为 `type:"table"`）：

```json
{ "source": { "type": "table", "table_id": 12 } }
{ "source": { "type": "link", "link_id": 800, "alias": "各部门销售" } }
```

- 落库仍存模板 JSON（`analytics_template.config`），**不改表结构**；
- `alias` 只是展示用快照，不参与判定；执行时以 `link_id` 为准重新解析；
- 校验：`type=link` 时 `link_id` 必须以 `active` 且未过期存在，且**当前用户**可读（否则保存期就 400/403，避免存一个必然失败的模板）。

### 2. 执行链路（唯一入口）

```
run_template(db, user, template)
  ├─ source.type == "table"  → 现状不变（list_rows on 本工作区表）
  └─ source.type == "link"   → resolved = resolve_link(db, user, workspace_id=当前工作区, link_id)
                               fields   = link_fields(db, user, resolved)      # 已裁剪隐藏字段
                               rows     = link_rows(db, user, resolved, filters=模板筛选, limit=0)
                               → 复用现有公式引擎 / 分组汇总 / 图表渲染
```

- **不新增取数实现**：链接分支只做「解析 + 交给现有分析管线」，公式引擎、聚合、图表、导出全部复用；
- 解析失败一律走链接侧统一出口（404 无效 / 403 无读权），**不吞异常**；
- 字段白名单在保存与执行两处都校验（保存期友好报错，执行期兜底）。

### 3. 聚合位置（下推 vs 内存）

MVP 选**内存聚合**：链接数据源先按模板筛选取行（受 `ANALYTICS_MAX_SCAN_ROWS` 兜底），再走现有聚合。
理由：行级读范围来自 `list_rows` 的 WHERE 组合，若自写下推 SQL 就要重写一遍默认档 + 规则并集 + 隐藏字段丢弃逻辑，**是 H15 最容易出错的地方**；链接数据量级（部门级汇总表）在扫描上限内可接受。

> 后续若确需下推，必须复用 `row_read_scope_where` + 同一 `_build_query_plan`，并在 ADR 补一份「下推 WHERE 与 list_rows 等价」的测试矩阵，不得在 analytics 里另写一套。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/analytics/datasources` | 新增：可选数据源清单（本工作区表 + 我可见的 active 链接），带 `readable` / `expires_at` |
| `GET /api/v1/workspaces/{wid}/analytics/recommendations` | 修改：接受 `link_id` 作为数据源（字段画像与推荐复用链接可见字段） |
| `POST /api/v1/workspaces/{wid}/analytics/run` | 修改：`source` 支持 `{type:"link", link_id}`；`table_id` 保留为兼容字段 |
| `GET /api/v1/workspaces/{wid}/analytics/templates/{id}/export` | 修改：数据源按 `source` 解析（导出 CSV / PNG 与页面同源） |

### 5. 边界与例外

1. 链接失效（撤回 / 过期 / 源表删除）：`run` 返回 404，前端提示「该链接已失效，请联系源工作区拥有者重新授权」。
2. 模板共享：打开者无权 → 403（文案指源工作区拥有者）；**不回退**为创建者权限、不返回空结果。
3. 单数据源限制：`source` 只允许一个；多链接 / join / union → 400，文案「本轮仅支持单一数据源」。
4. 链接的链接：分析数据源里再次链接不允许（0154 L5 不变）。
5. 分析结果不进工作区统计（`table_count` / `total_rows` 不计链接行）。
6. 导出：CSV 与页面同源；超过 `EXPORT_MAX_ROWS` → 400 提示收窄筛选（对齐 0148）。

### 6. 迁移

**无迁移**：模板配置是 JSON，兼容旧 `table_id`；无新表、无回填（存量零迁移，L6）。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 数据源选择 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | 数据源下拉分两组：「本工作区表」「外部链接（只读）」；链接项显示来源工作区与到期，不可读置灰并给 tooltip |
| 模板配置 | 同页模板抽屉 | 保存时带 `source`；失效链接给出「重新授权」引导，不静默改成空数据源 |
| 分析范围 | 同页「分析范围」 | 筛选字段候选 = 链接可见字段；隐藏字段不出现 |
| 失效提示 | 同页 | 执行失败时按后端 code 展示可执行文案（重新授权 / 等对方批准） |

### 8. 测试清单

**判定层（单测）** `tests/test_analytics_link_source.py`
- 链接失效（撤回 / 过期 / 源表软删）→ 404；用户对源工作区无 READ → 403；
- 隐藏字段用于指标 / 分组 / 筛选 → 400（保存与执行两处）；
- 行级默认档外行不计入聚合（H15 回归）；
- 视图口径链接：默认筛选 / 排序生效。

**接口层** `tests/test_analytics_link_source_api.py`
- `datasources` 只列可读链接；`run` 与 `recommendations` 接受 `link_id`；
- 模板共享：创建者有权 / 打开者无权 → 403；
- 多数据源 / join → 400；CSV 导出与页面结果一致；超 `EXPORT_MAX_ROWS` → 400；
- 缓存：同参数二次执行命中；撤回链接后不再命中（事件失效）。

**回归** `tests/test_analytics.py`（既有用例全绿，L6 存量不变）+ `tests/test_analytics_scope.py`。

**前端 / e2e**
- `frontend/src/pages/analytics/AnalyticsPage.test.tsx`：数据源分组、不可读置灰、失效提示；
- `frontend/tests/e2e/critical/analytics-link-source.spec.ts`：批准链接 → 选为数据源 → 出图 → 撤回后执行报错。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `datasources` 端点 + `run` 接受链接（单源、只读、fail-closed）+ 判定层用例 | 中（权限口径，需 H15/H17 回归） |
| **P1** | 字段白名单 / 分析范围 / recommendations 适配链接 + 缓存键与失效 | 中 |
| **P2** | 前端数据源分组、失效提示、导出对齐 | 低 |
| **P3**（可选，另立 ADR） | 多链接 union 汇总 / 跨工作区 join（需定义行级叠加与列冲突口径） | 高 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 是否新增授权面 | **不新增**：分析页读数与只读网格同权（源工作区 READ + 行级 + 字段隐藏） | 0154 L1 / H53 原文不动；分析只是另一个读数入口 | 为分析单独发「跨工作区读」令牌：等于第二套授权面，无法解释为何网格读不到的数据分析能读到 | `analytics/services/compute.py`、`workspaces/services/links.py` |
| D2 | 数据源配置形态 | 模板 JSON 内 `source:{type,table_id\|link_id,alias}`，旧模板按 `table` 解释 | 零迁移（L6）；配置天然可回滚 | 新增 `analytics_datasource` 表：为两种来源建表过重，且要迁移存量模板 | `analytics/services/templates.py`、`schemas.py` |
| D3 | 聚合位置 | **内存聚合**（复用 `list_rows` 结果），不下推 SQL | 下推要重写行级 WHERE，是 H15 最易出错处；链接数据量在扫描上限内 | 直接下推聚合：收益有限、风险集中，且需等价性测试矩阵 | `analytics/services/compute.py` |
| D4 | 失效表达 | 链接无效 404、无读权 403、多源 400 | 与 0154 D6 / C6 一致（无泄露 + 可解释） | 返回空结果：用户分不清「没数据」与「没权限」 | `analytics/routers/run.py` |
| D5 | 模板权限 | 只存定义，执行按打开者身份；无权 fail-closed | C6；模板本质是查询定义，不是数据快照 | 把创建者权限「冻结」进模板：等于权限随模板传播，最难解释也最危险 | `analytics/services/templates.py` |
| D6 | 缓存键 | `user_id` + `source` + `link_id` + 链接口径签名（`expires_at` 桶 + 源表 updated_at）+ 模板签名 | 防止换人 / 换链接 / 过期后命中旧结果 | 只按模板 id 缓存：共享模板会串味（别人的权限结果被复用） | `analytics`、`core/cache` |
| D6 附注 | 现状核对（P1） | 分析链路**当前没有跨请求结果缓存**（只有公式引擎内部的单次求值缓存），因此 H60 以「若引入缓存」的约束形式登记；将来加缓存必须按本行键设计 | 不假装已实现一个不存在的缓存 | 为满足条文新增缓存：无收益、只增风险 | `analytics/services/compute.py` |
| D7 | 单源限制 | 仅单数据源；union / join 拒绝 | C9；join 的行级叠加与列冲突口径需要独立设计 | 先上 join：口径说不清，越权风险最高 | `analytics/services/templates.py` |
| D8 | 隐藏字段 | 保存期 + 执行期双重校验，隐藏字段不得出现在任何配置位置 | C3 / H17；只看执行期校验会让模板「保存成功但永远失败」 | 只做执行期过滤：用户无从知道为什么算不出 | `analytics/services/formula.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：跨工作区汇总不必再导 CSV；权限口径零新增（复用链接读数），H15/H17 不破；无迁移。
- **负向**：内存聚合对「部门级大表」有扫描上限约束（超限需收窄筛选，与现有分析页一致）；不支持 join / union，复杂汇总仍需拆模板。
- **风险与缓解**：① 缓存串味 → D6 键设计 + 链接事件失效；② 共享模板误以为「别人看得到我看得到」→ D5 fail-closed + 文案；③ 隐藏字段从公式泄露 → D8 双重校验。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 链接只读语义 | `workspaces_link` / `link_rows` | 分析页复用同一取数入口，不新增授权面 | ADR 0154 L1 / H53 |
| 行级权限 | `tables_rowpermission` | 聚合仍以 `list_rows` 的 WHERE 为准 | ADR 0004（H15 / H17） |
| 字段隐藏 | `tables_tablepermission.hidden_fields` | 白名单来自 `link_fields`，双重校验 | ADR 0003 / 0154 C3 |
| 分析能力 | `analytics_template` | 数据源扩展，公式 / 图表 / 汇总链路不变 | ADR 0116 之外的既有分析域 |
| 导出上限 | `EXPORT_MAX_ROWS` | CSV 与页面同源，超限 400 | ADR 0148 |
| 硬约束台账 | `docs/CONSTRAINTS.md` | L1 / L2 / L5 待评审后登记 | ADR 0119（H27） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/analytics/routers/run.py`、`src/cndb/plugins/analytics/routers/datasources.py`、`src/cndb/plugins/analytics/schemas.py`、`src/cndb/plugins/analytics/plugin.py` | `tests/test_analytics_link_source.py` | `44beda2c` |
| P1 | 已落地 | `src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/analytics/services/recommend.py`、`src/cndb/plugins/analytics/routers/recommend.py`、`src/cndb/plugins/analytics/schemas.py` | `tests/test_analytics_link_source.py` | 未提交 |
| P2 | 未开始 | `frontend/src/pages/analytics/AnalyticsPage.tsx` | `frontend/src/pages/analytics/AnalyticsPage.test.tsx`、`frontend/tests/e2e/critical/analytics-link-source.spec.ts` | — |
| P3 | 未开始 | 另立 ADR | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 已落地（数据源清单 + `compute` 链接源 + 模板保存链接源 + `recommendations` 适配 + 字段白名单）；P2（前端）未开始
- 已完成：需求卡片 0158（C1-C10）；ADR 决策记录 D1-D8、不变量 L1-L6；P0（数据源清单、`compute` 链接源、隐藏字段拒绝、单源校验、存量兼容）；P1（模板 `config.source` 落库并按链接可见字段校验、`table_id` 落源表 id 兼容旧消费方、`recommendations?link_id=` 适配含隐藏字段裁剪、H58-H60 已登记）
- 下一步：开 P2（前端数据源分组 / 失效提示 / 导出对齐）
- 已知坑：① 链接分支必须走 `resolve_link` 统一出口，**不要**在 analytics 里直接 `db.get(WorkspaceLink)`（会绕开 404/403 与到期判定）；② 缓存键必须含 `user_id`，否则共享模板会把甲的权限结果喂给乙；③ 隐藏字段要在**保存期**就拒绝（否则模板存下来必然执行失败）；④ `ANALYTICS_MAX_SCAN_ROWS` 对链接数据源同样生效，超限文案要引导「用分析范围收窄」而不是「换表」
- 最近一次全绿：`make check-fast` + `make cov`（7613 passed，95.0%）+ `tests/test_analytics_link_source.py` 22 passed @ 未提交（2026-11-25）
