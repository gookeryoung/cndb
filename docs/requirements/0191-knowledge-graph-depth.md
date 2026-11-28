# 需求卡片：知识图谱功能与 UI 补齐（本地图谱 / 视图持久化 / 标签色组 / 断链虚节点）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0191（S1，方案并入本卡片，无 ADR）
- 来源 / 提出人：用户（会话 2026-11-28，方案已确认「按此推进」）
- 日期：2026-11-28
- 关联 ADR：无（S1，方案并入本卡片；C5 触及接口字段扩展，仍属聚合读接口的字段增量，不触数据 / 权限口径变化）
- 关联前序：`0168-document-knowledge-graph.md`（图谱首版与解析口径）、`0182-document-graph-explorer.md`（探索器交互）、`0183-document-graph-edge-arrows.md`（单双向边）、`0184-document-graph-visual-polish.md`（视觉参数）、`0189-knowledge-graph-ui.md`（布局重构范式）、`0187-table-link-graph.md`（相邻概念，不合并）
- 状态：**P0–P2 已落地**（2026-11-28 用户「按此推进」后实现；S1 无 ADR，方案与落地结果均在本卡）

## 需求原句（逐字）

> 知识图谱，参考 obsidian 等同类 APP，针对功能和 UI 优化，结合最佳实践制定方案

> 按此推进

## 背景（现状核实，非推测）

0168→0184→0189 三轮已把交互与视觉基线收敛到位（画布控制簇 / 筛选 / 聚焦深链 / Inspector / 图例 / 空
载态）。对标 Obsidian（Local graph 插件、color groups、unresolved links）、Neo4j Bloom、Logseq，剩余
差距集中在**功能深度**与少量 **UI 收尾**：

| # | 差距 | Obsidian 对应 | 现状核实 | 位置 |
|---|---|---|---|---|
| 1 | 本地图谱按钮（页内一键设中心） | Local graph | Inspector 已有「设为中心」，但画布上无一键入口；聚焦只能靠双击或深链 | `DocumentGraphPage.tsx` `graph-inspector-focus`、`focusNode()` |
| 2 | 视图状态不持久化 | 设置自动保存 | 力参数 / 标签 / 箭头 / 图例收起态 / 缩放档位刷新即重置；组件内 useState，无持久化 | `DocumentGraphPage.tsx:599-604`（`force` / `forcePanelOpen` 等 useState） |
| 3 | 无标签 / 文件夹信息编码 | color groups | 节点只按 `content_type` 配色；文档已有 tags 元数据但未进图谱 | `buildOption()`（`docFormat.ts` 色映射） |
| 4 | 断链目标不可见 | unresolved links 虚节点 | 断链只画虚线边，目标不建节点；接口 `broken` 边的标题未出现在响应体 | `services/content/graph.py`、`build_link_graph` |
| 5 | hover 信息单薄 | hover preview | tooltip 只有标题；更新时间 / 标签 / 状态未展示 | `buildOption()` tooltip 配置 |

