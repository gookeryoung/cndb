"""行级权限判定入口（ADR 0004）.

**唯一判定入口**（I5）：记录读写 / 审计 / 导出 / 数据分析共用本模块的行范围合成，
不再各写各的。

读范围合成（ADR 0004 §3，P0 仅读侧）：

```
0. 管理员豁免：row_filters_bypass(owner / 工作区 OWNER / 超管) → 全表（None）
1. 默认档 default = compile_filters(row_filters, row_filter_type)（空 → 无限制）
2. 命中规则中所有 view / edit 规则的 filters → 并集
3. 读范围 = OR(default, 命中规则…)；默认档为空时读=全表（规则读侧不产生额外效果）
```

要点：
- 默认档为空（人人可见全表）时，新规则的**读侧**不产生额外效果（ADR §7-5）；
- **edit 规则命中行同时并入读范围**（I4：读 ⊇ 写）；
- 规则 filters 引用当前用户被隐藏的字段 → 该条件**静默丢弃**（侧信道保护，ADR §7-1）；
- 未命中任何规则的主体只在其默认档范围内可见（I2）；
- 表外用户（无表 READ）不命中任何规则（I1），实际不可读由路由层 READ 门槛兜底。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, RowAction, RowPermission, RowSubject
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    get_hidden_field_names,
    get_row_scope,
    row_filter_conjunction,
    row_filters_bypass,
)

logger = logging.getLogger(__name__)

#: member_role 主体的档位取值（= RowSubject.MEMBER_ROLE 的 subject_id）
MEMBER_ROLE_WRITE = "write"
MEMBER_ROLE_READ = "read"

#: member_role 主体档位 → 展示名（前端选择器 / 规则列表）
MEMBER_ROLE_LABELS: dict[str, str] = {MEMBER_ROLE_READ: "查看者", MEMBER_ROLE_WRITE: "编辑者"}

#: 规则 filters 里可能引用隐藏字段的键
_FIELD_NAME_KEYS = ("field_name", "field")
#: 规则 filters 里的嵌套分组键
_NESTED_KEYS = ("__or__", "__and__", "__query_or__")


def _effective_member_role(db: Session, table: DataTable, user: User) -> str | None:
    """用户在表上的**有效成员档位**（ADR 0004 D5）.

    - ``write``：通过表级 ``EDIT_RECORDS``；
    - ``read`` ：通过 ``READ`` 但不通过 ``EDIT_RECORDS``；
    - ``None`` ：对该表无 ``READ``（表外用户，不命中任何规则，I1）。

    按有效档位（而非显式 ``TableMember.role``）匹配 —— 绝大多数成员靠工作区角色获权、
    根本没有 ``TableMember`` 行，用后者会让规则对他们永不命中。
    """
    if check_action(db, table, user, TableAction.EDIT_RECORDS):
        return MEMBER_ROLE_WRITE
    if check_action(db, table, user, TableAction.READ):
        return MEMBER_ROLE_READ
    return None


def applicable_row_rules(db: Session, table: DataTable, user: User | None) -> list[RowPermission]:
    """返回对该用户命中的行级规则（subject=user:me 或 subject=member_role:<有效档位>）.

    未命中任何主体（无表 READ）时返回空列表（I1）。
    """
    if db is None or user is None:
        return []
    tier = _effective_member_role(db, table, user)
    if tier is None:
        return []
    uid = str(user.id)
    rules = db.query(RowPermission).filter(RowPermission.table_id == table.id).all()
    return [
        rule
        for rule in rules
        if (rule.subject_type == RowSubject.USER and rule.subject_id == uid)
        or (rule.subject_type == RowSubject.MEMBER_ROLE and rule.subject_id == tier)
    ]


def _strip_hidden_conditions(items: Any, hidden: set[str]) -> Any:
    """递归剔除引用了 ``hidden`` 字段的条件项（侧信道保护，ADR §7-1）.

    返回清理后的 filters；被清空的嵌套分组整体丢弃。非 dict / list 原样返回。
    """
    if isinstance(items, dict):
        if any(items.get(key) in hidden for key in _FIELD_NAME_KEYS):
            return None
        cleaned: dict[str, Any] = {}
        for key, value in items.items():
            if key in _NESTED_KEYS:
                nested = _strip_hidden_conditions(value, hidden)
                if nested:
                    cleaned[key] = nested
            else:
                cleaned[key] = value
        return cleaned or None
    if isinstance(items, list):
        out: list[Any] = []
        for item in items:
            c = _strip_hidden_conditions(item, hidden)
            if c is not None:
                out.append(c)
        return out
    return items


def _compile_rule_scope(
    table: DataTable,
    sa_table: Any,
    rule: RowPermission,
    hidden: set[str],
) -> Any | None:
    """编译单条规则的命中条件（隐藏字段条件静默丢弃）；无有效条件返回 None."""
    from cndb.plugins.tables.services.core.query import compile_filters

    filters = list(rule.filters or [])
    if hidden:
        filters = _strip_hidden_conditions(filters, hidden)
    if not filters:
        return None
    logic = str(rule.filter_type or "AND").upper()
    return compile_filters(table, sa_table, filters, logic)


def row_read_scope_where(db: Session, table: DataTable, sa_table: Any, user: User | None = None) -> Any | None:
    """合成读范围 WHERE：默认档 ∪ 命中的 view/edit 规则（管理员豁免返回 None）.

    返回 ``None`` 表示**无行限制**（全表可见）。传入 ``user`` 时按统一口径：
    表所有者 / 工作区 OWNER / 超管豁免（见 ``row_filters_bypass``）。
    """
    if db is None:
        return None

    from cndb.plugins.tables.services.core.query import compile_filters

    if user is not None and row_filters_bypass(db, table, user):
        return None

    # 默认档（TablePermission.row_filters）
    scope = get_row_scope(db, table)
    default_where = compile_filters(table, sa_table, scope, row_filter_conjunction(db, table)) if scope else None
    if default_where is None:
        # 默认档无限制 → 全表可见；规则读侧不产生额外效果（ADR §7-5，I3）
        return None

    rules = applicable_row_rules(db, table, user)
    hidden = get_hidden_field_names(db, table, user) if user is not None else set()
    parts: list[Any] = [default_where]
    for rule in rules:
        clause = _compile_rule_scope(table, sa_table, rule, hidden)
        if clause is not None:
            parts.append(clause)

    if len(parts) == 1:
        return parts[0]
    return or_(*parts)


def row_edit_scope_where(db: Session, table: DataTable, sa_table: Any, user: User | None = None) -> Any | None:
    """合成写范围 WHERE（ADR 0004 §3）：``OR(默认档 if base_edit else ∅, edit 规则命中)``.

    返回 ``None`` 表示**无行限制**（全表可写）；返回恒假条件（``false()``）表示**无任何可写行**
    （仅有 ``view`` 规则 / 无任何写侧开放）。管理员豁免返回 None。

    要点：
    - ``base_edit = check_action(EDIT_RECORDS)``：无表编辑权的用户，默认档行不可直编（避免 viewer 误得写权）；
    - ``edit`` 规则的写权**独立于表 EDIT_RECORDS**（D2）：命中行即使无表编辑权也可写；
    - 默认档为空且 ``base_edit`` 为真 → 全表可写（返回 None）。
    """
    from cndb.plugins.tables.services.core.query import compile_filters

    if db is None:
        return None
    if user is not None and row_filters_bypass(db, table, user):
        return None

    base_edit = user is not None and check_action(db, table, user, TableAction.EDIT_RECORDS)
    parts: list[Any] = []
    if base_edit:
        scope = get_row_scope(db, table)
        if not scope:
            # 有表编辑权且无默认档 → 全表可写（无行限制）
            return None
        parts.append(compile_filters(table, sa_table, scope, row_filter_conjunction(db, table)))

    rules = applicable_row_rules(db, table, user)
    hidden = get_hidden_field_names(db, table, user) if user is not None else set()
    for rule in rules:
        if rule.action != RowAction.EDIT:
            continue
        clause = _compile_rule_scope(table, sa_table, rule, hidden)
        if clause is not None:
            parts.append(clause)

    if not parts:
        # 无默认档可用（无表编辑权）且无命中 edit 规则 → 无任何可写行
        return false()
    if len(parts) == 1:
        return parts[0]
    return or_(*parts)


def _row_in_scope(db: Session, sa_table: Any, row_id: int, scope: Any | None) -> bool:
    """单行是否落在给定行范围条件内（含软删除过滤）；scope=None 表示无行限制."""
    engine: Any = db.get_bind()
    where: list[Any] = [sa_table.c.id == row_id, sa_table.c._trashed.is_(False)]
    if scope is not None:
        where.append(scope)
    with engine.connect() as conn:
        return conn.execute(select(sa_table.c.id).where(and_(*where))).first() is not None


def can_view_row(db: Session, table: DataTable, sa_table: Any, row_id: int, user: User | None = None) -> bool:
    """该行是否落在调用者的**读范围**内（读范围外的行按不存在处理，I6）."""
    return _row_in_scope(db, sa_table, row_id, row_read_scope_where(db, table, sa_table, user))


def can_edit_row(db: Session, table: DataTable, sa_table: Any, row_id: int, user: User | None = None) -> bool:
    """该行是否落在调用者的**写范围**内（可直编）."""
    return _row_in_scope(db, sa_table, row_id, row_edit_scope_where(db, table, sa_table, user))


# ── 授予时的强制约束（ADR 0004 §6）────────────────────


def _parse_user_id(subject_id: Any) -> int | None:
    try:
        return int(subject_id)
    except (TypeError, ValueError):
        return None


def _is_workspace_member(db: Session, workspace_id: int, user_id: int) -> bool:
    from cndb.plugins.workspaces.models import WorkspaceMember

    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
        is not None
    )


def assert_row_rule_valid(
    db: Session,
    table: DataTable,
    operator: User,
    *,
    subject_type: str,
    subject_id: str,
    action: str,
) -> None:
    """授予行级规则时的强制约束，任一不满足即抛 ``HTTPException``（ADR 0004 §6）.

    - ``action`` ∈ {``view``, ``edit``}；``subject_type`` ∈ {``user``, ``member_role``}；
    - ``member_role`` 型：``subject_id`` ∈ {``read``, ``write``}；
    - ``user`` 型：必须是**本工作区成员** ∧ 对该表有 ``READ``（生效权 = min(行规则, 表 READ)）；
    - 不允许给自己配规则（与 ADR 0003 §4 的「target != operator」一致）。
    """
    from fastapi import HTTPException

    if str(action) not in tuple(RowAction):
        raise HTTPException(status_code=422, detail="动作只能是 view 或 edit")
    if str(subject_type) == RowSubject.MEMBER_ROLE:
        if str(subject_id) not in (MEMBER_ROLE_READ, MEMBER_ROLE_WRITE):
            raise HTTPException(status_code=422, detail="成员档只能是 read 或 write")
        return
    if str(subject_type) == RowSubject.USER:
        uid = _parse_user_id(subject_id)
        if uid is None:
            raise HTTPException(status_code=422, detail="成员 id 非法")
        if uid == int(operator.id):
            raise HTTPException(status_code=400, detail="无需给自己配置行级规则")
        if not _is_workspace_member(db, table.workspace_id, uid):
            raise HTTPException(status_code=422, detail="只能授权给本工作区成员")
        target = db.get(User, uid)
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if not check_action(db, table, target, TableAction.READ):
            raise HTTPException(status_code=422, detail="该成员无此表查看权限，无法授予行级规则")
        return
    raise HTTPException(status_code=422, detail="主体类型只能是 user 或 member_role")


def row_rule_subject_label(db: Session, rule: RowPermission) -> str:
    """规则的**主体展示名**（member_role → 档位中文名；user → 昵称 / 用户名）."""
    if str(rule.subject_type) == RowSubject.MEMBER_ROLE:
        return MEMBER_ROLE_LABELS.get(str(rule.subject_id), str(rule.subject_id))
    uid = _parse_user_id(rule.subject_id)
    user = db.get(User, uid) if uid is not None else None
    if user is None:
        return str(rule.subject_id)
    return user.nickname or user.username


__all__ = [
    "MEMBER_ROLE_LABELS",
    "MEMBER_ROLE_READ",
    "MEMBER_ROLE_WRITE",
    "applicable_row_rules",
    "assert_row_rule_valid",
    "can_edit_row",
    "can_view_row",
    "row_edit_scope_where",
    "row_read_scope_where",
    "row_rule_subject_label",
]
