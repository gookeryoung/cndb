# ADR 0059: 图表设计器联动单元格「(计算)」显示与默认联动态

Status: Accepted
Date: 2026-10-28
Related: `frontend/src/pages/documents/chartLinkage.ts`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、ADR 0056（派生单元格联动）、ADR 0048（图表模板）
需求卡片: `docs/requirements/0059-chart-linkage-display.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「联动项风格按当前形式，数值后增加(计算)表示联动值」 | 设计器联动态单元格非编辑态渲染为可点击的展示态：沿用底色高亮（`#FDF2E4`），数值后追加「(计算)」后缀（如 `12.3(计算)`），并带 `data-linked` 标记 |
| C2 | 「默认次值直接显示为联动状态」 | 双轴设计器打开时，次值列（i≥1）凡 `growth === null` 且按主值可推算（基数存在且 >0）即处于联动态，显示推算增速值 +「(计算)」；推算复用 `chartLinkage.linkGrowthFromValue`（与渲染端同口径，一位小数）；存储仍为 `null` |
| C3 | 「点击联动项单元格后，进入编辑状态，仅显示数值不显示(计算)」 | 点击联动态单元格切换为真实 `InputNumber` 编辑态，初始值为推算数值（纯数字，无后缀），可直接修改 |
| C4 | 「对应主/次值单元格变为联动状态」 | 失焦 / 回车提交：数值有改动 → 走既有 `updateRowField` 联动（公式与舍入口径沿用 ADR 0056 D2/D3：互逆、不跨行级联、基数缺失不联动），配对单元格被重算进入联动态；清空次值 → 删除显式值，恢复按主值推算的联动态显示；数值未改动 → 保持联动态（Q1，存储不变） |
| C5 | 「完善该设计」 | 提交的 config 结构不变（`label`/`value`/`growth`），无任何联动标记字段；次值未被显式编辑仍存 `null`，渲染端留空推算行为不变 |
| C6 | 「一并完善其他类图表」 | 联动态显示机制实现为双轴数据表分支内的通用渲染模式（展示态 / 编辑态切换不绑定具体字段）；堆叠 / 分组模板无数值派生关系，行为不变（Q2，沿用 ADR 0056 D5 否决结论） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 联动公式唯一入口 `chartLinkage.ts` 已有互逆两函数（含一位小数舍入口径） | `frontend/src/pages/documents/chartLinkage.ts:21-29` | 默认联动态的显示值可直接复用 `linkGrowthFromValue`，无需新公式 | 确认（C2 复用） |
| 2 | 联动标记用 `affected` 集合（仅登记本轮联动重算的单元格），默认留空次值不在集合内、显示为空白 | `frontend/src/pages/documents/ChartDesignerModal.tsx:187-188`、`:214-239` | 用户看不到「留空即按主值推算」的默认联动态，空白列语义不直观 | 确认（C2/C4 核心改造点） |
| 3 | 联动单元格与普通单元格同为 `InputNumber`，高亮仅改背景色，无「(计算)」字样 | `ChartDesignerModal.tsx:557-585` | 无法区分「推算值」与「显式值」的数值本身 | 确认（C1/C3 改造点） |
| 4 | 首行次值禁填（前端 disabled + 后端 400） | `ChartDesignerModal.tsx:569-580`、`src/cndb/plugins/documents/services/charts/registry.py`（validate_config） | 默认联动态不覆盖第 1 行 | 确认（保留不动） |
| 5 | 渲染端次值留空按主值推算（`growth_at`，一位小数），首行恒不画 | `src/cndb/plugins/documents/services/charts/render.py:166-175` | 设计器默认联动态显示值须与其同口径 | 确认（C2 口径基准） |
| 6 | 堆叠 / 分组系列模板行结构为 `label + values[]`，无派生配对 | `ChartDesignerModal.tsx:510-541` | C6 范围外，回归确认即可 | 确认（排除改动） |
| 7 | 既有测试断言高亮样式与联动行为 | `frontend/src/pages/documents/ChartDesignerModal.test.tsx`、`chartLinkage.test.ts`、`frontend/tests/e2e/critical/chart-designer-linkage.spec.ts` | 显示形态变化需同步断言 | 新增（波及面） |
| 8 | 教程含联动说明文案 | `frontend/src/pages/help/content/tutorials.tsx` | 需补「(计算)」与默认联动态说明 | 新增（C1/C2 文档面） |

**核心缺陷（需求要补的）**：0056 的联动只解决「填了才联动」，留空次值在设计器里显示为空白，用户看不出「空白 = 按主值自动推算」；且联动结果与手动值在数值本身上无区别（仅底色 + 悬浮提示），不直观。

设计目标（不变量）：

