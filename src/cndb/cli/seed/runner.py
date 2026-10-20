"""seed 命令编排入口。

按序注入：账号 → datasets 工作区/数据表 → 业务表 → 字段设置 → 视图 → 文档 → 报告模板 → 示例报告。"""

from __future__ import annotations

import argparse

from cndb.cli.seed import (
    analytics,
    datasets,
    datasource,
    documents,
    fields,
    paths,
    sqlite,
    templates,
    views,
)


def seed(_args: argparse.Namespace) -> None:
    """向数据库注入演示数据（datasets CSV + 硬编码业务表 + 视图种子 + 三员演示账号）."""
    from cndb.core.database import SessionLocal, engine
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User, UserRole

    # 触发所有插件 register_models，确保 Base.metadata 完整注册
    plugin_registry.discover_and_load()

    seed_pragma_handler = sqlite._set_seed_sqlite_pragmas(engine)
    if engine.dialect.name == "sqlite":
        # SQLite 全量清库（含 metadata 外的残留表/孤儿表），避免
        # drop_all 在外键级联下因悬空外键报 no such table（见函数 docstring）
        sqlite._drop_all_tables_sqlite(engine)
    else:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # 补写 alembic_version（seed 自行建表绕过了迁移），避免 serve 启动时
    # ensure_db_migrated 误判为"半迁移库"而重放建表迁移报 table already exists
    from cndb.core.migrations import stamp_head

    stamp_head()
    # 全量重建已删掉 documents_fts 虚拟表，重置进程内建表缓存，
    # 避免长驻进程（同进程重复 seed）后续写文档命中已消失的 FTS 表
    from cndb.plugins.documents.services.search import reset_fts_schema_cache

    reset_fts_schema_cache()
    db = SessionLocal()
    try:
        # 用户 —— 三员账号（GB/T 22239 等级保护模型）+ 1 个普通用户示例
        # 系统管理员（同时是超级管理员，用于首次安装时的初始管理员）
        admin = User(
            username="admin",
            email="admin@example.com",
            nickname="系统管理员",
            role=UserRole.SYSTEM_ADMIN.value,
            is_superuser=True,
        )
        admin.set_password("admin1234")
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print("[seed] 创建用户: admin / admin1234  (角色: 系统管理员 + 超级管理员)")

        # 安全管理员
        sec_admin = User(
            username="sec_admin",
            email="sec_admin@example.com",
            nickname="安全管理员",
            role=UserRole.SECURITY_ADMIN.value,
        )
        sec_admin.set_password("sec1234")
        db.add(sec_admin)
        db.commit()
        db.refresh(sec_admin)
        print("[seed] 创建用户: sec_admin / sec1234  (角色: 安全管理员)")

        # 审计管理员
        audit_admin = User(
            username="audit_admin",
            email="audit_admin@example.com",
            nickname="审计管理员",
            role=UserRole.AUDIT_ADMIN.value,
        )
        audit_admin.set_password("audit1234")
        db.add(audit_admin)
        db.commit()
        db.refresh(audit_admin)
        print("[seed] 创建用户: audit_admin / audit1234  (角色: 审计管理员)")

        # 普通用户（示例）
        demo = User(
            username="demo",
            email="demo@example.com",
            nickname="演示用户",
            role=UserRole.USER.value,
        )
        demo.set_password("demo1234")
        db.add(demo)
        db.commit()
        db.refresh(demo)
        print("[seed] 创建用户: demo / demo1234  (角色: 普通用户)")

        # 用 admin 作为后续数据的所有者（超级管理员最合理）
        owner = admin

        # 1) datasets CSV：每个子文件夹 → 工作区，每个 CSV → 数据表
        csv_count, ws_map, tables_map = datasets._seed_datasets(db, engine, owner)

        # 2) 硬编码业务表挂到 "某企业销售管理" 工作区
        extra = 0
        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            print(f"[seed] 在工作区 '{sales_ws.name}' 下扩展部门/员工业务表")
            extra, extra_tables = templates._seed_sales_tables(db, engine, sales_ws, owner_id=owner.id)
            tables_map.setdefault("某企业销售管理", {}).update(extra_tables)
        else:
            print("[seed] 未找到 '某企业销售管理' 工作区，跳过部门表/员工表注入")

        # 2b) 字段设置种子（依赖所有表已就绪，含硬编码业务表；扫描每个工作区文件夹下的 fields.json）
        datasets_dir = paths._get_datasets_dir()
        fields._apply_field_settings(db, engine, tables_map, datasets_dir)

        # 3) 视图种子（依赖所有表已就绪，扫描每个工作区文件夹下的 views.json）
        #    同时把 demo 用户作为 personal_owner_user，views.json 里声明 scope=personal 的
        #    条目会归属 demo（演示普通用户的个人视图隔离）
        view_count = views._seed_views(db, owner, tables_map, datasets_dir, personal_owner_user=demo)

        # 3c) 文档种子（依赖工作区 + 表 + 视图已就绪：正文可引用真实表/视图 ID；
        #     目录树见 examples/datasets/<工作区>/documents/）
        doc_count, folder_count = documents._seed_documents(db, owner, ws_map, tables_map, datasets_dir)

        # 3b) demo 用户硬编码个人视图：在"某企业销售管理/日常待办"上建 1 个
        #     演示视图"我的待办"，让前端进入时同时看到 global + personal 两类视图
        views._seed_demo_personal_views(db, demo, tables_map)

        # 3d) 分析模板种子（依赖工作区 + 表已就绪：公式引用真实字段名；
        #     analytics.json 见 examples/datasets/<工作区>/）
        analytics_count = analytics._seed_analytics(db, owner, ws_map, tables_map, datasets_dir)

        # 3e) 数据源同步任务种子（依赖工作区 + 表已就绪：字段映射引用真实中文列名；
        #     datasource.json 见 examples/datasets/<工作区>/，只注入配置不触发抓取）
        datasource_count = datasource._seed_datasource(db, owner, ws_map, tables_map, datasets_dir)

        # 5) 为"某企业销售管理"工作区添加其他演示成员，使表权限设置能看到可添加的候选成员
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            extra_members = [
                (sec_admin, WorkspaceRole.EDITOR, "安全管理员"),
                (audit_admin, WorkspaceRole.EDITOR, "审计管理员"),
                (demo, WorkspaceRole.VIEWER, "演示用户"),
            ]
            for u, role, label in extra_members:
                db.add(WorkspaceMember(workspace_id=sales_ws.id, user_id=u.id, role=role))
                print(f"[seed] 添加工作区成员: {label} → {sales_ws.name} ({role.value})")
            db.commit()

        total = csv_count + extra
        print(
            f"[seed] 完成！共 {total} 张数据表、{view_count} 个视图、"
            f"{doc_count} 篇示例文档（{folder_count} 个文档文件夹）、"
            f"{analytics_count} 个分析模板、"
            f"{datasource_count} 个数据源同步任务、"
            f"4 个演示账号（三员 + 普通用户）。"
            "\n登录账号："
            "\n  系统管理员: admin / admin1234"
            "\n  安全管理员: sec_admin / sec1234"
            "\n  审计管理员: audit_admin / audit1234"
            "\n  普通用户:   demo / demo1234"
        )
    finally:
        db.close()
        sqlite._remove_seed_sqlite_pragmas(engine, seed_pragma_handler)
