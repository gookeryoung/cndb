"""文档内容服务（包）：对外公开面与拆分前模块完全等价（ADR 0180 I1 / C3）.

``__all__`` 是唯一权威导出清单。``_DOCS_DIR`` 的物理定义在此处（I3 单一可变状态），
子模块经 ``storage._docs_root()`` 延迟读取，因此对包顶层属性的 monkeypatch 写后立即生效。
"""

from __future__ import annotations

from pathlib import Path

from cndb.core.config import settings
from cndb.plugins.documents.models import EXTERNAL_MIN_SIZE  # noqa: F401 兼容拆分前从本模块取该常量的调用

from . import access, storage  # noqa: F401
from ._legacy import (
    _GRAPH_CACHE_MAX_ENTRIES,
    _GRAPH_CACHE_TTL_SECONDS,
    DUPLICATE_SUFFIX,
    GRAPH_MAX_NODES,
    _broken_node_id,
    _copy_asset_file,
    _document_tag_ids,
    _duplicate_node,
    _graph_cache,
    _prune_graph_cache,
    _unique_duplicate_title,
    build_link_graph,
    duplicate_document,
    invalidate_link_graph_cache,
    reset_link_graph_cache,
)
from .access import (
    _get_workspace,
    get_deleted_document_or_404,
    get_document_any_state_or_404,
    get_document_or_404,
    require_editor,
)
from .fts import (
    _fts_upsert_sql,
    _sync_fts_delete,
    sync_fts,
)
from .links import (
    find_backlinks,
    repair_wikilinks,
    resolve_outgoing_links,
)
from .serialize import (
    _document_visibility,
    _normalize_ts,
    _serialize_document,
    pinned_document_ids,
    serialize_document,
    serialize_documents,
    set_document_pin,
    sort_pinned_first,
)
from .storage import (
    _COMPRESSED_PREFIX,
    RAW_INLINE_MAX_SIZE,
    _external_dir,
    _read_external_content,
    decode_inline_compressed,
    external_version_path,
    latest_version,
    load_content,
    logger,
    store_content_bytes,
    version_count,
)
from .tags import (
    _apply_tags,
    _refresh_tag_counts,
)
from .trash import (
    _collect_purge_targets,
    _mark_deleted_subtree,
    _remove_asset_files,
    _restore_subtree,
    _same_delete_batch,
    list_deleted_documents,
    purge_document,
    restore_document,
    soft_delete_document,
    soft_delete_documents,
)
from .write import (
    _dispatch_document_saved,
    _mark_open_change_requests_stale,
    create_document,
    ensure_text_document,
    move_target_reason,
    replace_document_asset,
    rollback_version,
    update_content,
)

# 外存根目录：跟随数据库目录（data/docs）
_DOCS_DIR = (
    Path(settings.DATABASE_URL.replace("sqlite:///", "")).parent / "docs"
    if (settings.DATABASE_URL.startswith("sqlite:///"))
    else Path("data/docs")
)

__all__ = [
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
]
