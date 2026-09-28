# 工作区分页导航（workspace-tab-nav）

## 背景与目标

顶部导航中的「报表」「工作区设置」实为工作区级功能（挂在 `/w/:wid/` 下），与主页、帮助、用户菜单等应用级功能不同层，混排易混淆。将工作区级导航移入 Content 区域顶部，改为分页导航（antd Tabs），顶部导航仅保留应用级功能。tab label 同步显示工作区级数量徽标（数据资产=表数量、报表=报表数量，0 也显示；工作区设置不显示）。

## 导航层级定义

- **应用级（顶部 Header）**：Logo（主页）、工作区切换下拉、帮助、管理台（仅管理员）、用户菜单。不再承载工作区级按钮。
- **工作区级（Content 分页导航）**：三个 tab，路由驱动——
  - `tables`「数据资产」→ `/w/:wid/tables`（含表详情 `/w/:wid/tables/:tid`，激活「数据资产」）
  - `reports`「报表」→ `/w/:wid/reports`
  - `settings`「工作区设置」→ `/w/:wid/settings`

## 接口定义（组件契约）

### MainLayout

- Header 移除「报表」「工作区设置」两个按钮及其 Tooltip 包装；`FileTextOutlined` import 同步移除。
- 布局层级：外层 `Layout`（Header / 下层 Layout）→ 下层 `Layout`（Sider / 右侧 `Layout`（column））→ 右侧 Layout 内依次为 tab 导航条 + `Content`。
- tab 导航条（antd `Tabs`）仅在 `wid` 存在时渲染；无工作区上下文（`/`、`/w`、`/admin`）时不渲染，由侧边栏「请先从顶部选择一个工作区」提示承担引导。
- `activeKey` 由 pathname 计算：含 `/reports` → `reports`；含 `/settings` → `settings`；其余（tables / tables/:tid）→ `tables`。
- `onChange(key)` 统一 `navigate(/w/:wid/{key})`；`key` 取值即路由段，无额外映射表。
- tab 导航条样式：背景 `var(--cn-bg-container)`、底边框 `1px solid var(--cn-border)`、左右内边距 16px，通过专用 CSS 类 `cn-ws-tabs` 实现（样式走 `var(--cn-*)` 主题变量，禁止硬编码颜色）。
- `Content` 保留 `key={location}` + `cn-page-enter` 重挂载语义与 Suspense 骨架；tab 导航条位于 Content 之外，跨页切换不重挂载。

### tab 数量徽标

- 「数据资产」label 渲染当前工作区表数量：取 MainLayout 既有 `['workspaces', wid, 'tables']` 查询缓存的 `tables.length`，零新增请求；该查询未就绪时不渲染数量。
- 「报表」label 渲染当前工作区报表数量：取既有 `['workspaces']` 查询缓存中当前工作区的 `report_count`（后端列表响应新增字段，与 `table_count` 同事务聚合，见 report-workspace-scope.md），零新增请求。
- 数量为 0 照常显示（「数据资产 0」「报表 0」）；「工作区设置」label 不渲染数量。
- 数量以 `<span className="cn-ws-tab-count">` 内嵌于 label 文本之后，样式走 `var(--cn-*)` 专用类（次级文字色），禁止硬编码颜色。
- accessible name 随之变化（如「数据资产 3」）：MainLayout 测试的 tab 定位从精确 `name` 匹配改为 `/数据资产/`、`/报表/` 正则匹配；激活态断言仍走 `.ant-tabs-tab-active` 容器。
- 报表新建/删除后 ReportsPage 追加 invalidate `['workspaces']`，徽标数量同步刷新。

### WorkspaceSettingsPage

- 移除面包屑、标题行与返回按钮（tab 已承担导航职责），仅保留内容卡片（`WorkspaceSettingsContent`）；同步移除 `useNavigate`、workspace 详情 `useQuery` 等不再使用的依赖。

### TablesList（数据资产页）

- 页头「工作区设置」按钮（`workspace-settings-link`）删除——tab 导航常驻后为冗余入口。

## 数据模型

tab 导航自身无新增路由与 API；徽标数量依赖报表归属改造（见 report-workspace-scope.md）：`reports_template` 新增 `workspace_id` 列，`GET /v1/workspaces` 列表响应新增 `report_count` 字段。

## 算法与流程

- tab 激活判定为纯 pathname 字符串包含匹配（与原顶部按钮 `location.includes` 判定一致），不解析路由参数。
- 跨 tab 导航沿用 react-router `navigate`，URL 可分享、可刷新、可回退。
- 徽标数量全部来自既有 React Query 缓存聚合，不新增请求、不新增轮询。

## 异常处理

- 无 `wid` 时 tab 导航不渲染，不存在「tab 点击后 wid 为空」的路径；`onChange` 闭包捕获的 `wid` 由渲染条件保证非空。
- `/w/:wid` 裸路径仍由既有 `<Navigate to="tables">` 重定向，激活「数据资产」。
- `['workspaces', wid, 'tables']` 缓存未就绪时「数据资产」仅显示文字不显示数量；`report_count` 缺失（旧缓存结构）时「报表」同理，不渲染占位。

## 依赖项描述

- 被依赖：`WorkspaceSettingsContent`（设置内容）、antd `Tabs` 组件、主题变量 `--cn-bg-container` / `--cn-border`。
- 徽标依赖：`GET /v1/workspaces` 响应的 `report_count` 字段与工作区表列表长度（均为既有 React Query 缓存）。
- 文案联动：新手引导（onboardingSteps.ts）与帮助中心（helpContent.tsx）中「顶部报表/工作区设置按钮」的描述同步改为内容区分页导航表述。

## 验收清单

- [x] 顶部 Header 不再出现「报表」「工作区设置」按钮。
- [x] 有工作区上下文时，Content 顶部渲染「数据资产 / 报表 / 工作区设置」三 tab，激活态随路由变化。
- [x] 点击 tab 正确导航；表详情页激活「数据资产」。
- [x] 无工作区上下文（/、/w、/admin）时不渲染 tab 导航。
- [x] 工作区设置页无面包屑/返回按钮，内容正常渲染。
- [x] 数据资产页头无重复「工作区设置」按钮。
- [x] 新手引导与帮助中心文案与实际导航一致。
- [x] 前端测试全绿（MainLayout / WorkspaceSettingsPage / TablesList 相关断言同步更新）。
- [x] 「数据资产」「报表」tab label 显示数量，数量为 0 也显示；「工作区设置」不显示；查询未就绪/字段缺失时不渲染数量。
- [x] 报表新建/删除后 tab 徽标数量同步刷新（ReportsPage 三个 mutation invalidate `['workspaces']`）。
