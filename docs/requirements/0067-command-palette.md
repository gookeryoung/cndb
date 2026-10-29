# 需求卡片：全局搜索命令模式（⌘K Command Palette）

- 编号：0067（与 ADR `docs/adr/0067-*.md` 同号，卡片存 `docs/requirements/0067-command-palette.md`）
- 来源 / 提出人：用户（GitHub 对齐分析 · 差距 3：`⌘K` 只有搜索，没有命令模式）
- 日期：2026-10-29
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 在 `GlobalSearch` 面板基础上加**命令模式**（输入 `>` 前缀切换）：新建表/文档/工作区、切换主题、跳转最近工作区、打开设置页签——全部是前端路由动作，无后端改动。（上下文：GitHub 的 command palette 是「搜索 + `>` 命令 + `#` 跳转」三合一；本项目 `⌘K` 只收敛到搜索。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 输入 `>` 前缀切换 | 输入框内容以 `>` 开头时进入命令模式：面板替换为命令列表（按关键词子串过滤命令标题，大小写不敏感），不再发起搜索请求（既有去抖 query 保持 `enabled` 不含命令模式输入）；删除 `>` 回到搜索模式 | `frontend/src/components/GlobalSearch.tsx` | `GlobalSearch.test.tsx`：输入 `>` 后无 workspace-search 请求、展示命令列表；退格回搜索模式 |
| C2 | 命令注册表 | 命令定义为独立模块（`frontend/src/components/commands.ts`）：每条命令含 `key / 标题 / 关键词别名 / 执行动作(返回 navigate 或回调)`；面板渲染与键盘导航只依赖该表，不内联命令实现 | `frontend/src/components/commands.ts`（新增）、`GlobalSearch.tsx` | 单测：命令表结构（key 唯一、标题非空） |
| C3 | 命令集合（首批） | 首批命令：① 新建数据表 ② 新建文档 ③ 新建工作区 ④ 切换主题：浅色 / 深色 / 跟随系统（调用 `useTheme().setMode`）⑤ 打开个人设置（复用 ui store `openSettings`）⑥ 打开大模型设置（`openSettings('llm')`）⑦ 帮助文档（`/help`）⑧ 工作区列表（`/w`）。①②③ 的页面新建入口为页面内按钮，为其补 URL 触发口径：TablesList / DocumentsPage / WorkspaceList 各自识别 `?create=1`（幂等：打开后移除该参数避免刷新重复弹出），触发与页面内新建按钮相同的弹窗/流程；不得新造后端调用 | `commands.ts`、`GlobalSearch.tsx`、`TablesList.tsx`、`DocumentsPage.tsx`、`WorkspaceList.tsx` | 单测逐条执行断言路由 / store / 弹窗变化 |
| C4 | 键盘导航复用 | 命令模式下 ↑↓ 移动高亮、Enter 执行、Esc 收起，与搜索结果共用同一套 activeIndex 逻辑；执行后清空输入并收起面板 | `GlobalSearch.tsx` | `GlobalSearch.test.tsx` 键盘用例 |
| C5 | 提示与可发现性 | 搜索框占位或面板头部提示「输入 > 查看命令」；命令模式下空结果显示「无匹配命令」 | `GlobalSearch.tsx`、`index.css`（如需） | 单测断言提示存在 |
| C6 | 既有搜索行为不变 | 非 `>` 输入时全部既有行为（范围选择器、去抖、分组、testid、快捷键 ⌘K / `/`）保持不变；既有用例零改写（新增不改旧） | `GlobalSearch.tsx` | 既有 `GlobalSearch.test.tsx` 全绿 |
| C7 | 无后端改动 | 全部命令为前端动作（路由跳转 / store / localStorage），不新增任何 API 端点 | 全部 | 后端测试零改动，`make test` 全绿 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 全局搜索面板与键盘导航 | `frontend/src/components/GlobalSearch.tsx:68-180`（items/activeIndex/onKeyDown/openItem） | 命令模式复用同一面板层 |
| 2 | 快捷键监听 | `GlobalSearch.tsx:113-131`（⌘K / `/`） | 不改；`>` 只是输入内容前缀 |
| 3 | 搜索请求去抖 | `GlobalSearch.tsx:79-108`（useQuery enabled） | 命令模式下不请求（C1） |
| 4 | 主题切换 / 设置入口 | `theme/ThemeProvider.tsx`（`setMode`）、`store`（`openSettings`） | 命令直接调用 |
| 5 | 新建入口路由 | `pages/workspace/TablesList.tsx`、`pages/documents/DocumentsPage.tsx`、`WorkspaceList.tsx` | ADR 精查各页新建触发方式（URL 参数 or 页面内按钮），避免新造 query 口径 |
| 6 | 面板样式 | `frontend/src/index.css`（`.cn-gs-*`） | 命令列表沿用分组样式，预计少量新增类 |
| 7 | e2e | `frontend/tests/e2e/critical/` | 搜索快捷键相关用例行为不变（C6） |

## 未决问题

- [x] 新建表 / 文档 / 工作区是否纳入首批？→ 结论：**纳入**（需求方 2026-10-29 确认），为三页补 `?create=1` URL 触发口径（幂等，打开后移除参数）。
- [x] 命令模式是否需要独立快捷键（如 GitHub 的 `⌘.`）？→ 结论：不需要，`>` 前缀即可（与需求原句一致），减少快捷键占用冲突。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-29）
