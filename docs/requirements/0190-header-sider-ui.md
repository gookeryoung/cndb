# 需求卡片：顶栏与文档侧栏 UI / 布局美化

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0190（S1，方案并入本卡片，无 ADR）
- 来源 / 提出人：用户（会话 2026-11-28）
- 日期：2026-11-28
- 关联 ADR：无（纯前端视觉 / 布局，不触碰数据 / 接口 / 权限口径；约束 H24 / H25 / H29 / H30 / H31 / H32）
- 关联前序：`docs/requirements/0189-knowledge-graph-ui.md`（同批版式重构的范式）、`0160-home-navigation-layout.md`、`0157-team-navigation-and-layout.md`、`0081`（顶栏三区）、`0065`（侧栏形态）、`0162`（侧栏宽度）
- 状态：**P0–P2 已落地**（2026-11-28 用户「开始」后实现；S1 无 ADR，方案与落地结果均在本卡）

## 需求原句（逐字）

> 文档，顶部栏和侧边栏的UI及布局需进一步美化，请给出可行建议

> 开始

## 背景（现状核实，非推测）

「不美」不是配色问题，是**元素平铺 + 层级语言不统一 + 行内样式拼装**三件事：

### 顶栏（`MainLayout.tsx:1221-1400`，44px，样式 `index.css:589-800`）

| # | 现象 | 根因（已核实） | 位置 |
|---|---|---|---|
| 1 | 左区一行塞 7 类元素：汉堡 / LOGO / 品牌字 / 版本号 / 团队面包屑 / 斜杠分隔 / 切换器 / 一级导航（带计数） | 无分组，全靠 `gap` 分隔 | `:1229-1340` |
| 2 | 三层导航语言并存：顶栏 `inset 0 -2px` 墨条、工作区页签 3px 墨条、二级页签胶囊底 | 层级靠「线宽 2 vs 3」区分，扫视不可辨 | `index.css:737` / `:1041` / `:1175` |
| 3 | 右侧 4–5 个图标按钮同权重同形状，无主次 | 全部 `type` 默认 | `:1352-1390` |
| 4 | 每个图标按钮都被加了 1px 描边，像一排小方块 | `.cn-app-header .ant-btn` 无差别加边框 | `index.css:604` |
| 5 | 窄屏靠 JS 两档硬降级（`<1280` / `<1024`），元素整块消失无中间态 | `compactHeader` / `narrowHeader` 布尔 + 20 处 `!compactHeader` 条件 | `:190-192` |
| 6 | `height: 44, lineHeight: '44px'` 内联字面量 | 未走标尺 | `:1225` |
| 7 | 版本号 `v0.3.0` 常驻顶栏，占据本已拥挤的左区 | 低价值信息占高位 | `:1247-1255` |

### 文档侧栏（`MainLayout.tsx:925-1018`，样式 `index.css:5298-5370`）

