# ADR 0075: 工作区全量备份与恢复（归档格式 + 覆盖恢复）

Status: Accepted（已评审，2026-10-31 需求方确认）
Date: 2026-10-31
Related: `src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/cli/backup.py`、`src/cndb/cli/restore/`、`frontend/src/pages/settings/WorkspaceBackupDialog.tsx`、ADR 0004 / 0006 / 0019 / 0048
需求卡片: `docs/requirements/0075-workspace-full-backup.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 完全备份 | 备份 JSON 升级为 v9，补齐 Context 表 #1-#10 全部工作区级数据；归档内附 uploads 附件与文档外存正文原文件 |
| C2 | 完全恢复 | 新增覆盖恢复端点：清空目标工作区业务数据后按 v9 全量重建；会话密钥、cursor、回收站、版本历史均还原 |
| C3 | 重构设计 | 新格式为归档（manifest v1 + backup.json v9 + files/）；`backup_io` 版本白名单扩到 9，旧版 1-8 JSON 导入路径不动 |
| C4 | 所有内容 | 二进制内容不再入 JSON，一律走归档 `files/` 原文件（见 D2） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 导出仅含文档最新正文，不含历史版本 | `plugins/workspaces/routers/workspaces.py:493-527` | 恢复后版本历史丢失 | 确认 |
| 2 | 草稿（含 diff）不在导出范围 | `plugins/documents/models.py:234` | 草稿丢失 | 确认 |
| 3 | 软删除文档被 `is_deleted.is_(False)` 过滤 | `workspaces.py:501` | 回收站内容丢失 | 确认 |
| 4 | 置顶、分享、文档变更请求不在导出范围 | `plugins/documents/models.py:322,202,270` | 恢复后置顶/分享断 | 确认 |
| 5 | 文档议题/评论/事件不在导出范围 | `plugins/documents/models.py:339-419` | 议题丢失 | 确认（事件流按卡片 Q3 排除，议题本体+评论纳入） |
| 6 | 表成员、视图可见性规则、导入/治理任务不导出（仅导表级+行级权限） | `plugins/tables/models.py:452-602`、`workspaces.py:448-459` | 协作与任务口径丢失；审计/治理任务按 Q3 排除 | 确认（tablemember、view visibility 纳入） |
| 7 | 数据源会话仅按名称引用、密钥不导出；entrant cursor 不导出 | `workspaces.py:529-566`、`plugins/datasource/models.py:60,181` | 恢复后须重配密钥、增量水位丢失 | 确认 |
| 8 | 同步运行历史（`datasource_sync_run`）不导出 | `plugins/datasource/models.py:139` | 流水类 | 确认（按 Q3 排除） |
| 9 | 工作区 JSON 备份不含 uploads 附件，文档外存内容仅解出明文正文 | `workspaces.py:494-495`、`cli/backup.py:20` | 附件引用（图片等）恢复后断链 | 确认 |
| 10 | LLM 个人配置与运行记录不随工作区备份 | `plugins/llm/models.py:31,54`、ADR 0019 | 按既定口径排除 | 确认（排除） |
| 11 | 备份为单 JSON，`version` 白名单 1-8 | `services/backup_io.py:78-84` | 无法承载二进制 | 确认 |
| 12 | 导入入口固定为「创建新工作区」，无覆盖恢复 | `workspaces.py:588-640`、`backup_io.py:61` | 无法原地灾备恢复 | 确认 |
| 13 | 系统级 CLI 备份（SQLite 全库 + uploads tar.gz + manifest）已存在 | `cli/backup.py:1-21`、`cli/restore/__init__.py:10-20` | 全库快照非单工作区可移植，两者定位互补 | 确认（保留，不合并） |
| 14 | 前端备份入口 `WorkspaceBackupDialog`，API `exportWorkspace/importWorkspace` | `frontend/src/api/workspaces.ts:43-45`、`frontend/src/pages/settings/WorkspaceBackupDialog.tsx` | 需新增归档导出与恢复入口 | 新增 |

**核心缺陷（需求要补的）**：工作区备份的数据模型只覆盖「结构 + 最新数据」，既缺时间维度（版本历史、草稿、回收站）与协作维度（成员、议题、置顶、分享），又缺二进制载体（附件、外存正文），且恢复语义只有「新建」没有「原地还原」。

设计目标（不变量）：

- **I1 全量往返一致**：导出→清空→覆盖恢复后，C1 清单内所有对象（内容与引用关系）逐一比对一致；流水类（Q3 排除项）除外。
- **I2 向后兼容**：version 1-8 旧 JSON 备份的导入行为与现状完全一致；旧备份导入结果不因本重构变化。
- **I3 单一判定入口**：v9 归档与旧 JSON 最终都收敛到同一个导入函数族；覆盖恢复与新建导入共用同一份数据落库逻辑，只差「先清后写」前置步骤。
- **I4 密钥口径显式**：密钥是否入备份由导出参数决定并写入 manifest；导入端不猜测，无密钥字段即解绑（与现状口径一致）。

## Decision

### 1. 数据模型

无新表、无新列，**零 alembic 迁移**。备份数据模型变化全部体现在备份文件内：

- 归档结构（复用 CLI 备份的 tar.gz + manifest 约定，见 D2）：

  ```text
  cndb-workspace-backup-<版本>-<时间戳>.tar.gz
  ├── manifest.json          # 归档协议版本 v1 + kind="workspace_backup" + 软件版本 + 选项(include_secrets) + 统计
  └── payload/
      ├── backup.json        # 工作区备份数据，version="9"
      └── files/             # 二进制内容原文件（按确定性键命名，路径由 backup.json 内引用）
          ├── uploads/…      # files_fileowner 对应的附件
          └── docs/…         # 文档外存正文 / 草稿 / 历史版本的外存内容块
  ```

- `backup.json` v9 在 v8 顶层结构（`workspaces.py:576-585`）上扩展：
  - `documents[]` 增加 `is_deleted`、`pinned`、`shares`、`issue`（本体+评论）子结构；
  - 新增 `document_versions[]`（全版本：内容、commit message、created_at/author）、`drafts[]`（含 diff）、`doc_change_requests[]`；
  - `tables[]` 增加 `members[]`；`views[]` 补 `visibility` 规则；
  - 新增 `datasource_sessions[]`（全字段；`include_secrets=false` 时密钥字段置 null 并在 manifest 声明）、`entrant_cursors[]`；
  - 明确**排除**：`tables_auditlog`、`tables_governancetask`、`datasource_sync_run`、`documents_issueevent`、`core_event`、`llm_user_config`、`llm_run`。
- 二进制引用方式：backup.json 内存确定性相对路径（如 `files/uploads/<sha256前缀>/<文件名>`），内容与元数据解耦，避免 base64 膨胀。

### 2. 判定算法（唯一入口）

- **导出唯一入口**：`build_workspace_backup_v9(workspace_id, include_secrets, db) -> (dict, files: list[FileEntry])`，置于 `plugins/workspaces/services/`（新模块 `workspace_backup.py`，现 `workspaces.py:430-585` 的导出逻辑迁入并扩展）。旧 `GET /export` 的 v8 JSON 继续由 v9 构建器**降采样**生成（v9 超集字段按 v8 口径裁剪），保证新旧出口同一份数据来源。
- **导入唯一入口**：`_import_backup_into_workspace`（`backup_io.py:25`）保持为落库入口，接受 version 1-9；v9 新增键缺失时按「无数据」处理（与既有旧版兼容口径一致）。归档解包层（`parse_workspace_archive`）负责校验 manifest、解出 backup.json 与 files/，再调用该入口。
- **覆盖恢复**：`restore_workspace(workspace_id, payload, user, db)` = 前置 `clear_workspace_content(workspace_id)` + `_import_backup_into_workspace`。clear 删除该工作区的表（含 DDL drop）、文档（含版本/草稿/回收站/议题/图表）、同步任务、游标、标签、置顶、分享，**保留** `workspaces_workspace` 行与 `workspaces_workspacemember`（成员与 owner 不动，D4）。clear 与 import 同事务边界，失败整体回滚。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /v1/workspaces/{wid}/export/archive` | 新增：StreamingResponse 返回 tar.gz，query 参数 `include_secrets`（默认 true） |
| `POST /v1/workspaces/{wid}/restore` | 新增：multipart 上传归档，覆盖恢复到当前工作区；仅 owner 可调用 |
| `POST /v1/workspaces/import` | 兼容扩展：请求体支持归档文件（v9）与旧 JSON（v1-8），按 manifest/`version` 字段分流到解包层或旧路径 |
| `GET /v1/workspaces/{wid}/export` | 保留：v8 JSON 口径，由 v9 构建器降采样输出（废弃预告，不在本期删除） |

