# ADR 0046: 网页性能瓶颈识别与读路径优化（大表页面切换卡滞）

Status: Implemented（需求方已确认卡片与方案，2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-27
Related: `src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/datasource/services/write.py`、`frontend/src/api/records.ts`、`frontend/src/pages/grid/useGridData.ts`、`frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/utils/tagColors.ts`
需求卡片: `docs/requirements/0046-web-performance-bottlenecks.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「平台各页面切换卡滞」 | Context 表按「数据表目录页 / 打开表网格 / 翻页与筛选 / 非 grid 视图」四条切换路径逐条给实测瓶颈与 `文件:行号`；P0 修复热路径（读缓存 + 计数分离 + 排序索引 + 工作区统计收敛） |
| C2 | 「是否和它（股市日线数据量）过大存在关系」 | Context 表每条标「确认 / 排除 / 新增」：计数、排序、深分页、contains 与行数线性相关（确认）；表详情载荷、内容区重挂载与行数无关但被大表放大（新增/排除详见各行） |
| C3 | 「对网页的性能提升进行瓶颈识别和方案制定」 | 分期 P0（后端读路径）/ P1（前端载荷）/ P2（分页与渲染），每期带本地实测验收指标（见「分期」表） |
| C4 | 「修复不得改变现有功能口径」 | 不变量 I1-I4；Tag 颜色口径的预期变化在 D6 显式声明；既有单测 / e2e 不新增失败 |

## Context

测量环境（2026-10-27）：本地 SQLite（`~/.cndb/data/cndb.db`，641MB），「数据源示例」工作区（wid=2）「股市日线」表 4,286,980 行、10 字段；dev 服务（`uvicorn cndb.app:app --port 8772`）。以下耗时为该环境实测（冷 = 该查询体 5s 缓存窗口外首次执行）。dev 前端（Vite 未压缩）会放大 JS 侧卡滞，但各条后端耗时在生产构建下不变。

现状逐条核对（沿用卡片「现状影响面」编号）：

| # | 现状 | 位置 | 影响（实测） | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 网格行数据走 `GET /records`，该端点**无缓存**；带 5s `list_cache` 的是 `POST /records/list`，前端未使用 | `frontend/src/api/records.ts:7-13`、`src/cndb/plugins/tables/routers/records.py:173-217`（GET 无缓存）vs `records.py:220-253`（POST 缓存，`RECORD_LIST_TTL_SECONDS = 5.0`，事件失效见 `core/events.py:177-180`） | 最热读路径每次全量执行：默认视图排序分页冷 0.86s；同查询体走 POST 仅 3.5ms（缓存命中） | 确认（与行数无关的纯结构性缺陷） |
| 2 | 行列表每次执行 `COUNT`（含 `_trashed=0` 过滤）+ 排序分页；COUNT 344ms、默认视图排序 486ms | `src/cndb/plugins/tables/services/core/records.py:527-532`（count）、`:534-546`（排序/分页） | 每次翻页 / 筛选 / 排序变化都重付 344ms 计数；COUNT 与 offset 无关但与行数线性 | 确认（行数线性放大） |
| 3 | 默认视图「全部日线」排序 `股票代码 ASC, 日期 DESC`；现有 `ix_{table}_match` 索引为全 ASC（`(股票代码, 日期, 来源)`），方向不匹配 → 排序溢出临时 B-tree | `src/cndb/plugins/datasource/services/write.py:143-170`（`ensure_match_keys_index` 全 ASC）；视图排序存于 `tables_dataview.sortings` | 排序分页 486ms；实测补建 `(股票代码 ASC, 日期 DESC)` 索引后同一查询 ~0ms | 确认（索引方向缺陷） |
| 4 | 工作区详情逐表 `Table(autoload_with=...)` 反射 + 逐表 COUNT + 懒算存储快照，无缓存；数据表目录页（`/w/:wid/tables`，工作区落地页）每次挂载调用 | `src/cndb/plugins/workspaces/routers/workspaces.py:211-226`（反射+COUNT 循环）、`:255`（lazy snapshot）、`frontend/src/pages/workspace/TablesList.tsx:228-232` | `GET /workspaces/2` 稳定 ~240ms/次（含 4.3M 行表的 COUNT 与反射） | 确认（统计路径行数线性 + 无缓存） |
| 5 | 表详情 / 字段列表携带 select 字段全量 options：「股票代码」字段 7,289 个选项、config 约 453KB；表详情响应 414KB | `src/cndb/plugins/tables/routers/tables.py:427-498`（`fields=active_fields`）、`routers/fields.py:244-255` | 每次 GridPage 挂载传输并解析 414KB；筛选下拉 / 视图配置按全量选项渲染 | 新增（载荷与行数无关，但被「选项即标的清单」的大表放大；单元格 `resolveTagColor` 还对每格做 options 线性查找，`frontend/src/utils/tagColors.ts:201-211`） |
| 6 | 非 grid 视图一次性拉 2000 行 | `frontend/src/pages/grid/useGridData.ts:22`（`VIEW_FETCH_ALL_LIMIT = 2000`）、`:37` | 后端 0.31s + 839KB 载荷 + 前端整批渲染（gallery 已分批 48/批，tree/gantt/matrix 未审计） | 确认（行数与渲染量双重放大） |
| 7 | 深分页 `OFFSET` 线性扫描 | `src/cndb/plugins/tables/services/core/records.py:538-544` | offset 4,000,000 实测 4.44s（含全表排序；命中排序索引后仍需扫过 offset 个索引项） | 确认（行数线性） |
| 8 | 关键词 contains 走全字段 `LIKE '%x%'` | `src/cndb/plugins/tables/services/core/query.py`（`compile_filters`，`__query__` 分发） | 「600519」实测 1.13s | 确认（行数线性；搜索为按需触发，非页面切换主因） |
| 9 | MainLayout 内容区按 pathname 整体重挂载（Suspense 骨架重放 + `cn-page-enter` 动画） | `frontend/src/layouts/MainLayout.tsx:589-597`（`<Content key={location}`，`location` 为 pathname） | 跨页切换整页重建 DOM；查询命中缓存时为数十 ms 级固定成本 | 排除（与行数无关、非主因；query 变化不触发重挂载，`MainLayout.tsx:69`） |
| 10 | 数据表列表 UNION ALL COUNT（含 4.3M 行表） | `src/cndb/plugins/tables/routers/tables.py:58-72`（`_batch_record_counts`） | 冷 173ms，`list_cache` 命中 4.5ms | 排除（已有缓存兜底，非主因） |

**核心缺陷（需求要补的）**：大表读路径（计数、排序、统计）随行数线性放大，且最热的 `GET /records` 与工作区详情两条路径既无缓存也无方向匹配的排序索引；同时展示载荷携带超全量字段配置（7,289 选项 ≈ 450KB）。

设计目标（不变量）：

- **I1 缓存隔离与失效**：记录 / 计数 / 工作区统计缓存必须按（工作区, 表, 用户, 查询体）隔离（行级权限按人过滤，不得跨用户复用），并沿用 `record.* / row_rule.* / datasource.* / table.*` 事件失效（`core/events.py:174-186` 同源扩展）。
- **I2 行为不变**：分页 `total` 语义（含 lookup 内存过滤修正）、过滤 / 排序结果、行级权限过滤、字段隐藏与现有完全一致；缓存只省重复计算，不改变返回内容。
- **I3 大载荷显式截断**：options 截断必须带 `options_truncated: true` 与 `options_total`，前端不得静默丢选项；字段编辑 / 导入校验路径仍取全量。
- **I4 索引幂等可回收**：排序索引创建幂等（`CREATE INDEX IF NOT EXISTS`）、命名可枚举（可整体 DROP 还原），不改变写路径语义与既有 `match` 索引。

## Decision

### 1. 数据模型

无新表、无 alembic 迁移（本 ADR 全部为读路径行为变更 + 动态物理表 DDL 产物）：

- 动态表追加「视图排序索引」：命名 `ix_{db_table_name}_sort_{n}`（n = 该表排序索引序号），列 = 视图 `sortings` 的字段按各自 `direction` 声明 ASC/DESC，尾部固定补 `id ASC`（tie-break，保证分页稳定）。索引进 `sqlite_master`，零元数据表；每表上限 3 个（超出按创建序淘汰最旧并 DROP）。
- 字段序列化新增只读标志位（响应层字段，不入库）：`config.options_truncated: boolean`、`config.options_total: int`（仅截断时出现）。

### 2. 判定算法（唯一入口）

- **排序索引入口** `ensure_sort_index(db, table, sorts)`（落 `plugins/tables/services/core/ddl.py`，与 ADR 0038 原子 DDL 同层）：
  1. `sorts` 为空或含 lookup 字段（无物理列）→ 直接返回；
  2. 进程内按 `(物理表名, 列+方向元组)` 缓存已建结果（复用 `ensure_match_keys_index` 的 `_INDEXED_KEY_SETS` 模式，`plugins/datasource/services/write.py:163-165`）；
  3. 命中上限 3 时淘汰最旧；DDL 幂等（`IF NOT EXISTS`）。
  调用点（唯一两处）：`routers/views.py` 视图创建 / 更新保存 `sortings` 后；`routers/records.py` GET / POST 列表路径首查惰性建（首个请求一次性付建索引成本，4.3M 行实测 ~1.9s 一次性）。
- **计数分离入口** `count_rows(engine, table, *, filters, filter_logic, include_trashed, db, user)`：从 `list_rows` 抽出 `records.py:527-532` 的 count 构造（含行级权限与 trashed 条件、lookup 修正由调用方处理）；`list_rows` 增加可选参数 `total: int | None`（传入即跳过内部计数）。router 层按 `cache_key("records-count", wid, tid, user_id, include_trashed, filters-sig, filter_logic)` 缓存计数（TTL 与记录缓存同 5s，同事件失效）；**offset 变化不改 filters-sig**，翻页不重算计数。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/records` | 接入 `list_cache`（cache key 与 POST `/records/list` 同构：`records` 前缀 + wid + tid + user + include_trashed + 查询体签名 + engine 身份，TTL 5s）；计数走分离缓存；排序索引惰性建 |
| `POST /{wid}/tables/{tid}/records/list` | 计数走分离缓存（响应缓存维持现状）；排序索引惰性建 |
| `GET /{wid}`（工作区详情） | `total_rows` 改用 `_batch_record_counts` 同款 UNION ALL（去掉逐表 `Table(autoload_with=...)` 反射）；整个统计块（table_count / member_count / view_count / total_rows）挂 `list_cache("workspace-stats", wid)`，TTL 30s，`table./record./row_rule./datasource.` 事件失效 |
| `GET /{wid}/tables/{tid}`（表详情）、`GET /{wid}/tables/{tid}/fields` | options > 500 截断为前 500 + `options_truncated: true` + `options_total` |
| `GET /{wid}/tables/{tid}/fields?full=1` | 新增查询参数：返回全量 options（字段编辑器 / 筛选配置专用；权限同既有 GET） |

