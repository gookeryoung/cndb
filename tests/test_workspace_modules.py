"""工作区模块判定层单测（ADR 0080 I1/I2/I3）."""

from __future__ import annotations

import pytest

from cndb.plugins.workspaces.modules import (
    MODULE_FEATURES,
    legacy_type_to_modules,
    normalize_modules,
    resolve_features,
    workspace_modules_from_meta,
)

ALL = ["tables", "documents", "design"]


class TestNormalizeModules:
    def test_valid_passthrough_normalized_order(self) -> None:
        assert normalize_modules(["design", "tables", "documents"]) == ALL

    def test_dedupe_and_reorder(self) -> None:
        assert normalize_modules(["design", "tables", "design"]) == ["tables", "design"]

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            normalize_modules([])
        with pytest.raises(ValueError, match="不能为空"):
            normalize_modules("tables")

    def test_unknown_rejected(self) -> None:
        with pytest.raises(ValueError, match="未知模块"):
            normalize_modules(["tables", "data"])

    def test_non_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="未知模块"):
            normalize_modules([1, 2])


class TestResolveFeatures:
    def test_all_seven_combinations(self) -> None:
        """7 种非空组合的功能矩阵（与旧 workspace_type 矩阵逐项对齐，I3）."""
        expected: dict[tuple[str, ...], dict[str, bool]] = {
            ("tables", "documents", "design"): {
                "tables": True,
                "documents": True,
                "design": True,
                "analytics": True,
                "datasource": True,
                "acquisition": True,
                "quality": True,
            },
            ("tables", "documents"): {
                "tables": True,
                "documents": True,
                "design": False,
                "analytics": True,
                "datasource": True,
                "acquisition": True,
                "quality": True,
            },
            ("tables", "design"): {
                "tables": True,
                "documents": False,
                "design": True,
                "analytics": True,
                "datasource": True,
                "acquisition": True,
                "quality": True,
            },
            ("documents", "design"): {
                "tables": False,
                "documents": True,
                "design": True,
                "analytics": False,
                "datasource": False,
                "acquisition": True,
                "quality": True,
            },
            ("tables",): {
                "tables": True,
                "documents": False,
                "design": False,
                "analytics": True,
                "datasource": True,
                "acquisition": True,
                "quality": True,
            },
            ("documents",): {
                "tables": False,
                "documents": True,
                "design": False,
                "analytics": False,
                "datasource": False,
                "acquisition": True,
                "quality": True,
            },
            ("design",): {
                "tables": False,
                "documents": False,
                "design": True,
                "analytics": False,
                "datasource": False,
                "acquisition": False,
                "quality": True,
            },
        }
        for modules, matrix in expected.items():
            assert resolve_features(list(modules)) == matrix, modules

    def test_quality_always_enabled(self) -> None:
        """质量检查恒开放（ADR 0080 D4），且不在绑定表中."""
        assert "quality" not in MODULE_FEATURES
        for m in MODULE_FEATURES:
            assert resolve_features([m])["quality"] is True


class TestLegacyTypeToModules:
    def test_three_values(self) -> None:
        assert legacy_type_to_modules("data_doc") == ALL
        assert legacy_type_to_modules("data") == ["tables"]
        assert legacy_type_to_modules("doc") == ["documents", "design"]

    def test_unknown_falls_back_to_all(self) -> None:
        assert legacy_type_to_modules("bogus") == ALL


class TestWorkspaceModulesFromMeta:
    def test_v12_modules_field(self) -> None:
        modules, warning = workspace_modules_from_meta({"modules": ["design", "tables"]})
        assert modules == ["tables", "design"]
        assert warning is None

    def test_legacy_field_mapped(self) -> None:
        for raw, expected in (("data_doc", ALL), ("data", ["tables"]), ("doc", ["documents", "design"])):
            modules, warning = workspace_modules_from_meta({"workspace_type": raw})
            assert modules == expected
            assert warning is None

    def test_legacy_unknown_falls_back_with_warning(self) -> None:
        modules, warning = workspace_modules_from_meta({"workspace_type": "bogus"})
        assert modules == ALL
        assert warning is not None and "bogus" in warning

    def test_invalid_modules_falls_back_with_warning(self) -> None:
        modules, warning = workspace_modules_from_meta({"modules": []})
        assert modules == ALL
        assert warning is not None and "非法" in warning

    def test_no_fields_defaults_all(self) -> None:
        modules, warning = workspace_modules_from_meta({})
        assert modules == ALL
        assert warning is None
