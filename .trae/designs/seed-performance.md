# seed 性能优化设计（bulk 写入通道）

## 背景与问题

`cndb seed` 实测 16.1s（DEBUG=false），SQL 事件统计定位：3175 条 INSERT 占 8.2s（57%）。

根因链（均有实测证据）：

1. [database.py](../../../src/cndb/core/database.py) 的 SQLite 连接参数 `isolation_level=None` 关闭了 sqlite3 隐式事务，而 SQLAlchemy pysqlite 方言的 `do_begin` 是 no-op（依赖 DBAPI 隐式 BEGIN），导致 `engine.begin()` 不会发出 BEGIN——每条语句都是独立事务 + `synchronous=FULL` fsync，实测 ~2ms/条；
2. `records.bulk_create` 对全部行逐条 `INSERT ... VALUES`（为取 `lastrowid`），放大上述开销；
3. select/multiselect 字段的 `validate_value` 每行重建 `SelectFieldConfig`，重复触发 `_normalize_options` 校验器与 `suggest_colors` 智能配色（seed 全程 ~8500 次），纯 Python 开销 ~1.8s。

附带发现（本设计不处理，独立议题）：`isolation_level=None` 下 `engine.begin()` 事务隔离与回滚完全失效（实测：事务内未提交写入立即对他连接可见、rollback 后数据残留），`bulk_create` 的"同事务回滚"承诺实际不成立；恢复真实事务需重构 `set_links` 嵌套 `engine.begin()`、事务内反射等模式，并全量回归。

## 机制设计

### A. seed 连接级 PRAGMA（seed.py）

- `_set_seed_sqlite_pragmas(engine)`：注册 SQLAlchemy `connect` 事件，SQLite 连接建立时执行 `PRAGMA synchronous=OFF`；非 SQLite 方言返回 None；
- `_remove_seed_sqlite_pragmas(engine, handler)`：seed 主流程 `finally` 中移除监听器，同进程复用（测试直调 seed）不留残留；
- 适用性：seed 为一次性批量重建演示库场景，崩溃安全性由"重建即覆盖"语义兜底。

### B. bulk_create 双通道写入（records.py）

主行插入按行是否携带 link 值分通道，返回 ids 与输入行严格同序：

- **逐行通道**：存在任一非空 link 值的行，保持 `INSERT ... VALUES` + `lastrowid` + `set_links`（关联写入需要行 id 立即可用）；空物理值行写 `_trashed=False` 兜底；
- **批量通道**：连续无 link 值的行段走 `INSERT ... RETURNING id` executemany（SQLite insertmanyvalues 编译为多 VALUES 语句），段内按**列集合签名**（`tuple(sorted(keys))`，空 values 行归入 `_trashed` 组）分组执行——executemany 要求各行参数键一致，CSV 归一化后不同行的 None 跳过会导致列集合不同。

保证项：

- RETURNING 返回 id 与参数顺序一一对应（SQLite 3.35+ / Python 3.12 自带 3.42+，实测 2000 行保序）；
- 自动编号分配（`_apply_auto_increment_defaults`）与 link 预校验发生在拆行阶段，不受通道影响；
- 全部写入仍在同一 `engine.begin()` 内。

### C. select/multiselect validate_value 轻量化（select.py）

- 新增 `_allowed_values_from_config`：直接从原始 config 提取选项值集合（dict 取 `value` 缺省回退 `label`，与 `_normalize_options` 归一语义一致；兼容 str / dict / SelectOption），返回 `frozenset` 或 None（无 options 放行）；
- `SelectFieldType.validate_value` / `MultiSelectFieldType.validate_value` 不再构建 `SelectFieldConfig`，校验语义不变（非法值抛 ValueError，文案含 `sorted(allowed)`）。

## 性能收益（实测，临时数据目录 + SQL 事件统计）

| 项 | 优化前 | 优化后 |
|---|---|---|
| seed 总耗时 | 16.1s | 约 5s（方案 A+B+C 叠加；D 项即本设计 C 节） |
| 行数据 INSERT | 8.2s（逐行独立事务 fsync） | <0.5s（批量 RETURNING + synchronous=OFF） |

## 已知边界

- 批量通道依赖 SQLite RETURNING（3.35+），项目最低 Python 3.12 自带 3.42+ 满足；PostgreSQL 原生支持 RETURNING，路径通用；
- `synchronous=OFF` 仅 seed 进程连接生效，serve/运行期连接不受影响；
- 运行期并发 bulk_create（API 导入）下 RETURNING 同样正确：id 由数据库分配并逐行返回，不依赖"区间连续性"假设。

## 验收

- [x] 无 link 行批量段 ids 与输入行严格同序，行内容对应正确（test_bulk_create_batch.py）
- [x] 批量-逐行-批量穿插单次调用：ids 同序、link 只落在目标行（load_links 断言）
- [x] 空 values + link 值行走逐行通道，关联正确落库
- [x] select/multiselect 轻量校验：str/dict options、value 回退 label、空 options 放行、非法值拦截（test_tables_plugin.py）
- [x] 临时数据目录实测 seed 总耗时 16.1s → 约 5s
- [x] 现有回归（tables/transfer/seed 往返/links/lookup）全绿，make check 通过
