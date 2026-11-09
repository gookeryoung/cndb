"""工作区备份 v14：复用模块已锁定快照（``library_refs[]``）与 vendor 离线恢复（ADR 0118 D9/C9）."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.workspaces.services.backup_io import import_backup_into_workspace
from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v9

PART = "param dw = 10\ncyl(d = dw, h = 2)"
ASM_TEMPLATE = 'use "lib:{module_key}@1"() as wheel\n'


def _make_workspace(db: Session, name: str = "v14 工作区"):
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    user = User(username=f"v14_{name}", nickname="V14")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name=name, created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    db.refresh(user)
    return ws, user


def _seed_source(db: Session, ws, user) -> str:
    """源工作区：零件发布为公开模块 v1 + 装配引用该模块（快照依赖落库），返回 module_key."""
    from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
    from cndb.plugins.design.services.files import (
        compile_design_file,
        direct_library_refs,
        direct_use_keys,
        sync_refs,
    )
    from cndb.plugins.design.services.library import publish_design

    part = DesignDesign(
        workspace_id=ws.id,
        title="轮毂",
        kind="part",
        file_key="wheel",
        content=PART,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(part)
    db.flush()
    db.commit()

    module, _version = publish_design(db, part, user, visibility="public")

    asm_content = ASM_TEMPLATE.format(module_key=module.module_key)
    asm = DesignDesign(
        workspace_id=ws.id,
        title="小车",
        kind="assembly",
        file_key="rover",
        content=asm_content,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(asm)
    db.flush()
    result = compile_design_file(db, asm)
    assert result.ok and result.ir is not None

    def _dep_dicts(deps):
        return [
            {
                "source": d.source,
                "file_key": d.file_key,
                "version_number": d.version_number,
                "content_hash": d.content_hash,
                **(
                    {"module_id": d.module_id, "module_version_id": d.module_version_id, "bundle_hash": d.bundle_hash}
                    if d.source == "library"
                    else {"file_id": d.file_id}
                ),
            }
            for d in deps
        ]

    asm.compiled = result.ir
    asm.dependencies = _dep_dicts(result.dependencies)
    db.add(
        DesignDesignVersion(
            design_id=asm.id,
            workspace_id=ws.id,
            version_number=1,
            change_type="manual",
            content=asm_content,
            compiled=result.ir,
            dependencies=[asdict(d) for d in result.dependencies],
            comment="",
            created_by_id=user.id,
        )
    )
    sync_refs(db, asm, direct_use_keys(asm.content), direct_library_refs(asm.content))
    db.commit()
    return module.module_key


def _vendor_rows(db: Session, workspace_id: int) -> list:
    from cndb.plugins.design.models import DesignLibraryVendor

    return list(
        db.execute(select(DesignLibraryVendor).where(DesignLibraryVendor.workspace_id == workspace_id)).scalars().all()
    )


class TestBackupV14LibraryRefs:
    """v14 ``library_refs[]`` 导出与 vendor 离线恢复（ADR 0118 D9 / §9）."""

    def test_export_includes_locked_snapshot_and_import_writes_vendor(self, db_engine, db) -> None:
        from cndb.plugins.design.models import DesignDesign, DesignLibraryref, DesignLibraryVersion

        ws, user = _make_workspace(db, "v14 导出源")
        module_key = _seed_source(db, ws, user)

        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)
        assert backup["version"] == "15"
        assert len(backup["library_refs"]) == 1
        ref = backup["library_refs"][0]
        assert ref["module_key"] == module_key
        assert ref["version_number"] == 1
        assert ref["content"] == PART
        assert ref["content_hash"] and ref["bundle_hash"]
        assert ref["files"] == []  # 零件无工作区依赖，自包含
        assert isinstance(ref["params"], list)

        # 装配依赖快照带 source=library
        # 个人草稿是临时恢复数据，不进入 designs[]（ADR 0125 D7）
        assert all("draft" not in item for item in backup["designs"])
        design_items = {item["title"]: item for item in backup["designs"]}
        lib_dep = design_items["小车"]["dependencies"][0]
        assert lib_dep["source"] == "library"
        assert lib_dep["file_key"] == module_key

        target_ws, target_user = _make_workspace(db, "v14 导入目标")
        result = import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert result.errors == []
        assert result.imported_designs == 2

        # vendor 行写入且与模块版本同构
        vendors = _vendor_rows(db, target_ws.id)
        assert len(vendors) == 1
        assert vendors[0].module_key == module_key
        assert vendors[0].content_hash == ref["content_hash"]
        assert vendors[0].bundle_hash == ref["bundle_hash"]

        # 导入后按环境模块编译：依赖快照 source=library，design_libraryref 可落
        imported_asm = db.execute(select(DesignDesign).where(DesignDesign.workspace_id == target_ws.id)).scalars().all()
        imported_asm = next(d for d in imported_asm if d.title == "小车")
        assert imported_asm.compiled is not None
        assert imported_asm.dependencies[0]["source"] == "library"
        refs = db.execute(select(DesignLibraryref).where(DesignLibraryref.design_id == imported_asm.id)).scalars().all()
        assert len(refs) == 1
        version = db.get(DesignLibraryVersion, refs[0].module_version_id)
        assert version is not None and version.version_number == 1

    def test_offline_restore_compiles_from_vendor(self, db_engine, db) -> None:
        """跨环境离线：目标环境无该模块版本时按 vendor 快照编译（ADR 0118 I8/C9）."""
        from cndb.plugins.design.models import DesignDesign, DesignLibraryModule

        ws, user = _make_workspace(db, "v14 离线源")
        module_key = _seed_source(db, ws, user)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)

        # 模拟目标环境：模块与版本整体缺失（发布工作区设计也不存在）
        db.query(DesignLibraryModule).filter(DesignLibraryModule.module_key == module_key).delete()
        db.commit()

        target_ws, target_user = _make_workspace(db, "v14 离线目标")
        result = import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert result.errors == []
        assert result.imported_designs == 2

        imported_all = db.execute(select(DesignDesign).where(DesignDesign.workspace_id == target_ws.id)).scalars().all()
        imported_asm = next(d for d in imported_all if d.title == "小车")
        # vendor 快照编译成功：IR 落库、依赖按自然键记录（module_id 为 vendor 占位 0）
        assert imported_asm.compiled is not None
        dep = imported_asm.dependencies[0]
        assert dep["source"] == "library"
        assert dep["file_key"] == module_key
        assert dep["module_id"] == 0
        assert len(_vendor_rows(db, target_ws.id)) == 1

    def test_vendor_upsert_idempotent_and_v13_backup_ignored(self, db_engine, db) -> None:
        from cndb.plugins.design.models import DesignDesign

        ws, user = _make_workspace(db, "v14 幂等源")
        _seed_source(db, ws, user)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)

        target_ws, target_user = _make_workspace(db, "v14 幂等目标")
        first = import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert first.errors == []

        # 旧备份（v13）无 library_refs：不写 vendor、不提供库解析器，
        # 含 lib: 引用的装配按既有「DSL 非法跳过」口径处理（I9：v13 行为不变）
        v13_backup = dict(backup)
        v13_backup["version"] = "13"
        v13_backup["library_refs"] = []
        v13_ws, v13_user = _make_workspace(db, "v14 旧备份目标")
        old_result = import_backup_into_workspace(v13_ws.id, v13_backup, v13_user, db)
        assert old_result.imported_designs == 1  # 仅零件；装配因无库解析器跳过
        assert any("lib" in error for error in old_result.errors)
        assert _vendor_rows(db, v13_ws.id) == []

        # 重复导入：同名设计跳过，vendor 幂等 upsert 不产生重复行
        second = import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert second.imported_designs == 0
        assert second.errors == []
        assert len(_vendor_rows(db, target_ws.id)) == 1
        designs = db.execute(select(DesignDesign).where(DesignDesign.workspace_id == target_ws.id)).scalars().all()
        assert len(designs) == 2

    def test_overwrite_restore_clears_then_rebuilds_vendor(self, db_engine, db) -> None:
        """覆盖恢复先清空 vendor，再按备份 v14 重建（ADR 0118 §9）."""
        from cndb.plugins.workspaces.services.workspace_restore import (
            clear_workspace_content,
            restore_workspace_from_backup,
        )

        ws, user = _make_workspace(db, "v14 恢复源")
        module_key = _seed_source(db, ws, user)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)

        target_ws, target_user = _make_workspace(db, "v14 恢复目标")
        import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert len(_vendor_rows(db, target_ws.id)) == 1

        # 草稿不进备份，但覆盖恢复必须清空（ADR 0125 D7/C8）
        from cndb.plugins.design.models import DesignDesign, DesignDesignDraft

        imported_design = (
            db.execute(select(DesignDesign).where(DesignDesign.workspace_id == target_ws.id)).scalars().first()
        )
        assert imported_design is not None
        db.add(
            DesignDesignDraft(
                design_id=imported_design.id,
                user_id=target_user.id,
                content="box(size = [1, 1, 1])",
                content_hash="draft-hash",
            )
        )
        db.commit()

        clear_workspace_content(target_ws.id, db)
        assert _vendor_rows(db, target_ws.id) == []
        assert db.execute(select(DesignDesignDraft)).scalars().all() == []

        result = restore_workspace_from_backup(target_ws.id, backup, None, target_user, db)
        assert result.errors == []
        vendors = _vendor_rows(db, target_ws.id)
        assert len(vendors) == 1
        assert vendors[0].module_key == module_key
