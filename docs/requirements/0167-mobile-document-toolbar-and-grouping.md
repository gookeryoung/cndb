# 0167 手机端文档列表：工具栏收敛、筛选抽屉与时间分组（S1，P1 + P2）

- 编号：0167
- 来源 / 提出人：用户（会话 2026-11-26，0166 方案评审后回复「继续」）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；设计约束 H24 / H25 / H29 / H30；可见性与权限口径 H33 / H64）
- 状态：已确认（2026-11-26「继续」＝确认实施 0166 方案中余下的 P1 + P2）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。
> 上游卡：0166 实施 P0（移动行单行化），并明确 P1 / P2「待用户另行确认」；本卡承接余下范围。

## 需求原句（逐字）

> 手机端文档和文件列表不够美观紧凑，请结合其他同类产品最佳实践给出方案。

> 开始。

> 继续。

补充确认：本轮实施 **P1（工具栏一行 + 筛选 sheet + 列表/网格切换 + 长按快捷项）** 与 **P2（sticky 时间分组 + 搜索命中高亮）**。

## 方案（口径）

**范围**：仅 `DocumentsPage` 移动端（`useResponsive().isMobile`）工具栏、筛选交互、根层文件夹视图切换、行交互与 `index.css` 移动断点样式；前端单测同轮更新。零后端接口、零数据模型、零迁移、零新增依赖、零部署变更；桌面端工具栏 / 表格 / 卡片逐项不变。

**参考实践**：Google Drive 手机端列表/密度切换；iOS 文件与 Obsidian File Tree Alternative 的 Compact 默认视图；Material 底部 sheet 承载低频筛选；同类移动端列表的「搜索图标点击原地展开」与「长按快捷动作 + ⋯ 常驻」双通道。

**P1 行结构**：移动端工具栏由两行（导航行 + 操作行）压为**一行**：返回 → 面包屑（中间层级省略）→ 搜索图标（点击原地展开输入框）→ 排序 → 筛选（徽标显示已应用数）→ 新建 → 更多；排序与视图切换放「更多」菜单以保一行。标签 / 状态筛选由第三行内联控件改为**底部 Drawer**，带「重置 / 完成」；URL 深链 `?tag=&status=` 与回显口径不变。根层文件夹支持列表 / 网格切换，复用 `cndb_doc_view_v1` 持久化偏好，与桌面 `docView` 同一份状态。

**P2 行结构**：移动端文档块按「置顶 / 今天 / 本周 / 更早」分组，`<768px` 下分组头 sticky；分组只改变展示顺序与标题，不改变 `docSort` 写入的排序偏好，桌面完全不分组。搜索命中片段在移动行标题内高亮，完整标题仍在 `title`。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「不够美观紧凑」（工具栏） | 移动端工具栏只渲染**一个直接子节点**（单行 flex）；返回 / 面包屑 / 搜索 / 排序 / 筛选 / 新建 / 更多同行，不再有第二、第三行 | `DocumentsPage.tsx` | 单测断言 `doc-toolbar-mobile.children` 长度为 1，排序 / 筛选 / 新建 / 更多同行可见 |
| C2 | 「美观」（搜索） | 搜索默认收为图标按钮（`aria-label=搜索文档`），点击后原地展开 `过滤标题` 输入框并可关闭；关键词仍写共享偏好 | `DocumentsPage.tsx` | 单测断言默认无常驻输入框，点击后输入框出现且可再次收起 |
| C3 | 「紧凑」（导航） | 面包屑层级超过 2 层时中间层级省略为「…」，首尾保留；`上一级` 返回按钮仍可用 | `DocumentsPage.tsx` | 单测断言深层路径下省略号出现且根层级可点击 |
| C4 | 「文件列表」（筛选） | 标签 / 状态筛选改底部 Drawer（`placement=bottom`），保留 `doc-tag-filter` / `doc-status-filter` testid 与「重置 / 完成」；筛选按钮保留 `aria-label` 中的已应用计数 | `DocumentsPage.tsx` | 单测断言点击筛选后 Drawer 可见、控件可改 URL、关闭后 Drawer 消失；深链回显用例通过 |
| C5 | 「同类产品最佳实践」（视图） | 移动端根层文件夹支持列表 / 网格切换，复用 `cndb_doc_view_v1` 与 `Segmented` 的 `docView` 状态；入口在「更多」菜单，避免一行过载 | `DocumentsPage.tsx` | 单测断言切到列表后 `doc-series-grid` 消失且 `doc-folder-block` 行表出现；切回网格恢复 |
| C6 | 「不丢能力」（快捷操作） | 移动行长按（≥500ms）弹底部快捷菜单，含详情 / 重命名 / 移动 / 置顶 / 删除；行尾 `⋯` 四项能力与 Portal 冒泡拦截不变，长按不是唯一路径 | `DocumentsPage.tsx` | 单测模拟 touchstart/touchend 触发快捷菜单，且 `⋯` 菜单断言不改即全绿 |
| C7 | 「文件列表」（时间） | 移动端文档块按置顶 / 今天 / 本周 / 更早分组，分组头 `position: sticky`；分组仅展示层，不改 `docSort` 偏好、不改 H33/H64 可见性过滤 | `DocumentsPage.tsx`、`index.css` | 单测断言分组头文本与顺序、分组只出现在移动端；CSS 契约断言 sticky 与 `--cn-*` token |
| C8 | 「美观」（搜索反馈） | 移动端标题命中 `titleKeyword` 时高亮片段（`<mark>`），完整标题仍在 `title`；关键词为空时不渲染多余节点 | `DocumentsPage.tsx`、`index.css` | 单测断言高亮节点存在且文本等于关键词 |
| C9 | （不丢能力） | 既有 testid 全保留：`doc-toolbar-mobile`、`doc-toolbar-filter`、`doc-content-sort`、`doc-toolbar-filters`、`doc-toolbar-select-mode`、`doc-view-toggle`、`doc-series-grid`、`doc-row-*`；URL 深链与批量操作口径不变 | `DocumentsPage.tsx`、`DocumentsPage.test.tsx` | 既有桌面与移动用例不改断言即全绿（视图切换用例除外） |
| C10 | （桌面不回归） | 桌面工具栏、表格、文件夹卡片、筛选气泡、排序 / 深链行为完全不变 | `DocumentsPage.tsx`、`index.css` | 既有桌面用例不改断言即全绿；`make check-fast`、`make test` |
| C11 | （设计约束） | 断点只用 `767.98px` / `575.98px`；间距 / 字号 / 颜色只用 `--cn-*` token；线条用 `--cn-border`；不新增依赖 | `index.css` | `mobileCaliber.test.ts`、`make check-frontend` |
| C12 | （测试 / 文档） | 同轮改写移动端工具栏用例、补 Drawer / 视图 / 分组 / 长按断言；CHANGELOG 增条目；0166 卡标注后续修订见 0167 | `DocumentsPage.test.tsx`、`mobileCaliber.test.ts`、`CHANGELOG.md`、`0166-*.md` | `make flow` / `pnpm test` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 移动端两行工具栏 / 第三行筛选 | `DocumentsPage.tsx` `isMobile ?` 工具栏分支 | C1/C2/C3/C4 |
| 2 | 面包屑节点 | `DocumentsPage.tsx` `breadcrumbNode` | C3 |
| 3 | 根层文件夹网格 / 列表渲染条件 | `DocumentsPage.tsx` `docView` 分支 | C5 |
| 4 | 行点击与长按 | `DocumentsPage.tsx` `renderDocRow` | C6 |
| 5 | 文档列表分组与标题 | `DocumentsPage.tsx` `fileItems` 渲染 | C7/C8 |
| 6 | 移动断点样式 | `index.css` `767.98px` 段 | C7/C11 |
| 7 | 移动端工具栏用例 | `DocumentsPage.test.tsx` | C12 |

