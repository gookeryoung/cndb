# 前端死代码清理与 README 修正方案

## 概要

对应需求 `.trae/req/req-20-无用代码清理与文档完善.md`。以工具证据驱动的精简清理：前端删除 3 组零引用死代码；README 修正与实际代码不符的结构树、CLI 命令、包管理器与特性清单。后端经全维度工具扫描确认无可清理项。

## 工具证据（2026-10-08）

| 工具 | 范围 | 结果 |
|------|------|------|
| `ruff check --select F,F841` | src + tests | 全绿，零发现 |
| `vulture --min-confidence 60` | src + tests | 零发现（80 置信度同样为零） |
| `deptry` | 全仓库 | 24 项报告，逐项复核后全部为假阳性（见保留清单） |
| `eslint` | frontend/src | 全绿 |
| `tsc -b --noEmit` | frontend | 全绿 |
| `knip` | frontend | 1 个未引用文件 + 11 个未使用导出 + 8 组未使用类型重导出 |

## 删除清单（前端）

| 文件 | 符号 | 证据 |
|------|------|------|
| `frontend/src/api/auth.ts` | `userApi`（仅 `getPreferences` 一个方法）+ `PreferencesResponse` 导入 | knip unused exports；全仓库 grep 零调用 |
| `frontend/src/api/index.ts` | `userApi` 值重导出 + `PreferencesResponse` 类型重导出 | 同上 |
| `frontend/src/api/types.ts` | `USER_ROLE_LABEL` 常量 + `PreferencesResponse` 接口 | knip unused exports；grep 零引用（角色显示名实际由后端返回或各组件自持） |
| `frontend/src/hooks/index.ts` | `useResponsive` / `ResponsiveState` / `DeviceType` / `BREAKPOINTS` barrel 重导出 | 消费方（MainLayout / OnboardingTour / 测试）全部走直接路径 `@/hooks/useResponsive`，barrel 条目零消费 |

## 保留清单（假阳性，附理由）

| 对象 | 保留理由 |
|------|----------|
| deptry DEP002 `psycopg` | SQLAlchemy 按 URL scheme（`postgresql+psycopg://`）运行时动态加载驱动 |
| deptry DEP002 `cryptography` | `python-jose[cryptography]` 载体 + Win7 兼容版本锁定（pyproject 注释明确） |
| deptry DEP002 `python-jose` / `python-docx` | 模块名映射假阳性：实际以 `from jose import` / `from docx import` 使用 |
| deptry DEP002 `python-multipart` | FastAPI multipart 上传端点（import_csv.py）运行时需要，无直接 import |
| deptry DEP001 `starlette` | app.py SPA 中间件直接使用，starlette 为 fastapi 强制传递依赖 |
| deptry DEP002 `httpx` / `pytest-*` / `ruff` / `pyrefly` / `fspack` | test / lint / dev extras 的工具本体或运行载体 |
| knip `tests/e2e/auth.setup.ts` "未引用文件" | Playwright setup project，由 playwright.config.ts 以 project 形式调度 |
| knip 报 `FieldList.tsx` `FIELD_TYPE_ICONS`、`typeConfigPanel.tsx` `TYPE_CATEGORIES` / `normalizeOptionsFromConfig`、`useGridData.ts` `VIEW_FETCH_ALL_LIMIT`、`useChartListDraft.ts` `writeBackChartList`、`chartBoard.ts` `SINGLE_SERIES` | 符号均在定义文件内部使用中，仅 export 关键字过宽；收缩导出属过度清理，不动 |
| knip 报 `src/test/msw.ts` `mockWorkspace` / `mockTable` / `mockField` / `mockViews` / `handlers` | 测试基础设施：mock 工厂被 handlers 内部引用，`server` 被全部测试文件消费 |
| knip 报 8 组未使用类型重导出 | barrel 类型 re-export 删除收益低、逐项核实成本高，且部分类型（如 `UserRole`）在定义文件内部被注解消费；统一保留 |
| `GridPage.tsx` `TableSkeleton` 导出 | 有专门回归测试文件引用；且该文件存在外部会话未提交改动，本轮不触碰 |

## 明确不触碰

- `frontend/src/pages/grid/GridPage.tsx`、`ViewConfigDialog.tsx`：存在外部会话未提交改动（多会话并行风险），清理避开。
- 后端 src/tests：四维工具（ruff F / vulture / deptry / pyrefly 既有门禁）零真阳性，无死代码。
- 16 个 `test_cov_*` 测试文件：合法测试，合并属高风险 churn（延续前轮决策）。

## README 修正项

1. 项目结构树：`seed.py` / `runner.py`（已不存在）→ 实际 `cli/`（main/seed/backup/restore/users/service）、`gui/`、`models/`、`alembic/`、`app.py`、`static/`。
2. 新增「CLI 命令」节：serve / dev / build / info / seed / backup / restore / users / service 十项（`cndbw` 含内）。
3. E2E 测试命令 `npx playwright install` / `npm run e2e:*` → `pnpm exec playwright install` / `pnpm e2e:*`（对齐包管理器规范）。
4. 特性清单：字段类型 10 种 → 17 种（补 email/url/phone/json/percentage/timestamp/attachment）；补 7 种视图、备份恢复、Tkinter 桌面 GUI。
5. 快速上手：`uv run python -m cndb.cli.seed` → `uv run cndb seed`；补前端入口说明与 0.0.0.0 默认绑定提示。

## 验证

- 前端：`tsc -b --noEmit` 全绿；`vitest run src/api src/hooks` 60/60 通过；全量 `make frontend-test` 1074/1074 通过 + 覆盖率双门槛达标（核心 lines 97.01% ≥ 90%、branches 100% ≥ 85%；全局 78% ≥ 70%）。
- 全量 `make check` 全绿为收尾门禁。
- 后端零改动，ruff/pyrefly 既有门禁不受影响。

## 遗留

- knip 报告的 export 过宽类（保留清单第 4 行）如需收敛，建议单独小轮处理。

> CHANGELOG 版本节失实已于 2026-10-08 回填解决（iter-31）：以 git tag creatordate 为发布日期，0.1.3–0.2.7 全部版本节补齐，`[0.1.12]` 由"未发布"改为 2026-09-19，`[0.1.2]` 日期按 tag 修正为 2026-09-13。
