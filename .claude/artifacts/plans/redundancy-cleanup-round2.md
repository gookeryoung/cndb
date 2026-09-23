# 项目冗余设计清理与优化 — 开发计划（第二轮）

> 工作流：dev-tdd（重构路径：行为不变，测试先行作安全网，每阶段红→绿→扩验证）
> 前置：上一轮 `designs/cleanup-code-config-slimming.md` 已执行完毕（空壳包/docs/tox/httpx 归位均已落地）。本轮聚焦其未覆盖的**代码级冗余**，纯重构、外部行为不变。

## 一、现状证据（本轮新增冗余点）

| # | 位置 | 问题 | 严重度 |
|---|------|------|--------|
| R1 | `routers/tables.py:101` `_check_table_permission`、`routers/import_csv.py:41`、`routers/import_api.py:40` `_check_workspace_permission` | 同一段「工作区存在性 + 角色门槛」检查逻辑**三处复制粘贴**（仅返回值差异） | 高 |
| R2 | `routers/records.py:58-151` | `list_records_get`（GET）与 `list_records`（POST /list）重复实现 list_rows 调用 + 相同的 ValueError→400 / Exception→500 错误映射，约 40 行重复 | 高 |
| R3 | `routers/tables.py:113` `_get_table_or_404` | 定义在 router 文件，却被 records/views/fields/bulk/members/permissions/audit 共 **7 个 router 跨文件导入**，属分层错位（共享 helper 应在 services 层） | 中 |
| R4 | `tests/test_cov_*.py`、`tests/test_coverage_*.py` 共 16 文件 | 8594 行，占测试总量 34216 行的 **25%**，命名以覆盖率冲刺为导向（如 `TestFinalCoveragePushes`），存在用例重叠嫌疑。上一轮明确「不动」，本轮作为独立决策项 | 中 |

## 二、明确不做（已验证排除）

- 前端 `useDebouncedValue` / `useDebouncedCallback`：值防抖 vs 回调防抖，语义不同、各有调用点，**非冗余**。
- `docker-compose.yml` 与 `docker-compose.wheel.yml` 双方案：README 明确两种部署形态并存，属有意设计。
- `routers/bulk.py`（667 行）：导入流程复杂但功能内聚，本轮不动。
- `import_csv.py` 旧端点（compat_router）：对外 API 兼容层，删除属行为变更，不在本轮"行为不变"范围。

## 三、Phase 划分（每 Phase 独立提交）

### Phase 1 — 工作区权限检查收敛（R1，低风险高价值）

```
Behavior: 三份相同的工作区权限检查收敛为 services 层单一实现
Expected: 现有全部 API 测试通过；404（工作区不存在）/ 403（权限不足）语义逐字不变
Test target: tests/test_access_audit.py（安全网）+ 新增共享函数单测
Production target: services/core/access.py 新增 check_workspace_permission()；
                   tables.py / import_csv.py / import_api.py 三处改为委托
```

- RED：先写 `check_workspace_permission` 的单测（工作区不存在→404、角色不足→403、达标→返回 Workspace），确认失败。
- GREEN：在 access.py 实现最小函数。
- 重构：三个调用点替换。注意 tables.py 版本返回 None、import 版返回 ws —— 统一为**返回 Workspace**，tables.py 调用点忽略返回值，行为等价。
- 扩验证：`uv run pytest tests/ -k "import or table or access" -x` → 全量。

### Phase 2 — records 列表端点去重（R2）

```
Behavior: list_records_get 与 list_records 共用同一私有 helper，两路由对外契约不变
Expected: 参数、响应模型、400/500 错误语义、GET 端点 JSON 解析失败降级为 None 的行为全部不变
Test target: tests/test_cov_routers_records.py（安全网）+ 补 GET 降级解析用例（若缺）
Production target: routers/records.py 抽取 _list_response(db, dt, user, *, filters, sorts,
                   filter_logic, limit, offset, include_trashed) -> RecordListResponse
```

- RED：先确认 GET 端点「filters/sorts 非法 JSON 降级不报错」有用例覆盖，缺失则先补（此时应通过——characterization test）。
- 重构：抽 helper，两个端点变薄壳。禁止改变任何 HTTP 契约。
- 扩验证：records 相关测试目录 + `make check`。

### Phase 3 — 权限 helper 迁移至 services 层（R3，含决策点 D1）

```
Behavior: _get_table_or_404 与 check_workspace_permission 定居于 services/core/access.py
Expected: 全部测试通过，无行为变化
Test target: 全量 pytest
Production target: services/core/access.py（迁入）、tables.py（迁出）、7 个 router（import 路径）
```

- **D1 决策点**（二选一）：
  - a) tables.py 保留 `from ...access import ...` re-export，其他 router 导入路径不动（改动最小）
  - b) 直接更新 7 个 router 的 import 路径，不留兼容垫片（更干净，推荐）
- 顺序：先迁移函数体 → 逐文件更新 import → ruff/pyrefly 确认无残留引用。

### Phase 4 — 测试冗余收敛（R4，高 churn，含决策点 D2）

现状：16 个 cov 文件 8594 行。上轮以「高风险 churn、收益低」为由不动，维持该判断仍有理。

- **D2 决策点**（三选一）：
  - a) 本轮不动（与上轮口径一致，Phase 4 取消）
  - b) 保守清理：仅对 16 文件做断言重叠比对，删除**经运行验证**的重复用例，文件结构不动（推荐，预计可减 10-20%）
  - c) 全面整合：按目标模块合并进行为命名文件 + 重命名类（churn 最大，建议另立专项）
- 若选 b：每删一批跑 `uv run pytest tests/<file> && pytest --cov` 确认 cov 不降；单行删除可追溯到重复证据。

> **执行结果（已闭环）**：采用 b。AST 全量比对（精确函数体 + 抹平字面量/命名两级归一化）显示 16 文件间 **0 个完全重复用例**；仅 1 组参数化式结构相似（7 例，各测不同校验器，非重复）。按"删除需可证实重复"的保守标准，**未删除任何用例**，维持上轮"不动"判断。

## 四、门禁（每 Phase 完成后必过）

1. `uv run ruff check src tests` + `uv run pyrefly check`
2. `uv run pytest -m "not slow" -x -q` 快测 → 全量 `make check`（覆盖率 ≥95% **不得下降**，下降即回滚该 Phase）
3. 每 Phase 独立 commit：`refactor(tables): 收敛工作区权限检查为单一实现` 式中文 conventional message
4. 最终 `dev-verify` → `dev-code-review` → 用户确认后 `make push`

## 五、执行顺序与依赖

Phase 1 → Phase 2 → Phase 3（3 依赖 1 的 access.py 落点）→ Phase 4（独立，可与 1-3 并行决策）。
任一 Phase 失败回滚不阻塞其余 Phase。

## 六、待用户确认

| 决策点 | 选项 | 建议 |
|--------|------|------|
| D1 Phase 3 导入方式 | a) re-export 兼容 / b) 直接改 7 处 import | b |
| D2 cov 测试处置 | a) 不动 / b) 保守删重 / c) 全面整合 | b |
| 范围 | 是否仅执行 Phase 1-3（跳过 4） | 由 D2 决定 |
