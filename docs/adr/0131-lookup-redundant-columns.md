# ADR 0131: lookup 显示值写入冗余列（`_lk_*`）后过滤 / 排序 / COUNT 下推

Status: Accepted（2026-11-11 人工批准并落地）
Date: 2026-11-10（2026-11-11 落地）
Related: `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/lookups.py`、`src/cndb/plugins/tables/services/core/links.py`、`src/cndb/plugins/tables/services/core/lookup_sync.py`、`src/cndb/plugins/tables/services/core/lookup_columns.py`、`src/cndb/plugins/tables/services/core/query.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/core/config.py`、ADR 0046
需求卡片: 无卡片（需求直接立项）

## 口径（需求 → 设计落点）

需求原文（就地编号，后续补卡片时迁回）：

- C1：lookup 字段没有物理列，含它的过滤 / 排序只能在内存求值，基础条件命中超过上限即 400；此前是「慢但出结果」。
- C2：需要一条能彻底消除 O(N) 的路径，顺带覆盖看板 / 日历等复用 `list_rows` 的视图。
- C3：记录需要处理的维护点（create/update、link 变更、源值变更、源字段回收、多值聚合语义、排序索引）、回填与迁移策略、触发条件，以及与 ADR 0046 的关系。
- C4：本 ADR 只立项排期，不实现；当前硬限流方案（配置项 `TABLES_LOOKUP_SCAN_LIMIT`，默认 20000）保持不变。

| 约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「只能在内存求值…超过上限即 400」 | 现状确认：`_guard_post_filter_scan` + `TABLES_LOOKUP_SCAN_LIMIT`（默认 20000）限流兜底，D1 保留为回滚路径 |
| C2 | 「彻底消除 O(N)」 | 为每个 lookup 字段维护 `_lk_<name>`（拼接值）与 `_lk_<name>_first`（首值）物理列，过滤 / 排序 / COUNT / 分页全部下推 SQL（D1、D2） |
| C3 | 「维护点 / 回填与迁移 / 触发条件 / 与 0046 的关系」 | 维护点见 §Decision 2 与 D3，回填见 §5 与 D6，触发条件见 D5，关系见 §与既有 ADR 的关系 |
| C4 | 「只立文档，不改代码」 | 立项时口径；2026-11-11 已由人工批准落地（见 §落地结论 / §落地状态） |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 对应约束 |
|---|---|---|---|---|
| 1 | lookup 无物理列，值在 `attach_lookup_values` 中按 link 映射 + 源值解析 | `records.py:767-771`、`lookups.py:118` | 每次列表请求都按行解析，O(N) 次映射 + 至少 2 次 `IN` 查询 | C1 |
| 2 | 含 lookup 过滤 / 排序时 `needs_post`，不下推 WHERE / ORDER / LIMIT，整表 `select *` 后内存处理 | `records.py:732-781` | 内存驻留整表 dict + link 映射 + lookup 值；分页与 COUNT 无法下推；`attach_formula_values` 也对全量行计算（`records.py:775`） | C1、C2 |
| 3 | 超限直接 400，正文含命中行数、生效上限、配置项名与建议 | `records.py:654-677`、`config.py:179-183` | 2 万行以上的表该功能不可用；调高上限只换内存风险 | C1、C4 |
| 4 | 视图（看板 / 日历 / 画廊）复用 `list_rows` | `routers/views.py:862-880` | 同上问题按视图放大：视图常常不带缩小范围的普通字段筛选 | C2 |
| 5 | link 读取把全部行 id / 目标 id 绑进单条 `IN` | `links.py:133-137`、`lookups.py:505` | 绑定参数随行数线性增长，能否执行取决于 SQLite `SQLITE_MAX_VARIABLE_NUMBER` 编译选项（本机 3.53.1 实测 4 万参数可过，但不保证其它部署一致），不宜作为长期策略 | C3 |

**核心缺陷（本 ADR 要补的）**：lookup 的显示值只存在于读取期的内存里，数据库无法用它过滤、排序、计数，于是任何含 lookup 的列表查询都退化成全表扫描 + 全量装配。

设计目标（不变量）：