### 4. 边界与例外

1. 含 lookup 过滤 / 排序的查询走内存路径（`records.py:483-499`），排序索引不适用；计数分离缓存同样只按 SQL 侧 filters-sig 生效，lookup 修正后的 total 仍由内存路径每请求计算（lookup 场景多为中小表，维持现状）。
2. 工作区表数 > 100 时 `total_rows` 沿用 `_batch_record_counts` 的跳过退化（返回 null，前端显示维持现状）。
3. PostgreSQL 部署：排序索引 DDL 与 UNION ALL 统计通用；`ix_*_sort_*` 命名不与既有冲突（`pg_indexes` 同名幂等）。
4. options 截断只影响展示序列化；字段编辑器、导入校验、`select` 字段校验（ADR 0035 允许值缓存）继续用库内全量 config。
5. 事件失效延迟（事务提交后钩子）与现状一致（5s TTL 兜底），不引入新的一致性口径。

### 5. 迁移

无 alembic 迁移。排序索引随首个匹配查询 / 视图保存幂等创建；还原 = 按命名约定 `DROP INDEX ix_{table}_sort_{n}`（可写一次性脚本，不入仓库常规流程）。存量库零迁移。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 字段编辑 / 视图筛选下拉 | `frontend/src/pages/fields/FieldManager.tsx`、`frontend/src/pages/grid/view-config/ViewConfigDialog.tsx`、`grid/cells/buildColumns.tsx`（ColumnFilterDropdown） | 需要 options 全量的入口改调 `fields?full=1` |
| 单元格调色 | `frontend/src/utils/tagColors.ts`、`grid/cells/DisplayCell.tsx` | `options_truncated` 时 fallback 由「选项位置」改为「值稳定哈希」（`resolveTagColor` 的 `layout.truncated` 分支） |
| 网格数据 | `frontend/src/api/records.ts`、`pages/grid/useGridData.ts` | 无改动（缓存为端点内行为；翻页计数已由后端分离缓存加速） |
| 非 grid 视图 | `pages/grid/views/*` | 树 / WBS / 流程按 200 行/批分批挂载 +「加载更多」（`rowBatch.tsx`）；甘特已有行虚拟化，无需改；矩阵 / 日历 / 图表为聚合视图（计数来自全量行），不分批 |

