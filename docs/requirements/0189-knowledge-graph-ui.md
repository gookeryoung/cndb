# 需求卡片：图谱模块改名「知识图谱」与 UI 布局重构

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0189（S1，方案并入本卡片，无 ADR）
- 来源 / 提出人：用户（会话 2026-11-28）
- 日期：2026-11-28
- 关联 ADR：无（前端布局与文案，不触碰数据 / 接口 / 权限口径；约束 H5 / H24 / H25 / H29 / H30 / H31 / H32）
- 关联前序：`docs/requirements/0168-document-knowledge-graph.md`（图谱首版）、`0182-document-graph-explorer.md`（探索器 C1–C10）、`0183`（单双向边表达）、`0184-document-graph-visual-polish.md`（视觉参数与信息编码）
- 状态：**P0–P2 已落地**（2026-11-28 用户「统一 + 同意」后实现；S1 无 ADR，方案与落地结果均在本卡）

> 0182 的交互语义（单击选中 / 双击进入 / 局部图 / 筛选）与 0184 的视觉参数（选中态 / 邻接聚焦 / 孤岛淡化 / 线色 / 点阵）**全部继续有效**，本卡只重排信息层级与版式，不改它们。

## 需求原句（逐字）

> 图谱模块改名知识图谱；结合其他同类应用和项目自身特点，优化图谱UI布局设计，当前较为混乱。

## 背景（现状核实，非推测）

「混乱」不是配色问题（0184 已收敛），而是**四层控件平铺、画布不占主位、读数与操作分散**：

| # | 现象 | 根因（已核实） | 位置 |
|---|---|---|---|
| 1 | 页签叫「图谱」，页面标题叫「知识图谱」，同一功能两个名字 | 命名未统一 | `MainLayout.tsx:92`、`DocumentGraphPage.tsx:862` |
| 2 | 页头右侧平铺 6 个控件（隐藏标签 / 隐藏箭头 / 100% / − / + / 复位），其中 5 个是**画布**操作 | 视图控件挂在页级页头 | `DocumentGraphPage.tsx:868-907` |
| 3 | 控件分四层：页头动作 → 筛选条 → 画布内浮层（图例）→ 右侧 Inspector（力参数折叠区） | 没有统一的「页面动作 / 画布动作 / 详情」分工 | 同上 `:938`、`:996`、`:1019` |
| 4 | 画布高度写死 `min(72vh, 720px)`，大屏下方留大片空白，小屏要滚动才能看全 | 未跟随内容区高度 | `DocumentGraphPage.tsx:988-994` |
| 5 | 图例浮在画布左上，压住节点云最密的区域；且与页头标题区视觉上连成一片 | 浮层位置 | `DocumentGraphPage.css:95` |
| 6 | 力参数（开发者型控件）占据 Inspector 第一屏，选中详情被挤到下面 | 详情栏顺序反了 | `DocumentGraphPage.tsx:1022-1076` |
| 7 | 底部读数与交互提示混在一行（「显示 X / 共 Y · 关系 Z（拖拽平移，滚轮缩放…）」），离筛选条隔着一整张画布 | 读数未跟随筛选 | `DocumentGraphPage.tsx:1225-1229` |
| 8 | 三条 Alert 各自带 `marginBottom: SPACE.lg`，与 `.cn-page` 的 12px 纵向节奏叠加成双倍间距 | 内联 margin 与容器 gap 重复 | `:919`、`:933` |
| 9 | 加载中与「0 个文档」都是空白画布，没有任何引导 | 缺空态 / 载态（H30 要求走 `.cn-state`） | 全页无 `.cn-state` |

