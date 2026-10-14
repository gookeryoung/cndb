"""字段设置与字段引入规则种子。

读取各工作区 `fields.json`：必填/唯一约束、link/lookup 关联引入与存量数据回填。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, select

from cndb.cli.seed import paths

# ── 字段引入规则 ──────────────────────────────────────

# 同工作区字段克隆规则：(目标表, 源表, 要引入的字段名列表)。
# 提为模块级常量供测试与 views.json 完整性校验复用，保持单一真相源。
FIELD_IMPORT_RULES: dict[str, list[tuple[str, str, list[str]]]] = {
    # 项目进展表 / 科研经费表 都需要从 科研项目 表知道项目状态和立项年份
    "科研项目管理": [
        ("项目进展", "科研项目", ["项目状态", "立项年份"]),
        ("科研经费", "科研项目", ["项目状态", "项目类别"]),
        ("课题负责人", "科研项目", ["项目状态"]),
    ],
}


def _apply_field_import_rules(db: Any, engine: Any, ws_name: str, tables_map: dict[str, dict[str, Any]]) -> None:
    """按预定义规则在同一工作区内把源表字段克隆到目标表.

    设计意图：
    - CSV 建表天然是"先建主体表再建关联子表"，子表往往需要知道主表的某个状态/标签字段；
    - 这里用 field_ops.clone_fields_between_tables 把字段 schema 从主表克隆到子表，
      让子表可以独立存储（不依赖 link 字段和 lookup 计算）；
    - 失败不阻断其它规则执行（单条规则失败只打印）。
    """
    from cndb.plugins.tables.services.fields import field_ops as _fo

    ws_rules = FIELD_IMPORT_RULES.get(ws_name)
    if not ws_rules:
        return

    ws_tables = tables_map.get(ws_name, {})
    for dst_name, src_name, field_names in ws_rules:
        dst = ws_tables.get(dst_name)
        src = ws_tables.get(src_name)
        if dst is None or src is None:
            print(f"[seed-字段引入] {ws_name}: 表缺失（{src_name}->{dst_name}），跳过")
            continue
        try:
            created, skipped = _fo.clone_fields_between_tables(
                engine, db, src, dst, field_names=field_names, skip_conflicts=True
            )
            if created or skipped:
                print(f"[seed-字段引入] {ws_name}: {src_name} → {dst_name} (成功 {len(created)}, 跳过 {len(skipped)})")
        except Exception as exc:
            print(f"[seed-字段引入] {ws_name}: {src_name} → {dst_name} 失败: {exc}")


def _load_field_settings(datasets_dir: Path | None) -> dict[str, dict[str, Any]]:
    """读取每个工作区文件夹下的 fields.json 字段设置种子配置.

    配置结构（均可缺省，解析失败仅告警跳过）::

        {
          "settings": {"表名": {"字段名": {"required": true, "unique": true}}},
          "link_lookups": [
            {"table": "目标表", "source_table": "源表", "fields": ["源字段名"],
             "link_name": "关联课题", "multiple": false,
             "match": {"local": "本地匹配列", "source": "源表匹配列"}}
          ],
          "backfills": [
            {"table": "目标表", "source_table": "源表", "fields": ["源字段名"],
             "match": {"local": "本地匹配列", "source": "源表匹配列"}}
          ]
        }

    - link_lookups.match：声明后按匹配列把源表行回填为 link 关联数据
      （仅建 link/lookup 字段结构时行关联为空，lookup 列显示为空）；
    - backfills：把源表字段值按匹配列写入目标表同名物理列
      （用于 _apply_field_import_rules 克隆的字段结构补数据）。

    Returns:
        工作区显示名 -> fields.json 解析结果的映射.
    """
    result: dict[str, dict[str, Any]] = {}
    if datasets_dir is None or not datasets_dir.is_dir():
        return result
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        fields_path = folder / "fields.json"
        if not fields_path.is_file():
            continue
        ws_display = paths._workspace_display_name(folder.name)
        try:
            cfg = json.loads(fields_path.read_text(encoding="utf-8-sig"))
            if not isinstance(cfg, dict):
                raise ValueError("顶层必须是对象")
            result[ws_display] = cfg
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            print(f"[seed-字段设置] {folder.name}/fields.json 解析失败: {exc}")
    return result


def _backfill_rows_by_match(
    engine: Any,
    db: Any,
    dst_table: Any,
    src_table: Any,
    match_local: str,
    match_source: str,
    value_fields: Sequence[str] = (),
    link_field: Any = None,
) -> int:
    """按匹配列把源表行的关联/字段值回填到目标表.

    数据集 CSV 天然带外键文本列（如"课题编号"），但 link 字段与克隆物理列
    建立时只建结构不落数据，导致 lookup/克隆列在界面上显示为空。本函数按
    "目标表本地匹配列 == 源表匹配列"（字符串去空格比较）把两边行对上：

    - link_field 不为 None 时：写关联表（set_links，multiple=False 场景单目标）；
    - value_fields 中的物理列：UPDATE 目标表对应列（要求目标表已存在同名
      字段且字段有物理列，lookup/link 等虚拟字段自动跳过）。

    幂等：关联为替换语义、列值为重复覆写，重复执行结果一致。

    Args:
        engine: SQLAlchemy 引擎（读写物理表与关联表）.
        db: ORM 会话（校验 link 目标行存在）.
        dst_table: 目标 DataTable.
        src_table: 源 DataTable.
        match_local: 目标表匹配列名（如"课题编号"）.
        match_source: 源表匹配列名（如"课题编号"）.
        value_fields: 需要回填到目标表物理列的源表字段名列表.
        link_field: 目标表的 link 字段（提供时回填行关联）.

    Returns:
        成功回填的行数（匹配不到的行不计入）.
    """
    from cndb.plugins.tables.services.core.links import set_links

    dst_fields = {f.name: f for f in dst_table.active_fields()}
    src_fields = {f.name: f for f in src_table.active_fields()}
    if match_local not in dst_fields or match_source not in src_fields:
        print(f"[seed-回填] {dst_table.name}: 匹配列缺失（local={match_local!r}/source={match_source!r}），跳过")
        return 0

    # 源表值字段仅保留有物理列的（lookup/link 等虚拟字段无法回填）
    src_value_fields = [
        name for name in value_fields if name in src_fields and src_fields[name].field_type not in ("link", "lookup")
    ]

    def _read_rows(tbl: Any, col_names: list[str]) -> list[dict[str, Any]]:
        sa_tbl = _get_sa_table_by_name(engine, tbl.db_table_name)
        with engine.connect() as conn:
            rows = conn.execute(select(sa_tbl.c.id, *[sa_tbl.c[c] for c in col_names])).all()
        return [dict(r._mapping) for r in rows]

    match_src_col = src_fields[match_source].db_column_name
    src_rows = _read_rows(src_table, [match_src_col, *[src_fields[n].db_column_name for n in src_value_fields]])
    # 匹配值 -> 源行（值规范化为去空格字符串；None/空串不入映射）
    src_by_key: dict[str, dict[str, Any]] = {}
    for r in src_rows:
        key = str(r[match_src_col]).strip() if r[match_src_col] is not None else ""
        if key:
            src_by_key[key] = r

    match_dst_col = dst_fields[match_local].db_column_name
    dst_rows = _read_rows(dst_table, [match_dst_col])
    updated = 0
    for dst_row in dst_rows:
        key = str(dst_row[match_dst_col]).strip() if dst_row[match_dst_col] is not None else ""
        src_row = src_by_key.get(key)
        if src_row is None:
            continue
        if link_field is not None:
            set_links(engine, link_field, int(dst_row["id"]), [int(src_row["id"])], db=db)
        if src_value_fields:
            sa_tbl = _get_sa_table_by_name(engine, dst_table.db_table_name)
            values = {dst_fields[n].db_column_name: src_row[src_fields[n].db_column_name] for n in src_value_fields}
            with engine.begin() as conn:
                conn.execute(sa_tbl.update().where(sa_tbl.c.id == dst_row["id"]).values(**values))
        updated += 1
    return updated


def _get_sa_table_by_name(engine: Any, name: str) -> Any:
    """按物理表名反射 SQLAlchemy Table（供 seed 回填读写行数据）."""
    from sqlalchemy import Table

    return Table(name, MetaData(), autoload_with=engine)


def _apply_field_settings(
    db: Any, engine: Any, tables_map: dict[str, dict[str, Any]], datasets_dir: Path | None
) -> None:
    """按 fields.json 为数据集表补充字段设置示例：必填/唯一约束 + 关联/引用字段.

    - settings：直接改写 DataField.required / is_unique 标志（仅对已存在字段生效）；
    - link_lookups：复用 field_ops.import_fields_as_lookup 建实时关联（link + lookup），
      单行业务表通过 multiple=False 演示单选关联；规则声明 match 时按本地/源匹配列
      回填行关联数据（link 关联表），使 lookup 列可实时解析显示；
    - backfills：按匹配列把源表字段值写入目标表同名物理列，
      为 _apply_field_import_rules 克隆的字段结构补齐行数据；
    - 幂等：重复执行时 settings 重设标志，link 复用、同名 lookup 跳过，
      回填为替换/覆写语义；
    - 单表/单条失败仅打印，不阻断其它工作区。
    """
    from cndb.plugins.tables.services.fields import field_ops as _fo

    ws_configs = _load_field_settings(datasets_dir)
    if not ws_configs:
        return

    for ws_display, cfg in ws_configs.items():
        ws_tables = tables_map.get(ws_display, {})

        # 1) 必填 / 唯一约束设置
        for tbl_name, field_cfgs in (cfg.get("settings") or {}).items():
            tbl = ws_tables.get(tbl_name)
            if tbl is None:
                print(f"[seed-字段设置] {ws_display}: 表 '{tbl_name}' 不存在，跳过设置")
                continue
            field_by_name = {f.name: f for f in tbl.fields if not f.trashed}
            for fname, flags in field_cfgs.items():
                field = field_by_name.get(fname)
                if field is None:
                    print(f"[seed-字段设置] {ws_display}/{tbl_name}: 字段 '{fname}' 不存在，跳过")
                    continue
                if "required" in flags:
                    field.required = bool(flags["required"])
                if "unique" in flags:
                    field.is_unique = bool(flags["unique"])
                db.commit()
            print(f"[seed-字段设置] {ws_display}/{tbl_name}: 应用必填/唯一设置 {len(field_cfgs)} 项")

        # 2) 关联 + 引用示例字段
        for rule in cfg.get("link_lookups") or []:
            dst = ws_tables.get(rule.get("table", ""))
            src = ws_tables.get(rule.get("source_table", ""))
            src_field_names = rule.get("fields") or []
            if dst is None or src is None:
                print(
                    f"[seed-字段设置] {ws_display}: 关联规则表缺失"
                    f"（{rule.get('source_table')} -> {rule.get('table')}），跳过"
                )
                continue
            src_fields = [f for f in src.active_fields() if f.name in src_field_names]
            if not src_fields:
                print(f"[seed-字段设置] {ws_display}: 源字段 {src_field_names} 均不存在，跳过")
                continue
            try:
                created, skipped = _fo.import_fields_as_lookup(
                    engine,
                    db,
                    src,
                    dst,
                    src_fields,
                    link_name=rule.get("link_name"),
                    link_multiple=bool(rule.get("multiple", True)),
                )
                print(
                    f"[seed-字段设置] {ws_display}: {src.name} → {dst.name} 关联引入"
                    f"（新建 {len(created)}, 跳过 {len(skipped)}）"
                )
            except Exception as exc:
                print(f"[seed-字段设置] {ws_display}: {src.name} → {dst.name} 关联引入失败: {exc}")
                continue
            # 2b) match 声明的行关联回填：按本地/源匹配列对上后写 link 关联表
            match = rule.get("match") or {}
            local_name, source_name = match.get("local"), match.get("source")
            if not (local_name and source_name):
                continue
            link_name = rule.get("link_name") or "关联记录"
            link_field = next(
                (f for f in dst.active_fields() if f.field_type == "link" and f.name == link_name),
                None,
            )
            if link_field is None:
                print(f"[seed-回填] {ws_display}/{dst.name}: link 字段 '{link_name}' 不存在，跳过回填")
                continue
            filled = _backfill_rows_by_match(engine, db, dst, src, local_name, source_name, link_field=link_field)
            print(f"[seed-回填] {ws_display}: {src.name} → {dst.name}/{link_name} 行关联 {filled} 行")

        # 3) 物理列数据回填（克隆字段结构补数据）
        for rule in cfg.get("backfills") or []:
            dst = ws_tables.get(rule.get("table", ""))
            src = ws_tables.get(rule.get("source_table", ""))
            match = rule.get("match") or {}
            local_name, source_name = match.get("local"), match.get("source")
            if dst is None or src is None or not (local_name and source_name):
                print(
                    f"[seed-回填] {ws_display}: backfills 规则不完整"
                    f"（{rule.get('source_table')} -> {rule.get('table')}），跳过"
                )
                continue
            filled = _backfill_rows_by_match(
                engine,
                db,
                dst,
                src,
                local_name,
                source_name,
                value_fields=rule.get("fields") or [],
            )
            print(f"[seed-回填] {ws_display}: {src.name} → {dst.name} 字段 {rule.get('fields')} 数据回填 {filled} 行")
