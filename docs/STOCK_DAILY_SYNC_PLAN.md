# 股票日线定期拉取同步与数据分析 · 方案

> 目标：在工作区内实现「按标的定期拉取股票**日线**行情 → 幂等同步进数据表 → 面向时序的分析可视化」的完整闭环。

状态：**方案（待评审）**。评审后可据此拆分为实现任务。

---

## 一、现状盘点（可复用的能力）

| 能力 | 位置 | 说明 |
|---|---|---|
| 插件架构 | `src/cndb/plugins/base.py` | 插件自动发现、模型注册、路由挂载（`/api/v1/<prefix>`） |
| 动态数据表 | `src/cndb/plugins/tables/` | SQLAlchemy Core 运行时建表/加字段；19 种字段类型 |
| API 抓取 | `services/importing/api_fetch.py` | `FetchConfig` + **响应处理器注册表**（已内置 `tencent_stock`）+ `encoding` + `query_interval` |
| API 导入端点 | `routers/import_api.py` | 一次性抓取：分析列 / 建表 / 追加；JSON 配置批量建表 |
| 幂等 upsert | `services/importing/importer.py` + `services/core/records.find_rows_by_key` | 按 `match_keys` 做行匹配，已支持更新/新增分类 |
| 异步导入任务 | `services/importing/import_tasks.py` | 进程内后台线程 + 状态机 + 启动回收（**非持久调度**） |
| 统一事件流 | `core/events.py` | `record_event` 尽力而为写入 `core_event`，并驱动缓存失效 |
| 数据分析 | `src/cndb/plugins/analytics/` | 受限公式引擎 + 逐行派生 + 分组汇总 TopN + 图表 + 模板持久化 + 字段智能推荐 |
| 部署形态 | `docker-compose.prod.yml` / `deploy/backup.sh` | 单容器生产；已用系统 cron 做定时备份（可借鉴调度模式） |

### 关键结论

1. **已有实时快照能力，但无日线能力**：`tencent_stock` 处理器解析的是 `qt.gtimg.cn/q=` 的**实时快照**（`~` 分隔的买卖五档），不含历史日线。
2. **`query_interval` 是"死配置"**：它只被解析、落库、透传，**没有任何调度器消费它**去周期性执行抓取。
3. **全仓无调度基础设施**：`src/` 内无 apscheduler/cron/后台定时循环，`pyproject.toml` 亦无相关依赖。
4. **公式引擎缺时序函数**：仅有标量 `round/abs/sqrt/pow/ceil/floor` 与聚合 `sum/avg/count/min/max`，**没有** `prev/lag/ma/rolling_std/rank/cumsum/pct_change` 等窗口函数——而均线、涨跌幅、区间收益等股票分析强依赖这些。

---

## 二、差距（需要新建的功能）

| # | 缺口 | 影响 |
|---|---|---|
| G1 | 日线数据源处理器 | 无法获取历史日线 |
| G2 | 调度/定时机制（含持久化任务定义） | 无法"定期拉取" |
| G3 | 增量同步游标 + 幂等键 + 失败重试 | 会重复写行 / 拉全量 / 静默失败 |
| G4 | 时序分析能力（窗口函数 + 预置模板） | 无法算均线/涨跌/波动 |
| G5 | 标的与交易日历主数据 | 无法界定"每个交易日"与代码归一 |

---

## 三、总体架构

新增 **`stock` 插件**（`name="stock"`，`route_prefix="workspaces"`，与 tables/analytics 一致），职责单一、复用既有底座：

```
┌──────────────────────────────────────────────────────────────┐
│ 前端：股票同步任务页（列表/新建/启停/立即运行/运行历史）           │
│        + 数据分析页「股票分析」模板一键套用                        │
└───────────────┬──────────────────────────────────────────────┘
                │ REST /api/v1/workspaces/{wid}/stock/...
┌───────────────▼──────────────────────────────────────────────┐
│ stock 插件                                                     │
│  ├─ routers/      任务 CRUD / 手动 run / 运行记录 / 日线预览      │
│  ├─ models.py     StockSyncJob / StockSyncRun（+ 可选 Symbol）    │
│  ├─ services/                                                  │
│  │   ├─ kline_source.py   日线抓取（复用 api_fetch 处理器注册表） │
│  │   ├─ sync.py           增量计算 → match_keys upsert 落表      │
│  │   └─ scheduler.py      到期扫描 + 互斥租约 + 指数退避重试      │
│  └─ plugin.py     注册路由/模型；lifespan 启动调度线程            │
└───────┬───────────────────────┬───────────────────────────────┘
        │ 复用                   │ 复用
┌───────▼─────────────┐  ┌──────▼───────────────────────┐
│ tables：动态表 +     │  │ analytics：公式引擎(扩展窗口) │
│ Importer upsert      │  │ + 模板 + 推荐                 │
└──────────────────────┘  └──────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│ core：config / events(record_event) / database(SessionLocal)   │
└──────────────────────────────────────────────────────────────┘
```

