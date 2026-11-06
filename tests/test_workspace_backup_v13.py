"""工作区备份 v13：设计文件身份 / 依赖闭包往返（ADR 0086 D11）/ 流水线版本（ADR 0114）."""

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


PIPELINE_OLD = "name: 文档巡检\njobs:\n  文档:\n    steps:\n      - uses: document/links\n"
PIPELINE_NEW = "name: 文档巡检\njobs:\n  文档:\n    steps:\n      - uses: document/broken-refs\n"


class TestBackupPipelineVersions:
    """v13 pipelines 段版本历史往返与旧备份兼容（ADR 0114 C11）."""

    def _seed(self, db: Session, ws, user):
        from cndb.plugins.pipeline.models import PipelineWorkflow, PipelineWorkflowVersion

        workflow = PipelineWorkflow(
            workspace_id=ws.id,
            name="文档巡检",
            content=PIPELINE_NEW,
            compiled={},
            enabled=True,
            created_by_id=user.id,
        )
        db.add(workflow)
        db.flush()
        db.add_all(
            [
                PipelineWorkflowVersion(
                    workspace_id=ws.id,
                    workflow_id=workflow.id,
                    version_number=1,
                    change_type="manual",
                    content=PIPELINE_OLD,
                    comment="",
                    created_by_id=user.id,
                ),
                PipelineWorkflowVersion(
                    workspace_id=ws.id,
                    workflow_id=workflow.id,
                    version_number=2,
                    change_type="rollback",
                    content=PIPELINE_NEW,
                    comment="恢复自 v1",
                    created_by_id=user.id,
                ),
            ]
        )
        db.commit()
        return workflow

    def test_pipeline_versions_roundtrip(self, db_engine, db) -> None:
        from cndb.plugins.pipeline.models import PipelineWorkflow, PipelineWorkflowVersion

        ws, user = _make_workspace(db, "v13 流水线源")
        self._seed(db, ws, user)

        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)
        item = backup["pipelines"][0]
        assert [v["version_number"] for v in item["versions"]] == [1, 2]
        assert item["versions"][1]["change_type"] == "rollback"
        assert item["versions"][1]["comment"] == "恢复自 v1"

        target_ws, target_user = _make_workspace(db, "v13 流水线目标")
        result = _import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert result.errors == []
        assert result.imported_pipelines == 1

        workflow = db.execute(
            select(PipelineWorkflow).where(PipelineWorkflow.workspace_id == target_ws.id)
        ).scalar_one()
        versions = (
            db.execute(
                select(PipelineWorkflowVersion)
                .where(PipelineWorkflowVersion.workflow_id == workflow.id)
                .order_by(PipelineWorkflowVersion.version_number)
            )
            .scalars()
            .all()
        )
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[0].content == PIPELINE_OLD
        assert versions[1].change_type == "rollback"
        assert versions[1].comment == "恢复自 v1"
        assert versions[0].workspace_id == target_ws.id

    def test_old_backup_without_versions_imports_current_only(self, db_engine, db) -> None:
        from cndb.plugins.pipeline.models import PipelineWorkflow, PipelineWorkflowVersion

        ws, user = _make_workspace(db, "v13 旧备份源")
        self._seed(db, ws, user)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)
        for item in backup["pipelines"]:
            item.pop("versions", None)

        target_ws, target_user = _make_workspace(db, "v13 旧备份目标")
        result = _import_backup_into_workspace(target_ws.id, backup, target_user, db)
        assert result.errors == []
        assert result.imported_pipelines == 1

        workflow = db.execute(
            select(PipelineWorkflow).where(PipelineWorkflow.workspace_id == target_ws.id)
        ).scalar_one()
        assert workflow.content == PIPELINE_NEW
        assert (
            db.execute(select(PipelineWorkflowVersion).where(PipelineWorkflowVersion.workflow_id == workflow.id))
            .scalars()
            .all()
            == []
        )
