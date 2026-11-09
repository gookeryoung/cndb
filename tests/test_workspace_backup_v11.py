"""工作区全量备份 v11（ADR 0079 D9）：设计定义与版本随备份导出导入、旧备份兼容.

覆盖：
- 归档结构：``designs[]`` 携带原文 / 描述 / 软删标记 + 版本原文，``compiled`` 不导出；
- 覆盖恢复往返：设计 + 版本（编号 / 原文 / 备注）还原，IR 由导入端重编译；
- 旧备份兼容：v10（无 ``designs`` 键）导入正常且 ``imported_designs == 0``；
- 导入细节：坏 DSL 跳过并记错误、同名幂等、无版本时补 v1。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
DESIGNS = "/api/v1/workspaces/{wid}/designs"

GOOD_CONTENT = "param w = 80\nbox(size = [w, 40, 12])\n"
V2_CONTENT = "box(size = [10, 10, 10])\n"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_design(client: TestClient, headers: dict[str, str], wid: int) -> dict:
    """建一个两版本的设计（v1 = GOOD_CONTENT，v2 = 简化单盒），返回 v1 详情."""
    r = client.post(
        DESIGNS.format(wid=wid),
        json={"title": "法兰板", "content": GOOD_CONTENT, "description": "试验夹具"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    r = client.put(
        f"{DESIGNS.format(wid=wid)}/{created['id']}/content",
        json={"content": V2_CONTENT, "comment": "简化"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return created


def _export_archive(client: TestClient, headers: dict[str, str], wid: int) -> bytes:
    r = client.get(f"{WS}/{wid}/export/archive", headers=headers)
    assert r.status_code == 200, r.text
    return r.content


class TestArchiveStructure:
    def test_designs_exported_with_versions_no_compiled(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "设计备份结构")
        _seed_design(client, auth_headers, wid)

        raw = _export_archive(client, auth_headers, wid)
        archive_file = tmp_path / "d.tar.gz"
        archive_file.write_bytes(raw)
        from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

        archive = parse_workspace_archive(archive_file)
        try:
            backup = archive.backup
            assert backup["version"] == "16"
            assert archive.manifest["stats"]["designs"] == 1
            designs = backup["designs"]
            assert len(designs) == 1
            item = designs[0]
            assert item["title"] == "法兰板"
            assert item["description"] == "试验夹具"
            assert item["is_deleted"] is False
            assert item["content"] == V2_CONTENT, "本体原文为最新版"
            assert "compiled" not in item, "compiled 快照不导出（导入端重编译）"
            assert [v["version_number"] for v in item["versions"]] == [1, 2]
            assert item["versions"][0]["content"] == GOOD_CONTENT
            assert item["versions"][1]["comment"] == "简化"
            assert all("compiled" not in v for v in item["versions"])
        finally:
            archive.cleanup()

    def test_soft_deleted_design_exported(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "设计软删备份")
        created = _seed_design(client, auth_headers, wid)
        r = client.delete(f"{DESIGNS.format(wid=wid)}/{created['id']}", headers=auth_headers)
        assert r.status_code == 204, r.text

        raw = _export_archive(client, auth_headers, wid)
        archive_file = tmp_path / "s.tar.gz"
        archive_file.write_bytes(raw)
        from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

        archive = parse_workspace_archive(archive_file)
        try:
            assert archive.backup["designs"][0]["is_deleted"] is True
        finally:
            archive.cleanup()


class TestRestoreRoundtrip:
    def test_full_roundtrip_restores_design_and_versions(self, client, auth_headers, db, tmp_path: Path):
        from cndb.plugins.design.models import DesignDesign, DesignDesignVersion

        wid = _new_workspace(client, auth_headers, "设计往返源")
        _seed_design(client, auth_headers, wid)
        raw = _export_archive(client, auth_headers, wid)

        # 覆盖恢复到同一工作区（clear + import）
        r = client.post(
            f"{WS}/{wid}/restore",
            files={"file": ("backup.tar.gz", io.BytesIO(raw), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported_designs"] == 1
        assert body["errors"] == [], body["errors"]

        design = db.query(DesignDesign).filter(DesignDesign.workspace_id == wid).one()
        assert design.title == "法兰板"
        assert design.description == "试验夹具"
        assert design.content == V2_CONTENT
        assert design.compiled["nodes"] == [{"op": "box", "size": [10, 10, 10]}], "IR 由导入端重编译产出"
        versions = (
            db.query(DesignDesignVersion)
            .filter(DesignDesignVersion.design_id == design.id)
            .order_by(DesignDesignVersion.version_number)
            .all()
        )
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[0].content == GOOD_CONTENT
        assert versions[1].comment == "简化"
        assert all(v.compiled.get("nodes") for v in versions), "版本 IR 同样重编译"

        # 恢复后的设计可直接经 API 读写（路由层仍按工作区权限放行）
        r = client.get(f"{DESIGNS.format(wid=wid)}/{design.id}/versions", headers=auth_headers)
        assert r.status_code == 200
        assert [i["version_number"] for i in r.json()] == [2, 1]

    def test_restore_clears_existing_designs_first(self, client, auth_headers, db):
        from cndb.plugins.design.models import DesignDesign

        wid = _new_workspace(client, auth_headers, "设计清空恢复")
        _seed_design(client, auth_headers, wid)
        raw = _export_archive(client, auth_headers, wid)
        # 导出后再建一个只存在于当前库的设计，恢复后应消失（覆盖恢复 = 清空 + 重建）
        r = client.post(
            DESIGNS.format(wid=wid),
            json={"title": "将被清空", "content": "box(size = [1, 1, 1])"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text

        r = client.post(
            f"{WS}/{wid}/restore",
            files={"file": ("backup.tar.gz", io.BytesIO(raw), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        titles = {d.title for d in db.query(DesignDesign).filter(DesignDesign.workspace_id == wid).all()}
        assert titles == {"法兰板"}, "导出后才创建的设计随覆盖恢复被清空"

    def test_v10_backup_without_designs_imports_ok(self, client, auth_headers, db):
        """旧备份兼容（ADR 0079 D9）：v10 备份无 designs 键，导入不受影响."""
        from cndb.plugins.design.models import DesignDesign

        source = _new_workspace(client, auth_headers, "v10 旧备份源")
        _seed_design(client, auth_headers, source)
        raw = _export_archive(client, auth_headers, source)

        # 构造 v10 旧备份：剥掉 designs 键、版本号回写 10
        import tarfile

        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("backup.json"))
            backup = json.loads(tar.extractfile(member).read().decode())
        backup.pop("designs", None)
        backup["version"] = "10"

        # 导入到全新工作区（导入不清空目标区，正好验证 v10 白名单与 designs 缺省）
        target = _new_workspace(client, auth_headers, "v10 导入目标")
        r = client.post(
            f"{WS}/{target}/import",
            json={"json_data": backup},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported_designs"] == 0
        assert body["errors"] == []
        assert db.query(DesignDesign).filter(DesignDesign.workspace_id == target).count() == 0


class TestDesignImportDetails:
    """v11 设计导入的细节：坏 DSL 跳过、同名幂等、无版本补 v1、非法版本隔离."""

    def test_invalid_dsl_skipped_and_idempotent(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.design.models import DesignDesign
        from cndb.plugins.workspaces.services.backup_io import _import_designs

        wid = _new_workspace(client, auth_headers, "设计导入细节")
        user = db.query(User).first()
        payload = {
            "designs": [
                {"title": "坏设计", "content": "box(size = [1, 2, -3])"},
                "not-a-dict",
                {
                    "title": "法兰板",
                    "content": GOOD_CONTENT,
                    "versions": [{"version_number": 1, "content": GOOD_CONTENT, "comment": ""}],
                },
            ]
        }
        imported, errors = _import_designs(wid, payload, user, db)
        assert imported == 1
        assert len(errors) == 1 and "DSL 非法" in errors[0]
        assert (
            db.query(DesignDesign).filter(DesignDesign.workspace_id == wid, DesignDesign.title == "法兰板").count() == 1
        )

        # 同名再导入：幂等跳过（坏 DSL 仍会重复报错——它每次都编译失败，不属幂等分支）
        again, _ = _import_designs(wid, payload, user, db)
        assert again == 0
        assert (
            db.query(DesignDesign).filter(DesignDesign.workspace_id == wid, DesignDesign.title == "法兰板").count() == 1
        )

    def test_no_versions_falls_back_to_v1(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
        from cndb.plugins.workspaces.services.backup_io import _import_designs

        wid = _new_workspace(client, auth_headers, "设计无版本")
        user = db.query(User).first()
        imported, errors = _import_designs(
            wid,
            {"designs": [{"title": "直连导入", "content": GOOD_CONTENT}]},
            user,
            db,
        )
        assert imported == 1
        assert errors == []
        versions = (
            db.query(DesignDesignVersion)
            .join(DesignDesign, DesignDesign.id == DesignDesignVersion.design_id)
            .filter(DesignDesignVersion.workspace_id == wid)
            .all()
        )
        assert [v.version_number for v in versions] == [1], "无版本备份按当前原文补 v1"

    def test_versions_without_change_type_default_manual(self, client, auth_headers, db):
        """旧备份缺 change_type：按 manual 还原（ADR 0113 C10 / I6）."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
        from cndb.plugins.workspaces.services.backup_io import _import_designs

        wid = _new_workspace(client, auth_headers, "旧备份版本类型")
        user = db.query(User).first()
        imported, errors = _import_designs(
            wid,
            {
                "designs": [
                    {
                        "title": "旧备份设计",
                        "content": GOOD_CONTENT,
                        "versions": [{"version_number": 1, "content": GOOD_CONTENT, "comment": "旧版本"}],
                    }
                ]
            },
            user,
            db,
        )
        assert imported == 1
        assert errors == []
        version = (
            db.query(DesignDesignVersion)
            .join(DesignDesign, DesignDesign.id == DesignDesignVersion.design_id)
            .filter(DesignDesignVersion.workspace_id == wid)
            .one()
        )
        assert version.change_type == "manual"

    def test_bad_version_isolated(self, client, auth_headers, db):
        """某版本 DSL 非法只跳过该版本，不阻断设计本体与其它版本."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.design.models import DesignDesignVersion
        from cndb.plugins.workspaces.services.backup_io import _import_designs

        wid = _new_workspace(client, auth_headers, "设计坏版本")
        user = db.query(User).first()
        imported, errors = _import_designs(
            wid,
            {
                "designs": [
                    {
                        "title": "法兰板",
                        "content": GOOD_CONTENT,
                        "versions": [
                            {"version_number": 1, "content": GOOD_CONTENT, "comment": ""},
                            {"version_number": 2, "content": "box(size = [0, 0, 0])", "comment": "坏版"},
                            {"version_number": 3, "content": V2_CONTENT, "comment": "好版"},
                        ],
                    }
                ]
            },
            user,
            db,
        )
        assert imported == 1
        assert len(errors) == 1 and "v2 版本跳过" in errors[0]
        numbers = [
            v.version_number
            for v in db.query(DesignDesignVersion)
            .filter(DesignDesignVersion.workspace_id == wid)
            .order_by(DesignDesignVersion.version_number)
            .all()
        ]
        assert numbers == [1, 3]

    def test_empty_payload(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.services.backup_io import _import_designs

        wid = _new_workspace(client, auth_headers, "设计空载荷")
        user = db.query(User).first()
        assert _import_designs(wid, {}, user, db) == (0, [])
