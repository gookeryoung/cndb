# 冗余梳理与精简：已执行项与待办清单

> 生成时间：2026-10-14。本文件记录一轮「证据驱动」的冗余梳理与精简：
> 已完成的改动见 CHANGELOG「未发布」，下面只列**已分析清楚但尚未执行**的项，
> 每条都附可复现证据与风险判断，便于后续按优先级推进。

## 一、超大文件拆分：剩余候选

已完成的拆分（seed.py / reports.py / ReportsPage / GridCell / GanttView）见 CHANGELOG。
以下为仍超过 500 行的源码文件，按收益排序：

### 后端

| 文件 | 行数 | 建议拆分 |
|---|---|---|
| `src/cndb/plugins/workspaces/routers/workspaces.py` | 1041 | 拆 `routers/members.py`（成员/转让/pin）+ `services/backup_io.py`（备份导入导出，`_import_backup_into_workspace` 单函数 270 行）；`/workspaces` 测试 1206 处但全走 HTTP，改动对测试透明 |
| `src/cndb/gui/main_window.py` | 1041 | 按 Tab 拆 `gui/tabs/{serve,backup,info}.py`；**`main` 必须留在 `main_window.py`**（`pyproject` 的 `cndbw` entry point 指向它）。coverage 已 omit `gui/**`，无覆盖率风险，也没有 gui 测试 |
| `src/cndb/plugins/tables/services/fields/field_ops.py` | 1027 | 拆 `fields/field_import.py` + `fields/select_options.py`；需保持 `field_ops` 包级 re-export（seed 以 `field_ops as _fo` 使用） |
| `src/cndb/plugins/tables/services/core/records.py` | 957 | 拆 `core/{row_values,row_crud,row_bulk}.py`；**本项循环导入风险最高**（与 `query.py`/`ddl.py` 互依，现靠函数内延迟 import 规避，拆分须保留） |
| `src/cndb/plugins/tables/services/importing/importer.py` | 906 | `Importer` 类单类 776 行 / 19 方法，可按方法族拆 mixin |
| `src/cndb/plugins/documents/services/content.py` | 905 | 拆 `content/{crud,trash,links,tags,fts,serialize}.py`；FTS/软删子树/标签计数高耦合，成本较高 |
| `src/cndb/plugins/tables/services/transfer/normalize.py` | 758 | 32 个纯函数，可按 `{checks,date,numeric,promote}` 拆；`transfer/__init__.py` 已有 ~40 项 re-export，须保持同名 |
| `src/cndb/plugins/tables/routers/bulk.py` | 752 | 拆 `bulk/{records,export,import}.py` |
| `src/cndb/cli/users.py` | 748 | 拆 `io.py`（CSV/XLSX 读取）+ `commands.py` + `printing.py`；`test_cli_users.py` 直接 import，需 re-export |
| `src/cndb/cli/restore.py` | 727 | 拆 `restore/{inspect,sqlite,json,uploads,migrate}.py`；5 个测试文件直接 import，需 re-export |

### 前端

