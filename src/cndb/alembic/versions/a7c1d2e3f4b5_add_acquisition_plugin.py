"""add_acquisition_plugin —— 采集策略四表（ADR 0085 P0）.

Revision ID: a7c1d2e3f4b5
Revises: b6c7d8e9f0a1
Create Date: 2026-11-02 12:00:00.000000

- ``acquisition_strategy``：四段规则 JSON + 调度 + 租约；
- ``acquisition_run``：一次运行（状态 / 规则快照 / 计数 / 预算 / 明细）；
- ``acquisition_round``：轮次明细（唯一键 ``(run_id, round_no)``）；
- ``acquisition_item``：条目台账（唯一键 ``(strategy_id, dedupe_key)``）。

纯新增表，存量零迁移；upgrade 幂等（表已存在跳过），downgrade 按依赖序删表。
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1d2e3f4b5"
down_revision: str | Sequence[str] | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRATEGY = "acquisition_strategy"
_RUN = "acquisition_run"
_ROUND = "acquisition_round"
_ITEM = "acquisition_item"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _base_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    """建采集策略四表（幂等：已存在跳过）."""
    if _table_exists(_STRATEGY):
        return

    op.create_table(
        _STRATEGY,
        *_base_columns(),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("filter_rule", sa.JSON(), nullable=False),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("iteration", sa.JSON(), nullable=False),
        sa.Column("llm", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_acquisition_strategy_workspace_id", _STRATEGY, ["workspace_id"])
    op.create_index("ix_acquisition_strategy_created_by_id", _STRATEGY, ["created_by_id"])
    op.create_index("ix_acquisition_strategy_enabled", _STRATEGY, ["enabled"])
    op.create_index("ix_acquisition_strategy_lease_until", _STRATEGY, ["lease_until"])
    op.create_index("ix_acquisition_strategy_ws_enabled", _STRATEGY, ["workspace_id", "enabled"])

    op.create_table(
        _RUN,
        *_base_columns(),
        sa.Column(
            "strategy_id",
            sa.Integer(),
            sa.ForeignKey(f"{_STRATEGY}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("round_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("progress_message", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("fetched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("inserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("docs_created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("docs_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("docs_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("budget_used", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_acquisition_run_strategy_id", _RUN, ["strategy_id"])
    op.create_index("ix_acquisition_run_status", _RUN, ["status"])
    op.create_index("ix_acquisition_run_strategy_started", _RUN, ["strategy_id", "started_at"])

    op.create_table(
        _ROUND,
        *_base_columns(),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey(f"{_RUN}.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("query", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("new_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accumulated_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("top_keywords", sa.JSON(), nullable=False),
        sa.Column("next_query", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("gap", sa.JSON(), nullable=False),
        sa.Column("review_state", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("stop_reason", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("run_id", "round_no", name="uq_acquisition_round_run_no"),
    )
    op.create_index("ix_acquisition_round_run_id", _ROUND, ["run_id"])

    op.create_table(
        _ITEM,
        *_base_columns(),
        sa.Column(
            "strategy_id",
            sa.Integer(),
            sa.ForeignKey(f"{_STRATEGY}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey(f"{_RUN}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("round_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("channel", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("dedupe_key", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("published_at", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("match_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("target_kind", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("payload_digest", sa.String(length=64), nullable=False, server_default=""),
        sa.UniqueConstraint("strategy_id", "dedupe_key", name="uq_acquisition_item_strategy_key"),
    )
    op.create_index("ix_acquisition_item_strategy_id", _ITEM, ["strategy_id"])
    op.create_index("ix_acquisition_item_run", _ITEM, ["run_id"])


def downgrade() -> None:
    """按依赖序删表（数据不恢复，与既有迁移一致）."""
    op.drop_table(_ITEM)
    op.drop_table(_ROUND)
    op.drop_table(_RUN)
    op.drop_table(_STRATEGY)
