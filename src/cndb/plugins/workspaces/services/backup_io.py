"""工作区整体导入的服务层实现.

- ``_coerce_row_value_types``：按反射列类型归一备份 JSON 中的字符串值
- ``_import_backup_into_workspace``：把备份载荷落库为新工作区（表 / 字段 / 行 / 视图）

从 routers/workspaces.py 抽出（后者 270 行、与 HTTP 层无关，供两个导入端点复用）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.schemas import WorkspaceImportResponse

logger = logging.getLogger(__name__)

# ── 工作区整体导入导出 ──────────────────────────────


def _coerce_row_value_types(sa_table: Any, row_values: list[dict[str, Any]]) -> None:
    """按反射列类型归一备份 JSON 中的字符串值（就地修改）.

    备份 JSON 导出时 date/datetime 被序列化为 ISO 字符串，而 SQLAlchemy 的
    Date/DateTime 列不接受字符串输入（SQLite 下抛 TypeError 导致整表行
    导入失败），插入前需反序列化还原。
    """
    import datetime

    from sqlalchemy import Date, DateTime

    date_cols = {name: col for name, col in sa_table.columns.items() if isinstance(col.type, (Date, DateTime))}
    if not date_cols:
        return
    for values in row_values:
        for name, col in date_cols.items():
            v = values.get(name)
            if v is None or not isinstance(v, str):
                continue
            try:
                if isinstance(col.type, DateTime):
                    if "T" not in v and " " not in v:
                        v = f"{v}T00:00:00"
                    values[name] = datetime.datetime.fromisoformat(v)
                else:
                    values[name] = datetime.date.fromisoformat(v[:10])
            except ValueError:
                pass  # 非法格式保留原值，交由数据库报出真实错误


def _import_backup_into_workspace(
    workspace_id: int,
    json_data: dict[str, Any],
    current_user: User,
    db: Session,
) -> WorkspaceImportResponse:
    """把备份 JSON 中的表/行/视图导入到指定工作区（内部 helper，不做权限校验）."""
    import logging

    from cndb.plugins.tables.models import (
        DataField,
        DataTable,
        DataView,
        RowAction,
        RowPermission,
        RowSubject,
        TablePermission,
        ViewVisibility,
        ensure_default_view,
        scope_key_for,
    )
    from cndb.plugins.tables.services.core.ddl import create_table as ddl_create

    # 版本校验：缺失视为旧版 v1 文件；未知版本拒绝，避免静默错读新格式
    version = json_data.get("version", "1")
    if version not in ("1", "2", "3", "4", "5", "6"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的导出文件版本: {version}（当前支持: 1, 2, 3, 4, 5, 6）。请升级程序后再导入。",
        )

    imported_tables = 0
    imported_rows = 0
    imported_views = 0
    imported_documents = 0
    imported_sync_jobs = 0
    errors: list[str] = []

    # v4 跨表引用重映射的收集器（v1-v3 备份无 id 信息，保持原样跳过重映射）：
    # - table_id_map / field_id_map：备份内旧表/字段 id → 新工作区的表/字段 id
    # - pending_field_refs：含跨表 id 的字段（link/lookup），待全部表创建后统一重写 config
    # - row_id_maps：表 id → {行索引 → 新物理行 id}，用于回填 link 关联行
    # - pending_link_rows：待回填的 link 关联行 (字段, 所属表, 行索引对)
    table_id_map: dict[int, int] = {}
    field_id_map: dict[int, int] = {}
    pending_field_refs: list[tuple[DataField, dict[str, Any]]] = []
    row_id_maps: dict[int, dict[int, int]] = {}
    pending_link_rows: list[tuple[DataField, DataTable, list[list[int]]]] = []

    # 循环前先提交任何待处理事务，确保连接以干净状态进入逐表循环。
    # 原因：SQLite 的隐式事务（由 flush() 开启）会持有 RESERVED 锁，
    # 阻止任何连接（包括 engine 新创建的）执行需要 EXCLUSIVE 锁的 DDL。
    # 参考：tables.py 正常建表流程也是先 commit 再 ddl_create。
    if db.in_transaction():
        db.commit()

    try:
        for tbl_data in json_data.get("tables", []):
            table_name = tbl_data.get("name", "").strip()
            if not table_name:
                continue
            # 同名表跳过
            existing = (
                db.query(DataTable)
                .filter(
                    DataTable.workspace_id == workspace_id,
                    DataTable.name == table_name,
                    DataTable.trashed_at.is_(None),
                )
                .first()
            )
            if existing:
                continue

            table = DataTable(
                workspace_id=workspace_id,
                owner_id=current_user.id,
                name=table_name,
                description=tbl_data.get("description", ""),
            )
            table.ensure_db_name()
            db.add(table)
            db.flush()
            # v4：备份内旧表 id → 新表 id（同名跳过的表不进映射，引用它的字段保持原 config）
            old_table_id = tbl_data.get("id")
            if isinstance(old_table_id, int):
                table_id_map[old_table_id] = table.id

            # 创建 DataField
            fields_data = tbl_data.get("fields", [])
            fields_order = []
            for fd in fields_data:
                field = DataField(
                    table_id=table.id,
                    name=fd.get("name", ""),
                    field_type=fd.get("field_type", "text"),
                    config=fd.get("config", {}) or {},
                    required=fd.get("required", False),
                    is_unique=fd.get("is_unique", False),
                    default_value=fd.get("default_value"),
                    hidden=fd.get("hidden", False),
                    order=fd.get("order", 0),
                )
                field.ensure_db_name()
                db.add(field)
                fields_order.append(field)
                if fd.get("field_type") in ("link", "lookup"):
                    pending_field_refs.append((field, fd))

            db.flush()
            # v4：flush 拿到字段 id 后记录 旧字段 id → 新字段 id；跨表字段延后统一重写 config
            for fd, field in zip(fields_data, fields_order, strict=False):
                old_field_id = fd.get("id")
                if isinstance(old_field_id, int):
                    field_id_map[old_field_id] = field.id

            # ★ 关键：在执行 DDL 前先提交 flush 出的 DataTable / DataField 元数据。
            # SQLite flush() 隐式开启的事务会持有 RESERVED 锁，
            # 必须释放才能让 DDL 获取 EXCLUSIVE 锁（CREATE TABLE 需要）。
            # —— 逐表 commit 而非循环外统一 commit，使导入具备部分成功能力：
            # 单表失败不影响已成功表；整体失败时上层（create_workspace_from_backup）
            # 会回滚整个工作区级联清理。
            db.commit()

            # DDL 创建物理表（create_table 自动从 table.fields 拿字段）
            try:
                ddl_create(db.get_bind(), table)
            except Exception as exc:
                db.rollback()
                raise HTTPException(status_code=400, detail=f"创建表 {table_name} 失败: {exc}") from exc

            # 自动生成默认视图「全部」（若导入的 views 里已存在同名则跳过，
            # 避免与 uniq_table_view_name 约束冲突）
            views_data = tbl_data.get("views", [])
            if not any(vd.get("name") == "全部" for vd in views_data):
                ensure_default_view(db, table, owner_id=current_user.id, commit=False)

            # 插入数据行（用 raw INSERT 避免依赖 transfer.py 的复杂逻辑）
            rows_data = tbl_data.get("rows", [])
            if rows_data and not fields_order:
                msg = f"表 {table_name} 无字段定义，{len(rows_data)} 行数据无法导入，已跳过"
                errors.append(msg)
                logging.getLogger(__name__).warning("%s", msg)
            elif rows_data and fields_order:
                try:
                    from sqlalchemy import MetaData, insert, select
                    from sqlalchemy import Table as SATable

                    metadata = MetaData()
                    sa_table = SATable(table.db_table_name, metadata, autoload_with=db.bind)
                    row_values = []
                    row_orig_idx: list[int] = []
                    for idx, raw in enumerate(rows_data):
                        values = {}
                        for f in fields_order:
                            # link 等字段无主表物理列（值存关联表），跳过避免整表 INSERT 失败
                            if f.db_column_name not in sa_table.columns:
                                continue
                            # v3+ 行键为业务字段名；回退物理列名以兼容旧版 v1/v2 备份
                            if f.name in raw:
                                values[f.db_column_name] = raw[f.name]
                            elif f.db_column_name in raw:
                                values[f.db_column_name] = raw[f.db_column_name]
                        if values:
                            row_values.append(values)
                            row_orig_idx.append(idx)
                    if row_values:
                        _coerce_row_value_types(sa_table, row_values)
                        db.execute(insert(sa_table), row_values)
                        imported_rows += len(row_values)
                        # v4：记录 行索引 → 新物理行 id（自增 id 单调递增，按 id 排序即插入序），
                        # 供 link 关联行回填定位
                        if isinstance(old_table_id, int):
                            new_ids = [r[0] for r in db.execute(select(sa_table.c.id).order_by(sa_table.c.id)).all()]
                            row_id_maps[table.id] = dict(zip(row_orig_idx, new_ids, strict=False))
                    if len(row_values) < len(rows_data):
                        # 行键无法匹配（如旧版备份的随机物理列名）时不许静默丢数据
                        dropped = len(rows_data) - len(row_values)
                        msg = (
                            f"表 {table_name} 有 {dropped}/{len(rows_data)} 行数据"
                            "无法匹配到字段（旧版备份的物理列名不可映射），已跳过"
                        )
                        errors.append(msg)
                        logging.getLogger(__name__).warning("%s", msg)
                except Exception as exc:
                    msg = f"表 {table_name} 数据行导入失败，已跳过 {len(rows_data)} 行: {exc}"
                    errors.append(msg)
                    logging.getLogger(__name__).warning("%s", msg)

            # 创建视图（is_default 兼容 v1 旧键名 default）
            for vd in views_data:
                imported_owner_id = vd.get("owner_id")
                raw_scope = vd.get("scope_key")
                if str(vd.get("visibility") or "") in tuple(ViewVisibility):
                    # 新版备份：**原样还原**档位与命名空间，保证导出 / 导入往返无损
                    # （含 D3 孤儿视图这类"私有档 + 无 owner"的退化态，不做修正）
                    imported_visibility = ViewVisibility(str(vd["visibility"]))
                    imported_scope_key = (
                        int(raw_scope)
                        if raw_scope is not None
                        else scope_key_for(imported_visibility, imported_owner_id)
                    )
                else:
                    # 旧版备份无 visibility 键：按旧二元语义推断 —— 无 owner = 表内公开视图。
                    # 不可默认成 private：owner_id 为空会变成"孤儿私有视图"（对所有人不可见，ADR 0003 §7-2）
                    imported_visibility = ViewVisibility.TABLE if imported_owner_id is None else ViewVisibility.PRIVATE
                    imported_scope_key = scope_key_for(imported_visibility, imported_owner_id)
                view = DataView(
                    table_id=table.id,
                    owner_id=imported_owner_id,
                    name=vd.get("name", ""),
                    view_type=vd.get("view_type", "grid"),
                    filter_type=vd.get("filter_type", "AND"),
                    filters=vd.get("filters", []) or [],
                    sortings=vd.get("sortings", []) or [],
                    field_options=vd.get("field_options", {}) or {},
                    view_options=vd.get("view_options", {}) or {},
                    field_order=vd.get("field_order"),
                    is_default=bool(vd.get("is_default", vd.get("default", False)))
                    and imported_visibility == ViewVisibility.TABLE,
                    visibility=imported_visibility,
                    scope_key=imported_scope_key,
                )
                db.add(view)
                imported_views += 1

            # v4：收集 link 关联行（行索引对），待全部表建完后统一回填
            for ld in tbl_data.get("links", []):
                pairs = ld.get("pairs", [])
                link_field = next((f for f in fields_order if f.name == ld.get("field")), None)
                if link_field and link_field.field_type == "link" and pairs:
                    pending_link_rows.append((link_field, table, pairs))

            # 表级权限配置还原（hidden_fields/row_filters 按字段名表达，字段名已随表保真）
            perm_data = tbl_data.get("permission")
            if isinstance(perm_data, dict):
                db.add(
                    TablePermission(
                        table_id=table.id,
                        read_role=perm_data.get("read_role", "") or "",
                        edit_records_role=perm_data.get("edit_records_role", "") or "",
                        edit_views_role=perm_data.get("edit_views_role", "") or "",
                        edit_schema_role=perm_data.get("edit_schema_role", "") or "",
                        manage_data_role=perm_data.get("manage_data_role", "") or "",
                        hidden_fields=perm_data.get("hidden_fields", {}) or {},
                        row_filters=perm_data.get("row_filters", []) or [],
                        row_filter_type=perm_data.get("row_filter_type", "AND") or "AND",
                    )
                )

            # 行级权限规则还原（ADR 0004 §7-9）：旧版备份无该键 → 按「无规则」还原；
            # subject_id 为 user id 字符串或 read/write 常量，原样保留（孤儿规则自动失效，§7-10）
            for rd in tbl_data.get("row_permissions", []) or []:
                if not isinstance(rd, dict):
                    continue
                subject_type = str(rd.get("subject_type") or "")
                action = str(rd.get("action") or "")
                if subject_type not in tuple(RowSubject) or action not in tuple(RowAction):
                    continue
                db.add(
                    RowPermission(
                        table_id=table.id,
                        subject_type=subject_type,
                        subject_id=str(rd.get("subject_id") or ""),
                        action=action,
                        filters=rd.get("filters", []) or [],
                        filter_type=rd.get("filter_type", "AND") or "AND",
                        granted_by_id=current_user.id,
                    )
                )

            # 每个表的视图/行数据独立提交，避免再次持锁影响后续 DDL
            db.commit()
            imported_tables += 1

        # ── v4 第二阶段：跨表引用重映射 + link 关联行回填 ──
        for field, fd in pending_field_refs:
            cfg = dict(field.config or {})
            changed = False
            if fd.get("field_type") == "link":
                old = cfg.get("target_table_id")
                if isinstance(old, int) and old in table_id_map:
                    cfg["target_table_id"] = table_id_map[old]
                    changed = True
            else:  # lookup: source_table_id / source_field_id / via_link_field_id
                for key in ("source_table_id", "source_field_id", "via_link_field_id"):
                    old = cfg.get(key)
                    mapping = table_id_map if key == "source_table_id" else field_id_map
                    if isinstance(old, int) and old in mapping:
                        cfg[key] = mapping[old]
                        changed = True
                # 恢复后按重映射到的源字段回填缓存类型（旧备份无该键，或源类型已变）
                new_src_id = cfg.get("source_field_id")
                new_src = db.get(DataField, new_src_id) if isinstance(new_src_id, int) else None
                if new_src is not None and cfg.get("source_field_type") != new_src.field_type:
                    cfg["source_field_type"] = new_src.field_type
                    changed = True
            if changed:
                field.config = cfg
                db.add(field)
        if pending_field_refs:
            db.commit()

        for link_field, table, pairs in pending_link_rows:
            try:
                # config 已在上一阶段重映射，target_table_id 即新工作区表 id
                target_table_id = (link_field.config or {}).get("target_table_id")
                row_map = row_id_maps.get(table.id, {})
                target_map = row_id_maps.get(target_table_id) if isinstance(target_table_id, int) else None
                target_map = target_map or {}
                link_values = [
                    {"row_id": row_map[ri], "target_row_id": target_map[ti]}
                    for ri, ti in pairs
                    if ri in row_map and ti in target_map
                ]
                if not link_values:
                    continue
                from sqlalchemy import MetaData
                from sqlalchemy import Table as SATable
                from sqlalchemy import insert as sa_insert

                lt = SATable(link_field.link_table_name, MetaData(), autoload_with=db.bind)
                db.execute(sa_insert(lt), link_values)
                db.commit()
            except Exception as exc:
                db.rollback()
                msg = f"表 {table.name} 字段 {link_field.name} 的关联数据回填失败: {exc}"
                errors.append(msg)
                logging.getLogger(__name__).warning("%s", msg)

        # ── 文档标签 + 文档树还原（仅最新正文，不含历史版本） ──
        doc_imported, doc_errors = _import_documents(workspace_id, json_data, current_user, db)
        imported_documents += doc_imported
        errors.extend(doc_errors)

        # ── v5：外部数据同步任务（旧备份无该键时按空处理） ──
        job_imported, job_errors = _import_sync_jobs(workspace_id, json_data, current_user, db)
        imported_sync_jobs += job_imported
        errors.extend(job_errors)

        # ── v6：工作区级大模型连接（旧备份无该键时跳过；api_key 永不导入） ──
        _import_llm_config(workspace_id, json_data, current_user, db)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}") from exc

    return WorkspaceImportResponse(
        imported_tables=imported_tables,
        imported_rows=imported_rows,
        imported_views=imported_views,
        imported_documents=imported_documents,
        imported_sync_jobs=imported_sync_jobs,
        errors=errors,
    )


def _import_documents(
    workspace_id: int,
    json_data: dict[str, Any],
    current_user: User,
    db: Session,
) -> tuple[int, list[str]]:
    """还原备份中的文档标签与文档树（仅最新正文），返回 (成功文档数, 错误明细).

    - 标签按 ``(workspace_id, name)`` 幂等创建，备份内旧标签 id 映射到新 id；
    - 文档经 ``create_document`` 落库：自动生成 slug、解析元数据、按分级存储策略
      存正文并同步 FTS；
    - 父子层级分两遍还原：先建全部节点（``parent_id=None``），再按
      ``旧 parent_id → 新文档 id`` 回填，避免"子先于父"的排序问题。
    """
    from cndb.plugins.documents.models import Document, Tag
    from cndb.plugins.documents.services.content import create_document

    errors: list[str] = []

    # 1) 标签：按名称幂等，记录 旧标签 id → 新标签 id
    tag_id_map: dict[int, int] = {}
    tag_pairs: list[tuple[int, Tag]] = []
    for td in json_data.get("document_tags", []) or []:
        name = (td.get("name") or "").strip()
        if not name:
            continue
        tag = db.query(Tag).filter(Tag.workspace_id == workspace_id, Tag.name == name).first()
        if tag is None:
            tag = Tag(
                workspace_id=workspace_id,
                name=name,
                color=td.get("color") or "#1890FF",
                description=td.get("description", "") or "",
            )
            db.add(tag)
        old_tag_id = td.get("id")
        if isinstance(old_tag_id, int):
            tag_pairs.append((old_tag_id, tag))
    db.flush()
    for old_tag_id, tag in tag_pairs:
        tag_id_map[old_tag_id] = tag.id

    # 2) 文档：第一遍建节点（暂不挂父节点）
    docs_data = json_data.get("documents", []) or []
    doc_id_map: dict[int, int] = {}
    imported = 0
    for dd in docs_data:
        title = (dd.get("title") or "").strip()
        try:
            mapped_tags = [tag_id_map[t] for t in (dd.get("tag_ids") or []) if t in tag_id_map]
            doc = create_document(
                db,
                workspace_id,
                current_user,
                title=title,
                content="" if dd.get("is_folder") else (dd.get("content") or ""),
                is_folder=bool(dd.get("is_folder", False)),
                parent_id=None,
                status=dd.get("status") or "draft",
                tag_ids=mapped_tags or None,
                sort_order=int(dd.get("sort_order") or 0),
            )
            old_doc_id = dd.get("id")
            if isinstance(old_doc_id, int):
                doc_id_map[old_doc_id] = doc.id
            imported += 1
        except Exception as exc:
            db.rollback()
            msg = f"文档 {title or '(无标题)'} 导入失败: {exc}"
            errors.append(msg)
            logging.getLogger(__name__).warning("%s", msg)

    # 3) 文档：第二遍还原父子层级（父子均成功导入时才建立链接）
    changed = False
    for dd in docs_data:
        old_doc_id = dd.get("id")
        old_parent_id = dd.get("parent_id")
        if not isinstance(old_doc_id, int) or old_doc_id not in doc_id_map or old_parent_id is None:
            continue
        new_doc_id = doc_id_map[old_doc_id]
        new_parent_id = doc_id_map.get(old_parent_id)
        if new_parent_id is None or new_parent_id == new_doc_id:
            continue
        doc = db.get(Document, new_doc_id)
        if doc is not None and doc.parent_id != new_parent_id:
            doc.parent_id = new_parent_id
            db.add(doc)
            changed = True
    if changed:
        db.commit()

    return imported, errors


def _import_sync_jobs(
    workspace_id: int,
    json_data: dict[str, Any],
    current_user: User,
    db: Session,
) -> tuple[int, list[str]]:
    """还原外部数据同步任务（v5 起），返回 (成功数, 错误明细).

    - 同名任务已存在则跳过（与表/文档的幂等口径一致）；
    - 备份里的 ``table_name`` 按同名表映射为新表 id，找不到则任务不绑定表；
    - 游标 / 调度配置在导入时校验，非法配置跳过并记错误（不阻断整体导入）。
    """
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
    from cndb.plugins.datasource.services.cursor import CursorConfig
    from cndb.plugins.datasource.services.schedule import ScheduleConfig
    from cndb.plugins.tables.models import DataTable

    items = json_data.get("sync_jobs") or []
    if not items:
        return 0, []

    errors: list[str] = []
    table_ids = {
        row[0]: row[1]
        for row in db.query(DataTable.name, DataTable.id)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed_at.is_(None))
        .all()
    }
    session_ids = {
        row[0]: row[1]
        for row in db.query(DatasourceSession.name, DatasourceSession.id)
        .filter(DatasourceSession.workspace_id == workspace_id)
        .all()
    }
    imported = 0
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        exists = (
            db.query(DatasourceSyncJob)
            .filter(DatasourceSyncJob.workspace_id == workspace_id, DatasourceSyncJob.name == name)
            .first()
        )
        if exists is not None:
            continue
        try:
            CursorConfig.from_dict(item.get("cursor"))
            ScheduleConfig.from_dict(item.get("schedule"))
        except Exception as exc:
            errors.append(f"同步任务 {name} 跳过（配置非法）: {exc}")
            continue
        table_name = item.get("table_name")
        job = DatasourceSyncJob(
            workspace_id=workspace_id,
            created_by=current_user.id,
            name=name,
            provider=item.get("provider") or "http_json",
            table_id=table_ids.get(table_name) if table_name else None,
            request_spec=item.get("request_spec") or {},
            parser=item.get("parser") or "json",
            entrant_param=item.get("entrant_param"),
            entrant_keys=item.get("entrant_keys") or [],
            match_keys=item.get("match_keys") or [],
            field_mapping=item.get("field_mapping") or {},
            cursor=item.get("cursor") or {},
            schedule=item.get("schedule") or {},
            enabled=bool(item.get("enabled", True)),
            # 会话按同名绑定（密钥不导出）；找不到同名会话时解绑，任务仍可运行（可能缺鉴权）
            session_id=session_ids.get(item.get("session_name") or ""),
            rate_limit_ms=int(item.get("rate_limit_ms") or 0),
        )
        db.add(job)
        imported += 1
    if imported:
        db.commit()
    return imported, errors


def _import_llm_config(
    workspace_id: int,
    json_data: dict[str, Any],
    current_user: User,
    db: Session,
) -> bool:
    """还原工作区级大模型连接（v6 起），返回是否新建.

    - 旧备份无 ``llm_config`` 键时跳过；
    - 备份不含 API Key（绝不导出密文），还原后 Key 留空，需用户重新填写；
    - 目标工作区已有连接时保留现有配置（与表 / 任务的幂等口径一致）。
    """
    from cndb.plugins.datasource.models import DatasourceLlmConfig
    from cndb.plugins.datasource.services.connection import DEFAULT_BASE_URL, DEFAULT_MODEL

    data = json_data.get("llm_config")
    if not isinstance(data, dict):
        return False
    existing = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == workspace_id).first()
    if existing is not None:
        return False
    config = DatasourceLlmConfig(
        workspace_id=workspace_id,
        created_by=current_user.id,
        base_url=str(data.get("base_url") or "").strip() or DEFAULT_BASE_URL,
        model=str(data.get("model") or "").strip() or DEFAULT_MODEL,
        api_key="",
        system_prompt=str(data.get("system_prompt") or "").strip(),
    )
    db.add(config)
    db.commit()
    return True


__all__ = [
    "_coerce_row_value_types",
    "_import_backup_into_workspace",
    "_import_llm_config",
    "_import_sync_jobs",
]
