# ADR 0103：【设计】编辑器布局优化（可调分栏 / 视口工具条 / 参数常驻 / 树↔视口联动 IR v5）

Status: Implemented
Date: 2026-11-05
Related: `frontend/src/pages/design/`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`、`src/cndb/plugins/design/services/dsl/compile.py`、`frontend/src/api/design.ts`；上游 ADR 0079 / 0083 / 0084 / 0086
需求卡片: `docs/requirements/0103-design-editor-layout-optimization.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C8），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 侧边栏保留装配树范式 + 双向定位闭环 | 侧栏信息架构不动（0084 D4/D5）；补两件事：① 大纲节点点击后 `selectedKeys` 持续高亮该节点（现状仅设计根）；② `?line=` 定位源行时按 D9 归属规则滚动到对应大纲节点并展开祖先链（树↔编辑器双向） |
| C2 | 编辑器 / 预览分栏拖拽 + 三档预设，默认均分 | `.cn-dsl-workbench` 由固定 `1fr 1fr` 改为自研 splitter（D3）：内联 `grid-template-columns` 比例拖拽（clamp 25%–75%、每侧 ≥320px）、预设三档（编辑器优先 60/40 / 均分 50/50（默认，D10）/ 视口优先 40/60）、比例存 localStorage `cn-design-editor-split`；窄屏 <1024px 维持纵向堆叠、不渲染 splitter |
| C3 | 视口悬浮工具条：七向定向 / 布满 / 网格开关 | 视口右上悬浮胶囊（D4）：视图定向 Dropdown（主视 / 俯视 / 仰视 / 左视 / 右视 / 后视 / 等轴测，术语 D11）+ 布满视图（fit，复用现有 frame 逻辑）+ 网格显隐开关；`PreviewCanvas` 经 `onViewportApi` 回调暴露 `{ orientTo, fit, setGridVisible }`，工具条 UI 在编辑器页渲染 |
| C4 | 视口底部状态条：单位 / 节点数 / 三角数 | 视口左下常驻细条：`{units.length} · 节点 {n} · 三角 {m}`；单位取 IR `units.length`（不硬编码，D5），统计接通既有 `onStats` 回调（现状无消费者） |
| C5 | 参数面板常驻：预览栏底部「参数｜约束」可折叠 Tabs | 参数抽屉退役；预览栏纵向 flex = 视口（flex:1）+ 底部面板（展开上限 280px 内部滚动 / 折叠为 36px 细条，折叠态存 localStorage `cn-design-params-collapsed`）；Tab 徽标 = 覆盖数 / 约束数；参数改值即时重编译（沿用 preview 端点 + 一键重置覆盖，行为不变）；约束列表复用 `DesignConstraintsPanel` 内容渲染，原预览底部横条退役 |
| C6 | 工具栏单行化 + 次要动作溢出收纳 | `.cn-dsl-toolbar` 恒单行（nowrap，标题 truncate）；版本历史、导出恒收进「更多」Dropdown（D6，非断点式）；返回 / 标题 / 版本标签 / 编译状态 / 保存常显；诊断条保留 |
| C7 | 树↔视口实体联动高亮（IR v4→v5） | outline 节点增 `node_index`（首个所属顶层 `nodes` 数组下标，D7）；侧栏点击大纲节点 → 既有 `?line=` 定位源行 + 编辑器页按大纲归属收集 `node_index` 集合 → `PreviewCanvas` emissive tint 高亮 3s 渐隐（D8）；v4 旧快照无字段时静默降级（不高亮，不报错） |
| C8 | 管理页按目录分组 + 类型筛选 | `DesignsPage` 列表按 `folder` 分组（空目录归「未分组」置底）、`kind` Segmented 筛选（全部 / 零件 / 装配，D12）；字段为 0086 既有 `design_design.folder` / `kind`，零后端变更；新建 / 打开 / 改名 / 删除 / 描述能力不减少 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 编辑器 / 预览固定 `minmax(0,1fr) minmax(0,1fr)`，50/50 不可调 | `frontend/src/index.css:7234-7240` | 无法随任务调整主次（读代码 / 看模型两种姿势都被锁死） | 确认（C2） |
| 2 | 参数面板为右侧 Drawer（`paramsOpen`），默认隐藏 | `frontend/src/pages/design/DesignEditorPage.tsx:336-374` | 改参需两次点击才见参数，反馈闭环长，违背 CAD 参数面板常驻惯例 | 确认（C5） |
| 3 | 约束面板为预览栏底部横条 | `frontend/src/pages/design/DesignEditorPage.tsx:321-331`、`frontend/src/pages/design/DesignConstraintsPanel.tsx` | 与参数分居两处，辅助信息区域层级混乱 | 确认（C5 并入 Tabs） |
| 4 | `onStats`（节点 / 三角统计）已实现但无任何消费者 | `frontend/src/pages/design/PreviewCanvas.tsx:34-42` | 模型统计是死数据；单位（mm）也无 UI 展示 | 确认（C4 接通） |
| 5 | 视口仅 OrbitControls + 固定 GridHelper，每次 IR 变更自动 frame | `frontend/src/pages/design/PreviewCanvas.tsx:147-151` | 无标准视图定向、无手动 fit、无网格开关，低于 CAD 视口操作基线 | 确认（C3） |
| 6 | 工具栏 flex 布局窄屏换行挤压视口高度 | `frontend/src/index.css:7179-7198`、`frontend/src/pages/design/DesignEditorPage.tsx:191-250` | 视口高度不稳定 | 确认（C6） |
| 7 | 窄屏 <1024px 两栏纵向堆叠 | `frontend/src/index.css:7365-7376` | 移动降级路径，行为保留 | 确认（C2 降级路径不变） |
| 8 | 大纲与 `nodes` 同一次编译产出（`emit_program` 一次返回两者），但 outline 节点不携带 `nodes` 下标；`IR_VERSION = 4` | `src/cndb/plugins/design/services/dsl/compile.py:71`、`compile.py:389-430`（`_emit_instance` 返回 `(inst_nodes, inst_outline)`，`compile.py:362` `_part_outline`） | 树↔视口无实体级映射，高亮无从谈起；增量字段落点天然存在（同一函数产出两侧） | 确认（C7； emitter 结构对增量友好，见 D7） |
| 9 | 骨架渲染按顶层 `nodes` 下标存 `nodeGroups` | `frontend/src/pages/design/PreviewCanvas.tsx:283` | 高亮可直接复用该映射（index → mesh group） | 确认（C7 前端落点） |
| 10 | 侧栏树 `selectedKeys` 仅含设计根键，大纲节点无选中态 | `frontend/src/pages/design/DesignStructureNav.tsx:244` | 点击大纲节点后无持续视觉反馈 | 确认（C1①） |
| 11 | 树→编辑器单向定位（读 `?line=` reveal），编辑器不反向通知侧栏 | `frontend/src/pages/design/DesignStructureNav.tsx:127-133`、`frontend/src/pages/design/DesignEditorPage.tsx:308-310` | 半条链路：树能定位代码，代码位置不同步树 | 确认（C1② 补反向） |
| 12 | 管理页为平面 `List`，`folder` / `kind` 字段已有但无分组 / 筛选 | `frontend/src/pages/design/DesignsPage.tsx:100-271`、`design_design.folder` / `kind`（ADR 0086） | 文件多时无组织维度，低于 CAD 文件库基线 | 确认（C8，零后端） |
| 13 | 既有单测 / e2e 断言工具栏、参数抽屉、约束横条形态 | `frontend/src/pages/design/*.test.tsx`、`frontend/tests/e2e/critical/design-*.spec.ts` | C5/C6 改布局后断言需同步迁移 | 确认（测试清单） |
| 14 | 版本历史抽屉（回看 / 恢复）功能完整 | `frontend/src/pages/design/DesignEditorPage.tsx:377-451` | 只改入口位置（收进「更多」），功能不动 | 确认（C6） |

