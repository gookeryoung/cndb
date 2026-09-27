# 用户个人资料设置 Spec

> Status: ALIGNED
> Author: user
> Last updated: 2026-09-27

## Background
后端 `User` 模型（src/cndb/plugins/accounts/models.py）已含 `email`/`nickname` 字段，注册与 `/auth/me` 已支持读写展示。个人更新资料接口已上线。本文件同时记录个人设置 Modal（用户资料/主题/表格）当前生效的 UI 设计。

显示模式原为 Grid 视图栏独立 Dialog（TableSettingsDialog，草稿+保存模式），因其为浏览器级全局偏好（与视图级 view_options 语义混淆）而收编进个人设置「表格」页签，与操作风格合并管理；视图栏齿轮按钮保留为快捷入口，点击直达该页签。

## In scope
- [x] 更新当前用户资料接口（昵称、邮箱）：`PUT /v1/accounts/me`。
- [x] 个人设置 Modal：用户资料页签编辑昵称、邮箱并保存。
- [x] 右上角用户区显示昵称（空昵称回退账号名）。
- [x] 主题页签：配色节（10 主题）+ 字体节（字号档位 / 全局加粗）。
- [x] 主题页签底部「恢复默认」：一键重置配色与字体（modern / standard / 不加粗）。
- [x] 「操作风格」页签扩为「表格」页签：并入显示模式（间距/每页行数），分「显示模式」「操作风格」两节，全部即时生效。
- [x] 移除边框/表头/斑马纹三项开关：表头为功能性必需固定启用，边框/斑马纹为纯视觉装饰不提供配置；`TableSettings` 缩为 4 项。
- [x] 删除 TableSettingsDialog，测试迁移至 SettingsModal 层。
- [x] Grid 视图栏齿轮按钮改为快捷入口：打开个人设置并定位「表格」页签。

## Out of scope
- 修改密码、头像上传、手机号等其他资料项。
- 邮箱验证流程（仅格式与唯一性校验）。
- 自定义字体族（仅字号与字重）。

## Assumptions
- 更新接口挂在 accounts 插件路由下，复用 `get_current_user` 鉴权依赖。
- 邮箱需全库唯一，昵称允许为空字符串时不强制唯一。

## 接口定义

### 后端
- `PUT /v1/accounts/me`，请求体 `UserUpdateRequest`（nickname/email 可选，Pydantic v2 校验）；服务层做邮箱唯一性检查，路由层映射 400。

### 前端类型契约（src/api/types.ts）
- `UserResponse`：`nickname?: string`、`email?: string | null`；`ProfileUpdateRequest`：`{ nickname?: string; email?: string }`。

### 前端主题接口（src/theme/theme.ts / ThemeProvider.tsx）
- `DEFAULT_THEME_MODE = 'modern'`：默认主题单一来源，`loadThemeMode` 兜底与主题页「恢复默认」共用。
- `FONT_SCALES = ['small', 'standard', 'large', 'huge']`，`FONT_SCALE_META[s].px` 分别为 12/14/16/18。
- `FontSettings = { scale: FontScale; bold: boolean }`，默认 `{ scale: 'standard', bold: false }`。
- `loadFontSettings()`：解析 localStorage `cndb_font`（JSON），非法档位回退 standard，`bold` 仅接受 `true`，JSON 损坏/读写异常回退默认。
- `saveFontSettings(settings)` 写回 `cndb_font`。
- `useTheme()` 上下文新增：`font: FontSettings`、`setFontScale(s)`、`setFontBold(b)`，setter 内即时持久化。
- `getThemeConfig(mode)` 在原主题配置上注入 `components.Segmented`：`itemSelectedBg = colorPrimary`（激活滑块填充主题色）、`itemSelectedColor = SEGMENTED_ON_PRIMARY[mode]`（逐主题反色文字，高亮度主题色 github-dark/midnight/oled 用深字保证可读），返回合并后的新对象；配套删除 index.css 中深色主题 `.ant-segmented-item-selected` 文字色的 CSS 覆盖，避免 `!important` 压过 token。

### 前端 UI store（src/store/ui.ts）
- `useUiStore`：`settingsOpen: boolean`、`settingsTab: SettingsTab`、`openSettings(tab?)`、`closeSettings()`。
- `SettingsTab = 'profile' | 'theme' | 'table'`；`openSettings()` 缺省定位用户资料。
- 用途：跨层级打开 MainLayout 挂载的 SettingsModal（Grid 视图栏齿轮 → `openSettings('table')`）。

### 前端视图栏契约（src/pages/grid/gridViewBar.tsx）
- `GridViewBarProps.onOpenTableSettings: () => void`（替代原 `onOpenDisplaySettings`）；齿轮按钮 data-testid 仍为 `display-settings-btn`。

## 数据模型 / 持久化
| 键 | 内容 | 说明 |
|---|---|---|
| `cndb_theme` | 主题 mode 字符串 | 既有行为，不变 |
| `cndb_font` | `{"scale": FontScale, "bold": boolean}` | 字体设置，JSON |
| `cndb_auth` | 既有 | 不变 |
| `cndb_table_settings` | `TableSettings` 全 4 项（显示 2 + 操作 2） | 键不变；历史持久化中多余的 bordered/showHeader/striped 字段因 store 合并语义自然忽略，零迁移 |

