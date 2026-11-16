# ADR 0137: 数据表分组（侧栏与列表均可用，默认不分组）

Status: Implemented（2026-11-16 用户确认「按默认」后落地）
Date: 2026-11-16
Related: `src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/schemas/models.py`、`src/cndb/plugins/tables/routers/groups.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/alembic/versions/c9d0e1f2a3b4_add_table_groups.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/api/{tables.ts,types/tables.ts}`
需求卡片: `docs/requirements/0137-table-groups.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「数据表提供分组功能」 | 新增 `tables_tablegroup`（`workspace_id` / `name` / `order`）；表用 `DataTable.group_id`（可空）归属；端点 `GET|POST /table-groups`、`PATCH|DELETE /table-groups/{id}`、`POST /table-groups/reorder` |
| C2 | 「默认不分组」 | `group_id` 可空、建表默认空；列表页「分组显示」默认关、不持久化；删除分组把成员表显式置 `NULL`，不删表；每个工作区一条 `is_ungrouped` 占位分组行参与排序 |
| C3 | 「侧边栏…可用」 | 侧栏 Menu：无分组 / 折叠态平铺；有分组时 `type: 'group'` 标题（含「未分组」占位，按 order 位置），搜索时隐藏空分组；owner/editor 可拖拽分组标题排序（HTML5 DnD → `POST /table-groups/reorder`） |
| C4 | 「列表…可用」 | 列表页 `Switch` 分组开关：关闭=现有平铺 + 全局拖拽；打开=按组分节 + 组内拖拽（只重排该组占用的全局槽位） |
| C5 | （权限） | 读 `VIEWER`；写 `EDITOR`；表的分组归属沿用表 `EDIT_SCHEMA`；分组必须属于同一工作区，否则 400 |
| C6 | （唯一性） | 名去空白、1..80 字符、工作区内唯一；重名 400 |
| C7 | （备份） | v16 归档 `backup.json` 增加 `table_groups` 与 `tables[].group_id`；恢复先建组并做旧 id → 新 id 映射；`clear_workspace_content` 同步清分组；v8 JSON 出口剔除分组键 |
| C8 | （兼容） | 无数据回填（存量表即未分组）；表 CRUD / 记录读写口径不变；新增样式全部 `--cn-*` token |

## Context

现状（改造前）：

| # | 现状 | 位置 | 影响 |
|---|---|---|---|
| 1 | 表只有 `order` / `trashed`，工作区内平铺 | `tables/models.py:144` | 表一多只能靠搜索找，无法按业务域归类 |
| 2 | 侧栏直接 `orderedTables.map` 成 Menu 项 | `MainLayout.tsx` `renderTableNav` | 无分组语义 |
| 3 | 表列表页平铺 + 全局拖拽排序 | `TablesList.tsx` | 同上 |
| 4 | 工作区备份按表逐个导出 | `workspace_backup.py`、`backup_io.py` | 无分组资源可导 |

核心缺陷：缺少「工作区级表分组」这一层，用户无法把几十张表按业务域收拢，侧栏与表目录都只能一长串平铺。

## Decision

### 1. 数据模型

- 新表 `tables_tablegroup`：`id`、`workspace_id`（FK CASCADE）、`name`（80）、`order`、`is_ungrouped`、时间戳；唯一约束 `(workspace_id, name)`。
- 「未分组」为系统占位行（`is_ungrouped=True`，名称 `__ungrouped__`）：每个工作区一条、懒创建（`GET /table-groups`），参与 `order` 排序，不允许改名 / 删除 / 用户创建同名分组；未分组表 `group_id` 仍为 `NULL`。
- `tables_datatable.group_id`：可空 FK `ON DELETE SET NULL`，建索引。
- 迁移 `c9d0e1f2a3b4`（可重入），down_revision `e3f4a5b6c7d8`。

### 2. 判定与权限（唯一入口）

- 分组读写统一走 `check_workspace_permission`：`VIEWER` 读、`EDITOR` 写。
- 表的 `group_id` 在 `POST /tables` 与 `PATCH /tables/{id}` 中由 `_validate_group_id` 校验同工作区；跨工作区移动表时 `group_id` 置空。
- 删除分组：`UPDATE tables_datatable SET group_id = NULL WHERE group_id = ?` 后删除分组，并失效表列表缓存。

### 3. 前端

- 侧栏（`MainLayout`）：`useQuery(['workspaces', wid, 'table-groups'])`；`buildTableMenuItems(mobile, collapsed)` 无分组 / 折叠 → 平铺，否则按组标题 + 「未分组」。
- 列表页（`TablesList`）：
  - 分组开关默认关（不持久化），关闭时行为与改造前一致（含分页与全局拖拽）。
  - 打开时按 `groups` 顺序分节（未分组恒在最后），组内拖拽通过「组内 ids → 全局 order 槽位回填」保持其它表位置不变。
  - 行菜单「移动到分组」与「分组管理」弹窗（建组 / 改名 / 上移下移 / 删除）要求 owner/editor。
- API：`tableGroupApi.list/create/update/remove/reorder`；类型 `TableGroup`、`TableSummary.group_id`、`TableCreate/Update.group_id`。

### 4. 备份

- 导出：`table_groups`（旧 id / name / order）+ `tables[].group_id`（旧分组 id）。
- 恢复：先按名复用或新建分组建立 `group_id_map`，再建表并回填新 `group_id`；旧版备份缺键 → 未分组。
- `clear_workspace_content` 在删表后清空该工作区分组。

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/models.py`、`src/cndb/alembic/versions/c9d0e1f2a3b4_add_table_groups.py`、`src/cndb/alembic/versions/d1e2f3a4b5c6_add_ungrouped_group_marker.py`、`src/cndb/plugins/tables/routers/groups.py`、`src/cndb/plugins/tables/routers/tables.py` | `tests/test_table_groups.py` | 未发布 |
| P1 | 已落地 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/api/tables.ts` | `frontend/src/layouts/MainLayout.test.tsx`、`frontend/src/pages/workspace/TablesList.test.tsx` | 未发布 |
| P2 | 已落地 | `src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/workspace/TablesList.tsx` | `tests/test_table_groups_backup.py`、`frontend/src/pages/workspace/TablesList.test.tsx` | 未发布 |

## 交接

- 当前阶段：P0-P2 已全部落地。
- 下一步：观察使用反馈；候选增强为侧栏分组折叠记忆、跨组的「拖表入组」手势、分组颜色，均未开始。
- 已知坑：
  - `TableGroup` 名唯一性靠接口预检 + 唯一约束；并发同时建同名会由 DB 抛错（未转 400 文案）。
  - 列表页分组模式下分页器隐藏（按组全量渲染），表数极大时需评估。
  - 侧栏分组标题依赖 antd `Menu` 的 `type: 'group'`，折叠态不展示标题（保持图标平铺）。