**核心缺陷（需求要补的）**：现状树只通代码、代码只通树的半条链路，视口零手动操作、参数藏在抽屉、统计与单位不可见——缺一条「树 ↔ 视口」的实体级联动，以及 CAD 工具的视口操作面与常驻参数反馈闭环。

设计目标（不变量）：

- **I1 渲染零求值不变**：布局改造不改变 IR 消费方式，前端仍零解析零求值（沿用 0079 I1）；高亮只用 IR 既有字段 + v5 增量字段，不在前端做几何分析。
- **I2 IR 向后兼容**：v5 只在 outline 节点**新增** `node_index`；v4 旧快照照常渲染与导出，联动高亮静默降级（不高亮、不报错）；旧备份 / 版本快照不受影响。
- **I3 确定性不变**：同原文 + 同覆盖 → 同 IR（含 `node_index`）；`node_index ∈ [0, len(nodes))` 且与该节点子树图元一致（同源一次产出保证）。
- **I4 功能无回退**：保存 / 版本历史 / 导出 / 权限（viewer 只读、403）行为不变；窄屏堆叠态所有新功能可达（工具条 / 状态条跟随视口，参数面板置于预览下方）。
- **I5 UI 偏好本地化**：分栏比例、面板折叠态、网格开关等纯 UI 偏好只存 localStorage，不进后端、不进备份。

