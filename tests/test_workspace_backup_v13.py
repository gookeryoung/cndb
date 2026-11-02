"""工作区备份 v13（ADR 0085 P2）：采集策略随备份搬迁（落点按名字 / 路径重建）."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import AcquisitionRun, AcquisitionStrategy
from cndb.plugins.documents.models import Document
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.services.backup_io import _import_backup_into_workspace
from cndb.plugins.workspaces.services.workspace_backup import (
    build_workspace_backup_v8,
    build_workspace_backup_v9,
    downsample_v8,
)
from tests.test_acquisition_iteration import _make_job, _make_table, _make_workspace, _table_strategy


def _source_workspace(db: Session, engine) -> tuple[object, object, DataTable, Document]:
    ws, user = _make_workspace(db, "v13 源")
    table = _make_table(db, engine, ws.id)
    job = _make_job(db, ws.id, table.id)
    folder = Document(workspace_id=ws.id, title="资料", is_folder=True, created_by_id=user.id)
    db.add(folder)
    db.commit()
    db.refresh(folder)

    strategy = _table_strategy(
        db,
        workspace_id=ws.id,
        table_id=table.id,
        job_id=job.id,
        iteration={"max_rounds": 2, "budget": {"max_requests": 20}},
        user_id=user.id,
    )
    strategy.targets = [
        {"kind": "table", "table_id": table.id, "match_keys": ["city", "day"]},
        {"kind": "document", "parent_id": folder.id, "tags": ["采集"]},
    ]
    strategy.schedule = {"mode": "daily", "at": "08:00"}
    strategy.enabled = True
    strategy.rule_version = 3
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return ws, user, strategy, folder


class TestBackupV13Acquisitions:
    def test_export_replaces_ids_with_names(self, db_engine, db) -> None:
        ws, user, strategy, folder = _source_workspace(db, db_engine)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)

        assert backup["version"] == "13"
        assert len(backup["acquisitions"]) == 1
        item = backup["acquisitions"][0]
        assert item["name"] == strategy.name
        assert item["rule_version"] == 3
        assert item["schedule"] == {"mode": "daily", "at": "08:00"}
        table_target, doc_target = item["targets"]
        assert table_target["table_name"] == "采集表" + str(ws.id)
        assert "table_id" not in table_target
        assert table_target["match_keys"] == ["city", "day"]
        assert doc_target["parent_path"] == [folder.title]
        assert "parent_id" not in doc_target
        # 运行类数据不进备份
        assert "runs" not in item
        assert db.execute(select(AcquisitionRun)).first() is None

    def test_v8_downsample_strips_acquisitions(self, db_engine, db) -> None:
        ws, user, _strategy, _folder = _source_workspace(db, db_engine)
        backup_v8 = build_workspace_backup_v8(db, ws.id, user)

        assert backup_v8["version"] == "8"
        assert "acquisitions" not in backup_v8
        assert "acquisitions" not in downsample_v8(backup_v8)

    def test_import_remaps_targets_by_name_and_path(self, db_engine, db) -> None:
        ws, user, _strategy, _folder = _source_workspace(db, db_engine)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)

        target_ws, target_user = _make_workspace(db, "v13 目标")
        # 目标工作区先建同名表 + 同名文件夹（模拟从零重建后的匹配）
        table = DataTable(workspace_id=target_ws.id, name="采集表" + str(ws.id))
        table.ensure_db_name()
        db.add(table)
        db.commit()
        db.refresh(table)
        ddl.create_table(db_engine, table)
        folder = Document(workspace_id=target_ws.id, title="资料", is_folder=True, created_by_id=target_user.id)
        db.add(folder)
        db.commit()
        db.refresh(folder)

        result = _import_backup_into_workspace(target_ws.id, backup, target_user, db)

        assert result.imported_acquisitions == 1
        assert result.errors == []
        restored = db.execute(
            select(AcquisitionStrategy).where(AcquisitionStrategy.workspace_id == target_ws.id)
        ).scalar_one()
        assert restored.name == _strategy.name
        assert restored.rule_version == 3
        assert restored.schedule == {"mode": "daily", "at": "08:00"}
        assert restored.enabled is True
        table_target, doc_target = restored.targets
        assert table_target["table_id"] == table.id
        assert doc_target["parent_id"] == folder.id

    def test_import_reports_missing_table_and_skips_when_no_target(self, db_engine, db) -> None:
        ws, user, _strategy, _folder = _source_workspace(db, db_engine)
        backup, _files = build_workspace_backup_v9(db, ws.id, user, include_secrets=False)
        # 只留表落点，且名字在目标工作区不存在（备份被手工改过）→ 丢弃落点后无可用落点 → 跳过
        table_target = dict(backup["acquisitions"][0]["targets"][0])
        table_target["table_name"] = "不存在的表"
        backup["acquisitions"][0]["targets"] = [table_target]

        target_ws, target_user = _make_workspace(db, "v13 缺表")
        result = _import_backup_into_workspace(target_ws.id, backup, target_user, db)

        assert result.imported_acquisitions == 0
        assert any("未找到同名表" in message for message in result.errors)
        assert any("没有可用落点" in message for message in result.errors)


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