## 不做

- 桌面端任何结构 / 样式调整。
- 后端接口、可见性过滤、权限判定、数据模型与迁移。
- 新增依赖、swipe 作为唯一操作路径、修改 `docSort` 偏好写入逻辑。
- 0166 P0 已落地的单行行结构再改动（除 C6/C8 必要扩展）。

## 落地结果（2026-11-26，P1 + P2）

- C1/C2/C3：移动端工具栏改单行 flex；搜索收为图标按钮，点击原地展开 / 关闭时清空关键词；面包屑超过两层折叠中间层级为「…」。
- C4：标签 / 状态筛选改 `Drawer placement=bottom`（`size=auto`），带「重置 / 完成」；筛选按钮保留已应用计数徽标，`doc-tag-filter` / `doc-status-filter` 与 `?tag=&status=` 深链回显不变。
- C5：根层文件夹列表 / 网格切换复用 `docView` 与 `cndb_doc_view_v1`，入口在移动端「更多」菜单；默认列表，桌面行为不变。
- C6：`renderRowActions` 抽出 `rowActionItems` 供 ⋯ 与长按底部菜单共用；长按 500ms 触发，click 抑制防止误跳转，⋯ 常规路径保留。
- C7/C8：移动端文档块按置顶 / 今天 / 本周 / 更早分组，分组头 sticky（`--cn-bg-subtle` / `--cn-border`）；命中关键词用 `<mark class="cn-doc-hit">` 高亮，完整标题仍在 `title`；桌面无分组、无高亮。
- C9/C10/C11：既有 testid 与批量操作 / URL 口径保留；桌面用例不改断言即全绿；`index.css` 只加 `767.98px` 断点规则，全用 `--cn-*` token，无新增依赖。
- C12：`DocumentsPage.test.tsx` 改写工具栏用例、补视图切换 / 长按 / 分组 / 高亮 4 例；`mobileCaliber.test.ts` 补 sticky 与 token 契约。测试中发现标题过滤关键词为模块级缓存（`docTreeSort.cachedTitleFilter`），`storage.clear()` 无法复位，已在移动端 describe 的 `afterEach` 内 `act(() => setDocTitleFilter(''))` 隔离，避免污染后续桌面用例。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方已确认范围（2026-11-26「继续」）
- [x] 全量门禁已通过并回填 CHANGELOG：`make check-fast` 0 error（15 条存量 ADR warning）、`make test` 全绿、`make check-frontend` 全绿（核心 lines 97.66% / branches 100%）
