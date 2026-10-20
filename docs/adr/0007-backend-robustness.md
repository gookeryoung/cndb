# ADR 0007: 后端健壮性加固与极端用例基线

Status: Proposed
Date: 2026-10-20
Related: `src/cndb/core/ratelimit.py`、`src/cndb/core/security.py`、`src/cndb/core/cache.py`、`src/cndb/core/database.py`、`src/cndb/core/errors.py`、`src/cndb/api/deps.py`、`src/cndb/core/events.py`、`src/cndb/plugins/tables/services/importing/import_tasks.py`
需求卡片: 无卡片（需求直接立项，原文见「口径」）

## 口径（需求 → 设计落点）

需求原文：**「把『会坏』路径显式化 —— 先补齐极端情况的可回归验证，再按风险优先级排期结构性加固。」**+ 约束 **「本方案提出的测试补充不改动业务逻辑，仅锁定既有行为；结构性加固项列入排期，单独提交。」**（本 ADR 无需求卡片，原文与 C 编号就地维护）

| C # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 先补齐极端情况的可回归验证 | 新增 `tests/test_backend_extreme_cases.py`，覆盖限流 / 令牌 / 缓存 / 就绪探测 / 错误契约 / 认证头六个无专门单测的模块边界 |
| C2 | 仅锁定既有行为，不改动业务逻辑 | 本轮提交只含测试与本文档，零 `src/` 改动；断言以现有实现口径为准 |
| C3 | 结构性加固项列入排期，单独提交 | 风险清单 R1-R10 按 P0/P1/P2 排期，每项独立提交、独立回归，不与锁行为测试混提 |

## Context

加固前先确认基线，避免重复造轮子。现有保障（以代码为准）：

| 域 | 已有保障 | 位置 | 结论 |
|---|---|---|---|
| 错误契约 | `CndbError` 族 + 全局 handler，`{"detail","code"}`；未捕获异常统一 500 | `core/errors.py`、`app.py` | 保留 |
| 请求事务 | `get_db` 异常显式 `rollback` | `core/database.py` | 保留 |
| 会话安全 | 刷新令牌只存 SHA-256、一次性轮换、复用检测即吊销全部会话；access token 走 `token_version` 代次失效 | `accounts/services/sessions.py`、`core/security.py` | 保留 |
| 登录防爆破 | 账号维度 + IP 维度（4 倍阈值）进程内滑动窗口，429 + `Retry-After` | `core/ratelimit.py` | 有缺陷（R1-R3） |
| 只读缓存 | TTL + LRU，写路径事件驱动精确失效 + 短 TTL 兜底 | `core/cache.py`、`core/events.py` | 有边界问题（R5-R6） |
| 迁移自愈 | 启动自动 `upgrade head`；就绪探测区分 DB 可达与迁移缺失 | `core/migrations.py`、`core/database.db_readiness` | 语义待定（R4） |
| 后台任务 | 导入 / 治理任务启动回收 + 关闭中断标记 | `app.py` lifespan、`importing/import_tasks.py` | 保留（R7 观察） |
| 观测 | `request_id` 贯穿访问日志 / 慢查询 / 事件流；慢请求必记 | `core/observability.py` | 保留 |

风险清单（证据逐条核对）：

| # | 域 | 失效模式 | 证据 | 优先级 | 处置 |
|---|---|---|---|---|---|
| R1 | 限流 | `_hits` 无容量上限：海量不同 IP / 账号喷洒时字典无界增长 → 内存耗尽 | `core/ratelimit.py` 的 `_hits: dict[str, deque]`，`_prune` 只裁剪被访问 key 的 bucket | **P1** | 惰性全表扫描过期 key（每 N 次写入或超阈值）+ key 数上限，超限按最早过期淘汰 |
| R2 | 限流 | 进程内计数不共享，多实例 / 多 worker 下防爆破被绕过 | 模块 docstring 已声明「单机单进程」，部署形态可能水平扩 | P2 | 部署文档显式声明约束；`CacheBackend` 同款抽象预留 Redis 后端接入点 |
| R3 | 限流 | `request.client is None` 时全部落入同一 `ip:unknown` 桶，可能误伤 | `core/ratelimit.py#ip_key`（`ip or "unknown"`） | P2 | 无 client 时以账号维度为主，或降级不计 IP 维度 |
| R4 | 就绪探测 | `alembic_version` 缺失只标 `migration_current=null` 仍返回 ready，未迁移库可能被负载均衡接入 | `core/database.py#db_readiness`（异常被吞、仅 debug 日志） | **P1** | `/api/health/ready` 增 `migrated` 布尔，是否 unready 由部署层决策 |
| R5 | 缓存 | 事件驱动失效为 best-effort：`record_event` 写失败即静默跳过失效 | `core/events.py#record_event`（失败 rollback 返回 None） | P2 | 关键写路径补显式失效或收紧 TTL（现 3~15s 兜底） |
| R6 | 缓存 | `get_or_set` 命中返回**同一对象引用**，调用方误改污染缓存 | `core/cache.py#get_or_set`（docstring 已警示） | P2 | 保持「只读约定」，不做 deepcopy（性能代价） |
| R7 | 后台任务 | 导入单阶段超时统一 600s，超大文件可能被误判失败 | `settings.IMPORT_TASK_TIMEOUT_SECONDS` | P2 | 超时改可配置 + 按文件大小分级；先观察 |
| R8 | 存储 | SQLite 写锁依赖 `busy_timeout=5000`，极长写事务仍可能 `database is locked` | `core/database.py`（`PRAGMA busy_timeout=5000`） | P2 | 保持 WAL + busy_timeout；长事务继续拆分 |
| R9 | 密码 | bcrypt 对 >72 字节密码存在截断语义，超长密码可能语义碰撞 | `core/security.py#hash_password` 直接 `hashpw` | P2 | **待核实**钉版 bcrypt 的 72 字节行为后再决定是否显式拒绝 |
| R10 | 时钟 | access token 无 `nbf`、解码无 `leeway`，多机时钟偏移可能导致「刚签发即过期」 | `core/security.py` 令牌解码 | P2 | 跨机部署时解码加秒级 `leeway` |

