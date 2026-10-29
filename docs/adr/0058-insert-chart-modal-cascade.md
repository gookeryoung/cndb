# ADR 0058: 插入图表对话框多级列表改造与双轴模板更名

Status: Accepted
Date: 2026-10-28
Related: `src/cndb/plugins/documents/services/charts/registry.py`、`frontend/src/pages/documents/InsertChartModal.tsx`、`frontend/src/api/charts.ts`、ADR 0048（图表模板）、ADR 0056（次值联动）
需求卡片: `docs/requirements/0058-insert-chart-modal-cascade.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「改名为【双轴柱线组合图】」 | `registry.py` 双轴模板 `name` 更名、`version` 2→3；msw fixture / 测试 / 教程全仓同步，旧名零残留 |
| C2 | 「左侧为列表」多级设计 | `InsertChartModal` 新建页签重构为左右布局：左栏 antd Collapse 手风琴（一级分类常显、点开展开二级分类与模板项），右栏为选中模板详情 |
| C3 | 「预览仅选中后才看得到」 | 未选中时右栏空态（Empty），不发 `render-preview`；选中后按需渲染单张 `TemplateThumb`（现全量卡片缩略图机制移除） |
| C4 | 「纳入对比-柱形、对比-条形」 | `ChartCategory` 加 `parent: str | None`；新增二级 `comparison-bar`（对比-柱形）、`comparison-bar-h`（对比-条形），双轴图归 `comparison-bar`，堆叠 / 分组条形归 `comparison-bar-h`；删除「趋势分析」一级；`GET /charts/templates` 载荷层级化 |
| C5 | 「其余模板归位」 | 堆叠 / 分组之外的模板保留 `composition`；无模板的一级分类不输出 |

决策结论只在「决策记录」写一次。

## Context

现状逐条核对（沿用卡片影响面编号）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 双轴模板名「柱线组合图（双轴）」，version 2 | `src/cndb/plugins/documents/services/charts/registry.py:91`、`:142` | 更名需 version 递增驱动 ETag | 确认（C1） |
| 2 | `CHART_CATEGORIES` 扁平 3 个一级，无 parent | `registry.py:50`、`:79-82` | 无法表达两级目录 | 确认（C4 核心缺陷） |
| 3 | 双轴归 trend，堆叠 / 分组条形归 comparison | `registry.py:90`、`:149`、`:179` | 三模板需迁入 comparison 二级 | 确认（C4） |
| 4 | 新建页签全量卡片网格，每卡渲染缩略图（N 次 render-preview） | `frontend/src/pages/documents/InsertChartModal.tsx:123-165` | UI 冗余，需按需单张预览 | 确认（C2/C3） |
| 5 | `categories` 扁平载荷消费方仅 `InsertChartModal.tsx:93` | `frontend/src/api/charts.ts:47` | 载荷加层级不波及其他页面（chartBoard 的 categories 为无关同名概念） | 确认（排除） |
| 6 | 旧名引用 9 处（msw / 5 个前端测试 / 教程） | `frontend/src/test/msw.ts:227`、`ChartDesignerModal.test.tsx`、`InsertChartModal.test.tsx:32`、`DocumentEditorPage.test.tsx:1636`、`tutorials.tsx:584` | C1 全量同步 | 确认（C1 波及） |
| 7 | 素材库页签独立列表（左清单右详情已有雏形） | `InsertChartModal.tsx:170-210` | 本次不动（Q3） | 确认（排除） |

**核心缺陷**：类别模型是扁平一级，无法表达「对比-柱形 / 对比-条形」两级目录；弹窗一次性渲染全部模板缩略图，不紧凑。

不变量：

- **I1 载荷向后兼容**：`categories` 条目保留 `key/name/description`，新增可选 `parent`；一级条目含 `children` 二级数组；未带 parent 感知的旧消费方按一级渲染不崩。
- **I2 模板 key 稳定**：`bar-line-dual-axis` 等 key 不变，存量实例 / 内嵌块 / ETag 不受影响（更名只改展示名 + version）。
- **I3 按需预览**：右栏预览仅在选中态发 1 次 render-preview 请求；切换选中重新请求（沿用 `['chart-template-thumb', wid, key]` 缓存）。
- **I4 存量零迁移**：纯代码与载荷变更，无数据库迁移。

## Decision

### 1. 数据模型

`ChartCategory` 增加字段 `parent: str | None = None`。类别定义变为：

```python
CHART_CATEGORIES = (
    ChartCategory("composition", "结构构成", "..."),
    ChartCategory("comparison", "目标对比", "..."),
    ChartCategory("comparison-bar", "对比-柱形", "...", parent="comparison"),
    ChartCategory("comparison-bar-h", "对比-条形", "...", parent="comparison"),
)
```

「趋势分析」删除。模板 `category` 赋值：双轴 → `comparison-bar`；`stacked-bar-horizontal` / `grouped-bar-horizontal` → `comparison-bar-h`；其余不变（composition）。

### 2. 判定入口（载荷组装）

`registry.list_templates()`（`registry.py:477` 附近）改为输出两级：一级条目含 `children: [二级...]`；模板仍为扁平 `templates` 数组（`category` 指二级 key），前端按二级分组渲染。一级 `parent=None` 且自身无模板、二级也无模板的一级不输出。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /workspaces/{wid}/charts/templates` | `categories[]` 条目新增 `parent` 与 `children[]`；模板名随 C1 更新；无结构破坏性变更（I1） |
| `POST /charts/render-preview` | 不变 |

