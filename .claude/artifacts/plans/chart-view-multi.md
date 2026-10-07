# chart-view-multi 实现计划

> Status: APPROVED
> Source: user request（图表视图支持添加多个图表，只显示一个图表空间浪费太多）
> Mode: (default)
> Iterations: 2 / 3
> Author: user
> Last updated: 2026-10-07

## Requirements summary

图表视图（view_type = "chart"）当前一个视图只能渲染单个图表，屏宽利用率低。本计划让一个 chart 视图可配置多个图表并**同屏网格展示**（dashboard 式），同时保持既有单图配置（扁平 view_options 契约，含 seed 的 34 个视图）完全向后兼容、零迁移。

## Acceptance criteria

- AC-1：同一 chart 视图可配置 ≥ 2 个图表，同屏以自适应网格展示（多图）；单图视图保持现有全宽布局不变。
- AC-2：既有扁平 view_options（seed 34 个 chart 视图 + 用户既有数据）渲染行为不变，无任何数据迁移。
- AC-3：ViewConfigDialog 图表专属设置支持添加 / 删除 / 切换图表条目，每个条目复用现有 11 项 CHART_OPTIONS 且 visibleWhen 按该条目 chart_type 条件显隐；至少保留 1 个图表（禁删最后一项）。
- AC-4：后端创建 / 导入视图校验 `charts[]` 内每个条目的字段引用（dimension_field/measure_field/x_field/y_field/group_field），不存在时 400 且 detail 定位到 `charts[i].<key>`。
- AC-5：多图模式下每个图表卡片独立拥有：ECharts 实例、描述统计面板（按该图度量字段）、散点点击打开行详情。
- AC-6：每轮实现完成 / commit 前 `make check` 本地全绿（含 bundle budget）。

## RALPLAN-DR

### Principles

- 最小代码：复用现有 CHART_OPTIONS schema / visibleWhen / resolveOpts / ViewOptionItem 机制，从 ChartView 抽出 ChartCard 而非重写。
- 向后兼容：扁平 view_options 仍为合法形态；单图编辑保存后仍是扁平形态。
- 跟随 matrix/gantt 模式：纯前端聚合，不新增后端端点，只扩 view_options 校验白名单。
- 外科手术式：创建路径（CreateEditViewForm）保持扁平键不变（= 图表 1）；多图管理收敛在 ViewConfigDialog。

### Decision drivers

- 向后兼容（seed 34 视图 + 既有用户数据不可破坏）。
- 复用既有 schema 机制，压缩表单开发成本。
- ECharts 多实例（SVG 轻量）vs 单实例多 grid 的装配复杂度。

### Viable options

**Option A（chosen）：`view_options.charts[]` 数组 + 多 ECharts 实例网格**
- 实现思路：view_options 新增可选 `charts` 数组，每元素为现有扁平配置对象（同 CHART_OPTIONS 键集）；渲染端 charts 非空数组走多图 CSS grid，否则按扁平键回退单图。ChartView 抽出 ChartCard 子组件；ViewConfigDialog 图表设置顶部加图表切换器（Segmented + 添加/删除）。
- Pros：全兼容零迁移；每图配置/表单/统计面板完整复用既有机制；实例间独立 resize 与点击语义简单。
- Cons：N 个 echarts 实例（SVG 渲染，轻量，可控上限）；ViewConfigDialog 草稿状态从单层 dict 变 dict+array 混合（用确定性双向转换函数约束）。

**Option B（rejected）：单 ECharts 实例 + 多 grid/xAxis/yAxis 装配**
- Invalidation rationale：6 种图表类型（pie 无轴 / scatter 双数值轴 / boxplot 特殊系列）合并进单 option 的 grid 索引装配复杂度远超收益；散点点击行详情的 dataIndex 映射从全局变 series 域内，clickCtxRef 机制需重设计；统计面板本就是 DOM 无法共享实例。收益仅省 N-1 个轻量 SVG 实例。

**Option C（rejected）：新增 dashboard 视图类型引用多个 chart 视图**
- Invalidation rationale：显著超出诉求（新 view_type + 视图引用关系 + 拖拽布局），用户只要"一个图表视图放多个图"。

## Implementation steps

