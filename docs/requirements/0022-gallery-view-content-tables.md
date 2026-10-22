# 需求卡片：卡片画廊视图与 LLM 抓取资讯示例

- 编号：0022（与 ADR `docs/adr/0022-gallery-view-content-tables.md` 同号）
- 来源 / 提出人：产品需求（会话提出，附两份 LLM 抓取 CSV）
- 日期：2026-10-22
- 关联 ADR：`docs/adr/0022-gallery-view-content-tables.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据源示例-国际形势发展动态-全部-20261022_194026.csv 数据源示例-美食推荐做法-全部-20261022_210752.csv 请针对这两种通过LLM抓取的数据表，设计合适的视图，用于用户查看或者分享资讯。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 针对这两种通过LLM抓取的数据表 | 两张表（`国际形势发展动态` / `美食推荐做法`）按 CSV 原字段名种入「数据源示例」工作区；CSV 首列 `id` 为系统行 ID，不入表，避免覆盖 `_row_to_dict` 的 `id` 映射 | `examples/datasets/工作区-数据源示例/` | seed 后字段集合与 CSV 表头（去 id）逐一对应 |
| C2 | 设计合适的视图 | 新增第 11 种视图类型 `gallery`（卡片画廊）：卡片栅格展示标题 / 摘要 / 彩色标签 / 日期 / 元信息，点击卡片打开行详情；不新增封面图、不做卡片内联编辑 | `frontend/src/pages/grid/views/GalleryView.tsx`、`galleryBoard.ts`、`viewModes.ts`、`GridPage.tsx` | 组件测试 + e2e |
| C3 | 用于用户查看资讯 | 两张表各配置一套视图：画廊（默认）+ grid + kanban + matrix / calendar + chart + 过滤视图；视图名、排序与字段映射见 ADR「视图设计」 | `examples/datasets/工作区-数据源示例/views.json` | seed 完整性测试 + e2e 打开表默认落画廊 |
| C4 | 用于分享资讯 | 视图沿用现有可见性三档（ADR 0003）：seed 默认 `scope=global` → `ViewVisibility.TABLE`（表内全员可见）；分享靠深链 `/w/{wid}/tables/{tid}?view={vid}` 与主页收藏（ADR 0021）；**不开放表 / 视图匿名公开分享**（ADR 0003 D5） | `src/cndb/cli/seed/views.py`、既有视图访问控制 | 接口层既有可见性用例 + 文档口径 |
| C5 | （兼容既有 10 种视图） | `ViewMode` / `VALID_MODES` / `MODE_BUTTONS` / `MODE_VIEW_TYPES` 扩为 11 种；非法 `view_type` 仍被过滤；`DataView.view_type` 为自由 `String(32)`，零迁移 | `frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/GridPage.tsx` | `viewModes.test.ts` + `tests/test_backup_seed_roundtrip.py` |
| C6 | （视图配置可编辑） | 创建 / 编辑视图表单与视图设置对话框均支持 gallery 专属配置：`title_field` / `summary_field` / `tag_fields` / `meta_fields` / `date_field` / `card_size` / `summary_lines`；默认值回退由 `resolveOpts` 统一 | `viewOptionSchema.ts`、`CreateEditViewForm.tsx`、`ViewConfigDialog.tsx` | `viewOptionSchema.test.ts` + 表单测试 |
| C7 | （数据量边界） | 非 grid 视图沿用 `VIEW_FETCH_ALL_LIMIT = 2000`；画廊前端按 48 张分批渲染 + 「加载更多」，避免 2000 张卡片同时挂载 | `frontend/src/pages/grid/useGridData.ts`、`galleryBoard.ts`、`GalleryView.tsx` | 组件测试（分批 / 重置） |
| C8 | （字段引用校验） | 后端与 seed 两处 `_validate_view_fields` 同口径：`summary_field` 单值校验；`tag_fields` / `meta_fields` 逐项校验并带下标报错，非字符串项返回 400 而非 500 | `src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | `tests/test_views_api.py` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 视图模式注册清单 | `frontend/src/pages/grid/views/viewModes.ts`、`GridPage.tsx` | 新增类型需同步 4 处（类型 / 合法集合 / 按钮 / 模式推导） |
| 2 | 视图专属配置 schema | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | 创建表单与设置对话框共用真相源 |
| 3 | 视图字段引用校验 | `src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | 列表型 option 当前未处理，直接 `in set` 会 TypeError |
| 4 | 示例种子 | `examples/datasets/工作区-数据源示例/views.json` | 按表名追加视图，seed 幂等按同名更新 |
| 5 | seed 完整性测试 | `tests/test_backup_seed_roundtrip.py` | `VALID_VIEW_TYPES` 与 `_OPTION_FIELD_KEYS` 需同步 |
| 6 | 视图类型中文标签 | `MyViewsPanel.tsx`、`TableSettingsPage.tsx`、`helpContent.tsx` | 未登记时显示原始 `gallery` 字符串 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 落地口径 = 新增卡片画廊视图 + 两表配套视图（已确认，非仅用现有 grid/kanban）
- [x] 分享范围 = 工作区内共享（已确认，非对外公开链接）
- [x] 示例数据 = 只种静态 CSV 与视图，不种 `llm_prompt` 同步任务（需个人大模型连接）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
