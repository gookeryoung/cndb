# 周期性外部数据同步与数据分析 · 方案（通用框架）

> 目标：在工作区内提供**通用**的「定期拉取外部数据 → 规范化/幂等同步进数据表 → 面向时序的分析可视化」能力。
> 股票日线、天气、新闻日报等均作为该框架的**场景实例**，而非专门功能。

状态：**方案（通用化修订版，待评审）**。

---

## 一、设计原则（本次修订的核心）

从"为股票做一个功能"改为"做一套**可配置的外部数据同步框架**，让股票/天气/新闻都只是配置 + 一个适配器"。

三条原则：

1. **声明式优先**：绝大多数源（天气 API、新闻 API、行情 JSON）都是"HTTP 请求 + JSON 解析"，用户通过 UI 配置 **请求模板 / 解析路径 / 字段映射 / 增量字段 / 幂等键 / 调度**即可接入，**无需写代码**。
2. **适配器兜底**：少数格式特殊或需要多页/分批/特殊鉴权的源（如腾讯日线、RSS、分页榜单），以内置 `Provider` 适配器封装，复用同一套调度与同步管线。
3. **领域无关的存储与分析**：数据一律落到 tables 的动态表，分析一律走 analytics；分页/游标/幂等/调度/失败重试全部与"股票/天气/新闻"无关。

> 一句话：**Provider（怎么抓）× SyncJob（抓什么、抓去哪、多久抓）× Cursor（从哪接着抓）× Normalizer（怎么落表）** 四者可自由组合。

---

## 二、现状盘点（可复用 vs 需通用化改造）

| 能力 | 位置 | 复用 | 通用化改造点 |
|---|---|---|---|
| 插件架构 | `plugins/base.py` | ✅ 直接复用 | 新插件命名 `datasource` |
| 动态数据表 | `plugins/tables/` | ✅ 落库目标 | 按 `match_keys` 自动建唯一索引（增强幂等） |
| HTTP 抓取 | `importing/api_fetch.py` | ✅ SSRF/重试/编码/处理器注册表 | **新增：请求模板化 + 分页 + 日期分片** |
| 响应处理器注册表 | `api_fetch.RESPONSE_HANDLERS` | ✅ 复用为 `Parser` 层 | 拆成 **Parser（响应→rows）** 与 **Provider（组合）** 两层 |
| 字段映射 | `importing/api_config_loader.py` 的 `field_mapping` | ✅ 复用为 `Normalizer` 层 | 泛化到任意源 |
| 幂等 upsert | `importer.py` + `core/records.find_rows_by_key` | ✅ 直接复用 | `match_keys` 由 job 级配置（不再硬编码 symbol/date） |
| 异步任务 | `importing/import_tasks.py` | ⚠️ 模式可借鉴 | 它是**一次性**导入；周期同步需**持久化任务定义 + 调度器** |
| 统一事件流 | `core/events.py` | ✅ 运行留痕/缓存失效 | 新增 `datasource.sync` 动作 |
| 数据分析 | `plugins/analytics/` | ✅ 通用分析底座 | **公式引擎补窗口函数**（分区分序） |
| 部署 | `docker-compose.prod.yml` / `deploy/backup.sh` | ✅ 借鉴 cron 模式 | 增加同步 CLI 的 cron 条目 |

### 关键结论（同前，未变）

- `tencent_stock` 只解析**实时快照**，无历史日线；`query_interval` 是**死配置**；全仓**无调度器**；公式引擎**无时序窗口函数**。

---

## 三、抽象设计（框架骨架）

### 3.1 四层抽象

