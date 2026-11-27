# 0187 数据表关联图（S1）

- 编号：0187
- 来源 / 提出人：用户（会话 2026-11-28）
- 日期：2026-11-28
- 关联 ADR：无（S1，方案并入本卡片；可见性 / 权限口径 H17 / H53 / H64，前端约束 H21 / H24 / H25 / H29 / H30 / H31）
- 关联前序：`docs/requirements/0168-document-knowledge-graph.md`、`0182-document-graph-explorer.md`、`0183`、`0184`（文档图谱范式，本卡复用同一套交互与视觉口径）
- 状态：**P0 已落地**（2026-11-28 用户「先P0」，只读关联图，`2250fb9c`）；**P1 已落地**（2026-11-28 用户「立项」后实现，图上编辑关联，见下方「P1 范围」）

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

## P1 范围（2026-11-28 用户「立项」）

需求原句里的「并且能够支持编辑功能」在 P0 被显式排除，P1 补回。**复用既有字段端点，不新增任何写路径**（D5）。

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| E1 | 「支持编辑功能」 | **建边**：图上「从 A 表连到 B 表」→ 在 A 表建一个 `link` 字段（`config.target_table_id=B`）。走既有 `POST /{wid}/tables/{tid}/fields`，字段名由用户填（默认 `关联<目标表名>`），重名由后端既有 400 透出 | `TableLinkGraphPage.tsx` | 前端单测：连线提交 payload 正确（`field_type=link` / `target_table_id` / `multiple`）；后端用例不改即绿 |
| E2 | 「支持编辑功能」 | **改边**：Inspector 里改这条边的字段名 / 允许多选 → `PATCH /fields/{fid}`；**改目标表另走 E2′**（见 D6） | 同上 | 前端单测：PATCH payload 只含变化的键 |
| E2′ | （E2 派生） | **改目标表**：`PATCH` 改 `config.target_table_id` 时，**关联物理表里的存量行若指向新目标表中不存在的行 id，必须先给出影响面并要求显式 `force`**，否则拒绝（避免静默留下悬空关联） | `routers/fields.py`、`services/core/link_graph.py` | 后端用例：无 `force` 且存在失效行 → 400 且提示行数；带 `force` → 200 且悬空关联被清理 |
| E3 | 「支持编辑功能」 | **删边**：Inspector 里删这条关联字段 → `DELETE /fields/{fid}`；二次确认文案写明「会一并删除该字段承载的关联数据」 | 同上 | 前端单测：二次确认后才发请求 |
| E4 | 「结合最佳实践」 | **两步点击连线**（点源表 → 点目标表），**不做拖拽连线**：力导向下拖拽与节点拖动冲突，移动端也不可用（D5） | 同上 | 前端单测：第一步进「连线中」态、ESC / 点空白取消 |
| E5 | 「直观地表述」 | 编辑权限单一来源：后端 `build_link_graph` 在节点 / 边上带 `can_edit`（复用 `EDIT_SCHEMA`），前端**只按该位显隐入口**，不另算权限 | `link_graph.py`、`types/tables.ts` | 后端单测：viewer 的 `can_edit=false`；前端单测：`can_edit=false` 时编辑入口不渲染 |
| E6 | （一致性） | 写后即见：复用 P0 的 `_invalidate_link_graph`（字段增删改三处已挂），前端成功后 `invalidateQueries` 立即重取 | 既有 | 前端单测：成功后调用了 invalidate |
| E7 | （设计 / 测试 / 文档） | 只用 `--cn-*` token、断点仍只 767.98 / 575.98px；同轮补后端 + 前端单测；CHANGELOG 增条目 | 新代码、测试、`CHANGELOG.md` | `make flow` / `make check-frontend` 全绿 |

**P1 不做**（避免范围蔓延，见 ADR 0187 D6）：

- 拖拽连线建边（D5 已否决：与力导向节点拖动冲突、移动端不可用）。
- 在图上直接选「关联目标行」（那是行级数据操作，属数据面，图只看结构）。
- 修改已有边的「引用字段（lookup）」集合——那是字段面板的职责，图上只改名字 / 多选 / 目标表。
- 批量连线、连线模板、跨工作区连线的申请流。

## 不做（P1 之后仍排除）

- 节点坐标 / 备注的持久化（P2，需新表 + 迁移 + `backup_io`，届时升 S2 补 ADR）。
- 跨工作区关联的申请流、关联关系的历史审计。
- 行级数据预览（图上只看结构，不看行）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] P0 范围已由需求方确认（「先P0」）
- [x] P1 范围已由需求方确认（「立项」，2026-11-28）
- [x] P1 方案评审通过并实现（ADR 0187 D5–D8，2026-11-28）

## 落地结果

- 代码落点：
  - 后端 `plugins/tables/services/core/link_graph.py`（新增：`build_link_graph` / `invalidate_link_graph_cache` / `reset_link_graph_cache`，30s 缓存 + 上限 500 + 可读表过滤 + 外部 / 已删目标聚合）、`plugins/tables/routers/tables.py`（`GET /link-graph`，静态段先于 `/{table_id}`）。
  - 失效点：`_invalidate_table_list_cache`（表 CRUD）、`routers/fields.py`（字段 CRUD / 排序）、`routers/groups.py`（分组改名 / 删除）。
  - 前端 `api/tables.ts`（`linkGraph` + 类型）、`pages/tables/TableLinkGraphPage.tsx`（新增，echarts graph/force 独立 lazy chunk、单击选中 / 双击打开、Inspector、图例、孤岛 / 枢纽、聚焦 BFS、缩放 / 复位）、`pages/tables/TableLinkGraphPage.css`（新增，随页 chunk）、`App.tsx`（路由）、`layouts/MainLayout.tsx`（二级页签「关联图」+ 激活态 + `TABLE_LEVEL_TAB_PATHS`）。
- 测试：后端 `tests/test_tables_link_graph.py`；前端 `pages/tables/TableLinkGraphPage.test.tsx` + `MainLayout.test.tsx` 页签顺序用例同步。
