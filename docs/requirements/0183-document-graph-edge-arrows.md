# 0183 文档图谱单双向边表达优化（S1）

- 编号：0183
- 来源 / 提出人：用户（会话 2026-11-27，0182 图谱增强上线后复核）
- 日期：2026-11-27
- 关联 ADR：无（S1，方案并入本卡片；前端约束 H24/H25/H29/H30/H31、可见性 H33）
- 关联前序：`docs/requirements/0168-document-knowledge-graph.md`（图谱首版）、`docs/requirements/0182-document-graph-explorer.md`（探索器增强）
- 状态：已落地（2026-11-27 用户「1 按建议，2 算，3 加」确认范围，同日完成 C1–C8）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。0168 / 0182 的约束仍有效，本卡只补增量，不重编号。

## 需求原句（逐字）

> 文档，图谱，双向分两个箭头太占空间，且显得很乱，能否通过箭头自身的差异区分单双向，请结合最佳实践给出方案。

> 1 按建议，2 算，3 加

## 背景（现象与已核实的根因）

| # | 现象 | 根因（已核实） |
|---|---|---|
| 1 | 两篇文档互相 `[[双链]]` 时，画布上出现两条各带一个箭头的弧线，占两倍空间还留空洞 | 互引在数据层是两条独立有向边（`seen_edges` 按 `(source, target)` 去重，`(1,2)` 与 `(2,1)` 互不冲突）；`DocumentGraphPage.tsx` 又给每条边写死 `lineStyle.curveness: 0.06`，`forceLayout.js` 的控制点按 `source→target` 定向计算（`points[2] = [mid - (p1y-p2y)*c, mid - (p2x-p1x)*c]`），反向边把两端对调后控制点镜像到另一侧，于是两条弧线分列两侧 |
| 2 | 改了 `curveness` 也没把两条线分开 | echarts 自带的 `autoCurveness`（`multipleGraphEdgeHelper.js`）本来会给反向边分配相反曲率，但 `forceLayout.js:106` 里 `retrieve3(edgeModel.get(['lineStyle','curveness']), -getCurvenessForEdge(...), 0)` 表明显式 `curveness` 优先级更高，写死 0.06 等于把它整个关掉 |
| 3 | 单向与双向在视觉上无法一眼区分 | 每条边都用 series 级 `edgeSymbol: ['none','arrow']`，箭头数量恒为 1，不携带「对方是否也引用我」的信息 |
| 4 | 缩小到低倍率时箭头糊成小三角，反而更像噪声 | 箭头只有尺寸、没有显隐阈值；标签已有 `LABEL_ZOOM_THRESHOLD` 一套淡化机制，箭头没有对应的 |

