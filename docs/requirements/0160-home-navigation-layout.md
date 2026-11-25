# 需求卡片：登录默认页（主页）的导航与布局优化

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0160
- 分级：**S1（P0 / P1）** + **S2（P2 新增聚合接口）**
  - P0 排版收口 + P1 主页导航 rail：纯前端导航 / 布局，方案并入本卡片，无 ADR；
  - P2 `GET /api/v1/home/summary`：新增只读聚合接口 + 跨工作区权限聚合，另立 [ADR 0160](../adr/0160-home-summary-aggregation.md)。
- 来源 / 提出人：用户（会话 2026-11-27，「登陆后侧边栏取消以后，显得很空。请结合 GitHub 等最佳实践，给出当前登陆默认页面的导航优化布局方案」，选型确认：`1,A+B; 2,允许；3,接受`）
- 日期：2026-11-27
- 关联 ADR：**修订** [需求 0157](0157-team-navigation-and-layout.md) 的「主页导航收敛（补）」口径（当时为「无 `wid` 不渲染侧栏」，现改为「无 `wid` 渲染主页级导航，不渲染工作区级侧栏」）；复用 [ADR 0021](../adr/0021-home-favorite-views-panel.md)（我的视图面板）、[ADR 0123](../adr/0123-mobile-responsive-adaptation.md)（移动端断点）、[ADR 0026](../adr/0026-chrome81-compat.md)（无 container query）
- 前置实现：`frontend/src/pages/workspace/WorkspaceList.tsx`、`frontend/src/pages/workspace/MyViewsPanel.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`

## 需求原句（逐字）

> 登陆后侧边栏取消以后，显得很空。请结合GITHUB等最佳实践，给出当前登陆默认页面的导航优化布局方案

选型确认（2026-11-27，人工）：

> 1,A+B；2允许；3接受

即：采用方案 A（主页导航 rail 复活，同一导航轴换 Scope）+ 方案 B（内容宽度分段 + 行内定宽列 + 空态引导）；允许主页侧栏回归（修订 0157 口径）；接受 P2 新增 `GET /api/v1/home/summary`。

## 可实施约束（C1..Cn）

| # | 需求片段 | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「导航优化」 | **同一导航轴、两种 Scope**：`/w`、`/teams*`（无 `wid` 且非管理台 / 非帮助）渲染「主页导航 rail」；`/w/:wid/*` 沿用现有工作区侧栏；`/admin` 管理台侧栏、`/help` 自带两级侧栏不变。同一时刻最多一条侧栏，不新增第三个导航轴 | `layouts/MainLayout.tsx`、`components/HomeNav.tsx`（新增） | 单测：四种上下文各断言侧栏 testid 唯一；无 `sider-no-workspace` |
| C2 | 「显得很空」 | **宽度节奏**：主页容器 `max-width: 1440px` 居中；「我的视图」右栏定宽 360px（不再 `340px + 5vw` 随视口膨胀）；1600+ 三栏（rail / 主区 / 右栏）、1280–1599 两栏、<992 右栏下移；任何断点不出现横向滚动 | `index.css`、`pages/workspace/WorkspaceList.tsx` | 单测：容器类与栅格；e2e 断点矩阵断言 `scrollWidth <= clientWidth` |
| C3 | 「显得很空」 | **行内排版成表格化对齐**：`.cn-ws-row-body` 由 `flex + space-between` 改为 `grid`（标题 `minmax(0,1fr)` + meta `auto` 右对齐），名称与计数 / 时间按列对齐、不再被拉到两端；断点行为零回归（<1200 收模块徽标、<1024 收时间、<768 不渲染 meta、名称始终可读） | `index.css` | 既有 e2e `workspace-list-responsive.spec.ts` 全绿（1440/1280/1024/768/390） |
| C4 | 「默认页面」 | **继续上次**：主页主区首屏顶部横向卡片列出最近打开的 ≤5 个工作区（名称 + 落地模块 + 相对时间），点击直达 `最近落地路径`；数据只存本地 `usePersistedState`（`wid` / `path` / `ts`），不建表、不进备份、不上传、不区分设备 | `pages/workspace/recentWorkspaces.ts`（新增）、`WorkspaceList.tsx` | 纯函数单测：写入去重 / 上限 5 / 非法路径过滤 / 相对时间；组件单测：空态不渲染 |
| C5 | 「默认页面」 | **空态即引导**：无工作区时主区首屏是引导卡（新建工作区 / 导入备份 / 加入团队），搜索无结果仍用 `Empty`；有工作区但无收藏视图时右栏显示说明而非空面板 | `WorkspaceList.tsx`、`MyViewsPanel.tsx` | 单测：三种空态分支文案与按钮可达 |
| C6 | （移动端） | <1024 rail 收进抽屉（汉堡恢复），抽屉顶部为「主页导航」分区，其后保留既有「团队 → 工作区」分组；触控目标 ≥32px，不横向溢出 | `MainLayout.tsx`、`index.css` | 单测：移动端汉堡存在且抽屉含主页导航；e2e 390 宽度 |
| C7 | （存量兼容） | 团队 chips / 收藏分组 / 拖拽排序 / 展开详情 / 搜索 / 收藏视图拖拽 / 新建与导入流程行为不回归；`GET /workspaces`、`GET /teams`、`preferences` 载荷不变 | 前端为主 | 现有单测全绿 + 0157 相关 e2e 全绿 |
| C8 | （P2 聚合口径） | `GET /api/v1/home/summary` **只读**：返回最近访问（若有）之外的「待我处理」计数（修改申请 / 问题 / 链接申请）与团队 / 工作区计数；**逐工作区同权过滤**，无读权的条目计 0 且不暴露存在性（不返回 id / 名称）；载荷不含提示词、密钥、行数据；按用户隔离，缓存 TTL ≤ 30s | `plugins/workspaces/routers/home.py`（新增） | 接口测试：跨用户不可见、无读权计 0、载荷字段白名单、缓存随写失效 |
| C9 | （可访问性） | rail 用 `<nav aria-label="主页导航">`，当前项 `aria-current="page"`；分组标题为语义标题；键盘可 Tab 达全部条目 | `HomeNav.tsx` | 单测：role / aria 断言 |
| C10 | （门禁） | P0 / P1：`make check-fast` + `make test` + `make check-frontend`；P2 另加 `make cov`；关键 e2e 断点矩阵 | 全链路 | 见「分期」表 |

