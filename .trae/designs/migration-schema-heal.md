# 迁移 schema 自愈（schema drift heal）

## 背景

线上故障一：安装版创建报表模板报 `table reports_template has no column named extra_table_ids`。

根因链：`reports_template` 历史上由 `create_all` 兜底建表（当时模型 schema 尚无
`extra_table_ids` 等新列），而 `alembic_version` 被 stamp 到当时的 head
（d8e9f0a1b2c3，链序位于加列迁移 b3c4d5e6f7a8 / d4e5f6a7b8c9 / e5f6a7b8c9d0 之前）。
版本标记**越过**加列迁移后，新版 `upgrade head` 永不重放已"应用"的迁移，缺列永不修复；
`upgrade` 中途失败走 `create_all + stamp head` 兜底时同样把缺列库盖戳为最新版本。

线上故障二（0.2.0 备份恢复）：升级 0.3.0 后恢复 examples 的 0.2.0 备份，所有数据表
内容无法显示。根因：`accounts_user.role`、`tables_dataview.is_public`、
`tables_dataview.public_slug`、`tables_tablepermission.manage_data_role` 四列历史上
**只加在 ORM 模型上，迁移链从未覆盖**；旧备份恢复后 `upgrade head` 无迁移可放，
records API 权限检查对 `tables_tablepermission` 全列 SELECT 报
`no such column: tables_tablepermission.manage_data_role`。自愈层当时因
"NOT NULL 且无 server_default"拒绝补建（`manage_data_role` 仅有 Python 端
`default=""`），缺列持续存在。

create_all / seed / restore 等任何"自建表 + stamp"流程与后续加列迁移之间都存在同一
裂口，必须在启动迁移的出口处统一自愈；同时"只加模型不写迁移"的缺口需由迁移
f7a8b9c0d1e2 一次性补齐，双保险缺一不可。

## 接口定义

`core/migrations.py` 新增内部函数（均不导出，由 `ensure_db_migrated` 编排）：

- `_render_add_column_ddl(col: Column, dialect) -> str | None`
  - 将 ORM 列编译为 `ALTER TABLE ADD COLUMN` 的列定义片段（`CreateColumn.compile`）。
  - 返回 `None` 表示无法安全补建：主键自增列；NOT NULL 且既无 `server_default`
    也无法从 Python 端标量 default 合成的列（存量表有数据时 ADD COLUMN 必失败）。
- `_scalar_server_default(col) -> str | None`
  - 把 ORM 列的 Python 端标量 default 合成为 SQL DEFAULT 字面量（bool→'1'/'0'、
    int/float→str、str→单引号转义）；已有 server_default 或非标量 default
    （如 `default=dict`）返回 None。
  - `_render_add_column_ddl` 用合成结果构造影子 Column 参与编译，不改动原对象。
- `_heal_missing_columns(engine) -> list[str]`
  - 遍历 `Base.metadata.sorted_tables`，对库中已存在的表比对实际列，缺列则执行
    `ALTER TABLE ADD COLUMN <ddl>`；返回补建的 `表名.列名` 列表。
  - 单列失败仅记 warning 并继续（保持"缺列可诊断"优于"整库不可用"）。
- `_heal_missing_indexes(engine) -> list[str]`
  - 对库中已存在的表比对 ORM 元数据声明的显式索引（`Table.indexes`），缺则
    `CREATE INDEX` 补建；返回补建的索引名列表。
- `_heal_schema_drift() -> None`
  - 编排入口：取全局 engine 依次跑列自愈与索引自愈，有实际补建时记 warning。
  - 整体检查失败（如 inspect 异常）仅 warning，不阻断启动。
- `heal_schema_drift(database_url: str | None = None) -> list[str]`
  - 公开 API：按显式 URL 建 engine 执行列自愈与索引自愈，finally dispose，
    返回补建清单（`表名.列名` + 索引名）。
  - 供 restore 等非默认库流程调用；失败向上抛 SQLAlchemyError（恢复流程需显式
    感知），与启动期静默降级的 `_heal_schema_drift` 语义区分。

`ensure_db_migrated` 三条路径（全新库 create_all+stamp / upgrade 成功 / 兜底
create_all+stamp）出口统一调用 `_heal_schema_drift()`。

## 数据模型

- 自愈基准为 `Base.metadata`（ORM 元数据）与库内实际 schema 的差集，纯增量
  （ADD COLUMN / CREATE INDEX），不改动既有数据与列。
- 补建的列不建 FK 约束（与迁移先例一致：SQLite 链上加列迁移不建 FK，FK 由 ORM
  声明、create_all 新库生效）。