```
Provider（数据源类型，代码级适配器，注册表）
  ├─ request_spec      请求构造：URL 模板 + params/headers/body 模板 + 分页策略 + 时间区间参数
  ├─ parser            响应文本 → rows（复用/扩展 RESPONSE_HANDLERS）
  ├─ cursor_strategy   游标语义：按什么字段增量（date / datetime / none / key_set）
  └─ normalizer        默认字段映射与类型归一（复用 field_mapping + 强制类型）

SyncJob（用户配置的同步任务实例，持久化）
  = Provider 引用 + 目标表 + 标的/参数集合 + 字段映射覆盖 + 幂等键 + 调度 + 启停

Cursor（增量状态）
  = 上次成功的"位置"（日期 / 时间戳 / 已见键集合），决定下次请求区间

Normalizer（落表）
  = 校验/清洗/类型归一 → 按幂等键 upsert（复用 Importer）
```

### 3.2 Provider 接口（示意）

```python
class SourceProvider(Protocol):
    name: str                          # "http_json" / "tencent_kline" / "rss_atom" / "openweather"
    label: str                         # 展示名
    params_schema: dict                # 供前端动态渲染参数表单
    default_cursor: CursorStrategy      # 默认增量语义
    supports_paging: bool

    def build_request(self, job, cursor) -> FetchConfig: ...        # 请求模板 → 真实请求
    def parse(self, text, cfg) -> list[dict]: ...                   # 响应 → rows（可委托 parser）
    def normalize(self, rows, job) -> list[dict]: ...               # 字段映射 + 类型归一
```

内置 provider 注册在 `PROVIDERS: dict[str, SourceProvider]`；专用逻辑（如腾讯日线解析）只填这三步。

### 3.3 请求模板化（通用化的关键能力）

让同一套 `http_json` provider 覆盖大多数源——用户填模板，运行时求值：

- **URL/参数占位符**：`{symbol}`、`{start_date}`、`{end_date}`、`{page}`、`{page_size}`、`{key}`（API key）。
- 例：`?param={symbol},day,{start_date},{end_date},320,qfq`
- 例：`?city={city}&date={date}&appid={key}`
- 例：`?page={page}&per_page=50`

**分页策略**（声明式）：`none` / `page`（页码递增直到空或达上限）/ `offset` / `cursor`（用响应里的 next 标记）——解决榜单/搜索类多页数据。

**时间分片策略**：当接口按时间区间返回（日线、历史天气），按 `cursor → today` 自动切分区间逐段抓取并合并。

---

## 四、数据模型（Provider 无关）

### 4.1 `datasource_sync_job`（同步任务定义）

| 字段 | 说明 |
|---|---|
| id / workspace_id / name | 基本信息 |
| provider | provider 名（`http_json` / `tencent_kline` / `rss_atom` / …） |
| table_id | 目标动态表（可"自动建表"或"追加到已有表"） |
| request_spec | JSON：`url_template / method / headers_template / params_template / body_template / data_path / paging / time_window` |
| parser | 解析器名（留空用 provider 默认；可覆盖为自定义 handler） |
| entrant_keys | JSON：标的/城市/关键词等参数集合，如 `["sh600519","sz000001"]` 或 `["北京","上海"]` |
| match_keys | JSON：幂等键，如 `["symbol","trade_date"]` / `["city","date"]` / `["url"]` |
| field_mapping | JSON：字段重命名/类型覆盖（复用既有格式） |
| cursor | JSON：`{"strategy":"date","field":"trade_date","backfill_start":"2024-01-01"}` |
| schedule | JSON：`{"mode":"daily","at":"17:10"}` / `{"mode":"interval","seconds":3600}` / `{"mode":"cron","expr":"0 6 * * *"}` |
| enabled / last_run_at / last_status | 启停与最近状态 |
| lease_owner / lease_until | 多进程互斥租约 |

### 4.2 `datasource_sync_run`（每次运行记录）

`id / job_id / started_at / finished_at / status(success|partial|failed) / cursor_from / cursor_to / fetched/inserted/updated/skipped / error_message / detail(JSON：逐参数/逐页成败)`

### 4.3 `datasource_session`（可选：鉴权/密钥）

集中管理 `{key: secret, headers}`，job 引用之，避免密钥散落在 request_spec。首期可直接内联，后续抽取。

### 4.4 目标表 schema