### 4. 边界与例外

1. 手风琴默认展开第一个含模板的一级分类，但不自动选中模板（右栏初始为空态，满足 C3）。
2. 一级分类头部仅作展开控件，不承载「选中分类」语义；选中态只落在模板项上。
3. 右栏详情 = 大图预览（TemplateThumb 复用，尺寸放大）+ 描述 + 「基于此模板新建」按钮。
4. `GET /charts/templates` 的二级 key（`comparison-bar` 等）不参与存储校验之外的任何业务判定；前端仅用于分组。

### 5. 迁移

无（I4）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/charts.ts` | `ChartCategoryInfo` 加 `parent?: string | null`、`children?: ChartCategoryInfo[]` |
| 插入弹窗 | `frontend/src/pages/documents/InsertChartModal.tsx` | 新建页签重构：左 Collapse 手风琴 + 右详情；移除全量卡片网格 |
| 教程 | `frontend/src/pages/help/content/tutorials.tsx` | 旧名更名同步 |
| msw | `frontend/src/test/msw.ts` | fixture：名称、categories 层级 |

### 7. 测试清单

**判定层**：`tests/test_documents_charts_registry.py` — 模板名断言、`version==3`、新 category 归属、载荷 children 结构、无空一级分类。

**前端单测**：`InsertChartModal.test.tsx` — 未选中无 thumb 请求（C3）、手风琴展开选中后右栏出现预览与按钮（C2）、新分类目录渲染（C4）；`ChartDesignerModal.test.tsx` / `DocumentEditorPage.test.tsx` 旧名断言同步（C1）。

**e2e**：`frontend/tests/e2e/critical/` 现有图表 spec 中模板选择路径若引用旧文案则同步；本 ADR 不新增 e2e（交互已由前端单测覆盖，环境缺系统库暂不可跑）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端：parent 字段、二级分类、三模板迁类、更名 + version 3、载荷层级化、registry 单测 | 低 |
| **P1** | 前端：类型、InsertChartModal 重构、msw、前端单测 | 中 |
| **P2** | 教程 / 全仓旧名清理 + `make flow` 全绿 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体选型：后端层级化 vs 前端硬编码目录 | 后端 `parent` 字段层级化，载荷输出 children | 目录属于模板域数据，前端硬编码会在新增模板时漂移 | 前端写死目录映射（与新模板接入冲突） | `registry.py:ChartCategory` |
| D2 | 模板 `category` 指向 | 直接指二级 key | 一级仅作分组容器，模板必属二级 | 模板指一级+二级标签冗余 | `registry.py` 各模板 |
| D3 | 「趋势分析」分类 | 删除 | 双轴迁出后为空；需求方 Q1 确认 | 保留空分类（违背 I4 无空组） | `registry.py:CHART_CATEGORIES` |
| D4 | 预览渲染策略 | 仅选中后单张按需渲染 | 需求方 C3；N→1 请求 | 保留全量缩略图（UI 不紧凑） | `InsertChartModal.tsx` |
| D5 | 左栏交互 | antd Collapse 手风琴，一级常显、点开展开二级 | 需求方 Q4 | 全展开树（分类多时左栏过长） | `InsertChartModal.tsx` |
| D6 | 素材库页签 | 不动 | 需求方 Q3 | 同步改造（扩大改动面） | — |
| D7 | 更名的缓存失效 | `version` 2→3 | ADR 0048 D10 指纹机制 | 不递增（缩略与 ETag 不刷新） | `registry.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：目录两级化可容纳后续模板增长；弹窗请求从 N 张缩略图降为按需 1 张，UI 紧凑。
- **负向**：新建图表多一步「展开分类 → 选模板 → 看预览」；消费扁平 categories 的外部集成需感知 `parent/children`（I1 保证旧方不崩）。
- **风险与缓解**：模板更名影响既有文案引用，P2 全仓 `grep 柱线组合图（双轴）` 清零兜底。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板 schema / 默认值 | `registry.py` | 更名 + 分类层级 + version 3 | ADR 0048 / 0056 / 0058 |
| 设计器行为 | `ChartDesignerModal.tsx` | 不变（0056 联动保留） | ADR 0056 |
| 插入弹窗布局 | `InsertChartModal.tsx` | 新建页签多级列表 + 按需预览 | ADR 0058 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/charts/registry.py`（parent 字段、二级分类、三模板迁类、更名 + version 3、载荷层级化） | `tests/test_documents_charts_registry.py`、`tests/test_documents_charts_api.py` | 816d77aa |
| P1 | 已落地 | `frontend/src/pages/documents/InsertChartModal.tsx`、`frontend/src/api/charts.ts`、`frontend/src/test/msw.ts` | `frontend/src/pages/documents/InsertChartModal.test.tsx` | 816d77aa |
| P2 | 已落地 | `frontend/src/pages/help/content/tutorials.tsx`、`frontend/tests/e2e/critical/document-chart-embed.spec.ts`、`frontend/tests/e2e/critical/chart-designer-linkage.spec.ts`（全仓旧名 grep 清零） | `frontend/src/pages/documents/ChartDesignerModal.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 816d77aa |

## 交接（会话结束更新）

- 当前阶段：P0–P2 全部落地，`make flow` 全绿（后端 5854 passed）
- 已完成：
  - 后端：`ChartCategory.parent`、二级 `comparison-bar` / `comparison-bar-h`、双轴更名 + version 3、`templates_payload()` 层级化（空分类不输出——composition 无模板不再输出，见 C5）
  - 前端：`InsertChartModal` 新建页签左 Collapse 手风琴 + 右按需单张预览；`ChartCategoryInfo` 加 `parent?/children?`；msw fixture 同步
  - 旧名清零：教程、4 个前端测试文件、2 个 e2e spec（先 `chart-template-item-*` 选中再点 pick）
- 下一步：无（需求整体完成）
- 已知坑：
  - e2e 环境缺 libatk-1.0.so.0 不可本地运行；以 `make flow`（含前端全量单测）+ e2e spec 路径同步作为等价验证
  - ADR 0057 相关 e2e / 卡片改动为其他会话未提交工作，未纳入本次提交
- 最近一次全绿：`make flow`（5854 passed, 3 skipped）
