# 0187 数据表关联图（S1）

- 编号：0187
- 来源 / 提出人：用户（会话 2026-11-28）
- 日期：2026-11-28
- 关联 ADR：无（S1，方案并入本卡片；可见性 / 权限口径 H17 / H53 / H64，前端约束 H21 / H24 / H25 / H29 / H30 / H31）
- 关联前序：`docs/requirements/0168-document-knowledge-graph.md`、`0182-document-graph-explorer.md`、`0183`、`0184`（文档图谱范式，本卡复用同一套交互与视觉口径）
- 状态：**P0 已确认并落地**（2026-11-28 用户「先P0」，即只做只读关联图；编辑能力 E1/E2 见下方「不做」）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码（H26）。

## 需求原句（逐字）

> 数据表，增加关联图板块，用于直观地表述数据表之间的相互引用关系，并且能够支持编辑功能。请结合最佳实践给出可行的方案。

> 先P0

## 背景（现状核实，非推测）

| # | 事实 | 位置 |
|---|---|---|
| 1 | 表间关系唯一载体是 `link` 字段：`config.target_table_id`，物理关系存独立关联表，`has_physical_column=False` | `plugins/tables/field_types/relation.py` |
| 2 | `lookup` 是 link 的投影列（`via_link_field_id` + `source_field_id`），不产生新边 | `plugins/tables/field_types/lookup.py` |
| 3 | 关系数据分散在每张表的字段列表里，没有任何聚合读接口（`routers/tables.py` 只有一行「表关系图」占位注释） | `plugins/tables/routers/tables.py:739` |
| 4 | 已有成熟的图谱可视化范式（力导向 + Inspector + 聚焦 + 缓存失效） | `frontend/src/pages/documents/DocumentGraphPage.tsx` |

**核心缺口**：用户无法一眼看出「谁引用了谁、绕了几跳、有没有孤儿表」，也没有任何可视化的关系总览。

## 可实施约束（C1..Cn，P0 范围）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「增加关联图板块」 | 新增 `GET /api/v1/workspaces/{wid}/tables/link-graph`，返回 `{nodes, edges, external, truncated, total, edges_out_of_view}`；零新表、零迁移 | `tables/routers/tables.py`、`tables/services/core/link_graph.py`（新增） | 接口单测断言节点 / 边结构与字段 |
| C2 | 「相互引用关系」 | 边 = **未回收的 `link` 字段**（`lookup` 不建边，只计入 `reference_field_count`）；自关联字段不画自环，改标节点 `self_loop=true` | `link_graph.py` | 单测：lookup 不产生边；自关联节点带标记且无自环边 |
| C3 | 「直观地表述」 | 节点 = 当前用户**可读**的非回收表（复用 `preload_table_access` + `TableAction.READ`）；不可读的表既不建节点也不做边端点 | `link_graph.py` | 单测：viewer 看不到无读权表；H64 用例不改即绿 |
| C4 | 「表之间的引用」跨区口径 | 指向其他工作区的 link 目标**不返回表名**，聚合为虚拟节点（负 id）+ 虚线边；指向本工作区已回收表的同样聚合。不泄漏存在性（H17 / H53） | `link_graph.py` | 单测：响应体不含他区表名；`target_state` 取值正确 |
| C5 | 「直观地表述」规模 | 节点上限默认 500（按 `order` / `id` 取前 N），超出 `truncated=true`；指向窗口外可读表的边计入 `edges_out_of_view` | `link_graph.py` | 单测：小 `max_nodes` 下 `truncated` 与 `edges_out_of_view` |
| C6 | 「直观地表述」（一致性） | 聚合结果按 `(workspace_id, user_id, max_nodes)` 缓存 30s；字段增删改、表增删改 / 移动 / 回收站、分组变更后**显式失效**（0182 C1 教训：只靠 TTL 会被当成「保存没生效」） | `link_graph.py` + 三处写路径 | 单测：建关联字段后立刻读图能看到新边 |
| C7 | 「板块」入口 | 数据表模块工作区级页签「关联图」（`/w/:wid/tables/graph`），静态段路由注册在 `tables/:tid` 之前；支持 `?focus=<tid>&depth=1\|2` 局部图 | `App.tsx`、`MainLayout.tsx` | `MainLayout.test.tsx` 页签顺序与跳转；页面单测断言 BFS |
| C8 | 「结合最佳实践」 | 前端复用 0168/0182/0183/0184 已收敛的口径：单击选中 + 双击打开、Inspector、图例显隐、孤岛 / 枢纽清单、标签按倍率淡化、缩放以容器中心为锚、`labelLayout.hideOverlap`、SVG renderer、独立 lazy chunk | `pages/tables/TableLinkGraphPage.tsx`（新增） | 页面单测 + `make frontend-static`（H31） |
| C9 | （设计 / 测试 / 文档约束） | 只用 `--cn-*` token；断点仅 767.98 / 575.98px；样式随页 CSS 走（BUNDLE_BUDGET 第 ① 类）；同轮补后端 + 前端单测；CHANGELOG 增条目 | 新页面样式、测试文件、`CHANGELOG.md` | `make flow` / `make check-frontend` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 表列表缓存失效点 | `routers/tables.py::_invalidate_table_list_cache` | 建 / 改 / 删 / 复制 / 移动 / 排序 / 回收站都经此处，作为图缓存失效锚点 |
| 2 | 字段写路径 | `routers/fields.py`（create / update / delete / reorder） | 关联字段变更的唯一入口 |
| 3 | 表分组 | `routers/groups.py` | 分组名进节点载荷，改名 / 删除影响图 |
| 4 | 工作区二级页签 | `layouts/MainLayout.tsx::secondaryTabItems` | 新增「关联图」 |
| 5 | 前端 API 封装 | `api/tables.ts` | 新增 `tableApi.linkGraph` |
| 6 | 前端路由 | `App.tsx` | `w/:wid/tables/graph`（静态段先于 `:tid`） |

