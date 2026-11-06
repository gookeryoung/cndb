"""工作区备份 v13：设计文件身份 / 依赖闭包往返（ADR 0086 D11）."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.workspaces.services.backup_io import _import_backup_into_workspace
from cndb.plugins.workspaces.services.workspace_backup import (
    build_workspace_backup_v9,
)


def _make_workspace(db: Session, name: str = "v13 工作区"):
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    user = User(username=f"v13_{name}", nickname="V13")
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


PART = "param dw = 10\ncyl(d = dw, h = 2)"
ASM = 'use "pin"(dw = 12) as a\nuse "pin"() as b\n'


class TestBackupV13DesignFiles:
    """v13 designs 段文件身份 / 依赖闭包往返（ADR 0086 D11）."""

    def test_designs_roundtrip_with_file_identity(self, db_engine, db) -> None:
        from cndb.plugins.design.models import DesignDesign, DesignDesignref, DesignDesignVersion
        from cndb.plugins.design.services.dsl.compile import compile_design
        from cndb.plugins.design.services.files import build_resolver, content_hash, sync_refs

        ws, user = _make_workspace(db, "v13 设计源")
        part = DesignDesign(
            workspace_id=ws.id,
            title="销",
            kind="part",
            file_key="pin",
            folder="parts",
            content=PART,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
        db.add(part)
        db.flush()
        result = compile_design(PART, file_kind="part", file_id=part.id)
        part.compiled = result.ir
        db.commit()

        asm = DesignDesign(
            workspace_id=ws.id,
            title="装配",
            kind="assembly",
            file_key="assembly",
            content=ASM,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
        db.add(asm)
        db.flush()
        result = compile_design(ASM, file_kind="assembly", file_id=asm.id, resolver=build_resolver(db, ws.id))
        asm.compiled = result.ir
        deps = [
            {
                "file_id": d.file_id,
                "file_key": d.file_key,
                "version_number": d.version_number,
                "content_hash": d.content_hash,
            }
            for d in result.dependencies
        ]
        asm.dependencies = deps
        db.add(
            DesignDesignVersion(
                design_id=asm.id,
                workspace_id=ws.id,
                version_number=1,
                change_type="auto",
                content=ASM,
                compiled=result.ir,
                dependencies=deps,
                created_by_id=user.id,
            )
        )
        sync_refs(db, asm, ["pin"])
        db.commit()

        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)
        design_items = {item["title"]: item for item in backup["designs"]}
        assert design_items["销"]["kind"] == "part"
        assert design_items["销"]["file_key"] == "pin"
        assert design_items["销"]["folder"] == "parts"
        assert design_items["装配"]["dependencies"][0]["file_key"] == "pin"
        assert design_items["装配"]["versions"][0]["dependencies"][0]["content_hash"] == content_hash(PART)
        assert design_items["装配"]["versions"][0]["change_type"] == "auto"

        target_ws, target_user = _make_workspace(db, "v13 设计目标")
        import_result = _import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert import_result.imported_designs == 2
        assert import_result.errors == []

        rows = {
            row.title: row
            for row in db.execute(select(DesignDesign).where(DesignDesign.workspace_id == target_ws.id)).scalars()
        }
        assert rows["销"].kind == "part"
        assert rows["销"].file_key == "pin"
        assert rows["销"].folder == "parts"
        assert rows["装配"].dependencies[0]["file_id"] == rows["销"].id
        refs = db.execute(select(DesignDesignref).where(DesignDesignref.design_id == rows["装配"].id)).scalars().all()
        assert [ref.target_design_id for ref in refs] == [rows["销"].id]
        version = db.execute(
            select(DesignDesignVersion).where(DesignDesignVersion.design_id == rows["装配"].id)
        ).scalar_one()
        assert version.dependencies[0]["version_number"] == 1
        assert version.change_type == "auto"
