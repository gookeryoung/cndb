"""分析模板种子：按各工作区文件夹下的 analytics.json 预置分析模板.

analytics.json 结构（表名 -> 模板列表）::

    {
      "产品批次": [
        {
          "name": "批次合格率分布",
          "description": "说明文字",
          "config": {
            "formulas": [{"key": "pass_rate", "label": "合格率(%)", "expr": "round([合格数] / [实际产量] * 100, 2)"}],
            "group_by": null,
            "chart": {"type": "histogram", "x": "pass_rate", "title": "批次合格率分布"},
            "fields": ["批次号", "产品类别", "实际产量", "合格数"],
            "limit": 1000
          }
        }
      ]
    }

写入前校验公式语法与字段引用（复用 analytics 插件的公式引擎），
任何一项不通过则该模板跳过并打印原因。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _validate_template(tpl: dict[str, Any], valid_fields: set[str], ws_name: str, table_name: str) -> bool:
    """校验模板公式与图表引用的字段是否存在.

    Returns:
        True 表示通过，False 表示已打印错误信息并应跳过该模板.
    """
    from cndb.plugins.analytics.services.formula import FormulaError, parse, referenced_fields

    name = tpl.get("name", "")
    config = tpl.get("config") or {}
    keys: set[str] = set()
    for spec in config.get("formulas", []):
        key = spec.get("key", "")
        if not key or key in keys:
            print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 公式键缺失或重复: {key!r}")
            return False
        keys.add(key)
        try:
            node = parse(spec.get("expr", ""))
        except FormulaError as exc:
            print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 公式 {key} 非法: {exc}")
            return False
        unknown = sorted(f for f in referenced_fields(node) if f not in valid_fields)
        if unknown:
            print(
                f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 公式 {key} 引用不存在字段: {', '.join(unknown)}"
            )
            return False

    chart = config.get("chart") or {}
    for opt_key in ("x", "y", "series"):
        opt_val = chart.get(opt_key)
        if opt_val and opt_val not in valid_fields and opt_val not in keys:
            print(
                f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' "
                f"图表 {opt_key}='{opt_val}' 既不是字段也不是公式键"
            )
            return False

    valid_aggs = ("sum", "avg", "count", "min", "max")
    if chart.get("aggregation") not in (None, *valid_aggs):
        print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 图表聚合方式非法: {chart.get('aggregation')!r}")
        return False

    # 分组汇总：分组字段 / 指标来源 / 排序指标均须存在（与模板保存校验同口径）
    summary = config.get("summary") or {}
    group_by = summary.get("group_by")
    if group_by and group_by not in valid_fields:
        print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 分组字段不存在: {group_by!r}")
        return False
    metric_keys: set[str] = set()
    for metric in summary.get("metrics", []):
        field = metric.get("field", "")
        agg = metric.get("agg", "sum")
        if agg not in valid_aggs:
            print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 汇总聚合方式非法: {agg!r}")
            return False
        if field not in valid_fields and field not in keys:
            print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 汇总指标不存在: {field!r}")
            return False
        metric_keys.add(f"{agg}({field})")
    sort_by = summary.get("sort_by")
    if sort_by and sort_by not in metric_keys and sort_by not in valid_fields and sort_by not in keys:
        print(f"[seed-分析] 跳过: {ws_name}/{table_name} 模板'{name}' 汇总排序指标不存在: {sort_by!r}")
        return False
    return True


def _seed_analytics(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    tables_map: dict[str, dict[str, Any]],
    datasets_dir: Path | None,
) -> int:
    """按各工作区文件夹下的 analytics.json 预置分析模板.

    Args:
        ws_map: 工作区显示名 -> Workspace.
        tables_map: 工作区显示名 -> {表名: DataTable}.

    Returns:
        新建模板数量.
    """
    from cndb.plugins.analytics.models import AnalyticsTemplate

    if datasets_dir is None:
        print("[seed-分析] examples/datasets 目录不存在，跳过分析模板注入")
        return 0

    ws_configs = paths._get_workspace_analytics_configs(datasets_dir)
    if not ws_configs:
        print("[seed-分析] 未发现任何 analytics.json，跳过分析模板注入")
        return 0

    created = 0
    for ws_name, tables in ws_configs.items():
        ws = ws_map.get(ws_name)
        ws_tables = tables_map.get(ws_name)
        if ws is None or not ws_tables:
            print(f"[seed-分析] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        for table_name, tpl_list in tables.items():
            if table_name.startswith("_"):
                continue  # 跳过 _comment 等元数据键
            dt = ws_tables.get(table_name)
            if dt is None:
                print(f"[seed-分析] 配置中的表 '{ws_name}/{table_name}' 不存在，跳过")
                continue
            valid_fields = {f.name for f in dt.fields}
            for tpl in tpl_list:
                if not _validate_template(tpl, valid_fields, ws_name, table_name):
                    continue
                config = dict(tpl.get("config") or {})
                # 归一化公式：补 label 默认值，保留窗口上下文（分区 / 排序 / 降序），
                # 避免前端展示空标题或丢失 ma/pct_change 等窗口函数的分区语义
                formulas: list[dict[str, Any]] = []
                for spec in config.get("formulas", []):
                    entry = {"key": spec["key"], "label": spec.get("label") or spec["key"], "expr": spec["expr"]}
                    for extra in ("partition_by", "order_by", "order_desc"):
                        if spec.get(extra):
                            entry[extra] = spec[extra]
                    formulas.append(entry)
                config["formulas"] = formulas
                db.add(
                    AnalyticsTemplate(
                        workspace_id=ws.id,
                        table_id=dt.id,
                        name=tpl.get("name") or f"{table_name} 分析",
                        description=tpl.get("description", ""),
                        config=config,
                        created_by_id=user.id,
                        updated_by_id=user.id,
                    )
                )
                created += 1
    if created:
        db.commit()
    print(f"[seed-分析] 注入 {created} 个分析模板")
    return created
