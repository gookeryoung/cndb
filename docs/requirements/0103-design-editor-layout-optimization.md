# 需求卡片：【设计】编辑器布局优化（对齐 CAD 最佳实践）

- 编号：0103（与 ADR `docs/adr/0103-design-editor-layout-optimization.md` 同号）
- 来源 / 提出人：用户（2026-11-05 会话）
- 日期：2026-11-05
- 关联 ADR：`docs/adr/0103-design-editor-layout-optimization.md`（S2，立项后回填状态）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请结合机械结构设计的最佳实践，针对设计页面的布局制定优化方案，包括侧边栏、内容区域的布局设计。

## 需求澄清（2026-11-05 用户已确认）

1. 参数面板形态：**预览栏底部「参数｜约束」可折叠面板**（Tabs），不采用右侧第三栏、不保留抽屉。
2. 树↔视口实体联动高亮：**纳入本轮（P2）** —— 接受 IR v4→v5 双端契约演进，整单按 S2 走需求卡片 + ADR。
3. 分栏默认档：**均分 50/50**（与现状连续），用户可拖拽 / 切换三档预设并本地持久化。
4. （2026-11-05 复核补充）「设计页面」覆盖设计模块全部页面：侧边栏与内容区域（含设计管理页 / 设计编辑器页）都要给出布局设计，侧边栏不做「仅保留」处理。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「包括侧边栏…的布局设计」 | 侧边栏保留装配树范式（ADR 0084 D4/D5：设计→系统→组件→分组→零件、懒加载、只读），并补双向定位闭环：① 大纲节点点击后**持续选中高亮**（现状仅设计根高亮，`selectedKeys` 不含大纲节点）；② 编辑器 `?line=` 定位时侧栏滚动到对应大纲节点并展开其祖先链（CAD「选中特征 → 树中高亮」惯例，现状只有树→编辑器单向） | frontend（`DesignStructureNav` / `DesignEditorPage`） | 前端单测（选中态 / 反向定位滚动）+ e2e 回归 |
| C2 | 「内容区域的布局设计」 | 编辑器 / 预览分栏支持拖拽调整比例 + 三档预设（编辑器优先 / 均分 / 视口优先）；默认均分 50/50；比例 localStorage 持久化；窄屏（<1024px）维持纵向堆叠、不启用拖拽 | frontend（`DesignEditorPage` + `index.css`） | 前端单测（预设切换 / 持久化 / 窄屏降级）+ e2e |
| C3 | 「结合机械结构设计的最佳实践」 | 视口提供悬浮工具条：**主视（前）/ 俯视（上）/ 仰视（下）/ 左视 / 右视 / 后视 / 等轴测**七向定向（术语对齐机械制图国标惯例）、布满视图（fit）、网格显示开关 | frontend（`PreviewCanvas`） | 前端单测 + e2e（定向后相机位姿 / fit 生效） |
| C4 | 「结合机械结构设计的最佳实践」 | 视口底部常驻状态条：显示长度单位 mm、节点数、三角数；数据消费既有 `PreviewStats`（`onStats` 当前无消费者，属接通闲置数据） | frontend（`PreviewCanvas` / `DesignEditorPage`） | 前端单测（统计上报 → 状态条渲染） |
| C5 | 「结合机械结构设计的最佳实践」 | 参数面板常驻化：预览栏底部「参数｜约束」可折叠 Tabs 面板替代参数抽屉；参数改值即时重编译（沿用既有 preview 端点，前端零求值）；保留一键重置覆盖；约束面板并入同区域（原预览底部横条退役） | frontend（`DesignEditorPage` / `DesignConstraintsPanel`） | 前端单测（改参重编译 / 重置 / 折叠）+ e2e |
| C6 | 「内容区域的布局设计」 | 顶部工具栏单行化：任何屏宽不换行挤压视口；版本历史、导出收进溢出菜单（次要动作），返回 / 标题 / 编译状态 / 保存保持常显 | frontend（`DesignEditorPage`） | 前端单测 + 窄屏 e2e 断言工具栏高度不变 |
| C7 | 「结合机械结构设计的最佳实践」 | 树↔视口联动高亮（P2）：点击侧栏大纲节点，视口高亮对应实体；大纲节点须携带对应 IR `nodes` 索引（IR v4→v5 双端契约演进，同源产出、确定性不变） | design plugin + frontend（`compile.py` / `design.ts` / `PreviewCanvas` / `DesignStructureNav`） | 判定层单测（outline↔nodes 索引一致）+ 接口回归 + 前端单测 + e2e |
| C8 | 「内容区域的布局设计」 | 设计管理页（内容区默认页）布局改造：设计列表按**目录（folder）分组**展示、支持按**类型（零件 / 装配）筛选**（字段为 ADR 0086 既有 `folder` / `kind`，零后端变更），对齐 CAD 文件库「目录树 + 类型过滤」组织惯例；新建 / 打开 / 改名 / 删除 / 描述能力不减少 | frontend（`DesignsPage`） | 前端单测（分组 / 筛选 / 既有操作回归）+ e2e |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 分栏固定 `1fr 1fr` 网格，不可拖拽 | `frontend/src/index.css:7234-7240` | C2 改造点 |
| 2 | 参数抽屉（`paramsOpen` Drawer） | `frontend/src/pages/design/DesignEditorPage.tsx:336-374` | C5 退役对象 |
| 3 | 约束面板在预览栏底部横条 | `frontend/src/pages/design/DesignEditorPage.tsx:321-331`、`DesignConstraintsPanel.tsx` | C5 并入 Tabs |
| 4 | `onStats`（节点 / 三角统计）已实现但无消费者 | `frontend/src/pages/design/PreviewCanvas.tsx:34-42` | C4 接通点 |
| 5 | OrbitControls + 固定 GridHelper，无手动视图控制 | `frontend/src/pages/design/PreviewCanvas.tsx:147-151` | C3 改造点 |
| 6 | 工具栏 `flex-wrap` 换行 | `frontend/src/index.css:7179-7198`、`DesignEditorPage.tsx:191-250` | C6 改造点 |
| 7 | 窄屏两栏堆叠 media query | `frontend/src/index.css:7365-7376` | C2 降级路径保持 |
| 8 | 大纲节点无 IR node 索引（outline 与 nodes 同源但未关联） | `src/cndb/plugins/design/services/dsl/compile.py`（`_Emitter` 大纲收集）、`frontend/src/api/design.ts`（`DesignOutlineNode`） | C7 契约演进根因 |
| 9 | 骨架渲染按 node index 存 `nodeGroups`（联动高亮可复用） | `frontend/src/pages/design/PreviewCanvas.tsx:283` | C7 前端落点 |
| 10 | 编辑器页既有单测 / e2e（工具栏、抽屉、约束断言） | `frontend/src/pages/design/*.test.tsx`、`frontend/tests/e2e/critical/*` | C5/C6 需同步改断言 |
| 11 | 版本历史抽屉交互（回看 / 恢复） | `frontend/src/pages/design/DesignEditorPage.tsx:377-451` | C6 只改入口位置，功能不变 |
| 12 | 侧栏树 `selectedKeys` 仅含设计根键，大纲节点无选中态 | `frontend/src/pages/design/DesignStructureNav.tsx:244` | C1① 改造点 |
| 13 | 树→编辑器单向定位（`?line=`），编辑器不反向通知侧栏 | `frontend/src/pages/design/DesignEditorPage.tsx:308-310`、`DesignStructureNav.tsx:127-133` | C1② 改造点（反向联动） |
| 14 | 设计管理页为平面 `List`，`folder` / `kind` 字段已有但无分组 / 筛选 | `frontend/src/pages/design/DesignsPage.tsx:100-271` | C8 改造点（零后端变更） |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 参数面板形态 → 已确认：预览栏底部「参数｜约束」Tabs 面板（见「需求澄清」#1）
- [x] 树↔视口联动是否纳入 → 已确认：纳入为 P2，IR v4→v5，整单 S2（见「需求澄清」#2）
- [x] 默认分栏档位 → 已确认：均分 50/50（见「需求澄清」#3）
- [ ] 视口高亮的视觉呈现（自发光 tint vs 描边）与持续时间 → ADR「Decision」定（设计细节，非需求分叉）
- [ ] 溢出菜单的收纳清单与顺序 → ADR「Decision」定

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」；侧边栏 C1、管理页 C8 均有实质设计，非「仅保留」）
- [x] 未决问题全部有结论，需求方确认（2026-11-05 会话确认三个分叉；其余两项转 ADR 设计细节）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