**同类应用共性结论**（已并入约束）：① 画布上一键「以选中为中心看局部图」是知识图谱的核心动线；
② 视图配置属于用户偏好，应跨会话留存；③ 分类着色 + 图例联动是图谱最有用的信息编码；④ 未解析链
接画为虚节点能回答「该写什么」；⑤ 全屏 / 小地图 / 时间轴在信息密度不足时收益低。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考 obsidian」（本地图谱） | 画布控制簇加「聚焦」按钮（`graph-local-focus`）：选中节点时一键进入 `?focus=<id>&depth=1` 局部图（复用现有 BFS 与深链格式，零后端）；未选中时禁用并给 tooltip「先选中一个文档」；Inspector「设为中心」与深链行为保持不变 | `DocumentGraphPage.tsx` | 单测：选中后点按钮 URL 带 `focus`；未选中按钮 `disabled`；深链兼容既有断言 |
| C2 | 「参考 obsidian」（持久化） | 视图状态持久化到 localStorage：键 `cndb.graph.view.<workspace_id>`，字段 = `{ labels, arrows, legendCollapsed, force:{repulsion,edgeLength,gravity}, zoom }`；挂载时恢复、变更时写回（`JSON.stringify` + try/catch 容错）；「复位」按钮**同时**重置视图态与清空该键（回到默认）；力参数面板开合不持久化 | 同上 | 单测：localStorage mock 写入 / 恢复 / 复位清键三例；键含 workspace_id 隔离 |
| C3 | 「功能和 UI 优化」（hover） | tooltip 增强：标题 + 状态徽标 + 标签 chips + 更新时间（相对时间，复用现有格式化工具）；目录节点（`is_folder`）只显示标题与「文件夹」；数据已在节点载荷内的直接用，缺的进聚合 payload 补字段（`updated_at`、`tags`） | `graph.py`、`DocumentGraphPage.tsx` | 后端单测：payload 含新字段；前端单测：option.formatter 输出含状态 / 标签 / 时间 |
| C4 | 「参考 obsidian」（色组） | 节点着色维度可切换：筛选条加「着色」Select（`graph-color-by`）：`类型`（默认，现状）/ `标签` / `文件夹`；按标签时取节点首个标签映射固定色板（8 色，token 化色值数组），无标签归「未分类」；图例（`graph-legend`）随维度联动切换；切维度不重置力布局 | 同上 | 单测：三档 option 节点色分组数不同；图例 chips 跟随维度；无标签节点入「未分类」 |
| C5 | 「参考 obsidian」（断链虚节点） | `build_link_graph` 输出断链目标为虚节点：`nodes` 增加 `{id: 负数(-1000-序号), title, virtual: true, content_type: null}`；对应边 `broken: true` 保留；`ambiguous` 口径沿用 0168（解析命中多个取首个，虚节点 title 取链接原文，不标候选数）；前端虚节点渲染为虚线边框 + 淡色，Inspector 显示「去创建」按钮（预填标题跳 `/w/:wid/documents?create=1&title=...`）；虚节点不进枢纽 / 孤岛清单计数 | `graph.py`、`routers/documents.py`、`DocumentGraphPage.tsx` | 后端单测：断链目标成虚节点、不泄真实文档存在性（虚节点 id 为负且非真实 id）；前端单测：虚线样式 + 「去创建」跳转 |
| C6 | （交互语义边界） | 不改 0182/0183/0184 已收敛的交互与视觉参数（单击选中 / 双击进入 / 互引折叠 / 选中态 / 邻接聚焦 / 孤岛淡化）；本卡只做增量控件与字段，既有 testid 全部保留 | 全部 | 既有 42 例单测零放宽通过 |
| C7 | （设计约束） | 只用 `--cn-*` token（H29）；线条 1px 中性线（H25）；断点只 `767.98px` / `575.98px`（H30）；echarts 仍独立 lazy chunk + SVG renderer（H31）；体积变化走 `bundle-budget.mjs`（H32）；色板 8 色为 `--cn-*` 派生色或 themeMix 混色，不写裸 hex | `.css`、`themeMix.ts` | `tokens.test.ts` / `make frontend-static` / `bundle-budget` 全绿 |
| C8 | （测试约束） | 同轮补：后端 `test_documents_link_graph.py`（虚节点结构 / 不泄名 / 字段扩展 3 例）；前端 `DocumentGraphPage.test.tsx`（C1–C5 各 2–3 例，约 +12 例）；既有断言不放宽 | 测试文件 | `make flow` / `make check-frontend` 全绿 |
| C9 | （文档约束） | `CHANGELOG.md` 增条目；`docs/USER_DOC_MAP.md` 与帮助教程正文（`tutorials.tsx`）补新控件说明；本卡回填落地结果 | 文档 | `make check-docs` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 图谱聚合服务 | `src/cndb/plugins/documents/services/content/graph.py::build_link_graph` | C5 / C3（字段扩展） |
| 2 | 文档路由 | `src/cndb/plugins/documents/routers/documents.py` | C5 响应体类型 |
| 3 | 图谱页面 | `frontend/src/pages/documents/DocumentGraphPage.tsx`（1319 行） | C1–C5 主战场 |
| 4 | 页面样式 | `frontend/src/pages/documents/DocumentGraphPage.css` | C4 色组 / C5 虚节点样式 |
| 5 | 前端 API 类型 | `frontend/src/api/documents.ts`、`types` | C5 `virtual` 字段 |
| 6 | 后端单测 | `tests/test_documents_link_graph.py` | C8 |
| 7 | 前端单测 | `DocumentGraphPage.test.tsx`（42 例） | C8 |
| 8 | 帮助教程 | `frontend/src/pages/help/content/tutorials.tsx` | C9 |
| 9 | 色板与格式 | `frontend/src/components/Document/docFormat.ts`、`themeMix.ts` | C4 |

