# ADR 0015: 工作区搜索缓存与全表覆盖增强

Status: Accepted（2026-10-21，P0 已落地，P1-P2 待实施）
Date: 2026-10-21
Related: `src/cndb/plugins/workspaces/services/search.py`、`src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/core/cache.py`、`src/cndb/core/events.py`、`src/cndb/plugins/tables/services/core/records.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts`、`tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx`；上游 ADR [0012](0012-workspace-global-search.md)

## 口径（需求 → 设计落点）

| 需求片段 | 本设计的落地 |
|---|---|
| 未打开特定视图时，无法搜索到对应关键词内容 | 两个根因：① 不在表上下文（工作区页 / 文档页）时只扫**前 8 张表**，第 9 张及以后的数据表内容永远不进入结果；② 在表上下文但 URL 无 `?view=` 时，后端仍把数据表侧**收敛到当前表**，其他表内容搜不到。修复：工作区范围（`scope=all`）覆盖全部可读表且**不按视图收敛**；只有「数据表」范围（`scope=tables`）才收敛到当前表与激活视图（保留 ADR 0012 的视图口径） |
| 构建缓存机制，便于实施快速搜索 | 新增进程内搜索结果缓存（TTL 15s + LRU 256），键含工作区 / 用户 / 范围 / 关键词 / 表 / 视图 / 上限；重复查询与范围切换直接命中，不再逐表 LIKE；写路径（单行 CRUD、批量导入、数据源同步）主动失效，批量写用短 TTL 兜底 |
| 覆盖全部内容 | 删除 `MAX_TABLES_SCAN` 截断，工作区范围内逐表扫描全部可读表；保留「总行命中 20 条即停」的展示预算，避免把面板撑爆 |

## Context

现状逐条核对（以改动前代码为准）：

| # | 现状 | 位置 | 影响 |
|---|---|---|---|
| 1 | 无表上下文时 `targets = tables[:MAX_TABLES_SCAN]`（8 张） | `services/search.py` | 工作区第 9 张及以后表的内容**永远搜不到**，且与关键词无关；这是「未打开特定视图时搜不到」的首要原因 |
| 2 | `scope=all` 仍把 `table_id` / `view_id` 下发给 `_search_tables` 并收敛到当前表/视图 | `services/search.py`、`GlobalSearch.tsx` | 范围选择器写着「工作区」，实际在表页只搜当前表；当前视图外的行也搜不到 |
| 3 | 每表 `ROWS_PER_TABLE=3`、总 `MAX_ROWS_TOTAL=20` | `services/search.py` | 命中密集时只展示前几条，特定行可能不在面板里（展示预算，非覆盖缺陷） |
| 4 | 行检索逐表 `list_rows($query)`，无任何缓存 | `services/search.py`、`core/records.py` | 每次输入（250ms 去抖后）都重新扫表；关键词不存在时扫描成本最高，重复搜索没有任何收益 |
| 5 | 单行 CRUD 通过 `log_action → record_event` 进入统一事件流；`invalidate_for_event` 已集中处理 `records` / `tables` 缓存失效 | `tables/services/core/audit.py`、`core/events.py` | 搜索结果缓存可以复用同一失效 choke point，不需要逐端点埋点 |
| 6 | 批量写 `bulk_create` / `bulk_update` / `bulk_update_rows` **不写 audit** | `tables/services/core/records.py` | 批量导入 / 数据源同步后事件失效不会触发，需显式清搜索缓存（否则陈旧窗口只能靠 TTL） |
| 7 | `$query` 只匹配 String/Text 物理列 | `tables/services/core/query.py` | 数字 / 日期 / 选项字段的关键词搜不到（本次不改，列为 P2 边界） |

设计不变量：

- **I1 权限单一**：文档沿用 FTS 可见性口径；数据表沿用 `list_rows` 的 `row_scope`、字段隐藏与软删除排除，不新增旁路。
- **I2 结果契约不变**：响应仍为 `{query, documents, tables, rows, view}`；`view` 仅在「数据表」范围且收敛到某张表时回显。
- **I3 缓存只读 + 短 TTL**：进程内缓存（与项目「SQLite 单进程」部署一致），值按只读约定使用；失效 best-effort，正确性由 15s TTL 兜底。
- **I4 覆盖优先于截断**：不再按表数量硬截断；用总行命中预算控制响应体积。
- **I5 零 schema 迁移**：P0 不改表 / 列 / 索引，无 alembic 迁移。

## Decision

### 1. 范围语义（修复「未打开视图搜不到」）

| 范围 | 数据表侧行为 | 视图收敛 | 当前表 |
|---|---|---|---|
| `all`（工作区） | 扫描全部可读表；当前表排在最前（仅排序） | **不收敛** | 仅排序优先 |
| `tables`（数据表） | 有表上下文 → 只扫当前表；无表上下文 → 全部可读表 | URL 带 `?view=` 时按该视图 filters 收敛；否则整表 | 收敛目标 |
| `documents`（文档） | 不跑数据表侧 | — | — |

前端 `GlobalSearch` 只在 `scope === 'tables'` 时下发 `view_id`；`table_id` 始终下发，但在工作区范围只用于排序。后端在 `scope=all` 时忽略 `view_id`，即使旧客户端传了也不会收窄。

### 2. 全表覆盖

`_search_tables` 删除 `tables[:MAX_TABLES_SCAN]`，`targets` 为全部可读表（当前表前置）。保留 `MAX_ROWS_TOTAL=20` 短路：行命中达到 20 条即停止扫描，面板展示上限不变。

### 3. 搜索结果缓存

