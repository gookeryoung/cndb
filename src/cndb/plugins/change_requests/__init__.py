"""change_requests 插件包：修改申请模型与插件注册的对外门面."""

from __future__ import annotations

from cndb.plugins.change_requests.models import (
    CHANGE_OP_CREATE,
    CHANGE_OP_DELETE,
    CHANGE_OP_UPDATE,
    CHANGE_OPS,
    CR_ACTION_CLOSE,
    CR_ACTION_COMMENT,
    CR_ACTION_MERGE,
    CR_ACTION_REOPEN,
    CR_ACTION_UPDATE_BASE,
    CR_STATUS_CLOSED,
    CR_STATUS_MERGED,
    CR_STATUS_OPEN,
    CR_STATUSES,
    ChangeItem,
    ChangeRequest,
    ChangeRequestAction,
)
from cndb.plugins.change_requests.plugin import ChangeRequestsPlugin, plugin

__all__ = [
    "CHANGE_OPS",
    "CHANGE_OP_CREATE",
    "CHANGE_OP_DELETE",
    "CHANGE_OP_UPDATE",
    "CR_ACTION_CLOSE",
    "CR_ACTION_COMMENT",
    "CR_ACTION_MERGE",
    "CR_ACTION_REOPEN",
    "CR_ACTION_UPDATE_BASE",
    "CR_STATUSES",
    "CR_STATUS_CLOSED",
    "CR_STATUS_MERGED",
    "CR_STATUS_OPEN",
    "ChangeItem",
    "ChangeRequest",
    "ChangeRequestAction",
    "ChangeRequestsPlugin",
    "plugin",
]