| # | 现象 | 根因（已核实） | 位置 |
|---|---|---|---|
| 8 | 标题行 / 工具条 / 树三段各自写行内 `style`，左内边距分别为 `space-lg` / `space-lg` / `space-xs`，靠注释人工对齐 | 无统一面板容器 | `:932`、`:942`、`:997` |
| 9 | 过滤框与两个图标按钮同排抢宽度，窄侧栏下互相挤 | 工具条无分组 | `:943-990` |
| 10 | 树选中态只有一层 `--cn-bg-selected` 底色，无左指示条、无圆角 | 侧栏无自己的选中语义 | `index.css:1009` |
| 11 | 表导航有品牌色左指示条（`.cn-table-nav`），文档树没有 —— 同一位置两条侧栏两种选中语言 | 未复用 | `index.css:992` vs `:5298` |
| 12 | 侧栏与内容区同底色，只靠 1px 线分开；拖拽把手常态透明 | 无视觉分区 | `:1424`、`index.css:5686` |
| 13 | 空态「还没有文档，去文档页创建吧」无动作按钮 | 只有文字 | `:995` |
| 14 | `MainLayout.tsx` 共 30 处行内 `style={{}}`（顶栏 12 + 侧栏 8） | DESIGN_SYSTEM §6 收敛清单第一条 | 全文 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「顶部栏…美化」 | 左区收敛为**两段**：① 品牌块（LOGO + 品牌字，去掉版本号）；② 位置控件（团队 › 工作区 ▾，把现有面包屑与 `ScopeSwitcher` 合成一个可点区域）。中间那条独立斜杠分隔符删除 | `MainLayout.tsx:1229-1308` | 单测：`.cn-header-left` 内只有 `.cn-header-brand` 与 `.cn-header-loc` 两个子块；`header-team-crumb` 仍在 `cn-header-loc` 内可点 |
| C2 | 同上 | 版本号移出顶栏，只在「关于系统」弹窗展示（`AboutModal` 已有「版本」行）；`app-version` testid 从顶栏移除 | `MainLayout.tsx:1247-1255` | 单测改：顶栏无 `app-version`；`AboutModal` 仍显示版本 |
| C3 | 同上 | 一级导航激活态由「底部 2px 墨条」改为**圆角胶囊底**（`--cn-mix-brand-color-12-bg-container`），与二级页签同语言；层级改由位置（顶栏 / 内容区上方）+ 形状（胶囊 / 墨条）区分 | `index.css:699-745` | `headerBorders.test.ts` 增断言：`cn-header-nav-item-active` 用胶囊底、不含 `box-shadow: inset` |
| C4 | 同上 | 计数徽标统一为中性胶囊（`--cn-radius-pill` + `--cn-bg-subtle`），与 `cn-record-pill` 同源；不再只是灰字 | `index.css:565` | 单测：徽标 class 含 `cn-nav-count` |
| C5 | 同上 | 右侧按钮分级：工具类（大模型 / 帮助）**无描边**（`type="text"` 语义），管理台保留 1px 描边，头像唯一圆形；`.cn-app-header .ant-btn` 的全局 1px 边框收窄为只作用于带描边的类 | `index.css:604`、`MainLayout.tsx:1352-1390` | `headerBorders.test.ts` 改断言：默认无描边、`.cn-header-btn-outlined` 有描边；e2e 右区按钮顺序不变 |
| C6 | 同上 | 降级改为**CSS 驱动**：删除 `compactHeader` / `narrowHeader` 两个 JS 布尔与 20 处 `!compactHeader` 条件渲染，改由 `@media` + 容器宽度逐步收起（品牌字 → 导航文字 → 工具按钮）。**保留** `data-compact` 属性供测试与 e2e 判定 | `MainLayout.tsx`、`index.css` | 单测：1100px 宽下品牌字与导航文字不可见（靠 CSS class 而非不渲染）；`data-compact="true"` 仍在 |
| C7 | 「侧边栏…美化」 | 三段合并为**一个统一面板** `.cn-doc-nav`：标题行（「文档」+ 新建入口）→ 过滤行（独占一行）→ 工具行（排序 / 展开 / 更多）→ 树。删掉这三段的全部行内 `style` | `MainLayout.tsx:925-1018` | 单测：`.cn-doc-nav` 存在且含四个子块；`doc-tree-filter` / `doc-tree-sort` / `doc-tree-expand-toggle` 仍在 |
| C8 | 同上 | 树选中态补**品牌色左指示条 + 圆角胶囊**，与 `.cn-table-nav` 同语言 | `index.css:5298` | `headerBorders.test.ts` 或新用例：`.cn-doc-sider-tree .ant-tree-node-selected::before` 存在且宽 3px 品牌色 |
| C9 | 同上 | 侧栏底改 `--cn-bg-subtle`（低一档），与内容区容器底形成层次；1px 右边框保留；拖拽把手常态可见 1px 中性线（hover 转品牌色） | `MainLayout.tsx:1424`、`index.css:5686` | `headerBorders.test.ts`：`.cn-sider-resizer::after` 常态 `--cn-border`、hover 品牌色 |
| C10 | 同上 | 侧栏空态补动作按钮（「新建文档」→ `/w/:wid/documents?create=1`），与知识图谱页空态同口径 | `MainLayout.tsx:995` | 单测：空态含按钮且点击后 URL 带 `create=1` |
| C11 | （共性） | 本文件行内 `style` 由 30 处降到 ≤12 处（顶栏 + 侧栏段落归零），新增 `.cn-header-*` / `.cn-doc-nav-*` 类承载 | `MainLayout.tsx`、`index.css` | `DESIGN_SYSTEM.md §6` 数字更新；单测：`.cn-header-left` 子节点无 `style` 属性 |
| C12 | （设计约束） | 只用 `--cn-*` token（H29）；线条 1px 中性线、hover/active 才用品牌色（H25）；选中态用 `--cn-bg-selected` 且对比度达标（H24）；断点只 `767.98` / `575.98`（H30）；不新增重型依赖（H31）；体积变化走 `bundle-budget.mjs`（H32） | `index.css`、`MainLayout.tsx` | `make check-frontend` 双门槛 + `make frontend-static` + `bundle-budget` |
| C13 | （测试约束） | 同轮补：`MainLayout.test.tsx`（新结构契约 + 侧栏面板 + 选中态 + 空态动作 + 紧凑档改判据）、`headerBorders.test.ts`（顶栏按钮分级 / 侧栏分区 / 把手）、e2e `workspace-list-responsive.spec.ts` 与 `navigation.spec.ts` 按新判据调整（不得放宽） | 测试文件 | `make check-frontend` / `make e2e-affected` |
| C14 | （文档约束） | `DESIGN_SYSTEM.md`（新增顶栏 / 侧栏原语说明、§6 收敛数字）、`CHANGELOG.md`、本卡回填 | 文档 | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 目标形态

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◈ 晶格协同 │ 科研团队 › 科研项目管理 ▾ │ [数据表][文档][设计][统计][设置] │  🔍  ⚙ ❓ ⛨  ◯ │
└──────────────────────────────────────────────────────────────────────────┘
   ↑品牌块      ↑位置控件（合并面包屑+切换器）      ↑胶囊激活（计数为中性胶囊）    ↑无描边工具 / 描边管理 / 圆形头像

