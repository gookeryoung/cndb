# 0184 文档图谱视觉打磨（S1）

- 编号：0184
- 来源 / 提出人：用户（会话 2026-11-27，0182 图谱探索器上线后复核）
- 日期：2026-11-27
- 关联 ADR：无（S1，方案并入本卡片；前端约束 H24 / H25 / H29 / H30 / H31）
- 关联前序：`docs/requirements/0182-document-graph-explorer.md`（探索器 C1–C10 已落地）、`docs/requirements/0183-document-graph-edge-arrows.md`（互引折叠与箭头表义，本卡在其之上做视觉）、`docs/requirements/0168-document-knowledge-graph.md`（图谱首版）
- 状态：已落地（2026-11-27 P0–P2 全部实现；三项口径由用户「按倾向意见继续」冻结见 D6–D8；原编号 0183 与同号卡片冲突，已按 H8 改为 0184，实施排在需求 0183 提交之后）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。0182 的 C1–C10 仍有效，本卡只补视觉增量，不重编号、不复用 0182 / 0168 编号。

## 需求原句（逐字）

> 文档，图谱，当前的图谱风格还是不够美观，请结合最佳实践，为美化方案给出可行建议。

> 按倾向意见继续

## 背景（0182 落地后复核发现的问题）

「不美观」不是布局问题，是**样式参数与信息编码**问题。九项根因，全部已在代码中核实：

