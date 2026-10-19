# 后端健壮性与可靠性提升方案

> 生成时间：2026-10-20。范围：**后端为主**（`src/cndb`）。
> 目标：把"会坏"路径显式化 —— 先补齐极端情况的可回归验证，再按风险优先级排期结构性加固。
> 约束：本方案提出的测试补充**不改动业务逻辑**，仅锁定既有行为；结构性加固项列入排期，单独提交。

## 1. 现状基线（已具备的保障）

后端已有一套成体系的健壮性资产，加固前先确认基线，避免重复造轮子：

| 域 | 已有保障 | 关键实现 |
|---|---|---|
| 错误契约 | 统一 `CndbError` 族 + 全局 handler，响应体 `{"detail","code"}`；未捕获异常统一 500 JSON | `core/errors.py`、`app.py` |
| 请求事务 | `get_db` 异常显式 `rollback`，不依赖隐式回滚 | `core/database.py` |
| 会话安全 | 刷新令牌落库只存 SHA-256、一次性轮换、**复用检测即吊销全部会话**；access token 走 `token_version` 代次失效 | `accounts/services/sessions.py`、`core/security.py` |
| 登录防爆破 | 账号维度 + 来源 IP 维度（4 倍阈值）进程内滑动窗口，429 + `Retry-After` | `core/ratelimit.py` |
| 只读缓存 | TTL + LRU 进程内缓存，写路径经统一事件驱动精确失效 + 短 TTL 兜底 | `core/cache.py`、`core/events.py` |
| 迁移自愈 | 启动自动 `upgrade head`，失败给出可操作指引；就绪探测区分 DB 可达与迁移缺失 | `core/migrations.py`、`core/database.db_readiness` |
| 后台任务 | 导入/治理任务**启动回收 + 关闭中断标记**，消除"卡在 5% 无报错" | `app.py` lifespan、`importing/import_tasks.py` |
| 观测 | request_id 贯穿访问日志 / 慢查询 / 事件流；慢请求无视开关必记 | `core/observability.py` |
| 测试门禁 | 覆盖率阈值 **95%**，CI 低于阈值自动拒绝 | `Makefile`、`pyproject.toml` |

已有健壮性专项用例：`tests/test_data_robustness.py`（导入导出/公式注入/损坏文件）、
`test_backup_restore_robustness.py`、`test_documents_robustness.py`、
`test_xlsx_wps_import_robustness.py`、`test_error_contract.py`、`test_auth_unauthorized.py`、
`test_import_task_recovery.py`、`test_core_cache.py`、`test_observability.py`。

## 2. 风险清单与优先级

优先级：**P0** 安全/数据正确性且有现成低成本修复；**P1** 服务可用性/资源安全；
**P2** 部署约束或体验类，需排期。

| # | 域 | 失效模式 | 证据 | 优先级 | 建议动作 |
|---|---|---|---|---|---|
| R1 | 限流 | `SlidingWindowLimiter._hits` **无容量上限**：喷洒攻击用海量不同 IP/账号触发时字典无界增长 → 内存耗尽（DoS 放大） | `core/ratelimit.py:20` `_hits: dict[str, deque]`，`_prune` 仅裁剪被访问 key 的 bucket，无全局淘汰/上限 | **P1** | 增加惰性全表扫描（每 N 次写入或超阈值时清理过期 key）+ 可选 key 数上限，超限按最早过期淘汰 |
| R2 | 限流 | 单实例部署语义：多实例/多 worker 下进程内计数不共享，防爆破被绕过 | 模块 docstring 已声明"单机单进程"，但部署形态可能水平扩 | **P2** | 部署文档显式声明约束；`CacheBackend` 同款抽象预留 Redis 后端接入点 |
| R3 | 限流 | `request.client is None`（ASGI 无 client）时全部落到 `ip:unknown` 同一桶，可能误伤/误拦 | `core/ratelimit.py:85` `ip_key(ip or "unknown")` | P2 | 无 client 时按账号维度为主，或降级为不计 IP 维度 |
| R4 | 就绪探测 | `alembic_version` 缺失仅标注 `migration_current=null`，仍返回 ready：未迁移库可能被负载均衡接入 | `core/database.py:130-137` | **P1** | 是否"未迁移即 unready"取决于部署策略；建议至少在 `/api/health/ready` 增加 `migrated` 布尔并在部署层按需拦截 |
| R5 | 缓存 | 事件驱动失效为 best-effort：`record_event` 写失败即静默跳过失效，可能残留脏缓存 | `core/events.py:153-157`（失败 rollback 并返回 None） | P2 | 已有短 TTL 兜底（3~15s）；建议对关键写路径补显式失效或收紧 TTL |
| R6 | 缓存 | `get_or_set` 命中时返回**同一对象引用**，调用方误改会污染缓存 | `core/cache.py:155-166` 文档已警示 | P2 | 保持"只读约定"；如需强隔离可选 deepcopy（有性能代价，暂不做） |
| R7 | 后台任务 | 导入单阶段超时统一 600s，超大文件可能被误判超时失败 | `settings.IMPORT_TASK_TIMEOUT_SECONDS` | P2 | 超时改为可配置 + 按文件大小分级；失败原因已可读，先观察 |
| R8 | 存储/写入 | SQLite 写锁竞争依赖 `busy_timeout=5000`，极长写事务仍可能 `database is locked` | `core/database.py:59` | P2 | 保持 WAL + busy_timeout；长事务拆分（治理/导入已分批） |
| R9 | 密码 | bcrypt 对 >72 字节密码存在截断语义，超长密码可能语义碰撞 | `core/security.py:42-54` 直接 `hashpw` | P2 | **待核实**：确认当前钉版 bcrypt 的 72 字节行为后再决定是否显式拒绝超长密码 |
| R10 | 时钟 | access token 无 `nbf`、解码未设 `leeway`，多机时钟偏移可能导致"刚签发即过期/未生效" | `core/security.py:97-123` | P2 | 如需跨机部署，解码加 `leeway` 秒级容差 |

