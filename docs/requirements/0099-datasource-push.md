# 需求卡片：数据同步支持对外推送

- 编号：0099
- 来源 / 提出人：用户（会话 2026-11-05）
- 日期：2026-11-05
- 关联 ADR：0099（S2：新增同步方向 / 数据列 / 推送执行路径）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 数据同步除抓取外，还需支持对外推送。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「除抓取外」 | 同步任务增加 `direction`：`pull`（默认，外部→表，存量行为不变）/ `push`（表→外部）；迁移给存量任务回填 `pull` | `datasource/models.py`、alembic | 迁移测试 / 旧任务默认 pull |
| C2 | 「支持对外推送」 | 新增 `push_spec`：URL / method / headers / body 模板 / batch_size / max_rows / fields / watermark_field / timeout；创建 / 更新时统一校验 URL、字段、批次与超时 | `services/push.py`、`routers/sync_jobs.py`、`schemas.py` | 接口层：非法 URL / 字段 / batch 400；合法配置 201 |
| C3 | （执行） | `execute_job` 按 direction 分流：推送读取源表行 → 按批渲染 JSON → HTTP 发送；运行记录沿用 `datasource_sync_run`（rows_read / pushed / batches / failed） | `services/runner.py`、`services/push.py` | 单测：2 行分 2 批发送、请求体符合模板 |
| C4 | （增量） | `watermark_field` + `job.cursor.value` 只推送水位之后的新行；成功后推进水位 | 同上 | 单测：首轮全量、次轮只推新增行 |
| C5 | （失败口径） | 单批失败不中断后续批次；全部失败 = failed、部分失败 = partial；有失败批次时不推进游标，下次重试覆盖失败行 | 同上 | 单测：HTTP 500 落 failed、游标不动 |
| C6 | （前端） | 任务抽屉增加「方向」切换；推送模式提供源表 / URL / 方法 / 批次 / 字段 / 增量字段 / 请求头 / 请求体模板 / 调度；列表推送任务带「推送」标签 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 前端单测：切换推送后提交 `push_spec` |
| C7 | （安全） | 推送 URL 走 `validate_url`（SSRF）；请求头密钥可引用凭证会话（`{api_key}`），不新建第二套 HTTP 客户端 | `services/push.py` | 单测 / 代码审查 |
| C8 | （备份） | 同步任务导出 / 导入带上 `direction` / `push_spec`；旧备份缺省按 pull | `workspace_backup.py`、`backup_io.py` | 往返测试 |
| C9 | （工程口径） | CHANGELOG / CONTEXT / ADR 索引同步；后端 / 前端全量测试通过 | 文档 | `make flow` / `make check-fast` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 同步任务模型 | `datasource/models.py` | 新增 direction / push_spec |
| 2 | 任务执行 | `services/runner.py` | pull 路径不变，新增 push 分支 |
| 3 | 任务 API | `routers/sync_jobs.py`、`schemas.py` | 校验与字段透传 |
| 4 | 前端任务抽屉 | `DatasourcePage.tsx` | 方向切换 + 推送配置 |
| 5 | 工作区备份 | `workspace_backup.py`、`backup_io.py` | 推送配置随任务导出 |
| 6 | 调度 / 租约 / 运行历史 | 既有 scheduler / run 表 | 推送复用，不新增调度机制 |

## 未决问题（已确认）

- [x] ① 是否新建独立「推送任务」模型：**结论**复用同步任务 + direction，调度 / 租约 / 运行历史不再复制。
- [x] ② HTTP 客户端：**结论**复用 `core.http.open_http_client` 与 SSRF 校验。
- [x] ③ 增量口径：**结论**按可选 watermark 字段 + 任务 cursor value；失败批次不推进游标。
- [x] ④ 方案分级：**结论**S2（模型 / 迁移 / 执行路径 / 前端页面）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-05 用户口述）
