# 0182 文档知识图谱探索器增强（S1）

- 编号：0182
- 来源 / 提出人：用户（会话 2026-11-26，0168 图谱上线后复核）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；可见性口径 H33 / H64，前端约束 H24/H25/H29/H30/H31）
- 关联前序：`docs/requirements/0168-document-knowledge-graph.md`（图谱首版，落地 sha `432c771e` + 交互修复 `7275c9f3`）
- 状态：已确认范围（2026-11-26 用户「都按建议，开始」）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。0168 的 C1–C8 仍有效，本卡只补增量，不重编号、不复用 0168 编号。

## 需求原句（逐字）

> 结合典型应用最佳实践，继续完善图谱板块功能，给出建议方案

> 都按建议，开始

## 背景（0168 落地后复核发现的问题）

| # | 现象 | 根因（已核实） |
|---|---|---|
| 1 | 改完正文立即看图谱，仍是 30 秒前的旧图，容易被判断为「双链没生效」 | `_graph_cache` 有 30s TTL，但 `reset_link_graph_cache()` 只在测试里调用；`create_document` / `update_content` / `soft_delete_*` / `restore_document` / `purge_document` / `move` / `repair_wikilinks` / `duplicate_document` 一次都没清缓存 |
| 2 | 超 500 节点时，指向窗口外文档的边直接消失，中心文档看起来成了孤立点 | `build_link_graph` 在 `target_title in all_titles` 分支 `continue`，既不建边也不标断链；`truncated` 只表示节点被截，没有边被截的计数 |
| 3 | 500 个节点的力导向图读不出结论 | 全局限定视图；典型应用（Obsidian / cogninote / okve）一致认为全局图是诊断工具，局部图与筛选才是日常视图 |
| 4 | 不知道颜色代表什么、字挤在一起 | 按 `content_type` 着色但无图例；只有 `labelLayout.hideOverlap`，缩放不控制标签显隐 |
| 5 | 进图谱要自己在一团线里找自己正在写的文档 | 编辑器没有「在图谱中查看」入口 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「完善图谱板块」（缺陷 1） | 新增 `invalidate_link_graph_cache(workspace_id)`：只清该工作区的缓存条目，不整表清空；在所有会改变节点/边的写路径末尾调用（创建、改正文、软删、恢复、彻底删、移动、链接修复、副本、标签变更） | `services/content.py`、`services/move.py`、`routers/documents.py` | 单测：写后立刻读图谱，看到新边，不依赖 `reset_link_graph_cache` |
| C2 | 「完善图谱板块」（缺陷 2） | 截断时统计 `edges_out_of_view`：指向「存在但落在节点窗口外」的文档的边数，随 payload 返回；前端页脚明示「另有 N 条链接指向未展示的文档」，与断链区分 | `services/content.py`、`api/documents.ts` | 单测：`max_nodes` 小值下 `edges_out_of_view > 0` 且不产生断链节点 |
| C3 | 「典型应用最佳实践」（局部图） | 支持 `?focus=<docId>&depth=1\|2`：进入页面即只渲染该文档的 N 跳邻域，顶部显示「正在聚焦《标题》· 深度 N」与「查看全图」清除；邻域在**前端**用已有 nodes/edges 做 BFS，不新增接口 | `DocumentGraphPage.tsx` | 前端单测：depth=1 只保留直连节点；depth=2 含二跳；清除后回到全图 |
| C4 | 「典型应用最佳实践」（入口） | 编辑器次级入口新增「在图谱中查看」，跳 `/w/:wid/documents/graph?focus=<id>&depth=1`；原件族 / 文件夹不展示（无正文链接） | `DocumentEditorPage.tsx` | 前端单测：点击后 URL 带 focus 与 depth |
| C5 | 「典型应用最佳实践」（筛选） | 工具栏筛选栏：标题关键词、内容格式（多选，取自 `DOC_FORMAT_META`）、状态（草稿 / 已发布 / 归档）、只看断链、只看孤立点；筛选只作用于渲染，页脚同时给出「显示 X / 共 Y 个节点」 | `DocumentGraphPage.tsx` | 前端单测：各筛选组合后的 `series.data` 长度与页脚计数 |
| C6 | 「典型应用最佳实践」（Inspector） | 单击节点改为**选中**并在右侧 Inspector 显示标题 / 格式 / 状态 / 度数 / 出链数 / 反链数 + 「打开文档」「设为中心」「复制链接」；**双击**或 Inspector 的「打开文档」才跳转。断链虚拟节点不可打开，Inspector 提示「目标文档不存在」 | `DocumentGraphPage.tsx` | 前端单测：单击不跳转且 Inspector 出现；双击跳转；断链节点无打开按钮 |
| C7 | 「典型应用最佳实践」（图例与可读性） | 图例列出当前出现的格式及色块，点击可显隐该格式；标签按倍率淡化：`zoomPct` 低于阈值（默认 60%）时不显示标签，工具栏可切换「显示标签」 | `DocumentGraphPage.tsx` | 前端单测：图例点击后该格式节点被过滤；低倍率下 `label.show === false` |
| C8 | 「典型应用最佳实践」（诊断输出） | 侧栏「孤立点 / 枢纽」清单：孤立点 = 度数为 0 的非断链节点；枢纽 = 度数 top 10。点击条目选中并居中该节点 | `DocumentGraphPage.tsx` | 前端单测：清单内容与节点度数一致，点击后选中项变化 |
| C9 | 「典型应用最佳实践」（布局力） | 力参数面板（`repulsion` / `edgeLength` / `gravity`）可调，改动即时重排；「恢复默认」回到当前常量 | `DocumentGraphPage.tsx` | 前端单测：拖动后 `option.series[0].force.repulsion` 变化 |
| C10 | （设计 / 测试 / 文档约束） | 只用 `--cn-*` token；断点仅 767.98 / 575.98px；echarts 保持独立 lazy chunk（H31）、SVG renderer；同轮补后端 + 前端单测；CHANGELOG 增条目；本卡回填落地结果 | 新页面样式、测试文件、`CHANGELOG.md` | `make check-fast` / `make flow` / `make check-frontend` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 图谱聚合与缓存 | `src/cndb/plugins/documents/services/content.py:1180-1340` | C1 / C2 主战场 |
| 2 | 文档写路径 | `content.py:240 create_document`、`:359 update_content`、`:520/536 soft_delete*`、`:628 restore_document`、`:695 purge_document`、`:896 repair_wikilinks`、`:1389 duplicate_document`、`move.py` | C1 失效点 |
| 3 | 图谱接口 | `routers/documents.py:1579 GET /links/graph` | C2 payload 增字段 |
| 4 | 前端 API 类型 | `frontend/src/api/documents.ts:154-178` | C2 / C5 |
| 5 | 图谱页 | `frontend/src/pages/documents/DocumentGraphPage.tsx`（343 行） | C3/C5/C6/C7/C8/C9 |
| 6 | 编辑器次级入口 | `frontend/src/pages/documents/DocumentEditorPage.tsx:1352 docMoreItems` | C4 |
| 7 | 格式元数据 | `frontend/src/components/Document/docFormat.ts:41 DOC_FORMAT_META` | C5/C7 格式清单与配色 |
| 8 | 路由 | `frontend/src/App.tsx:198` | C3 query 参数 |

