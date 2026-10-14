"""bulk 路由聚合出口.

实现按职责拆到：
- bulk_crud.py：批量建行 / 删除 / 更新
- bulk_export.py：导出与导出文件名构造
- bulk_import.py：导入（同步 / 异步 / 分析 / 确认 / 重新分析 / 失败行）

本模块把三者挂在同一 router 下（路径与前缀完全不变），并转发既有私有符号
（测试按 cndb.plugins.tables.routers.bulk.<name> 引用）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from cndb.plugins.tables.routers.bulk_crud import router as bulk_crud_router
from cndb.plugins.tables.routers.bulk_export import router as bulk_export_router
from cndb.plugins.tables.routers.bulk_import import (
    _augment_task_result,
    _normalize_cleaning_actions,
)
from cndb.plugins.tables.routers.bulk_import import (
    router as bulk_import_router,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}", tags=["bulk"])
router.include_router(bulk_crud_router)
router.include_router(bulk_export_router)
router.include_router(bulk_import_router)

__all__ = ["_augment_task_result", "_normalize_cleaning_actions", "router"]