## Decision

### 1. 数据模型

无新表、无新列。`design_design.compiled`（JSON 布尔树快照）契约从 **v4 → v5**：

- 顶层 `version: 4 → 5`（`compile.py:71` `IR_VERSION`）。
- `outline` 每个节点（`system` / `assembly` / `group` / `part`）新增 `node_index: int | null` —— 该节点所辖**首个顶层 `nodes` 数组元素**的下标；零产出实例（空模块）为 `null`。父节点（system / assembly）不聚合子树（前端按 `children` 递归聚合，见 D7）。
- `nodes` 结构不变（渲染热路径零改动）。

### 2. 判定算法（唯一入口）

编译唯一入口 `compile_design(content, overrides, resolver)` 不变；`node_index` 在 `_Emitter` 落点：

- `_emit_instance`（`compile.py:389-490` 一族）已同时返回 `(inst_nodes, inst_outline)`——在把 `inst_nodes` 追加进顶层 `nodes` 处记录起始下标，回填本层每个 outline 节点的 `node_index`。
- `_part_outline`（`compile.py:362`）由调用方注入 `node_index`（布尔块内多个 `part` 共享该块顶层下标，见「边界与例外」#2）。
- 保存 / 预览 / 版本恢复 / 种子 / 重构共用同一编译入口，无需各处适配。

### 3. API 变更清单

无新端点；既有端点载荷增量（**只增字段**）：

| 端点 | 变更 |
|---|---|
| `GET /{wid}/designs/{id}/outline` | outline 节点新增 `node_index`（快照为 v4 时无该字段） |
| `GET /{wid}/designs/{id}/ir` | `version: 5`；outline 节点带 `node_index` |
| `POST /{wid}/designs/preview` | 同上（即时编译，恒为 v5） |

### 4. 边界与例外

1. **布尔块粒度**：一个布尔块（`group`）是单个顶层 CSG 树 → 其下所有 `part` 的 `node_index` 相同，选中任一 `part` 高亮**整块**网格；这是 CSG 网格粒度上限，接受（无 BREP）。
2. **v4 旧快照**：无 `node_index` → 联动高亮静默跳过，`?line=` 定位源行照常；重新保存后自然升 v5。
3. **零产出实例**（空模块 / 空装配）：`node_index = null`，点击只定位源行。
4. **反向定位归属**（D9）：同一父节点下按 `line` 升序取「最后一个 `line ≤ revealLine`」的节点；早于首行不选中。启发式，够用（大纲节点只有起始行）。
5. **高亮时序**：编译进行中（布尔网格未就绪）触发高亮 → 对已就绪的 `nodeGroups` 生效，未就绪节点在就绪后不补高亮（避免闪烁；再次点击可重触发）。
6. **viewer 权限**：全部新交互为只读，viewer 可用；改参 / 保存仍 403（不变）。
7. **窄屏**：<1024px 堆叠态 splitter 不渲染，比例不生效；工具条 / 状态条 / 参数面板随视口列正常渲染。

