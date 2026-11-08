# 需求卡片：页面状态维持（导航形态 / 筛选 / 滚动位置记忆）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0124
- 来源 / 提出人：用户（2026-11-08 会话）
- 日期：2026-11-08
- 关联 ADR：无（S1，跨模块 UI 状态，无数据 / 权限 / 对外契约变化）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对用户当前页面的状态维持给出建议项，如侧边栏的收起应当记忆，而不是刷新后又变回去了。

会话内补充确认（2026-11-08）：

> 按此推进到结束。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 侧边栏的收起应当记忆，而不是刷新后又变回去了 | 主侧栏折叠态用 localStorage 持久化；点击折叠 / 展开即写入，刷新后恢复 | `frontend/src/layouts/MainLayout.tsx` | `MainLayout.test.tsx` 预置 localStorage 恢复 + 点击写回 |
| C2 | 页面状态维持 | 管理台侧栏折叠态用 localStorage 持久化，刷新后保持图标栏 / 展开态 | `frontend/src/pages/admin/AdminPanel.tsx` | `AdminPanel.test.tsx` 点击写入 + 预置恢复 |
| C3 | 页面状态维持 | 文档树展开态按工作区、会话级持久化（`expanded` + `collapsedAll`），刷新 / 返回不丢；写入时剪除已删除文件夹 | `frontend/src/layouts/MainLayout.tsx` | `MainLayout.test.tsx` 预置收起态 + 点击写回 |
| C4 | 刷新后又变回去了 | **2026-11-08 更新（需求方口径调整）**：工作区设置页侧栏固定为设置分项（基本设置 / 权限 / 生命周期 / 统计信息），不再沿用最近一次文档 / 设计模块侧栏；原 `last_module_sider` 会话持久化随之下线。分项选中态改由 URL `?section=` 承载，可直接分享 / 刷新保持 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/workspace/WorkspaceSettingsPage.tsx` | `MainLayout.test.tsx` 侧栏分项渲染与 `?section=` 选中态；`WorkspaceSettingsPage.test.tsx` 分项渲染 |
| C5 | 页面状态维持 | 数据表侧栏搜索词按工作区、会话级记忆 | `frontend/src/layouts/MainLayout.tsx` | `MainLayout.test.tsx` 预置搜索词后断言输入框值 |
| C6 | 页面状态维持 | 文档标题过滤关键词会话级记忆（原注释明确不写 localStorage，保持该口径） | `frontend/src/pages/documents/docTreeSort.ts` | `docTreeSort.test.ts` 写入 sessionStorage + 模块重载恢复 |
| C7 | 页面状态维持 | 设计侧栏筛选（产品搜索 / 类型 / 模块库可见范围等）按工作区、会话级记忆 | `frontend/src/pages/design/DesignStructureNav.tsx` | `DesignStructureNav.test.tsx` 预置筛选后断言搜索框与列表收窄 |
| C8 | 页面状态维持 | 内容区滚动位置按 pathname 会话级记忆，返回 / 刷新同页后恢复；最多保留 50 条 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/layouts/scrollMemory.ts` | `scrollMemory.test.ts` 读写 / 清零 / 损坏 / 上限 |
| C9 | 通用口径 | 存储分档：用户偏好用 localStorage，会话上下文用 sessionStorage，可分享导航态继续走 URL；storage 不可用或数据损坏时静默回落，不阻塞渲染 | `frontend/src/utils/persistedState.ts` | `persistedState.test.ts` 回退 / 损坏 / local 与 session 隔离 / key 变化重读 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 主侧栏 / 管理台侧栏折叠均为组件内 `useState` | `frontend/src/layouts/MainLayout.tsx:146`、`frontend/src/pages/admin/AdminPanel.tsx:124` | C1 / C2 主缺口 |
| 2 | 文档树展开态为 `useState`，展开全部仅记录一级文件夹 | `frontend/src/layouts/MainLayout.tsx:226-239` | C3，保持既有展开全部口径 |
| 3 | 设置页来源侧栏用 `useRef`，刷新即丢失 | `frontend/src/layouts/MainLayout.tsx:468` | C4 |
| 4 | 表搜索词 / 文档标题过滤词仅内存态 | `MainLayout.tsx:243`、`docTreeSort.ts:153-176` | C5 / C6 |
| 5 | 设计侧栏筛选为多个 `useState` | `DesignStructureNav.tsx:92-99` | C7 |
| 6 | 内容区 `key={location}` 重挂载，滚动归零 | `MainLayout.tsx:1033-1042` | C8 |
| 7 | 表格视图 URL 深链与手动切换已写 `?view=`；落地视图不写 URL，刷新由 sessionStorage 快照兜底 | `frontend/src/pages/grid/GridPage.tsx:397-545` | 评估后不改：现有行为已覆盖刷新与分享，避免进入默认视图即改写 URL |
| 8 | 文档编辑器专注模式 | `frontend/src/pages/documents/DocumentEditorPage.tsx:213` | P2 不纳入：全屏依赖用户手势，自动恢复体验突兀 |
| 9 | 顶部页签横向滚动位置 | `frontend/src/layouts/tabScroll.ts` | P2 不纳入：激活页签已有自动滚入可视区，原始位置恢复会与之冲突 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 实施范围：P0 + P1 全部落地，P2 两项经评估不纳入 —— 用户 2026-11-08 确认「按此推进到结束」
- [x] 存储分档：偏好 localStorage / 会话上下文 sessionStorage / 可分享导航态 URL —— 用户确认按建议方案执行

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
