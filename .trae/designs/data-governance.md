# 数据治理（重复检测 / 合并 / 清洗）设计

对应需求：`.claude/artifacts/plans/data-cleaning-merge.md`（APPROVED，Option A 独立治理模块）。

## 范围

对已存表提供数据治理能力：精确重复检测 → 人工确认 → 合并（字段级融合 + link 引用迁移 + 回收站）、in-place 清洗（复用导入侧 4 动作）。所有治理操作异步任务化、强制预览确认、全量审计。

## 数据模型

### GovernanceTask（`tables_governance_task`，迁移 `a7b8c9d0e1f2_add_governance`）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | int | PK | 自增 |
| table_id | int | FK tables_datatable.id, index | 目标表；表删除时级联删除 |
| user_id | int | nullable, FK user | 发起人 |
| kind | str(16) | required | `detect` / `merge` / `clean`（应用层校验） |
| status | str(16) | default `pending` | 状态机见下 |
| progress | int | default 0 | 0-100 |
| config | JSON | default {} | 请求参数快照（含 preview 标记） |
| report | Text | default "" | 报告 JSON 字符串（接口层解析后返回） |
| error_message | Text | default "" | 失败原因 |
| total_groups / done_groups | int | default 0 | merge/detect 分组进度 |
| created_at / updated_at | datetime | default now | |

### TablePermission 增列

`manage_data_role: str(16) nullable=False default ""`。空串 = 使用默认阈值 ADMIN。

## 状态机与并发约束

```
pending → running → done | failed（非法转换抛 ValueError）
```

- 同表同时仅允许一个 `pending/running` 治理任务，违反返回 400（`create_governance_task` 校验）。
- 后台线程执行器与 import_tasks 结构同构（`run_governance_task_in_background` + `join_background_threads`），第三个任务型需求出现前不合并。
- 执行器 `execute_governance_task(db, task_id)` 统一管理生命周期，按 kind 延迟导入 dispatch 到 detect/merge/clean。

## 权限语义

- 新表级动作 `TableAction.MANAGE_DATA`，映射 TablePermission 字段 `manage_data_role`，默认阈值 `WorkspaceRole.ADMIN`。
- 判定链复用 `check_action`：表拥有者 > 工作区 ADMIN/OWNER（无条件）> 表成员授权（内置 read/write + 自定义 Role.permissions 的 `MANAGE_DATA` 位）> TablePermission 阈值 > 工作区角色默认。
- 注意：工作区 ADMIN/OWNER 走优先级 2 无条件放行，`manage_data_role` 阈值无法限制他们；阈值只影响 editor/viewer 及以下。
- `Role.ensure_permissions` 自动为既有/新角色补 `MANAGE_DATA=False` 权限位。
- `current_user_actions` 中序列化为 `manage_data`。

## API（全部要求 MANAGE_DATA 权限）

路由前缀 `/{workspace_id}/tables/{table_id}/governance`（`routers/governance.py`）：

| 方法 | 路径 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| POST | `/detect` | DetectRequest：`match_fields`（min 1）+ `ignore_case`/`ignore_whitespace` | GovernanceTaskOut | 400 同表活跃任务 |
| POST | `/merge` | MergeRequest：`groups`（每组 `member_row_ids` min 2 + `survivor_row_id` + `survivorship`） | GovernanceTaskOut | 400 同表活跃任务 |
| POST | `/clean` | CleanRequest：`actions`（4 动作，`on_fail` nullify/reject）+ `preview`（默认 true） | GovernanceTaskOut | 400 同表活跃任务 |
| GET | `/tasks/{task_id}` | - | GovernanceTaskOut | 404 不存在/不属于此表 |
| GET | `/tasks/{task_id}/report` | - | `{task_id, status, report}`（report 为解析后 JSON） | 404 |

- 422 由 Pydantic 校验产生（如 match_fields 为空、组内成员不足 2）。
- 创建任务后 `sessionmaker(bind=db.get_bind())` 提交后台线程。

## 算法与流程

### detect（`governance/detect.py`）

1. 按 id 递增分批扫描（`BATCH_SIZE=5000`），仅加载判重字段 + row id。
2. Python 层归一化判重键：casefold（`ignore_case`）+ strip（`ignore_whitespace`），None → `""`，跨 DB 语义一致。
3. dict 分组只存 `(member_row_ids, match_key_values)`，不持有全行。
4. 报告：`{total_rows, duplicate_row_count, group_count, groups:[...]}` 写 task.report；`total_groups/done_groups = group_count`。

### merge（`governance/merge.py`）