非目标（本期不做）：

- 命令面板（Cmd/Ctrl+K）—— 方案 C，留作后续增强。
- 主页「动态 / 活动流」（GitHub feed 形态）：没有跨工作区事件聚合口径，先不做。
- 工作区级侧栏的形态调整（仍是表 / 文档 / 设计 / 设置 / 统计分项）。
- 服务端存储「最近访问」（不做新表；跨设备同步不在本期）。

## 方案（A + B）

### 布局骨架（≥1600）

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 44px 顶栏：品牌  「全部工作区 ▾」           [搜索] [大模型][帮助][管理台][头像] │
├────────────┬─────────────────────────────────────────────────────────────┤
│ 主页 rail  │ 内容区（max-width 1440 居中）                                │
│ 240 / 60   │  ┌ 继续上次（≤5 横卡）──────────────────────────────────┐   │
│ ＋新建      │  └──────────────────────────────────────────────────────┘   │
│ 最近访问    │  ┌ 我的工作区 ─────────────────────┐ ┌ 我的视图 ───────┐  │
│ 全部工作区  │  │ 搜索 / 新建 / 导入 + 团队 chips   │ │ 收藏视图列表    │  │
│ 团队 (n)    │  │ 分组行列表（grid 定宽列）        │ │                 │  │
│ 收藏视图    │  └──────────────────────────────────┘ └─────────────────┘  │
│ 管理团队    │                                                              │
└────────────┴─────────────────────────────────────────────────────────────┘
```

### 分期

| 期 | 内容 | 需求级 | 门禁 | 状态 |
|---|---|---|---|---|
| P0 | 排版收口：`max-width` + 右栏定宽 + 行内 grid + 空态引导 | S1 | `make check-fast` + `make test` + `make check-frontend` | 已落地 |
| P1 | 主页导航 rail（新建 / 最近 / 全部 / 团队 / 收藏视图 / 管理团队）+ 移动端抽屉 | S1 | 同上 + e2e 断点矩阵 | 已落地 |
| P2 | `GET /api/v1/home/summary` + rail 待办徽标（修改申请 / 问题 / 链接申请） | S2（ADR 0160） | `make cov` + 接口测试 | 未开始 |

## 卡点

- [x] 选型确认：A + B（2026-11-27）
- [x] 允许主页侧栏回归，并据此修订需求 0157 的「主页导航收敛（补）」口径（2026-11-27）
- [x] 接受 P2 新增只读聚合接口 `GET /api/v1/home/summary`（2026-11-27）
- [ ] ADR 0160 评审（P2 开工前）

## 落地（实现完成）

| 项 | 落点 |
|---|---|
| P0 宽度节奏 | `frontend/src/index.css`（`.cn-home-page` `max-width: 1360px` 居中；`.cn-home-split` 右栏定宽 360px；<1600 堆叠）；`frontend/src/theme/tokens.ts` 新增 `BREAKPOINT.wide = 1600`（断点白名单单测登记 1599.98） |
| P0 行内排版 | `frontend/src/index.css`（`.cn-ws-row-body` 改 `grid: minmax(0,1fr) auto`，`.cn-ws-row-meta` 右对齐；≤991 堆叠左对齐） |
| P0 空态引导 | `frontend/src/pages/workspace/WorkspaceList.tsx`（`Empty` + 新建 / 导入备份 / 我的团队）；根容器 `cn-home-page` |
| P0 测试 | `WorkspaceList.test.tsx` +2 例（宽度收口容器与双板块骨架、空态三入口与新建弹窗） |
| P1 主页 rail | `frontend/src/components/HomeNav.tsx`（新建 / 最近访问 / 全部工作区 / 团队（含工作区计数）/ 收藏视图 / 管理团队 / 帮助；条目走 antd `Menu` 复用 `.cn-table-nav`，不新增一套导航样式；lazy 加载） |
| P1 路由接线 | `frontend/src/layouts/MainLayout.tsx`：`SiderMode` 新增 `'home'`（无 `wid` 且非管理台 / 帮助→主页导航；`/w/:wid/*` 仍为工作区侧栏）；移动端汉堡恢复，抽屉顶部先给主页导航分区再接既有团队分组 |
| P1 最近访问 | `frontend/src/utils/recentWorkspaces.ts`（`localStorage`：`wid` / `path` / `ts`，同工作区去重、上限 5、非法路径忽略；登录 / 登出清空避免串号）+ `MainLayout` 导航时记录 |
| P1 测试 | `HomeNav.test.tsx` 7 例（分区与计数、选中态、最近访问读本地、折叠态、移动端变体、新建 / 团队 / 管理 / 帮助跳转）、`recentWorkspaces.test.ts` 7 例（规范化 / 去重 / 上限 / 损坏兜底）、`MainLayout.test.tsx` 改写 3 例（主页与团队页渲染主页 rail、移动端汉堡与抽屉） |
| P1 体积 | `HomeNav` lazy 化（不进应用外壳 chunk）；`frontend/scripts/bundle-budget.json` 按实测收口「主入口 CSS」「MainLayout」基线并上调上限（理由已落盘） |