- **I1 结果等价**：同一请求下，冗余列路径与现有内存求值路径返回的 `rows` / `total` / 顺序必须逐条一致（对拍基线，见 §7）。
- **I2 一致性有界**：写路径同步维护冗余列；任何源值 / link 变更后，冗余列在**同一事务**内更新，读路径不得读到跨事务的中间态。
- **I3 可回滚**：读路径由配置开关控制，关闭即回到内存回退 + 限流兜底（D1、D7）。
- **I4 权限不旁路**：冗余列只参与过滤 / 排序表达式，行级权限与 `trashed` 条件仍由 `final_where` 决定。

## Decision

### 1. 数据模型（已落地）

- 每个 lookup 字段在**持有它的物理表**（消费方）新增三列，命名为 `_lk_<db_column_name>` 前缀（`lookup_columns.py:lookup_column_names`）：
  - `_lk_<db_column_name>`：拼接值。多值按 `U+001F` 连接（无关联为 `''`）；单值为原始值（无关联为 `NULL`）。供 `contains` / 等值 / `in` / 前后缀过滤。
  - `_lk_<db_column_name>_first`：最小解析值（升序排序、`<` / `<=`、`contains_all` 等「任一元素满足」语义）。
  - `_lk_<db_column_name>_max`：最大解析值（降序排序、`>` / `>=`）。
- 列类型：SQLite 用 `BLOB`（无类型亲和性，数字按数字存 / 比较，文本按文本存 / 比较，避免字符串排序）；PostgreSQL 用 `TEXT`。
- 索引：`ix_<table>_<first>`（B-tree），服务升序 / 比较；`max` 与拼接列暂不建索引（避免写放大，深分页排序仍受益于 first 索引与 LIMIT 下推的裁剪）。
- 列名带 `_lk_` 前缀，与业务列隔离；字段改名 / 删除时随字段回收（`ddl.drop_column`）。

### 2. 同步算法（唯一入口，已落地）

- 写入维护入口唯一：`lookup_sync.sync_lookup_columns(engine, table, row_ids, *, db, conn)`——按行重算全部 lookup 冗余列，幂等，可在调用方事务内执行。
- 触发面（均在同一事务内）：
  - 记录 `create_row` / `update_row` / `delete_row`；
  - 批量 `bulk_create` / `bulk_update` / `bulk_delete` / `bulk_update_rows`；
  - link 字段关联变更（`set_links` 后重算该行）；
  - 源表被引用值变更（`resync_lookup_consumers`，按 `source_field_id` 反查消费方，仅重算关联到变更源行的消费方行）；
  - 目标行硬删除（`resync_lookup_consumers_for_deleted_rows`）；
  - 字段配置 / 源字段类型 / link `multiple` 变化、字段导入引入 lookup（`backfill_lookup_columns` / `resync_lookup_fields`）。
- 读路径：`records._build_query_plan` 先判断 `lookup_pushdown_available`；具备冗余列时 lookup 过滤 / 排序不再拆分到内存，`WHERE` / `ORDER BY` / `COUNT` / `LIMIT/OFFSET` 全部下推（`query._compile_lookup_condition` / `compile_sorts`）。`attach_lookup_values` 只对最终页做实时值装配，保持响应语义不变。
- 回退开关：`LOOKUP_COLUMNS_ENABLED=False`（默认 `True`）。关闭后回到旧内存路径 + `TABLES_LOOKUP_SCAN_LIMIT` 限流兜底，行为与改造前一致。
- PostgreSQL 下冗余列类型为 `TEXT`，`lookup_columns_present` 要求 `LargeBinary`，因此在 PG 上自动回退旧内存路径（已知限制，后续单独立项处理类型绑定与排序口径）。

### 3. API 变更清单

无对外契约变更：`POST /records/list` 与视图接口的请求 / 响应结构不变，仅内部实现切换；`_lk_*` 列不会出现在行响应里（`_row_to_dict` 过滤）。运维侧新增 CLI：`cndb lookup backfill --workspace <id> --table <id> --batch-size <n> --json`（分批回填 / 校准，幂等），不暴露 HTTP。

### 4. 边界与例外（按实现口径）

