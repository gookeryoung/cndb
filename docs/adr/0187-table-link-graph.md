# ADR 0187: 数据表关联图（link 关系聚合可视化；P0 只读 + P1 图上编辑）

Status: Accepted（2026-11-28 用户确认「先P0」并验收 P0；同日「立项」P1 并评审通过、已落地；仅剩 P2 未开始，故未置 Implemented）
Date: 2026-11-28
Related: `src/cndb/plugins/tables/services/core/link_graph.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/tables/routers/groups.py`、`frontend/src/pages/tables/TableLinkGraphPage.tsx`、`frontend/src/api/tables.ts`、`frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx`
需求卡片: `docs/requirements/0187-table-link-graph.md`（需求原文与约束编号的唯一副本）
上游：ADR 0168 / 0182 / 0183 / 0184（文档图谱范式，交互与视觉口径复用）、ADR 0131（lookup 投影口径）、ADR 0004 / 0153 / 0161（可见性与权限判定）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；约束编号 C1..C9 一律引用卡片，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「增加关联图板块」 | `GET /{wid}/tables/link-graph`（`routers/tables.py`，静态段先于 `/{table_id}` 注册）；聚合在 `services/core/link_graph.py`，零新表、零迁移（D1） |
| C2 | 「相互引用关系」 | 边 = 未回收 `link` 字段；`lookup` 只计 `reference_field_count` 不建边（D2）；自关联标 `self_loop=true` 不画自环 |
| C3 | 「直观地表述」 | 节点 = 当前用户可读的非回收表（复用 `preload_table_access` + `TableAction.READ`，H64）；不可读表不建节点不做边端点（H17） |
| C4 | 「表之间的引用」跨区口径 | 指向其他工作区（虚拟 id `-1`）/ 本区已回收或无权读取（虚拟 id `-2`）的目标聚合为虚拟节点，响应体不含目标表名（H53 / H17） |
| C5 | 「直观地表述」规模 | 节点上限 500（`LINK_GRAPH_MAX_NODES`），超出 `truncated=true`；指向窗口外可读表的边计入 `edges_out_of_view`（0182 C2 同口径） |
| C6 | 「直观地表述」（一致性） | 结果按 `(workspace_id, user_id, max_nodes)` 缓存 30s（上限 256 条）；表 CRUD / 字段 CRUD / 分组改名删除后显式失效（0182 C1 教训） |
| C7 | 「板块」入口 | 数据表模块工作区级页签「关联图」（`/w/:wid/tables/graph`）；支持 `?focus=<tid>&depth=1|2` 局部图（前端 BFS） |
| C8 | 「结合最佳实践」 | echarts graph/force + SVG renderer + `labelLayout.hideOverlap` + 单击选中 / 双击打开 + Inspector + 图例显隐 + 孤岛 / 枢纽清单 + 缩放以容器中心为锚（复用 0182/0183/0184 已收敛口径），独立 lazy chunk（H31） |
| C9 | （设计 / 测试 / 文档约束） | 样式随页 CSS（BUNDLE_BUDGET 第 ① 类）；同轮补后端 + 前端单测；CHANGELOG 增条目 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 表间关系唯一载体是 `link` 字段（`config.target_table_id`） | `plugins/tables/field_types/relation.py` | 关系数据已在，无需新表 | 确认（C1） |
| 2 | `lookup` 是 link 的投影列（`via_link_field_id`） | `plugins/tables/field_types/lookup.py` | 不产生新边，只加语义 | 确认（C2 / D2） |
| 3 | 关系数据分散在每张表字段列表里，无聚合读接口 | `routers/tables.py:739`（空占位注释） | 用户看不到全局引用关系 | 确认（C1） |
| 4 | 已有成熟的图谱可视化范式与交互结论 | `pages/documents/DocumentGraphPage.tsx` | 可整套复用交互口径 | 确认（C8） |
| 5 | 表列表页已批量判定可读表 | `routers/tables.py::_list_tables_uncached` | 节点集合判定直接复用 | 确认（C3） |
| 6 | 跨工作区 link 天然允许（`target_table_id` 只校验存在） | `routers/fields.py:169` | 图必须处理跨区目标且不泄名 | 确认（C4） |

**核心缺陷（需求要补的）**：关系数据完整存在但没有任何聚合视图，用户无法回答「谁引用了谁、绕了几跳、有没有孤儿表」。

设计目标（不变量）：

- **I1 不泄存在性**：当前用户不可读的表既不建节点也不做边端点；跨区 / 已删 / 无权目标一律聚合虚拟节点，响应体不含目标表名。
- **I2 写后即见**：任何改变节点 / 边集合的写路径（表 CRUD、字段 CRUD、分组变更）后立即失效关联图缓存，不让用户等 TTL。
- **I3 单一聚合入口**：图数据只从 `build_link_graph` 出，前端不自己扫字段列表拼图。

## Decision

### 1. 数据模型

零新表、零迁移：关系已由 `link` 字段（`tables_datafield.config.target_table_id` + 独立关联物理表）完整表达，聚合只读元数据。

