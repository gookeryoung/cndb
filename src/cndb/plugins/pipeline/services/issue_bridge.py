"""发现物一键转 Issue（P2）：把表目标 finding 落到所属表的问题清单.

映射口径（ADR 0076 D15）：
- 仅 ``target_type == "table"`` 的发现物可转换，其余返回 400；
- 标题取 ``[严重度] 消息``（截断到 Issue 标题上限），消息为空时退化为
  ``<检查动作> 发现问题``；
- 描述携带检查动作、严重度与 ``locator`` 定位信息，不写字段值与单元格内容（D7）。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.issues.models import ISSUE_CATEGORY_DATA_ERROR, Issue
from cndb.plugins.issues.services import create_issue
from cndb.plugins.pipeline.models import PipelineFinding, PipelineRun
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404

#: Issue 标题上限（与 ``issues.schemas.IssueCreate.title`` 保持一致）
TITLE_MAX_LENGTH = 255


def _issue_title(finding: PipelineFinding) -> str:
    """按 ``[严重度] 消息`` 生成问题标题（超长截断）."""
    text = finding.message.strip() or f"{finding.check} 发现问题"
    title = f"[{finding.severity}] {text}" if finding.severity else text
    return title[:TITLE_MAX_LENGTH]


def _issue_description(finding: PipelineFinding) -> str:
    """生成问题描述（检查动作 + 严重度 + 定位信息）."""
    lines = [f"流水线检查：{finding.check}", f"严重度：{finding.severity}"]
    if finding.message.strip():
        lines.append(finding.message.strip())
    if finding.locator:
        lines.append("定位：" + json.dumps(finding.locator, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def convert_finding_to_issue(
    db: Session,
    workspace_id: int,
    run_id: int,
    finding_id: int,
    user: User,
) -> Issue:
    """把一条表目标发现物转换为所属数据表的问题.

    Args:
        db: 数据库会话。
        workspace_id: 工作区 ID（运行记录必须归属该工作区）。
        run_id: 运行 ID。
        finding_id: 发现物 ID（必须属于该运行）。
        user: 当前用户（需对目标表有读权限，问题创建权限与 issues 插件一致）。

    Raises:
        NotFoundError: 运行 / 发现物不存在。
        BadRequestError: 发现物目标不是数据表。
    """
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id, PipelineRun.workspace_id == workspace_id).first()
    if run is None:
        raise NotFoundError("运行记录不存在", code="pipeline_run_not_found")
    finding = (
        db.query(PipelineFinding).filter(PipelineFinding.id == finding_id, PipelineFinding.run_id == run.id).first()
    )
    if finding is None:
        raise NotFoundError("发现物不存在", code="pipeline_finding_not_found")
    if finding.target_type != "table" or finding.target_id is None:
        raise BadRequestError("仅数据表目标的发现物可转为问题", code="pipeline_finding_not_table")

    table = get_table_or_404(finding.target_id, workspace_id, db, user=user, action=TableAction.READ)
    return create_issue(
        db,
        table,
        user,
        title=_issue_title(finding),
        description=_issue_description(finding),
        category=ISSUE_CATEGORY_DATA_ERROR,
    )


__all__ = ["TITLE_MAX_LENGTH", "convert_finding_to_issue"]