1. **多值聚合语义**：过滤用拼接串（`contains` 等价「任一元素包含」）；等值 `=` 在多值 + 列表入参时按「关联顺序拼接后整体相等」比较，单值入参按「存在某元素恰好相等」比较（`_multi_element_equal`，用 U+001F 边界 + LIKE 转义）；排序用 `first`（升序）/ `max`（降序），`NULL` 排最后。
2. **broken link / 源行已删**：写入 `NULL` / `''`，与旧内存路径的「无值」渲染一致，不保留悬空 id。
3. **lookup → lookup 链**：按现有解析顺序逐级展开后再落列，禁止跨级循环；循环检测沿用现有实现。
4. **源字段类型 / 选项**：冗余列存全值快照，不受 `options` 截断影响；行级权限与 `trashed` 仍由 `final_where` 决定（I4）。数值比较前用源字段类型的 `parse_query_value` 归一（`_coerce_lookup_value`）。
5. **未支持操作符**：`between` / `date_range` 与未知操作符在旧内存实现中即恒不匹配，下推路径保持 `false()`，结果一致。
6. **数值排序口径变化**：旧实现把解析值当字符串比较；冗余列在 SQLite 上保留原生类型，数值源字段按数值排序（视为缺陷修复，已在测试对拍中覆盖文本场景）。

### 5. 迁移与回填（已落地）

- 单条 alembic 迁移 `e3f4a5b6c7d8_add_lookup_columns`（`src/cndb/alembic/versions/`）：
  1. 读取 `tables_datafield` / `tables_datatable`，定位全部未回收 lookup 字段与所在物理表；
  2. 幂等 `ALTER TABLE ... ADD COLUMN` 三列（SQLite `BLOB` / PG `TEXT`）+ `CREATE INDEX IF NOT EXISTS ix_<table>_<first>`；
  3. 复用迁移连接分批回填（默认 1000 行 / 批，`LOOKUP_BACKFILL_BATCH_SIZE` 可调），按主键游标续跑、可重入；单表失败只告警，可稍后用 CLI 重跑；
  4. `downgrade` 幂等删索引与列（`batch_alter_table`）。
- 旧数据可升级：`create_all` 时代已存在的物理表由迁移补齐；已手工加过列的库跳过加列但仍回填。
- 运维兜底：`cndb lookup backfill` 可对指定 workspace / table 重新回填，也可作为漂移校准手段。

### 6. 前端

无改动：过滤 / 排序仍走同一接口，行为差异只在性能与上限消失。

### 7. 测试清单（已落地）

**单测 / 接口**（`tests/test_lookup_field.py`，61 项）：
- 写入同步：create / update / link 变更 / 批量创建后 `_lk_*` 落值；接口响应不暴露 `_lk_*` 且 lookup 实时值不变；
- 级联：源字段值变更、目标行硬删除后消费方重算；
- 回填：删除值后回填恢复、重复回填幂等；CLI backfill 报告；
- 对拍：14 组过滤条件（`is_empty` / `=` / `!=` / `in` / `not_in` / `contains` / 前后缀 / `contains_any` / `contains_all` / 比较）新旧路径 `rows` + `total` 一致；升 / 降序排序对拍；
- 上限：下推路径不受 `TABLES_LOOKUP_SCAN_LIMIT` 限制；关闭开关后旧路径超上限仍 400（含命中行数 / 上限 / 收窄建议），边界值放行。
- 迁移（`tests/test_lookup_columns_migration.py`，4 项）：加列 + 索引 + 历史数据回填、已含列时幂等、物理表缺失跳过、downgrade 往返可重复。

**回归**：tables / records / bulk / 视图 / 公式 / 字段导入相关 271 项全绿。

### 8. 分期（实际执行）