## 决策（并入本卡的 S1 方案）

- **D1 缓存失效用工作区粒度**：`_graph_cache` 键是 `(workspace_id, 身份)`，失效只需按 workspace 前缀删键，避免一个工作区写文档把全站图谱缓存清空。
- **D2 截断丢边只统计不改口径**：节点上限仍按 `updated_at` 取最近 500（0168 C6 不变），只新增 `edges_out_of_view` 让用户知道「图不完整」，不改成度数优先排序（会改变 0168 口径且截断语义不可预期）。
- **D3 局部图在前端算**：nodes/edges 已全量返回（≤500），BFS 是纯函数，不新增接口、不加后端参数，避免接口口径分裂。
- **D4 Inspector 不替代跳转**：单击选中 + 双击打开；双击是 `dblclick` 事件，单击跳转的老交互下线（现有 9 个前端用例里跳转断言一并改为双击）。
- **D5 筛选与图例都只在前端过滤**：后端 payload 不变（除 C2 计数），避免「筛选后再请求」带来的状态同步问题。

## 落地结果（2026-11-26）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 缓存失效 | `services/content.py::invalidate_link_graph_cache(workspace_id)`；调用方：`create_document` / `update_content` / `soft_delete_documents` / `soft_delete_document` / `restore_document` / `purge_document` / `duplicate_document` / `services/move.py::move_nodes_to_workspace` / `routers/documents.py::update_document_meta` / `batch_documents` 的 move 分支 | `test_cache_invalidated_by_writes`、`test_cache_invalidated_by_rename_and_delete` 通过（全程不调 `reset_link_graph_cache`） |
| C2 截断丢边计数 | `build_link_graph` 新增 `out_of_view` 集合 + payload `edges_out_of_view`；用 `visible_titles`（按身份过滤）区分「被截断」与「不可见」，避免 H33 泄漏 | `test_edges_out_of_view_counted_when_truncated`、`test_edges_out_of_view_ignores_invisible_documents` 通过；顺带修正 `cache_key` 漏 `max_nodes` 导致小窗口试探后大窗口命中截断版 |
| C3 局部图 | `DocumentGraphPage.tsx::collectNeighborhood`（无向 BFS）+ `?focus=&depth=` 走 `useSearchParams`；`focus` 不在图内给「回到全图」 | 用例「局部图按 ?focus=&depth= 收敛节点集」「中心文档不在图内时给出回退入口」 |
| C4 编辑器入口 | `DocumentEditorPage.tsx::openGraphFocus`；更多菜单 `graph` 项 + 桌面 `doc-graph-focus-open` | `DocumentEditorPage.test.tsx` 新增 1 例断言 `/w/10/documents/graph?focus=2&depth=1` |
| C5 筛选栏 | `filterGraph`（关键词 / 状态 / 只看断链 / 只看孤立点 / scope / 格式显隐）；页脚「显示 X / 共 Y」 | 用例「筛选栏按关键词与只看断链收敛，页脚同时给出显示 X / 共 Y」 |
| C6 选中与 Inspector | `chart.on('click')` 只选中、`chart.on('dblclick')` 才跳转；Inspector 含出链 / 反链 / 打开 / 设为中心 / 复制链接 | 用例「单击只选中，双击才进入文档」「Inspector 显示出链反链并可复制链接」 |
| C7 图例与标签淡化 | `formatKey` / `legendLabel` / `legendColor`；`LABEL_ZOOM_THRESHOLD = 0.6`，单独 `setOption` 只改 `label.show` | 用例「图例按格式显隐」「标签按倍率淡化」 |
| C8 孤立与枢纽清单 | `findIsolated` / `findHubs(limit = HUB_TOP_N = 10)`；点击 `focusNodeAdjacency` | 用例「孤岛与枢纽清单可点击定位」 |
| C9 力参数面板 | `DEFAULT_FORCE` + `ForceParams`；三档滑块（斥力 40–600 / 边长 40–300 / 向心 0–0.5）+ 恢复默认；767.98px 以下隐藏 | 用例「力参数面板可调斥力并恢复默认」 |
| C10 口径 | 只用 `--cn-*`；断点 767.98 / 575.98px；echarts 仍独立 lazy chunk + SVG renderer；同轮补测试与 CHANGELOG | `make check-fast` / `make flow` / `make check-frontend` 全绿 |

后端 `tests/test_documents_link_graph.py` 5 → 9 例；前端 `DocumentGraphPage.test.tsx` 重写为 21 例、`DocumentEditorPage.test.tsx` 94 例（+1）。

## 未决问题

- [x] 范围：C1–C10 全做（用户「都按建议，开始」）
- [x] Inspector 交互变更：接受单击选中 / 双击打开
- [x] 截断语义：补 `edges_out_of_view`，不改节点排序口径（D2）

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-26）

## 不做

- 不引入新依赖（echarts 已够；不加 d3 / cytoscape）。
- 不落库、不加反链索引表、不改双链语法、不加块级模型。
- 不做跨工作区边；不做图谱内编辑关系（只读可视化）。
- 不改 0168 的节点上限口径（仍 `updated_at` 最近 500）。