- `ReportTemplate.extra_table_ids` 补 `server_default="[]"`，与迁移 b3c4d5e6f7a8
  的列定义对齐——NOT NULL 列带 server_default 是自愈可安全补建的前提。
- 迁移 f7a8b9c0d1e2（当前 head）补齐四列（逐列检查存在性，幂等）：
  - `accounts_user.role` String(32) NOT NULL DEFAULT 'user'
  - `tables_dataview.is_public` Boolean NOT NULL DEFAULT 0
  - `tables_dataview.public_slug` String(12) NULL + 唯一索引 ix_tables_dataview_public_slug
  - `tables_tablepermission.manage_data_role` String(16) NOT NULL DEFAULT ''
  - 目标表整体不存在时跳过（由启动 create_all 兜底建表）；downgrade 同样按
    表/列存在性幂等跳过。

## 算法与边界

- 幂等性：先 inspect 再补建，已存在的列/索引跳过；重复启动无副作用。
- NOT NULL 无 server_default 的列：有 Python 端标量 default 时用
  `_scalar_server_default` 合成 DEFAULT 子句补建（存量行取该默认值）；无标量
  default（如 `default=dict/list`）跳过并 warning，不阻断其余列。
- 存量行新列取值：等价于 ADD COLUMN 的 DEFAULT 语义（extra_table_ids='[]'、
  theme='minimal'、workspace_id=NULL、manage_data_role=''、role='user'、
  is_public=0）。
- 不重放迁移内的数据回填（如 e5f6a7b8c9d0 按 table_id 反推 workspace_id）；
  版本已越过但列缺失的库，回填逻辑不执行，存量模板 workspace_id 保持 NULL
  （仅全量 API 可见，与"表已删除保持 NULL"语义一致）。
- 版本落后的库走正常 upgrade：迁移先行补列，自愈比对后 no-op，不重复补建。
- 自愈目标库与 upgrade 目标库一致：均来自 `settings.DATABASE_URL` /
  `_build_config`（env.py 对编程式调用不覆盖已注入的 URL）。

## 依赖项描述

- **包内迁移链是唯一真相源**（`src/cndb/alembic/versions/`，运行时经
  `_alembic_dir()` 定位）。仓库根 `alembic/versions/` 为早期遗留，已停更且与包内链
  分叉（多出 a7b8c9d0e1f2_add_governance），不做同步；演进迁移只落包内链。
  当前 head：f7a8b9c0d1e2（revises e5f6a7b8c9d0）。
- 恢复流程（`cli/restore.py::_migrate_after_restore`）在 upgrade head +
  create_all 补建缺失表之后调用 `heal_schema_drift(database_url)`，失败包装为
  RestoreError 终止恢复。
- 测试隔离约定：凡经 `ensure_db_migrated` 的测试必须同时 patch
  `settings.DATABASE_URL`（upgrade 目标）、`cndb.core.database.engine`
  （fresh 探测 / 兜底 create_all / 自愈目标）、`_db_is_fresh`（跳过真实库探测），
  否则会触碰真实用户库（`~/.cndb/data/cndb.db`），在服务运行时表现为
  `disk I/O error`。

## 验收项

- [x] 版本越过加列迁移的库：启动自愈后创建模板成功（ORM INSERT 含
      extra_table_ids/theme/workspace_id 不再报 no column）
- [x] 存量数据保留，新列取迁移约定的默认值，索引 ix_reports_template_workspace_id 补齐
- [x] 自愈幂等：重复启动不重复补建、不改数据
- [x] upgrade 失败走兜底路径后，自愈仍补齐已存在表的缺列
- [x] 版本落后的库走正常 upgrade 后自愈 no-op，版本到 head
- [x] NOT NULL 且无 server_default 也无标量 default 的缺失列跳过不崩
- [x] NOT NULL 仅有 Python 标量 default 的缺列被自愈补建（manage_data_role 契约，
      ORM 全列查询恢复可用）
- [x] 自愈覆盖 Base.metadata 全部表（非仅 reports_template）
- [x] heal_schema_drift 按显式 URL 自愈并返回补建清单，schema 对齐时返回空且幂等
- [x] 迁移 f7a8b9c0d1e2：0.2.0 时代库 upgrade head 补齐四列；create_all 时代
      已含部分列的库幂等通过；目标表缺失时跳过；存量数据保留取 server_default；
      downgrade 幂等
- [x] 恢复 0.2.0 备份（examples/backups/backup-0.2.0-*）后全部表
      records/fields/views API 200、TablePermission 全列查询正常
