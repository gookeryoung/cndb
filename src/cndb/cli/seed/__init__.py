"""演示数据注入（seed）—— 幂等：drop_all 后重建，每次全新。

数据源：
1. `examples/datasets/<工作区名>/*.csv` — 按文件夹名自动建工作区，CSV 自动推断字段建表导入
2. `examples/datasets/<工作区名>/views.json` — 每个工作区独立的视图种子配置，按 `表名 -> 视图列表` 组织
3. `examples/datasets/<工作区名>/fields.json` — 每个工作区独立的字段设置种子：必填/唯一约束、
   关联（link）+ 引用（lookup）示例字段
4. 硬编码业务表 — 部门表 + 员工表 + 报告模板，绑定到 datasets 创建的"某企业销售管理"工作区
5. `examples/datasets/<工作区名>/documents/` — 典型文档种子目录树

模块划分（原 `cli/seed.py` 单文件 2700 行，按职责拆分）：

| 模块 | 职责 |
|---|---|
| `sqlite`   | SQLite 连接级加速（synchronous=OFF）与全量清库 |
| `paths`    | datasets 目录定位、工作区显示名、views.json 扫描 |
| `datasets` | CSV/XLSX/API 建表、工作区创建 |
| `fields`   | 字段设置（fields.json）、字段引入规则与数据回填 |
| `documents`| documents/ 目录树解析与入库 |
| `views`    | views.json 视图种子 + demo 个人视图 |
| `templates`| 部门/员工业务表与报告模板种子 |
| `samples`  | 示例报告模板定义与落盘生成 |
| `demo`     | 「修改申请写模式」演示数据 |
| `runner`   | `seed()` 编排入口 |

本 `__init__` 保留 `cndb.cli.seed.<name>` 的历史可用性（CLI 入口 `main.py` 与
多个测试按旧路径导入私有辅助函数），新代码请直接从对应子模块导入。
"""

from __future__ import annotations

from cndb.cli.seed.datasets import _seed_datasets, _seed_xlsx_table
from cndb.cli.seed.documents import (
    _DOC_FRONT_MATTER_RE,
    _DOC_ORDER_PREFIX_RE,
    _DOC_STATUSES,
    _DOC_TABLE_REF_RE,
    _DOC_TAG_PALETTE,
    _document_create_nodes,
    _document_ensure_tag,
    _document_entry_sort_key,
    _document_find_existing,
    _document_tag_color,
    _document_title_from_name,
    _get_workspace_document_dirs,
    _iter_document_entries,
    _parse_document_front_matter,
    _resolve_document_table_refs,
    _seed_documents,
)
from cndb.cli.seed.fields import (
    FIELD_IMPORT_RULES,
    _apply_field_import_rules,
    _apply_field_settings,
    _backfill_rows_by_match,
    _get_sa_table_by_name,
    _load_field_settings,
)
from cndb.cli.seed.paths import _get_datasets_dir, _get_workspace_view_configs, _workspace_display_name
from cndb.cli.seed.permission_demo import _seed_permission_demo
from cndb.cli.seed.runner import seed
from cndb.cli.seed.sqlite import (
    _drop_all_tables_sqlite,
    _remove_seed_sqlite_pragmas,
    _set_seed_sqlite_pragmas,
)
from cndb.cli.seed.templates import _seed_sales_tables
from cndb.cli.seed.views import _seed_demo_personal_views, _seed_views, _validate_view_fields

__all__ = [
    "FIELD_IMPORT_RULES",
    "_DOC_FRONT_MATTER_RE",
    "_DOC_ORDER_PREFIX_RE",
    "_DOC_STATUSES",
    "_DOC_TABLE_REF_RE",
    "_DOC_TAG_PALETTE",
    "_apply_field_import_rules",
    "_apply_field_settings",
    "_backfill_rows_by_match",
    "_document_create_nodes",
    "_document_ensure_tag",
    "_document_entry_sort_key",
    "_document_find_existing",
    "_document_tag_color",
    "_document_title_from_name",
    "_drop_all_tables_sqlite",
    "_get_datasets_dir",
    "_get_sa_table_by_name",
    "_get_workspace_document_dirs",
    "_get_workspace_view_configs",
    "_iter_document_entries",
    "_load_field_settings",
    "_parse_document_front_matter",
    "_remove_seed_sqlite_pragmas",
    "_resolve_document_table_refs",
    "_seed_datasets",
    "_seed_demo_personal_views",
    "_seed_documents",
    "_seed_permission_demo",
    "_seed_sales_tables",
    "_seed_views",
    "_seed_xlsx_table",
    "_set_seed_sqlite_pragmas",
    "_validate_view_fields",
    "_workspace_display_name",
    "seed",
]
