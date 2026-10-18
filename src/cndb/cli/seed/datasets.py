"""datasets 目录扫描 → 工作区 / CSV / XLSX / API 数据表。

每个子文件夹建一个工作区，逐类数据源建表并汇总 `工作区名 → 表名 → DataTable` 映射。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.seed import fields, paths


def _seed_xlsx_table(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    xlsx_path: Path,
    owner_id: int | None = None,
) -> tuple[Any, list[int]]:
    """从 xlsx 文件建表导入 —— 带降级重试，保证原始值无损入表.

    两步策略：
    1. 正常自动推断类型（create_table_from_file）—— 干净文件走这条快速路径.
    2. 失败兜底 —— openpyxl 直接读原始行，预处理表头（跳过说明行、
       裁尾部空列、None 自动命名），所有单元格值转 str，
       create_table_from_json_data 建成全 text 类型表，原始值无损入表.
       后续由数据治理的 coerce_type / fill_null 等动作做类型修正.

    Returns:
        (DataTable | None, 新行 id 列表) — 彻底失败返回 (None, []).
    """
    from cndb.plugins.tables.services.transfer.table_create import (
        create_table_from_file,
    )

    filename = xlsx_path.name
    xlsx_bytes = xlsx_path.read_bytes()

    # ── 策略 1：正常自动推断 ──
    try:
        dt, ids, _cols = create_table_from_file(
            engine,
            db,
            workspace_id,
            table_name,
            xlsx_bytes,
            format="xlsx",
            filename=filename,
            owner_id=owner_id,
        )
        print(f"[seed-XLSX] 建表: {table_name} → (id={dt.id})")
        return dt, ids
    except Exception as exc:
        # 策略 1 失败属预期回退，但需留痕：兜底也失败时可追溯根因
        print(f"[seed-XLSX] {table_name} 常规推断失败，转 text 兜底: {exc}")

    # ── 策略 2：openpyxl 预处理 + 全 text 兜底 ──
    try:
        from openpyxl import load_workbook

        wb = load_workbook(str(xlsx_path))
        ws = wb.active
        if ws is None:
            print(f"[seed-XLSX] 建表失败: {table_name} (无可读工作表)")
            return None, []
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            print(f"[seed-XLSX] 建表失败: {table_name} (空文件)")
            return None, []

        # 跳过开头说明行 —— 真正表头应是"存在非 None 且非空白单元格"的首行
        header_idx = 0
        for i, row in enumerate(all_rows):
            if row and any(c is not None and str(c).strip() for c in row):
                header_idx = i
                break
        header_row = all_rows[header_idx]

        # 生成合法表头名（None / 空串 → 自动命名，重名 → 后缀去重）
        header_names: list[str] = []
        seen: dict[str, int] = {}
        for idx, cell in enumerate(header_row):
            raw = str(cell).strip() if cell is not None else ""
            if not raw:
                raw = f"列{idx + 1}"
            base = raw
            if raw in seen:
                seen[raw] += 1
                raw = f"{base}_{seen[raw]}"
            else:
                seen[raw] = 0
            header_names.append(raw)

        # 裁掉尾部全 None 空列
        valid_count = len(header_names)
        for j in range(len(header_names) - 1, -1, -1):
            col_all_none = all(row[j] is None for row in all_rows[header_idx + 1 :]) if j < len(header_names) else True
            if col_all_none:
                valid_count -= 1
            else:
                break
        header_names = header_names[: max(valid_count, 1)]

        # 组装 rows dict（所有值 str → create_table_from_json_data 推断为 text）
        rows: list[dict[str, str]] = []
        for row in all_rows[header_idx + 1 :]:
            if not any(c is not None for c in row):
                continue
            rec: dict[str, str] = {}
            for i, name in enumerate(header_names):
                v = row[i] if i < len(row) else None
                rec[name] = str(v) if v is not None else ""
            rows.append(rec)

        if not rows:
            print(f"[seed-XLSX] 建表失败: {table_name} (无有效数据行)")
            return None, []

        # 手动建表（全部 text 字段），彻底绕开类型推断/校验
        from cndb.plugins.tables.models import DataField, DataTable, ensure_default_view
        from cndb.plugins.tables.services.core import ddl
        from cndb.plugins.tables.services.core import records as _rec

        dt = DataTable(workspace_id=workspace_id, owner_id=owner_id, name=table_name)
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        for idx, fname in enumerate(header_names):
            f = DataField(table_id=dt.id, name=fname, field_type="text", order=idx)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)
        ensure_default_view(db, dt, owner_id=owner_id, commit=True)
        ids = _rec.bulk_create(engine, dt, rows, db=db)
        print(f"[seed-XLSX] 建表(全text降级): {table_name} → (id={dt.id})")
        return dt, ids
    except Exception as exc:
        print(f"[seed-XLSX] 建表失败(兜底): {table_name}: {exc}")
        return None, []


def _seed_datasets(db: Any, engine: Any, user: Any) -> tuple[int, dict[str, Any], dict[str, dict[str, Any]]]:
    """扫描 datasets 目录，按子文件夹建工作区、按 CSV 建表导入 + 按 api_config.json 建表.

    Returns:
        (成功创建的数据表总数, 工作区名 -> Workspace 对象映射, 工作区名 -> 表名 -> DataTable 映射)
    """
    from cndb.plugins.tables.services.importing.api_config_loader import (
        ApiConfigError,
        build_fetch_config,
        load_api_config_file,
    )
    from cndb.plugins.tables.services.transfer import create_table_from_csv, ingest_from_api
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    datasets_dir = paths._get_datasets_dir()
    if datasets_dir is None:
        print("[seed] examples/datasets 目录不存在，跳过 CSV 注入（wheel 安装版无此目录属正常）")
        return 0, {}, {}

    table_count = 0
    ws_map: dict[str, Any] = {}
    tables_map: dict[str, dict[str, Any]] = {}

    # "某企业销售管理"（硬编码业务表宿主）固定最先创建 → 稳定占据 ws id=1，
    # 供 e2e 等场景对工作区 id 做稳定假设；其余工作区保持名称排序。
    def _sales_first(p: Path) -> tuple[bool, str]:
        """排序键：某企业销售管理优先，其余按文件夹名升序."""
        return (p.name != "工作区-某企业销售管理", p.name)

    folders = sorted(datasets_dir.iterdir(), key=_sales_first)
    for folder in folders:
        if not folder.is_dir() or folder.name.startswith("."):
            continue

        # 工作区名去掉 "工作区-" 前缀让显示更友好
        ws_display = paths._workspace_display_name(folder.name)

        ws = Workspace(name=ws_display, description=f"示例数据：{ws_display}")
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
        ws_map[ws_display] = ws
        tables_map[ws_display] = {}
        print(f"[seed] 创建工作区: {ws_display} (id={ws.id})")

        # ── CSV 建表 ──
        csv_files = sorted(folder.glob("*.csv"))
        for csv_path in csv_files:
            table_name = csv_path.stem
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            try:
                dt, _ids = create_table_from_csv(engine, db, ws.id, table_name, csv_text, owner_id=user.id)
                table_count += 1
                tables_map[ws_display][table_name] = dt
                print(f"[seed-CSV] 建表: {ws_display}/{table_name} → (id={dt.id})")
            except Exception as exc:  # 单表失败不应阻断其它表
                print(f"[seed-CSV] 建表失败: {ws_display}/{table_name}: {exc}")

        # ── XLSX 建表（数据治理/质量样例多以 xlsx 组织） ──
        # 跳过"示例报告"类 xlsx：这类文件是报表导出样例（如电商销售月报-示例报告.xlsx），
        # 不是数据表，导入后会污染表列表并破坏 e2e 对表数量的稳定假设。

        xlsx_files = sorted(folder.glob("*.xlsx"))
        for xlsx_path in xlsx_files:
            if "示例报告" in xlsx_path.stem:
                print(f"[seed-XLSX] 跳过示例报告文件: {xlsx_path.name}")
                continue
            table_name = xlsx_path.stem
            dt, _ids = _seed_xlsx_table(engine, db, ws.id, table_name, xlsx_path, owner_id=user.id)
            if dt is not None:
                table_count += 1
                tables_map[ws_display][table_name] = dt

        # ── API 配置建表 ──
        api_config_path = folder / "api_config.json"
        if api_config_path.is_file():
            try:
                table_defs = load_api_config_file(api_config_path)
            except ApiConfigError as exc:
                print(f"[seed-API] 配置文件解析失败 {api_config_path.name}: {exc}")
                continue

            for table_def in table_defs:
                tbl_name = table_def["table_name"]
                fetch_cfg = build_fetch_config(table_def)
                try:
                    dt, ids, _columns = ingest_from_api(
                        engine,
                        db,
                        ws.id,
                        tbl_name,
                        api_url=fetch_cfg.url,
                        method=fetch_cfg.method,
                        headers=fetch_cfg.headers,
                        params=fetch_cfg.params,
                        body=fetch_cfg.body,
                        data_path=fetch_cfg.data_path,
                        timeout=fetch_cfg.timeout,
                        response_handler=fetch_cfg.response_handler,
                        encoding=fetch_cfg.encoding,
                        query_interval=fetch_cfg.query_interval,
                        owner_id=user.id,
                    )
                    table_count += 1
                    tables_map[ws_display][tbl_name] = dt
                    print(
                        f"[seed-API] 建表: {ws_display}/{tbl_name} "
                        f"(handler={fetch_cfg.response_handler}, "
                        f"interval={fetch_cfg.query_interval:.0f}s, "
                        f"{len(ids)} 行, id={dt.id})"
                    )
                except Exception as exc:
                    print(f"[seed-API] 建表失败: {ws_display}/{tbl_name}: {exc}")

        # ── 跨表字段引入（表已就绪后执行，避免源表不存在） ──
        fields._apply_field_import_rules(db, engine, ws_display, tables_map)

    return table_count, ws_map, tables_map