- **I1 显示 = 渲染口径**：设计器联动态显示值一律来自 `chartLinkage` 既有函数（与 `render.py` `growth_at` 同公式、同舍入），不引入第二套推算逻辑。
- **I2 联动态不入库**：联动态（含「(计算)」后缀）是纯显示态；提交 config 结构不变，留空次值仍存 `null`（C5）。
- **I3 显式值优先**：用户实际改动过的单元格是显式值，退出联动态；清空则回到联动态（可推算时）。
- **I4 存量零迁移**：无表变更、无 API 结构变更，存量实例 config 不改写。

## Decision

### 1. 数据模型

无表变更、无迁移、无 config 结构变更。全部改动在前端设计器显示层与交互层。

### 2. 判定算法（唯一入口）

联动态判定与显示值计算仍以 `chartLinkage.ts` 为唯一入口，新增一个纯展示判定 helper（不改既有两函数）：

```ts
// 默认联动态显示值：次值留空时按主值推算（C2），与 linkGrowthFromValue 同口径
growthLinkedDisplay(row: ChartDataRowDraft, prevRow: ChartDataRowDraft | undefined):
  { linked: boolean; display: number | null }   // linked=false 时 display 为 row.growth
```

设计器内单元格最终显示态 = 三步收敛（`ChartDesignerModal.tsx` 内纯函数 `cellDisplayState`）：

1. 编辑态（该单元格正被点击编辑）→ 显示纯数值（联动态取推算值，非联动态取原值）；
2. 联动态（`affected` 含该键，或 C2 的默认联动态判定成立）→ 非编辑态显示 `数值(计算)` + 高亮；
3. 其余 → 普通 `InputNumber` 原样显示。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| 无 | 全部接口不变；提交 payload 结构与校验规则均不变（C5） |

### 4. 边界与例外

1. 第 1 行（i=0）次值：无上年基数，不进入默认联动态，保持禁填（C2 与 0056 I3 一致）。
2. 基数缺失 / ≤0、推算结果非有限数：该单元格不进入联动态，按普通空白处理，可正常填写。
3. 点击联动态单元格进入编辑后未改动即失焦：保持联动态（Q1），`growth` 仍为 `null`、主值不被改写。
4. 编辑联动态次值并改动数值：走 `updateRowField` 既有联动，主值被重算进入联动态（C4）；再次手动编辑被联动单元格即清除其 `affected` 标记（0056 D4 行为不变）。
5. 清空已填次值：`growth` 置 `null` 后，默认联动态判定自动接管，恢复「推算值(计算)」显示（C4）。
6. 联动态主值（被次值联动重算）：其数值已写入草稿（0056 既有行为），显示 `数值(计算)`；点击编辑显示该数值，改动后按反向公式重算次值。
7. 增删行导致行号位移：`affected` 集合整体清空（既有行为），默认联动态按新行序即时重算，不受影响。
8. 堆叠 / 分组系列模板：不进入联动态渲染分支，行为不变（C6）。

### 5. 迁移

无。零迁移、存量零改写（I4）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 联动纯函数 | `frontend/src/pages/documents/chartLinkage.ts` | 新增 `growthLinkedDisplay`（C2 默认联动态判定与显示值），复用 `linkGrowthFromValue` |
| 设计器 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | 双轴数据表单元格改为「展示态 / 编辑态」双态渲染：联动态非编辑时渲染可点击的 `数值(计算)` 文本（沿用高亮），点击切换为 `InputNumber`（C1/C2/C3）；失焦提交接入 Q1 未改动保持联动态语义（C4） |
| 教程文档 | `frontend/src/pages/help/content/tutorials.tsx` | 图表教程补「次值留空显示为推算值(计算)、点击可编辑、编辑后对应主/次值联动」说明（C6 文档面） |

### 7. 测试清单

**判定层（单测）**：`frontend/src/pages/documents/chartLinkage.test.ts` — `growthLinkedDisplay`：基数存在 → linked + 一位小数推算值；基数缺失 / ≤0 / 首行 → linked=false；growth 非空 → linked=false。

**前端单测**：`ChartDesignerModal.test.tsx` — 默认打开双轴设计器，次值列（i≥1 且可推算）显示 `x.x(计算)` 且带高亮（C2）；第 1 行次值禁填不变；点击联动态次值 → 编辑框为纯数值（C3）；未改动失焦 → 恢复 `(计算)` 显示、payload growth 仍 null（Q1/C5）；改动次值失焦 → 主值显示 `x.x(计算)`（C4）；清空次值 → 恢复联动态显示（C4）；提交 payload 无标记字段（C5）；堆叠 / 分组模板行为回归不变（C6）。

**接口层 / 迁移 / 备份**：无（零接口、零迁移，不适用）。

