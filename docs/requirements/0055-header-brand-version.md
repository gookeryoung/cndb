# 需求卡片：顶栏品牌字右侧显示应用版本

- 编号：0055（与 ADR `docs/adr/0055-header-brand-version.md` 同号）
- 来源 / 提出人：用户（口头需求）
- 日期：2026-10-28
- 关联 ADR：`docs/adr/0055-header-brand-version.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 主页顶部cndb右侧显示版本小字

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「主页顶部」「cndb 右侧」 | 位置固定在 `MainLayout` 顶栏品牌区（`home-logo`）内、品牌字 `cndb` 的右侧，不放到工作区下拉、右侧用户区或页面内容区 | `frontend/src/layouts/MainLayout.tsx` | 前端单测：版本节点是 `home-logo` 的后代，且位于 `.cn-brand-word` 之后 |
| C2 | 「显示版本」 | 展示**当前运行后端**的 `APP_VERSION`，格式为 `v<app_version>`（如 `v0.4.19`），与管理台 `v{app_version}` 口径一致 | `MainLayout.tsx`、`GET /api/v1/system/about` | 前端单测：msw 返回 `0.3.0` 时文案为 `v0.3.0` |
| C3 | 「显示版本」（数据来源） | 复用既有 `systemApi.about()`（`GET /api/v1/system/about`），不新增后端端点、不新增数据库字段、不在前端硬编码版本 | `frontend/src/api/system.ts`、`src/cndb/core/system_api.py` | 代码评审：无新增路由 / 表 / 常量；单测走既有 msw handler |
| C4 | 「小字」 | 以次要色、小号字（`--cn-text-xs` / `--cn-text-secondary`）呈现，不改变品牌方块与 `cndb` 品牌字尺寸、字重、间距，不抬高顶栏高度 | `frontend/src/index.css`、`MainLayout.tsx` | 前端单测 + 现有 e2e `typography.spec.ts`（`.cn-brand-word` 字体断言）保持通过 |
| C5 | 隐含（加载 / 失败态） | 版本请求未返回、失败或返回空字符串时不渲染该节点：不显示占位、不抛错、不阻塞顶栏导航 | `MainLayout.tsx` | 前端单测：覆盖 about 接口 500 时 `app-version` 不存在且布局仍可操作 |
| C6 | 隐含（移动端） | 移动端（`isMobile`）品牌字本身隐藏，版本小字随品牌字一并隐藏，不在品牌方块右侧单独出现 | `MainLayout.tsx` | 前端单测：移动端 `queryByTestId('app-version')` 为 null |
| C7 | 隐含（可点击性） | 版本小字位于 `home-logo` 内，点击仍触发原有「返回主页」导航；不新增独立交互 | `MainLayout.tsx` | 前端单测 / 代码评审：版本节点无独立 onClick |
| C8 | 隐含（缓存与请求纪律） | 与「关于系统」弹窗共用 `['system-about']` 查询缓存，避免同一信息重复请求；头部展示按非关键信息处理，失败不重试刷屏 | `MainLayout.tsx`、`frontend/src/components/AboutModal.tsx` | 代码评审：queryKey 一致；单测断言失败态静默 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 顶栏品牌区：品牌方块 + 品牌字，桌面端显示、移动端隐藏 | `frontend/src/layouts/MainLayout.tsx:407-422` | C1 / C6 的落点 |
| 2 | 系统基本信息接口（登录即可） | `src/cndb/core/system_api.py:250-264` | C2 / C3 的数据源 |
| 3 | 前端系统信息 API 封装 | `frontend/src/api/system.ts:14-17` | C3 复用 |
| 4 | 「关于系统」弹窗已用同接口、同 queryKey | `frontend/src/components/AboutModal.tsx:18-23`、`:34` | C8 缓存复用 |
| 5 | 顶栏高度与品牌区间距 | `frontend/src/layouts/MainLayout.tsx:391-396` | C4 不得改变 |
| 6 | 品牌字 CSS | `frontend/src/index.css:3429-3436` | C4 新增版本样式需独立类 |
| 7 | 移动端隐藏品牌字用例 | `frontend/src/layouts/MainLayout.test.tsx:559-569` | C6 需同步断言版本也隐藏 |
| 8 | msw 系统信息默认 mock | `frontend/src/test/msw.ts:688-696` | 单测版本文案来源 |
| 9 | e2e 字体断言读取 `.cn-brand-word` | `frontend/tests/e2e/critical/typography.spec.ts:67-85` | C4 回归点 |
| 10 | 管理台已采用 `v{app_version}` 展示 | `frontend/src/pages/admin/AdminPanel.tsx:488` | C2 格式对齐依据 |

## 未决问题

- [x] 版本来源：**运行中的应用版本**（`GET /api/v1/system/about`），不用前端构建产物版本 —— 顶栏展示的应是当前服务端版本，且与「关于系统」/管理台同源。
- [x] 文案格式：**`v<版本号>`**（如 `v0.4.19`），与管理台 `AdminPanel` 既有写法一致。
- [x] 移动端：**随品牌字一起隐藏**，不给窄屏增加额外元素。
- [x] 加载 / 失败态：**不渲染**，不做骨架占位，不弹错误提示。
- [x] 展示样式：**小号 + 次要色**的独立类（`cn-brand-version`），不继承品牌字的展示字体与负字距。

> 以上为本轮按最小改动确定的口径，需求方确认 C1..C8 后即可进入实现。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方对 C1..C8 与版本格式 / 移动端隐藏口径拍板（2026-10-28 确认按方案实现）
