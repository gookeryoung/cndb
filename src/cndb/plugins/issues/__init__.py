"""issues 插件包：问题清单模型与插件注册的对外门面."""

from __future__ import annotations

from cndb.plugins.issues.models import (
    ISSUE_ACTION_CLOSED,
    ISSUE_ACTION_CREATED,
    ISSUE_ACTION_REOPENED,
    ISSUE_CATEGORIES,
    ISSUE_CATEGORY_DATA_ERROR,
    ISSUE_CATEGORY_OTHER,
    ISSUE_CATEGORY_QUESTION,
    ISSUE_CATEGORY_SUGGESTION,
    ISSUE_STATUS_CLOSED,
    ISSUE_STATUS_OPEN,
    ISSUE_STATUSES,
    Issue,
    IssueComment,
    IssueEvent,
)
from cndb.plugins.issues.plugin import IssuesPlugin, plugin

__all__ = [
    "ISSUE_ACTION_CLOSED",
    "ISSUE_ACTION_CREATED",
    "ISSUE_ACTION_REOPENED",
    "ISSUE_CATEGORIES",
    "ISSUE_CATEGORY_DATA_ERROR",
    "ISSUE_CATEGORY_OTHER",
    "ISSUE_CATEGORY_QUESTION",
    "ISSUE_CATEGORY_SUGGESTION",
    "ISSUE_STATUSES",
    "ISSUE_STATUS_CLOSED",
    "ISSUE_STATUS_OPEN",
    "Issue",
    "IssueComment",
    "IssueEvent",
    "IssuesPlugin",
    "plugin",
]
