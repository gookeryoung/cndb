# 性能优化（第一批）

## 范围

前后端五项低风险优化：HTTP gzip、SQLite WAL pragmas、物理表反射缓存、Grid 单元格 memo、报表编辑器按需加载。lookup 过滤下推与物理表二级索引为后续批次（见文末未实现项）。

## 接口定义

### core/database.py

- `register_sqlite_pragmas(engine) -> None`：为 SQLite 引擎注册 connect 监听器；非 sqlite 方言无操作。监听器按序执行：
  1. `PRAGMA busy_timeout=5000` —— 写锁竞争时等待而非立即报 database is locked；
  2. `PRAGMA cache_size=-20000` —— 页缓存提升到 20MB；
  3. `PRAGMA journal_mode=WAL` —— 读写不互斥；失败仅记 warning 不阻断连接，且失败时不设置 synchronous（保持默认 FULL）；
  4. `PRAGMA synchronous=NORMAL` —— 仅 WAL 生效时设置。
- 模块级 engine 创建后立即注册。CLI 一次性引擎（seed/backup/restore）与测试临时引擎不注册，生产请求路径统一走 `core.database.engine`。

### tables/services/core/ddl.py

- `get_reflected_table(engine, db_table_name, *, missing_message=None) -> Table`：反射结果按 engine（WeakKeyDictionary 弱引用）→ 表名两级缓存；同一 engine 下同名表复用同一 Table 对象。表不存在时抛 RuntimeError，文案取 `missing_message`（缺省 `物理表 {db_table_name} 不存在`）。
- `invalidate_reflected_table(db_table_name: str | None = None) -> None`：失效缓存；None 时全量清空。
- 接入点（保持各调用方原错误文案与优雅降级语义）：
  - `records._get_sa_table`（文案 `物理表 X 不存在，请先调用 create_table()`）；
  - `links._get_link_sa_table`（文案含 `关联物理表`）与 `links._get_sa_table_by_name`；
  - `lookups` 源表值读取的反射（前置 inspect 存在性守卫保留）；
  - `field_ops._sync_select_options`（表缺失时 warning 跳过，不抛错）。

### 失效契约

`invalidate_reflected_table` 由 ddl.py 内每个变更物理结构的函数在成功路径末尾调用：`create_table`、`add_column`、`drop_column`、`drop_table`、`create_link_table`、`drop_link_table`、列重建函数。唯一索引函数（`add_unique_constraint`/`drop_unique_constraint`）不改变列结构，不失效。

### GridCell Props（新增）

- `onCellSave?: (rowId, fieldName, value) => Promise<unknown>`：`onSave` 的稳定引用替代版，GridCell 内部组合 rowId 调用；`onCellSave` 优先于 `onSave`，两者皆缺省时单元格不可编辑（与原 onSave 缺省语义一致）。
- GridCell 默认导出改为 `memo` 包装；`buildColumns` 普通单元格分支改传 `onCellSave`（消除逐渲染新建的行级适配闭包），行内编辑受控分支保持原 props。`onSave` 路径保留给 PublicSharePage 等静态调用方。

### ReportsPage 懒加载

- `ReportTemplateEditor` / `PreviewPanel` / `SyntaxHelpPanel` 改为 `React.lazy`，三者共用同一 barrel 动态 import（落在同一按需 chunk）；编辑器页签内容包 `Suspense`，fallback 为居中 `Spin`。
- `React.lazy` 的 factory 必须以 `.then(m => ({ default: m.X }))` 返回 `{ default: Component }` 形态——React 内部仅读取 resolved 值的 `default` 字段，直接返回组件函数会解析为 undefined 并卸载整棵 React 树。
- barrel `@/components/report-editor` 的静态导出不变，其余调用方不受影响。

## HTTP 压缩

- `GZipMiddleware(minimum_size=1024)` 注册在 `CORSMiddleware` 之后（最外层）。静态资源与 API JSON 统一压缩；流式响应（报表下载）同样压缩——xlsx/docx 自身已压缩，收益趋零但无害，如需精确排除再切换预压缩方案。

