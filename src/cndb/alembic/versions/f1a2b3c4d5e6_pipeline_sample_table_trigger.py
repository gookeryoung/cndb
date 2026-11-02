"""示例流水线「工作区综合巡检」触发事件改为数据表变更

该示例同时含数据表与文档检查，会出现在数据表域的质量检查页；旧种子用
``document.saved`` 触发，表域用户看到的典型示例触发事件是「文档保存」，与页面
语境不符。改为 ``record.updated``（记录批量变更提交后触发）。

只迁移**未被改过**的种子定义：content 里同时命中旧注释与旧事件行才改写，用户
自行编辑过的同名流水线保持原样。``compiled`` 快照同步重编译，避免显示口径漂移。

Revision ID: f1a2b3c4d5e6
Revises: c8e2f4a6b8d0
Create Date: 2026-11-03 09:00:00.000000

"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c8e2f4a6b8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "pipeline_workflow"
_NAME = "工作区综合巡检"
_OLD_EVENT = "  events: [document.saved]"
_NEW_EVENT = "  events: [record.updated]"
_OLD_TITLE = "# 工作区内容物综合巡检（ADR 0076 示例）：数据表 + 文档混合检查。"
_NEW_TITLE = "# 工作区内容物综合巡检（ADR 0076 示例）：数据表变更触发，数据表 + 文档混合检查。"
_OLD_NOTE = "# document 检查族三类动作全覆盖，与数据表 job 并列执行互不阻断。"
_NEW_NOTE = (
    "# 该规则在数据表域的质量检查页出现，触发事件用 record.updated（记录批量变更）而不是\n"
    "# 文档保存；document 检查族三类动作全覆盖，与数据表 job 并列执行互不阻断。"
)


def _rewrite(content: str, *, upgrade: bool) -> str | None:
    """命中旧 / 新种子模板时返回改写后的原文，否则 None（用户改过则跳过）."""
    if upgrade:
        if _OLD_EVENT not in content or _OLD_TITLE not in content:
            return None
        return content.replace(_OLD_TITLE, _NEW_TITLE).replace(_OLD_NOTE, _NEW_NOTE).replace(_OLD_EVENT, _NEW_EVENT)
    if _NEW_EVENT not in content or _NEW_TITLE not in content:
        return None
    return content.replace(_NEW_TITLE, _OLD_TITLE).replace(_NEW_NOTE, _OLD_NOTE).replace(_NEW_EVENT, _OLD_EVENT)


def _apply(*, upgrade: bool) -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    from cndb.plugins.pipeline.services.dsl.parse import compile_workflow

    rows = bind.execute(
        sa.text(f"SELECT id, content FROM {_TABLE} WHERE name = :name"),  # noqa: S608 - 迁移内固定表名
        {"name": _NAME},
    ).fetchall()
    for row_id, content in rows:
        rewritten = _rewrite(str(content or ""), upgrade=upgrade)
        if rewritten is None:
            continue
        compiled = compile_workflow(rewritten).to_dict()
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET content = :content, compiled = :compiled WHERE id = :id"),  # noqa: S608
            {
                "content": rewritten,
                "compiled": json.dumps(compiled, ensure_ascii=False),
                "id": row_id,
            },
        )


def upgrade() -> None:
    _apply(upgrade=True)


def downgrade() -> None:
    _apply(upgrade=False)
