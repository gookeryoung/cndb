"""ADR 0180：content 包拆分的结构与不变量测试.

覆盖 ADR 0180 的硬不变量：

- I1 公开面等价：包顶层可导出名集合与拆分前模块一致，且全部可访问；
- I2 依赖单向无环：``storage`` 不依赖同包其它模块，``access`` 只向下依赖；
- I3 单一可变状态：``_DOCS_DIR`` / ``_graph_cache`` 全包只有一处物理定义，
  子模块经延迟属性读取，对包顶层的 monkeypatch 立即生效；
- D3 / D7：被 monkeypatch 的函数经包属性解析、logger 用固定全名。

这些断言都属于「结构契约」，与业务语义无关；业务行为由原有测试覆盖。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from cndb.plugins.documents.services import content as content_pkg
from cndb.plugins.documents.services.content import storage

PKG_DIR = Path(content_pkg.__file__).parent
PKG_PREFIX = "cndb.plugins.documents.services.content"

# 拆分前 content.py 的 66 个顶层符号（ADR 0180 C3 / I1）
EXPECTED_NAMES = {
    "DUPLICATE_SUFFIX",
    "GRAPH_MAX_NODES",
    "RAW_INLINE_MAX_SIZE",
    "_COMPRESSED_PREFIX",
    "_DOCS_DIR",
    "_GRAPH_CACHE_MAX_ENTRIES",
    "_GRAPH_CACHE_TTL_SECONDS",
    "_apply_tags",
    "_broken_node_id",
    "_collect_purge_targets",
    "_copy_asset_file",
    "_dispatch_document_saved",
    "_document_tag_ids",
    "_document_visibility",
    "_duplicate_node",
    "_external_dir",
    "_fts_upsert_sql",
    "_get_workspace",
    "_graph_cache",
    "_mark_deleted_subtree",
    "_mark_open_change_requests_stale",
    "_normalize_ts",
    "_prune_graph_cache",
    "_read_external_content",
    "_refresh_tag_counts",
    "_remove_asset_files",
    "_restore_subtree",
    "_same_delete_batch",
    "_serialize_document",
    "_sync_fts_delete",
    "_unique_duplicate_title",
    "build_link_graph",
    "create_document",
    "decode_inline_compressed",
    "duplicate_document",
    "ensure_text_document",
    "external_version_path",
    "find_backlinks",
    "get_deleted_document_or_404",
    "get_document_any_state_or_404",
    "get_document_or_404",
    "invalidate_link_graph_cache",
    "latest_version",
    "list_deleted_documents",
    "load_content",
    "logger",
    "move_target_reason",
    "pinned_document_ids",
    "purge_document",
    "repair_wikilinks",
    "replace_document_asset",
    "require_editor",
    "reset_link_graph_cache",
    "resolve_outgoing_links",
    "restore_document",
    "rollback_version",
    "serialize_document",
    "serialize_documents",
    "set_document_pin",
    "soft_delete_document",
    "soft_delete_documents",
    "sort_pinned_first",
    "store_content_bytes",
    "sync_fts",
    "update_content",
    "version_count",
}


def _module_imports(module_path: Path) -> set[str]:
    """模块里的同包依赖集合（相对导入 / 包内绝对导入的模块名）."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    found.add(node.module.split(".")[0])
                else:
                    found.update(alias.name.split(".")[0] for alias in node.names)
            elif node.module and node.module.startswith(PKG_PREFIX):
                tail = node.module[len(PKG_PREFIX) :].lstrip(".")
                if tail:
                    found.add(tail.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{PKG_PREFIX}."):
                    tail = alias.name[len(PKG_PREFIX) + 1 :]
                    found.add(tail.split(".")[0])
    return found


def _top_level_assigns(module_path: Path) -> set[str]:
    """模块顶层的赋值目标名（含带注解的赋值）."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_public_surface_matches_pre_split_module() -> None:
    """I1：__all__ 与拆分前 66 个顶层符号完全一致，且都真的可访问."""
    assert set(content_pkg.__all__) == EXPECTED_NAMES
    assert len(content_pkg.__all__) == len(set(content_pkg.__all__))
    missing = [name for name in EXPECTED_NAMES if not hasattr(content_pkg, name)]
    assert missing == []


def test_public_surface_is_sorted() -> None:
    """__all__ 有序，便于人工核对与 diff."""
    assert list(content_pkg.__all__) == sorted(content_pkg.__all__)


def test_storage_does_not_depend_on_siblings() -> None:
    """I2：storage 是依赖图底层，不得 import 同包其它模块."""
    assert _module_imports(PKG_DIR / "storage.py") == set()


def test_access_only_depends_on_storage() -> None:
    """I2：access 只允许向下依赖 storage."""
    assert _module_imports(PKG_DIR / "access.py") <= {"storage"}


def test_package_dependency_graph_is_acyclic() -> None:
    """I2：包内依赖图无环."""
    graph = {path.stem: _module_imports(path) for path in PKG_DIR.glob("*.py")}

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"包内依赖出现环：{name}"
        if name in done:
            return
        visiting.add(name)
        for dep in graph.get(name, set()):
            if dep in graph:
                visit(dep)
        visiting.discard(name)
        done.add(name)

    for node in graph:
        visit(node)


def test_docs_dir_defined_once_in_package_init() -> None:
    """I3：_DOCS_DIR 只在包 __init__ 物理定义，子模块不得再赋值."""
    for path in PKG_DIR.glob("*.py"):
        assigned = _top_level_assigns(path)
        if path.name == "__init__.py":
            assert "_DOCS_DIR" in assigned
        else:
            assert "_DOCS_DIR" not in assigned, f"{path.name} 重复定义了 _DOCS_DIR"


def test_docs_dir_monkeypatch_takes_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """I3 / D3：patch 包顶层 _DOCS_DIR 后，storage 立即读到新根目录."""
    monkeypatch.setattr(content_pkg, "_DOCS_DIR", tmp_path)
    assert storage._docs_root() == tmp_path
    assert storage._external_dir(7) == tmp_path / "7"
    assert storage.external_version_path(7, 2) == tmp_path / "7" / "v2.md.gz"


def test_graph_cache_defined_once() -> None:
    """I3：_graph_cache 全包只有一处物理定义，包顶层只是再导出同一个对象."""
    defining = [path for path in PKG_DIR.glob("*.py") if "_graph_cache" in _top_level_assigns(path)]
    assert len(defining) == 1, [p.name for p in defining]
    owner = importlib.import_module(f"{PKG_PREFIX}.{defining[0].stem}")
    assert content_pkg._graph_cache is owner._graph_cache


def test_logger_uses_stable_name() -> None:
    """D7：各子模块 logger 用固定全名，拆包后日志分类不能碎掉."""
    found = 0
    for path in PKG_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "logger" for t in node.targets):
                continue
            call = node.value
            assert isinstance(call, ast.Call)
            arg = call.args[0]
            assert isinstance(arg, ast.Constant)
            assert arg.value == PKG_PREFIX
            found += 1
    # __init__ 不重复定义 logger（从 storage 再导出），子模块各自定义一份
    assert found >= 2, found


def test_private_symbols_still_importable() -> None:
    """I1：外部依赖的私有符号仍可从包顶层导入（routers/tags.py、测试直调）."""
    from cndb.plugins.documents.services.content import (
        _normalize_ts,
        _refresh_tag_counts,
        _serialize_document,
        require_editor,
    )

    assert callable(_refresh_tag_counts)
    assert callable(require_editor)
    assert callable(_normalize_ts)
    assert callable(_serialize_document)


def test_reexported_mutable_state_reads_through_package() -> None:
    """D3：包顶层 patch 的函数/常量，包内调用点必须经包属性解析才能生效."""
    source = (PKG_DIR / "_legacy.py").read_text(encoding="utf-8")
    for name in ("create_document", "latest_version", "load_content"):
        assert f"_pkg.{name}(" in source, f"_legacy 未经包属性调用 {name}"


def test_package_has_no_oversized_module() -> None:
    """I5 的补充：已拆出模块都明显小于原单文件，避免名义拆分.

    过渡期 ``_legacy.py`` 暂存尚未搬迁的符号，允许超限；P3 删掉它之后
    本断言会连它一起约束，确保拆完不再有大文件。
    """
    for path in PKG_DIR.glob("*.py"):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        limit = 1400 if path.name == "_legacy.py" else 400
        assert line_count < limit, f"{path.name} 仍有 {line_count} 行"