> 说明：本轮未发现需要立即修复的正确性缺陷 —— `record_event` 默认 `commit=True`（独立提交），
> 因此"登录失败"审计事件不会被 `get_db` 的异常回滚吃掉（曾疑虑点已排除）。

## 3. 测试缺口（本轮补齐）

以下路径此前**无专门单元测试**，是本轮极端用例的靶点（与第 4 节用例一一对应）：

| 模块 | 缺口 | 对应新增用例 |
|---|---|---|
| `core/ratelimit.py` | 全模块无专门单测：阈值边界、窗口滑出、键归一化、`configure` 钳制、并发线程安全 | `TestSlidingWindowLimiterExtremes`、`TestLoginRateLimiterExtremes` |
| `core/security.py` | `hash_token` / `create_refresh_token` 无直测；令牌声明（`typ`/`tv`/`exp`）与异构密钥/过期分支未锁定 | `TestSecurityTokenExtremes` |
| `core/cache.py` | `delete` / `clear()` 无参 / 负 TTL / producer 异常或返回 None / `invalidate_all` / `cache_key` 未覆盖 | `TestCacheInvariantExtremes` |
| `core/database.py` | `db_readiness` 三条分支（可达未迁移 / 有迁移版本 / 不可达）未直测 | `TestDbReadinessExtremes` |
| `core/errors.py` | 基类默认 `status_code/code` 与 `TooManyRequestsError.retry_after` 默认值未锁定 | `TestErrorContractExtremes` |
| `api/deps.py` | 认证头极端形态：大小写方案、令牌首尾空白、停用账号令牌 | `TestAuthHeaderExtremes` |

## 4. 极端用例补充计划（本轮已落地）

新增文件 `tests/test_backend_extreme_cases.py`（不改业务逻辑，仅锁定既有行为）：

1. **滑动窗口限流**：构造参数钳制（0→1）；未达阈值 `retry_after=0`；达阈值返回等待秒数；
   冻结时钟验证**窗口边界**（`t0+window` 仍计数、`t0+window+1` 滑出归零）；`reset` 清键；
   `configure` 钳制与阈值同步；8 线程并发写入不崩且计数生效。
2. **登录限流门面**：IP 维度为账号维度 4 倍；`configure` 同步两维；键归一化（去空白/小写、`None→unknown`）；
   账号维度拦截与 `reset` 清账号；IP 喷洒仅触发 IP 维度、单账号不越阈；`reset(user, ip)` 同时清 IP 桶。
3. **令牌与哈希**：`hash_token` 等于 SHA-256 hex 且确定性/敏感；`create_refresh_token` 形态（43 字符、
   urlsafe 字符集）与唯一性；access token 声明（`typ=access`、`tv`、`exp>iat`、`sub` 字符串化）；
   异构密钥拒绝、过期拒绝。
4. **缓存不变量**：`delete`（含幂等缺失）；`clear()` 全清返回计数、缺失前缀返回 0；
   负 TTL 不写入；producer 返回 `None` 不缓存、producer 抛异常向上传播且不缓存；`cache_key` 分隔符；
   `invalidate_all` 同时清两套预置缓存。
5. **就绪探测**：可达但无 `alembic_version` → `db=True, migration_current=None`；有版本 → 回读版本号；
   不可达 → `db=False` 且 `error` 非空。
6. **错误契约**：基类默认 `400/cndb_error` 与 `to_payload`；构造覆盖 `code/status_code`；
   `TooManyRequestsError` 默认 `retry_after=60`、`429`。
7. **认证头极端形态**：方案大小写不敏感（`BEARER`/`bearer` 均可）、令牌首尾空白被裁剪并可放行；
   停用账号（`is_active=False`）的令牌 → 401。

## 5. 落地节奏

- **本轮（已交付）**：方案文档 + 上述极端用例；`make check-fast` → `make test` 全绿后提交。
- **下一轮（建议顺序）**：
  1. R1 限流键表容量治理（低风险、直接消除内存 DoS 面）+ 单测覆盖淘汰逻辑；
  2. R4 就绪探测增补 `migrated` 语义并在部署层决策；
  3. R2/R3 部署约束与无 client 降级；
  4. R5 缓存失效兜底策略复核（按写路径盘点缺失事件）；
  5. R7/R8/R9/R10 视实际部署形态逐项评估。
- 每轮遵守 `AGENTS.md`：`make check-fast` → `make test` → 文档更新 → `make push`；覆盖率不得低于 95%。

## 6. 待决与风险

- R9 依赖对钉版 bcrypt 截断行为的核实，未核实前不引入行为变更。
- R1 的淘汰策略需在"精确性"（滑动窗口语义）与"内存上界"之间取平衡，改动会影响限流边界语义，
  必须配套更新本方案第 4 节的限流用例。
- 多实例部署（R2）本质是架构选择，非代码缺陷；确需水平扩时按 `CacheBackend` 协议接 Redis，
  调用方无需改动。
