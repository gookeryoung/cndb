"""datasource 插件 ORM 模型：同步任务定义 + 运行记录 + 个人大模型连接.

四张表（见 ADR 0006「数据模型」与 ADR 0019）：

- ``datasource_session``         凭证会话：请求头 + 加密密钥（读接口只回显键名）
- ``datasource_user_llm_config`` 个人大模型连接：地址 / 模型 / 加密 API Key / 系统提示词覆盖（每用户一条）
- ``datasource_sync_job``        任务定义：Provider 引用 + 目标表 + 标的集合 + 幂等键 + 游标 + 调度 + 租约
- ``datasource_sync_run``        每次运行：状态 / 游标区间 / 增删改计数 / 逐请求明细

半结构化配置一律存 JSON 列（``request_spec`` / ``cursor`` / ``schedule`` 等），
与 ``ImportTask`` 的口径一致：不把用户配置拆成强类型列，避免每加一种 provider 就改表。
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class ScheduleMode(enum.StrEnum):
    """调度模式（落库为字符串值）."""

    MANUAL = "manual"  # 仅手动 / CLI 触发
    DAILY = "daily"  # 每天固定时刻
    INTERVAL = "interval"  # 固定间隔秒数
    CRON = "cron"  # 5 段 cron 表达式


class RunStatus(enum.StrEnum):
    """一次运行的状态（partial = 部分请求失败但已落库部分数据）."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class RunTrigger(enum.StrEnum):
    """触发来源（区分手动 / 调度器 / 外部 cron）."""

    MANUAL = "manual"
    SCHEDULER = "scheduler"
    CLI = "cli"


class DatasourceSession(TimestampMixin, Base):
    """凭证会话：集中管理请求头与密钥，供多个同步任务复用（ADR 0006 D6 / M5）.

    - ``headers``：非敏感请求头（User-Agent / Accept / Referer 等），运行期合并进 job 请求；
    - ``secrets``：密钥字典（如 ``{"api_key": "..."}``），**不随工作区导出**、读接口只回显键名；
      运行期作为模板变量注入（请求模板里写 ``{api_key}`` 即可）。
    """

    __tablename__ = "datasource_session"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secrets: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class UserLlmConfig(TimestampMixin, Base):
    """个人「大模型连接」：配一次即可被该用户创建的 ``llm_prompt`` 任务复用（ADR 0019）.

    - ``user_id``：唯一，一个用户至多一条连接；随用户级联删除；
    - ``base_url``：OpenAI 兼容服务地址（默认 ``https://api.deepseek.com``）；
    - ``model``：模型名（默认 ``deepseek-chat``）；
    - ``api_key``：**Fernet 密文**，读接口只回 ``has_api_key``，不随备份导出；
    - ``system_prompt``：可选覆盖系统提示词，空串表示使用内置默认值。
    """

    __tablename__ = "datasource_user_llm_config"
    __table_args__ = {"extend_existing": True}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 密文（core.crypto.encrypt_secret）；空串表示未配置
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")


class DatasourceSyncJob(TimestampMixin, Base):
    """同步任务定义.

    租约字段（``lease_owner`` / ``lease_until``）用于多副本互斥：
    同一 job 在任意时刻至多一个执行者（ADR 0006 I4）。
    """

    __tablename__ = "datasource_sync_job"
    __table_args__ = {"extend_existing": True}

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="http_json")
    # 目标动态表；为空表示"尚未绑定"（M3 向导里可自动建表后回填）
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # ── 抓取声明（Provider 无关） ──
    # {"url_template","method","headers_template","params_template","body_template",
    #  "data_path","encoding","paging":{...},"time_window":{...}}
    request_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parser: Mapped[str] = mapped_column(String(32), nullable=False, default="json")
    # 标的占位符名与取值集合，如 entrant_param="city" + entrant_keys=["北京","上海"]
    entrant_param: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entrant_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 幂等键（目标字段名）；为空退化为纯追加
    match_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 字段映射：{"源字段": {"name": "目标字段", "field_type": "float"}} 或 {"源字段": null}
    field_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 凭证会话（M5）：请求头 + 密钥集中管理，job 只引用不复制
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasource_session.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 同一 job 内相邻请求的最小间隔（毫秒；0 = 不限速），用于对源站友好的多参数 / 分页抓取
    rate_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── 增量与调度 ──
    # {"strategy":"date|datetime|key_set|none","field":"trade_date",
    #  "backfill_start":"2024-01-01","value":"2024-06-30"}
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # {"mode":"manual|daily|interval|cron","at":"17:10","seconds":3600,"expr":"0 6 * * *","timezone":"Asia/Shanghai"}
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # ── 执行租约（防多副本重复跑） ──
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class DatasourceSyncRun(TimestampMixin, Base):
    """一次同步运行的留痕（成功 / 部分成功 / 失败都落一行）."""

    __tablename__ = "datasource_sync_run"
    __table_args__ = {"extend_existing": True}

    job_id: Mapped[int] = mapped_column(
        ForeignKey("datasource_sync_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RunStatus.RUNNING.value, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default=RunTrigger.MANUAL.value)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 本轮抓取区间（date / datetime 游标才有值）
    cursor_from: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cursor_to: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {"plans":N,"succeeded":N,"failures":[{"label","entrant","page","error"}],
    #  "normalize_failures":[{"row_index","field","reason"}],"dropped_fields":N}
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


__all__ = [
    "DatasourceSession",
    "DatasourceSyncJob",
    "DatasourceSyncRun",
    "RunStatus",
    "RunTrigger",
    "ScheduleMode",
    "UserLlmConfig",
]
