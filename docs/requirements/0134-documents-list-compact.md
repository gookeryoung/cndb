# 需求卡片：文档列表对齐 ima 式紧凑单行（P1）

- 编号：0134
- 来源 / 提出人：用户（会话 2026-11-11）
- 日期：2026-11-11
- 关联 ADR：无（S1，方案并入本卡片；样式口径见 H24 / H25 / H29 / H30）
- 状态：已确认（2026-11-11，用户选择 P1「单行列表」+「摘要隐藏，标签计数保留」）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 文档模块，对齐ima知识库的文档列表设计，有无可以借鉴的，使其美观紧凑

补充确认（2026-11-11 用户选择）：

> 按 P1 推进：桌面端单行列表 + 右侧 meta 列，标签降噪，移动端保持两行。
> 列表里的摘要隐藏，标签计数保留。

## 方案（口径）

**范围**：仅文档管理页列表行（`DocumentsPage` 的 `renderDocRow` / `renderRowActions`）与其样式、单测、CHANGELOG。零后端接口、零数据模型、零迁移、零部署变更、零新增依赖。

**桌面端（≥768px）单行**：勾选框 + 格式图标 + 标题（超长单行省略、`title` 悬停看全名）→ 置顶图钉 → 状态圆点 + 文本 → 仅自己可见锁图标 → `N 个标签` → 右侧固定两列：大小（右对齐）、更新时间（右对齐）→ 行尾「⋯」操作。列表不再渲染第二行描述，摘要与版本号移出列表（版本仍可在版本抽屉查看）。

**标签降噪**：置顶由彩色 `Tag` 改为图钉图标；状态由彩色胶囊改为 antd `Badge` 状态圆点 + 文本（draft=default / published=success / archived=warning，沿用现有色义）；仅自己可见由胶囊改为锁图标 + 既有 Tooltip；标签只保留计数文本。

**操作收敛**：桌面与移动端统一为行尾「⋯」下拉，菜单项（重命名 / 移动 / 置顶 / 删除）与二次确认逻辑、现有 `doc-row-*` testid 全部保留。

**移动端（<768px）**：维持现有两行结构与既有紧凑规则，不改行为、不改 testid 语义。

**不做**：表头列与点击排序、文件夹 / 文档混排、hover 勾选或批量模式切换、拖拽上传、列表 / 网格切换、工具栏收敛、外框与分隔线体系调整（属后续档位）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「美观紧凑」 | 桌面端列表行单行渲染：不渲染 `description` 行；行高由两行降为一行 | `frontend/src/pages/documents/DocumentsPage.tsx` | 单测断言列表内无 `.cn-list-meta-description`；行内仅一个标题行 |
| C2 | 「对齐 ima 文档列表」 | 右侧 meta 固定两列：大小（文件夹留空占位）、更新时间，均右对齐；长标题单行省略并带 `title` | `DocumentsPage.tsx`、`frontend/src/index.css` | 单测断言 `doc-row-meta-<id>` 存在、含大小与时间、标题带 `title` |
| C3 | 「美观紧凑」 | 摘要不在列表展示；版本号移出列表行（版本抽屉能力不变） | `DocumentsPage.tsx` | 单测断言列表行不含摘要与 `v<version>` 文本 |
| C4 | 「美观紧凑」 | 置顶图钉、状态 `Badge` 圆点 + 文本、仅自己可见锁图标、`N 个标签` 计数；保留 `doc-pinned-tag-<id>` / `doc-list-visibility-<id>` testid 与 aria 语义 | `DocumentsPage.tsx` | 既有可见性 / 置顶用例改造后全绿；新增桌面行标签断言 |
| C5 | （操作） | 桌面与移动端统一「⋯」下拉；重命名 / 移动 / 置顶 / 删除菜单项、二次确认与 `doc-row-*` testid 不变 | `DocumentsPage.tsx` | 单测：打开「⋯」后四项均在，且各操作请求口径不变 |
| C6 | （移动端） | `<768px` 维持两行结构、现有紧凑样式与交互口径不变 | `DocumentsPage.tsx`、`index.css` | 既有移动端用例全绿 |
| C7 | （设计约束） | 线条沿用 H25（1px `--cn-border`）；间距 / 字号 / 颜色只用 `--cn-*` token；不新增颜色 token；选中态如启用须用 `--cn-bg-selected`（本次不新增选中底色）；不新增依赖 | `index.css` | `make frontend-static`、`make frontend-coverage` |
| C8 | （边界） | 不改接口、排序 / 筛选 / 搜索 / 批量 / 导入导出 / 系列卡片 / 回收站行为；不改后端 | 全仓 | 变更文件清单核对；`make flow` |
| C9 | （测试） | 同一轮更新 `DocumentsPage.test.tsx`：桌面换行布局用例改为单行断言，三处行操作用例改为先开「⋯」；不删用例、不放宽断言 | `frontend/src/pages/documents/DocumentsPage.test.tsx` | `pnpm test` / `make frontend-coverage` 全绿 |
| C10 | （文档） | CHANGELOG 增变更条目；无需改动帮助文案与接口文档 | `CHANGELOG.md` | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 列表行两行结构（标题 + 描述） | `frontend/src/pages/documents/DocumentsPage.tsx:724-859` | 桌面改为单行（C1/C2/C3） |
| 2 | 桌面行尾四枚常驻操作 | `DocumentsPage.tsx:592-657` | 收敛为「⋯」（C5） |
| 3 | 桌面标题行彩色 Tag | `DocumentsPage.tsx:781-805` | 图钉 / Badge / 锁图标 / 计数（C4） |
| 4 | 列表行紧凑样式 | `frontend/src/index.css:5188-5234` | 标题单行省略与 meta 列（C2） |
| 5 | 桌面换行布局用例 | `DocumentsPage.test.tsx:717-726` | 改为单行断言（C9） |
| 6 | 桌面行操作用例直接点图标 | `DocumentsPage.test.tsx:728-781` | 改为先开「⋯」（C5/C9） |

## 未决问题

- 无。桌面 / 移动端分工、摘要与标签处理、操作收敛方式均已由用户确认。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