| # | 现象 | 根因（已核实） |
|---|---|---|
| 1 | 点中节点后画布毫无变化，只有右侧 Inspector 换内容 | `buildOption(nodes, edges, colors, force)` 无 `selectedId` 参数（`DocumentGraphPage.tsx:258`），`selectedId` 只喂给 Inspector（`:437`），从未回写画布 |
| 2 | 孤立点在画布上与已连接节点同等显眼，图看起来「满但没信息」 | 节点 `itemStyle` 只有按格式着色（`:325`），无度数 / 孤立区分；`findIsolated` 只服务侧栏清单（`:242`） |
| 3 | 每个节点都有一圈深灰粗边，像「一堆图钉」 | 节点 `borderColor: colors.border` 即 `--cn-border`（浅色 `#6e7781`），1px（`:327-328`）；`--cn-border` 是为 1px UI 线调的深灰，用作图形描边过重 |
| 4 | 边统一灰色、无法读出「谁引用谁」 | 边色 `colors.border`、无方向编码（`:343`）；箭头 7px 在 0.55 透明度灰线上几乎看不见 |
| 5 | 标签压线、字挤在一起 | `label.fontSize: 11` 是裸值（`:310`），无 `backgroundColor` 底衬（`:306-312`），跨边时字与线糊成一片 |
| 6 | 改筛选 / 改力参数后整张图重排、画布「跳」一下 | 更新走 `setOption(option, true)`（`:527`）notMerge 全量重建，力导向从零重算 |
| 7 | 同一对文档互相引用时，两根线叠成一条透镜状粗线 | **已由需求 0183 解决**：`foldReciprocal` 按无序对把互引折成一条线、两端箭头表义（`DocumentGraphPage.tsx:163`，2026-11-27 已落地）。本卡不再处理，见 D5 / D10 |
| 8 | 浮层拥挤：图例与力参数面板都浮在画布底部两侧，遮住图 | `.cn-graph-legend` 与 `.cn-graph-force` 都是 `position: absolute`（`index.css:11388`、`:11428`），各带 `opacity: .94` 底卡 |
| 9 | 目录节点与普通文档只能靠颜色区分，色弱用户读不出 | `symbolSize` 与 `itemStyle.color` 是唯一编码（`:325`、`:330`），无非颜色通道 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「不够美观」（根因 1） | `buildOption` 增 `selectedId` 参数，选中节点：`borderColor` 走 `--cn-primary`（H24 选中语义）、`borderWidth: 2`、`shadowBlur: 10` + 同色 `shadowColor`、`symbolSize × 1.15`（仍受 40 上限约束）；同期 graph 开 `focusNodeAdjacency` 作邻接高亮 | `DocumentGraphPage.tsx` | 前端单测：`series.data[选中].itemStyle.borderColor` 与未选中不同，`symbolSize` 增大且 `<= 40`；e2e：单击后该节点 SVG 属性变化 |
| C2 | 「不够美观」（根因 1） | 常驻邻接聚焦：有 `selectedId` 时非邻接节点 `opacity: 0.12`、非邻接边 `opacity: 0.06`；点画布空白处取消选中（`chart.on('click')` 的 `dataType !== 'node'` 分支） | `DocumentGraphPage.tsx` | 前端单测：选中后非邻接 `itemStyle.opacity < 0.2` |
| C3 | 「不够美观」（根因 2） | 孤立点（`findIsolated`，非断链且度 0）画布默认淡化：`opacity: 0.35`、`symbolSize: 10`、不显示标签；侧栏「孤岛」清单保留（0182 C8 不变） | `DocumentGraphPage.tsx` | 前端单测：孤立点 `symbolSize === 10` 且 `label.show === false` |
| C4 | 「不够美观」（根因 3） | 节点描边改 `--cn-bg-container` 2px 作「分隔环」（在彩色节点与彩色边之间留白），不再用 `--cn-border`；`--cn-border` 仍用于画布外框等 UI 边界（H25 不变） | `DocumentGraphPage.tsx`、`readThemeColors` | 前端单测：节点 `itemStyle.borderColor` 取到的是 container 色 |
| C5 | 「不够美观」（根因 4） | 边按**源节点**格式色着色，但不直接用饱和色：以 `themeMix` 兼容层把格式色与 `--cn-border` 混合（新增注册项），得到低饱和「线色」；断链保持 `--cn-error` 虚线（形状 + 颜色双通道，不与灰线争权重） | `DocumentGraphPage.tsx`、`themeMix.ts` | 前端单测：正常边 `lineStyle.color` 不含 `var(`，断链边仍为 error 色 + `dashed` |
| C6 | 「不够美观」（根因 4） | 边弱化：正常边 `lineStyle.width: 1`、`opacity: 0.32`；选中邻接边 `width: 1.6`、`opacity: 0.9`。**箭头不并入主 option**：`edgeSymbol` / `edgeSymbolSize` 由需求 0183 C7 的独立 `setOption` 下发（含低倍率自动收起），本卡只改线宽与透明度 | `DocumentGraphPage.tsx` | 前端单测：`links` 的 `lineStyle.width` / `opacity` 按 C6 取值；箭头显隐仍由独立 `setOption` 承担（0183 既有用例仍绿） |
| C7 | 「不够美观」（根因 5） | 标签底衬：仅度数 ≥ 2 的节点加 `backgroundColor: <container 色>` + `padding: [2,4]` + `borderRadius: 3`（避让交叉边时不糊）；度数 < 2 的保持无底衬，避免满屏小方块 | `DocumentGraphPage.tsx` | 前端单测：高度数节点 `label.backgroundColor` 存在、低度数节点为 `'transparent'` |
| C8 | 「不够美观」（根因 5） | 标签字号 / 字重 / 颜色改读计算值：新增 `readThemeMetrics()` 读 `--cn-text-2xs`、`--cn-weight-medium`（与 `readThemeColors` 同源，主题切换时重算），消除 `fontSize: 11` 裸值（H29） | `DocumentGraphPage.tsx` | 前端单测：`series.label.fontSize` 来自 token 解析结果而非字面量 |
| C9 | 「不够美观」（根因 9） | 目录节点用 `symbol: 'roundRect'`（形状 + 颜色双编码）；`symbolSize` 换算保持圆形视觉面积等价（宽 = size，高 = size × 0.75） | `DocumentGraphPage.tsx` | 前端单测：`is_folder` 节点 `symbol === 'roundRect'`，普通节点为 `'circle'` |
| C10 | 「不够美观」（根因 8） | 浮层重排：图例从画布左下角改为画布**左上**横向 chip 行（不压节点云中心）；力参数面板从画布右下浮层移入 Inspector 顶部可折叠区（`767.98px` 以下仍隐藏） | `DocumentGraphPage.tsx`、`index.css` | 前端单测：力参数控件在 Inspector 容器内；e2e：图例仍可点击显隐 |
| C11 | 「结合最佳实践」（根因 7） | **移出本卡**：互引折叠已由需求 0183 C1 / C2 落地（`foldReciprocal`、折叠边两端箭头、页脚「关系 N（互引 M）」）。本卡不重复实现，也不得改动其 `mutual` / `reverseRaw` / 互引计数 / 箭头开关语义；原「曲率 0 分离两条线」方案一并作废 | — | 无需新增验收（由 0183 单测覆盖） |
| C12 | 「结合最佳实践」（根因 6） | 布局稳定：`force.initLayout: 'circular'` + `layoutAnimation: true`；`edgeLength: [60,140]`、`repulsion` 默认调至 220（仍在 0182 C9 的 40–600 滑轨内）；更新改 `setOption(option, false)`（merge）而非 notMerge，标签显隐仍单独下发 | `DocumentGraphPage.tsx` | 前端单测：`force.initLayout === 'circular'`；`setOption` 第二次参数为 `false` |
| C13 | 「结合最佳实践」 | 画布极淡点阵网格：16px 网格，颜色由 `themeMix` 注册项生成（`var(--cn-border-soft)` 低比例 → transparent）；不新增 `--cn-graph-grid` 主题变量（10 套主题同步 + 无独立语义，成本不值） | `index.css`、`themeMix.ts` | `make frontend-coverage`（H24 手写低比例 color-mix 检查通过） |
| C14 | （设计 / 测试 / 文档约束） | 只用 `--cn-*` token 与 `themeMix` 兼容层；断点仅 767.98 / 575.98px；echarts 保持独立 lazy chunk（H31）与 SVG renderer（e2e 依赖）；同轮补前端单测 + e2e + CHANGELOG；本卡回填落地结果 | 新样式、测试文件、`CHANGELOG.md` | `make check-fast` / `make flow` / `make check-frontend` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 画布 option 构建 | `frontend/src/pages/documents/DocumentGraphPage.tsx:398 buildOption` | C1–C9 / C12 主战场；需新增 `selectedId`、`metrics` 入参（互引折叠已由 0183 落地，不必重做） |
| 2 | 主题读取 | 同文件 `:147 readThemeColors`、`:172 readThemeMetrics`（新增） | C4 / C7 / C8 依赖，需扩为含 container / 字号 / 字重 |
| 3 | 节点尺寸与度数 | 同文件 `:216 buildDegrees`、`:269 nodeSize` | C3 / C9 触碰，但度数口径已由 0183 C3 定为唯一关联数，不得回退 |
| 4 | 互引边折叠 | `DocumentGraphPage.tsx:242 foldReciprocal`（已由 0183 落地） | 本卡只在其输出上做样式，不改折叠语义与计数 |
| 5 | 选中态写入 | 同文件 `:664 option = useMemo(...)`、`:690` 清选中 effect | C1 / C2 |
| 6 | 画布更新 | 同文件 `:779 setOption(option, false)` | C12（notMerge → merge） |
| 7 | 图例 / 力面板 DOM | 同文件 `:996`（图例）、`:1036`（力面板，已在 Inspector 内） | C10 |
| 8 | 图谱样式 | `frontend/src/pages/documents/DocumentGraphPage.css`（`.cn-graph-*` 已随页面 lazy 加载，不再在 index.css） | C10 / C13 |
| 9 | color-mix 注册表 | `frontend/src/theme/themeMix.ts:44 MIX_REGISTRY` | C5 / C13 新增注册项 |
| 10 | 格式配色 | `frontend/src/components/Document/docFormat.ts:41 DOC_FORMAT_META` | C5 线色来源（不改表本身） |
| 11 | 前端单测 | `frontend/src/pages/documents/DocumentGraphPage.test.tsx`（34 例） | 已同步：`symbolSize` 经新增 `sizeOf()` 取宽（目录节点为 `[宽, 高]`）、`every <= 40`、`blur.opacity < 0.5`、`links[0].type === 'solid'`、`forceOf()` 期望 `repulsion:220` / `edgeLength:[60,140]` |
| 12 | e2e | `frontend/tests/e2e/critical/document-graph.spec.ts`（4 例） | 只按 `graph-legend` testid 判定，图例移左上、力面板移入 Inspector 均不影响；无需改动 |