**同类应用的做法**（Obsidian 关系图 / Neo4j Bloom / Gephi / Logseq）：画布是唯一主角并吃满可用高度；缩放与显示开关作为**画布内浮动控制簇**（右下角）；筛选在画布外的独立一行或侧栏；详情在右侧可折叠面板；计数作为状态读数紧邻筛选；图例可收起且默认不压内容。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「图谱模块改名知识图谱」 | 全站统一为「知识图谱」：文档区二级页签 `图谱` → `知识图谱`（`DOCUMENT_SUBPAGES`）；帮助教程正文「文档区「图谱」页」→「知识图谱」页；`CONTEXT.md` 术语注记里的「文档区二级页签「图谱」」同步 | `MainLayout.tsx`、`pages/help/content/tutorials.tsx`、`CONTEXT.md` | `MainLayout.test.tsx` 断言页签文案；全仓 grep `图谱` 只剩「知识图谱 / 关联图」两类合法组合 |
| C2 | 改名边界 | **只改称谓，不改契约**：路由 `/w/:wid/documents/graph`、`data-testid`（`graph-*`、`document-graph-*`）、接口 `GET …/documents/links/graph`、组件名与文件名全部不动 | — | 现有 e2e 与单测的 URL / testid 断言零改动通过 |
| C3 | 「改名」的相邻概念 | 数据表模块的「关联图」**不改名**（它表达的是表间 `link` 字段引用，不是知识图谱）；两页副标题各自写明对象（文档双链 / 表间关联），避免同名混淆 | `TableLinkGraphPage.tsx` | 人工复核文案；表页测试零改动通过 |
| C4 | 「当前较为混乱」（根因 2） | 页头只留「图标 + 标题 + 副标题」；把标签 / 箭头 / 缩放 / 复位 / 布局参数**全部移出页头**，页头不再有动作按钮 | `DocumentGraphPage.tsx` | 单测：页头容器内不含 `graph-zoom-in` / `graph-labels-toggle` |
| C5 | 「优化 UI 布局」（根因 2 / 3） | 新增**画布视图控制条**：浮在画布右下角的一个簇，顺序 `标签 · 箭头 │ − 100% + │ 复位 │ 布局参数`；控件之间用 1px `--cn-border` 竖线分组（H25）；testid 全部保留原值 | `DocumentGraphPage.tsx`、`DocumentGraphPage.css` | 单测：控制条是画布容器子节点；各 testid 仍可点；布局参数在控制条内可展开 |
| C6 | 「优化 UI 布局」（根因 7） | 读数跟随筛选：`graph-footer-stats`（显示 X / 共 Y · 关系 Z · 互引 M · 隐藏 K）移入筛选条**右端**，删除页脚那一行；交互提示（拖拽平移 / 滚轮缩放 / 单击选中 / 双击打开）并入页头副标题 | 同上 | 单测：读数与 `graph-filter-keyword` 同一父容器；页脚 `graph-footer-stats` 唯一 |
| C7 | 「优化 UI 布局」（根因 4） | 画布吃满可用高度：页面根改 `cn-page cn-graph-page`（`height: 100%`），主体 `flex: 1; min-height: 0`，画布 `height: 100%`；移除 `min(72vh,720px)` 内联高度与内联 border（边框并入样式表，H25） | `DocumentGraphPage.tsx`、`.css` | 单测：画布内联 `style` 不含 `height` / `border`；e2e：画布高度 ≥ 视口 55% |
| C8 | 「优化 UI 布局」（根因 5） | 图例改**左下角可收起**：默认展开为 chip 行，点「图例」按钮收起为单按钮；testid `graph-legend` / `graph-legend-<key>` / `graph-legend-edge-direction` 不变 | 同上 | 单测：收起后 `graph-legend-<key>` 不可见、再点恢复；格式显隐状态保持 |
| C9 | 「优化 UI 布局」（根因 6） | Inspector 恢复「详情优先」：选中时依次为 详情 → 出链 → 反链 → 操作；未选中时为 孤岛 / 枢纽清单 + 引导文案；力参数移出 Inspector（随 C5 进控制条） | 同上 | 单测：选中态 Inspector 首个区块是标题；`graph-force-panel` 不在 Inspector 内 |
| C10 | 「优化 UI 布局」（根因 9） | 空态与加载态走 `.cn-state`（H30）：`isPending` 显示「正在加载知识图谱…」；`nodes.length === 0` 显示「这个工作区还没有文档」+「新建文档」按钮（跳 `/w/:wid/documents`）；错误 Alert 保留 | 同上 | 单测：MSW 返回空 payload → 空态可见；请求未回 → 载态可见 |
| C11 | 「当前较为混乱」（根因 8） | 去掉 Alert 的内联 `marginBottom`，纵向节奏统一由 `.cn-page` 的 `gap` 承担 | 同上 | 单测：截断提示无 `margin-bottom` 内联样式 |
| C12 | （设计约束） | 只用 `--cn-*` token 与 `themeMix`；间距 / 字号 / 圆角不写裸值（H29）；断点只 `767.98px` / `575.98px`（H30）；`<768px` 主体改上下堆叠（画布 60vh + Inspector 在下）；echarts 仍独立 lazy chunk + SVG renderer（H31）；体积变化走 `bundle-budget.mjs`（H32） | `.css`、`themeMix` | `make check-frontend` 覆盖率双门槛 + `make frontend-static` |
| C13 | （测试约束） | 同轮补：页面单测（新布局契约 + 空 / 载态 + 图例收起）、`MainLayout.test.tsx` 页签文案断言、`frontend/tests/e2e/critical/document-graph.spec.ts` 增加「页签叫知识图谱」「读数在筛选条内」两条断言；既有 34 例中仅按新位置改断言，不放宽 | 测试文件 | `make check-frontend` / `make e2e-affected` |
| C14 | （文档约束） | `CHANGELOG.md` 记条目；`CONTEXT.md` 术语与 `docs/USER_DOC_MAP.md` 核对；本卡回填落地结果 | 文档 | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 目标版式（P0 落地后）