由 provider 的 `normalizer` 默认输出 + 用户 `field_mapping` 决定；首次同步"自动建表"（复用 `create_table_from_json_data`）；按 `match_keys` 建唯一索引。

---

## 五、核心机制（全部领域无关）

### 5.1 抓取管线

`build_request(job, cursor)` →（分页/时间分片循环）`fetch_json` → `parse` → `normalize` → 汇总 rows → `Importer` upsert。
所有 HTTP 均复用 `api_fetch` 的 **SSRF 防护 / 超时 / 重试 / 编码 / 体积上限 / query_interval 限流**。

### 5.2 增量游标策略（内置 4 种）

| 策略 | 语义 | 典型场景 |
|---|---|---|
| `date` | 按日期字段增量，cursor=最大日期；首跑按 backfill_start 回填 | 股票日线、天气（按天） |
| `datetime` | 按时间戳增量，cursor=最大发布时刻 | 新闻、日志、公告 |
| `key_set` | 记录已见幂等键集合（或依赖 DB 唯一约束），用于无稳定时间序的源 | 榜单、RSS 去重 |
| `none` | 每次全量覆盖（先删后插或 upsert 全量） | 最新快照类 |

非交易/无新数据时游标不前移（"没有新数据"与"同步失败"区分开）。

### 5.3 调度（同前，通用）

- **内置进程内调度器**：`lifespan` 启守护线程，每 ~30s 扫描到期 job；
- **CLI + 系统 cron**：`cndb sync run [--job-id|--all] [--dry-run]`；
- 二者共用 `scheduler.tick()`，靠 **DB 租约（lease）互斥** 防多副本重复执行；
- 支持 `daily@HH:MM`（收盘/凌晨）、`interval`（小时级天气）、`cron` 表达式。

### 5.4 幂等与失败处理

- 幂等：统一走 `match_keys` upsert；重复运行不产生重复行。
- 失败：单参数/单页失败不拖垮整体（`partial`）；`datasource_sync_run` + `core_event` 留痕；指数退避重试上限。
- 限流：job 级 `interval` 与全局并发池，避免打爆数据源。

---

## 六、内置 Provider 清单 + 接入新源的两条路径

### 6.1 内置（首期）

| provider | 用途 | 备注 |
|---|---|---|
| `http_json` | **通用 REST/JSON**（默认） | 覆盖绝大多数天气/新闻/行情源；声明式配置即可 |
| `tencent_kline` | A 股日线（前/后复权） | 解析 `fqkline` 嵌套 JSON |
| `gtimg_realtime` | 实时快照（沿用现有 `tencent_stock`） | 迁移既有处理器 |
| `rss_atom` | RSS/Atom 新闻源 | 解析 XML → title/link/source/published |
| `openweather` | 天气示例 | 或作为 `http_json` 模板示例 |
| `csv_endpoint` | 返回 CSV/TSV 的接口 | 复用编码探测 + csv 解析 |

### 6.2 接入新数据源

- **路径 A（声明式，零代码）**：选 `http_json`，填请求模板/解析路径/字段映射/增量字段/幂等键/调度 → 预览 → 保存即用。**覆盖 ~80% 场景。**
- **路径 B（适配器，少量代码）**：新增 `SourceProvider` 子类（三步：build_request / parse / normalize 之一二），注册即被 UI 自动发现。**处理特殊格式/鉴权/分页。**

---

## 七、场景实例映射（同框架，不同配置）

| 维度 | 股票日线 | 天气 | 新闻日报 |
|---|---|---|---|
| provider | `tencent_kline` / `http_json` | `http_json`(openweather) | `rss_atom` / `http_json` |
| entrant_keys | 股票代码列表 | 城市列表 | 源/栏目列表 |
| 粒度 | symbol × trade_date | city × date(或 date_hour) | source × url |
| cursor 策略 | `date`(trade_date) | `date`(date) | `datetime`(published_at) |
| match_keys | `(symbol,trade_date)` | `(city,date)` | `(url)` 或 `(source,guid)` |
| 字段 | ohlc/volume/amount | temp/humidity/weather/wind | title/link/summary/published_at |
| schedule | 每日 17:10 | 每小时/每日 | 每日 07:00 |
| 分析重点 | 均线/涨跌/波动 | 温度趋势/极值/温差 | 数量趋势/来源占比/热度 |