## 决策（并入本卡的 S1 方案）

- **D1 只改样式参数与信息编码，不动布局引擎**：观感问题的九项根因里只有 #6 与布局相关，且用 `initLayout` + merge 即可解决；不换 d3 / cytoscape、不改力导向算法。理由：布局改动代价最大且冲击 e2e 的节点定位方式，收益远低于参数调整。
- **D2 「美化」按测试契约变更处理**：`DocumentGraphPage.test.tsx` 的 `symbolSize === 14`、`forceOf()` 匹配、边样式断言都是硬编码视觉参数，改实现必须同轮改断言并说明新口径，不允许为了让测试过而保留旧参数。
- **D3 互引边折叠放前端、不上下游改**：后端 `seen_edges` 只按有序对去重是**正确**的（有向图的 A→B 与 B→A 是两条不同的语义关系）；折叠只发生在**渲染层**。理由：改后端会让接口丢失方向语义，Inspector 与度数都依赖它。
- **D4 度数口径随 0183 冻结**：度数已由需求 0183 C3 改为「唯一关联文档数」（`buildDegrees` 入参是折叠后的边，互引只给两端各 +1）。本卡沿用该口径，不再改回有向计数 —— 否则节点尺寸与枢纽排序会和画布上的线条数自相矛盾。
- **D5 折叠边与箭头形态已由 0183 落地**：互引折叠成一条线、`symbol: ['arrow','arrow']` 由 0183 C1 / C2 实现；箭头显隐（`graph-arrows-toggle`、`ARROW_ZOOM_THRESHOLD = 0.4`）由 0183 C7 实现且走独立 `setOption`。本卡 C6 只调线宽 / 透明度，不改箭头形态，也不得把 `edgeSymbol` 并回主 option（会把显隐开关打回失效）。
- **D6 H25 口径（用户已确认）**：H25 的「静态 1px 中性线」约束**不覆盖数据可视化图形元素**。节点描边、边线宽属于图形编码，可破例（C4 用 container 色 2px 分隔环，C1 选中态 2px primary）；UI 边界（画布外框、Inspector 卡片、浮层）仍严格 1px `--cn-border`。
- **D7 C8 口径（用户已确认）**：孤立点在画布默认淡化**不违反** 0182 C8。C8 要求的是「能找出孤立点」，侧栏清单完整保留即可；画布淡化反而是让清单成为主要入口。
- **D8 彩色边口径（用户已确认）**：接受边按源节点格式色着色。断链红虚线的视觉权重靠**形状（虚线）+ 颜色（error）+ 单箭头**补偿，不靠线宽堆叠。
- **D10 与需求 0183 的分工**：0183（单双向边表达，2026-11-27 已落地）负责**折叠与计数语义**——`foldReciprocal`、互引两端箭头、度数改唯一关联数、页脚「关系 N（互引 M）」、图例箭头说明项、`graph-arrows-toggle` 与低倍率收起。本卡负责**视觉参数与信息编码**——选中态、邻接聚焦、孤岛淡化、描边分隔环、线色、标签底衬与字号 token 化、目录形状、浮层重排、布局稳定、点阵网格。两卡同号冲突已按 H8 拆开：0183 保留边表达，本卡改用 0184。
- **D9 不新增主题变量做网格**：点阵走 `MIX_REGISTRY` 注册项，避免为一张装饰网格在 10 套主题里各加一个颜色变量。