### 为什么独立插件而非并入 tables

- tables 的 `import-api` 定位是**一次性**导入；"定期同步任务定义 + 调度 + 运行历史 + 增量游标"是独立生命周期，塞进 tables 会让其职责膨胀。
- 独立插件可独立开关、独立测试、独立前端入口，符合仓库既有插件化惯例。

---

## 四、数据模型（新表）

### 4.1 `stock_sync_job`（同步任务定义）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| workspace_id | FK | 所属工作区 |
| name | varchar | 任务名 |
| table_id | FK(DataTable) | 目标数据表（日线落库处） |
| symbols | JSON | 标的列表，如 `["sh600519","sz000001"]`（或引用 Symbol 表） |
| fetch | JSON | 抓取配置：`provider`（tencent/eastmoney…）、`adjust`（none/qfq/hfq）、`timeout`、`headers` |
| match_keys | JSON | 幂等键，默认 `["symbol","trade_date"]` |
| schedule | JSON | 调度：`{"mode":"daily","at":"17:10","weekdays":[1..5]}` 或 `{"mode":"interval","seconds":86400}` |
| backfill_start | date | 首次回填起始日（回填后仅增量） |
| last_trade_date | date | 增量游标：每个标的最后已同步交易日（也可下沉到 run 明细） |
| enabled | bool | 启停 |
| lease_owner / lease_until | varchar/datetime | 多进程互斥租约（见 5.2） |
| created_by | int | 创建人 |

### 4.2 `stock_sync_run`（每次运行记录）

| 字段 | 说明 |
|---|---|
| id / job_id / started_at / finished_at / status(success/partial/failed) |
| cursor_from / cursor_to | 本次同步的日期区间 |
| fetched_rows / inserted_rows / updated_rows / skipped_rows |
| error_message / detail(JSON 每个标的的成败) |

> 运行记录也可只落 `core_event`，但独立表更利于"任务级历史 + 分标的成败"查询与前端展示。

### 4.3 `stock_symbol`（可选，主数据）

`symbol / code / name / exchange(SH/SZ/BJ) / board / industry / listed_at / delisted_at`。
首期可由日线返回自带 `symbol` 反推，若需"筛选板块/行业"再落表。

### 4.4 目标日线表 schema（`sync` 首次自动建表）

`symbol(text) / trade_date(date) / open/close/high/low(float) / volume(number) / amount(float) / change_pct(float) / turnover(float)`，并对 `(symbol, trade_date)` 建唯一约束/索引以强化幂等。

---

## 五、核心机制

### 5.1 日线数据源（G1）

在 `api_fetch.RESPONSE_HANDLERS` 注册新处理器 **`tencent_kline`**（复用现有注册表与 `encoding/SSRF/重试/限流` 全套防护）：

