# ADR 索引

> `Status` 口径：`Proposed`（待评审）/ `Accepted`（已评审）/ `Implemented`（已落地）。
> 落地阶段以各 ADR「落地状态」表为准；进度、下一步与已知坑看「交接」节。
> `make adr-check` 校验本索引、ADR 落地表与代码 / 测试 / CHANGELOG 的对应关系。

| 编号 | 标题 | Status | 落地阶段 | 代码 | 测试 | CHANGELOG |
|---|---|---|---|---|---|---|
| [0002](0002-frontend-check-sharding.md) | Frontend Check 拆分并行 | Accepted | 静态链已落地；分片未采用 | `Makefile`、`.codeup/pipelines/ci.yml` | `frontend/scripts/check-coverage.mjs` | [未发布](../../CHANGELOG.md) |
| [0003](0003-view-visibility-permission-model.md) | 视图可见性三档模型 | Implemented | P0-P3 + D6 已落地 | `src/cndb/plugins/tables/services/core/view_access.py` | `tests/test_view_share_p3.py` | [未发布](../../CHANGELOG.md) |
| [0004](0004-row-level-permission-rules.md) | 行级权限规则 | Proposed | P0-P2 已落地（待评审） | `row_access.py`、`row_permissions.py` | `tests/test_row_*.py` | [未发布](../../CHANGELOG.md) |
| [0005](0005-change-request-row-merge-view.md) | 修改申请同行合并视图与冲突裁决 | Accepted | M1-M3 已落地；M4 待补前端用例 | `plugins/change_requests/services.py`、`routers/change_requests.py` | `tests/test_change_requests_merge_view.py` | [未发布](../../CHANGELOG.md) |
| [0006](0006-periodic-datasource-sync.md) | 周期性外部数据同步框架 | Implemented | M1-M5 + 遗留项全部落地 | `plugins/datasource/`、`core/crypto.py`、`analytics/services/formula.py`、`frontend/src/pages/{datasource,analytics}/` | `tests/test_{datasource,core_crypto,analytics_window,analytics_scope}_*.py` | [未发布](../../CHANGELOG.md) |
| [0007](0007-backend-robustness.md) | 后端健壮性加固与极端用例基线 | Proposed | P0 已落地；P1-P3 未开始 | `core/ratelimit.py`、`core/database.py` | `tests/test_backend_extreme_cases.py` | [未发布](../../CHANGELOG.md) |
| [0008](0008-offline-docker-image-export.md) | 离线部署镜像导出 | Accepted | P0-P2 已落地 | `deploy/`、`docker-compose.prod.yml` | `tests/test_deploy_scripts.py` | [未发布](../../CHANGELOG.md) |
| [0009](0009-stock-daily-datasource-example.md) | 股市日线典型示例（数据源同步 + K 线等视图） | Accepted | P0-P2 已落地 | `frontend/src/pages/grid/views/`、`src/cndb/cli/seed/datasource.py`、`plugins/tables/routers/views.py` | `tests/test_seed_datasource.py`、`frontend/tests/e2e/*` | [未发布](../../CHANGELOG.md) |
| [0010](0010-document-file-import.md) | 文档通用文件导入（md / docx / html，单文件与文件夹模式） | Accepted | P0-P2 已落地 | `src/cndb/plugins/documents/services/importers/`、`src/cndb/plugins/documents/routers/file_import.py` | `tests/test_documents_file_import_*.py`、`frontend/tests/e2e/critical/document-file-import.spec.ts` | [未发布](../../CHANGELOG.md) |
| [0011](0011-stock-kline-enhanced.md) | 股市 K 线增强（多周期复权、全历史字段与行内 K 线视图） | Accepted | P0-P1 已落地 | `providers/eastmoney_kline.py`、`providers/eastmoney_symbols.py`、`cli/seed/stock_quotes.py`、`frontend/src/pages/grid/views/KlineView.tsx` | `tests/test_datasource_eastmoney_*_provider.py`、`tests/test_datasource_partial_upsert.py`、`frontend/src/pages/grid/views/klineBoard.test.ts` | [未发布](../../CHANGELOG.md) |
| [0012](0012-workspace-global-search.md) | 工作区顶栏统一搜索（文档 + 数据表，默认按激活视图收敛） | Implemented | P0-P2 已落地 | `src/cndb/plugins/workspaces/{routers,services}/search.py`、`frontend/src/components/GlobalSearch.tsx`、`frontend/src/layouts/MainLayout.tsx` | `tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx` | [未发布](../../CHANGELOG.md) |
| [0013](0013-stock-daily-multi-source-sample.md) | 示例日线两源扩样（tencent / sina，一源一表） | Accepted | P0-P2 已落地 | `src/cndb/plugins/datasource/providers/sina_kline.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`scripts/build_example_kline.py` | `tests/test_datasource_sina.py`、`tests/test_seed_datasource.py` | [未发布](../../CHANGELOG.md) |
| [0014](0014-llm-prompt-datasource-sync.md) | 数据源同步接入大模型（llm_prompt + 提示词 + cron + 连通测试） | Implemented | P0-P2 已落地 | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | [未发布](../../CHANGELOG.md) |
| [0015](0015-search-cache-and-full-coverage.md) | 工作区搜索缓存与全表覆盖 | Accepted | P0 已落地；P1-P2 未开始 | `src/cndb/plugins/workspaces/services/search.py`、`src/cndb/core/cache.py` | `tests/test_workspace_search.py`、`frontend/src/components/GlobalSearch.test.tsx` | [未发布](../../CHANGELOG.md) |
| [0016](0016-auth-background-animation.md) | 认证页 JS 动态背景（5 组风格，可切换） | Implemented | P0-P2 已落地 | `frontend/src/components/auth-background/`、`frontend/src/layouts/AuthLayout.tsx` | `frontend/src/components/auth-background/*.test.ts` | [未发布](../../CHANGELOG.md) |

## 说明

- 新增 ADR 时按 `NNNN-<topic>.md` 命名，并把编号、标题、Status、落地阶段补进本表；编号一旦分配不复用。
- ADR 被新方案替代或需求作废时**直接删除**该文件、本表索引行及代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；历史追溯看 git（`git log -- docs/adr/`）。
- 需求移除 / 变更时先清理 ADR 正文（删失效段落与决策行），再改代码。`make adr-check` 校验索引 Status 与 ADR 一致，并拦截残留的失效状态文档。