## 分期

| 期 | 内容 | 预估 | 说明 |
|---|---|---|---|
| P0 | C1 / C2 / C3 / C6 / C7 | 约半天 | 选中态 + 邻接聚焦 + 孤立点淡化 + 边弱化 + 标签底衬；纯参数，收益最高 |
| P1 | C4 / C5 / C8 / C9 / C10 | 约 1 天 | 描边分隔环 + 彩色边 + 字号 token 化 + 目录方形 + 浮层重排；触碰 themeMix 与新样式 |
| P2 | C12 / C13 | 约 1 天 | 布局稳定 + 点阵网格（原 C11 互引折叠已移出、由 0183 落地）；触碰 setOption 语义与样式，风险最高放最后 |
| 收尾 | C14 | — | 门禁全绿、CHANGELOG、本卡回填 |

## 落地结果（2026-11-27）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 选中态 | `DocumentGraphPage.tsx:398 buildOption` 增 `selectedId` 入参；选中节点 `borderColor: colors.primary`、`borderWidth: 2`、`shadowBlur: 10` + 同色 `shadowColor`、`symbolSize × SELECTED_NODE_SCALE(1.15)` 且仍受 `MAX_NODE_SIZE(40)` 约束 | 单测：单击后 `itemStyle.borderColor` 与未选中不同、`borderWidth === 2`、`shadowBlur > 0`、`sizeOf()` 增大且 `<= 40` |
| C2 常驻邻接聚焦 | `buildOption` 内 `adjacent` 集合 + `isDimmed` / `dimmedEdge` / `adjacentEdge`；`DIMMED_NODE_OPACITY(0.12)`、`DIMMED_EDGE_OPACITY(0.06)`；`chart.on('click')` 的 `dataType !== 'node'` 分支 `setSelectedId(null)` | 单测：选中后非邻接节点 `itemStyle.opacity < 0.2`、非邻接边 `opacity === 0.06`；点 `{dataType:'series'}` 后选中清空 |
| C3 孤岛淡化 | `isIsolated = !node.broken && nodeDegree === 0 && !isSelected`；`ISOLATED_NODE_SIZE(10)`、`ISOLATED_NODE_OPACITY(0.35)`、`label.show: false`；侧栏 `isolated` 清单未改 | 单测：孤立点 `sizeOf() === 10`、`opacity === 0.35`、`label.show === false`，`graph-isolated-list` 仍在 |
| C4 描边分隔环 | `ThemeColors` 增 `container`（`--cn-bg-container`，兜底 `#ffffff`）；未选中节点 `borderColor: colors.container` | 单测：未选中节点 `borderColor` 为 container 色而非 `--cn-border` |
| C5 降饱和线色 | 新增 `edgeColor(edge, source, colors)`：断链 → `colors.error`；否则 `mixColor(formatColor(source, colors), EDGE_COLOR_FORMAT_PCT(45), colors.border)`；`nodeById` 提供源节点 | 单测：正常边 `lineStyle.color` 不含 `var(`；断链边仍 error 色 + `dashed`。走运行时 `mixColor()`，`MIX_REGISTRY` 无需为 C5 加项 |
| C6 边弱化 | `EDGE_WIDTH(1)` / `EDGE_OPACITY(0.32)`；选中邻接 `EDGE_EMPHASIS_WIDTH(1.6)` / `EDGE_EMPHASIS_OPACITY(0.9)`；断链单独 `BROKEN_EDGE_OPACITY(0.6)`；`edgeSymbol` / `edgeSymbolSize` 仍由 0183 C7 的独立 `setOption` 下发 | 单测：`lineStyle.width === 1`、`opacity === 0.32`；选中邻接边 `1.6` / `0.9`；0183 的箭头开关用例仍绿 |
| C7 标签底衬 | 节点 `label`：`...(isIsolated ? { show: false } : {})`、`backgroundColor: nodeDegree >= LABEL_BACKPLATE_MIN_DEGREE(2) ? colors.container : 'transparent'`、`padding: [2, 4]`、`borderRadius: 3` | 单测：度 ≥2 节点底衬非 `transparent`、度 1 节点为 `'transparent'`、`padding` 为 `[2,4]`。**刻意不下发无条件 `show`**，避免覆盖缩放 / 开关那次独立 `setOption` |
| C8 字号 token 化 | 新增 `ThemeMetrics` + `readThemeMetrics()`（`--cn-text-2xs` 兜底 11、`--cn-weight-medium` 兜底 500，`Number.isFinite` 校验）；`series.label.fontSize / fontWeight` 取解析值，`fontSize: 11` 裸值已消除 | 单测：`series.label.fontSize === 11`（来自 token 解析，非字面量传入）；组件侧 `metrics` 随 `themeMode` 重算 |
| C9 目录形状 | 节点 `symbol: node.is_folder ? 'roundRect' : 'circle'`、`symbolSize: node.is_folder ? [size, Math.round(size * FOLDER_SYMBOL_RATIO(0.75))] : size` | 单测：目录节点 `symbol === 'roundRect'` 且 `symbolSize` 为数组、普通节点 `'circle'` |
| C10 浮层重排 | 图例 `.cn-graph-legend` 由 `bottom` 改 `top`（左上 chip 行，575.98px 下改 `top: var(--cn-space-xs)`）；`.cn-graph-force` 去掉 absolute / 定位 / 底衬，只留栏式布局；力面板 JSX 移入 Inspector 首个 `Collapse` 项（`forcePanelOpen` state，`767.98px` 以下仍 `display: none`），`graph-force-*` testid 全部保留 | 单测：点击「布局参数」后 `findByTestId('graph-force-repulsion-wrap')` 出现，滑轨可调、可恢复默认；e2e 只按 `graph-legend` testid 判定，不受位置变更影响 |
| C11 互引折叠 | 未在本卡实现（已由需求 0183 C1 / C2 落地）；本卡未改 `foldReciprocal` / `mutual` / `reverseRaw` / 互引计数 / 箭头开关 | 0183 既有 5 例仍绿 |
| C12 布局稳定 | `DEFAULT_FORCE.repulsion` 180 → 220；`edgeLengthRange()` 把标量摊成 `[round(×0.6), round(×1.4)]`；`force` 增 `initLayout: 'circular'`、series 增 `layoutAnimation: true`；主 option 下发改 `setOption(option, false)` | 单测：`force.initLayout === 'circular'`、`force.edgeLength` 为 `[60, 140]`、`layoutAnimation === true`、含 `data` 的每次 `setOption` 第二参均为 `false` |
| C13 点阵网格 | `themeMix.ts:44` 新增 `'border-soft-40-transparent': {a:'var(--cn-border-soft)', aPct:40, b:'transparent', bPct:60}`；`DocumentGraphPage.css` 新增 `.cn-graph-canvas { background-color: var(--cn-bg-canvas); background-image: radial-gradient(var(--cn-mix-border-soft-40-transparent) 1px, transparent 1px); background-size: 16px 16px; }`；画布内联 `background` 移除 | 单测：画布 `style.background` 为空、`getAttribute('style')` 不含 `background`；`themeMix.test.ts` 权重合计与注册表扫描均通过 |
| C14 口径与门禁 | 只用 token / themeMix；断点仍 767.98 / 575.98px；echarts 仍独立 lazy chunk + SVG renderer；同轮补单测 + CHANGELOG + 本卡回填 | `make check-fast` 全绿；`make flow` 7840 passed / 17 skipped；前端全量 293 文件 / 3641 passed；`make check-frontend` 覆盖率双门槛达标（核心 lines 97.66% / branches 100%，全局 83.95%） |

