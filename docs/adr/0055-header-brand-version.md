# ADR 0055: 顶栏品牌字右侧显示应用版本小字

Status: Accepted（2026-10-28 人工评审通过）
Date: 2026-10-28
Related: `frontend/src/layouts/MainLayout.tsx`、`frontend/src/layouts/MainLayout.test.tsx`、`frontend/src/index.css`、`frontend/src/api/system.ts`、`frontend/src/components/AboutModal.tsx`、`src/cndb/core/system_api.py`、`frontend/src/test/msw.ts`、`frontend/tests/e2e/critical/typography.spec.ts`
需求卡片: `docs/requirements/0055-header-brand-version.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「主页顶部」「cndb 右侧」 | 在顶栏 `home-logo` 容器内、`<span className="cn-brand-word">cndb</span>` 之后渲染 `<span className="cn-brand-version" data-testid="app-version">v{app_version}</span>`；容器已有 `display: inline-flex`，天然横排 |
| C2 | 「显示版本」 | 取 `systemApi.about().app_version`，渲染为 `v{app_version}`；与 `AdminPanel.tsx:488` 的 `v${info.app_version}` 写法一致 |
| C3 | 「显示版本」（数据来源） | 复用 `GET /api/v1/system/about`（登录即可）与 `frontend/src/api/system.ts` 的 `systemApi.about`；零新增端点 / 字段 / 迁移 |
| C4 | 「小字」 | 新增 `.cn-brand-version`：`font-size: var(--cn-text-xs)`、`font-weight: var(--cn-weight-regular)`、`color: var(--cn-text-secondary)`、`white-space: nowrap`、`line-height: 1`；不使用品牌字的显示字体与负字距，不改变 `.cn-brand-word` 与品牌方块 |
| C5 | 隐含（加载 / 失败态） | 仅在 `about?.app_version` 为非空字符串时渲染；查询 `retry: false`，失败静默为不渲染，不占位、不弹提示 |
| C6 | 隐含（移动端） | 版本节点与品牌字放在同一 `!isMobile` 条件内（或等价条件），移动端两者都不渲染 |
| C7 | 隐含（可点击性） | 版本节点无 onClick，作为 `home-logo` 子节点随父级点击回 `/w` |
| C8 | 隐含（缓存与请求纪律） | 与 `AboutModal` 共用 `queryKey: ['system-about']`、`queryFn: systemApi.about`、`staleTime: 60_000`；头部查询关闭重试，避免非关键信息失败刷请求 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 顶栏品牌区为 `Tooltip` → 可点击 `div[data-testid="home-logo"]` → 品牌方块 + 桌面端品牌字 `cndb`；移动端只留品牌方块 | `frontend/src/layouts/MainLayout.tsx:407-422` | 品牌区已有横排容器与跳转行为，可直接追加只读文本 | 确认（C1 / C6 / C7 落点） |
| 2 | `GET /api/v1/system/about` 返回 `app_name / app_version / auth_enabled / timezone / server_time`，要求登录 | `src/cndb/core/system_api.py:250-264` | 当前用户已处于登录态（`MainLayout` 受 `ProtectedRoute` 保护），无需新权限 | 确认（C2 / C3 数据源） |
| 3 | 前端 `systemApi.about()` 已封装该端点并导出 `SystemAbout` 类型 | `frontend/src/api/system.ts:6-17`、`frontend/src/api/index.ts:46` | 可直接复用，无需新增 API 封装 | 确认（C3 复用） |
| 4 | 「关于系统」弹窗仅在 `open` 时查询，`queryKey: ['system-about']`、`staleTime: 60_000`，版本展示不带 `v` 前缀 | `frontend/src/components/AboutModal.tsx:18-23`、`:34` | 头部查询可与弹窗共享缓存；头部采用 `v` 前缀不改变弹窗展示 | 确认（C2 / C8）|
| 5 | 顶栏 `Header` 高 44px、`display:flex`、`gap` 桌面 8 / 移动 4 | `frontend/src/layouts/MainLayout.tsx:391-396` | 追加小字会略增品牌区宽度，需保证不换行、不抬高度 | 确认（C4 边界） |
| 6 | `.cn-brand-word` 使用展示字体 Outfit、`--cn-text-lg`、粗体、负字距 | `frontend/src/index.css:3429-3436` | 版本若复用该类会继承不适配的字距与字重，需独立类 | 确认（C4 需新增样式） |
| 7 | 移动端用例断言品牌字隐藏；e2e `typography.spec.ts` 读取 `.cn-brand-word` 校验 Outfit | `frontend/src/layouts/MainLayout.test.tsx:559-569`、`frontend/tests/e2e/critical/typography.spec.ts:67-85` | 版本随品牌字隐藏；新增节点不得影响既有字体断言 | 确认（C6） |
| 8 | msw 默认 `/api/v1/system/about` 返回 `app_version: '0.3.0'` | `frontend/src/test/msw.ts:688-696` | 单测可直接断言出现 `v0.3.0`，无需自建 handler | 确认（C2 验收） |
| 9 | 管理台版本文案为 `v${info.app_version}` | `frontend/src/pages/admin/AdminPanel.tsx:488` | 已有 `v` 前缀先例 | 确认（C2 格式依据） |
| 10 | 顶栏查询目前只有工作区 / 表列表，`system-about` 仅在弹窗打开时加载 | `frontend/src/layouts/MainLayout.tsx:108-121`、`AboutModal.tsx:18-23` | 新增一次轻量登录态请求；可通过共享缓存与 `staleTime` 收敛 | 新增（C8 请求成本） |

**核心缺陷（需求要补的）**：当前应用版本只能进入「关于系统」弹窗（或管理台）才能看到，主页顶栏没有任何常驻版本标识；用户反馈问题时无法一眼读出当前部署版本。

设计目标（不变量）：

- **I1 单一数据源**：顶栏版本只来自 `GET /api/v1/system/about` 的 `app_version`，前端不硬编码、不读 `package.json`、不另设构建期常量。
- **I2 位置与形态固定**：版本节点始终是 `home-logo` 内、`cndb` 品牌字之后的只读小字；不改变品牌区点击行为、顶栏高度与品牌字字体。
- **I3 静默降级**：请求未完成 / 失败 / 返回空版本时，版本节点不存在，顶栏其余功能与布局不受影响。
- **I4 窄屏一致**：移动端品牌字隐藏时版本同时隐藏，不出现孤立版本小字。
- **I5 请求可共享**：与「关于系统」弹窗共用同一 queryKey 与 staleTime；头部查询不重试，不因非关键信息失败制造请求风暴。

## Decision

以下小节按需增减；不适用的小节保留标题写「无」。

### 1. 数据模型

无（展示既有 `APP_VERSION`，不落库、不新增字段）。

### 2. 判定算法（唯一入口）

无后端判定。前端展示条件唯一：`about?.app_version` 为非空字符串，且 `!isMobile`。查询入口唯一为 `MainLayout` 的 `useQuery({ queryKey: ['system-about'], queryFn: systemApi.about })`，与 `AboutModal` 共享缓存。

### 3. API 变更清单

无。复用 `GET /api/v1/system/about` 的既有 `app_version` 字段。

### 4. 边界与例外

1. **版本为空 / 接口失败**：不渲染版本节点；头部查询 `retry: false`，后台仍有 React Query 自身缓存与下一次挂载重试机会，不弹全局错误提示。
2. **开发版本 / 预发布版本**：`app_version` 可能含 `dev` / `rc` 等后缀，按原样展示；`white-space: nowrap`，空间不足时由品牌区自然占位，不换行、不挤压右侧工作区下拉（移动端已隐藏）。
3. **移动端**：`isMobile` 为真时不渲染版本节点；断点沿用 `useResponsive` 的 768px，不新增断点。
4. **点击行为**：版本节点不绑定事件，点击冒泡到 `home-logo`，仍执行 `navigate('/w')`；不新增 Tooltip，避免与父级「主页」Tooltip 叠加。
5. **关于系统 / 管理台**：弹窗仍展示不带前缀的 `app_version`，管理台仍为 `v{version}`；本 ADR 不改这两处。
6. **帮助页 / 管理台**：`MainLayout` 顶栏在这些路由同样渲染，版本持续可见（符合「主页顶部」常驻口径）。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 布局 | `frontend/src/layouts/MainLayout.tsx` | 引入 `systemApi`；新增 `useQuery({ queryKey: ['system-about'], queryFn: systemApi.about, staleTime: 60_000, retry: false })`；在 `home-logo` 内、`cn-brand-word` 之后按 `!isMobile && about?.app_version` 渲染 `<span className="cn-brand-version" data-testid="app-version">v{...}</span>` |
| 样式 | `frontend/src/index.css` | 新增 `.cn-brand-version`：小号 / 常规字重 / 次要色 / 不换行 / `line-height: 1`，不改 `.cn-brand-word` 与 `.cn-brand-mark` |
| 测试 | `frontend/src/layouts/MainLayout.test.tsx` | 桌面端断言 `app-version` 文案为 `v0.3.0` 且位于 `home-logo` 内；移动端断言不存在；接口 500 时静默不渲染 |

### 7. 测试清单

**判定层（单测）**：无（无判定算法变更）。

**接口层**：无（无 API 变更；复用既有 `/system/about`）。

**迁移 / 备份**：无。

**前端单测**（`MainLayout.test.tsx`）：

- 桌面端：等待顶栏加载后 `getByTestId('app-version')` 文案为 `v0.3.0`，且 `home-logo` 同时包含 `cndb` 与版本节点、版本节点在品牌字之后；
- 移动端：`queryByTestId('app-version')` 为 null，且品牌方块与汉堡入口仍可见；
- 失败态：覆盖 `/api/v1/system/about` 返回 500，工作区仍正常加载，`app-version` 不存在、无错误弹窗；
- 回归：既有「关于系统」弹窗用例（`MainLayout.test.tsx:259` 附近）继续通过，证明共享 queryKey 不改变弹窗行为。

**e2e（前端）**：无新增用例；既有 `typography.spec.ts` 的 `.cn-brand-word` Outfit 断言继续通过（版本节点使用独立类，不污染品牌字）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 顶栏版本查询 + 版本小字 + `.cn-brand-version` 样式 | 低 |
| **P1** | 桌面 / 移动 / 失败态单测与既有用例回归 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：版本从哪里取 | **复用 `GET /api/v1/system/about` 的 `app_version`** | 展示的是当前运行后端版本；登录即可访问；已有前端封装与 msw handler；与「关于系统」同源（I1） | ① 前端构建期读 `package.json`（前后端版本可能不一致，展示失真）；② 新增 `/api/version` 专用端点（重复既有信息，增加维护面）；③ 读 `/api/health`（无前端封装，且健康检查不是用户信息入口） | `MainLayout.tsx`、`frontend/src/api/system.ts` |
| D2 | 文案格式 | **`v<app_version>`** | 与管理台 `AdminPanel.tsx:488` 一致；版本一眼可辨 | 裸版本号（与「关于系统」弹窗一致，但与管理台不一致，且 `v` 更能表明是版本） | `MainLayout.tsx` |
| D3 | 展示位置 | **`home-logo` 内、`cn-brand-word` 右侧** | 最贴近需求原句「cndb 右侧」；品牌区已有横排容器；仍随品牌区点击回主页（I2/C7） | 放到工作区下拉右侧 / 顶栏最右侧用户区（偏离「cndb 右侧」；与操作入口混在一起） | `MainLayout.tsx:407-422` |
| D4 | 移动端是否展示 | **不展示，随品牌字隐藏** | 窄屏顶栏空间紧张；需求语境是桌面主页顶部品牌字（C6/I4） | 在品牌方块右侧单独显示（只剩方块与版本，视觉失衡且挤压汉堡 / 搜索） | `MainLayout.tsx` |
| D5 | 加载 / 失败态 | **静默不渲染** | 版本是非关键信息，占位或报错会干扰顶栏；缓存命中后自然出现（C5/I3） | 骨架占位（小字宽度闪烁）；失败弹提示（噪音） | `MainLayout.tsx` |
| D6 | 请求策略 | **共享 `['system-about']` 缓存 + `staleTime: 60_000` + `retry: false`** | 与弹窗同源，避免重复请求；头部失败不重试刷屏（I5/C8） | 独立 queryKey（同一信息两份缓存）；默认重试（非关键信息失败放大请求） | `MainLayout.tsx`、`AboutModal.tsx` |
| D7 | 样式承载 | **新增 `.cn-brand-version` 独立类** | 品牌字使用展示字体 / 粗体 / 负字距，版本需要小号次要色，混用会破坏品牌字视觉（C4/I2） | 复用 `.cn-brand-word` 加内联样式（继承负字距与粗体，且难以统一主题色）；纯内联样式（主题 token 使用分散） | `index.css`、`MainLayout.tsx` |
| D8 | 是否新增 e2e | **不新增**：布局与小字由前端单测覆盖，e2e 字体用例作为回归 | 无端到端流程变化；e2e 运行成本高且无法稳定断言「小字」视觉 | 为版本小字补 e2e（收益低、脆） | `MainLayout.test.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：主页顶栏常驻当前部署版本，反馈问题时可一眼确认版本；复用既有接口与弹窗缓存，实现面小；移动端与失败态静默降级，不干扰现有布局。
- **负向**：登录后首页多一次轻量 `/system/about` 请求（缓存 60s）；顶栏品牌区宽度略增（桌面端有充足空间）。
- **风险与缓解**：版本号含预发布后缀时可能偏长 → `white-space: nowrap` 且移动端隐藏；接口失败导致版本不显示 → 接受为静默降级，不弹错误；与弹窗共用缓存但 `staleTime` 不同 → 统一为 60s，避免口径漂移。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 顶栏品牌区 | `MainLayout.tsx` `home-logo` | 品牌区继续作为回主页入口，版本只读附加 | 既有布局实现 |
| 系统信息出口 | `GET /api/v1/system/about` | 顶栏与「关于系统」共用同一端点与缓存 | 既有 `AboutModal` 口径、本 ADR D1/D6 |
| 展示字体 | `.cn-brand-word` / Outfit | 版本小字不复用品牌字样式，独立类 | ADR 0031 字体与排版口径 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css` | `frontend/src/layouts/MainLayout.test.tsx` | `30e775d1` |
| P1 | 已落地 | `frontend/src/layouts/MainLayout.test.tsx` | `frontend/src/layouts/MainLayout.test.tsx` | `30e775d1` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0/P1 已落地并提交（`30e775d1`），等待人工确认是否将 `Status` 转 `Implemented`
- 已完成：需求卡片与 ADR 评审确认；顶栏版本查询、版本小字与 `.cn-brand-version` 样式；桌面 / 移动 / 失败态单测
- 下一步：处理与本次无关的既有后端测试失败后跑 `make flow` 收口；确认后转 `Implemented`
- 已知坑：头部查询与 `AboutModal` 共用 `['system-about']`，修改 queryKey / staleTime 需两处同步；msw 默认版本为 `0.3.0`，单测断言需跟随该 mock；移动端依赖 `useResponsive` mock 切换；后端全量测试被 `examples/datasets/工作区-数据源示例/views.json` 缺少「全部日线」视图阻塞（HEAD `4fa9c947` 既有问题，与本次改动无关）
- 最近一次全绿：`make check-fast`、`pnpm test`（2300 passed）、`make frontend-coverage`（2026-10-28）