- **实例**：`core/cache.py` 新增 `search_cache = TTLCache(max_entries=256, name="search")`，并接入 `invalidate_all`。
- **键**：`search | workspace_id | user_id | scope | table_id | view_id | limit | keyword`；`scope=all` 时 `view_id` 归一为 0，避免无意义的缓存分片。
- **TTL**：15s。交互搜索的重复率远高于 15s，命中后零 SQL；权限变化（如工作区角色调整）最迟 15s 生效。
- **入口**：`search_workspace` 包一层 `get → 计算 → set`，空结果同样缓存（关键词不存在是全扫的最坏情况，最需要缓存）。

### 4. 失效矩阵

| 写入 | 失效方式 | 覆盖 |
|---|---|---|
| 单行 create / update / delete / trash / restore | `log_action → record_event → invalidate_for_event` 清 `search\|{wid}` | 即时 |
| 批量导入 / 数据源同步（`bulk_create` / `bulk_update` / `bulk_update_rows`） | 写函数末尾显式清 `search\|{wid}`（best-effort） | 即时 |
| 表 / 字段 / 视图 / 行级权限变更 | `table.*` / `row_rule.*` 事件清 `search\|{wid}`；无事件路径由 TTL 兜底 | ≤15s |
| 文档创建 / 更新 / 删除 | `document.*` 事件清 `search\|{wid}`；文档写路径无事件时由 TTL 兜底 | ≤15s |
| 备份恢复 / 成员角色变更 | `invalidate_all()` 或 TTL | ≤15s |

### 5. 后续分期（方案，不在 P0 实施）

| 期 | 内容 | 触发条件 |
|---|---|---|
| **P1 行内容快照缓存** | 每张表懒构建「row_id + 文本列值」内存快照（单表 ≤2 万行 / 单工作区 ≤32MB），工作区搜索改为一次内存子串扫描；命中后按 row_id 回表走 `list_rows` 权限裁剪。失效复用 P0 事件 + 30s TTL | 可读表 >12 或单表行数 >5 万、工作区范围搜索 P95 >800ms |
| **P2 FTS5 持久行索引** | SQLite FTS5 虚拟表（`workspace_id/table_id/row_id` UNINDEXED + `content`），写路径增量维护、字段变更重建、首次搜索回填；中文子串兜底沿用文档 FTS 的两段式策略 | P1 内存超预算，或需要跨进程 / 多实例共享索引 |

P1 / P2 的取舍：FTS5 查询快但维护面大（行 CRUD、批量导入、数据源同步、字段重命名/删除、表删除、备份恢复都要同步），中文还需子串兜底；内存快照零 schema 迁移、中文天然支持，先用它承接中等规模，再按触发条件升级。

## 边界与例外

1. **展示预算仍在**：总行命中 20 条即停，命中极多时后面的表可能只剩表名结果；需要「看全部命中」应另立 ADR 做独立结果页 / 分页。
2. **`$query` 仅文本列**：数字、日期、选项字段的关键词不命中（P2 边界，不在本次改动）。
3. **缓存不跨进程**：与项目单进程部署一致；多实例部署前必须换成共享后端（`CacheBackend` 协议已预留）。
4. **权限变更延迟**：成员角色 / 表权限调整没有统一事件时，最迟 15s 后生效。

## 测试清单

- 后端 `tests/test_workspace_search.py`：10 张表时第 10 张表的行仍命中；`scope=all` 忽略 `view_id` 且能搜到视图外行；`scope=tables` 仍按视图收敛；相同查询第二次命中缓存（底层行检索只执行一次）；新建行后缓存即时失效。
- 前端 `GlobalSearch.test.tsx`：工作区范围不下发 `view_id`（无范围回显）；切到「数据表」后仍按激活视图收敛并回显范围。
- 回归：`make check-fast`、`make test`、前端 `pnpm vitest run` 定向用例。

## 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 范围语义修正 + 全表覆盖 + 结果缓存 + 事件/批量写失效 + 前后端测试 | 中（改变工作区范围的收敛行为，需同步 ADR 0012 与前端用例） |
| P1 | 行内容快照缓存（内存） | 中（内存预算与构建击穿） |
| P2 | FTS5 持久行索引 + 迁移回填 | 高（写路径维护面大） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/search.py`、`src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/core/cache.py`、`src/cndb/core/events.py`、`src/cndb/plugins/tables/services/core/records.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/api/search.ts` | `tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx` | 待提交 |
| P1 | 未开始 | `src/cndb/plugins/workspaces/services/search.py` | `tests/test_workspace_search.py` | - |
| P2 | 未开始 | `src/cndb/plugins/workspaces/services/search.py`、`src/cndb/alembic/versions/` | `tests/test_workspace_search.py` | - |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件。

## 交接（会话结束更新）

- 当前阶段：P0 已落地；P1 / P2 按触发条件实施
- 已完成：`scope=all` 改为全工作区覆盖且不按视图收敛；删除 8 张表截断；`search_cache`（15s / 256 条）与事件 / 批量写失效；前端只在数据表范围下发 `view_id`
- 下一步：工作区规模（表数 >12 或单表 >5 万行）导致工作区搜索 P95 超 800ms 时，按 P1 做行内容快照缓存；需要跨进程共享时按 P2 上 FTS5
- 已知坑：`$query` 只搜文本列（数字 / 日期 / 选项不命中）；总行命中 20 条为面板展示预算；缓存失效 best-effort，权限变化最迟 15s 生效
- 最近一次全绿：`make check-fast` + `make test`（5136 passed / 8 skipped）+ 前端定向单测 34 例（`GlobalSearch` / `MainLayout`）2026-10-21