1. **ChartView 抽出 ChartCard** — `frontend/src/pages/grid/views/ChartView.tsx:376-488`
   - 将主组件体内 missing/data/option/stats/scatterSummary 计算 + 两个 effect（init/dispose L414-432、setOption L435-438）+ 空态分支（L458-473）+ 渲染（L475-488）整体移入 `ChartCard({ cfg, rows, fields, total, onRowClick })`；clickCtxRef/onRowClickRef 随迁。
   - 新增 `resolveChartList(viewOptions): ChartConfig[]`（本文件内，单调用方）：`charts` 为非空对象数组时逐条经 `resolveOpts(entry, CHART_OPTIONS)` 解析；否则返回 `[resolveOpts(flat, CHART_OPTIONS)]`（现有路径，等价现状）。
   - 主组件：`rows.length === 0` 时空态保留在视图级（L467-473 语义上移）；单图（列表长度 1 且来源扁平）保持现有 flex 全宽容器；多图渲染 `display:grid; gridTemplateColumns:repeat(auto-fill, minmax(420px, 1fr)); gap:12px`，每格一张 ChartCard。
   - 卡片头自动标注（纯展示，非用户可配 title）：`{类型中文} · {关键字段名}`，字段缺失的卡片显示对应空态（chart-empty-config 语义下沉到卡片，data-testid 加索引后缀 `chart-empty-config-{i}` 供测试定位）。
2. **ViewConfigDialog 图表条目管理** — `frontend/src/pages/grid/view-config/ViewConfigDialog.tsx:131,179,361-411,424-437`
   - 新增纯函数 `normalizeChartList(draftOpt)` / `serializeChartList(chartList)`（放 viewOptionSchema.ts 导出，供测试）：前者把扁平键或 charts[] 归一为内部列表（扁平键 → 单条目，charts[] 原样）；后者按"图表数 >1 写 `charts[]`、==1 写扁平键"输出，并对条目做 cleanOpt 同款空值清洗（''/null 剔除，数组空长度剔除）。
   - 新增 `activeChartIdx` state；viewType === 'chart' 时「视图专属设置」tab 顶部渲染 Segmented（`图表 1 / 图表 2 / …`）+ 「添加图表」按钮（上限 6，达到后禁用并 tooltip 提示）+ 「删除当前图表」（仅多图时可用）。
   - 分区渲染复用 `groupOptionSchema(CHART_OPTIONS, activeChartOpts)`（L179 既有 visibleWhen 机制，第二参传当前条目 resolveOpts 后的 opts）；`ViewOptionItem` 的 `onSet`/`onPatch`（L387-399）改为 patch `charts[activeChartIdx]`（不可变展开）。
   - 保存按钮（L424-437）：`serializeChartList` 产物合入 cleanOpt 后交 `onSaveOptions`。
   - 折叠重置 effect（L186-193）依赖分区标签 join，不动；activeChartIdx 切换不触发该 effect（标签集合不变）。
3. **后端校验白名单扩嵌套** — `src/cndb/plugins/tables/routers/views.py:30-55`
   - `_validate_view_fields` 扁平键循环后追加：`vo.get("charts")` 为 list 时逐条校验——元素非 dict 返回 400（`view_options.charts[{i}] 不是对象`）；dict 内 `dimension_field/measure_field/x_field/y_field/group_field` 五键存在且值不在 valid_fields 时返回 400，detail 格式 `view_options.charts[{i}].{key}='{val}' 不存在`。
4. **seed 校验同步** — `src/cndb/cli/seed.py:1618-1646`
   - `_validate_view` 同步上述嵌套校验（打印跳过信息含 charts[{i}] 定位）；既有 34 个扁平 chart 视图 views.json **不改动**。
5. **测试**
   - `frontend/src/pages/grid/views/ChartView.test.tsx`：新增多图用例——charts 两元素渲染 2 个 chart-container、卡片头标注、每卡独立统计面板字段、单图扁平回退（既有 16 条全部不动应继续通过）、多图模式下某卡必填缺失显示对应空态。
   - `frontend/src/pages/grid/view-config/ViewConfigDialog.test.tsx`（或 CreateEditViewForm.test.tsx 旁新增）：添加图表 → Segmented 增项；切换条目后字段下拉按该条 chart_type 显隐；删除条目；禁删最后一项；保存时 serializeChartList 的扁平/charts[] 双形态输出断言。
   - `src/cndb` 后端测试（对齐 `test_views_api.py` 既有 chart 用例风格）：chart 视图带合法 charts[] 创建 201；`charts[1].measure_field` 引用不存在字段 400；charts 元素为非 dict 400。
   - `viewOptionSchema.test.ts`：normalizeChartList / serializeChartList 往返与空值清洗用例。
6. **文档与设计同步** — 实现完成后更新 `.trae/designs/chart-view.md`（view_options 契约表加 `charts` 行、渲染节加多图布局与单图回退规则、测试约定节补充），并在 `.trae/req/` 新增本需求条目（req-NN 图表视图多图）。
7. **验证** — 见 Verification steps；bundle budget 如超限按既有惯例更新 ChartView chunk 基线并在总结注明。

