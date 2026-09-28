# 工作区分页导航（workspace-tab-nav）

## 背景与目标

顶部导航中的「报表」「工作区设置」实为工作区级功能（挂在 `/w/:wid/` 下），与主页、帮助、用户菜单等应用级功能不同层，混排易混淆。将工作区级导航移入 Content 区域顶部，改为分页导航（antd Tabs），顶部导航仅保留应用级功能。

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

### WorkspaceSettingsPage

- 移除面包屑、标题行与返回按钮（tab 已承担导航职责），仅保留内容卡片（`WorkspaceSettingsContent`）；同步移除 `useNavigate`、workspace 详情 `useQuery` 等不再使用的依赖。

### TablesList（数据资产页）

- 页头「工作区设置」按钮（`workspace-settings-link`）删除——tab 导航常驻后为冗余入口。

## 数据模型

无后端改动，零迁移；不新增路由与 API。

## 算法与流程

- tab 激活判定为纯 pathname 字符串包含匹配（与原顶部按钮 `location.includes` 判定一致），不解析路由参数。
- 跨 tab 导航沿用 react-router `navigate`，URL 可分享、可刷新、可回退。

## 异常处理

- 无 `wid` 时 tab 导航不渲染，不存在「tab 点击后 wid 为空」的路径；`onChange` 闭包捕获的 `wid` 由渲染条件保证非空。
- `/w/:wid` 裸路径仍由既有 `<Navigate to="tables">` 重定向，激活「数据资产」。

## 依赖项描述

- 被依赖：`WorkspaceSettingsContent`（设置内容）、antd `Tabs` 组件、主题变量 `--cn-bg-container` / `--cn-border`。
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