**已知项**：`frontend/src/pages/documents/ContentTemplatePanel.test.tsx` 在并发 worker 下偶发「找不到 `content-template-duplicate` / `content-template-export-template`」（8 次跑红 4 次）；已在干净 HEAD 的临时 worktree 复现同样 50% 频率，属既有基线 flake（自动选中首个模板的 effect 与断言存在竞态），与本需求无关，未在本轮修。

另：`frontend/tests/e2e/critical/document-graph.spec.ts` 的「筛选栏「只看断链」」用例在本轮首次运行时红过一次（`graphLabels(page).filter({ hasText: sourceTitle })` 15s 内 not found，截图显示筛选后页脚计数正确、画布已重绘），随后单独复跑 4 次 + 整个 spec 复跑 4 次均全绿（共 8 连通过），判定为标签渲染时序脆弱的偶发问题而非 C3 行为变化：只留断链视图下源节点度数为 1（`degrees` 按全图折叠边算），不会命中 `isIsolated`，其 `label.show` 未被关掉。未放宽断言，留待 CI 全量 e2e 观察。

## 未决问题

- [x] H25 是否覆盖图形元素：不覆盖，UI 边界仍 1px（D6，用户 2026-11-27 确认）
- [x] 孤立点画布淡化是否违反 0182 C8：不违反，清单保留（D7，同上）
- [x] 是否接受彩色边：接受（D8，同上）
- [x] 互引边折叠放前端还是后端：已由需求 0183 定案并落地在前端渲染层，本卡不再实现（D10）
- [x] 度数是否改按无向边：随 0183 冻结为「唯一关联文档数」，本卡沿用不改（D4）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认后进入实现（S1 人工卡点，用户 2026-11-27「开始」）

## 不做

- 不引入新依赖（不加 d3 / cytoscape / pixi；echarts 已够）。
- 不做 3D 质感、不做节点缩略图 / 文档预览气泡。
- 不改节点上限口径（仍 `updated_at` 最近 500）、不改双链语法、不改后端 payload。
- 不改 0182 的筛选语义、Inspector 字段、局部图 BFS 与力参数滑轨范围。
- 不做节点拖拽后的位置持久化（`fixed` 回写留待后续需求）。