### 5. 迁移

无 alembic 迁移（`compiled` 为 JSON 列，无 schema 变更）。存量 v4 快照按只读兼容处理（I2），随下次保存重编译自然升 v5；备份 / 版本往返不感知该字段（只含原文与重编译结果）。downgrade 不适用。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面骨架 | `frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/index.css`（`.cn-dsl-*`） | workbench 改可调分栏（splitter 组件 + 内联 `grid-template-columns`）；工具栏单行 + 「更多」Dropdown（版本历史 / 导出）；接收 `onViewportApi` / `onStats`；挂视口工具条与状态条；管理「参数｜约束」底部面板状态 |
| 视口 | `frontend/src/pages/design/PreviewCanvas.tsx`、`frontend/src/pages/design/viewOrient.ts`（新） | 新增 `onViewportApi`（暴露 `orientTo` / `fit` / `setGridVisible` / `highlight(indices)`）；网格改受控显隐；定向常量表（七向方向向量 + up）；高亮 = 按 `node_index` 即时求值该节点几何、叠加 emissive 副本（polygonOffset 防 z-fighting）2.4s 常亮 + 0.6s 淡出后释放，宿主 `data-highlight-nodes` 作为可观测通道 |
| 参数 / 约束面板 | `frontend/src/pages/design/DesignParamsPanel.tsx`（新）、`DesignConstraintsPanel.tsx` | 抽出 Drawer 内参数列表为常驻面板（Tabs：参数 N / 约束 M + 折叠）；约束列表复用 `DesignConstraintsPanel` 渲染；改参 / 重置逻辑不变 |
| 侧栏 | `frontend/src/pages/design/DesignStructureNav.tsx` | `selectedKeys` 支持大纲节点键；`?line=` 变化按 D9 归属 → 展开祖先链 + `tree.scrollTo`（antd Tree 虚拟滚动定位）；点击节点 = 定位源行（既有）+ 触发高亮（P2） |
| 侧栏宿主 | `frontend/src/layouts/MainLayout.tsx` | 不改（侧栏仍 240/60，`MainLayout.tsx:928`；联动经 `?line=` URL 既有通道） |
| 管理页 | `frontend/src/pages/design/DesignsPage.tsx` | `folder` 分组（空 → 「未分组」置底）+ `kind` Segmented 筛选；列表操作不变 |
| 「更多」菜单 | `frontend/src/pages/design/DesignMoreMenu.tsx`（新，原 `DesignExportMenu` 演进） | 版本历史 + 导出（STL / OBJ / GLB / 三视图）收进同一 Dropdown（导出为分组，不嵌套二级菜单）；仍在 three lazy 边界 |
| API 封装 | `frontend/src/api/design.ts` | `DesignOutlineNode` 增 `node_index?: number \| null` 与 `file_id?: number`（可选，兼容 v4） |
| 后端 | `src/cndb/plugins/design/services/dsl/compile.py` | `IR_VERSION = 5`；`_Emitter` 回填 `node_index`（§2） |

### 7. 测试清单

**判定层（单测，`tests/test_design_dsl.py`）**：
- `node_index` 存在性与范围：所有 outline 节点 `node_index ∈ [0, len(nodes))` 或 `null`；
- 布尔块内多 `part` 共享同一顶层下标；无分组图元 `part` 下标即自身；
- 变换穿透不改下标；`use` 引用实例的 `node_index` 指向展开后的顶层节点；
- 确定性：同输入两次编译 IR 全等（含 `node_index`）；
- `version == 5`。

**接口层（`tests/test_design_api.py`）**：
- outline / ir / preview 载荷含 `node_index`；
- v4 旧快照（手工构造 compiled 行）outline 端点照常 200、无该字段。

