# 面向初级用户的界面引导与帮助体系改进计划

## Summary

为 cndb（React 18 + AntD 5 表格数据库应用）建立面向初级用户的三层帮助体系：

1. **交互式新手引导（Onboarding Tour）**：引入 driver.js，首次使用时分步高亮讲解核心功能，可跳过、可重放；
2. **应用内帮助中心**：顶部帮助按钮打开 Drawer，内置分主题帮助文档（快速上手/视图类型/导入导出/权限角色/常见问题）；
3. **全站 Tooltip 与说明文字系统化**：补齐图标按钮 Tooltip、升级关键操作说明、统一空状态引导、表单对话框内嵌 HelpTip。

## Current State Analysis（现状勘察）

### 项目形态
- 前端：`frontend/src`，React 18 + AntD 5.29 + zustand + React Query + React Router 6，Vite 构建
- 文案：硬编码中文（无 i18n 库），antd locale 已配 `zh_CN`（[ThemeProvider.tsx](file:///F:/Dev/cndb/frontend/src/theme/ThemeProvider.tsx#L56)）
- 主题：5 套主题，颜色统一走 `var(--cn-*)` CSS 变量（index.css / theme/）
- 布局：[MainLayout.tsx](file:///F:/Dev/cndb/frontend/src/layouts/MainLayout.tsx) = Header（工作区下拉/报表/工作区设置/管理台/用户菜单）+ Sider（表搜索/数据表列表）+ Content（Outlet）

### 页面清单
| 路由 | 页面 | 说明 |
|---|---|---|
| `/w` | WorkspaceList | 工作区卡片列表 |
| `/w/:wid/tables` | TablesList | 表列表（新建/导入） |
| `/w/:wid/tables/:tid` | GridPage | 核心数据表格（grid/kanban/calendar/gallery/gantt/wbs 多视图） |
| `/w/:wid/reports` | ReportsPage | 报告模板 |
| `/w/:wid/settings` | WorkspaceSettingsPage | 工作区设置 |
| `/admin` | AdminPanel | 系统管理台 |
| `/login` `/register` | LoginPage/RegisterPage | 认证 |
| `/public/form|share/:slug` | PublicFormPage/PublicSharePage | 公开分享 |

### 引导/帮助现状与缺口
- **无新手引导、无帮助中心**：全站无 Onboarding、无帮助入口；唯一帮助内容是报告编辑器的 SyntaxHelpPanel（报告语法场景）
- **Tooltip 约 38 处**，但多为 1~5 字功能名（"新建视图""打开""更多操作"），缺乏"怎么用/为什么"；存在只有图标无 Tooltip 的按钮需逐站补齐
- **空状态参差**：TablesList 已有较好引导（"还没有表——点击右侧新建表…"），但 MainLayout 侧边栏仅"暂无表"无引导（[MainLayout.tsx#L194](file:///F:/Dev/cndb/frontend/src/layouts/MainLayout.tsx#L194)），GridPage 表格无行数据空状态无引导，部分 Empty 无动作按钮
- **表单/对话框缺说明**：字段管理器（FieldManager）、视图配置（ViewConfigDialog）、工作区设置（可见性/角色）等专业概念无内嵌解释
- **依赖现状**：package.json 无任何引导库（driver.js/intro.js 均未引入）
- **测试体系**：vitest（单元+组件）+ Playwright E2E（smoke/critical 分目录）；门禁 `make check` = gitkeep + lint + typecheck + frontend-check + cov

## Proposed Changes

### 新增依赖
- `driver.js`（MIT，~20KB gzip，零依赖）——用户已确认引入。安装：`pnpm add driver.js`（frontend/ 下）

### 新增文件

#### 1. `frontend/src/components/HelpTip.tsx`
统一"问号图标 + 说明"组件（全站复用）：
- Props：`title: ReactNode`（Tooltip 短文案）、可选 `content: ReactNode`（Popover 展开长说明）、`placement`
- 无 content 时渲染 `Tooltip + QuestionCircleOutlined`；有 content 时渲染 `Popover`，图标尺寸 14px、颜色 `var(--cn-text-muted)`
- 用于表单 label 旁、设置项旁、专业概念旁

#### 2. `frontend/src/components/HelpCenterDrawer.tsx`
帮助中心抽屉（160px 宽锚点导航 + 内容区，`placement="right"`，宽 560px）：
- 内容主题（纯静态 JSX 数据驱动，定义在同目录 `helpContent.tsx` 便于拆分）：
  1. 快速上手：工作区→建表→录入→视图→分享 主链路 5 步图解（纯文字步骤条）
  2. 视图类型说明：6 种视图各自的适用场景与专属配置（分组字段/开始字段等）
  3. 数据导入导出：CSV/XLSX/JSON 导入流程、upsert 匹配键概念、字段类型推断规则摘要
  4. 权限与角色：OWNER/ADMIN/EDITOR/VIEWER 权限矩阵表
  5. 字段类型参考：14 种字段类型一句话说明
  6. 常见问题：删除恢复（回收站）、筛选排序保存位置、公开分享机制等
- 底部操作区：「重新播放新手引导」按钮（调 tourStore.startTour()）
- 主题适配：全部用 `var(--cn-*)` 变量

#### 3. `frontend/src/components/onboarding/onboardingSteps.ts`
引导步骤定义（**纯数据 + 纯函数**，便于单测）：
- 每步：`element`（CSS 选择器）、`popover`（title/description）、可选 `disableActivePage`（该步所在的页面路径）
- 步骤草案（在 GridPage 触发的单一 tour，覆盖 MainLayout 同屏元素）：
  1. 欢迎（无目标，居中 modal）：一句话介绍 cndb
  2. 工作区下拉（Header `.ws-switch-btn`，需在实现时给元素补 data-testid）
  3. 侧边栏数据表列表（Sider）
  4. 新增一行按钮（GridPage 工具栏）
  5. 视图切换 Segmented（grid/kanban/calendar…）
  6. 表设置按钮（字段/视图/权限）
  7. 导入导出按钮
  8. 帮助按钮（收尾：告诉用户随时点这里看文档）
- 空表兜底：目标元素不存在时 driver.js 自动降级为居中展示（官方行为），description 文案写成"若无 X，请先创建"式条件表述
- 提供 `buildSteps(ctx)` 工厂函数与 `TOUR_STORAGE_KEY = 'cndb_onboarding_done_v1'`

#### 4. `frontend/src/components/onboarding/OnboardingTour.tsx`
driver.js 封装组件：
- 挂载在 MainLayout；订阅 tourStore，`shouldStart` 时实例化 `driver({ steps, showProgress: true, allowClose: true, popoverClass: 'cn-driver-theme' })`
- 完成或跳过时写 localStorage + tourStore
- 移动端（`useResponsive().isMobile`）降级：跳过 tour 仅标记 done（引导设计基于桌面布局）

#### 5. `frontend/src/store/onboarding.ts`
zustand persist store（沿用现有 store 模式，index.ts barrel 导出）：
- 状态：`tourDone: boolean`、`tourRequested: boolean`（帮助中心重放信号）
- action：`markTourDone()`、`requestTour()`、`clearTourRequest()`

#### 6. 样式：`frontend/src/index.css` 追加 `.cn-driver-*`
driver.js 弹窗主题适配：背景/文字/边框/主色全部映射 `var(--cn-*)`，保证 5 套主题（含暗色）下可读；遮罩透明度用默认

### 修改文件

#### A. 帮助入口 — `frontend/src/layouts/MainLayout.tsx`
- Header 右侧（管理台按钮前）加帮助按钮：`QuestionCircleOutlined` + Tooltip"帮助中心与新手引导"，点开 HelpCenterDrawer；移动端仅图标
- 用户菜单（userMenuItems）加「帮助中心」项
- 挂载 OnboardingTour；登录后首次进入（无 tourDone）自动触发
- Sider 空状态「暂无表」改为引导文案 + 建表跳转（`useNavigate` 到 TablesList 并锚定新建按钮，无 wid 时跳 `/w`）
- 涉及元素补 `data-testid`：工作区下拉按钮 `ws-switch-btn`、帮助按钮 `help-btn`（供 tour 与 e2e 定位）

#### B. Tooltip 补齐与升级（全站扫描，改动文件）
- **GridPage.tsx**：升级现有 Tooltip（"新增一行"→补说明"在表格末尾添加空行，回车快速保存"；"表设置"保留；筛选/显示模式按钮补一句效果说明）；`modeButtons` 的 tooltip（[viewModes](file:///F:/Dev/cndb/frontend/src/pages/grid)）统一为"视图名 + 适用场景"句式
- **TablesList.tsx**："打开""更多操作""显式授予成员"等升级为完整句
- **MainLayout.tsx / AdminPanel / WorkspaceSettingsPage / 各视图组件**：扫描所有 `icon={` 且未包 Tooltip 的 Button，逐一补齐（实现时用 Grep 清单核对，不遗漏）
- 文案规范：格式"做什么 + 产生什么结果"，≤2 行；不用句号结尾短语保持一致

#### C. 空状态引导统一
- **GridPage.tsx**：表格无行数据时，Empty description 改为引导（"这张表还没有数据。点击右上角「新增一行」，或通过「导入数据」批量导入"），locale.emptyText 内嵌「新增一行」快捷按钮
- **ReportsPage.tsx**：现有"暂无模板"加按钮直达新建
- **WorkspaceSettingsContent.tsx**：成员管理"暂无成员"加「添加成员」按钮
- **FieldManager / TableSettingsModal**：现有空状态文案已有引导，统一措辞即可
- **CalendarView/KanbanView/GalleryView/GanttView**：各自 Empty 补一句"如何让内容出现"的条件说明（如日历：需日期字段）

#### D. 表单与对话框内嵌说明（HelpTip 应用点）
- **FieldManager.tsx**：字段类型 Select 的每个 option 附一句话说明（options 文案拼接或 option 描述行）；「唯一约束」「默认值」「允许为空」等 Checkbox/Form label 加 HelpTip
- **ViewConfigDialog.tsx**：筛选规则/排序规则区块标题加 HelpTip（"规则保存在当前视图中，切换视图互不影响"）
- **CreateEditViewForm.tsx**：看板 group_field、日历 start_field、画廊 title/image_field 等 label 加 HelpTip（说明该字段决定什么）
- **ImportExportDialog.tsx**：upsert 模式与匹配键概念加 HelpTip + 参考列推荐已有 Tooltip 保留
- **WorkspaceSettingsContent.tsx**：可见性三选项（public/member-only/private）radio 每项加说明副文案；成员角色 Select 每项加一句话说明
- **PermissionEditor.tsx**：角色说明同上对齐

### 测试计划

- **单元/组件测试（vitest）**：
  - `HelpTip.test.tsx`：Tooltip/Popover 两形态渲染、placement 透传
  - `onboardingSteps.test.ts`：步骤结构完整性（每步有 popover.title、选择器以 data-testid 或语义标签锚定）、`TOUR_STORAGE_KEY` 常量
  - `OnboardingTour.test.tsx`：mock driver.js，断言 shouldStart 时实例化、markTourDone 写入、isMobile 跳过逻辑
  - `onboarding.test.ts`（store）：状态流转
  - `HelpCenterDrawer.test.tsx`：抽屉打开、主题锚点渲染、重放按钮触发 requestTour
- **E2E（Playwright）**：`tests/e2e/smoke/` 加 1 条用例：登录 → 断言 tour 自动弹出（首次）→ 关闭 → localStorage 置 done → 刷新不再弹出；现有 E2E 用例的 setup（auth.setup.ts）预置 `cndb_onboarding_done_v1` 避免引导干扰存量用例
- **门禁**：`make check` 全绿（gitkeep + lint + typecheck + frontend-check + cov）；新组件测试保持 vitest 覆盖率水位只升不降规则

## Assumptions & Decisions

1. **driver.js 引入已获授权**（用户在澄清问题中明确选择"交互式引导（driver.js）"）；除此之外不新增任何依赖
2. **单 Tour 策略**：引导只在进入 GridPage 后触发（MainLayout 同屏可高亮 Header/Sider/GridPage 全部核心元素），不做跨页面多段 tour，复杂度可控
3. **触发条件**：登录用户 + localStorage 无 done 标记 + 非移动端；不区分按用户（本地标记粒度足够初级用户场景）
4. **帮助内容为静态内置 JSX**（非远程文档），随代码版本维护，离线可用；不做 i18n 抽象（项目现状全硬编码中文，保持一致）
5. **不改任何后端代码**；本轮纯前端改动，不触碰 `_ui.py` 自动生成文件
6. E2E 存量用例通过 setup 预置 done 标记，避免 tour 弹层遮挡造成用例失败

## Verification

1. `pnpm typecheck && pnpm lint`（frontend/ 下）通过
2. `pnpm test` 全部通过，`pnpm test:coverage` 水位不降
3. `make check` 全绿（项目根）
4. 手工验证清单（dev server）：
   - 清空 localStorage 登录 → tour 自动出现，步骤可前进/后退/跳过，完成后刷新不再弹出
   - 5 套主题（含暗色）下 tour 弹窗与帮助中心可读
   - 帮助中心 6 个主题内容完整、锚点跳转正常、重放按钮有效
   - 全站图标按钮 hover 均有 Tooltip；GridPage/TablesList 空状态有引导动作
   - FieldManager/ViewConfigDialog/工作区设置中 HelpTip 正常
   - 移动端宽度下 tour 不弹出、帮助入口仍可达
5. 提交：分维度提交（路径限定 `git commit -- <paths>`），遵循 `类型: 描述` 中文规范；`.trae/` 不入库；推送用 `make push`