### 2. 判定算法（唯一入口）

`link_graph.build_link_graph(db, workspace_id, user, max_nodes=500)`：

1. 取工作区非回收表，经 `preload_table_access` 按 `READ` 过滤 → 节点候选；
2. 窗口内表的字段一次查回：`link` → 边，`lookup` → 按 `via_link_field_id` 聚合 `reference_field_count`；
3. 边目标分类：本区可读存活 → `ok`；其他工作区 → 虚拟 `-1`（`other_workspace`）；已回收 / 不存在 / 无权读取 → 虚拟 `-2`（`trashed` / `restricted`）；自指 → 不建边，标 `self_loop`；
4. 超窗口的可读目标计入 `edges_out_of_view`；缓存 30s（键含 user 身份与 max_nodes）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/link-graph` | 新增（成员可读，H64 口径） |

### 4. 边界与例外

1. 目标表 `trashed` 与「目标存在但用户无 `READ`」都归虚拟 `-2`，`target_state` 分别为 `trashed` / `restricted`（不区分会让 owner 与 viewer 看到不同的图，属预期：可见性即视图）。
2. `max_nodes` 请求参数夹取 `[1, 500]`。
3. 分组名进节点载荷（`group_id` / `group_name`），「未分组」占位行名不外露。
4. 编辑能力（图上建 / 改 / 删边）留 P1，复用既有 `POST/PATCH/DELETE .../fields`，不新增写路径。

### 5. 迁移

无（零新表零列）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/tables.ts`、`types/tables.ts` | `tableApi.linkGraph` + `LinkGraph*` 类型 |
| 页面 | `frontend/src/pages/tables/TableLinkGraphPage.tsx` + `.css` | 新增（echarts lazy chunk，样式随页走） |
| 路由 | `frontend/src/App.tsx` | `w/:wid/tables/graph`（静态段先于 `:tid`） |
| 导航 | `frontend/src/layouts/MainLayout.tsx` | 工作区级页签「关联图」+ 激活态 + `tablesDerivedActive` 收敛窗口 |

### 7. 测试清单

**判定层（单测）**：`tests/test_tables_link_graph.py` —— 节点 / 边结构、lookup 不建边、自关联、跨区 / 已删 / 无权目标聚合与不泄名（I1）、截断与 `edges_out_of_view`、写路径缓存失效（I2）、缓存按工作区隔离。

**接口层**：同文件（HTTP 路径、静态段先于 `/{table_id}`）。

**前端**：`TableLinkGraphPage.test.tsx`（option 结构 / 选中与跳转 / 聚焦 BFS / 筛选 / 图例 / Inspector / 标签淡化 / 缩放锚点 / 截断提示）+ `MainLayout.test.tsx`（页签顺序）。

**e2e（前端）**：P1 编辑能力落地时一并补（只读版不做 e2e）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 只读关联图（本 ADR 全部内容） | 低 |
| **P1** | 图上建 / 改 / 删边（复用字段端点 + 二次确认 + 写后失效）；新增 `can_edit` 判定位与「改目标表」的影响面拦截 | 中 |
| **P2** | 布局 / 备注持久化（需新表 + 迁移 + `backup_io`，届时另行评审） | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 关系数据要不要新表 | 零新表：link 字段已完整表达关系，聚合只读元数据（不扫行、不 JOIN 关联表） | 现状核实 #1 | 「关系快照表」（写入成本 + 备份复杂度，无消费方） | `services/core/link_graph.py` |
| D2 | lookup 是否建边 | 不建边，只计 `reference_field_count`；同一关系画两遍是噪声 | ADR 0131 投影口径 | 「lookup 画虚线边」（信息重复，图变线团） | `build_link_graph` |
| D3 | 跨区 / 已删目标怎么画 | 聚合虚拟节点（负 id），不带目标表名 | I1 / H17 / H53 | 「逐目标建断链节点」（泄漏表名与存在性） | `_build_payload` |
| D4 | 图缓存失效策略 | 显式失效（写路径调用）+ 30s TTL 兜底 | 0182 C1 教训：只靠 TTL 会被当成「保存没生效」 | 「纯 TTL」（已知坑） | `invalidate_link_graph_cache` + 三处写路径 |
| D5 | 编辑交互载体 | P0 只读；P1 复用字段端点，两步点击连线（不与力导向拖拽冲突） | 0182 C6 单击 / 双击分离结论 | 「拖拽连线建边」（与节点拖拽冲突、移动端不可用） | — |
| D6 | P1 是否新增写路径 | 不新增：建 / 改 / 删边一律走既有 `POST/PATCH/DELETE .../fields`，图页只做「表单预填 + 提交」 | 需求卡片 P1「复用字段端点」；0130 插件边界 | 「新增 `/link-graph/edges` 写端点」（与字段 CRUD 双写、权限口径要维护两套） | `TableLinkGraphPage.tsx` |
| D7 | 改「目标表」要不要拦 | **要**：`PATCH` 改 `config.target_table_id` 时，关联物理表里指向旧目标、且在新目标中不存在（或已软删）的行，必须先给出影响行数并要求显式 `force`，否则 400 拒绝 | **2026-11-28 实测**：把 link 目标从 B 改到 C（C 无行）后 PATCH 返回 200，关联物理表存量行原样保留，读取侧静默回退为 `#1`——悬空关联无任何提示 | 「静默放行，靠读侧回退兜底」（用户看不到数据已失效）；「自动清理全部悬空行」（破坏性且不可逆，无二次确认） | `routers/fields.py::update_field` |
| D8 | `can_edit` 怎么算 | 后端在节点上带 `can_edit`（该表 `EDIT_SCHEMA`）与 `can_connect`（同时可写源表 schema），前端只按位显隐；边上的编辑入口取源表的能力 | H64 单一判定入口 | 「前端按 workspace role 自己算」（与后端判定漂移，H64 违规） | `services/core/link_graph.py` |