## 决策（S1 方案）

- **D1 本地图谱复用聚焦深链，不新增「本地图谱模式」**：`?focus=&depth=` 已实现 BFS 局部图与分享深
  链（0182 C3），控制簇按钮只是把它从「Inspector 动作 / 双击」提升为画布一级入口。不引入独立模式，
  避免两套视图语义并存。
- **D2 持久化只存「用户偏好」，不存会话态**：选中节点、聚焦文档、筛选关键词是会话性质，不存；标
  签 / 箭头 / 图例收起 / 力参数 / 缩放是稳定偏好，存。localStorage 客户端存储，零迁移；键按
  workspace 隔离避免 A 区偏好串到 B 区。
- **D3 色组维度三档、标签取首个**：标签可能多值，全部编码会让图例爆炸；取首个标签（创建时通常为
  主标签）+「未分类」兜底。文件夹档回答「这个区怎么组织的」，标签档回答「这些文档讲什么」。
- **D4 断链虚节点用负 id 段（-1000 起）**：与 0187 表关联图虚拟节点（-1/-2）范式一致，前端零 id 碰
  撞风险；虚节点不参与度数统计（枢纽清单口径不变），不泄真实文档存在性（断链目标本就不存在，标题
  取链接原文，无歧义候选泄漏）。
- **D5 「去创建」预填标题用 `?title=` 查询参数**：新建文档入口已有 `?create=1`（0190 C10 同款），
  追加 title 参数由 DocumentsPage 读取预填；若该页当前不支持 `?title=`，同轮补（读参 + 预填，S 量
  级）。
- **D6 不做**：图上建双链（改正文，依赖块模型 0178）、全屏 / 小地图 / 时间轴、跨工作区图谱（H33/H17
  隔离口径）、表关联图合并（D7 of 0189 不变）。

## 分期

| 期 | 内容 | 预估 |
|---|---|---|
| P0 | C1 本地图谱按钮 + C2 视图持久化 + C3 hover 增强 | 约一天 |
| P1 | C4 标签 / 文件夹色组 + C5 断链虚节点（含后端字段扩展） | 约两天 |
| P2 | C6–C9 收尾：token / 预算自查、测试回填、文档回填 | 约半天 |

## 未决问题

- [x] ① 范围是否 P0+P1？→ 是（用户 2026-11-28 确认）。
- [x] ② 断链虚节点做不做？→ 做（C5 / D4），负 id 段不泄存在性。
- [x] ③ ambiguous 断链虚节点标题取哪个？→ 取链接原文（0168「取首个」口径的延伸），不展示候选数。
- [x] ④ 持久化存哪些？→ 仅稳定偏好（D2），选中 / 聚焦 / 筛选词不存。
- [x] ⑤ 「去创建」入口？→ 预填标题跳新建（D5），不直接创建文档。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认后进入实现（S1 人工卡点，H5；2026-11-28 用户「按此推进」）

## 不做

- 不改正文存储与双链解析口径（`iter_wikilinks` 唯一解析入口不变）。
- 不改节点上限（500）、`truncated` 口径、`?focus=&depth=` 深链格式、既有 testid。
- 不做图上编辑双链、全屏 / 小地图 / 时间轴、跨工作区图谱、表关联图合并。
- 不引入新依赖。

