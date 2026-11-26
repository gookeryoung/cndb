# 0168 文档知识图谱（S1）

- 编号：0168
- 来源 / 提出人：用户（会话 2026-11-26，P0 分析后确认「先做 P0，P2」→「先做 4 项 S1」）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；可见性口径 H33 / H64，前端约束 H24/H25/H29/H30/H31）
- 状态：已确认范围（2026-11-26 选择「先做 4 项 S1」；卡片约束待复核）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 请分析文档部分功能对照典型知识库应用，功能上还有哪些需补齐完善的。

> 先做 P0，P2。

> （P0 分析结论）知识图谱 view：双链、反链、出链齐全，无可视化图谱 —— 复用 wikilink 解析 + backlinks 数据，加力导向图。

补充确认：本卡只做 **知识图谱可视化**；块级模型（P0）、内容模板（本批另卡 0169）、反链索引（P2，S2 后做）不在本卡范围。

## 方案（口径）

**范围**：后端新增一条「链接边」聚合接口，复用现有 `iter_wikilinks` / `resolve_outgoing_links` 解析能力；前端新增文档区二级页「图谱」，用已引入的 `echarts` graph 系列 **lazy** 渲染力导向图（H31，不进首屏 chunk）。零新依赖、零数据模型、零迁移；不改正文存储与双链语法。

**数据来源**：以工作区内**可见文档**为节点（H33：draft/archived 仅创建者与 OWNER/超管可见，统一走可见性过滤），以解析出的 wikilink 为边。边解析规则：链接目标标题 → 同工作区同名文档；命中多个时取首个并标 `ambiguous`；未命中标 `broken`（虚线边 + 孤立节点）。自环过滤。边去重。

**布局与交互**：echarts `series.type=graph`、`layout=force`，节点标签显示标题（省略超长），按 `content_type` 取 `docFormat.ts` 图标色；点击节点跳文档编辑/阅读页，点击边显示「源 → 目标」；提供缩放/拖拽/复位；节点数上限（默认 500，超出按 updated_at 取最近 N 并在页脚提示）。

**性能**：聚合在接口内完成，单次扫描最新版本正文；结果按 `(workspace_id, viewer 可见性签名)` 缓存 30s，与 `/tree` 的 TTL 模式一致；缓存只存解析结果，不存正文。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「双链、反链、出链齐全，无可视化图谱」 | 新增 `GET /{workspace_id}/documents/links/graph`，返回 `{nodes:[{id,title,content_type,status}], edges:[{source,target,broken,ambiguous}], truncated}` | `routers/documents.py`、`services/content.py` | 接口单测断言节点/边结构、自环过滤、边去重 |
| C2 | 「复用 wikilink 解析 + backlinks 数据」 | 边解析唯一复用 `iter_wikilinks`（`parse.py:139`）+ 标题→id 解析；**不另写第二套链接解析**，不落库（无新表） | `services/parse.py`、`services/content.py` | 单测断言同一正文在 `/links`、`/backlinks`、`/graph` 三处解析一致 |
| C3 | 「可见性」（H33/H64） | 图谱只收集当前用户可见文档；草稿/归档按 H33 过滤，不可见文档既不做节点也不做边端点，不泄漏标题存在性；工作区判定走 `resolve_capabilities` 的 `data_role` | `services/visibility.py`、`routers/documents.py` | 接口单测：viewer 看不到他人草稿节点，404 口径不变；H64 用例不改即全绿 |
| C4 | 「加力导向图」 | 前端文档区新增二级页「图谱」，`echarts` graph + `layout=force`，从独立 chunk 动态 import（H31） | `pages/documents/DocumentGraphPage.tsx`（新）、路由、`api/documents.ts` | 前端单测断言节点/边渲染、点击跳转、缩放复位；bundle budget 不超基线 +5%（H21） |
| C5 | 「图谱」（断链表达） | 断链用虚线边/孤立节点标记，语义与 `LinksDrawer` 断链一致；`ambiguous` 有 tooltip 提示 | `DocumentGraphPage.tsx` | 单测断言断链/歧义样式与 tooltip 文本 |
| C6 | 「图谱」（规模） | 节点上限默认 500，超出取最近更新 N 个并提示；聚合结果 30s 缓存，仅缓存解析结构 | 后端 service / router | 单测断言截断标记与缓存命中行为 |
| C7 | （设计约束） | 断点只用 767.98/575.98px；间距/字号/颜色只用 `--cn-*` token；线条用 `--cn-border`；选中态 `--cn-bg-selected`（H24/H25/H29/H30） | 新页面样式 | `mobileCaliber.test.ts`、`make check-frontend` |
| C8 | （测试 / 文档） | 同轮补后端接口单测 + 前端页面单测；CHANGELOG 增条目；本卡回填落地结果 | 测试文件、`CHANGELOG.md` | `make flow` / `make test` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | wikilink 解析 | `services/parse.py:139 iter_wikilinks` | C2 复用入口 |
| 2 | 出链 / 反链解析 | `services/content.py:776 find_backlinks`、`:830 resolve_outgoing_links` | C2 复用 |
| 3 | 文档接口路由 | `routers/documents.py:1446 /backlinks`、`:1478 /links` | C1 新增同级路由 |
| 4 | 可见性过滤 | `services/visibility.py`、`H33/H64` | C3 |
| 5 | 前端 API 封装 | `frontend/src/api/documents.ts` | C4 |
| 6 | 前端文档区路由与页签 | `frontend/src/pages/documents/`、`DocumentsPage.tsx` | C4 入口 |
| 7 | 格式图标映射 | `frontend/src/components/Document/docFormat.ts` | C4 节点配色 |
| 8 | echarts lazy 范式 | `frontend/src/pages/grid/views/ChartView.tsx`、`chart/register.ts` | C4 复用 lazy 模式 |