| 期 | 内容 | 状态 |
|---|---|---|
| **P0** | 加列 + 分批回填 + 读路径下推（过滤 / 排序 / COUNT / 分页），保留内存回退 | 已落地 |
| **P1** | 写路径全接入（create / update / 导入 / link 变更 / 源值变更 / 源字段回收） | 已落地 |
| **P2** | 迁移内回填 + CLI 校准入口 + 大表实测 | 已落地 |
| **P3**（可选） | 删除内存回退与 400 兜底，移除 `TABLES_LOOKUP_SCAN_LIMIT` | 未做（保留回滚开关；上限仅在旧路径生效） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 写入冗余列（本 ADR） | 唯一能把过滤 / 排序 / COUNT / 分页全部下推；JOIN 与流式都留着 O(N) 或语义缺口 | LEFT JOIN 下推（仅单值等值可下推、多值与嵌套分组仍回退、双路径语义要对齐两遍）；仅流式扫描（只降内存不降 CPU，total 仍需全扫，深分页不变） | `lookup_sync.py`、`query.py`、`records.py` |
| D2 | 多值聚合语义 | 两列：拼接串用于过滤、首值列用于排序 | SQL 无法从拼接串走索引取首值；拼接串保留「任一值包含」的既有直觉 | 单列拼接串同时承担排序（排序退化为字符串序，与现「首值优先」不一致）；子表存多值（多一次 JOIN，回到 O(N) 复杂度） | `lookup_columns.py`、`lookup_sync.encode_lookup_values`、`query._compile_lookup_condition` |
| D3 | 一致性策略 | 写路径同事务同步 + 后台抽样校准 | 同步保证读不到中间态（I2）；校准兜住漏接的写路径 | 仅定时全量重算（窗口期漂移可见）；trigger 维护（SQLite 上难表达跨表解析逻辑） | `records.py` 写路径、`lookup_sync.resync_lookup_*`、`cli/lookup.py` |
| D4 | 索引策略 | 三个冗余列，仅 `first` 建 B-tree 索引 | 避免把写放大到全部 lookup 字段；过滤走拼接串的 `contains` 本就无法用 B-tree，等值前缀收益有限 | 全字段建索引（写入放大）；完全不建（排序仍全扫） | `ddl.ensure_lookup_columns`、迁移 `e3f4a5b6c7d8` |
| D5 | 触发条件（何时值得做） | 满足任一即立项实现：① 单表规模 ≥ 2 万行且出现该 400 报障；② 看板 / 日历在同规模表上不可用；③ 为绕开 400 已把 `TABLES_LOOKUP_SCAN_LIMIT` 上调到 > 5 万（内存风险）；④ 目标客户主表 ≥ 10 万行在排期上 | 实测 15k 行 lookup 过滤 229.65ms、25k 行直接 400，确认命中①；本次人工批准立项 | 提前做（写入维护成本在没有大表诉求时是净负担）；永久保持 400（功能回退，见 D5 触发口径） | 本 ADR |
| D6 | 回填策略 | 分批 1000 行、按 id 游标、可重入；迁移内自动回填，CLI 可重跑 | 大表一次性回填会长时间持锁；可重入保证中断可续；迁移内回填复用同一连接（SQLite 新列可见性） | 一次性全量 UPDATE（长事务 / 锁表）；写时懒回填（读路径长期双语义） | `lookup_sync.backfill_lookup_columns`、迁移 `_backfill`、`cli/lookup.py` |
| D7 | 与 ADR 0046 的关系 | 0046 保留「读路径优化 + 限流兜底」的结论，本 ADR 承接其「后续优化 §1 写入冗余」并给出可执行细则 | 0046 已把三方案排序定稿，无需重开选型 | 另起一套方案（与 0046 结论冲突） | `docs/adr/0046-web-performance-bottlenecks.md` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：含 lookup 的过滤 / 排序 / 分页 / COUNT 从 O(N) 降到 O(log N + page)，峰值内存从整表降到单页；2 万行的 400 上限消失；看板 / 日历 / 画廊自动受益（同一 `list_rows` 入口）；`attach_formula_values` 只在单页计算，附带降一次 CPU。
- **负向**：写入放大（每行多写 1-2 列，源值变更需级联重算）；新增迁移 + 回填 + 校准任务，长期维护面变大；多值聚合语义需要持续对拍守卫（I1）。
- **风险与缓解**：漏接写路径导致冗余列漂移 → 后台抽样校准 + 对拍用例；回填期间读路径不变（I3）；上线后若 `total` 与内存路径不一致，可关开关回退到限流兜底。
- **遗留事项（绑定参数）**：即便本 ADR 落地，`links.py:133-137` / `lookups.py:505` 仍是「单条 `IN` 绑定全部 id」。当前可执行性依赖 SQLite `SQLITE_MAX_VARIABLE_NUMBER` 编译选项（本机 3.53.1 实测 4 万参数通过），不作为长期策略；落地时要么改走临时表 / `VALUES` 连接，要么由分块读取（每批 2000 行）自然收敛。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 读路径 / 限流兜底 | `records.py:654-677`、`config.py:179-183` | 2 万行以上直接 400，配置 `TABLES_LOOKUP_SCAN_LIMIT` 可调 | ADR 0046 |
| lookup 彻底下推 | `_lk_*` 冗余列 | 已落地（P0-P2） | 本 ADR |
| 字段物理 DDL 原子性 | `ddl.py` | 加列 / 删列的原子回退沿用 | ADR 0038 |
| 排序索引命名 | `ix_<table>_sort_<n>` | 冗余列索引独立命名 `ix_<table>__lk_<col>_first`，不混用 | ADR 0034 / 0035 |