## Workspace setup

- 实施前运行 `git status --short` 和 `git branch --show-current`。
- 若 working tree 干净且当前分支为 main/master/release/*，默认推荐 worktree：`git worktree add -b codex/chart-view-multi ../cndb-chart-multi`。
- 若 working tree dirty（多会话并行写回风险已知），先与用户确认现有改动归属，不得把本计划改动混入；`git stash` 后必须 `git status` 复核。
- 实施期间每步编辑后 `git diff --stat` 核对落盘（Edit/Write 显示污染教训）。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| N 个 ECharts 实例内存/性能 | SVG 实例轻量；对话框添加上限 6；实例随卡片卸载 dispose（ChartCard cleanup 沿用 L427-431） |
| ViewConfigDialog visibleWhen/折叠态回归（历史 bug：防抖 refetch 重建引用后 effect 重跑） | 折叠 effect 依赖分区标签 join 机制已有，不改依赖；图表切换仅换 bind 目标不重置折叠；ViewConfigDialog 测试覆盖"切换条目不重置分区折叠" |
| cleanOpt 空值清洗漏掉嵌套 charts | serializeChartList 内做条目级清洗并被单测锁定（空串/null/空数组剔除） |
| 扁平/charts[] 双形态长期共存造成隐性漂移 | 双向转换纯函数 + 往返测试锚定；保存规则确定（>1 → charts[]，==1 → 扁平） |
| bundle budget 超限 | ChartView 为懒加载 chunk，增量仅布局代码；超限则更新基线并注明 |
| 多会话并行写工作区 | Workspace setup 节流程；每步 git diff 核对 |

## Verification steps

- AC-1/AC-2/AC-5：`cd frontend && pnpm test -- ChartView`（既有 16 条 + 新增多图用例全绿；断言单图仍走全宽容器、多图为 grid）。
- AC-3：`pnpm test -- ViewConfigDialog`（添加/切换/删除/禁删最后/双形态保存断言）。
- AC-4：`cd F:\Dev\cndb && uv run pytest tests/test_views_api.py -k chart`（201/400 用例）。
- AC-6：`make check` 全绿（lint/typecheck/cov/bundle budget）；收尾注明"已本地通过 make check"。
- 手工冒烟（可选）：`make e2e` 前先 `make frontend-build`（e2e-server 服务构建产物，旧产物会掩盖新功能）。

## Open questions

- 单图上限 6 与网格最小列宽 420px 为默认拍定值，用户可后续调整（设计文件标注"待用户复核"）。
- seed 示例 views.json 是否挑选若干表升级为多图形态（如电商销售把 5 个单图视图合并）——本次不做，进 follow-ups。

## ADR

- **Decision**：采用 Option A——view_options 新增可选 `charts[]`（每元素 = 现有扁平配置键集），多 ECharts 实例自适应网格同屏渲染；扁平键保留为合法单图形态，双向确定性转换。
- **Drivers**：向后兼容（决定性）；复用既有 schema 机制；多实例 SVG 成本可忽略。
- **Alternatives considered**：Option B（单实例多 grid）rejected——装配复杂度与点击语义重设计成本远超收益；Option C（dashboard 视图类型）rejected——显著超出诉求。
- **Why chosen**：以最小代码同时满足"多图同屏"与"零迁移"；表单、统计面板、散点点击全链路复用既有实现，仅新增布局壳与条目管理 UI。
- **Consequences**：view_options 出现双形态（扁平/charts[]），渲染端与两处后端校验必须同时支持——已由转换纯函数 + 测试锁定；ViewConfigDialog 复杂度上升（index 状态 + patch 嵌套）。
- **Follow-ups**：seed 示例升级多图形态；多图布局列数/卡片标题自定义（用户提出再做）。

## Review trail

- Planner draft v1：Option A favored，B/C 附 invalidation rationale；步骤 cite ChartView/ViewConfigDialog/views.py/seed.py。
- Architect challenge v1：steelman 指出嵌套草稿 + cleanOpt 失效 + 双形态漂移风险；synthesis 为确定性双向转换规则。
- Critic verdict v1：REVISE——①单图布局分支未定义；②删光图表空态未定义；③title 属未请求功能。
- Planner draft v2：单图保留全宽 flex 分支；对话框禁删最后一个图表；裁掉自定义 title（卡片头自动标注）。
- Critic verdict v2：APPROVED，reservations——上限 6/420px 为拍定值（已进 Open questions）；serializeChartList 清洗规则必须测试锁定（已进 Risks/步骤 5）。
- Final iterations: 2 / 3