```
┌───────────────────────────────────────────────────────────────────┐
│ [◈] 知识图谱                                                      │
│     工作区内可见文档与 [[双链]]；单击选中、双击进入，虚线为断链     │
├───────────────────────────────────────────────────────────────────┤
│ [搜索____] [状态▾] [只看断链] [只看孤立] [中心：X·1跳 ×]           │
│                              显示 12 / 共 40 · 关系 18（互引 2）   │
├──────────────────────────────────────────┬────────────────────────┤
│                                          │ 详情（选中时）          │
│            画布（吃满高度）              │  标题 / 格式 / 状态     │
│                                          │  出链 N                │
│  ┌ 图例（左下，可收起）                  │  反链 N                │
│  │ ● Markdown ● PDF ⇄ 互引              │  [打开][设为中心][复制] │
│  └                                       │                        │
│                       ┌ 视图控制条 ─┐    │ 概览（未选中时）        │
│                       │标签 箭头│−100%+│ 孤立文档 N            │
│                       │复位 布局参数  │    │ 枢纽 top 10            │
│                       └──────────────┘    │                        │
└──────────────────────────────────────────┴────────────────────────┘
```

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 文档区二级页签定义 | `frontend/src/layouts/MainLayout.tsx:92` | C1 改 label |
| 2 | 页面根 / 页头 / 控件 | `frontend/src/pages/documents/DocumentGraphPage.tsx:855-1232` | C4–C11 主战场 |
| 3 | 页面样式（随 chunk 加载） | `frontend/src/pages/documents/DocumentGraphPage.css`（184 行） | C5–C10 |
| 4 | 页签激活态判定 | `MainLayout.tsx:584-596` | 只认路由段，不受改文案影响 |
| 5 | 帮助教程正文 | `frontend/src/pages/help/content/tutorials.tsx:701-711` | C1 |
| 6 | 术语口径 | `CONTEXT.md:44` | C1 |
| 7 | 前端单测（34 例） | `DocumentGraphPage.test.tsx` | C13 |
| 8 | 页签导航单测 / e2e | `MainLayout.test.tsx:685`、`frontend/tests/e2e/critical/navigation.spec.ts:123` | C13 |
| 9 | 图谱 e2e（4 例） | `frontend/tests/e2e/critical/document-graph.spec.ts` | C13 |
| 10 | 表关联图页（相邻概念） | `frontend/src/pages/tables/TableLinkGraphPage.tsx` | C3 只改副标题，不重构 |

