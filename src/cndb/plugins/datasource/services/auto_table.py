"""llm_prompt 落表自动化 —— 空表自动建表 / 补字段 / 自动幂等键（ADR 0019）.

只在 ``provider=llm_prompt`` 的运行链路里被调用；其它 provider 的抓取与落表行为
完全不变（见 ADR 0019「口径」）。三个能力：

- :func:`ensure_job_table`  任务未绑定目标表时按任务名建表（同名未删除表直接复用）
- :func:`is_table_empty`    目标表「无未删除字段」或「无任何数据行」时视为空表，
  空表落表时允许自动补字段（``unknown_cols_strategy="add_text_field"``）
- :func:`infer_match_keys`  从本次行数据推断幂等键（单列唯一优先，其次 2-3 列组合）

自动幂等键只用于「任务原本没配 ``match_keys``」的场景：推断成功后由 runner 回填
``job.match_keys`` 并持久化，后续运行沿用同一组键，保证重复运行只更新不重复插入。

事务注意：SQLite 下建表 / DDL 前先 commit 释放写锁（与 ``routers/tables.py`` 的
建表流程同口径），否则同一连接上的反射 / DDL 会与未提交事务互相卡住。
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.tables.models import DataTable, ensure_default_view
from cndb.plugins.tables.services.core.ddl import (
    create_table as ddl_create,
)
from cndb.plugins.tables.services.core.ddl import (
    drop_table as ddl_drop,
)
from cndb.plugins.tables.services.core.ddl import (
    get_reflected_table,
)

logger = logging.getLogger(__name__)

# 组合推断时参与枚举的候选列上限（候选通常只有几列；封顶避免超宽表组合爆炸）
MAX_COMBO_CANDIDATES = 15

# 「像键」的名称片段：命中越多越优先（ADR 0019 决策 D2）
# 中英并列：大模型默认输出中文字段（见 llm/services/prompts.py），两套命名都要能识别
KEY_NAME_HINTS = (
    "date",
    "day",
    "id",
    "code",
    "symbol",
    "city",
    "name",
    "title",
    "time",
    "key",
    "uuid",
    "email",
    "phone",
    "month",
    "year",
    "week",
    "日期",
    "时间",
    "编号",
    "代码",
    "名称",
    "城市",
    "标题",
    "主题",
    "年份",
    "月份",
    "周",
)


# ── 目标表：按任务名建表 / 复用 ─────────────────────


def ensure_job_table(db: Session, job: DatasourceSyncJob) -> DataTable:
    """确保任务已有目标表：未绑定 ``table_id`` 时按任务名建表或复用同名未删除表.

    幂等语义：同工作区存在同名未删除表 → 直接复用并回填 ``job.table_id``，
    不重复建表；否则新建 ``DataTable`` + 物理表 + 默认视图「全部」。

    Args:
        db: SQLAlchemy Session（表元数据 / 默认视图写入这里）。
        job: 同步任务定义（``workspace_id`` / ``name`` / ``created_by`` 参与建表）。

    Returns:
        目标 ``DataTable``（已回填 ``job.table_id`` 并提交）。
    """
    existing = _find_table_by_name(db, job.workspace_id, job.name)
    if existing is not None:
        _bind_job_table(db, job, existing)
        return existing

    table = DataTable(
        workspace_id=job.workspace_id,
        owner_id=job.created_by,
        name=job.name,
    )
    table.ensure_db_name()
    db.add(table)
    # 先提交表元数据：SQLite 下持有写事务时反射 / DDL 会互相阻塞
    db.commit()
    _invalidate_table_list_cache(job.workspace_id)
    db.refresh(table)

    engine: Any = db.get_bind()
    try:
        ddl_create(engine, table)
        # 与手工建表一致：每张表至少有一个「全部」视图，否则成员进表看到空白
        ensure_default_view(db, table, owner_id=job.created_by, commit=True)
    except Exception:
        # 半初始化表会污染后续复用（同名表存在但物理表缺失）：DROP 物理表 + 删元数据
        with contextlib.suppress(Exception):
            ddl_drop(engine, table.db_table_name)
        with contextlib.suppress(Exception):
            db.rollback()
        db.delete(table)
        db.commit()
        raise

    _bind_job_table(db, job, table)
    return table


def is_table_empty(db: Session, table: DataTable) -> bool:
    """目标表是否为空（无未删除字段，或无任何未删除数据行）.

    物理表缺失（仅有元数据）时按空表处理：后续落表路径会因物理表不存在而报错，
    这里不提前吞掉该异常。回收站里的行不计入数据行（软删除不算「有数据」）。
    """
    if not table.active_fields():
        return True

    engine: Any = db.get_bind()
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
        stmt = select(func.count()).select_from(sa_table).where(sa_table.c._trashed.is_(False))
        with engine.connect() as conn:
            total = int(conn.execute(stmt).scalar_one())
    except Exception:
        logger.debug("统计目标表数据量失败，按空表处理: table=%s", table.db_table_name, exc_info=True)
        return True
    return total == 0


def candidate_names(rows: Sequence[Mapping[str, Any]], field_names: Sequence[str]) -> list[str]:
    """幂等键候选列：行 key 与目标字段名的交集；目标表无字段时直接用行 key.

    返回顺序按行内首次出现顺序，便于推断结果稳定可复现。
    """
    row_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                row_keys.append(key)
    fields = list(dict.fromkeys(field_names))
    if not fields:
        return row_keys
    field_set = set(fields)
    return [key for key in row_keys if key in field_set]


# ── 自动幂等键推断 ─────────────────────────────────


def infer_match_keys(
    rows: Sequence[Mapping[str, Any]],
    candidate_names: Sequence[str],
) -> list[str]:
    """从行数据推断幂等键；找不到唯一组合时返回 ``[]``（退化为纯追加）.

    判定顺序（ADR 0019 决策 D2）：

    1. 只考虑候选列里有非空值的列（全空列不可能是键）；
    2. 单列在**全部行**上唯一 → 直接采用；多列都唯一时按名称含
       ``date/day/id/code/symbol/city/name/title`` 等片段加权，权重高者优先；
    3. 无单列唯一时枚举 2 列、再 3 列组合，要求组合在全部行上唯一且各列非空；
    4. 最多返回 3 列，仍无解返回 ``[]``。
    """
    if not rows or not candidate_names:
        return []

    usable = _usable_columns(rows, candidate_names)
    if not usable:
        return []

    singles = [name for name in usable if _is_unique(rows, (name,))]
    if singles:
        # 权重高者优先；同权重保持候选顺序（max 对元组取第一个最大值，天然稳定）
        return [max(singles, key=lambda name: (_name_weight(name), -usable.index(name)))]

    # 组合推断：候选按「像键」程度排序，只枚举前 MAX_COMBO_CANDIDATES 个
    pool = sorted(usable, key=lambda name: (-_name_weight(name), usable.index(name)))[:MAX_COMBO_CANDIDATES]
    for size in (2, 3):
        for combo in combinations(pool, size):
            if _is_unique(rows, combo):
                return list(combo)
    return []


def _usable_columns(rows: Sequence[Mapping[str, Any]], candidate_names: Sequence[str]) -> list[str]:
    """过滤出「至少一行非空」且确实出现在行里的候选列."""
    usable: list[str] = []
    for name in dict.fromkeys(candidate_names):
        if not name:
            continue
        if any(not _is_blank(row.get(name)) for row in rows):
            usable.append(name)
    return usable


def _is_unique(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> bool:
    """组合在全部行上是否唯一且非空（任一行为空即判失败）."""
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = tuple(_cell_key(row.get(column)) for column in columns)
        if any(value is _BLANK for value in key):
            return False
        if key in seen:
            return False
        seen.add(key)
    return True


def _name_weight(name: str) -> int:
    """名称「像键」加权：命中 KEY_NAME_HINTS 的片段数量."""
    lowered = name.lower()
    return sum(1 for hint in KEY_NAME_HINTS if hint in lowered)


class _Blank:
    """空值哨兵：区分「空值」与合法的 None/0/False 之外的假值."""

    __slots__ = ()


_BLANK = _Blank()


def _is_blank(value: Any) -> bool:
    """宽松空值判断：None / 空串 / 纯空白字符串视为空."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _cell_key(value: Any) -> Any:
    """把单元格值转成可哈希键（list/dict 等结构按字符串形态参与比较）."""
    if _is_blank(value):
        return _BLANK
    if isinstance(value, (list, dict, set)):
        return str(value)
    return value


# ── 内部：表查询 / 缓存 ─────────────────────────────


def _find_table_by_name(db: Session, workspace_id: int, name: str) -> DataTable | None:
    """按「工作区 + 名称」找未删除的表（同名多张时取最早创建的一张）."""
    stmt = (
        select(DataTable)
        .where(
            DataTable.workspace_id == workspace_id,
            DataTable.name == name,
            DataTable.trashed.is_(False),
        )
        .order_by(DataTable.id)
    )
    return db.execute(stmt).scalars().first()


def _bind_job_table(db: Session, job: DatasourceSyncJob, table: DataTable) -> None:
    """回填 ``job.table_id`` 并提交（后续运行复用它，不再触发建表）."""
    job.table_id = table.id
    db.add(job)
    db.commit()


def _invalidate_table_list_cache(workspace_id: int) -> None:
    """失效数据表列表缓存（建表后读-写一致，参考 tables.py 同名函数）."""
    from cndb.core.cache import cache_key, list_cache

    list_cache.clear(cache_key("tables", workspace_id))


__all__ = [
    "KEY_NAME_HINTS",
    "MAX_COMBO_CANDIDATES",
    "candidate_names",
    "ensure_job_table",
    "infer_match_keys",
    "is_table_empty",
]