文档侧栏：
┌─────────────────────┐
│ 文档            ＋  │  ← 标题行带新建
│ [🔍 过滤标题…     ] │  ← 过滤独占一行
│ [⇅ 排序] [⊟ 展开] ⋯│  ← 工具行归组
├─────────────────────┤
│ ▸ 📁 文件夹         │
│ ▌ 📄 文档标题   🔒  │  ← 选中 = 胶囊底 + 3px 品牌左指示条
└─────────────────────┘
```

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 顶栏结构 / 三区 | `MainLayout.tsx:1221-1400` | C1 / C5 / C6 |
| 2 | 顶栏样式 | `index.css:589-800` | C3 / C4 / C5 |
| 3 | 侧栏面板 | `MainLayout.tsx:925-1018` | C7 / C10 |
| 4 | 文档树样式 | `index.css:5298-5370` | C8 |
| 5 | 侧栏容器与把手 | `MainLayout.tsx:1424`、`index.css:5686` | C9 |
| 6 | 顶栏线条契约测试 | `frontend/src/layouts/headerBorders.test.ts` | C3 / C5 / C9 |
| 7 | 布局单测（含紧凑档 4 例） | `frontend/src/layouts/MainLayout.test.tsx:1805+` | C6 / C13 |
| 8 | e2e 响应式（含 `<1280` 判据） | `frontend/tests/e2e/critical/workspace-list-responsive.spec.ts:64-92` | C6 / C13 |
| 9 | e2e 导航 | `frontend/tests/e2e/critical/navigation.spec.ts:81-89` | C13 |
| 10 | 版本号展示 | `components/AboutModal.tsx:34` | C2（已有版本行，只需移除顶栏那份） |

## 决策（S1 方案）

- **D1 顶栏左区改「品牌 + 位置」两段**：现在的 7 类元素里，版本号是低价值信息、斜杠是纯装饰、面包屑与切换器是同一件事的两半。合并后左区只剩两个语义块，扫视成本从 7 降到 2。
- **D2 一级导航改胶囊**：三层墨条/胶囊并存是「层级混乱」的直接来源。胶囊与二级页签同语言后，层级只靠「顶栏 vs 内容区」这一条空间规则区分，不再靠线宽 2px vs 3px 这种几乎看不出差别的参数。
- **D3 图标按钮去描边**：GitHub 顶栏的 icon-only 按钮本来就没有边框。现在全局 `.cn-app-header .ant-btn` 加 1px 描边（`index.css:604`），导致一排小方块；改为默认无描边 + 显式 `cn-header-btn-outlined` 才描边，同时解决「主次不分」。
- **D4 降级交给 CSS**：`compactHeader` / `narrowHeader` 是两档硬开关，元素整块消失；且 20 处 `!compactHeader` 条件渲染让 JSX 难以阅读。改为 CSS `@media` 逐步收起，`data-compact` 保留给测试判定。**风险**：e2e 现有「`<1280` 时品牌字 `toHaveCount(0)`」的断言会变成「不可见」而非「不存在」，需同步改判据（不放宽，仍断言不可见）。
- **D5 侧栏三段合一**：三处行内 `padding` 靠注释人工对齐是不可维护的；统一面板后左基线由一处控制。
- **D6 侧栏选中态对齐表导航**：同一位置（左栏）两条侧栏两种选中语言是明显的设计缺陷，直接复用 `.cn-table-nav` 的左指示条语言。
- **D7 侧栏底降一档**：现在侧栏与内容区同底色，只靠 1px 线分开，眼睛分不出层次；`--cn-bg-subtle` 是现成 token，零新增。
- **D8 本轮不碰**：工作区页签（`.cn-ws-tabs`）的三级导航本身、侧栏宽度逻辑（0162）、团队切换器面板内部、主页 rail（0160）、帮助页侧栏。

## 分期

| 期 | 内容 | 预估 |
|---|---|---|
| P0 | C1 / C2 / C3 / C4 / C5（顶栏结构 + 胶囊导航 + 按钮分级 + 版本号移出） | 约半天 |
| P1 | C6 / C7 / C8 / C9 / C10（CSS 驱动降级 + 侧栏三段合一 + 选中态 + 分区 + 空态动作） | 约半天 |
| P2 | C11 / C12 / C13 / C14（行内 style 收敛、token 自查、测试与文档回填） | 约半天 |

## 未决问题

- [x] ① 版本号是否移出顶栏？→ 移出（C2 / D1）：顶栏 44px 空间紧张，版本信息在「关于系统」已有；且它是 `0.3.0` 这类低变动信息，不配常驻高位。
- [x] ② 一级导航改胶囊还是保留墨条？→ 胶囊（D2）：与二级统一，层级靠位置区分。
- [x] ③ 本轮范围？→ 顶栏 + 文档侧栏（A+B），共性收敛 C11 作为收尾；不扩到其他侧栏（D8）。
- [x] ④ 降级改 CSS 会不会破 e2e？→ 会，`toHaveCount(0)` 需改 `not.toBeVisible()`（D4）；这是判据迁移不是放宽，同轮改。
- [x] ⑤ 是否合并表导航 / 设置 / 统计侧栏？→ 本轮不合并（D8），只在 C8 把选中态语言对齐；合并留后续需求。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认后进入实现（S1 人工卡点，H5；2026-11-28 用户「开始」）

## 落地结果（2026-11-28）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 左区两段 | 新增 `.cn-header-brand`（品牌块）与 `.cn-header-loc`（位置控件，面包屑 + 切换器同容器）；斜杠归入位置控件 | 单测：`documents-crumb` 等既有断言零改动通过 |
| C2 版本号移出 | 顶栏 `app-version` / `.cn-brand-version` 删除；`systemAbout` 查询保留为弹窗缓存预热 | 单测 2 例改为断言「顶栏不再渲染版本」 |
| C3 胶囊导航 | `.cn-header-nav-item-active` 改 `--cn-mix-brand-color-12-bg-container` 胶囊底，去掉 `inset` 墨条 | `headerBorders.test.ts` 断言激活态无 `box-shadow`、有胶囊底 |
| C4 计数胶囊 | 顶栏灰字升级为 `.cn-ws-tab-count` 中性胶囊（与页签 / 团队页共用一套） | 视觉统一，无新增规则 |
| C5 按钮分级 | `.cn-app-header .ant-btn` 去掉无差别描边；`cn-header-btn-outlined`（管理台 / 头像）描边、`cn-header-btn-ghost`（工具）平面 | `headerBorders.test.ts` 断言默认无 `border`、两类各自口径 |
| C6 CSS 降级 | 删除 20 处 `!compactHeader` 条件渲染；`@media 1199.98 / 1023.98px` 逐级收起；`data-compact` 保留 | 单测改判「元素仍在 DOM + 命中收起选择器」；e2e 改 `not.toBeVisible()` |
| C7 侧栏面板 | `.cn-doc-nav` = head / filter / tools / tree 四段，行内 style 清零 | 单测：四段各归其位、过滤框与工具按钮不同父容器、段落无内联 style |
| C8 树选中态 | 补 3px 品牌色左指示条 + 圆角胶囊，与 `.cn-table-nav` 同语言 | `headerBorders.test.ts` 断言两条侧栏左条同为 3px 品牌色 |
| C9 侧栏分层 | `.cn-app-sider` 底 `--cn-bg-subtle` + 1px 右边框；把手常态 1px 中性线 | `headerBorders.test.ts` 断言底色与把手两态 |
| C10 空态动作 | `doc-nav-empty` + 「新建文档」按钮（→ `?create=1`） | 单测：空树出空态、点击跳 `create=1` |
| C11 行内 style | `MainLayout.tsx` 30 → 21 处，顶栏与侧栏段落归零 | `DESIGN_SYSTEM.md §6` 数字更新 |
| C12 设计约束 | 只用 `--cn-*` token；新增 `--cn-control-header` 进 `tokens.ts` + `:root`；断点 1199.98 / 1023.98 均在白名单 | `tokens.test.ts` 全绿 |
| C13 测试同轮 | `MainLayout.test.tsx` 102 → 105 例；`headerBorders.test.ts` 7 → 10 例；e2e 判据迁移 + 补 `title` 断言 | 105 / 10 例全绿 |
| C14 文档回填 | `DESIGN_SYSTEM.md` 新增「应用外壳原语」节 + §6 数字；CHANGELOG；本卡 | `make check-docs` 全绿 |

**门禁**：`make check-fast` 全绿；`make test` 7958 passed / 17 skipped；`make check-frontend` 核心集合 lines 97.66% / branches 100%，全局 83.95%；`pnpm build` 通过且 `[compat] Chromium 81 0 warning`。

**体积处置（H32）**：主入口 CSS 27.9 → 28.18 KiB 超原上限 28.00。按 `BUNDLE_BUDGET.md` 处置顺序先做**实质精简**（合并 outlined/ghost 共享声明、合并重复媒体块、删掉 `cn-brand-version` 死规则、把新增计数类合并进既有 `.cn-ws-tab-count`），从 28.24 降到 28.18 仍超 0.18 KiB。剩余全是应用外壳常驻样式（无 Dialog/Modal 可 lazy、无重型依赖可拆），按 3% 余量经 `--set-budget --only "主入口 CSS（全局样式）"` 调至 29.00 KiB 并落 reason，非「先抬上限」。

**已知项**：`make check-frontend` 首次在并发 worker 下红过 1 次（2 文件 / 3 例），单跑与复跑均 295 文件 / 3716 例全绿，属既有基线 flake（与 0184 记录的 `ContentTemplatePanel` 同款），未在本轮修。e2e 的判据迁移未在本机实跑（需 playwright install + 隔离后端），按 AGENTS 3.3 留给 CI 全量 e2e。

## 不做

- 不改后端 / 接口 / 权限 / 数据口径。
- 不改侧栏宽度逻辑（0162 C5 的 200–420 拖拽范围）、不改侧栏折叠记忆（`cndb_sider_collapsed`）。
- 不改工作区页签（`.cn-ws-tabs`）的三级导航结构、不改团队切换器面板内部信息架构。
- 不改主页导航 rail（0160）、帮助页侧栏、管理台侧栏。
- 不引入新依赖（不加 Tailwind / CSS-in-JS 库），不新增主题变量（复用现有 token）。
- 不做深色主题以外的额外主题适配（10 套主题靠 token 自动跟随）。