| 文件 | 行数 | 建议拆分 |
|---|---|---|
| `src/pages/grid/GridPage.tsx` | 1276 | 外置 `gridFallbacks.tsx`、`modeSwitch.ts`、`useGridPageRows.ts`、`useGridPageModals.ts`；主组件 1140 行主要是状态与回调，抽 hook 有一定回归风险 |
| `src/pages/import-export/ImportExportDialog/ImportPanel.tsx` | 958 | 拆 `importSteps.ts`（状态机）+ `ImportFieldMapping` / `ImportTaskProgress` / `ImportResultSummary` |
| `src/api/types.ts` | 976 | 按域拆 `types/{admin,workspace,tables,views,import,reports}.ts` + `types/index.ts` barrel；唯一深路径引用是 `ImportPanel.test.tsx:20` |
| `src/pages/documents/DocumentsPage.tsx` | 797 | 拆 `documents/seriesStats.ts`（纯统计）+ `documentsFormat.ts` + 系列栅格 / 列表 / 回收站三面板。**测试要求保留 `buildSeriesStats` 具名导出** |
| `src/pages/documents/DocumentEditorPage.tsx` | 802 | 拆 `DiffView` / `TagEditor` / `useDocumentEditor` / `VersionTimeline` / `OutlinePanel` |
| `src/pages/grid/views/KanbanView.tsx` | 789 | 拆 `kanban/{KanbanCard,KanbanColumn,kanbanDensity,KanbanBadges}` |
| `src/pages/import-export/FileImportPreview.tsx` | 774 | 拆 `importPreviewConvert.ts`（纯转换）+ 字段列表 / 字段编辑 / 数据预览三块 |
| `src/pages/grid/views/CalendarView.tsx` | 782 | 拆 `calendar/{YearView,MonthView,WeekView,calendarEventUtils}` |
| `src/theme/theme.ts` | 695 | 10 套 antd ThemeConfig 预设抽 `theme/presets/*.ts`，theme.ts 只留 registry 与读写 |
| `src/pages/grid/view-config/viewOptionSchema.ts` | 562 | 按视图拆 `options/{kanban,calendar,gantt,wbs,matrix,chart}.ts`；**测试要求保留 7 个具名导出** |
| `src/pages/grid/views/WbsView.tsx` | 588 | 树构建与渲染行两分 |

> 拆分通用的两条约束（前几次拆分已验证）：
> 1. **monkeypatch / mock 目标必须指向 canonical 模块**。把实现移出后，若测试仍 patch 原模块的同名属性，patch 会静默失效（seed 的 `_get_datasets_dir`、reports 的 `_run_command` / `_cjk_font_candidates` 都踩过）。
> 2. 测试使用的具名导出要在原文件 `export { ... } from '...'` 或 `__all__` 里保留（GridCell 4 个、DocumentsPage 的 `buildSeriesStats`、DocumentTree 4 个、viewOptionSchema 7 个、FieldManager 2 个、ViewConfigDialog 的 `FilterRule`/`SortRule`）。

## 二、僵尸 Alembic 迁移（4 个，需谨慎）

`forms` / `workflows` 插件源码已删除，但 4 个迁移仍在链上，会在纯迁移链库中建出 6 张没人用的表
（`forms_formdefinition`、`workflows_workflow*`、`workflows_approvalinstance/action`），随后由
`e8f9a0b1c2d3_github_issue_pr_refactor.py` 全部 drop —— 对新库净效果为零，属历史包袱。

- 涉及文件：`62817ea574fa_add_workflows_tables.py`、`b8a7c6d5e4f3_add_forms_formdefinition.py`、`c1d2e3f4a5b6_add_form_approval.py`、`d5c6a7b8e9f0_add_change_request_fields.py`
- **不能直接删文件**：迁移链是单链，删节点会断链。需改 `949b0d8ddf3f` 的 `down_revision` 为 `6399e5f0f61f`、`d5c6a7b8e9f0` 的为 `a9c0d1e2f3b4`，或改为在链尾追加 drop 迁移。
- 建议：**暂不执行**。收益（少量迁移文件）低于风险（已有部署库升级路径），除非确认无存量库依赖该链。

## 三、测试层的剩余重复