## 落地结论（2026-11-11）

**改造前后对比**（同机、同一 `scripts/bench_perf.py`、50k 大表 / 15k lookup 行 / 1k 目标行、8 次 cold 采样；`--no-lookup-columns` 即旧内存路径）：

| 场景 | 改造前（旧内存路径） | 改造后（冗余列下推） | 变化 |
|---|---|---|---|
| lookup 条件筛选 p50 | 229.65 ms | 10.63 ms | 21.6x |
| lookup 排序 p50 | 237.84 ms | 9.32 ms | 25.5x |
| 25k 行 lookup 筛选 | 400（`TABLES_LOOKUP_SCAN_LIMIT=20000`） | 200 @ 11.46 ms | 上限不再触发 |
| 回填耗时 | — | 15k 行 0.895 s（16,764 行/s） | 25k 行 1.515 s（16,498 行/s） |

其他基线不受影响：列表 9.55→9.89 ms、详情 5.26→5.11 ms、搜索 16.82→18.52 ms（噪声范围内）；导入路径未改动。

**已知限制 / 后续**：
1. PostgreSQL 的 `TEXT` 冗余列暂不参与下推（类型绑定与数值排序口径需单独立项），线上 PG 自动走旧内存路径。
2. `between` / `date_range` 在旧实现中即恒不匹配，下推保持同语义；如后续要支持，需先改内存语义再同步改 SQL。
3. 数值源字段排序由旧的「字符串序」修正为原生数值序（缺陷修复，需在升级说明中提示）。
4. `TABLES_LOOKUP_SCAN_LIMIT` 与内存回退保留为回滚路径（P3 未做），重写 SQLite 绑定参数上限的遗留事项仍见 §Consequences。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/lookup_columns.py`、`src/cndb/plugins/tables/services/core/ddl.py`、`src/cndb/plugins/tables/services/core/query.py`、`src/cndb/plugins/tables/services/core/records.py` | `tests/test_lookup_field.py` | ea9d6e1b |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/lookup_sync.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/tables/services/fields/field_import.py` | `tests/test_lookup_field.py` | ea9d6e1b |
| P2 | 已落地 | `src/cndb/alembic/versions/e3f4a5b6c7d8_add_lookup_columns.py`、`src/cndb/cli/lookup.py`、`scripts/bench_perf.py` | `tests/test_lookup_columns_migration.py` | ea9d6e1b |
| P3（可选） | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地并全绿，P3（删除内存回退 / 移除上限）保留为后续可选
- 已完成：冗余列 DDL + 索引、写入同步（单行 / 批量 / 级联）、读路径下推（过滤 / 排序 / COUNT / 分页）、迁移内分批回填、CLI 校准、测试对拍与迁移测试、同脚本 A/B
- 下一步：观察一个发布周期的漂移（可用 `cndb lookup backfill` 校准）；PG 冗余列类型绑定与数值排序口径单独立项；P3 前需确认无 PG 存量依赖
- 已知坑：BLOB 列写入必须走 `text()` 原生绑定（`LargeBinary` 处理器只认 bytes）；查询侧用 `type_coerce(..., NullType())` 规避绑定处理器；多值 `=` 的「整体拼接相等」语义要持续对拍；`_lk_*` 不得出现在 API 响应（`_row_to_dict` 已过滤）
- 最近一次全绿：`make check-fast` / `make flow` / `make check`（见 CHANGELOG 与提交记录，2026-11-11）
