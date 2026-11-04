# ADR 0099: 数据同步支持对外推送

Status: Implemented
Date: 2026-11-05
Related: `src/cndb/plugins/datasource/`、`src/cndb/core/http.py`、`frontend/src/pages/datasource/`、ADR 0006、ADR 0075
需求卡片: `docs/requirements/0099-datasource-push.md`

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 除抓取外 | `DatasourceSyncJob.direction`：`pull` / `push`，存量默认 pull |
| C2 | 支持对外推送 | `push_spec`：URL / method / headers / body 模板 / 批次 / 字段 / 水位 / 超时；保存时统一校验 |
| C3 | 执行 | `execute_job` 按 direction 分流；`services/push.py` 读表 → 分批 → HTTP 发送 → 复用运行记录 |
| C4 | 增量 | `push_spec.watermark_field` + `job.cursor.value`；成功后推进水位 |
| C5 | 失败口径 | 逐批失败留痕；全部失败 failed / 部分失败 partial；有失败不推进游标 |
| C6 | 前端 | 任务抽屉方向切换 + 推送配置；列表显示「推送」标签 |
| C7 | 安全 | 复用 `validate_url` / `open_http_client`；凭证会话注入请求头 |
| C8 | 备份 | 同步任务导出 / 导入带 direction / push_spec，旧备份默认 pull |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 同步任务只有「外部→表」抓取语义 | `datasource/models.py`、`services/runner.py` | 无法把工作区数据回传业务系统 | 新增 C1/C3 |
| 2 | 任务已有调度 / 租约 / 运行记录 / 凭证会话 | `services/scheduler.py`、`datasource_sync_run` | 推送可完全复用这些基础设施 | 确认 C1/C3 |
| 3 | 平台已有 SSRF 校验与统一 HTTP 客户端 | `core/http.py` | 推送不自建网络层 | 确认 C7 |
| 4 | 表行读取有 DDL / 字段类型 / 软删口径 | `tables/services/core/ddl.py` | 推送字段必须与物理列对齐，排除 link / lookup 虚拟列 | 新增 C3/C4 |
| 5 | 备份已包含 sync_jobs | `workspace_backup.py` | 推送配置必须随任务导出，否则恢复后漂移 | 新增 C8 |

核心缺陷：**数据同步是单向入口，缺少从工作区表向外部系统的出口。**

设计目标（不变量）：

- **I1 默认向后兼容**：存量任务 direction=pull，原有抓取路径行为不变。
- **I2 单一批量口径**：推送按 push_spec.batch_size 分批；运行记录与抓取共用 fetched/inserted/skipped 字段。
- **I3 失败不吞数据**：有失败批次时游标不前进，重试覆盖失败行（接收方需幂等）。
- **I4 安全同源**：URL 必须过 SSRF；密钥优先走凭证会话，不写入 push_spec 明文。
- **I5 无虚拟列**：link / lookup 等无物理列字段不进入推送载荷。

## Decision

### 1. 数据模型

`datasource_sync_job` 新增：

- `direction: String(16) NOT NULL DEFAULT 'pull'`；
- `push_spec: JSON NOT NULL DEFAULT '{}'`。

`push_spec` 结构：

```
{
  "url_template": "https://example.com/ingest",
  "method": "POST|PUT|PATCH",
  "headers_template": {"Authorization": "Bearer {api_key}"},
  "body_template": {"items": "{rows}", "count": "{count}"},
  "batch_size": 100,
  "max_rows": 5000,
  "fields": ["名称", "日期"],
  "watermark_field": "日期",
  "timeout": 30
}
```

### 2. 判定算法（唯一入口）

- `validate_push_spec`：创建 / 更新唯一校验入口。
- `execute_push`：唯一推送执行入口；`execute_job` 按 direction 分流。
- 行选择：源表 active fields 中仅物理列；`watermark_field > job.cursor.value`，按水位字段 + id 升序，limit max_rows。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST/PUT /api/v1/workspaces/{wid}/datasource/sync-jobs` | 新增 `direction` / `push_spec` 字段；推送任务跳过抓取 provider / request_spec 校验，改为推送配置校验 |

### 4. 边界与例外

- 推送必须绑定源表；未绑定 / 表被删 → 400。
- `fields` 只允许源表字段；`link` / `lookup` 默认不进入载荷。
- 无 `watermark_field` 时每次全量推送（按 max_rows 截断）。
- 某批失败不中断后续批；有失败时游标不推进。
- `body_template` 留空默认 `{"rows": [...]}`；`{rows}` / `{count}` / `{table}` / `{job}` / `{batch}` 保留 JSON 类型。
- 请求头中的 `{api_key}` 等占位符从凭证会话解密注入；缺失变量直接报错（不静默空串）。
- 推送任务不提供「抓取预览」；运行历史 / 立即运行 / 调度复用现有入口。

### 5. 迁移

单条迁移 `19d835337b45_datasource_push_direction.py`（`down_revision=134adcb233cb`）：新增两列，存量回填 pull；幂等，downgrade 可还原。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 任务抽屉方向切换；推送配置表单；列表「推送」标签 |
| API | `frontend/src/api/datasource.ts` | `PushSpec` / `direction` / `push_spec` 类型 |
| 预览 | 同上 | 推送模式隐藏「保存并预览 / 抓取预览」 |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_datasource_push.py`：配置校验、分批发送、请求头 / 请求体模板、增量游标、HTTP 500 失败口径、API 创建 / 非法字段 400。
- `frontend/src/pages/datasource/DatasourcePage.test.tsx`：编辑任务切换推送后提交 push_spec。

