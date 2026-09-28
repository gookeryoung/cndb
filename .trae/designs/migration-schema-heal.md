# 迁移 schema 自愈（schema drift heal）

## 背景

线上故障：安装版创建报表模板报 `table reports_template has no column named extra_table_ids`。

根因链：`reports_template` 历史上由 `create_all` 兜底建表（当时模型 schema 尚无
`extra_table_ids` 等新列），而 `alembic_version` 被 stamp 到当时的 head
（d8e9f0a1b2c3，链序位于加列迁移 b3c4d5e6f7a8 / d4e5f6a7b8c9 / e5f6a7b8c9d0 之前）。
版本标记**越过**加列迁移后，新版 `upgrade head` 永不重放已"应用"的迁移，缺列永不修复；
`upgrade` 中途失败走 `create_all + stamp head` 兜底时同样把缺列库盖戳为最新版本。

create_all / seed / restore 等任何"自建表 + stamp"流程与后续加列迁移之间都存在同一
裂口，必须在启动迁移的出口处统一自愈，而非逐迁移打补丁。

## 接口定义

`core/migrations.py` 新增内部函数（均不导出，由 `ensure_db_migrated` 编排）：

- `_render_add_column_ddl(col: Column, dialect) -> str | None`
  - 将 ORM 列编译为 `ALTER TABLE ADD COLUMN` 的列定义片段（`CreateColumn.compile`）。
  - 返回 `None` 表示无法安全补建：主键自增列；NOT NULL 且无 `server_default`
    （存量表有数据时 ADD COLUMN 必失败）。
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

`ensure_db_migrated` 三条路径（全新库 create_all+stamp / upgrade 成功 / 兜底
create_all+stamp）出口统一调用 `_heal_schema_drift()`。

## 数据模型

- 自愈基准为 `Base.metadata`（ORM 元数据）与库内实际 schema 的差集，纯增量
  （ADD COLUMN / CREATE INDEX），不改动既有数据与列。
- 补建的列不建 FK 约束（与迁移先例一致：SQLite 链上加列迁移不建 FK，FK 由 ORM
  声明、create_all 新库生效）。
- `ReportTemplate.extra_table_ids` 补 `server_default="[]"`，与迁移 b3c4d5e6f7a8
  的列定义对齐——NOT NULL 列带 server_default 是自愈可安全补建的前提。

## 算法与边界

- 幂等性：先 inspect 再补建，已存在的列/索引跳过；重复启动无副作用。
- 无法安全补建的列（NOT NULL 无 server_default）跳过并 warning，不阻断其余列。
- 存量行新列取值：等价于 ADD COLUMN 的 DEFAULT 语义（extra_table_ids='[]'、
  theme='minimal'、workspace_id=NULL）。
- 不重放迁移内的数据回填（如 e5f6a7b8c9d0 按 table_id 反推 workspace_id）；
  版本已越过但列缺失的库，回填逻辑不执行，存量模板 workspace_id 保持 NULL
  （仅全量 API 可见，与"表已删除保持 NULL"语义一致）。
- 版本落后的库走正常 upgrade：迁移先行补列，自愈比对后 no-op，不重复补建。
- 自愈目标库与 upgrade 目标库一致：均来自 `settings.DATABASE_URL` /
  `_build_config`（env.py 对编程式调用不覆盖已注入的 URL）。

## 依赖项描述

- 双份迁移链约定（根 `alembic/versions/` 与包内 `src/cndb/alembic/versions/`
  同内容）：本次同步补齐根目录缺失的 d4e5f6a7b8c9、e5f6a7b8c9d0 两份文件，
  双份 head 必须一致（e5f6a7b8c9d0）。新增迁移时两份必须同时落盘。
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
- [x] NOT NULL 且无 server_default 的缺失列跳过不崩
- [x] 自愈覆盖 Base.metadata 全部表（非仅 reports_template）
- [x] 双份迁移链 head 一致
