# ADR 0056: 图表设计器派生单元格联动（双轴次值默认留空）

Status: Accepted
Date: 2026-10-28
Related: `src/cndb/plugins/documents/services/charts/registry.py`、`src/cndb/plugins/documents/services/charts/render.py`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、ADR 0048（图表模板）、ADR 0051（预览与显示比例）
需求卡片: `docs/requirements/0056-chart-derived-cell-linkage.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「数据第二列次值默认均留空」 | `registry.py` 双轴模板 `default_config.data.rows` 全部 `growth: null`，`version` 1→2 驱动 ETag 失效；已存量实例 config 不改写 |
| C2 | 「第二列第一行次值默认不能填入」 | 设计器第 1 行次值输入框禁用（antd `disabled` + Tooltip 说明）；后端 `validate_config` 对第 1 行 `growth is not None` 返回 400 |
| C3 | 「填入次值则对应主值随之变动」 | 设计器 `updateRowField('growth')` 触发联动：`主值ᵢ = 主值ᵢ₋₁ × (1 + 次值ᵢ/100)`（i≥2）；与渲染端 `growth_at` 留空推算公式互逆 |
| C4 | 「把主动修改的和受影响的值进行区分」 | 设计器编辑态记录「受影响单元格」集合，底色高亮 + antd Tooltip「由次值联动重算」/「由主值重算」；仅编辑期 state，不写入提交的 config；下一次手动编辑该单元格即清除其标记 |
| C5 | 「其他图表也参考此规则」 | 仅 `bar-line-dual-axis` 落地；堆叠 / 分组模板无派生列、行为不变；联动规则作为「派生单元格模式」供未来含派生列的模板复用 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 双轴模板默认数据 growth 带示例值（19.7 等），新建即非空 | `src/cndb/plugins/documents/services/charts/registry.py:130-142` | 新建实例次值全部预填，用户需逐行删除 | 确认（C1） |
| 2 | 后端校验允许任意行次值非空 | `src/cndb/plugins/documents/services/charts/registry.py:423-438` | 首行次值可保存，但渲染不画（见 #4） | 确认（C2） |
| 3 | 设计器次值列可自由编辑，主次值无联动 | `frontend/src/pages/documents/ChartDesignerModal.tsx:200-209`、`:530-536` | 填次值不改主值，两者可能矛盾 | 确认（C3/C4） |
| 4 | 渲染时次值留空按主值推算：`round((b/a−1)*1000)/10`，实际段与测算段口径一致；首行恒不画 | `src/cndb/plugins/documents/services/charts/render.py:166-175` | 推算公式是联动的设计基准；渲染端任意段留空均自动推算，保证次值留空不导致增长曲线缺段 | 确认（C3 公式互逆依据；P2 后修正渲染口径） |
| 5 | `{cagr}` 图注 token 只依赖主值复合增速 | `src/cndb/plugins/documents/services/charts/render.py:694-705` | 次值默认留空不影响 `{cagr}` | 确认（排除） |
| 6 | 既有测试对默认 growth 值无硬编码断言 | `tests/test_documents_charts_registry.py:91-133`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx:51` | C1 改动波及面小 | 确认（排除波及） |
| 7 | 模板 `version` 参与 ETag 指纹（D10） | `src/cndb/plugins/documents/services/charts/registry.py:75-76`、`:232-236` | 默认数据变更需递增 version | 新增 |
| 8 | 教程文档含次值说明文案 | `frontend/src/pages/help/content/tutorials.tsx` | 需同步「首行禁填、联动」说明 | 新增（C2/C3 文档） |

**核心缺陷（需求要补的）**：设计器把主值与次值当作两个独立字段，用户填写次值（增速）后主值不会随之变动，且默认预填示例次值，用户无法区分「自己填的」与「系统推算的」。

设计目标（不变量）：

- **I1 派生一致性**：设计器内任一行（i≥2）的 `主值ᵢ`、`次值ᵢ`、`主值ᵢ₋₁` 三者始终满足 `次值ᵢ ≈ (主值ᵢ/主值ᵢ₋₁ − 1) × 100`（一位小数），与渲染端留空推算公式互逆；不满足的场景（主值ᵢ₋₁ 为空 / ≤0）不联动。
- **I2 显式值优先**：用户主动填写的单元格是「显式值」，联动重算产生的值是「受影响值」且仅在编辑期可见；提交的 config 结构不变（label/value/growth/rows），不含任何标记。
- **I3 首行无派生**：第 1 行次值恒为空（前端禁填 + 后端 400），渲染端 i=0 不画折线点的既有行为不变。
- **I4 存量零迁移**：不改数据库、不改已有实例的 config；联动纯为设计器编辑期行为。

## Decision

### 1. 数据模型