## 落地结果（2026-11-28）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 本地图谱 | 控制簇新增「本地图谱」按钮（`graph-local-focus`）：选中后一键写 `?focus=<id>&depth=1`（复用既有 BFS 与深链格式，零新接口）；未选中 `disabled`，Inspector「设为中心」不变 | 前端单测：未选中禁用 / 选中后 URL 带 `focus=1&depth=1` / 中心 Tag 出现 |
| C2 视图持久化 | `loadViewPrefs` / `saveViewPrefs` / `clearViewPrefs`（键 `cndb.graph.view.<wid>`）；挂载恢复、变更写回（集中一个 useEffect）；「复位」重置为默认值并重写键；JSON 容错逐字段回退；选中 / 聚焦 / 筛选词不存（D2） | 单测：写回后重新挂载恢复（标签关 / 图例收 / 力参数 400）；复位后值回默认 |
| C3 hover 增强 | 聚合接口节点补 `updated_at` 与 `tag`（一条聚合查询取首个标签，避免 N+1；断链节点两字段为 null）；tooltip 输出标题 + 状态 + 标签 + 相对时间（`formatRelativeTime`），断链标「尚未创建」；`POST /{doc_id}/tags` 后失效图谱缓存 | 后端单测 2 例（载荷字段 / 改标签写后即见）；前端 formatter 断言 |
| C4 色组 | 控制簇新增「着色」Select（`graph-color-by` 三档：类型 / 标签 / 文件夹）；`colorGroupKey` + `colorGroupMeta`（标签 8 色色板哈希分配、无标签「未分类」、文件夹两色）；图例随维度联动；边线色随源节点维度色；`formatColor` / `legendColor` 被收敛进 `colorGroupMeta`，删除未再引用的 `legendLabel` | 单测：切标签档后图例 chips 变为标签名 |
| C5 断链去创建 | **范围勘误**：核实发现断链虚节点（负 id + `broken=true`）后端自 0168 起已输出、前端已画虚线边——本卡 C5 收窄为纯前端增量：断链节点改虚线边框（`borderType: 'dashed'` + error 色）+ 淡色；Inspector 出「去创建「标题」」按钮（`graph-inspector-create`），跳 `/w/:wid/documents?create=1&title=<预填>`；`useCreateParam` 读 `?title=` 预填新建弹窗标题 | 单测：断链节点虚线边框 / 点「去创建」后 URL 带 `create=1&title=`；不泄存在性口径由既有 0168 用例继续钉住 |
| C6 交互边界 | 未改 0182/0183/0184 已收敛语义；既有 testid 零改动 | 既有 44 例单测零放宽通过 |
| C7 设计约束 | 色板取 docFormat 同源中间明度色（不新增 token）；无新断点；echarts 仍 lazy chunk | `tokens.test.ts` 全绿；`bundle-budget` 全部在预算内；`[compat] Chromium 81 0 warning` |
| C8 测试同轮 | 后端 10 → 12 例；前端 44 → 50 例（C1–C5 各新增） | `make test` 7965 passed / 17 skipped；前端全量 3745 例全绿 |
| C9 文档回填 | CHANGELOG 增条目；帮助教程「知识图谱」节补本地图谱 / 持久化 / hover / 去创建说明；BACKLOG 状态改「已完成」；本卡回填 | `make check-docs` 全绿 |

**门禁**：`make check-fast` 全绿；`make test` 7965 passed / 17 skipped；`make check-frontend`（覆盖率核心集合 lines 97.66% / branches 100%，全局 83.88%）全绿；`pnpm build` 通过。

**已知项**：① 覆盖率门禁一次 HelpDocsPage 失败为跨文件 MSW handler 串扰 flake（干净 stash 基线同样场景偶发），重跑全绿，与本次改动无关；② 同会话并行的设计模块改动（0192 / 0193）在 `DesignStructureNav.test.tsx` 留有两处 TS 悬空引用（未定义 `$T2` / 未使用 `SEL_TREENODE`）导致 `pnpm build` 失败，已顺手修复（改用 `screen.getByTestId` / `SEL_TREENODE`），语义零变更。