> 三者的**调度、游标、幂等、失败重试、存储、出图**全部共用同一套代码。

---

## 八、分析通用化

### 8.1 公式引擎补窗口函数（`analytics/services/formula.py`）

新增按「分区 + 排序」的窗口函数，实例无关：

`prev / lag / lead`、`ma([x],n)`、`rolling_sum / rolling_std`、`cumsum`、`rank`、`pct_change / diff`。

需要给引擎引入**分区键（partition_by）与排序键（order_by）**上下文（当前引擎为纯逐行/整列聚合）——这是主要改动点。分区键即"标的名/城市/来源"，排序键即"日期/时间"。

### 8.2 通用分析模板（不绑领域）

复用 analytics 既有「模板 + 典型示例 + 字段智能推荐」机制，生成通用套件：
- **时间趋势**（分区叠加）：指定 `entrant × time × metric`，出多线趋势（股票收盘、城市气温、每日新闻数）。
- **分布/占比**：数值直方、类别占比（天气类型、新闻来源）。
- **比率与变化**：`pct_change`、区间首末比、波动。
- **数据概览**：行数/时间跨度/缺失率。

### 8.3 领域模板包（可选增强）

以"模板包"形式提供股票/天气/新闻的**预置公式与图表预设**，但**不写死**——本质是通用模板的领域默认值，用户可改。

### 8.4 字段智能推荐扩展（`analytics/services/recommend.py`）

已能识别 metric/dimension/time/identifier；补充识别：
- 粒度标识列（symbol/city/source）→ `partition_dimension`；
- 日期/时间戳列 → `time`（若为 `date` 单选可识别）；
- 依此自动生成"时间趋势（分区叠加）"等典型示例。

---

## 九、API 设计（`/api/v1/workspaces/{wid}/datasource`）

| 方法 | 路径 | 说明 | 角色 |
|---|---|---|---|
| GET | `/providers` | 可用数据源适配器 + 参数 schema（前端动态表单） | viewer |
| GET / POST | `/sync-jobs` | 任务列表 / 新建（含预览校验、可自动建表） | viewer / editor |
| GET / PUT / DELETE | `/sync-jobs/{id}` | 详情 / 修改（启停、改调度与映射）/ 删除 | editor |
| POST | `/sync-jobs/{id}/run` | 立即运行一次 | editor |
| POST | `/sync-jobs/{id}/preview` | 抓一次并预览（不落库，含列画像） | viewer |
| GET | `/sync-jobs/{id}/runs` | 运行历史 | viewer |

权限复用 `services/core/access.check_workspace_permission`。

---

## 十、前端

- **数据源/同步任务页（工作区级）**：任务列表（名称/来源/目标表/频率/上次运行状态）。
- **新建向导（Provider 驱动）**：选 provider → 动态渲染 `params_schema` 表单 → 请求模板/解析路径 → 抓取预览（复用 `importPreview`/列画像）→ 字段映射（复用 `ImportDiffTable`/`SelectedFieldEditor`）→ 增量字段与幂等键 → 调度 → 保存。
- **任务详情**：启停、立即运行、运行历史抽屉、错误原因。
- **数据分析**：在 `AnalyticsPage` 增加"一键套用通用模板"入口（复用 `RecommendationPanel`）。

---

## 十一、CLI / 部署

- `cndb sync list|run|preview|jobs` — `cndb sync run [--job-id|--all] [--dry-run] [--json]`。
- 生产：`deploy/` 增加 cron（同 `backup.sh`）；或启用内置调度器（需单副本或依赖租约）。
- 文档：更新 `README.md`（特性/API）、`CONTEXT.md`（术语）、`CHANGELOG.md`。