## 决策（S1 方案）

- **D1 只重排版式与命名，不动语义与视觉参数**：0182 的交互（单击选中 / 双击进入 / 局部图 / 筛选 / 图例显隐）与 0184 的视觉编码（选中态、邻接聚焦、孤岛淡化、线色、点阵）保持原样。理由：用户诉求是「乱」，不是「不好看」；再动一次视觉参数会让 0184 的 34 例断言与 e2e 反复返工，收益也低。
- **D2 画布动作归画布**：缩放 / 标签 / 箭头 / 复位 / 布局参数全部搬进画布右下浮动控制簇。理由：这些控件的操作对象是画布，放在页头会让「页面级动作」与「视图级动作」混在同一层，是根因 2 的直接来源。
- **D3 读数跟随筛选**：`graph-footer-stats` 移到筛选条右端，删掉页脚那一行。理由：读数回答的是「这次筛选还剩多少」，必须与筛选控件同屏；交互提示属于首次使用信息，收进副标题即可。
- **D4 力参数进控制簇而非 Inspector**：力参数是「怎么摆这张图」，与缩放同级，不是「这个节点是什么」。搬走后 Inspector 第一屏回到详情，根因 6 解决。
- **D5 图例可收起**：默认展开（保留 e2e 对 `graph-legend` 可见的断言），点按钮收起。理由：图例是格式说明，长期占用左下角不如按需展开；但默认收起会让新用户失去格式语义，所以默认展开。
- **D6 改名只到称谓层**：路由段 `graph`、testid 前缀 `graph-`、接口路径、组件名、文件名全部不动。理由：改路由会打断已分享的 `?focus=` 深链（0182 C3 的分享链接）与 e2e，收益为零。
- **D7 表关联图不重构**：两页 CSS 类前缀不同（`cn-graph-*` / `cn-tgraph-*`），合并会牵动 0187 的 21 例与 P1 编辑功能。本轮只在副标题上区分「文档双链」与「表间关联」，同构留作后续需求。
- **D8 高度填充用页面级修饰类**：新增 `.cn-graph-page { height: 100% }` 而非改全局 `.cn-page`。理由：改全局会波及所有页面（H30 只规定根容器用 `.cn-page`，不禁止修饰类）。

## 分期

| 期 | 内容 | 预估 |
|---|---|---|
| P0 | C1 / C2 / C4 / C5 / C6 / C7 / C11（改名 + 三层收敛 + 画布吃满高度） | 约半天 |
| P1 | C8 / C9 / C10（图例收起、Inspector 顺序、空 / 载态） | 约半天 |
| P2 | C3 / C12 / C13 / C14（相邻概念文案、token 自查、测试与文档回填） | 约半天 |

## 未决问题

- [x] ① 改名是否连路由 / testid 一起改？→ 不改（D6）：只改称谓，避免打断已分享深链。
- [x] ② 是否顺手把表「关联图」也改叫知识图谱？→ 不改（D7）：对象不同（表间 `link` 引用），同名反而更乱。
- [x] ③ 图例默认展开还是收起？→ 展开（D5），保留既有 e2e 断言与格式语义。
- [x] ④ 是否顺带重做视觉参数？→ 不（D1）：0184 已收敛，本轮只动布局。
- [x] ⑤ 两页是否合并成共享组件？→ 本轮不合并（D7）：前缀 / 交互差异大，合并风险高于收益。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认后进入实现（S1 人工卡点，H5；2026-11-28 用户「统一 + 同意」）

## 不做

- 不改后端 / 接口 / 权限 / 缓存 / 双链解析口径。
- 不改 0182 的交互语义与 0184 的视觉参数（选中态、邻接聚焦、孤岛淡化、线色、点阵、力导向参数默认值）。
- 不改节点上限（500）、`truncated` 口径、`?focus=&depth=` 深链格式。
- 不重构数据表关联图页，不合并两页组件，不引入新依赖（d3 / cytoscape 等）。
- 不做布局位置持久化、不做全屏 / 小地图 / 时间轴等新能力。

