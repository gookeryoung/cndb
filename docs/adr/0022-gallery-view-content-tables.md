# ADR 0022: 卡片画廊视图（gallery）与 LLM 抓取资讯示例

Status: Implemented（P0-P1 已落地，2026-10-22）
Date: 2026-10-22
Related: `docs/requirements/0022-gallery-view-content-tables.md`、`docs/adr/0003-view-visibility-permission-model.md`、`docs/adr/0011-stock-kline-enhanced.md`、`docs/adr/0021-home-favorite-views-panel.md`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py`、`examples/datasets/工作区-数据源示例/views.json`
需求卡片: `docs/requirements/0022-gallery-view-content-tables.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C8），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 针对这两种通过LLM抓取的数据表 | 两张 CSV 去掉系统 `id` 列后放入 `examples/datasets/工作区-数据源示例/`，seed 按文件名建表；字段名保持英文原样，视图配置可直接复用到用户同结构表 |
| C2 | 设计合适的视图 | 新增 `view_type=gallery`：卡片栅格（标题 / 摘要 / 彩色标签 / 日期 / 元信息），点击卡片打开行详情；`view_options` 七项由 `GALLERY_OPTIONS` 定义 |
| C3 | 用于用户查看资讯 | 两表各 5-7 个视图（画廊默认 + grid + kanban + matrix / calendar + chart + 过滤视图），配置见 §Decision 9 |
| C4 | 用于分享资讯 | 视图仍走 ADR 0003 三档可见性；seed `scope=global` → `ViewVisibility.TABLE`，表内成员均可见；分享用深链与收藏，不扩匿名公开分享（ADR 0003 D5） |
| C5 | （兼容既有视图） | `ViewMode` / `VALID_MODES` / `MODE_BUTTONS` / `MODE_VIEW_TYPES` 扩为 11 种；`view_type` 无枚举约束，零迁移 |
| C6 | （配置可编辑） | `GALLERY_OPTIONS` 同时供创建表单与视图设置对话框；默认值由 `resolveOpts` 回退 |
| C7 | （数据量边界） | 沿用 `VIEW_FETCH_ALL_LIMIT = 2000`；画廊前端每批 48 张 + 「加载更多」 |
| C8 | （字段引用校验） | 后端 / seed 两处 `_validate_view_fields` 增加 `summary_field` 单值与 `tag_fields` / `meta_fields` 列表逐项校验 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 视图模式注册为 10 种：`grid/tree/kanban/calendar/gantt/wbs/matrix/chart/kline/flow`；`ViewMode` 与 `VALID_MODES` 为白名单，URL / localStorage 校验共用 | `frontend/src/pages/grid/views/viewModes.ts:11-14` | 新模式不进白名单会被过滤，`?mode=gallery` 无效 | 确认 |
| 2 | 视图栏模式按钮 `MODE_BUTTONS` 与「视图类型 → 模式」推导 `MODE_VIEW_TYPES` 各自硬编码类型集合 | `frontend/src/pages/grid/GridPage.tsx:125-136`、`GridPage.tsx:346` | 新增类型需两处同步，否则按钮不出现 / 视图打开落回 grid | 确认 |
| 3 | 视图专属配置唯一真相源为 `viewOptionSchema.ts`（创建表单与 ViewConfigDialog 共用） | `frontend/src/pages/grid/view-config/viewOptionSchema.ts:50-545` | 新视图类型只需新增 schema + `getOptionSchema` 分支 | 确认 |
| 4 | `DataView.view_type` 为自由 `String(32)`，无枚举 / 无迁移 | `src/cndb/plugins/tables/models.py`（`DataView`） | 新类型零 DDL | 确认 |
| 5 | 视图字段引用校验为两套同口径白名单；列表型 option 未处理，`list in set` 会抛 TypeError | `src/cndb/plugins/tables/routers/views.py:48-145`、`src/cndb/cli/seed/views.py:13-146` | 直接把 `tag_fields` 加进白名单会让保存 500 | 新增 |
| 6 | seed 视图默认 `scope=global` → `owner_id=None` + `ViewVisibility.TABLE`；`is_default` 仅 table 档生效 | `src/cndb/cli/seed/views.py:199-244` | 默认画廊对表内全员可见，符合「工作区内共享」 | 确认 |
| 7 | 非 grid 视图一次拉取上限 `VIEW_FETCH_ALL_LIMIT = 2000`，排序由服务端按视图 `sortings` 应用 | `frontend/src/pages/grid/useGridData.ts:21-38` | 画廊无需客户端排序；2000 卡片需分批挂载 | 确认 |
| 8 | 视图匿名公开分享已明确不复活（ADR 0003 D5）；文档分享（ADR 0017）不适用于表 / 视图 | `docs/adr/0003-view-visibility-permission-model.md` | 分享范围限定工作区内 | 确认 |
| 9 | seed CSV 建表时低基数文本自动提升 select（`region/topic/trend/cuisine/difficulty`），日期 / 数字按值推断 | `src/cndb/plugins/tables/services/transfer/normalize/promote.py:21-79` | 彩色标签、看板分组、矩阵轴可直接使用 | 新增 |
| 10 | `_row_to_dict` 把物理列 `id` 映射为 `result["id"]`；CSV 导出的首列 `id` 是系统行 ID | `src/cndb/plugins/tables/services/core/records.py:834-851` | 示例 CSV 必须去掉 `id` 列，否则建出同名业务字段并覆盖行 ID | 新增 |
| 11 | seed 完整性测试静态解析 CSV 表头 + `valid view types` 白名单 | `tests/test_backup_seed_roundtrip.py:349`、`:439-455`、`:533-542` | 新表无需硬编码字段；类型集合与引用提取需同步 | 新增 |