> 本轮未发现需立即修复的正确性缺陷：`record_event` 默认 `commit=True`（独立提交），登录失败审计不会被 `get_db` 的异常回滚吃掉（曾疑虑点已排除）。

**核心缺陷（需求要补的）**：六个核心模块的**边界行为没有被测试锁定** —— 限流窗口滑出、令牌声明、缓存不变量、就绪三分支、错误契约默认值、认证头形态此前只有「主路径」覆盖，一旦重构就会静默改变语义。

设计目标（不变量）：

- **I1 测试不改行为**：本轮只新增测试与文档，`src/` 零改动；若测试暴露真实缺陷，单独立项而不在本轮顺手修。
- **I2 优先级可裁决**：每项加固必须有「失效模式 + 证据 + 优先级」，无证据项不入排期。
- **I3 单项单提**：一项加固一次提交、一次回归，不与锁行为测试混合。
- **I4 覆盖率不注水**：阈值维持 95%，omit 白名单不动。

## Decision

### 1. 两层处置

1. **锁行为层（本轮）**：补极端用例，把既有语义写死；不碰 `src/`。
2. **加固层（后续期）**：按 R 编号逐项改实现，每项附专属用例更新（限流语义变化须同步改该层用例）。

### 2. 风险处置顺序

P1 先行：R1（消除内存 DoS 面）→ R4（就绪语义 `migrated`）→ R2 / R3（部署约束与无 client 降级）→ R5（写路径失效复核）→ R7 / R8 / R9 / R10（按实际部署形态评估）。

### 3. 测试缺口覆盖（本轮）

| 模块 | 缺口 | 新增用例 |
|---|---|---|
| `core/ratelimit.py` | 阈值边界、窗口滑出、键归一化、`configure` 钳制、并发线程安全 | `TestSlidingWindowLimiterExtremes`、`TestLoginRateLimiterExtremes` |
| `core/security.py` | `hash_token` / `create_refresh_token` 无直测；令牌声明（`typ` / `tv` / `exp`）与异构密钥 / 过期分支未锁定 | `TestSecurityTokenExtremes` |
| `core/cache.py` | `delete`、无参 `clear()`、负 TTL、producer 异常或返回 None、`invalidate_all`、`cache_key` 未覆盖 | `TestCacheInvariantExtremes` |
| `core/database.py` | `db_readiness` 三分支（可达未迁移 / 有迁移版本 / 不可达）未直测 | `TestDbReadinessExtremes` |
| `core/errors.py` | 基类默认 `status_code` / `code` 与 `TooManyRequestsError.retry_after` 默认值未锁定 | `TestErrorContractExtremes` |
| `api/deps.py` | 认证头极端形态：大小写方案、令牌首尾空白、停用账号令牌 | `TestAuthHeaderExtremes` |

具体断言口径：窗口边界（`t0+window` 仍计数、`t0+window+1` 归零）、参数钳制（`0 → 1`）、`retry_after` 未达阈值为 0、IP 维度为账号维度 4 倍、键归一化（去空白 / 小写 / `None→unknown`）、刷新令牌形态（43 字符 urlsafe）、`hash_token` 等于 SHA-256 hex、缓存负 TTL 不写入且 producer 异常不缓存、就绪三分支返回值、错误契约默认 `400/cndb_error` 与 `429/retry_after=60`、`BEARER`/`bearer` 均可且首尾空白被裁剪、`is_active=False` 的令牌 401。

