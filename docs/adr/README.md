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
| [0006](0006-periodic-datasource-sync.md) | 周期性外部数据同步框架 | Proposed | M1-M2 已落地；M3-M5 未开始 | `plugins/datasource/`、`cli/sync.py` | `tests/test_datasource_*.py` | [未发布](../../CHANGELOG.md) |
| [0007](0007-backend-robustness.md) | 后端健壮性加固与极端用例基线 | Proposed | P0 已落地；P1-P3 未开始 | `core/ratelimit.py`、`core/database.py` | `tests/test_backend_extreme_cases.py` | [未发布](../../CHANGELOG.md) |

## 说明

- 新增 ADR 时按 `NNNN-<topic>.md` 命名，并把编号、标题、Status、落地阶段补进本表；编号一旦分配不复用。
- ADR 被新方案替代或需求作废时**直接删除**该文件、本表索引行及代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；历史追溯看 git（`git log -- docs/adr/`）。
- 需求移除 / 变更时先清理 ADR 正文（删失效段落与决策行），再改代码。`make adr-check` 校验索引 Status 与 ADR 一致，并拦截残留的失效状态文档。