## 算法与流程
- 右上角展示：`user?.nickname || user?.username || ''`；用户菜单首项仍展示账号名。
- 字体应用（ThemeProvider）：
  - body 内联样式：`fontSize = FONT_SCALE_META[scale].px + 'px'`；加粗时 `fontWeight = '600'`，否则清空。
  - antd ConfigProvider：`token.fontSize` 取档位 px；加粗时叠加 `fontWeightStrong: 700`。token 与主题配置合并（`...baseConfig.token`）而非整体替换，保证主题配色 token 不丢失。
- 用户资料表单：每次打开/用户变化时以 auth store 最新值重置（含只读 username）；保存仅提交 nickname/email，成功后 `refresh()` 同步 store。
- 主题页「恢复默认」：依次 `setMode(DEFAULT_THEME_MODE)`、`setFontScale(DEFAULT_FONT_SETTINGS.scale)`、`setFontBold(DEFAULT_FONT_SETTINGS.bold)`，复用既有 setter 的即时持久化，不新增重置接口；完成后提示「已恢复主题设置为默认值」。
- 表格页签即时生效：所有项变更直接 `updateSettings(patch)` 写入 zustand persist，无草稿/保存按钮；底部「恢复默认」调用 `resetSettings()` 重置全 4 项。
- 表格固定外观：表头固定启用（antd Table 默认），边框固定关闭、无斑马纹；`GridDisplaySettings` 仅含 density，`GridTableSection` 不再透传 bordered/showHeader/striped。
- 每页行数联动：GridPage 订阅 `settings.defaultPageSize`，变更时 `setLimit` + `setOffset(0)`（替代原 Dialog onAfterSave 回调）。
- initialTab 定位：SettingsModal 传 `initialTab` 作 Tabs `defaultActiveKey`，Modal `destroyOnHidden` 每次打开重新挂载生效。

## UI 结构约定
- 个人设置 Modal 三个页签：`用户资料` / `主题` / `表格`；默认激活用户资料（`initialTab` 可覆盖）。
- 用户资料页：无重复节标题；用户名（disabled Input）/ 昵称 / 邮箱同行 flex 紧凑排布（flex 比例 1 / 1 / 1.3），用户名列底部附提示「注册后不可修改」，保存按钮在下方。
- 主题页：第一节标题「配色」（10 主题 Radio 按钮组 + 卡片网格）；第二节标题「字体」（字号 Select 4 档 + 全局加粗 Switch）；底部「恢复默认」按钮。
- 表格页：第一节标题「显示模式」（间距 Select + 每页行数 Select 同行，副注说明间距影响全部视图的卡片密度）；第二节标题「操作风格」（新增行默认位置 Select + 自动填充锁定 Switch）；底部「恢复默认」按钮。
- 提示文字统一样式：全部用 `Text type="secondary"` + `fontSize: 12`（antd colorTextSecondary token），不硬编码颜色，不用 Form.Item extra（其默认色 colorTextDescription 偏浅，与提示体系不一致）；节级提示跟节标题同行（marginLeft 8），控件级说明独立成行（marginTop 4、display block）与控件左对齐。

## Edge cases & risks
| Category | Notes |
|---|---|
| Boundary | 邮箱格式非法/已被占用 -> 400 带明细，前端 message 展示 |
| Failure | 更新前后字段相同 -> 幂等成功 |
| Boundary | localStorage 不可用/JSON 损坏 -> 字体设置回退默认，静默失败 |
| Boundary | 恢复默认同时重置显示 2 项与操作 2 项（同页签全可见，语义一致）；主题页「恢复默认」同时重置配色与字体（同页签全可见，语义一致） |
| Risks | 无 |

## Acceptance criteria
- AC-1 登录用户 PUT 昵称+邮箱 -> 返回 200 且 `/auth/me` 反映新值。
- AC-2 PUT 已被他人占用的邮箱 -> 400 且提示明细。
- AC-3 未登录调用 -> 401。
- AC-4 前端用户资料页可编辑并保存昵称、邮箱，用户名只读，保存后界面展示同步更新。
- AC-5 右上角优先显示昵称，无昵称回退账号名。
- AC-6 主题页字号/加粗变更即时生效（body + antd token）并持久化到 `cndb_font`，重进后保持。
- AC-7 个人设置「表格」页签可即时调整间距/每页行数并持久化到 `cndb_table_settings`，对所有表生效；不再提供边框/表头/斑马纹配置。
- AC-8 每页行数变更后 Grid 分页立即按新值请求（limit 同步、回到第 1 页）。
- AC-9 Grid 视图栏齿轮按钮点击打开个人设置并定位「表格」页签；头像菜单「个人设置」仍默认定位用户资料。
- AC-10 主题页「恢复默认」点击后配色回 modern、字号回 standard、加粗关闭，并即时持久化到 `cndb_theme` / `cndb_font`。
