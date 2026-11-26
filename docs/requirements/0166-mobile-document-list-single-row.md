# 0166 手机端文档 / 文件列表单行紧凑化（S1，P0）

- 编号：0166
- 来源 / 提出人：用户（会话 2026-11-26）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；样式口径见 H24 / H25 / H29 / H30；可见性与权限口径见 H33 / H64）
- 状态：已确认（2026-11-26 用户审阅方案后回复「开始」，范围 = P0）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。
> 与旧卡关系：0044 C9/C10、0134 C6、0162 C6 曾规定「移动端维持两行」，该口径由本卡 P0 修订为单行；旧卡原文保留历史，当前口径以本卡为准。
> 后续修订：P1（工具栏一行 + 筛选 sheet + 列表/网格切换）与 P2（时间分组 + 搜索高亮）见 0167，本卡只覆盖 P0。

## 需求原句（逐字）

> 手机端文档和文件列表不够美观紧凑，请结合其他同类产品最佳实践给出方案。

> 开始。

补充确认（2026-11-26，用户审阅方案后的选择）：仅实施 **P0（行内降噪）**；P1（工具栏一行 + 筛选 sheet + 列表/网格切换）与 P2（sticky 分组）本期不做。

## 方案（口径）

**范围**：仅 `DocumentsPage` 移动端（`<768px`）列表行 `renderDocRow`、移动端多选入口、对应 `index.css` 移动断点样式与前端单测。零后端接口、零数据模型、零迁移、零部署变更、零新增依赖；桌面端（`DocumentTable` 与桌面工具栏、文件夹卡片）逐项不变。

**参考实践**：Google Drive 手机端网格/列表切换与单行小图标；iOS 文件 / Pttrns 的 leading 图标 + 标题 + trailing 元信息 + hairline 分隔；Obsidian File Tree Alternative 的 Compact（仅文件名）与 Preview 分层；Obsidian 插件设计标准的「状态绝不只用颜色」「今天 / 昨天 + HH:mm」「放大点击区而非装饰图标」。

**行结构（移动端）**：格式 / 文件夹图标 → 标题（单行省略、完整名进 `title`）→ 主状态图标（草稿 Edit / 已发布 CheckCircle / 归档 Inbox，颜色仅辅助）→ 相对时间 → 行尾 `⋯`。移除描述行；大小 / 版本数 / 标签数 / 多状态分布移入 `⋯ → 详情` 弹窗。置顶由文字 Tag 改 `PushpinOutlined`；私有用 `LockOutlined` + Tooltip；文件夹带子孙聚合状态与「N 项」计数。

**多选模式**：移动端勾选框默认不渲染（横向空间让给标题）；`⋯` 工具栏菜单新增「多选 / 退出多选」入口，进入后行与文件夹卡片显示勾选框、整行点击改为切换选中，退出时清空选择。桌面勾选框恒显不变。