---

## 十二、分阶段实施

| 里程碑 | 内容 | 产出 |
|---|---|---|
| **M1 通用抓取管线** | 拆 Provider/Parser 两层 + `http_json`（请求模板化 + 分页 + 时间分片）+ `normalize` + 单测 | 声明式接入一个 JSON 源并落表 |
| **M2 同步任务与调度** | `sync_job/run` 模型 + 游标策略 + `scheduler`（到期扫描+租约+退避）+ CLI + run/preview 端点 | 可"定期"、可增量、可手动 |
| **M3 Provider 与可观测/前端** | 内置 `tencent_kline`/`rss_atom` + 运行历史 + `core_event` + 前端任务页/向导 | 股票/新闻接入，可视可运维 |
| **M4 分析通用化** | 公式引擎窗口函数 + 通用模板（趋势/分布/占比/比率）+ 推荐扩展 | 任一时序数据可出图 |
| **M5 完善** | 鉴权会话/密钥管理、多源限流、领域模板包、天气 provider 示例 | 生产完备 |

每里程碑收尾：`make check-fast` → `make test` → 文档更新 → `make push`（覆盖率 ≥95%，新代码带测试）。

---

## 十三、测试与验收

- **单测**：请求模板求值（含缺参/转义）；分页终止条件；时间分片边界；4 种游标策略（首跑/已最新/无新数据/时间乱序）；`match_keys` upsert 幂等；租约互斥；窗口函数数值。
- **集成**：`http_json` 接一个假 JSON 源（天气样例）→ 首次回填 → 二次增量不重复；`rss_atom` 去重。
- **E2E**：新建任务→运行→表有数据→analytics 套通用模板出图。
- **验收**：`make check-fast`、`make test` 全绿，覆盖率达标，文档同步。

---

## 十四、决策点

| # | 决策 | 建议 |
|---|---|---|
| D1 | 插件命名 | `datasource`（概念：数据源同步），路由前缀 `workspaces` |
| D2 | 通用优先 vs 专用优先 | `http_json` 声明式为默认主路径；专用 provider 作便利封装 |
| D3 | 调度形态 | 生产 CLI + 系统 cron；开发/单机内置调度器；统一 DB 租约互斥 |
| D4 | 增量游标 | 内置 `date/datetime/key_set/none` 四策略，job 级可选 |
| D5 | 分析实现 | 扩展公式引擎加窗口函数（分区分序）为主 + 通用模板 |
| D6 | 密钥管理 | 首期内联于 request_spec；M5 抽为 `datasource_session` 集中管理 |
| D7 | 规模 | 时序全量可能超 `analytics` 单扫描上限 `MAX_SCAN_ROWS=20000`，需按区间/分区分析（同前） |

---

## 附：主要改动文件（预估）

**新增**
- `src/cndb/plugins/datasource/{__init__.py,plugin.py,models.py}`
- `src/cndb/plugins/datasource/providers/{base.py,http_json.py,tencent_kline.py,rss_atom.py,registry.py}`
- `src/cndb/plugins/datasource/services/{pipeline.py,cursor.py,scheduler.py,normalize.py}`
- `src/cndb/plugins/datasource/routers/{providers.py,sync_jobs.py}`
- `src/cndb/cli/sync.py`
- `src/cndb/alembic/versions/xxxx_add_datasource_sync.py`
- `frontend/src/pages/datasource/*`、`frontend/src/api/datasource.ts`
- `tests/test_datasource_*.py`

**改动（通用化）**
- `importing/api_fetch.py`：`tencent_stock` → 归入 provider/parser；新增模板求值与分页/分片能力（或在新 provider 层实现，`api_fetch` 保持通用请求内核）
- `analytics/services/formula.py`：窗口函数
- `analytics/services/recommend.py`：粒度列识别 + 分区趋势示例
- `README.md` / `CONTEXT.md` / `CHANGELOG.md`