## Consequences

- **正向**：零迁移拿到全局引用视图；交互与文档图谱同范式，学习成本为零；P1 编辑复用既有字段端点，不新增写路径与权限口径。
- **负向**：图数据按用户身份缓存（同工作区多身份各占条目）；P1 落地前「图上不能改」是已知限制。
- **勘误（2026-11-28）**：P0 的 Consequences 曾写「节点载荷已带 `can_edit` 语义位（P1 直接消费）」，实际 P0 代码未实现该字段——P1 把它作为 E5 的第一件事补上，并以 D8 定死计算口径。
- **风险与缓解**：超大工作区（>500 表）靠截断 + `edges_out_of_view` 提示 + 聚焦模式兜底。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 可视化交互口径 | echarts graph/force + Inspector + 聚焦 | 复用同一套结论，不造第二套 | ADR 0182 / 0183 / 0184 |
| lookup 语义 | 引用字段挂在关联字段下 | 图上只画 link，lookup 计数 | ADR 0131 |
| 数据面判定 | `resolve_capabilities` / `preload_table_access` | 节点集合 = 可读表，不另写判定 | ADR 0153 / 0161（H64） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/services/core/link_graph.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/tables/routers/groups.py`、`frontend/src/pages/tables/TableLinkGraphPage.tsx`、`frontend/src/api/tables.ts`、`frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx` | `tests/test_tables_link_graph.py`、`frontend/src/pages/tables/TableLinkGraphPage.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | `2250fb9c` |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/link_graph.py`（节点 / 边带 can_edit 位，E5/D8）、`src/cndb/plugins/tables/services/core/links.py`（悬空关联检测与清理，D7）、`src/cndb/plugins/tables/routers/fields.py`（改目标表失效预检，E2′）、`frontend/src/api/types/tables.ts`、`frontend/src/pages/tables/TableLinkGraphPage.tsx`（两步连线 E4 / 建边 E1 / 改边 E2 / 删边 E3） | `tests/test_tables_link_graph.py`（能力位 3 例 + 改目标表拦截 3 例）、`frontend/src/pages/tables/TableLinkGraphPage.test.tsx`（编辑 8 例） | `2d4966bb` |
| P2 | 未开始 | — | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 已落地并提交（`2250fb9c`）；P1 已落地并提交（`2d4966bb`，2026-11-28）；P2 未开始。
- 已完成：P0（后端聚合接口 + 缓存失效点 + 前端页面 + 页签入口 + 单测）；P1（`can_edit` 判定位、两步点击连线建边、Inspector 改 / 删边、改目标表的失效预检 + `force` 清理）。
- 下一步：P2（布局 / 备注持久化）需新表 + 迁移 + `backup_io`，届时按 S2 另行评审；P1 不新增写路径（D6），后续若要「拖拽连线」需先推翻 D5 并说明移动端方案。
- 已知坑：
  - echarts `graphRoam` 缺省锚点是画布 (0,0)，缩放必须显式带 `originX/originY`（0168 踩过，本页已按中心锚点实现）；前端单测里 jsdom 无布局，断言缩放锚点前要 `Object.defineProperty` 显式给画布尺寸。
  - **echarts 的 `click` 处理器只挂一次**（在 init 的 useEffect 里），P1 引入「连线态」后必须经 ref（`connectFromRef` / `nodeByIdRef` / `pickConnectTargetRef`）读最新交互态，否则处理器会读到闭包里的旧值、或在依赖变化时被重挂而丢失 echarts 内部状态。
  - 两个 Modal（建边 / 改边）**共用同一个 `form` 实例**：打开前必须 `setFieldsValue` 把对应字段全量写一遍（含 `targetId`），否则会带上一次弹窗的残留值。
  - antd 6 会在两字中文按钮中间插空格（「复 位」「删 除」），前端测试用 `getByRole('button', { name })` 必须写正则 `/删\s*除/`，否则匹配不到。
  - 改目标表的失效判定按「新目标表中不存在的行 id」计算（D7）；若新目标表**物理表尚未创建**，合法行集为空，等于全部关联失效——这是有意的保守口径。
- 最近一次全绿：`make flow` @ `2250fb9c`（2026-11-28，7944 passed / 17 skipped）
