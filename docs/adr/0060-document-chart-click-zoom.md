# ADR 0060: 文档图表点击放大查看

Status: Accepted（已评审）
Date: 2026-10-28
Related: `frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/DocumentImage.tsx`、ADR 0052（图表内嵌块）、ADR 0051（图表预览与宽度）
需求卡片: `docs/requirements/0060-chart-click-zoom.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 在查看模式下 | ChartEmbed 渲染成功（`chart-embed-svg` 存在）时，SVG 容器变为可点击：点击打开放大预览弹层；渲染失败 / 加载中 / 无效块无放大入口 |
| C2 | 像图一样可以点击放大查看 | 预览层为 antd `Modal` 遮罩弹层（默认宽 75vw，SVG 按原比例自适应、居中），内容直接渲染同一份已 sanitize 的 SVG 字符串（`dangerouslySetInnerHTML` 复用，零额外请求、矢量清晰）；标题栏提供 −/＋ 缩放按钮与当前百分比（0.5x-3x，步进 10%，到边界按钮禁用，打开时复位 100%）；滚轮仅用于弹层内上下滚动，不缩放 |
| C3 | 插入图表 | 编辑 / 宽度 / 保存图片控件仍在 `<figure>` 内的按钮区，放大点击只挂在 SVG 容器上，互不遮挡；编辑模式行为不变 |
| C4 | （推论）游客分享页一致 | ChartEmbed 组件内实现，`shareToken` 模式自动获得同样放大能力，无单独改动 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 文档图片用 antd `Image` 自带 preview（mask「预览」），点击放大 | `frontend/src/components/Document/DocumentImage.tsx:37-45,62-72` | 图片已有放大，体验基准 | 确认 |
| 2 | 图表内嵌块 SVG 容器为纯 `div`（`dangerouslySetInnerHTML`），无任何点击交互 | `frontend/src/components/Document/ChartEmbed.tsx:95-101` | 图表只能按块宽度（缺省 75%）查看，小字看不清 | 确认 |
| 3 | ChartEmbed 以 `shareToken` 区分成员 / 游客模式，渲染路径共用同一组件 | `frontend/src/components/Document/ChartEmbed.tsx:55,69-80` | 一处改动两端生效 | 确认 |
| 4 | 已有 `sanitizeSvg` 清洗（去 `<script>` 与行内事件属性） | `frontend/src/components/Document/ChartEmbed.tsx:21-26` | 复用同一字符串到预览层无新增安全面 | 确认 |

**核心缺陷（需求要补的）**：图表块只有内联固定宽度视图，没有像图片一样的放大查看入口，宽表格 / 密集标注类 SVG 在正文宽度下不可读。

设计目标（不变量）：

- **I1 单一数据源**：预览层只复用同一次渲染返回并已 sanitize 的 SVG 字符串，不发第二次渲染请求、不做位图转换。
- **I2 降级一致**：仅当 `chart-embed-svg` 实际渲染成功时提供放大入口；无效块 / 加载中 / 渲染失败态不出现点击交互。
- **I3 模式无关**：成员与游客（shareToken）两种模式共享同一放大实现与交互。

## Decision

### 1. 数据模型

无（纯前端交互改动）。

### 2. 判定算法（唯一入口）

无（无判定逻辑变更）。

### 3. API 变更清单

无。

### 4. 边界与例外

1. 渲染失败 / 无效块 / 加载中：无放大入口（I2）。
2. SVG 本身带 `overflowX: auto` 横向滚动（`ChartEmbed.tsx:98`）：放大层内禁用横向滚动、按视口宽度整体展示（预览语义是「看全貌」，与内联的「可平移」区分）。
3. 点击目标：仅 SVG 容器；按钮区（编辑 / 宽度 / 保存图片）不触发预览。
4. 预览层内点击遮罩或关闭按钮即关闭；Esc 关闭由 Modal 默认行为提供。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 图表内嵌块 | `frontend/src/components/Document/ChartEmbed.tsx` | 新增 `previewOpen` state；SVG 容器加 `role="button"`、`cursor: zoom-in` 与点击回调；新增 antd `Modal`（footer=null，标题为图表名）渲染同一 SVG；`data-testid="chart-embed-zoom"` / `chart-embed-preview` |
| 样式 | `frontend/src/index.css`（如需） | 预览层 SVG 宽度 / 背景样式 |
| 测试 | `frontend/src/components/Document/ChartEmbed.test.tsx` | 新增放大交互用例 |

### 7. 测试清单

**判定层（单测）**：无（无判定逻辑）。

**接口层**：无（无 API 变更）。

**迁移 / 备份**：无。

**e2e（前端 / 单测）**：

- 渲染成功：点击 `chart-embed-svg` 出现预览弹层（`chart-embed-preview`），内容含同一 SVG。
- 渲染失败 / 无效块：无放大入口，点击无响应。
- 编辑模式下宽度 / 编辑 / 保存图片控件不受影响（C3 回归）。
- 关闭预览后回到原视图（Modal onClose）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | ChartEmbed 放大预览（交互 + 弹层 + 失败态无入口），单测 | 低 |
| **P1** | e2e 用例 + 教程 / 帮助文档提及（如有图表章节） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 放大实现方式 | antd `Modal` + 复用 sanitize 后的 SVG 字符串（`dangerouslySetInnerHTML`） | I1 零额外请求、矢量清晰、两模式共用 | antd `Image` preview（需 img src，要走 data URL 转换且语义错位）；echarts/位图转换（引入导出复杂度） | `frontend/src/components/Document/ChartEmbed.tsx` |
| D2 | 放大入口范围 | 仅 `chart-embed-svg` 渲染成功态可点，失败 / 加载 / 无效块无入口 | I2 降级一致 | 全 figure 可点（会与按钮区冲突） | 同上 |
| D3 | 游客分享页覆盖 | 组件内实现自动覆盖 `shareToken` 模式，无单独代码 | I3、卡片 C4 | 分享页单独实现（重复代码） | 同上 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：查看模式与游客分享页图表可读性对齐图片体验；实现集中单组件，回归面小。
- **负向**：ChartEmbed 增加弹层 state、缩放 state 与 Modal 渲染；缩放仅按钮步进（0.5x-3x），无捏合手势与滚轮缩放（滚轮保留给弹层滚动，避免手势冲突）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 图表内嵌块渲染 | ChartEmbed 组件 | 后端唯一渲染器 SVG + 单块降级 | ADR 0052 |
| 块宽度 | refWidth 字段 | 内联宽度 25-100%，放大层不受其约束 | ADR 0051 / 本 ADR D1 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/index.css` | `frontend/src/components/Document/ChartEmbed.test.tsx` | 40b7233f |
| P1 | 已落地 | `frontend/tests/e2e/critical/document-chart-embed.spec.ts`、`frontend/src/pages/help/content/tutorials.tsx` | `frontend/tests/e2e/critical/document-chart-embed.spec.ts` | 40b7233f |

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地（待人工评审回填 Status）
- 已完成：P0（放大交互 + 预览弹层 + 失败态无入口 + 单测 13/13）；P1（e2e 成员 4.2 段与游客段、教程文档提及）
- 下一步：人工评审 → Status 改 Implemented；推送后由 CI 补跑 e2e（见已知坑）
- 已知坑：本机缺 chromium 系统依赖（libatk-1.0.so.0），e2e 无法本地启动，由 CI 兜底；jsdom 不跑 Modal 离场动画，关闭断言用「不可见」而非「卸载」
- 最近一次全绿：`make check-fast` + `make test`（后端 5856 passed）@ 3795aeed 之后的工作区（2026-10-28）