无表变更、无迁移。`documents_chart.config` 的 `data.rows` 结构不变（`label` / `value` / `growth`）。变更点仅两处代码常量：

- `registry.py` 双轴模板 `default_config.data.rows`：11 行 `growth` 全部改为 `null`（C1）；
- 同模板 `version: 1 → 2`：默认数据变更驱动模板指纹与 ETag 失效（沿用 ADR 0048 D10）。

### 2. 判定算法（唯一入口）

联动计算唯一入口为设计器内纯函数（`frontend/src/pages/documents/chartLinkage.ts` 新建）：

```ts
// 填次值联动主值（C3）：主值ᵢ = 主值ᵢ₋₁ × (1 + 次值ᵢ/100)
linkValueFromGrowth(prevValue: number | null, growth: number): number | null | 'skip'
// 改主值反向重算次值（Q4）：次值ᵢ = round((主值ᵢ/主值ᵢ₋₁ − 1) × 1000) / 10（与 render.py growth_at 同一舍入口径）
linkGrowthFromValue(value: number, prevValue: number | null): number | null | 'skip'
```

判定顺序（`updateRowField` 内）：`主值ᵢ₋₁` 为 `null` 或 `≤ 0` → `'skip'`（不联动，仅写入本单元格）；否则按公式联动并登记受影响单元格。联动不级联：修改第 i 行只影响第 i 行的配对单元格，后续行的显式值保留（用户 Q4 结论为「该行次值自动重算」，未含跨行级联）。

