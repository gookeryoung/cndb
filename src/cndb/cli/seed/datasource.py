"""数据源同步任务种子：各工作区 `datasource.json`。

把声明式同步任务（Provider 引用 + 标的集合 + 幂等键 + 字段映射 + 游标 / 调度）
注入 ``datasource_sync_job``，让「多标的同源 → 同一张表」的典型链路随
`cndb seed` 开箱可用。只注入配置（``enabled`` 由配置决定），不触发联网抓取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import paths


def _validate_job_fields(jc: dict[str, Any], valid_fields: set[str], ws_name: str, table_name: str) -> bool:
    """校验任务的幂等键与字段映射目标列是否存在于目标表.

    Returns:
        True 表示通过，False 表示校验失败并已打印告警.
    """
    job_name = jc.get("name", "")
    for key in jc.get("match_keys") or []:
        if key not in valid_fields:
            print(f"[seed-数据源] 跳过: {ws_name}/{table_name} 任务'{job_name}' 的 match_keys='{key}' 不存在")
            return False
    mapping = jc.get("field_mapping") or {}
    for src, target in mapping.items():
        if target is None:
            continue  # 显式丢弃源字段
        target_name = target.get("name") if isinstance(target, dict) else None
        if target_name and target_name not in valid_fields:
            print(
                f"[seed-数据源] 跳过: {ws_name}/{table_name} 任务'{job_name}' 的字段映射 {src}→'{target_name}' 不存在"
            )
            return False
    return True


def _seed_datasource(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    tables_map: dict[str, dict[str, Any]],
    datasets_dir: Path | None,
) -> int:
    """按各工作区文件夹下的 datasource.json 注入同步任务.

    配置结构（工作区显示名 → ``{"jobs": [job, ...]}``）：每个 job 的 ``table`` 为
    目标表名（解析为真实 ``table_id``）；解析失败或字段引用不存在则打印告警并跳过。
    幂等：同一 ``(workspace_id, name)`` 已有任务则跳过，不重复建。
    """
    from cndb.plugins.datasource.models import DatasourceSyncJob

    if datasets_dir is None:
        print("[seed-数据源] examples/datasets 目录不存在，跳过数据源注入")
        return 0

    ws_configs = paths._get_workspace_datasource_configs(datasets_dir)
    if not ws_configs:
        print("[seed-数据源] 未发现任何 datasource.json，跳过数据源注入")
        return 0

    created = 0
    for ws_name, cfg in ws_configs.items():
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-数据源] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        ws_tables = tables_map.get(ws_name) or {}
        for jc in cfg.get("jobs") or []:
            if not isinstance(jc, dict) or not jc.get("name"):
                continue
            job_name = jc["name"]
            table_name = jc.get("table")
            if not table_name:
                print(f"[seed-数据源] 任务'{job_name}' 未声明目标表 table，跳过")
                continue
            dt = ws_tables.get(table_name)
            if dt is None:
                print(f"[seed-数据源] 配置中的表 '{ws_name}/{table_name}' 不存在，跳过")
                continue
            valid_fields = {f.name for f in dt.fields}
            if not _validate_job_fields(jc, valid_fields, ws_name, table_name):
                continue
            existing = (
                db.query(DatasourceSyncJob)
                .filter(DatasourceSyncJob.workspace_id == ws.id, DatasourceSyncJob.name == job_name)
                .first()
            )
            if existing is not None:
                print(f"[seed-数据源] 已存在，跳过: {ws_name}/{table_name} → {job_name}")
                continue
            job = DatasourceSyncJob(
                workspace_id=ws.id,
                created_by=user.id,
                name=job_name,
                provider=jc.get("provider", "http_json"),
                table_id=dt.id,
                request_spec=jc.get("request_spec", {}),
                parser=jc.get("parser", "json"),
                entrant_param=jc.get("entrant_param"),
                entrant_keys=jc.get("entrant_keys", []),
                match_keys=jc.get("match_keys", []),
                field_mapping=jc.get("field_mapping", {}),
                rate_limit_ms=jc.get("rate_limit_ms", 0),
                cursor=jc.get("cursor", {}),
                schedule=jc.get("schedule", {}),
                enabled=jc.get("enabled", True),
            )
            db.add(job)
            db.flush()
            created += 1
            print(f"[seed-数据源] {ws_name}/{table_name} → {job_name} ({job.provider}, {len(job.entrant_keys)} 标的)")

    db.commit()
    return created


__all__ = ["_seed_datasource"]