**核心缺陷（需求要补的）**：现有 10 种视图没有「阅读态」——grid 长文本截断、kanban 卡片只显示标题与少量标签、chart 只做聚合，LLM 抓取的资讯 / 菜谱类内容缺少可浏览、可分享的卡片墙。

设计目标（不变量）：

- **I1 零迁移**：新增视图类型不产生 DDL，存量 `view_type` 语义不变。
- **I2 阅读态与数据态分离**：gallery 只读（不内联编辑 / 不拖拽 / 不选中），编辑仍回 grid。
- **I3 配置向后兼容**：`view_options` 缺字段时由 schema 默认值 / 自动推断兜底，不阻断打开。
- **I4 分享边界不变**：不新增匿名读接口，可见性判定继续复用 `view_access`。

## Decision

### 1. 数据模型

无迁移。`DataView.view_type = 'gallery'`，配置存 `view_options` JSON，键固定为：

| key | kind | 字段类型 | 默认 / 说明 |
|---|---|---|---|
| `title_field` | field_select | text / longtext | 留空自动取首个 text 字段，再退 `id` |
| `summary_field` | field_select | longtext / text | 留空自动取首个 longtext 字段 |
| `tag_fields` | field_multi_select | select / multiselect / text | 彩色标签，单卡最多 6 个 |
| `meta_fields` | field_multi_select | select / multiselect / number / float / percentage / date / datetime / text | 底部元信息，最多 4 项 |
| `date_field` | field_select | date / datetime | 卡片右上日期徽章（取前 10 位） |
| `card_size` | enum_select | `small` / `medium` / `large` | 默认 `medium`，列最小宽 220 / 280 / 360px |
| `summary_lines` | number_enum | 2 / 3 / 4 / 6 | 默认 3 |

排序不新增配置：沿用视图 `sortings`（服务端生效），与 grid 同口径。

### 2. 判定算法（唯一入口）

`frontend/src/pages/grid/views/galleryBoard.ts`：