- 候选接口（**需实测验证**）：腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=<sym>,day,<start>,<end>,<count>,<qfq|hfq>`，返回 `{code,data:{<sym>:{qfqday|day:[[date,open,close,high,low,volume,...]],...}}}`。
- 处理器职责：把嵌套 JSON 展平为 `[{symbol, trade_date, open, close, high, low, volume, amount, ...}]`，并做类型/日期归一。
- 备用源：东方财富 `push2his.eastmoney.com`（`klt=101&fqt=1`）——作为可插拔 `provider`。
- 落地要点：**复权口径**（`qfq` 前复权）必须显式配置，避免不同任务口径混用。

### 5.2 调度（G2）

推荐**双轨**，二者共用同一套 `scheduler.tick()`：

1. **内置进程内调度器**：`lifespan` 启动守护线程，每 ~30s 扫描 `enabled` 且到期的 job，调用 `sync`。
   - **必须做多进程互斥**：生产可能多 worker/多副本。用 `stock_sync_job.lease_owner/lease_until` 做**数据库租约**（CAS 抢占、过期可回收），或文件锁；避免同一 job 被并发重复执行。
   - 参考现有 `import_tasks` 的"进程内线程 + 启动回收"模式，但**任务定义持久化**（这才是"定期"的关键，import_tasks 不具备）。
2. **CLI + 系统 cron**：`cndb stock sync [--job-id|--all] [--dry-run]`，交由 `deploy/` 的 cron（同 `backup.sh` 模式）。优点：可观测、可运维、与容器重建解耦、天然单点。

> 决策点 D2：默认启用哪种（建议生产用 CLI+cron，开发/单机用内置调度器；两者可同时存在但靠租约互斥）。

### 5.3 同步语义（G3）

- **幂等**：以 `match_keys=["symbol","trade_date"]` 走 `Importer` upsert；重复运行不产生重复行。
- **增量**：`cursor_from = last_trade_date + 1 交易日`，`cursor_to = 今天`（收盘后可取当日；盘中取到上一交易日）。首次按 `backfill_start` 全量回填，之后仅增量。
- **交易日历**：非交易日跳过（用简单"周末 + 已知节假日表"起步，或直接以"接口返回是否有新数据"为准）。
- **失败处理**：单标的失败不影响其它；整体失败 → `stock_sync_run` 落 `failed` + `record_event`；按**指数退避**重试（次数上限）。
- **可观测**：每次运行写 `stock_sync_run` 与 `core_event`（`stock.sync` 动作），复用事件流做审计与缓存失效。
- **并发/限流**：复用 `api_fetch` 的 `query_interval`/重试；标的较多时分批，避免触发数据源限流。

### 5.4 时序分析（G4）

两条路线，建议**以扩展公式引擎为主、预置模板为辅**（决策点 D4）：

- **扩展公式引擎**（`plugins/analytics/services/formula.py`）：新增**窗口函数**，语义为"按维度分区、按排序字段排序的滑动窗口"：
  - `prev([x]) / prev([x], n)`、`lag/lead`、`ma([x], n)`、`rolling_std([x], n)`、`cumsum([x])`、`rank([x])`、`pct_change([x])`。
  - 引擎需引入"分组键 + 排序键"上下文（当前引擎为纯逐行/整列聚合），这是主要改动点。
- **预置分析模板**（复用 analytics 模板/示例机制，前端一键套用）：
  - K 线趋势：收盘价折线 + `ma(close,5/10/20)`；
  - 量价：成交量柱 + 收盘线；
  - 涨跌分布：`pct_change` 直方/占比；
  - 多股对比：按 symbol 分区叠加；
  - 区间收益/波动：起始末值比、`rolling_std`。
- **字段智能推荐扩展**（`services/recommend.py`）：识别 `symbol→dimension`、`trade_date→time`、价格/量→`metric`，自动给出上述模板。

---

## 六、API 设计（`/api/v1/workspaces/{wid}/stock`）

| 方法 | 路径 | 说明 | 最低角色 |
|---|---|---|---|
| GET | `/sync-jobs` | 任务列表 | viewer |
| POST | `/sync-jobs` | 新建任务（含首次建表/校验） | editor |
| GET/PUT/DELETE | `/sync-jobs/{id}` | 详情/修改（启停、改间隔）/删除 | editor |
| POST | `/sync-jobs/{id}/run` | **立即运行一次**（手动触发） | editor |
| GET | `/sync-jobs/{id}/runs` | 运行历史（分页） | viewer |
| POST | `/kline/preview` | 抓一次日线并预览（不落库，同 `import-api/analyze` 手感） | viewer |

> 权限校验复用 `services/core/access.py::check_workspace_permission`。

---

## 七、前端

- **股票同步任务页**（工作区级）：任务列表（名称/目标表/标的数量/频率/上次运行/状态）、新建向导（选表 or 自动建表 → 选标的 → 选数据源/复权 → 定频率）、启停开关、"立即运行"、运行历史抽屉（含失败原因）。
- **数据分析**：在 `AnalyticsPage` 增加"股票分析"预置模板入口，一键套用（复用现有 `RecommendationPanel`/模板示例机制）。
- 复用组件：`ApiImportDialog`（抓取配置表单可借鉴）、`grid/views/ChartView`（出图）。

---

## 八、CLI / 部署

- `cndb stock sync [--job-id <id> | --all] [--dry-run] [--json]` —— 供系统 cron/运维/手动补数。
- 生产：在 `deploy/` 增加 cron 条目（模式同 `backup.sh`），或启用内置调度器（需确认单副本或依赖租约互斥）。
- 文档：更新 `README.md`（特性/API 表）、`CONTEXT.md`（术语：股票同步任务）、`CHANGELOG.md`。

---

## 九、分阶段实施

| 里程碑 | 内容 | 产出 |
|---|---|---|
| **M1 打通链路** | `tencent_kline` 处理器 + `sync.py`（手抓→建表→按 `(symbol,trade_date)` upsert）+ 单测 | 能手动把一批标的日线同步进表 |
| **M2 定时** | `stock_sync_job/run` 模型 + `scheduler`（到期扫描+租约+重试）+ CLI + 手动 run 端点 | 可"定期拉取"，增量游标生效 |
| **M3 可观测/前端** | 运行历史 + `core_event` + 前端任务管理页 + 启停 | 可运维、可视 |
| **M4 分析** | 公式引擎窗口函数扩展 + 股票预置模板 + 推荐扩展 + 前端一键套用 | 均线/涨跌/波动等分析可用 |
| **M5 完善** | 主数据/交易日历/多数据源 provider/复权口径/多市场 | 生产完备 |

每个里程碑收尾遵循仓库工作流：`make check-fast` → `make test` → 文档更新 → `make push`（覆盖率门禁 ≥95%，新代码需配套测试）。

---

## 十、测试与验收

- **单测**：日线响应解析（正常/缺字段/空）；增量区间计算边界（首次回填、已最新、跨周末）；幂等（重复同步零新增）；租约互斥（并发只跑一次）；窗口函数数值正确性。
- **集成**：建 job → 手动 run → 目标表行数/内容正确 → 再次 run 不重复且能更新。
- **E2E**：股票任务页新建→运行→在 analytics 套用模板出图。
- **验收标准**：`make check-fast` 与 `make test` 全绿；覆盖率达标；文档同步更新。

---

## 十一、待确认的决策点

| # | 决策 | 建议 |
|---|---|---|
| D1 | 数据源与复权口径 | 腾讯 `fqkline`，默认 `qfq`（前复权），provider 可插拔 |
| D2 | 调度形态 | 生产 CLI + 系统 cron；开发/单机启用内置调度器；统一靠 DB 租约互斥 |
| D3 | 独立 stock 插件 vs 并入 tables | 独立插件（`route_prefix="workspaces"`） |
| D4 | 时序分析实现 | 扩展公式引擎（加窗口函数）为主 + 预置模板为辅 |
| D5 | 存储与规模 | 日线行数 = 标的数 × 交易日；需评估目标表行数与查询/分析性能（`analytics` 单次扫描上限 `MAX_SCAN_ROWS=20000`，股票全历史可能超限，需分区/限制区间） |
| D6 | 标的来源 | 首期任务内配置标的列表；后续再引入 `stock_symbol` 主数据筛选 |

---

## 附：涉及的主要改动文件（预估）

**新增**
- `src/cndb/plugins/stock/{__init__.py,plugin.py,models.py}`
- `src/cndb/plugins/stock/routers/{sync_jobs.py,preview.py}`
- `src/cndb/plugins/stock/services/{kline_source.py,sync.py,scheduler.py}`
- `src/cndb/cli/stock.py`（`cndb stock sync`）
- `src/cndb/alembic/versions/xxxx_add_stock_sync.py`
- `frontend/src/pages/stock/*`、`frontend/src/api/stock.ts`
- `tests/test_stock_*.py`

**改动**
- `src/cndb/plugins/tables/services/importing/api_fetch.py`（注册 `tencent_kline` 处理器）
- `src/cndb/plugins/analytics/services/formula.py`（窗口函数）
- `src/cndb/plugins/analytics/services/recommend.py`（时序字段识别）
- `README.md` / `CONTEXT.md` / `CHANGELOG.md`
