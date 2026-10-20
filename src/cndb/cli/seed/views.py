"""视图种子：各工作区 `views.json` 与 demo 用户硬编码个人视图。

写入前校验视图字段/筛选/图表配置引用的字段确实存在于目标表。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _validate_view_fields(vc: dict[str, Any], valid_fields: set[str], ws_name: str, table_name: str) -> bool:
    """校验单个视图配置里引用的所有 field_name 是否在目标表存在.

    Returns:
        True 表示通过，False 表示校验失败并已打印错误信息.
    """
    view_name = vc.get("name", "")
    for f in vc.get("filters", []):
        if f.get("field_name") not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 filter field_name='{f.get('field_name')}' 不存在"
            )
            return False
    for s in vc.get("sortings", []):
        if s.get("field_name") not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 sorting field_name='{s.get('field_name')}' 不存在"
            )
            return False
    # kanban 的 group_field / calendar 的 start_field / kanban/gantt/wbs 的 title_field 等
    vo = vc.get("view_options", {})
    for opt_key in (
        "group_field",
        "start_field",
        "end_field",
        "title_field",
        "start_date_field",
        "end_date_field",
        "actual_end_field",
        "progress_field",
        "assignee_field",
        # tree/wbs 层级视图（父节点字段）
        "parent_field",
        "status_field",
        # matrix 矩阵视图（纵横轴字段）
        "row_field",
        "column_field",
        # chart 图表视图（维度/度量/散点双轴字段；group_field 已在上方）
        "dimension_field",
        "measure_field",
        "x_field",
        "y_field",
        # chart K线蜡烛图（时间轴 + 开/高/低/收四价字段）
        "time_field",
        "open_field",
        "high_field",
        "low_field",
        "close_field",
        # flow 流程视图（流程节点字段；title_field 已在上方）
        "node_field",
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 view_options.{opt_key}='{opt_val}' 不存在"
            )
            return False
    # chart 多图形态：charts[] 逐条目校验字段引用（打印定位到 charts[i].<key>）
    charts = vo.get("charts")
    if isinstance(charts, list):
        for i, entry in enumerate(charts):
            if not isinstance(entry, dict):
                print(
                    f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' 的 view_options.charts[{i}] 不是对象"
                )
                return False
            for opt_key in (
                "dimension_field",
                "measure_field",
                "x_field",
                "y_field",
                "group_field",
                "time_field",
                "open_field",
                "high_field",
                "low_field",
                "close_field",
            ):
                opt_val = entry.get(opt_key)
                if opt_val and opt_val not in valid_fields:
                    print(
                        f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                        f"的 view_options.charts[{i}].{opt_key}='{opt_val}' 不存在"
                    )
                    return False
    return True


def _seed_views(
    db: Any,
    user: Any,
    tables_map: dict[str, dict[str, Any]],
    datasets_dir: Path | None,
    *,
    personal_owner_user: Any | None = None,
) -> int:
    """按各工作区文件夹下的 views.json 为每张表创建典型视图.

    views.json 视图条目新增可选字段 ``scope``：

    - ``"global"``（默认）→ 公共视图，``owner_id=None``，所有工作区成员可见。
    - ``"personal"`` → 个人视图，``owner_id=personal_owner_user.id``（未传则回退为调用者 ``user.id``）；
      仅该用户可见可改，用于演示"个人视图隔离"。

    新增的演示用 personal 视图不会占用表的"默认视图"槽位——默认视图始终为 global。
    """
    from cndb.plugins.tables.models import DataView, ViewVisibility, scope_key_for

    if datasets_dir is None:
        print("[seed-视图] examples/datasets 目录不存在，跳过视图注入")
        return 0

    ws_configs = paths._get_workspace_view_configs(datasets_dir)
    if not ws_configs:
        print("[seed-视图] 未发现任何 views.json，跳过视图注入")
        return 0

    personal_owner_id = personal_owner_user.id if personal_owner_user is not None else user.id

    created = 0
    for ws_name, tables in ws_configs.items():
        ws_tables = tables_map.get(ws_name)
        if not ws_tables:
            print(f"[seed-视图] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        for table_name, view_list in tables.items():
            if table_name.startswith("_"):
                continue  # 跳过 _comment 等元数据键
            dt = ws_tables.get(table_name)
            if dt is None:
                print(f"[seed-视图] 配置中的表 '{ws_name}/{table_name}' 不存在，跳过")
                continue
            valid_fields = {f.name for f in dt.fields}
            for idx, vc in enumerate(view_list):
                try:
                    if not _validate_view_fields(vc, valid_fields, ws_name, table_name):
                        continue

                    # scope 决定归属与可见性档位：
                    #   global   → table 档（继承表权限，表内所有人可见）
                    #   personal → private 档（仅创建者可见）
                    # 显式写好 visibility 时以配置为准（值域同 ADR 0003 §1）
                    scope = vc.get("scope", "global")
                    if scope == "global":
                        owner_id: int | None = None
                        visibility = ViewVisibility.TABLE
                    elif scope == "personal":
                        owner_id = personal_owner_id
                        visibility = ViewVisibility.PRIVATE
                    else:
                        print(
                            f"[seed-视图] 非法 scope={scope!r}（仅接受 global/personal），"
                            f"默认当作 global: {ws_name}/{table_name} / {vc.get('name')}"
                        )
                        owner_id = None
                        visibility = ViewVisibility.TABLE
                    raw_visibility = str(vc.get("visibility") or "")
                    if raw_visibility in tuple(ViewVisibility):
                        visibility = ViewVisibility(raw_visibility)

                    # 默认视图必须为 table 档（让所有成员进入时都看得到）
                    is_default = bool(vc.get("is_default", False)) and visibility == ViewVisibility.TABLE

                    dv_payload = {
                        "table_id": dt.id,
                        "owner_id": owner_id,
                        "visibility": visibility,
                        "scope_key": scope_key_for(visibility, owner_id),
                        "name": vc["name"],
                        "view_type": vc.get("view_type", "grid"),
                        "filter_type": vc.get("filter_type", "AND"),
                        "filters": vc.get("filters", []),
                        "sortings": vc.get("sortings", []),
                        "field_options": vc.get("field_options", {}),
                        "field_order": vc.get("field_order", []),
                        "view_options": vc.get("view_options", {}),
                        "is_default": is_default,
                        "order": vc.get("order", idx),
                    }
                    # 同名视图已存在则用配置更新（自动生成的「全部」默认视图需要被丰富化）
                    # 同名判定按命名空间（scope_key）：私有视图不与表内共享视图抢名
                    existing = (
                        db.query(DataView)
                        .filter(
                            DataView.table_id == dt.id,
                            DataView.scope_key == dv_payload["scope_key"],
                            DataView.name == vc["name"],
                        )
                        .first()
                    )
                    if existing is not None:
                        for key, value in dv_payload.items():
                            setattr(existing, key, value)
                        db.flush()
                        print(
                            f"[seed-视图] 更新已存在: {ws_name}/{table_name} → {dv_payload['name']} ({dv_payload['view_type']})"
                        )
                        continue
                    dv = DataView(**dv_payload)
                    db.add(dv)
                    db.flush()
                    created += 1
                    print(f"[seed-视图] {ws_name}/{table_name} → {dv.name} ({dv.view_type})")
                except Exception as exc:  # 单视图失败不阻断其它
                    db.rollback()
                    print(f"[seed-视图] 跳过: {ws_name}/{table_name} / {vc.get('name', '<无>')}: {exc}")

    db.commit()
    return created


def _seed_demo_personal_views(db: Any, demo_user: Any, tables_map: dict[str, dict[str, Any]]) -> None:
    """为演示用户硬编码追加典型 personal 视图.

    views.json 里的 scope=personal 条目已能覆盖配置化注入，但本函数保证
    「日常待办」表一定同时存在 global + personal 两类视图（即使 views.json
    没有写 personal 条目），让前端演示进入时就能看到两类视图的真实效果。

    规则：幂等，同名（owner 维度）即跳过。
    """
    from cndb.plugins.tables.models import DataView, ViewVisibility

    personal_specs: list[tuple[str, str, dict[str, Any]]] = [
        # (工作区名, 表名, 视图 payload 精简版 —— owner_id 由调用者注入)
        (
            "某企业销售管理",
            "日常待办",
            {
                "name": "我的待办（个人）",
                "view_type": "grid",
                "filter_type": "AND",
                "filters": [
                    {"field_name": "负责人", "op": "=", "value": demo_user.nickname or demo_user.username},
                    {"field_name": "完成日期", "op": "=", "value": ""},
                ],
                "sortings": [{"field_name": "截止日期", "direction": "asc"}],
                "order": 90,
            },
        ),
    ]

    for ws_name, table_name, payload in personal_specs:
        ws_tables = tables_map.get(ws_name)
        if not ws_tables:
            continue
        dt = ws_tables.get(table_name)
        if dt is None:
            continue
        # 幂等：(table_id, owner_id, name) 命中即跳过
        existing = (
            db.query(DataView)
            .filter(
                DataView.table_id == dt.id,
                DataView.owner_id == demo_user.id,
                DataView.name == payload["name"],
            )
            .first()
        )
        if existing is not None:
            print(f"[seed-demo-personal] 已存在，跳过: {ws_name}/{table_name} → {payload['name']}")
            continue
        dv = DataView(
            table_id=dt.id,
            owner_id=demo_user.id,
            visibility=ViewVisibility.PRIVATE,
            scope_key=demo_user.id,
            name=payload["name"],
            view_type=payload.get("view_type", "grid"),
            filter_type=payload.get("filter_type", "AND"),
            filters=payload.get("filters", []),
            sortings=payload.get("sortings", []),
            field_options={},
            field_order=[],
            view_options={},
            is_default=False,
            order=payload.get("order", 0),
        )
        db.add(dv)
        db.flush()
        print(f"[seed-demo-personal] {ws_name}/{table_name} → {dv.name} (owner=demo)")

    db.commit()