## 不做

- 块级模型、正文存储改造、新数据模型、迁移。
- 反链索引表（P2 S2，后做）：本接口实时解析 + 短缓存，不落库。
- 编辑图谱节点、改链接、拖拽改关系；只读可视化。
- 跨工作区边（工作区隔离，按 H33/H64）。
- 新依赖（echarts 已在 package.json，复用）。

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

## 落地结果

- 代码落点：
  - 后端 `services/content.py::build_link_graph`（复用 `parse.iter_wikilinks`，30s 缓存 + 256 条上限（过期即清理），节点上限 500，H33 可见性过滤含「存在但不可见不建断链节点」防泄漏）、`routers/documents.py::GET /{wid}/documents/links/graph`；节点载荷含 `is_folder`（前端据此决定跳编辑器还是目录列表）与 `broken`。
  - 前端 `api/documents.ts`（`LinkGraph` 类型 + `linkGraph`）、`pages/documents/DocumentGraphPage.tsx`（echarts graph/force，独立 lazy chunk；配色经 `getComputedStyle` 读取 `--cn-*` 并用 `useTheme` 触发重建）、文档区二级页签「图谱」与路由。
- 测试：后端 `tests/test_documents_link_graph.py` 5 例（节点/边/断链、自环去重、歧义、可见性、截断与缓存）；前端 `DocumentGraphPage.test.tsx` 3 例（option 结构 / 点击跳转 / 截断提示）。`pnpm build` + `pnpm bundle:budget` 全绿，`DocumentGraphPage` 独立 chunk（H31）。
- 提交 sha：432c771e。

## 补充：交互与显示修复（2026-11-26）

C4 只规定了「echarts graph + layout=force」，没约束缩放锚点与可读性细节，上线后暴露为「缩放不正常、显示效果差」：

- 根因：echarts 6.1.0 的 `graphRoam` 是相对增量、默认以画布 (0,0) 为锚点（`coord/View.js::applyRoamPayloadToOverallTrans`），原工具栏只派发 `zoom` 不派发 `originX/originY`，导致图往左上角飞出且 roam transform 出现 `null`（SVG 里是 `NaN`）。
- 修复：`zoomBy()` 以容器中心为锚点派发；补 `scaleLimit 0.25–4`、`nodeScaleRatio 0.4`、`labelLayout.hideOverlap`（需 `echarts/features` 的 `LabelLayout`）、`edgeSymbol ['none','arrow']`、度数分级节点尺寸、`emphasis.focus:'adjacency'` + `blur`、tooltip `confine`。
- 测试：`DocumentGraphPage.test.tsx` 3 → 9 例，覆盖锚点坐标、上下限夹取与按钮禁用、option 显示要素、`graphroam` 倍率读数同步。
- 改动文件：`frontend/src/pages/documents/DocumentGraphPage.tsx`、`frontend/src/pages/documents/DocumentGraphPage.test.tsx`。C7 的 token 口径（只用 `--cn-*`）未破。