### 4. 边界与例外

1. 覆盖恢复进行中若该工作区有运行中的同步任务：先标记任务停止并等待进程退出（复用 ADR 0006 任务管理），超时 30s 则拒绝恢复并提示。
2. `include_secrets=false` 导出的归档：manifest 标注；导入端对密钥为 null 的会话按现状「按名绑定、解绑缺失」处理，同步任务需重填密钥。
3. 归档内 files/ 缺失（用户改包、断点）：对应引用对象按「内容丢失」降级——附件记录保留但文件缺失，导入统计里显式列出缺失清单，不静默。
4. 覆盖恢复保留 workspace id/成员，但 `workspace` meta（名称/描述/可见性/tags）按备份还原（成员关系不动）。
5. 附件路径冲突：归档内以内容寻址键命名，导入端按现有 uploads 存储规则落盘，同名覆盖前先校验 sha256。
6. 大归档：解包到临时目录流式处理，不走内存全量装载（与 CLI restore 同口径）。

### 5. 迁移

零 alembic 迁移（无表结构变化）。兼容面全在备份 IO 层：

- `backup_io.py` 版本白名单扩至 `("1",…,"9")`；
- 旧 JSON（1-8）导入断言不回归（现有 `tests/test_backup_seed_roundtrip.py` 等保持通过）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/workspaces.ts` | 新增 `exportWorkspaceArchive`（blob）、`restoreWorkspace` |
| 备份对话框 | `frontend/src/pages/settings/WorkspaceBackupDialog.tsx` | 新增「归档备份（全量）」导出入口 + 密钥开关；新增「恢复到本工作区」入口（危险操作二次确认，输入工作区名确认） |
| 工作区设置 | `frontend/src/pages/settings/`（工作区设置页） | 恢复入口挂在工作区设置，非 owner 隐藏 |

### 7. 测试清单

**判定层（单测）**：v9 构建器逐键覆盖断言（含密钥开关两种口径）；`clear_workspace_content` 清理完整性（残留为零）；归档解包 manifest 校验、files 缺失降级；版本分流（9→解包层、1-8→旧路径）。

**接口层**：export/archive 端点（含 `include_secrets` 参数）；restore 端点权限（owner/非 owner）、运行中同步任务拒绝；import 归档创建新工作区。

**迁移 / 备份**：全量往返一致测试——建含附件/文档版本/草稿/回收站/议题/表成员/会话密钥/cursor 的工作区 → 导出 → 清空 → 覆盖恢复 → 逐表逐字段比对（I1）；v1-8 旧 JSON 样本导入回归（I2）；`include_secrets=false` 往返后密钥为空且任务解绑。

**e2e（前端）**：归档导出下载；归档恢复到新工作区；覆盖恢复危险确认流。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | v9 备份构建器（`workspace_backup.py` 迁移 + 扩展）+ 归档打包/解包 + v8 降采样出口 | 低（纯增量，不改导入行为） |
| **P1** | 导入端 v9 落库扩展 + `POST /import` 归档分流 + 覆盖恢复端点（clear + import） | 中（clear 的 DDL drop 与任务停止时序） |
| **P2** | 前端（导出/恢复 UI、密钥开关、二次确认）+ e2e | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 备份重构为「归档（manifest + v9 JSON + 文件）+ 双恢复语义（新建导入 / 覆盖恢复）」，收敛到唯一导出/导入入口 | 需求方 Q1/Q4 确认；I3 单一入口 | 继续单 JSON（附件 base64 膨胀、内存压力大）；直接扩 CLI 全库备份（非单工作区可移植，与工作区备份定位不同） | `plugins/workspaces/services/workspace_backup.py`、`backup_io.py` |
| D2 | 备份文件格式 | tar.gz 归档，复用 `cli/backup.py` 的 manifest 协议（新增 kind 字段区分系统级/工作区级） | Q4 确认；与 CLI 恢复工具链一致 | zip（Python 标准库对 zip64/权限支持弱于 tarfile，且与既有 CLI 备份格式割裂） | 归档层复用 `cli/backup.py` 打包约定 |
| D3 | 恢复语义 | 覆盖恢复到原工作区（保留 ws id 与成员，业务数据先清后写）；「导入为新工作区」保留兼容 | Q1 确认；灾备场景必须原地还原 | 仅新建导入（无法满足「恢复」）；快照级整库替换（SQLite 文件级恢复会连带用户/其他工作区，越界） | `POST /v1/workspaces/{wid}/restore` |
| D4 | 覆盖恢复保留边界 | 保留 `workspaces_workspace` 行、`workspaces_workspacemember`；meta 字段按备份还原 | 成员是部署级资产，不属工作区内容 | 连成员一起还原（会把部署里的用户体系改乱） | `clear_workspace_content` |
| D5 | 密钥口径 | 会话密钥纳入 v9，导出参数 `include_secrets` 开关（默认 true），manifest 声明；导入端密钥 null 即解绑 | Q2 确认；敏感信息显式化优于暗处理 | 永不导出（Q2 已否决：恢复后须手动重填不符合「完全恢复」）；明文硬编码导出无开关（泄露面不可控） | v9 `datasource_sessions`、manifest 选项 |
| D6 | 流水类数据 | 审计日志、同步运行历史、议题事件流、core_event 不备份 | Q3 确认；流水无恢复价值且体积大 | 可选开关（需求方明确选「不备份」，不加开关避免口径复杂化） | v9 明确排除清单 |
| D7 | 个人级 LLM 数据 | `llm_user_config`、`llm_run` 不随工作区备份 | ADR 0019 既定口径；卡片 Q5 | 随工作区导出（越出工作区边界） | — |

## Consequences

- **正向**：工作区备份/恢复达到灾备级（版本历史、回收站、附件、密钥、增量水位全覆盖）；单一构建器消除 v8 出口与真实数据的口径漂移；归档格式与 CLI 系统备份工具链统一。
- **负向**：`clear_workspace_content` 引入破坏性路径，须严格事务与任务停止时序；归档解包临时目录管理新增 I/O 复杂度；v8 导出端点进入维护态（不删除但不演进）。
- **风险与缓解**：覆盖恢复误操作 → 前端双重确认（勾选 + 输入工作区名）+ 仅 owner；归档被篡改 → manifest 校验 + files 缺失显式降级清单（不做静默）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 系统级全库备份 | `cli/backup.py`（SQLite + uploads tar.gz） | 保持不动，与工作区归档备份并存，kind 字段区分 | ADR 0075 |
| 行级权限规则随表备份 | `backup_io.py`（v4+） | v9 沿用，不改变结构 | ADR 0004 |
| LLM 连接为个人配置 | `plugins/llm/` | 不入工作区备份 | ADR 0019 / 0075 D7 |
| 数据源会话/任务 | `plugins/datasource/` | 会话全量+密钥（可关）与 cursor 纳入 v9 | ADR 0006 / 0075 |
| 文档图表 | `documents_chart` | v8 口径沿用，随 v9 导出 | ADR 0048 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/services/workspace_backup.py`（v9 构建器 / v8 降采样 / 归档打包与解包）；`routers/workspaces.py` `GET /{wid}/export/archive` | `tests/test_workspace_backup_v9.py` TestArchiveStructure | 见 git log |
| P1 | 已落地 | `services/backup_io.py`（版本白名单 1-9、v9 extras 落库、files_dir、旧行 id 映射）；`services/workspace_restore.py`（wait_sync_jobs_idle / clear_workspace_content / restore_workspace_from_backup）；`routers/workspaces.py` `POST /{wid}/restore`、`POST /workspaces/import/archive`（独立端点，偏离 D1「同端点分流」，multipart 与 JSON 载荷无法共端点） | `tests/test_workspace_backup_v9.py` TestRestoreRoundtrip；既有 v1-8 回归（version "9"→"99" 修正 2 处） | 见 git log |
| P2 | 已落地 | `frontend/src/api/workspaces.ts`（exportWorkspaceArchive / restoreWorkspace / importWorkspaceArchive）；`pages/settings/WorkspaceBackupDialog.tsx`（全量归档导出 + 密钥开关 + 覆盖恢复双重确认，非 owner 隐藏）；`pages/workspace/WorkspaceList.tsx` 导入弹窗支持 .tar.gz | `WorkspaceBackupDialog.test.tsx` 9 例；e2e `frontend/tests/e2e/critical/workspace-backup.spec.ts` 3 例 | 见 git log |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，门禁全绿
- 已完成：v9 归档构建/解包、v8 降采样出口、导入端 v9 extras、覆盖恢复（clear + import + meta 还原）、前端备份对话框与导入入口、单测 + e2e
- 下一步：`make check` 全绿后提交推送（`feat: 工作区全量备份与恢复（ADR 0075）`）
- 已知坑：测试环境 `LD_LIBRARY_PATH` 含旧 libsqlite3 导致 `_sqlite3` ImportError，须 `LD_LIBRARY_PATH= make test`；clear 的 DDL drop 前必须 commit 释放 RESERVED 锁；导出 `_store_content_bytes` 内联 50KB / 外存 2MB 阈值沿用 documents/services/content.py 口径
- 最近一次全绿：make check（本次提交前）