- `resolveGalleryConfig(fields, opts)` — 唯一配置解析入口，应用上表默认值与自动推断；`GalleryView` 不得自行回退。
- `galleryTagLabels(field, value)` — select 取 option label、multiselect 逐项取 label、text 原样；空值剔除；最多 6 个，超出以 `+N` 表示。
- `galleryMetaItems(fields, row, metaFields)` — 复用 `formatFieldDisplayValue`，空值跳过，最多 4 项。
- `GALLERY_BATCH_SIZE = 48`；`GALLERY_COLUMN_MIN_PX` 为 `card_size` 到最小列宽的映射。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/tables/{tid}/views` | 无签名变更；`view_options.summary_field` / `tag_fields` / `meta_fields` 新增字段引用校验 |
| `PATCH /api/v1/workspaces/{wid}/tables/{tid}/views/{vid}` | 同上 |
| seed `_seed_views` | 同口径校验，不通过则跳过该视图并打印 |

### 4. 边界与例外

1. gallery 不做内联编辑、拖拽、行选中与批量操作；编辑入口仍为 grid / 行详情。
2. 不配置 `date_field` 时卡片不显示日期徽章；`meta_fields` / `tag_fields` 为空或值全空时整块省略。
3. 非 grid 模式最多 2000 行；超出部分需通过视图 `filters` 收窄（与 kanban / kline 同口径），不做分页拉取。
4. 卡片点击走 `onRowClick`（行详情 Drawer），不直接跳转外链；`url` 这类外链字段可放进 `meta_fields` 展示。
5. 视图分享沿用三档可见性 + 深链 + 收藏；不新增「复制公开链接」。

### 5. 迁移

无（`view_type` 自由字符串；`view_options` 为 JSON）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 纯逻辑 | `frontend/src/pages/grid/views/galleryBoard.ts` | 新增：配置解析 / 标签归一 / 元信息 / 列宽与批次常量 |
| 视图组件 | `frontend/src/pages/grid/views/GalleryView.tsx` | 新增：卡片栅格、分批渲染、空态、测试锚点 |
| 模式注册 | `frontend/src/pages/grid/views/viewModes.ts` | `ViewMode` / `VALID_MODES` 加 `gallery` |
| 页面集成 | `frontend/src/pages/grid/GridPage.tsx` | lazy import、`MODE_BUTTONS`、`MODE_VIEW_TYPES`、渲染分支 |
| 配置 schema | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | `GALLERY_OPTIONS` + `getOptionSchema('gallery')` |
| 创建表单 | `frontend/src/pages/grid/view-config/CreateEditViewForm.tsx` | 视图类型下拉加「卡片画廊 (Gallery)」 |
| 表设置 | `frontend/src/pages/settings/TableSettingsPage.tsx` | `VIEW_MODE_META` 加画廊标签与图标 |
| 主页收藏 | `frontend/src/pages/workspace/MyViewsPanel.tsx` | 类型中文名与图标 |
| 帮助 | `frontend/src/components/helpContent.tsx` | 视图类型说明新增画廊条目，快速上手文案改为「多种视图」 |

### 7. 测试清单

**判定层（单测）**：`galleryBoard.test.ts`（回退链 / 非法值回退 / 标签归一与上限 / 元信息跳过空值 / 列宽映射）、`GalleryView.test.tsx`（渲染 / 点击与键盘 / 分批与重置 / 空态）、`viewModes.test.ts`（11 种）、`viewOptionSchema.test.ts`（7 项 schema 与默认值）。

**接口层**：`tests/test_views_api.py`（gallery 合法 201；`summary_field` 非法 400；`tag_fields` 含非法项 400 带下标；非字符串项 400 不 500）。

**迁移 / 备份**：`tests/test_backup_seed_roundtrip.py`（11 种类型全覆盖、列表型字段引用可解析、CSV 表头静态校验通过）。

**e2e（前端）**：`frontend/tests/e2e/critical/gallery-view.spec.ts`（默认落画廊、卡片数与标签、点击展开行详情、第二张表同样渲染）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | gallery 类型 + 组件 + 配置 schema + 注册清单 + 后端 / seed 校验 | 低（零迁移，不改既有视图语义） |
| **P1** | 两张示例 CSV 与视图配置、完整性测试、e2e、文档 | 低（seed 幂等，失败只跳过单表 / 单视图） |

### 9. 示例视图配置（种子落地值）

**国际形势发展动态**（`date,region,source,summary,title,topic,trend,url`）：

| order | 视图 | 类型 | 配置摘要 |
|---|---|---|---|
| 0 | 资讯画廊（默认） | gallery | `title_field=title`、`summary_field=summary`、`tag_fields=[region,topic,trend]`、`meta_fields=[source]`、`date_field=date`、`summary_lines=3`；sortings `[date desc, title asc]` |
| 1 | 全部资讯 | grid | sortings `[date desc, title asc]` |
| 2 | 态势看板 | kanban | `group_field=trend`、`title_field=title`、`priority_field=topic`、`card_fields=[region,date]` |
| 3 | 地区议题矩阵 | matrix | `row_field=region`、`column_field=topic`、`title_field=title` |
| 4 | 每日简报日历 | calendar | `start_field=date`、`title_field=title`、`group_field=topic` |
| 5 | 议题与态势分布 | chart | `charts[]`：饼图 `topic`（measure=`title`, count）+ 柱图 `trend`（measure=`title`, count） |
| 6 | 升温议题 | grid | filters `trend = 升温`；sortings `[date desc, title asc]` |

**美食推荐做法**（`cook_time_min,cuisine,difficulty,dish_name,ingredients,steps,tips`）：

| order | 视图 | 类型 | 配置摘要 |
|---|---|---|---|
| 0 | 菜谱画廊（默认） | gallery | `title_field=dish_name`、`summary_field=steps`、`tag_fields=[cuisine,difficulty]`、`meta_fields=[cook_time_min]`、`summary_lines=4`；sortings `[cook_time_min asc, dish_name asc]` |
| 1 | 全部菜谱 | grid | sortings `[cook_time_min asc, dish_name asc]` |
| 2 | 按菜系看板 | kanban | `group_field=cuisine`、`title_field=dish_name`、`priority_field=difficulty`、`card_fields=[cook_time_min]` |
| 3 | 快手菜（≤40分钟） | grid | filters `cook_time_min <= 40`；sortings `[cook_time_min asc, dish_name asc]` |
| 4 | 菜系与时长概览 | chart | `charts[]`：直方图 `cook_time_min` + 饼图 `cuisine`（measure=`dish_name`, count） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 资讯阅读的落地形态 | 新增独立 `view_type=gallery` | 卡片墙是阅读态，不是 grid / kanban 的配置变体；独立类型才能有专属 schema 与懒加载 | 复用 kanban 卡片列（缺摘要、夹带拖拽/完成语义）；grid 加行高（长文本仍截断、无卡片感） | `views/GalleryView.tsx`、`views/viewModes.ts` |
| D2 | gallery 配置字段集 | 7 项：title / summary / tag / meta / date / size / lines | 覆盖「标题 + 摘要 + 标签 + 日期 + 元信息」的最小阅读单元；排序交给视图 sortings | `cover_field`（两表无图片列）；`group_field`（分组需求由 kanban 承担）；`card_sort_*`（与 sortings 重复） | `view-config/viewOptionSchema.ts`、`views/galleryBoard.ts` |
| D3 | 大数据量渲染 | 每批 48 张 +「加载更多」 | 非 grid 上限 2000，一并挂载会明显卡顿；分批实现简单、可测、无额外依赖 | 全量渲染（2000 卡片 DOM 过重）；行虚拟化（画廊为栅格，需自算列数，成本高于收益） | `views/GalleryView.tsx` |
| D4 | 示例表默认视图 | 两表默认均为 gallery | 需求场景是「查看 / 分享资讯」；进入即阅读态，grid 一键可达 | 默认 grid（首屏仍是表格，新能力不可见） | `examples/datasets/工作区-数据源示例/views.json` |
| D5 | 分享范围 | 工作区内共享：`ViewVisibility.TABLE` + 深链 + 收藏 | 复用 ADR 0003 三档可见性与 ADR 0021 收藏，零新增权限面 | 表 / 视图匿名公开链接（ADR 0003 D5 明确不复活，需新权限与脱敏设计） | `cli/seed/views.py`、`pages/workspace/MyViewsPanel.tsx` |
| D6 | 示例数据来源 | 只种静态 CSV + 视图，不种 `llm_prompt` 任务 | 保存 / 运行 LLM 任务需个人连接与 API Key（`routers/sync_jobs.py` 强制校验），种子无法代持 | 种子内置 llm 任务（开箱即失败，且把个人配置带入工作区） | `examples/datasets/工作区-数据源示例/` |
| D7 | CSV 首列 `id` | 种入前删除 | 会建出名为 `id` 的业务字段；`_row_to_dict` 用物理行 ID 覆盖同名字段，数据不可读 | 保留并改名 `source_id`（语义变成抓取侧 ID，与本需求无关） | `examples/datasets/工作区-数据源示例/*.csv` |
| D8 | 列表型 option 校验 | `tag_fields` / `meta_fields` 逐项校验，非字符串 400 | 现有 `opt_val not in valid_fields` 对 list 抛 TypeError → 500；逐项校验报错可定位 | 不校验（脏引用到渲染期才静默丢字段）；只校验首项（漏检） | `routers/views.py`、`cli/seed/views.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：内容型数据表获得阅读态入口；新增类型零迁移、零新端点；分享复用既有可见性，权限面不变；配置 schema 同时服务创建表单与设置对话框。
- **负向**：视图模式注册清单再增一处硬编码（`ViewMode` / `VALID_MODES` / `MODE_BUTTONS` / `MODE_VIEW_TYPES` / 中文标签表）；非 grid 的 2000 行上限在画廊场景更易被感知（靠筛选收窄）。
- **风险与缓解**：默认画廊使 grid 工具栏的「新增行」不在首屏（切「全部资讯 / 全部菜谱」一键可达，属有意取舍）；画廊组件保持 lazy，避免 GridPage 体积预算超限（超限用 `bundle:budget:update` 收口）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性 | `DataView.visibility` / `scope_key` | gallery 沿用三档，不新增档位 | ADR 0003 |
| 模式注册清单 | `viewModes.ts` / `GridPage.tsx` | 新增类型必须同步全部注册点 | ADR 0011「已知坑」 |
| 收藏与深链 | `accounts_user.preferences.favorite_views` | 分享入口沿用主页收藏面板 | ADR 0021 |
| 匿名分享 | 文档公开链接 | 只覆盖文档，不扩表 / 视图 | ADR 0017 / ADR 0003 D5 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/grid/views/GalleryView.tsx`、`frontend/src/pages/grid/views/galleryBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`src/cndb/plugins/tables/routers/views.py` | `frontend/src/pages/grid/views/GalleryView.test.tsx`、`frontend/src/pages/grid/views/galleryBoard.test.ts`、`tests/test_views_api.py` | `<待提交>` |
| P1 | 已落地 | `examples/datasets/工作区-数据源示例/views.json`、`src/cndb/cli/seed/views.py` | `tests/test_backup_seed_roundtrip.py`、`frontend/tests/e2e/critical/gallery-view.spec.ts` | `<待提交>` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地（gallery 类型 + 组件 + 配置 schema + 注册清单 + 后端/seed 校验；两表 CSV + 12 个 seed 视图）
- 已完成：前端 `172` 个测试文件 / `2109` 例全绿（核心集合 lines 97.69% / branches 100%，全局 lines 82.06%）；后端 `make test` 5367 passed / 8 skipped；`make check-fast` 全绿；e2e `gallery-view.spec.ts` 本地实跑 3 passed（setup + 两表用例）；`bundle:budget` 全绿（GridPage +1.2%，在 5% 容差内 warn）
- 下一步：合并后由人确认 `Status`；如需超 2000 行全量画廊另立行虚拟化 ADR；观察默认画廊视图下「新增行」入口的发现性反馈
- 已知坑：① CSV 首列 `id` 必须删（`_row_to_dict` 用物理 id 覆盖同名字段，数据不可读）；② 列表型 option 直接 `in set` 会 TypeError → 500，必须逐项校验；③ 非 grid 上限 2000，画廊每批 48 +「加载更多」；④ 默认画廊会让「新增行」不在首屏（切「全部资讯 / 全部菜谱」一键可达，有意取舍）；⑤ e2e 不能等 grid 专属的「新增行」按钮作就绪信号，画廊默认视图下不存在
- 最近一次全绿：2026-10-22（`make check-fast` + `make test` 5367 passed + 前端全量 vitest 2109 passed + e2e `gallery-view.spec.ts` 3 passed + `bundle:budget`）