### 7. 测试清单

**判定层（单测）**：
- `ensure_sort_index`：方向组合（asc/desc 混合）建索引正确、幂等、上限 3 淘汰最旧、lookup / 空排序跳过；
- `count_rows`：与 `list_rows` 内部计数同值（含行级权限、trashed、filters 组合）；`list_rows(total=...)` 传入跳过计数；
- 工作区统计 UNION ALL 与逐表 COUNT 同值（含 >100 表退化）；
- options 截断：>500 截断 + 标志位 / ≤500 不截断 / `full=1` 全量；
- `hashTagColor`：同值同色、截断前后非截断字段颜色不变。

**接口层**：
- `GET /records` 命中缓存（二次请求 < 阈值 + 内容一致）；写入事件后缓存失效；
- 翻页（offset 变化）不重算计数（计数缓存命中计数不变、total 一致）；
- `GET /workspaces/{id}` 统计缓存 + 失效；`GET /tables/{tid}` 截断载荷体积断言（< 30KB，用 7000+ 选项的表）。

**迁移 / 备份**：无迁移；备份往返不受影响（排序索引为库内 DDL 产物，备份恢复后首查重建）——用既有备份往返用例回归。

**e2e（前端）**：
- 大表网格：默认视图加载、翻页、切换视图不超时（沿用现有 grid 冒烟 + 断言无骨架闪烁回归）；
- 截断字段的单元格 Tag 渲染与筛选下拉（`full=1`）可用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | GET /records 读缓存 + 计数分离缓存 + `ensure_sort_index`（视图保存 / 首查两入口）+ 工作区统计 UNION ALL 化与缓存 | 低（缓存与索引均为只读加速，事件失效机制已有） |
| **P1** | options 截断 + `fields?full=1` + 前端哈希调色与全量拉取改造 | 中（颜色口径变化 D6、下拉入口需逐一核对） |
| **P2** | 非 grid 视图分批渲染（树 / WBS / 流程）+ 深分页上限（`MAX_RECORD_OFFSET = 100_000`） | 低-中（分批不改变聚合口径，已在 D7 / D8 声明） |