## 数据模型

无 schema 变更。WAL 是 SQLite 文件持久属性：运行期出现 `-wal`/`-shm` sidecar 属预期；备份走 `sqlite3.Connection.backup()`（快照含 WAL 内容）不受影响；`_reset_sqlite_database` 已清理 sidecar 文件后整文件覆盖。

## 算法与流程

- 请求路径 list_rows / 行 CRUD 每次调用的 `MetaData().reflect` 全部改为缓存读取；缓存键含 engine，多测试引擎互不串扰，engine 回收后缓存随弱引用释放。
- seed 的 `synchronous=OFF` 监听器在主 pragma 监听器之后注册（同事件监听器按注册序执行），seed 期间 OFF 覆盖 NORMAL，卸载后新建连接恢复 NORMAL，既有加速语义不变。

## 异常处理

- `journal_mode=WAL` 切换失败（锁竞争/文件系统不支持）：记 warning，本次连接沿用默认日志模式，synchronous 保持默认。
- 反射缓存未命中且表不存在：按调用方原错误文案抛 RuntimeError，错误语义与缓存化前一致。

## 看板切换渲染性能（F4）

- **根因**：KanbanView 根容器仅有 `minHeight: 300` 无高度约束，列随内容生长到全高 → 列内 `overflowY: auto` 永不滚动、`useVirtualizer` 视口测量失效（视口=全量内容）；叠加虚拟化阈值 100，真实数据（500 行产品开发表按片区/项目类别分组）单列 60-90 行全部走非虚拟分支 → 切换视图时同步全量挂载 500 张重型 antd 卡片（Tag/Tooltip/Progress），主线程长任务卡顿。
- **修复契约**：
  - KanbanView 根容器 `flex: 1, minHeight: 300`——作为 GridPage 主内容区（column flex）的 flex item 占满剩余高度，列高度受约束；卡片列表滚动容器加 `minHeight: 0` 允许在 flex column 内收缩，内容超高时列内滚动而非撑开整列。
  - 列内虚拟化阈值 100 → 30：单列 ≥ 30 行启用虚拟滚动（估算高度 + `measureElement` 动态修正），30 行以下全量渲染。
  - GridPage `handleDeleteCard` / `handleToggleDone` 的 `useCallback` 依赖改用 `mutate`（React Query 保证稳定）而非 mutation 结果对象——结果对象每渲染都是新引用，会使回调每渲染重建、`KanbanCard` 的 memo 全部失效并全量重渲染。
- **回归测试**：KanbanView.test.tsx「大数据量渲染性能」——90 行单列（低于旧阈值、超过新阈值）断言挂载卡片数 < 50；jsdom 下虚拟器视口为 0，仅渲染窗口内条目，断言确定性成立。

## 实现状态

- [x] F1 后端 GZipMiddleware（app.py，`minimum_size=1024`）
- [x] B1 SQLite WAL 三连 pragma（core/database.py `register_sqlite_pragmas`）
- [x] B2 物理表反射缓存 + DDL 失效钩子（ddl.py `get_reflected_table` / `invalidate_reflected_table`，records/links/lookups/field_ops 接入）
- [x] F2 GridCell memo + props 稳定化（onCellSave 契约，buildColumns 普通分支改传）
- [x] F3 报表编辑器 React.lazy + Suspense（ReportsPage，编辑器独立按需 chunk）
- [x] F4 看板切换渲染性能（KanbanView 高度约束 + 虚拟化阈值 30 + GridPage 回调稳定化）

## 待实现（后续批次）

- [ ] lookup 过滤/排序两阶段下推：先以 link 关联表 + 源表 SQL 求满足条件的 row_id 集，再按 id 集分页取整行，attach 仅作用于当页
- [ ] 动态物理表二级索引：需先确定高频过滤字段清单，与反射缓存失效钩子共用 DDL 入口