**e2e（前端）**：`frontend/tests/e2e/critical/chart-designer-linkage.spec.ts` 扩展 — 新建双轴图默认次值列显示 `(计算)`；点击进入编辑显示纯数值；填次值后主值带 `(计算)`、预览曲线不变。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `chartLinkage.growthLinkedDisplay` + 单测（纯函数，无 UI） | 低 |
| **P1** | 设计器双态渲染（联动态 `(计算)` 展示 + 点击进编辑 + Q1 未改动语义）+ 前端单测 | 中 |
| **P2** | 教程文案 + e2e 扩展 + `make flow` 全绿 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型：联动态展示放显示层还是改数据模型（如落库推算值） | 纯前端显示层双态渲染，数据模型不动 | 需求只要求「知晓」；落库推算值违反 0056 I2 且破坏留空推算渲染语义 | 推算值落库（污染 config、渲染端双口径） | `ChartDesignerModal.tsx` |
| D2 | 默认联动态显示值口径 | 复用 `linkGrowthFromValue`（与 `render.py` `growth_at` 同公式同舍入，一位小数） | I1 单一口径；需求方确认 Q3 | 新增第二套推算函数（双口径漂移） | `chartLinkage.ts` |
| D3 | 「(计算)」呈现方式 | 非编辑态渲染为可点击文本 `数值(计算)`（沿用高亮），点击切换真实 `InputNumber` | 需求原文「点击后进入编辑状态，仅显示数值」；InputNumber 无法内嵌后缀文本 | InputNumber 内拼后缀（编辑态会带出 `(计算)` 字样）；仅加前缀 / 后缀 addon（占宽且编辑态同样带出） | `ChartDesignerModal.tsx` |
| D4 | 联动单元格未改动即失焦的语义 | 保持联动态（growth 仍 null、主值不改写） | 需求方确认 Q1；避免「点一下就固化推算值」的隐式写入 | 失焦即固化显式值（隐式改数据，违背显式值优先） | `ChartDesignerModal.tsx` |
| D5 | 联动态的来源建模 | 两种来源统一为「联动态」：默认推算（growth 为 null 且可算）+ 本轮联动重算（`affected` 集合，保留） | 显示行为一致（`(计算)` + 高亮），来源只影响数值是否已写入草稿 | 废弃 `affected` 改为全量即时推导（主值联动态无法从数据推导，会丢标记） | `ChartDesignerModal.tsx` |
| D6 | 其他图表范围 | 联动态渲染实现为通用模式，堆叠 / 分组行为不变，不新增派生能力 | 需求方确认 Q2；沿用 ADR 0056 D5 | 为堆叠 / 分组新增占比派生列（超出需求） | `ChartDesignerModal.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：次值列「留空即推算」从隐式语义变为可见（默认显示推算值 + `(计算)`），用户无需读文档即知增长曲线来源；联动值与手动值在数值上直接可辨；编辑交互（点击 → 纯数值）符合直觉。
- **负向**：双轴数据表单元格由单一 `InputNumber` 变为双态渲染，交互与测试复杂度上升；联动态单元格需一次额外点击才能编辑。
- **风险与缓解**：展示值与渲染推算同口径（D2），不存在「设计器显示与图上曲线不一致」；清空 / 未改动路径均不写库，隐式写入风险由 D4 排除。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 联动公式 / 舍入口径 | `chartLinkage.ts` | 不变，仍是唯一入口 | ADR 0056 D2 |
| 首行禁填 / 后端 400 | `registry.py` | 不变 | ADR 0056 D6 |
| 设计器显示层（联动态 / `(计算)` / 双态渲染） | `ChartDesignerModal.tsx` | 本 ADR 新增 | ADR 0059 |
| 渲染端留空推算 | `render.py` | 不变 | ADR 0048 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/documents/chartLinkage.ts` | `frontend/src/pages/documents/chartLinkage.test.ts` | 待提交 |
| P1 | 已落地 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | `frontend/src/pages/documents/ChartDesignerModal.test.tsx` | 待提交 |
| P2 | 已落地 | `frontend/src/pages/help/content/tutorials.tsx` | `frontend/tests/e2e/critical/chart-designer-linkage.spec.ts` | 待提交 |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（待人工评审回填 Implemented）
- 已完成：P0（growthLinkedDisplay 默认联动态判定）、P1（设计器联动态「(计算)」展示 / 点击进编辑 / Q1 未改动语义）、P2（教程文案 + e2e 扩展 + CHANGELOG）
- 下一步：`make flow` 全绿后提交；e2e 本地环境就绪后跑 critical 分片；人工评审后 Status → Implemented
- 已知坑：e2e 本地环境缺系统库（libatk-1.0.so.0）暂无法启动 chromium，spec 已就位待环境修复后执行；联动态展示用 readOnly Input 承载「数值(计算)」，点击切换 InputNumber 编辑态
- 最近一次全绿：见本次 `make flow` 结果（落地后回填）
