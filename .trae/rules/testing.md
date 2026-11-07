# 测试与覆盖率规范

> 硬约束编号以 [docs/CONSTRAINTS.md](../../docs/CONSTRAINTS.md) 为准；本文只写执行口径，不重复台账中的门槛数值。

- 测试与实现**同轮**编写（H9），按分层覆盖执行（H12），不得注水（H10）。
- 覆盖率门槛固定在 `pyproject.toml` 的 `[tool.coverage]`（`fail_under` + omit 白名单）；前端双门槛见 `frontend/scripts/check-coverage.mjs`（H10）。
- 命令链：`make test` → `make cov` → `make frontend-coverage` → `make e2e`（4 分片，H11）；e2e 抖动由 CI retries 兜底，不得跳过用例规避失败。