### 4. 边界与例外

1. R9 依赖对钉版 bcrypt 截断行为的核实，未核实前不引入行为变更。
2. R1 的淘汰策略在「精确性（滑动窗口语义）」与「内存上界」之间取舍，改动会影响限流边界语义 → 必须同步改本轮限流用例。
3. R2 本质是架构选择（是否水平扩），非代码缺陷；确需水平扩时按 `CacheBackend` 协议接 Redis，调用方不动。
4. R6 明确不做 deepcopy：缓存契约是只读引用，写入方负责构造新对象。

### 5. 迁移 / 前端

无（纯后端测试与核心模块加固，无表结构与前端改动）。

### 6. 测试清单

**单测**：上表六个模块的极端用例；加固项各自新增（R1 淘汰逻辑、R4 `migrated` 分支）。

**回归**：`make test` 全量；覆盖率 `--cov=cndb` 不低于 95%。

### 7. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 极端用例基线（六个模块，不改 `src/`） | 低 |
| **P1** | R1 限流键表容量治理 + R4 就绪探测 `migrated` | 中（改动限流边界语义） |
| **P2** | R2 / R3 部署约束与无 client 降级、R5 写路径失效复核 | 中 |
| **P3** | R7 / R8 / R9 / R10 按部署形态逐项评估 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 是否顺手修复发现的问题 | 不修。本轮只锁行为，修复独立提交 | 混提会让「行为变更」藏在测试提交里，回归不可归因 | 边写测试边修（提交语义混乱、覆盖率对比失真） | 本轮无 `src/` 改动 |
| D2 | R1 淘汰策略 | 惰性全表扫描过期 key + key 数上限，超限按最早过期淘汰 | 不改滑动窗口精确语义，代价是每 N 次写入一次 O(n) 扫描 | 定时全表清理线程（与限流器生命周期耦合）；LRU（与窗口语义冲突） | 待改 `core/ratelimit.py` |
| D3 | R4 就绪语义 | 只加 `migrated` 布尔，unready 与否交给部署层 | 单机部署与迁移自愈并存，代码内直接 unready 会导致启动期探活死锁 | 未迁移即 503（阻断启动探测）；维持现状（无信号） | 待改 `core/database.py`、健康端点 |
| D4 | R6 缓存引用隔离 | 维持只读引用约定，不 deepcopy | deepcopy 对大对象有可见性能代价；写方构造新对象是既有约定 | 命中即 deepcopy（热点读接口提速收益会归零） | `core/cache.py`（不改） |

## Consequences

- **正向**：六个核心模块的边界语义有回归网，重构有底线；风险清单带证据与优先级，排期可裁决；加固与锁行为分离，提交可归因。
- **负向**：测试文件增加约一个模块量级的用例，`make test` 时长小幅上升；R1 加固后限流器多一条 O(n) 扫描路径（受 N 次写入节流）。
- **风险与缓解**：极端用例把现有实现口径写死，若现有口径本身有误，测试会「锁住错误行为」→ 本项目将其视为显式决策（D1），发现真实缺陷时单独立项并同步改用例。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 极端用例基线 | 已落地 | `src/cndb/core/ratelimit.py`、`src/cndb/core/security.py`、`src/cndb/core/cache.py`、`src/cndb/core/database.py`、`src/cndb/core/errors.py`、`src/cndb/api/deps.py` | `tests/test_backend_extreme_cases.py` | `45719fb4` |
| P1 R1 + R4 | 未开始 | `src/cndb/core/ratelimit.py`、`src/cndb/core/database.py` | `tests/test_backend_extreme_cases.py` | — |
| P2 R2 / R3 / R5 | 未开始 | `src/cndb/core/ratelimit.py`、`src/cndb/core/events.py` | `tests/test_backend_extreme_cases.py` | — |
| P3 R7 / R8 / R9 / R10 | 未开始 | `src/cndb/plugins/tables/services/importing/import_tasks.py`、`src/cndb/core/security.py` | — | — |

> P0 只新增测试与本文档，`src/` 零改动（D1）；加固期开工前须先核实 R9 的 bcrypt 截断行为。

## 交接（会话结束更新）

- 当前阶段：P0 已落地；P1（R1 + R4）未开始
- 已完成：现状基线核对、风险清单 R1-R10 分级、六个模块的极端用例
- 下一步：R1 键表容量治理（含淘汰单测）→ R4 `migrated` 语义；每项单独提交
- 已知坑：R1 改动会变更限流边界语义，必须同步更新 `TestSlidingWindowLimiterExtremes`；R9 未核实前不得改密码校验；`record_event` 独立提交（`commit=True`），审计事件不受 `get_db` 回滚影响
- 最近一次全绿：`make flow` 通过（2026-10-20，本地工作区）