## 决策（并入本卡的 S1 方案）

- **D1 零新表**：关系已由 `link` 字段完整表达，聚合只读元数据（不扫行、不 JOIN 关联表），无迁移、无备份改动（H13 / H14 不受影响）。
- **D2 lookup 不建边**：同一关系画两遍会让图变成噪声；`lookup` 只作为边上的 `reference_field_count` 展示。
- **D3 外部 / 已删目标聚合**：跨工作区与已回收目标一律虚拟节点（负 id），不带表名 —— 与文档图谱 `broken` 虚拟节点同范式。
- **D4 编辑留到 P1**：图上的建 / 改 / 删边复用现有 `POST/PATCH/DELETE .../fields` 端点，属独立分期；P0 只读，节点载荷已带 `can_edit`（按 `EDIT_SCHEMA` 计算）供 P1 直接消费，不新增权限口径。

## 不做（P0 明确排除）

- 图上创建 / 修改 / 删除关联（P1 E1/E2，复用字段端点，不新增写路径）。
- 节点坐标 / 备注的持久化（P2，需新表 + 迁移 + `backup_io`，届时升 S2 补 ADR）。
- 跨工作区关联的申请流、关联关系的历史审计。
- 行级数据预览（图上只看结构，不看行）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] P0 范围已由需求方确认（「先P0」）

## 落地结果

- 代码落点：
  - 后端 `plugins/tables/services/core/link_graph.py`（新增：`build_link_graph` / `invalidate_link_graph_cache` / `reset_link_graph_cache`，30s 缓存 + 上限 500 + 可读表过滤 + 外部 / 已删目标聚合）、`plugins/tables/routers/tables.py`（`GET /link-graph`，静态段先于 `/{table_id}`）。
  - 失效点：`_invalidate_table_list_cache`（表 CRUD）、`routers/fields.py`（字段 CRUD / 排序）、`routers/groups.py`（分组改名 / 删除）。
  - 前端 `api/tables.ts`（`linkGraph` + 类型）、`pages/tables/TableLinkGraphPage.tsx`（新增，echarts graph/force 独立 lazy chunk、单击选中 / 双击打开、Inspector、图例、孤岛 / 枢纽、聚焦 BFS、缩放 / 复位）、`pages/tables/TableLinkGraphPage.css`（新增，随页 chunk）、`App.tsx`（路由）、`layouts/MainLayout.tsx`（二级页签「关联图」+ 激活态 + `TABLE_LEVEL_TAB_PATHS`）。
- 测试：后端 `tests/test_tables_link_graph.py`；前端 `pages/tables/TableLinkGraphPage.test.tsx` + `MainLayout.test.tsx` 页签顺序用例同步。