- **跨文件重复的同类 fixture**（16 个文件各自重写 `ws` + `table`，12 个文件各自重写 `owner`/`auth_owner`，7 个文件各自重写 `ws_with_auth` 家族，6 个文件各自重写 `test_session`）。可上提到 `tests/conftest.py`，但会改动大量测试文件的可见 fixture 名，属高风险 churn —— 建议按文件分批做，每批跑一次覆盖率对比。
- **e2e 与单测重叠**：`frontend/tests/e2e/critical/navigation.spec.ts:22-65`（Tab 顺序/可见性/路由）与 `MainLayout.test.tsx:138-208` 覆盖同一行为，且单测更强（还断言激活态）。e2e 独有价值的是「seed 数据下的表行数=8」等用例。可删 navigation 的 3 个重叠用例；e2e 目前 `continue-on-error: true`，删除零风险但也零收益。
- **前端测试样板未收敛**：26 个测试文件各自 `import { http, HttpResponse } from 'msw'` + `server.use(...)`；4 个文件（`api/hooks.test.tsx`、`api/hooks.placeholder.test.tsx`、`WorkspaceList.test.tsx`、`WorkspaceSettingsContent.test.tsx`）自建 Provider 栈而不用 `src/test/render-providers.tsx`。

## 四、前端死导出与重复类型

**完全零引用的导出**（建议删）：

| 符号 | 位置 | 备注 |
|---|---|---|
| `LoginResponse` | `api/types.ts:106` | 后端对应物叫 `TokenResponse`，前端从未使用 |
| `WorkspaceTrashResponse` | `api/types.ts:446` | 全仓库仅定义处命中 |
| `getTagColor` | `utils/tagColors.ts:203` | 注释自称「兼容旧 API」，生产已全用 `getTagColorName` |
| `loadTableSettings` / `saveTableSettings` | `theme/tableSettings.ts:33/45` | **与 `store/tableSettings.ts:30` 的 zustand persist 共用同一个 localStorage key `cndb_table_settings`** → 存在双写冲突，是最该清理的一项 |
| `ANTD_COLOR_NAMES` | `utils/tagColors.ts:312` | 仅测试引用 |

**重复类型定义**：

- `ViewMode`：`pages/grid/views/viewModes.ts:11` 与 `store/gridView.ts:12` 逐字相同 → store 应改为 import。
- `WorkspaceRole`：`api/types.ts:131`、`ChangeRequestDetailPage.tsx:26`、`IssueDetailPage.tsx:24` 三处同义 → 收敛到 `api/types.ts`。

**待确认（高置信）**：`Field.is_primary`（`api/types.ts:331`）在 `src/cndb` 全库 0 命中，但前端 8 处
（`FieldList.tsx:191/205`、`FieldManager/index.tsx:283/518-520`、`fieldValueFormat.ts:20`、`GridCell.tsx:724`、
`viewOptionSchema.ts:431/544/557`、`CalendarView.tsx:146`、`MatrixView.tsx:94`）用它判定主键/标题回退 ——
若后端从不返回该字段，这些分支恒为假。需与后端确认后决定「后端补字段」还是「前端删分支」。

## 五、配置与门禁的剩余项

- **coverage omit 盲区**：`pyproject [tool.coverage.run].omit` 排除了 `cli/main.py`、`cli/seed/**`、`gui/**`、
  `tables/routers/files.py`。其中 seed 包与 gui 共约 3000 行不参与 95% 门禁。当前 `--cov=cndb` 实测 95.44%
  （阈值 95%，余量仅 0.44pp），如需提高可信度可先把 `gui/checks.py` 纳入统计。
- **`frontend/scripts/bundle-budget.json`**：三条基线的 `commit` 字段全为 `""`，与其 `_readme` 宣称的
  可追溯性不符；`assetPattern` 依赖 Rollup 自动 chunk 命名，拆包后可能失配（本次拆分后仍匹配）。
- **e2e 不在 tsconfig 项目内**：`tsconfig.app.json` 只 include `src`，`tsconfig.node.json` 只 include
  `vite.config.ts` → `pnpm typecheck` 不覆盖 `frontend/tests/e2e/**` 与 `playwright.config.ts`。
- **`pytest.ini` 的 `--dist worksteal`**：仅在调用方传 `-n` 时生效（Makefile / CI 都传，裸 `pytest` 串行）；
  已在文件内加注释说明，未改动行为。