1. 逐组执行（进度 per group）；组处理流程：
   - 重读成员行；成员缺失或键值漂移（判重键当前值与报告不符）→ 记入 `skipped[{group_index, reason}]`，不中断。
   - `_fuse_fields` 按融合策略取值：`non_empty_first`（按行 id 序首个非空）/ `latest`（成员中最大 id 行的值）/ `oldest`（最小 id，物理行无时间戳列，以 id 为时间代理）/ `manual`（manual_values 显式指定）；`field_policies` 可按字段覆盖全局 `survivorship`。
   - 单事务：survivor 行 UPDATE + 非 survivor 置 `_trashed=True`（进回收站，可恢复）+ link 引用迁移。
2. link 迁移：遍历 `DataField(target_table_id == table.id)` 的物理关联表，`UPDATE target_row_id` 指向 survivor；仅当源表即本表（自引用）时排除组内成员行（`row_id NOT IN member_set`），跨表源不加该条件。
3. 审计：`log_action(action="merge")`，detail 含组快照。报告 `{merged_count, skipped, groups}`。

### clean（`governance/clean.py`）

1. 校验 actions 非空、column 均存在（字段名 → `DataField`）；fill_null 额外校验：strategy 必须为 mean/median/default/empty（缺失或非法报错，禁止静默无效）、default 必须提供 fill_value、mean/median 仅适用于数值列（number/float/percentage）。
2. 实时统计 profile：fill_null 的 mean/median、drop_outliers 的 IQR 阈值（`statistics.quantiles` n=4 inclusive；样本 < 4 返回空集）。
3. 预览与执行走**同一路径**保证一致：分批扫描（`BATCH_SIZE=1000`）→ `cleaning_core` 纯变换 → 预览模式只输出 samples（前 3 条 before/after）不写库；执行模式仅 UPDATE 值变化的行。
4. 报告 `{mode: preview|execute, affected:[{action,column,strategy,affected_rows}], samples}`；affected 键为 `(action, column, strategy)` 三元组。
5. 审计：执行模式单条 `log_action(action="clean")`。

### 共享变换层（`cleaning_core.py`）

从导入侧 `cleaning.py` 抽出 4 个纯函数 `apply_trim / apply_fill_null / apply_coerce / apply_drop_outliers`；导入侧改为顶部导入复用（保留 `_apply_dedupe`）。新增 profile 键支持：`{"median"}`（优先于 distribution_bins）、`{"fill_value"}`（strategy=default）。

导入侧 `apply_cleaning_actions` 不再直接透传列画像，而是经 `_build_fill_profile` 构建填充口径：default 取自动作配置 `fill_value`；mean/median 优先取画像统计值（画像仅在数值样本 ≥ 4 时含 mean/bins），缺失时回退为对当前行实时计算（内存全量行，口径全局一致）。`apply_drop_outliers` 用 `math.isclose`（rel_tol=1e-9，abs_tol=5e-7）容差匹配异常值，兼容画像中 round(6) 截断。

## 审计

- merge / clean 均写审计日志（action=`merge` / `clean`），detail 含足够回溯信息；预览不写审计。

## 前端

- 类型：`frontend/src/api/types.ts`（GovernanceTask/Detect/Merge/Clean + TablePermission.manage_data_role）；封装：`frontend/src/api/governance.ts`。
- 治理弹窗：`frontend/src/pages/grid/governance/GovernanceDialog.tsx`。按类别组织（AntD Tabs），两个页签相互独立、不依赖另一方的执行结果：
  - 「重复数据」：判重配置（字段 + 归一化选项）与合并确认同屏一体化——检测完成后，有重复组时直接展示分组表（逐组选保留行 + 全局融合策略）并提交合并，无重复组时提示"未发现重复行"；检测前置不再阻塞其他类别。
  - 「数据清洗」：预览 → 确认执行，可独立使用，无需先运行检测。fill_null 须选填充策略（均值/中位数/自定义值），自定义值时填充值必填（前后端双重校验）。
  - 任务进度 useQuery refetchInterval 轮询；打开弹窗时重置全部状态并回到「重复数据」页签。
- 入口：GridToolbar「数据治理」按钮（无 `manage_data` 动作时禁用）；表设置权限 Tab「数据治理」角色阈值下拉（空 = 默认管理员）。

## 测试与基准

- 单测：`tests/test_governance_tasks.py`（17）、`test_governance_detect.py`（12）、`test_governance_merge.py`（12）、`test_governance_clean.py`（17，含 fill_null 策略校验）、`test_cleaning_core.py`（20，含异常值容差匹配）、`test_governance_permissions.py`（12，含 403 矩阵/阈值覆盖/自定义 Role/表拥有者）、`test_governance_api.py`（8）。
- 性能基准：`scripts/bench_governance_detect.py`（AC-6：10 万行 < 60s，实测 SQLite 0.31s，--check 作门禁）。
- 测试环境注意：conftest `_sync_governance_tasks` 将治理后台任务同步执行（StaticPool 单连接）；`_cleanup_tables` join 治理线程。