**接口层**：`POST /datasource/sync-jobs` 推送任务创建 / 校验。

**迁移 / 备份**：迁移 head 常量更新；同步任务备份带 direction / push_spec。

**e2e（前端）**：本期未新增（组件测试覆盖主路径）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 / 迁移 / push_spec 校验 / execute_push | 低 |
| **P1** | runner 分流 / 运行记录 / 失败游标口径 | 中 |
| **P2** | 前端方向切换与推送表单 / 备份字段 | 中 |

## 决策记录

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 任务模型 | 复用 sync_job + direction，不新建 push_job | 调度 / 租约 / 运行历史 / 凭证全部复用 | 新建推送任务表（复制四套基础设施） | `models.py` |
| D2 | 配置载体 | `push_spec` JSON 与 `request_spec` 分离 | 抓取 / 推送声明语义不同，混写易误用 | 共用 request_spec（校验分支混乱） | `push.py` |
| D3 | HTTP 层 | 复用 `open_http_client` + `validate_url` | 平台已有 SSRF / 超时 / 重定向兜底 | 直接 httpx.post（绕过 SSRF） | `push.py` |
| D4 | 增量 | 可选 watermark + cursor.value | 简单、可解释；无水位时退化为全量 | 依赖 updated_at 隐式水位（用户不可见） | `push.py` |
| D5 | 失败游标 | 有失败批次不推进 | 避免失败行被游标跳过造成数据丢失 | 按成功批推进（会丢失败行） | `runner.py` |
| D6 | 前端入口 | 复用同步任务抽屉，方向切换 | 用户在一个地方管理拉 / 推；调度共用 | 新页面 / 新导航（重复） | `DatasourcePage.tsx` |
| D7 | 密钥 | 凭证会话 + 请求头模板占位符 | 复用已有加密会话，不落明文 | push_spec 内联密钥（备份泄密风险） | `push.py` |

## Consequences

- **正向**：数据同步从单向入口升级为双向通道；调度 / 租约 / 运行历史 / 凭证完全复用。
- **负向**：推送载荷模板需要用户理解 JSON 占位符；接收方需对重试批次做幂等。
- **风险与缓解**：失败批次不推进游标会重复成功行 → 文档明确要求接收方幂等；全量推送受 max_rows 限制。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 同步任务 / 调度 | `datasource_sync_job`、scheduler | 推送复用现有任务、租约、运行记录，不新建调度 | ADR 0006 |
| 工作区备份 | `sync_jobs[]` | 推送配置随任务导出 / 导入，旧备份默认 pull | ADR 0075 |
| HTTP 安全 | `core/http.py` | 推送与抓取共用 SSRF / 超时 / 重定向口径 | ADR 0006 / 0053 |
| 表字段口径 | `tables` DDL / field_types | 只推送物理列，link / lookup 不进入载荷 | ADR 0038 |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/services/push.py`、`src/cndb/alembic/versions/19d835337b45_datasource_push_direction.py` | `tests/test_datasource_push.py` | 本次 |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py` | `tests/test_datasource_push.py` | 本次 |
| P2 | 已落地 | `frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/api/datasource.ts`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py` | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | 本次 |

## 交接

- 当前阶段：全期已落地（P0 / P1 / P2）。
- 已完成：方向字段、push_spec 校验、分批推送、增量游标、失败留痕、前端推送表单、备份字段。
- 下一步：可补推送预览（只读渲染首批载荷）与接收方幂等键配置。
- 已知坑：有失败批次时游标不推进，成功行可能重复发送；接收方必须幂等。link / lookup 无物理列，不进入推送载荷。
- 最近一次全绿：`make flow`（本次提交前，2026-11-05）。
