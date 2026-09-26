# 用户个人资料设置 Spec

> Status: ALIGNED
> Author: user
> Last updated: 2026-09-27

## Background
后端 `User` 模型（src/cndb/plugins/accounts/models.py）已含 `email`/`nickname` 字段，注册与 `/auth/me` 已支持读写展示。个人更新资料接口已上线。本文件同时记录个人设置 Modal（用户资料/主题/操作风格）当前生效的 UI 设计。

## In scope
- [x] 更新当前用户资料接口（昵称、邮箱）：`PUT /v1/accounts/me`。
- [x] 个人设置 Modal：用户资料页签编辑昵称、邮箱并保存。
- [x] 右上角用户区显示昵称（空昵称回退账号名）。
- [x] 主题页签：配色节（10 主题）+ 字体节（字号档位 / 全局加粗）。

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
- `FONT_SCALES = ['small', 'standard', 'large', 'huge']`，`FONT_SCALE_META[s].px` 分别为 12/14/16/18。
- `FontSettings = { scale: FontScale; bold: boolean }`，默认 `{ scale: 'standard', bold: false }`。
- `loadFontSettings()`：解析 localStorage `cndb_font`（JSON），非法档位回退 standard，`bold` 仅接受 `true`，JSON 损坏/读写异常回退默认。
- `saveFontSettings(settings)` 写回 `cndb_font`。
- `useTheme()` 上下文新增：`font: FontSettings`、`setFontScale(s)`、`setFontBold(b)`，setter 内即时持久化。
- `getThemeConfig(mode)` 在原主题配置上注入 `components.Segmented`：`itemSelectedBg = colorPrimary`（激活滑块填充主题色）、`itemSelectedColor = SEGMENTED_ON_PRIMARY[mode]`（逐主题反色文字，高亮度主题色 github-dark/midnight/oled 用深字保证可读），返回合并后的新对象；配套删除 index.css 中深色主题 `.ant-segmented-item-selected` 文字色的 CSS 覆盖，避免 `!important` 压过 token。

## 数据模型 / 持久化
| 键 | 内容 | 说明 |
|---|---|---|
| `cndb_theme` | 主题 mode 字符串 | 既有行为，不变 |
| `cndb_font` | `{"scale": FontScale, "bold": boolean}` | 字体设置，JSON |
| `cndb_auth` / `cndb_table_settings` | 既有 | 不变 |

## 算法与流程
- 右上角展示：`user?.nickname || user?.username || ''`；用户菜单首项仍展示账号名。
- 字体应用（ThemeProvider）：
  - body 内联样式：`fontSize = FONT_SCALE_META[scale].px + 'px'`；加粗时 `fontWeight = '600'`，否则清空。
  - antd ConfigProvider：`token.fontSize` 取档位 px；加粗时叠加 `fontWeightStrong: 700`。token 与主题配置合并（`...baseConfig.token`）而非整体替换，保证主题配色 token 不丢失。
- 用户资料表单：每次打开/用户变化时以 auth store 最新值重置（含只读 username）；保存仅提交 nickname/email，成功后 `refresh()` 同步 store。

## UI 结构约定
- 个人设置 Modal 三个页签：`用户资料` / `主题` / `操作风格`；默认激活用户资料。
- 用户资料页：无重复节标题；用户名（disabled Input，extra「注册后不可修改」）/ 昵称 / 邮箱同行 flex 紧凑排布（flex 比例 1 / 1 / 1.3），保存按钮在下方。
- 主题页：第一节标题「配色」（10 主题 Radio 按钮组 + 卡片网格）；第二节标题「字体」（字号 Select 4 档 + 全局加粗 Switch + 自动保存说明）。

## Edge cases & risks
| Category | Notes |
|---|---|
| Boundary | 邮箱格式非法/已被占用 -> 400 带明细，前端 message 展示 |
| Failure | 更新前后字段相同 -> 幂等成功 |
| Boundary | localStorage 不可用/JSON 损坏 -> 字体设置回退默认，静默失败 |
| Risks | 无 |

## Acceptance criteria
- AC-1 登录用户 PUT 昵称+邮箱 -> 返回 200 且 `/auth/me` 反映新值。
- AC-2 PUT 已被他人占用的邮箱 -> 400 且提示明细。
- AC-3 未登录调用 -> 401。
- AC-4 前端用户资料页可编辑并保存昵称、邮箱，用户名只读，保存后界面展示同步更新。
- AC-5 右上角优先显示昵称，无昵称回退账号名。
- AC-6 主题页字号/加粗变更即时生效（body + antd token）并持久化到 `cndb_font`，重进后保持。