**既有 testid 与行为全保留**：`doc-select-*`、`doc-pinned-tag-*`、`doc-list-status-<id>-<status>`、`doc-list-visibility-*`、`doc-row-more-*` 及重命名 / 移动 / 置顶 / 删除菜单与确认逻辑不变；`⋯` 菜单的 Portal 冒泡拦截不变。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「不够美观紧凑」 | 移动端列表行由两行降为**单行**：不渲染 `description`；行内边距在移动断点再收紧一档 | `DocumentsPage.tsx`、`index.css` | 单测断言移动列表内无 `.cn-list-meta-description`；CSS 契约断言移动断点内 `.cn-doc-list .ant-listy-item` 用 `var(--cn-space-xs)` |
| C2 | 「美观」（状态表达） | 置顶 / 状态 / 私有改为图标：置顶 `PushpinOutlined`、草稿 `EditOutlined` / 已发布 `CheckCircleOutlined` / 归档 `InboxOutlined`、私有 `LockOutlined`；颜色仅辅助，语义保留 `aria-label` / Tooltip | `DocumentsPage.tsx` | 单测断言三个状态 testid 仍在行内、可见性 testid 的 `aria-label` 为「仅自己可见」、置顶 testid 带 `aria-label=置顶` |
| C3 | 「紧凑」（信息降噪） | 大小 / 版本号 / 标签计数 / 文件夹多状态分布不占列表行，收进移动端 `⋯ → 详情` 弹窗；详情保留完整时间 | `DocumentsPage.tsx` | 单测断言行内无 `v\\d+` 与大小文本；点 `doc-row-detail-*` 后弹窗含完整时间与大小 / 版本 |
| C4 | 「文件列表」（时间） | 行内相对时间复用 `frontend/src/utils/datetime.ts::formatRelativeTime`（不新增时钟 / 不新建函数）；完整时间在详情与 `title` 保留 | `DocumentsPage.tsx`、`utils/datetime.ts` | 单测断言行内相对时间文本；既有 `datetime.test.ts` 全绿 |
| C5 | 「文件列表」（文件夹） | 文件夹行显示子孙聚合状态图标 + 「N 项」计数，口径沿用 `buildFolderStatusCounts`；空文件夹不误报草稿 | `DocumentsPage.tsx` | 既有 `buildFolderStatusCounts` 用例全绿；单测断言文件夹行计数可见 |
| C6 | 「不够美观紧凑」（选择） | 移动端勾选框默认隐藏，仅「多选模式」显示；整行点击在多选模式下切换选中；退出多选清空 `selectedIds` | `DocumentsPage.tsx` | 单测断言默认无 `doc-select-*`、开启多选后可见且点击行只切换选中、退出后批量栏消失 |
| C7 | （不丢能力） | 行尾 `⋯` 四项操作（重命名 / 移动 / 置顶 / 删除）+ 删除二次确认 + Portal 冒泡拦截不变；工具栏「更多」菜单原有入口不变 | `DocumentsPage.tsx` | 既有移动端「更多」与删除用例不改断言即全绿 |
| C8 | （桌面不回归） | 桌面端列表、表格、工具栏、文件夹卡片、选择模式与排序 / 筛选 / 深链行为完全不变 | `DocumentsPage.tsx`、`index.css` | 既有桌面用例不改断言即全绿；`make check-fast`、`make test` |
| C9 | （设计约束） | 断点只用 `767.98px` / `575.98px`；间距 / 字号 / 颜色只用 `--cn-*` token；选中态用 `--cn-bg-selected`；线条用 `--cn-border`；不新增依赖 | `index.css` | `frontend` 静态 / 覆盖率门禁、`mobileCaliber.test.ts` |
| C10 | （测试 / 文档） | 同轮更新 `DocumentsPage.test.tsx` 移动行用例（单行、图标、详情、多选）；`mobileCaliber.test.ts` 补行高度口径断言；CHANGELOG 增条目 | `DocumentsPage.test.tsx`、`mobileCaliber.test.ts`、`CHANGELOG.md` | `pnpm test` / `make flow` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 移动行两行结构（标题 + 描述） | `DocumentsPage.tsx` `renderDocRow` | C1 / C2 / C3 / C4 |
| 2 | 常驻勾选框（行 + 文件夹卡片） | `DocumentsPage.tsx` avatar / 卡片 | C6 |
| 3 | 工具栏「更多」菜单 | `DocumentsPage.tsx` `mobileToolbarMenu` | C6 新增多选入口 |
| 4 | 移动列表紧凑样式 | `index.css` 文档列表移动断点 | C1 / C9 |
| 5 | 既有移动行用例 | `DocumentsPage.test.tsx` | C10 改写定位 |

## 不做

- 桌面端任何结构与样式调整。
- 移动端工具栏收成一行、底部筛选 Drawer、列表 / 网格切换、sticky 分组（属 P1 / P2）。
- 后端接口、可见性过滤、权限判定、数据模型与迁移。

## 落地结果（2026-11-26，P0）

- C1/C2/C4：`renderDocRow` 移动分支改单行；置顶 / 主状态 / 私有用图标，时间复用 `formatRelativeTime`；`documentDisplay.ts` 新增 `DOC_STATUS_META`，`DocumentTree` 改为引用同一映射。
- C3：移动端 `⋯ → 详情` Modal 承载大小 / 版本 / 标签数 / 状态分布 / 完整时间；文件夹「N 项」计数仍在行内。
- C5：文件夹主状态按 `buildFolderStatusCounts` 以「草稿 > 归档 > 已发布」优先取一枚，空文件夹不误报草稿。
- C6：工具栏「更多」新增「多选 / 退出多选」；移动端勾选框按需渲染，整行点击切换选中，退出清空选择；桌面分支不变。
- C7/C8：行尾四项操作、删除二次确认、桌面列表与工具栏全部保持原口径；`DOC_STATUS_META` 的颜色用 token，无裸色值。
- C9/C10：`index.css` 仅改 `767.98px` 断点内文档列表规则；`DocumentsPage.test.tsx` 与 `mobileCaliber.test.ts` 同轮更新，另补 2 例（详情弹窗 / 多选模式）。
- P1（工具栏一行 + 筛选 sheet + 列表/网格切换）与 P2（时间分组 sticky 头）本期不做，待用户另行确认。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方已确认方案与 P0 范围（2026-11-26「开始」）