echarts 侧已核实可以逐边定制箭头（`edgeVisual.js:58-88`：`itemModel.getShallow('symbol', true)` 覆盖 series 级 `edgeSymbol`；`adjustEdge.js:114-165`：两端都有 symbol 时曲线按 `intersectCurveCircle` 两端截短、直线按 `symbolSize * scale` 两端内缩；`Line.js:309` 的旋转角由切线推出，起点箭头自动反向，无需手工旋转）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「双向分两个箭头太占空间」 | 新增导出纯函数 `foldReciprocal(edges)`：把 `(a→b)` 与 `(b→a)` 按无序对归一（键取 `min-max`）折叠成一条画布边，标 `mutual = true` 并保留对方 `raw` 为 `reverseRaw`；`broken` / `ambiguous` 取两侧或值。**只作用于画布与计数**，`visible.edges` 仍保有有向明细供 Inspector | `DocumentGraphPage.tsx` | 纯函数单测：互引两输入 → 一输出且 `mutual`；单向不折叠；断链从一侧合并 |
| C2 | 「通过箭头自身的差异区分单双向」 | link 级 `symbol`：互引 `['arrow','arrow']`（两端箭头）、单向沿用 `['none','arrow']`；`edgeSymbolSize` 保持 7。依据 Graphviz `dir=both` 的通行做法，一条线两端箭头即双向 | `DocumentGraphPage.tsx` | 单测：互引边 `series.links[i].symbol` 为双元素且两端都是 arrow；单身边起点为 `none` |
| C3 | 「显得很乱」（度数口径一致性） | `buildDegrees` 改按**唯一关联文档数**：互引只给两端各 +1（否则「关联 2 条」但画布上只有一条线）。节点尺寸分级、枢纽排行、孤立点判定、筛选「只看孤立点」全部沿用同一份度数 | `DocumentGraphPage.tsx` | 单测：互引节点的度数等于唯一邻居数，不是有向边数 |
| C4 | 「显得很乱」（计数一致性） | 页脚关系数改为折叠后的线条数，并在存在互引时补「（互引 M）」；`graph-footer-stats` 原有「显示 X / 共 Y 个节点」口径不变 | `DocumentGraphPage.tsx` | 单测：页脚出现「关系 N（互引 M）」；空图仍是「关系 0」 |
| C5 | 「通过箭头自身的差异区分单双向」 | 图例末尾追加**不可点击**的说明项「→ 引用 ⇄ 互引」（无 `aria-pressed`、不参与格式显隐），样式 `.cn-graph-legend-note` 只允许 `--cn-*` token | `DocumentGraphPage.tsx`、`index.css` | 单测：说明项存在且不是 button；token 门禁通过 |
| C6 | 「显得很乱」 | Inspector 出链 / 反链保留**有向明细**（谁引用谁不能丢），互引条目追加「⇄」角标；edge tooltip 的 hints 追加「互相引用」 | `DocumentGraphPage.tsx` | 单测：互引时 tooltip 含「互相引用」；Inspector 互引条目带角标 |
| C7 | 用户确认第 3 点「加」（箭头显隐开关） | 工具栏新增 `graph-arrows-toggle`（`aria-pressed`，文案「隐藏箭头 / 显示箭头」，默认显示）；低倍率（< 40%）自动收起箭头；显隐走**单独 `setOption`**（与 `labelsVisible` 同一手法），不得并入主 option，否则每次缩放阈值跨越都 notMerge 重建、力导向重排跳动 | `DocumentGraphPage.tsx` | 单测：切换后 `setOption` 只下发了 `symbol`；低倍率下箭头为 `none` |
| C8 | （设计 / 测试 / 文档约束） | 只用 `--cn-*` token；断点仍只 767.98 / 575.98px；echarts 保持独立 lazy chunk（H31）；同轮补前端单测；CHANGELOG 增条目；本卡回填落地结果；e2e 现有 4 例的断言面（节点数、图例、聚焦、筛选、双击）不受影响 | 样式、测试、`CHANGELOG.md` | `make check-fast` / `make test` / `make check-frontend` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 画布 option 构造 | `DocumentGraphPage.tsx:buildOption`（`:260` 起） | C1 / C2 / C4 / C6 主战场 |
| 2 | 度数计算 | `DocumentGraphPage.tsx:buildDegrees`（`:132-141`） | C3 |
| 3 | 图例 | `DocumentGraphPage.tsx:731-746`、`index.css:11388-11430` | C5 |
| 4 | Inspector 出链 / 反链 | `DocumentGraphPage.tsx:805/827` | C6 |
| 5 | 工具栏 | `DocumentGraphPage.tsx:610-618`（`graph-labels-toggle` 同排） | C7 |
| 6 | 标签显隐下发 | `DocumentGraphPage.tsx:541-545` | C7 仿写 |

后端无改动：互引在 payload 里本来就是两条有向边，折叠属于纯展示口径（同 0182 D5「筛选只在前端」）。

## 决策（并入本卡的 S1 方案）