验收指标（本地 SQLite、4.29M 行股市日线表、dev 服务实测口径）：

| 指标 | 现状 | P0 目标 | P1 目标 |
|---|---|---|---|
| 默认视图网格冷请求（含计数+排序分页） | 0.86s | ≤ 0.6s | ≤ 0.6s |
| 同查询体 5s 内复访 | 0.86s（GET 无缓存） | ≤ 0.05s | ≤ 0.05s |
| 翻页（仅 offset 变化） | ~0.8s | ≤ 0.1s | ≤ 0.1s |
| 数据表目录页（工作区详情+表列表） | ~0.41s（240+173ms 冷） | ≤ 0.35s（复访 ≤ 0.05s） | ≤ 0.35s |
| 表详情响应体积 | 414KB | 414KB | ≤ 30KB |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 先实测定位、按「读缓存 + 计数分离 + 排序索引 + 载荷瘦身」四刀修复读路径，保持 SQLite 单机 | 实测 0.86s 中 344ms 计数 + 486ms 排序 + 无缓存，均为可独立消除项；单机本地场景无水平扩展诉求 | 换 PostgreSQL（迁移成本不成比例，瓶颈在查询形态而非引擎）；前端纯优化（后端 0.8s 不消除） | 本 ADR 全部 |
| D2 | 最热路径 GET /records 无缓存 | 直接把 POST /list 的 `list_cache` 机制扩到 GET（同 key 构造、同 5s TTL、同事件失效），前端零改动 | 前端网格实际走 GET（`records.ts:13`），缓存已存在但没盖住最热路径 | 前端改走 POST（改 2 处调用 + GET 端点语义仍裸奔，e2e / 第三方仍在用 GET） | `routers/records.py` |
| D3 | 每请求重算 COUNT | 计数从 `list_rows` 抽出为 `count_rows`，按（表, 用户, filters-sig）独立缓存 5s；offset 不参与 sig | 翻页只改 offset，重付 344ms 计数无意义；行级权限按人 → sig 含 user_id（I1） | 近似计数（破坏分页 total 语义 I2）；只靠整响应缓存（筛选/排序一变即全 miss） | `records.py`（service + router） |
| D4 | 默认视图排序无法命中索引 | 新增 `ensure_sort_index`：按视图 sortings 的「字段+方向」建索引（尾补 id ASC），视图保存与列表首查两入口惰性建，每表上限 3 | 实测补方向匹配索引后排序 486ms → ~0ms；match 索引是同步幂等键专用（全 ASC），不应复用 | 修 `ensure_match_keys_index` 支持方向（幂等键语义与视图排序耦合，污染数据源链路）；每次请求 EXPLAIN 探测（请求路径做 DDL 探测过重） | `services/core/ddl.py`、`routers/views.py`、`routers/records.py` |
| D5 | 工作区详情 240ms | total_rows 改 UNION ALL 单语句 + 统计块挂 30s `list_cache`（table./record./datasource. 事件失效） | `_batch_record_counts` 已验证 UNION ALL 可行（173ms → 4.5ms 缓存命中）；逐表 `Table(autoload_with=...)` 反射是纯浪费 | 读 `workspaces_storage_snapshot`（快照是字节数，无行数口径，ADR 0024 不覆盖） | `workspaces/routers/workspaces.py` |
| D6 | 7,289 选项 ≈ 450KB 载荷 | 展示序列化 options > 500 截断 + `options_truncated/options_total` 标志；`fields?full=1` 供编辑 / 筛选用全量；截断字段 Tag 颜色 fallback 改「值稳定哈希」 | 414KB 表详情每次挂载传输 + 解析；选项全集 = 标的清单属目录数据，展示不需要 | 按值前缀分片加载（复杂度高收益有限）；options 全量保留仅压缩 gzip（414KB 压后仍 ~100KB 且解析成本不变） | `routers/tables.py`、`routers/fields.py`、`utils/tagColors.ts` |
| D7 | 非 grid 视图 2000 行 | 逐个视图审计：树 / WBS / 流程改为 200 行/批 +「加载更多」；甘特已有行虚拟化；矩阵 / 日历 / 图表是**聚合**视图（卡片数 / 计数徽章来自全量行）不分批，否则计数失真 | 0.31s + 839KB 是次级瓶颈（非默认路径）；分批只应作用在「逐行挂载 DOM」的视图，聚合视图的分批会改变口径 | 立即下调 VIEW_FETCH_ALL_LIMIT（改变既有视图数据语义，需逐视图评估）；给聚合视图也加批次（计数徽章与列总计会随批次变化，违反 I2） | `pages/grid/views/rowBatch.tsx`、`TreeView.tsx`、`WbsView.tsx`、`FlowView.tsx` |
| D8 | 深分页 4.44s | P0 排序索引落地后复测仍 2.9s（4M 偏移），采用 **OFFSET 上限 100,000 + 400 可操作提示**（`MAX_RECORD_OFFSET`）；不做 keyset | 复测：offset 5 万 0.45s、50 万 0.94s、400 万 2.9s，仍是线性扫描；10 万偏移 = 每页 100 行时第 1000 页，覆盖正常浏览 | 直接 keyset（AntD 分页是 offset 模型，改造面大且 deep link 不兼容）；纯前端限制（API 仍可被深翻页拖垮） | `routers/records.py`（`MAX_RECORD_OFFSET`） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：网格冷请求 0.86s → ≤0.6s、5s 内复访与翻页进入 ≤50/100ms 区间；数据表目录页 240ms 统计收敛为缓存命中；表详情载荷 414KB → ≤30KB；页面切换主观卡滞的主因（后端串行慢查询 + 大载荷解析）被消除。
- **负向**：大表新增 ≤3 个排序索引（同步写入的索引维护成本，4.29M 行建索引一次性 ~2s）；截断字段的 Tag 颜色口径由「选项位置」变为「值哈希」（D6 显式声明）；计数缓存 5s 窗口内写入后靠事件失效，极端场景下 total 短暂滞后（与既有 POST 缓存同口径）。
- **风险与缓解**：惰性建索引发生在首个列表请求（阻塞该请求 ~2s 一次性）——缓解：视图保存时预建，seed / 启动期对默认视图预建；缓存 key 必须含 user_id——已有 POST 缓存先例，测试覆盖跨用户不复用。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无（性能工程实践，无产品口径对照）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 存储用量统计 | `workspaces_storage_snapshot`（字节数快照） | 本 ADR 只缓存行数 / 计数统计，不改动快照体系 | ADR 0024 |
| 数据源幂等索引 | `ix_{table}_match`（幂等键，全 ASC） | 保持不动，排序索引独立命名 `ix_{table}_sort_{n}` | ADR 0034 / 0035 |
| 记录列表缓存 | POST `/records/list` 5s `list_cache` + 事件失效 | 机制扩到 GET 与计数 / 工作区统计，失效事件同源 | 本 ADR D2/D3/D5 |
| select 校验允许值缓存 | `field_types/select.py`（库内全量） | options 截断只在序列化层，校验不截断 | ADR 0035 D1 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/tables/services/core/record_counts.py`、`src/cndb/plugins/workspaces/services/stats_cache.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/core/events.py`（GET 读缓存 / 计数缓存 / 排序索引惰性建 / 统计 UNION ALL 与 30s 缓存 / 事件失效） | `tests/test_adr0046_read_path_perf.py` | 247df719 |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/field_serialization.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/routers/fields.py`、`frontend/src/utils/tagColors.ts`、`frontend/src/pages/grid/cells/DisplayCell.tsx`、`frontend/src/pages/grid/layout/ColumnFilterDropdown.tsx`、`frontend/src/pages/grid/cells/EditCell.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx`、`frontend/src/pages/fields/FieldManager/index.tsx`（options 截断 + fields-full 全量通道 + 值哈希调色） | `tests/test_adr0046_options_truncation.py`、`frontend/src/utils/tagColors.test.ts` | 247df719 |
| P2 | 已落地 | `frontend/src/pages/grid/views/rowBatch.tsx`、`frontend/src/pages/grid/views/TreeView.tsx`、`frontend/src/pages/grid/views/WbsView.tsx`、`frontend/src/pages/grid/views/FlowView.tsx`、`src/cndb/plugins/tables/routers/records.py`（200 行/批 + 深分页上限） | `frontend/src/pages/grid/views/rowBatch.test.tsx`、`tests/test_adr0046_read_path_perf.py` | 247df719 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，`Status` 已置 `Implemented`（2026-10-27 人工确认）
- 已完成：瓶颈实测（Context 表，2026-10-27 本地 4.29M 行股市日线表）、需求卡片、本 ADR、P0/P1/P2 代码与测试
- 下一步：在真实大库复测「分期」表指标（网格冷请求 / 复访 / 翻页 / 目录页 / 表详情体积）作为后续基线；如需更深的翻页体验再单独立项 keyset（本 ADR D8 已否决按现状）
- 已知坑：dev 服务（Vite + uvicorn --reload）放大前端卡滞，复测须固定同一环境；排序索引首查有一次性建索引耗时（4.29M 行 ~2s），生产建议在视图保存 / seed 预建；`GET /records` 缓存 key 含 engine 身份与 user_id（行级权限按人隔离）；options 截断字段的 Tag 颜色改用值哈希，颜色与历史渲染不完全一致（D6 已声明）
- 最近一次全绿：`make flow`（5582 passed / 3 skipped）+ `make cov`（96.97%，门槛 95%）+ `make frontend-coverage`（核心集合 lines 97.78% / branches 100%，全局 82.85%）+ Playwright e2e 全量（73 passed / 21 skipped / 2 重试通过）@ 2026-10-27
- 环境坑（本机）：`:8000` 被无关项目 `stock-strategy` 的 dev 服务长期占用，`make e2e` 的 webServer 会因端口冲突失败；本次以临时配置（`E2E_PORT=8010` + 复制 `playwright.config.ts` 把 url/baseURL 指向 8010，跑完即删）完成等价全量验证，未改动仓库配置。另需 `LD_LIBRARY_PATH=$HOME/.local/share/pw-libs/usr/lib/x86_64-linux-gnu` 才能启动 Chromium（系统缺 `libatk-1.0.so.0`）