后端唯一校验入口仍是 `registry.validate_config`：新增规则「第 1 行 growth 必须为 null」→ 错误文案「第 1 行次值不能填写（无上年基数）」。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /workspaces/{wid}/charts/templates` | 载荷随 `default_config`（growth 全 null）与 `version: 2` 自然变化，无结构变更 |
| `POST /workspaces/{wid}/charts`（及更新） | 校验新增首行次值禁填规则，违反返回 400 `chart_config_invalid` |
| `POST /workspaces/{wid}/charts/render-preview` | 不变（渲染端留空推算逻辑不动） |

### 4. 边界与例外

1. 首行（i=1）次值输入框 `disabled` + Tooltip「第 1 行无上年基数，次值不可填写」；后端校验兜底 400（C2，前后端双防线）。
2. `主值ᵢ₋₁` 为空、0 或负数时不联动，只写用户当前输入的单元格；次值留空的行在渲染时按主值自动推算（实际段与测算段口径一致），增长曲线不因留空缺段。
3. 联动重算按一位小数舍入（`round((x)×1000)/10`），保证设计器显示值与渲染端推算口径一致。
4. 用户先填次值（主值被联动）再手动改主值 → 次值被反向重算并标记「受影响」；该单元格再次被手动编辑时清除标记。
5. 编辑正文内嵌块（`editBlock`）与新建实例走同一联动逻辑；已存量实例打开设计器不强制重算、不改写已有值。
6. 插入图表弹窗（InsertChartModal）的模板缩略示例图随 default_config 变化，次值线在测算段自动推算仍可显示，无需额外处理。

### 5. 迁移

无。数据库零迁移；存量实例 config 不改写（I4）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 联动纯函数 | `frontend/src/pages/documents/chartLinkage.ts`（新建） | C3/Q4 联动公式与舍入口径，单测直测 |
| 设计器 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | `updateRowField` 接入联动；次值单元格首行禁用；受影响单元格底色高亮 + Tooltip（C2/C3/C4） |
| 教程文档 | `frontend/src/pages/help/content/tutorials.tsx` | 图表教程补「次值默认留空、首行禁填、填写联动主值」说明（C5 文档面） |

### 7. 测试清单

**判定层（单测）**：`tests/test_documents_charts_registry.py` — 默认配置 11 行 growth 全 null（C1）；模板指纹含 `bar-line-dual-axis@2`（C1/version）；`validate_config` 第 1 行 growth 非空报错、第 2 行起仍允许（C2）。

**接口层**：`tests/test_documents_charts_api.py`（既有图表接口测试文件）— 建实例带首行 growth 返回 400；正常默认配置建实例通过。

**迁移 / 备份**：无迁移，不适用。

**前端单测**：`chartLinkage.test.ts` — 联动公式、舍入、skip 分支；`ChartDesignerModal.test.tsx` — 首行次值框 disabled；填第 2 行次值 → 主值变化且带受影响标记；改主值 → 次值重算且带标记；手动再编辑清除标记；提交 payload 不含标记字段（C3/C4）。

**e2e（前端）**：插入双轴图表 → 设计器首行次值禁用、默认次值全空；填写次值后预览柱高变化（C1/C2/C3）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端：默认 growth 全空 + `version` 递增 + `validate_config` 首行禁填 + 单测 | 低 |
| **P1** | 前端：联动函数 + 设计器接入（禁填 / 联动 / 高亮标记）+ 前端单测 | 中 |
| **P2** | 教程文档同步 + e2e + `make flow` 全绿 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型：联动放前端设计器还是后端渲染 | 联动仅在设计器编辑期实现，渲染端不改 | 需求只要求编辑时「便于用户知晓」；渲染端已有留空推算，改它影响存量图 | 后端渲染联动（会改变存量实例渲染结果）；联动结果落库（违反 I2） | `frontend/src/pages/documents/chartLinkage.ts` |
| D2 | 派生公式口径 | 次值ᵢ为同比增速：主值ᵢ = 主值ᵢ₋₁ × (1 + 次值ᵢ/100)；反向次值ᵢ = round((主值ᵢ/主值ᵢ₋₁ − 1) × 1000)/10 | 与 `render.py` `growth_at` 留空推算公式互逆（需求方确认 Q1/Q4） | 主值ᵢ₊₁ = 主值ᵢ×(1+次值ᵢ/100)（与渲染推算同口径要求次值对应本行） | `chartLinkage.ts` |
| D3 | 联动是否跨行级联 | 不级联：修改第 i 行只联动第 i 行配对单元格 | 需求方 Q4 结论仅「该行次值自动重算」；级联会连锁改写大量显式值 | 全链级联重算（不可控、难归因） | `chartLinkage.ts` |
| D4 | 区分方式 | 受影响单元格底色高亮 + Tooltip「由次值联动重算 / 由主值重算」，仅编辑期，不落库 | 需求方确认 Q2 | 弹窗列受影响行（打断编辑流） | `ChartDesignerModal.tsx` |
| D5 | 适用范围 | 仅双轴模板落地；堆叠 / 分组不变 | 需求方确认 Q3；两模板无派生列 | 为堆叠图新增占比派生列（超出本次需求） | `registry.py` |
| D6 | 首行禁填实现 | 前端 disabled + 后端 `validate_config` 400 双防线 | 前端可绕过（API 直调），校验须在后端；渲染端 i=0 本就不画点 | 仅前端禁用（不安全） | `registry.py:validate_config`、`ChartDesignerModal.tsx` |
| D7 | 默认值变更的缓存失效 | 双轴模板 `version` 1→2，ETag 指纹随之失效 | ADR 0048 D10 指纹机制 | 不递增（模板缩略图与新建默认不刷新） | `registry.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：新建双轴图表开箱即见「主值驱动」模型，填增速即得主值，主次值永不矛盾；用户可分辨手动值与推算值；首行禁填杜绝无意义数据。
- **负向**：设计器编辑逻辑复杂度上升（联动 + 标记 state）；存量实例中已填次值与主值矛盾的数据不会被动修正（用户自行编辑时才联动）。
- **风险与缓解**：次值留空时渲染端按主值自动推算增长曲线（实际段与测算段口径一致），教程中说明口径避免误解。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板 schema / 默认值 | `registry.py` | 双轴默认 growth 全空、version 2 | ADR 0048 / 0056 |
| 渲染派生值推算 | `render.py` | 不变，留空推算仍是渲染职责 | ADR 0048 |
| 设计器编辑行为 | `ChartDesignerModal.tsx` | 新增派生单元格联动与标记 | ADR 0056 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/charts/registry.py` | `tests/test_documents_charts_registry.py` | a3adaae9 |
| P1 | 已落地 | `frontend/src/pages/documents/chartLinkage.ts`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/test/msw.ts` | `frontend/src/pages/documents/chartLinkage.test.ts`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx` | a3adaae9 |
| P2 | 已落地 | `frontend/src/pages/help/content/tutorials.tsx`、`src/cndb/plugins/documents/services/charts/render.py` | `frontend/tests/e2e/critical/chart-designer-linkage.spec.ts`、`tests/test_documents_charts_render.py` | a3adaae9 + 修复提交 |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（待人工评审回填 Implemented）
- 已完成：P0（默认 growth 全空 + version 2 + 首行禁填校验）、P1（chartLinkage 联动 + 设计器禁填 / 联动 / 高亮标记）、P2（教程说明 + e2e spec + CHANGELOG）
- 下一步：`make flow` 全绿后提交；e2e 按环境可用性跑 critical 分片；人工评审后 Status → Implemented
- 已知坑：e2e 本地环境缺系统库（libatk-1.0.so.0）暂无法启动 chromium，spec 已就位待环境修复后执行；渲染端实际段次值留空不画点为既有行为；JS `Math.round` 与 Python `round` 半值边界舍入差异属可接受显示口径
- 最近一次全绿：`make flow` @ a3adaae9（5847 passed）