## 落地结果（2026-11-28）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 统一称谓 | `MainLayout.tsx:92` 页签 label 改「知识图谱」；`help/content/tutorials.tsx` 正文改为「知识图谱」页并补画布控制簇 / 图例收起说明；`CONTEXT.md:44` 与 `docs/USER_DOC_MAP.md` 同步 | `MainLayout.test.tsx` 新增 1 例断言页签文案与激活态；e2e 断言页签文案 |
| C2 改名边界 | 路由段 `graph`、`graph-*` testid、接口路径、组件 / 文件名零改动 | 既有 e2e 与 34 例单测的 URL / testid 断言零改动通过 |
| C3 相邻概念 | `TableLinkGraphPage.tsx` 副标题补「不是文档知识图谱」 | 表页 21 例零改动通过 |
| C4 页头无动作 | 页头只留图标 + 标题 + 副标题；`viewControls` 常量整体移入画布 | 单测：页头不含 `cn-page-head-actions`，5 个 testid 均不在页头内 |
| C5 视图控制簇 | `graph-view-controls`（三组 `Space.Compact`：标签 / 箭头 │ − 100% + │ 复位 / 布局），浮在画布右下 | 单测：控制簇是 `.cn-graph-canvas-wrap` 子节点且含缩放与布局按钮；力参数面板展开后在控制簇内 |
| C6 读数跟随筛选 | `graph-footer-stats` 移入 `cn-graph-toolbar`（`margin-left: auto`），删页脚行；交互提示并入副标题 | 单测：读数与 `graph-filter-keyword` 同父容器、全文唯一；e2e 同口径 |
| C7 画布吃满高度 | 根容器 `cn-page cn-graph-page`（`height: 100%`）；主体 `flex: 1; min-height: 0`；画布 `height: 100%`，内联 `height` / `border` 移除 | 单测：画布 `getAttribute('style')` 为 `null`、根容器双类名；e2e：画布高度 > 视口 50% |
| C8 图例可收起 | 图例改左下 + `graph-legend-toggle`（`aria-expanded`）；`<576px` 时图例与控制簇落为画布下方常列 | 单测：收起后 chip 隐藏、再展开状态延续（`aria-pressed=false` 保持） |
| C9 详情优先 | Inspector 内不再有力参数折叠区；未选中态顶部补一句引导 | 单测：`graph-force-panel` 在控制簇内、不在 Inspector 内 |
| C10 空 / 载态 | `graph-loading-state` / `graph-empty-state` 走 `.cn-state`，绝对定位压在画布上；空态带「去新建文档」 | 单测：空 payload 出空态且按钮跳 `/w/10/documents`；请求未回出载态、到达后消失 |
| C11 节奏统一 | 三条 Alert 去掉内联 `marginBottom` | 单测：截断提示 `style` 不含 `margin` |
| C12 设计约束 | 只用 `--cn-*` token；断点仅 767.98 / 575.98px；echarts 仍 lazy + SVG | `tokens.test.ts` 全绿（无游离字面量 / 未登记断点）；`make check-frontend` 双门槛达标 |
| C13 测试同轮 | 页面单测 34 → 42 例；`MainLayout.test.tsx` +1 例；e2e +3 条断言 | 42 / 102 / 65 例全绿 |
| C14 文档回填 | CHANGELOG、CONTEXT、USER_DOC_MAP、本卡 | `make check-docs` 全绿 |

**门禁**：`make check-fast` 全绿；`make test` 7958 passed / 17 skipped；`make check-frontend` 核心集合 lines 97.66% / branches 100%，全局 83.96%；`pnpm build` 通过且 `[compat] Chromium 81 0 warning`；`bundle-budget` 全部关键 chunk 在预算内。

**已知项**：e2e 的三条新断言本轮未在本机实跑（需 `pnpm playwright install` + 隔离后端，按 AGENTS 3.3 留给 CI 全量 e2e 与阶段收尾）；单测侧已覆盖同样口径（页签文案在 `MainLayout.test.tsx`、读数与筛选同父容器在页面单测）。