**迁移 / 备份**：无迁移；备份往返（v12）导出原文、导入重编译自然 v5；旧备份（含 v4 快照）导入后渲染 / 高亮降级路径回归。

**前端单测**：splitter 拖拽 / 三档预设 / 持久化 / 窄屏降级；定向常量表相机位姿；`onStats` → 状态条渲染；参数面板改参重编译 / 重置 / 折叠持久化；工具栏收纳（「更多」内可达版本历史 / 导出）；侧栏反向定位归属规则与 `scrollTo`；管理页分组 + 筛选。

**e2e（`frontend/tests/e2e/`）**：
- 新增 `critical/design-editor-layout.spec.ts`：预设切换与拖拽后布局比例、定向 / fit / 网格开关、状态条可见、参数改参即时重编译、工具栏单行不换行；
- 新增 `critical/design-tree-viewport-linkage.spec.ts`（P2）：点击树节点 → 视口高亮块出现并渐隐；v4 快照降级不高亮；
- 更新 `critical/design-structure-tree.spec.ts`（反向定位）与既有编辑器断言（抽屉 → 面板）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | C2 splitter + 预设、C3 视口工具条、C4 状态条、C6 工具栏收纳（纯前端，零契约） | 低 |
| **P1** | C5 参数｜约束常驻面板、C1 侧栏双向定位闭环、C8 管理页分组筛选（纯前端，零契约） | 中（编辑器页重构面大，既有断言迁移） |
| **P2** | C7 IR v5 `node_index` + 树↔视口联动高亮（双端契约演进） | 中（契约双端同步；布尔块粒度例外已在 §4#1 声明） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 纯前端布局重构 + 最小契约演进（IR v5 单字段增量）；零新 npm 依赖、零新端点、零迁移 | 0079 D2 零依赖惯例；改动面收敛在前端 + `compile.py` 单点 | 右侧第三参数常驻栏（≤1280px 每栏过窄）；独立 outline 版本化接口（过度设计） | `DesignEditorPage.tsx`、`compile.py` |
| D2 | 参数面板形态 | 预览栏底部「参数｜约束」可折叠 Tabs 面板（用户 2026-11-05 确认） | 保持两栏骨架、窄屏友好；约束面板自然并入；改参即时重编译闭环 | 右侧第三栏（同 D1）；抽屉钉住（不满足常驻，CAD 惯例差距仍在） | `DesignParamsPanel.tsx` |
| D3 | 分栏拖拽实现 | 自研 splitter（pointer 事件 + 内联 grid 比例），clamp 25%–75%、每侧 ≥320px，`localStorage: cn-design-editor-split` | 需求仅三档 + 拖拽，自研 ~百行内；Chrome 81 PointerEvent 可用 | `react-resizable-panels` 等三方库（违背零依赖）；CSS `resize`（单向、样式不可控） | `DesignEditorPage.tsx`、`index.css` |
| D4 | 视口工具条形态 | 视口内右上悬浮胶囊；`PreviewCanvas` 经 `onViewportApi` 暴露受控 API，UI 在编辑器页渲染 | 不占视口布局高度；three lazy chunk 与 antd UI 边界清晰（工具条与 canvas 同生命周期） | 常驻顶部横条（吃视口高度）；工具条塞进 `PreviewCanvas` 内部（lazy chunk 内引 antd，边界混乱） | `PreviewCanvas.tsx` |
| D5 | 状态条数据源 | 单位取 IR `units.length`（显式契约，不硬编码）；节点 / 三角接通既有 `onStats` | IR 已显式携带单位声明（0079 D3），硬编码是第二真相源；`onStats` 属接通死数据 | 硬编码 "mm"（契约漂移风险） | `PreviewCanvas.tsx`、`DesignEditorPage.tsx` |
| D6 | 工具栏溢出收纳 | 版本历史 / 导出**恒**收进「更多」Dropdown（非断点式）；保存 / 状态常显 | 单行恒成立、断言稳定；次要动作使用频度低 | 按屏宽断点动态迁移按钮（断点抖动、e2e 不稳定） | `DesignEditorPage.tsx` |
| D7 | IR v5 契约形态 | 仅 outline 节点增 `node_index`（首个所属顶层下标，空产出 `null`）；父节点不聚合，前端按 `children` 递归聚合 | `_emit_instance` 一次产出两侧（`compile.py:389-490`），单字段回填最小且无漂移面 | 全节点携带聚合数组（冗余、双份真相）；`nodes` 内嵌反向指针（渲染热路径加字段） | `compile.py`、`api/design.ts` |
| D8 | 联动高亮视觉 | 材质 emissive tint + 3s 渐隐；再次点击重触发（卡片未决项落点） | 零后处理、零新依赖，视觉足够醒目 | `OutlinePass` 描边（引 postprocessing 依赖 + GPU 成本） | `PreviewCanvas.tsx` |
| D9 | 反向定位归属规则 | 同父下 `line` 升序取「最后一个 `line ≤ revealLine`」；早于首行不选中 | 大纲节点只有起始行，区间启发式够用；无结束行契约可用 | 为 outline 增结束行（DSL 无块结束标记，解析器需大改，收益不匹配） | `DesignStructureNav.tsx` |
| D10 | 分栏默认档 | 均分 50/50（用户 2026-11-05 确认）；预设：编辑器优先 60/40、视口优先 40/60 | 与现状连续，老用户零感知 | 视口优先为默认（首次进入改变习惯） | `DesignEditorPage.tsx` |
| D11 | 视图定向术语 | 主视 / 俯视 / 仰视 / 左视 / 右视 / 后视 / 等轴测（机械制图惯例，与既有三视图导出语言一致） | 需求要求结合机械结构设计最佳实践；中文用户群 | CAD 英文方位（Front/Top/…）或 ViewCube 数字方位（与工程图语言割裂） | `PreviewCanvas.tsx` |
| D12 | 管理页组织 | `folder` 分组（空 → 「未分组」置底）+ `kind` Segmented 筛选（全部 / 零件 / 装配） | 0086 既有字段零后端；对齐 CAD 文件库「目录 + 类型过滤」惯例 | 目录树左栏（管理页体量小，树形过重） | `DesignsPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：改参反馈闭环从「点开抽屉 → 改 → 看」缩短为常驻即时；视口操作达到 CAD 基线（定向 / fit / 网格）；模型统计与单位可见；树 / 代码 / 视口形成三向联动（树↔代码双向 + 树→视口高亮）。
- **负向**：`DesignEditorPage` 重构面较大（布局骨架 + 面板迁移），既有单测 / e2e 断言需同步迁移；IR v5 后旧快照联动降级（§4#2）；布尔块内高亮粒度为整块（§4#1）。
- **风险与缓解**：splitter 的 Chrome 81 兼容（PointerEvent Chrome 55+ 已覆盖，e2e 冒烟锁定）；antd Tree `scrollTo` 虚拟滚动定位（antd 版本已带，前端单测覆盖）；高亮与编译竞态（§4#5 明确不补高亮）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | SolidWorks | Fusion 360 / Onshape | OpenSCAD | 本设计 |
|---|---|---|---|---|
| 结构树导航 | FeatureManager 左树 | Browser 左树 | 无树 | 侧栏装配树（0084）+ 双向定位闭环（C1，D9） |
| 视口比例 | 可拖 splitter | 可拖 | 固定（设置内调） | 拖拽 + 三档预设（C2，D3/D10） |
| 参数面板 | PropertyManager 常驻 | 参数表常驻 | 右侧面板 | 预览栏底部常驻 Tabs（C5，D2） |
| 视图控制 | 视图工具条 + Orientation | ViewCube | viewall 工具条 | 悬浮工具条七向定向（C3，D4/D11） |
| 状态可见 | 状态栏（单位 / 坐标） | 状态栏 | 状态栏 / 控制台 | 视口状态条（C4，D5） |
| 选中联动 | 树↔视口双向高亮 | 双向 | 无 | 树→视口 emissive 高亮（C7，D7/D8） |

来源：主流机械 CAD 工具界面惯例（SolidWorks / Fusion 360 / Onshape / OpenSCAD 官方文档与通用交互范式）；「机械结构设计的最佳实践」为用户需求原话口径。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| DSL 语法 / 零依赖 / 零求值 | 结构 DSL 与前端渲染链路 | 本 ADR 不改语法与渲染管线（I1） | ADR 0079 |
| outline 同源产出 | `emit_program` 单次编译 | v5 只在既有结构上回填 `node_index`（D7） | ADR 0083（本 ADR 增量演进） |
| 侧栏形态（240/60、懒加载、只读） | `DesignStructureNav` / `MainLayout` | 信息架构不动，只补选中态与反向定位（C1） | ADR 0084 |
| 文件库字段（`folder` / `kind` / IR v4） | `design_design` / `compiled` | C8 复用既有字段零后端；IR v4→v5 增量演进 | ADR 0086 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/PreviewCanvas.tsx`、`frontend/src/pages/design/DesignMoreMenu.tsx`、`frontend/src/pages/design/viewOrient.ts`、`frontend/src/index.css` | `frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/src/pages/design/DesignMoreMenu.test.tsx`、`frontend/src/pages/design/viewOrient.test.ts`、`frontend/tests/e2e/critical/design-editor-layout.spec.ts`、`frontend/tests/e2e/critical/design-3d-preview.spec.ts` | 见 CHANGELOG |
| P1 | 已落地 | `frontend/src/pages/design/DesignParamsPanel.tsx`、`frontend/src/pages/design/DesignConstraintsPanel.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designOutline.ts` | `frontend/src/pages/design/DesignStructureNav.test.tsx`、`frontend/src/pages/design/DesignsPage.test.tsx`、`frontend/src/pages/design/designOutline.test.ts` | 见 CHANGELOG |
| P2 | 已落地 | `src/cndb/plugins/design/services/dsl/compile.py`、`frontend/src/api/design.ts`、`frontend/src/pages/design/PreviewCanvas.tsx` | `tests/test_design_dsl.py`、`tests/test_design_api.py`、`frontend/tests/e2e/critical/design-tree-viewport-linkage.spec.ts` | 见 CHANGELOG |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：全期落地（P0 / P1 / P2 完成，`Status: Implemented`）
- 已完成：splitter + 三档预设 + 持久化；视口悬浮工具条（七向定向 / fit / 网格开关）+ 状态条；工具栏单行 + 「更多」收纳；参数｜约束常驻可折叠面板；侧栏双向定位闭环（选中态 + `?line=` 反选 + 祖先展开 + `scrollTo`）；管理页目录分组 + 类型筛选；IR v5 `node_index`（含布尔块共享、use 模板平移）与树→视口高亮渐隐
- 下一步：无（需求关闭）。若要再演进：① 大纲节点结束行（D9 启发式换精确区间，需解析器支持块结束标记）；② 高亮补 BREP 级面选（当前为 CSG 网格粒度，§4#1）
- 已知坑：① `node_index` 语义是「首个所属顶层 `nodes` 下标」——布尔块内全部零件共享块下标，高亮粒度即整块；② use 实例的子树行号属于被引用文件，反向定位必须按 `file_id` 过滤（`resolveOutlinePath` 已实现）；③ 静态单 mesh 合并（ADR 0086 C9）后 `nodeGroups` 被清空，高亮因此改为「按需求值单节点 + 叠加 emissive 副本」，不要退回遍历 `nodeGroups` 的做法；④ 同一节点重复点击不改变 `?line=`，高亮不会重触发（§4#5 的「再次点击可重触发」需先换行号）；⑤ shell 若被注入 `LD_LIBRARY_PATH` 会让 sqlite3 缺 `deserialize`，后端测试卡死在 import 阶段（先 `unset` 再跑）
- 最近一次全绿：`make flow`（含前端 3008 例 vitest、后端 244 例 design 测试）
