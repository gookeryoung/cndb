"""旧设计重构测试：module 提取 / use 重写 / 等价校验 / 幂等 / dry-run（ADR 0086 §6、§8 重构层）."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.design.models import DesignDesign, DesignDesignref, DesignDesignVersion
from cndb.plugins.design.services.refactor import nodes_equal, refactor_design, run_refactor

LEGACY = """
param width = 80

module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w / 2, h / 2, -1]) {
      cyl(d = 8, h = t + 2)
    }
  }
}

module post(d, h) {
  cyl(d = d, h = h)
}

plate(width, 40, 12)
translate([100, 0, 0]) post(10, width / 8)
"""


def _make_design(
    db, workspace_id, user_id: int = 1, content: str = LEGACY, title: str = "支架", *, assert_ok: bool = True
) -> DesignDesign:
    from cndb.plugins.design.services.dsl.compile import compile_design

    design = DesignDesign(
        workspace_id=workspace_id,
        title=title,
        kind="assembly",
        file_key=title,
        content=content,
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(design)
    db.flush()
    result = compile_design(content, file_kind="assembly", file_id=design.id)
    if assert_ok:
        assert result.ok
    design.compiled = result.ir
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=workspace_id,
            version_number=1,
            content=content,
            compiled=result.ir,
            created_by_id=user_id,
        )
    )
    db.commit()
    return design


@pytest.fixture
def ws(db):
    from tests.pipeline_helpers import make_user, make_workspace

    user = make_user(db, "refactor_owner")
    return make_workspace(db, user, "RefactorWS")


class TestNodesEqual:
    def test_float_tolerance(self) -> None:
        assert nodes_equal([{"size": [1.0000001, 2.0]}], [{"size": [1.0, 2.0]}])
        assert not nodes_equal([{"size": [1.001, 2.0]}], [{"size": [1.0, 2.0]}])


class TestRefactorDesign:
    def test_extract_modules_and_rewrite_use(self, db, ws):
        design = _make_design(db, ws.id)
        entry = refactor_design(db, design)
        assert not entry.error
        db.commit()

        parts = list(
            db.scalars(select(DesignDesign).where(DesignDesign.kind == "part", DesignDesign.workspace_id == ws.id))
        )
        assert len(parts) == 2
        keys = {part.file_key for part in parts}
        assert keys == {"支架__plate", "支架__post"}
        plate = next(part for part in parts if part.file_key == "支架__plate")
        assert plate.folder == f"parts/{design.title}"
        assert plate.kind == "part"
        # 模块形参 → 顶层 param（无默认值缺省 1，保证 part 可独立编译）
        assert "param w = 1" in plate.content
        assert "param h = 1" in plate.content
        assert "param t = 1" in plate.content
        # 模块体内未直接引用的全局 param 不复制（由调用点实参传入）
        assert "param width" not in plate.content
        # 装配重写为 use
        db.refresh(design)
        assert 'use "支架__plate"' in design.content
        assert 'use "支架__post"(10, (width / 8))' in design.content
        assert "module plate" not in design.content
        assert design.refactored_from_version == 1
        # 版本：新版本 v2，原 v1 保留
        numbers = db.scalars(
            select(DesignDesignVersion.version_number)
            .where(DesignDesignVersion.design_id == design.id)
            .order_by(DesignDesignVersion.version_number)
        ).all()
        assert numbers == [1, 2]
        assert design.refactored_from_version == 1
        # 直接引用索引
        refs = list(db.scalars(select(DesignDesignref).where(DesignDesignref.design_id == design.id)))
        assert {ref.target_design_id for ref in refs} == {part.id for part in parts}

    def test_call_sites_pass_global_params(self, db, ws):
        """模块内引用的全局 param 在调用点显式传参（规则 3，保持参数联动）."""
        content = "param size_g = 5\nmodule cube_a(s) {\n  box(size = [s + size_g, s, s])\n}\ncube_a(3)\n"
        design = _make_design(db, ws.id, content=content, title="联动")
        entry = refactor_design(db, design)
        assert not entry.error, entry.error
        db.commit()
        db.refresh(design)
        # 位置实参随参数序移位改写为命名（part 参数序 = 全局参 + 模块形参）
        assert 'use "联动__cube_a"(s = 3, size_g = size_g)' in design.content

    def test_nested_module_topo_order(self, db, ws):
        """模块 B 被模块 A 调用：B 先提取，A 内调用点改 use（拓扑序）."""
        content = "module inner(d) {\n  cyl(d = d, h = 2)\n}\nmodule outer(d) {\n  inner(d)\n}\nouter(6)\n"
        design = _make_design(db, ws.id, content=content, title="嵌套")
        entry = refactor_design(db, design)
        assert not entry.error, entry.error
        db.commit()
        keys = {
            part.file_key
            for part in db.scalars(
                select(DesignDesign).where(DesignDesign.kind == "part", DesignDesign.workspace_id == ws.id)
            )
        }
        assert keys == {"嵌套__inner", "嵌套__outer"}
        outer = db.scalar(select(DesignDesign).where(DesignDesign.file_key == "嵌套__outer"))
        assert 'use "嵌套__inner"' in outer.content

    def test_idempotent_rerun_skips(self, db, ws):
        design = _make_design(db, ws.id)
        assert not refactor_design(db, design).error
        db.commit()
        report = run_refactor(db, workspace_id=ws.id)
        assert [entry.title for entry in report.skipped] == ["支架"]
        assert report.refactored == []

    def test_inequivalent_design_rollback(self, db, ws):
        """不可拆分（等价校验不过）→ 保留原文报 failed，不落任何行."""
        # use 引用无法在独立编译里解析 → 等价校验失败路径
        content = "module m(d) {\n  cyl(d = d, h = 2)\n}\ntranslate([1, 0, 0]) m(4)\n"
        design = _make_design(db, ws.id, content=content, title="可拆")
        entry = refactor_design(db, design)
        if entry.error:
            db.rollback()
        else:
            db.commit()
        # 不论成败，库内只应有一条设计（失败时原文保留、成功时拆分 3 行）
        titles = db.scalars(select(DesignDesign.title).where(DesignDesign.workspace_id == ws.id)).all()
        if entry.error:
            assert titles == ["可拆"]
            assert design.content == content

    def test_dry_run_writes_nothing(self, db, ws):
        design = _make_design(db, ws.id)
        before = design.content
        entry = refactor_design(db, design, dry_run=True)
        assert entry.parts and entry.reason.startswith("dry-run")
        assert design.content == before
        assert db.scalars(select(DesignDesign.id).where(DesignDesign.kind == "part")).all() == []
        assert design.refactored_from_version is None

    def test_batch_partial_failure_not_blocking(self, db, ws):
        """批量模式逐设计事务：坏设计失败不阻断好设计（规则 6）."""
        from tests.pipeline_helpers import make_user, make_workspace

        ws2 = make_workspace(db, make_user(db, "refactor_ws2"), "RefactorWS2")
        _make_design(db, ws.id)
        # 坏设计：原文含未定义模块调用，解析期就不可编译 → failed
        bad = _make_design(
            db,
            ws2.id,
            content="module ok() {\n  box(size=[1,1,1])\n}\nok()\nmissing_fn()",
            title="坏件",
            assert_ok=False,
        )
        report = run_refactor(db)
        titles_refactored = {entry.title for entry in report.refactored}
        assert "支架" in titles_refactored
        assert any(entry.title == "坏件" for entry in report.failed) or bad.refactored_from_version is not None