- **D1 折叠而不是分离曲率**：只给反向边相反曲率（`±0.2`）能把两条线分开，但仍画两条、仍占两倍面积，与「太占空间」的原始诉求相悖；折叠成一条后线条数减半，且「一条线的箭头数」天然承载单/双向语义（Graphviz `dir=both`、Cytoscape `source-arrow-shape` 同为该做法）。
- **D2 用 link 级 `symbol` 而不是新增第二个 series**：拆 series 会让力导向、筛选、emphasis 邻接高亮各跑两套；`edgeVisual.js` 确认 link 级 `symbol` 逐项覆盖 series 级，单 series 即可。
- **D3 度数改口径而不是保留有向计数**：折叠后画布上互引只剩一条线，若度数仍按有向边算，Inspector 会写「关联 2 条」而图上只有一条线连出去，是自相矛盾的读数；唯一邻居数与「线」一一对应。
- **D4 关系计数包含互引**：互引折成一条线，但它是两条真实关系，页脚单独给「（互引 M）」让总量与结构都可读，不做取舍。
- **D5 箭头显隐单独下发**：沿用 0182 标签淡化的处置（`labelsVisible` 走独立 `setOption`），避免重建 option 触发力导向重排；阈值 40% 低于标签的 60%，让箭头比标签更早消失，缩小后先丢细节噪声。
- **D6 Inspector 不做折叠**：有向明细是「谁引用谁」的唯一出口，折叠只发生在画布与聚合计数上。

## 落地结果（2026-11-27）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 折叠互引 | `DocumentGraphPage.tsx::foldReciprocal` + `pairKey`；组件内 `folded`（全图，供度数）与 `displayEdges`（可见图，供画布与计数） | 单测：3 条有向边（1→2、2→1、1→3）→ 2 条线；互引项 `mutual:true` / `reverseRaw:'[[乙]]'` / `broken` 与 `ambiguous` 取并集 |
| C2 双端箭头 | `buildOption` 的 links 逐条下发 `symbol`；series `edgeSymbol` 保持 `['none','arrow']` | 存量断言 `series.edgeSymbol === ['none','arrow']` 仍绿；互引项 `symbol === ['arrow','arrow']`，单向项 `symbol === undefined`（沿用 series 默认） |
| C3 度数口径 | `buildDegrees` 入参改为折叠后的边；筛选 / 枢纽 / 孤岛共用同一份度数 | 互引场景下点节点 1：`关联 2 条`（唯一邻居 2、3），而有向明细仍为 `出链 2` / `反链 1` |
| C4 关系计数 | 页脚「关系 {折叠后线条数}（互引 M）」 | 互引场景页脚：`关系 2（互引 1）`；无互引时仍为 `关系 N`，旧所有数据渲染变化为零 |
| C5 图例说明项 | `.cn-graph-legend-note`（`index.css`）+ `data-testid="graph-legend-edge-direction"` | 单测：元素为 `SPAN`、无 `aria-pressed`、点击后页脚仍 `显示 4 / 共 4`（不触发格式过滤） |
| C6 有向明细 | Inspector 互引条目 `⇄` 角标；edge tooltip hints 追加「互相引用」 | 单测：tooltip 含 `互相引用` 且同时给出两侧原文；Inspector 含 `⇄ 互引` |
| C7 箭头开关 | 工具栏 `graph-arrows-toggle`；`ARROW_ZOOM_THRESHOLD = 0.4`；与标签合成一次 `setOption` 只下发 `label` / `edgeSymbol` / `edgeSymbolSize` | 单测：初始 `aria-pressed=true`、`edgeSymbol=['none','arrow']`；点关后 `'none'` 且 `edgeSymbolSize=0`；重开后连缩 5 档（约 33%）自动收起 |
| C8 口径与门禁 | 只用 token、断点不变、echarts 独立 chunk、单测 + CHANGELOG + 本卡回填 | `make check-fast` 绿；`make test` 7840 passed / 17 skipped；`make check-frontend` 绿（核心集合 lines 97.66% / branches 100%，全局 83.95%） |

## 未决问题

- [x] 度数口径：改为唯一关联文档数（用户「1 按建议」）
- [x] 互引是否计入关系计数：计入，并单列互引条数（用户「2 算」）
- [x] 是否新增箭头显隐开关：加，默认显示、低倍率自动收起（用户「3 加」）
- [x] 是否需要改后端 payload：不需要，折叠是纯展示口径（同 0182 D5）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-27）

## 不做

- 不改后端 `build_link_graph` 的边产物（互引仍是两条有向边，供 Inspector 与后续反链索引使用）。
- 不引入新依赖、不改双链语法、不加块级模型。
- 不做边的悬停分离、不做「点击线切换方向」这类交互（只读可视化）。
- 不调整 0168 的节点上限与 0182 的筛选项口径。
