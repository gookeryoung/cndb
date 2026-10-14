"""文档种子：`documents/` 目录树 → documents 插件数据。

含 front-matter 解析、`{{table:...}}` 动态引用解析、目录树入库与幂等判重。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cndb.cli.seed import paths

# ── 文档种子：documents/ 目录树 → documents 插件数据 ────────────────

# 文档元数据头（简易 front-matter）：入库前剥离，避免预览正文出现 `---` 噪音
_DOC_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# 文件名 / 目录名排序前缀：`01-` / `02_` / `3.` / `4、`
_DOC_ORDER_PREFIX_RE = re.compile(r"^\d+[-_.、\s]+")
# 正文中的数据表动态引用占位符：`{{table:表名|view=视图名|limit=20}}`
_DOC_TABLE_REF_RE = re.compile(r"\{\{table:([^}|]+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}")
# 标签色板（标签名稳定取色，无需在种子中手工声明颜色）
_DOC_TAG_PALETTE = ("#2F54EB", "#13C2C2", "#722ED1", "#FA8C16", "#EB2F96", "#52C41A", "#FA541C", "#1890FF")
_DOC_STATUSES = ("draft", "published", "archived")


def _get_workspace_document_dirs(datasets_dir: Path) -> dict[str, Path]:
    """扫描每个工作区文件夹下的 documents/ 文档种子目录.

    Returns:
        工作区显示名 -> documents/ 目录路径 的映射（未提供文档种子的工作区跳过）.
    """
    result: dict[str, Path] = {}
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        docs_dir = folder / "documents"
        if not docs_dir.is_dir():
            continue
        result[paths._workspace_display_name(folder.name)] = docs_dir
    return result


def _document_title_from_name(name: str) -> str:
    """文件名 / 目录名 → 文档标题（剥离 ``01-`` 之类的排序前缀）."""
    title = _DOC_ORDER_PREFIX_RE.sub("", name).strip()
    return title or name.strip()


def _document_entry_sort_key(path: Path) -> tuple[Any, ...]:
    """文档树目录项自然排序键：数字段按数值比较（``10-`` 排在 ``9-`` 之后）."""
    parts = [part for part in re.split(r"(\d+)", path.name) if part]
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def _iter_document_entries(dir_path: Path) -> list[Path]:
    """按名称自然排序返回文档种子目录下的子目录与 Markdown 文件（隐藏项跳过）."""
    entries = [
        p
        for p in dir_path.iterdir()
        if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in (".md", ".markdown"))
    ]
    return sorted(entries, key=_document_entry_sort_key)


def _parse_document_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """解析文档种子的简易元数据头，返回 (元数据, 剥离元数据头后的正文).

    支持的键（其余忽略）：

    - ``title``：覆盖文件名派生的标题；
    - ``status``：draft / published / archived（缺省 published）；
    - ``tags``：``[a, b]`` 或 ``a, b`` 两种写法；
    - ``author`` / ``summary``：写入文档作者与摘要（summary 覆盖自动摘要）。

    无元数据头时返回空元数据与原正文（原样入库）。
    """
    match = _DOC_FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key == "tags":
            tags = [t.strip().strip("\"'") for t in value.strip("[]").split(",")]
            meta["tags"] = [t for t in tags if t]
        elif key in ("title", "status", "author", "summary") and value:
            meta[key] = value
    return meta, text[match.end() :]


def _document_tag_color(name: str) -> str:
    """按标签名稳定取色（同名标签跨工作区同色，便于演示标签视觉分组）."""
    return _DOC_TAG_PALETTE[sum(ord(ch) for ch in name) % len(_DOC_TAG_PALETTE)]


def _resolve_document_table_refs(
    content: str,
    table_ids: dict[str, int],
    view_ids: dict[tuple[str, str], int],
) -> str:
    """把正文中 ``{{table:表名|view=视图名|limit=N}}`` 的符号名解析为数字 ID.

    - 表名已是数字：原样保留（允许种子直接写死 ID）；
    - 表名解析失败：保留原占位符并打印告警（正文仍可读，不阻断 seed）；
    - 视图名解析失败：忽略该 ``view`` 参数并打印告警，其余参数原样透传。
    """

    def _replace(match: re.Match[str]) -> str:
        table_name = match.group(1).strip()
        if table_name.isdigit():
            return match.group(0)
        table_id = table_ids.get(table_name)
        if table_id is None:
            print(f"[seed-文档] 数据表引用 '{table_name}' 不存在，保留占位符原样")
            return match.group(0)

        params: list[str] = []
        for part in match.group(2).lstrip("|").split("|"):
            if not part:
                continue
            key, _, value = part.partition("=")
            if key == "view" and value and not value.isdigit():
                view_id = view_ids.get((table_name, value))
                if view_id is None:
                    print(f"[seed-文档] 视图引用 '{table_name}/{value}' 不存在，已忽略 view 参数")
                    continue
                params.append(f"view={view_id}")
            else:
                params.append(part)
        return f"{{{{table:{table_id}{''.join(f'|{p}' for p in params)}}}}}"

    return _DOC_TABLE_REF_RE.sub(_replace, content)


def _seed_documents(
    db: Any,
    user: Any,
    ws_map: dict[str, Any],
    tables_map: dict[str, dict[str, Any]],
    datasets_dir: Path | None,
) -> tuple[int, int]:
    """按各工作区 documents/ 目录注入典型文档树（文件夹 + Markdown 文档）.

    目录结构即文档树：子目录 → 文件夹节点，``*.md`` → Markdown 文档。
    标题取文件名（剥离 ``01-`` 排序前缀，可由元数据头 ``title`` 覆盖）；
    元数据头（``---`` 包裹）提供 status / tags / author / summary 并在入库前剥离，
    避免预览正文出现 ``---`` 噪音。正文中 ``{{table:表名|view=视图名|limit=N}}``
    由本函数解析为该工作区真实的表 / 视图 ID（前端只认数字 ID）。

    幂等：同工作区同父节点下同名文档已存在时跳过，不覆盖既有内容。

    Returns:
        (创建的文档数, 创建的文件夹数).
    """
    from cndb.plugins.tables.models import DataView

    if datasets_dir is None:
        print("[seed-文档] examples/datasets 目录不存在，跳过文档注入")
        return 0, 0

    ws_dirs = _get_workspace_document_dirs(datasets_dir)
    if not ws_dirs:
        print("[seed-文档] 未发现任何 documents/ 文档种子目录，跳过文档注入")
        return 0, 0

    doc_count = 0
    folder_count = 0

    for ws_name, docs_root in ws_dirs.items():
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-文档] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue

        tables = tables_map.get(ws_name, {})
        table_ids = {name: dt.id for name, dt in tables.items()}
        id_to_table_name = {dt.id: name for name, dt in tables.items()}
        view_ids: dict[tuple[str, str], int] = {}
        if table_ids:
            rows = (
                db.query(DataView)
                .filter(DataView.table_id.in_(list(table_ids.values())), DataView.owner_id.is_(None))
                .all()
            )
            view_ids = {(id_to_table_name[row.table_id], row.name): row.id for row in rows}

        created_docs, created_folders = _document_create_nodes(
            db,
            user,
            ws.id,
            ws_name,
            table_ids,
            view_ids,
            {},
            None,
            _iter_document_entries(docs_root),
        )
        doc_count += created_docs
        folder_count += created_folders

    print(f"[seed-文档] 完成：{doc_count} 篇文档 + {folder_count} 个文件夹")
    return doc_count, folder_count


def _document_ensure_tag(db: Any, workspace_id: int, name: str, cache: dict[str, int]) -> int:
    """按标签名取/建工作区标签（色板稳定取色），返回标签 ID；cache 为工作区级缓存."""
    from cndb.plugins.documents.models import Tag

    if name not in cache:
        tag = db.query(Tag).filter(Tag.workspace_id == workspace_id, Tag.name == name).first()
        if tag is None:
            tag = Tag(workspace_id=workspace_id, name=name, color=_document_tag_color(name))
            db.add(tag)
            db.flush()
        cache[name] = tag.id
    return cache[name]


def _document_find_existing(db: Any, workspace_id: int, parent_id: int | None, title: str) -> Any:
    """同工作区同父节点下同名未删除文档（seed 幂等判重）."""
    from cndb.plugins.documents.models import Document

    query = db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.title == title,
        Document.is_deleted == False,  # noqa: E712
    )
    if parent_id is None:
        query = query.filter(Document.parent_id.is_(None))
    else:
        query = query.filter(Document.parent_id == parent_id)
    return query.first()


def _document_create_nodes(
    db: Any,
    user: Any,
    workspace_id: int,
    ws_name: str,
    table_ids: dict[str, int],
    view_ids: dict[tuple[str, str], int],
    tag_cache: dict[str, int],
    parent_id: int | None,
    entries: list[Path],
) -> tuple[int, int]:
    """递归创建一层文档树节点，返回 (新增文档数, 新增文件夹数).

    单节点失败仅回滚并告警，不阻断同层其它节点（与 _seed_views 的隔离策略一致）。
    """
    from cndb.plugins.documents.models import CHANGE_TYPE_IMPORT
    from cndb.plugins.documents.services import content as doc_content

    doc_count = 0
    folder_count = 0
    for sort_order, entry in enumerate(entries):
        if entry.is_dir():
            folder_title = _document_title_from_name(entry.name)
            existing_folder = _document_find_existing(db, workspace_id, parent_id, folder_title)
            if existing_folder is not None:
                print(f"[seed-文档] 跳过已存在文件夹: {ws_name}/{folder_title}")
                child_folder_id: int | None = existing_folder.id
            else:
                try:
                    folder = doc_content.create_document(
                        db,
                        workspace_id,
                        user,
                        title=folder_title,
                        is_folder=True,
                        parent_id=parent_id,
                        sort_order=sort_order,
                        change_type=CHANGE_TYPE_IMPORT,
                    )
                except Exception as exc:  # 单节点失败不阻断其它文档
                    db.rollback()
                    print(f"[seed-文档] 文件夹创建失败: {ws_name}/{folder_title}: {exc}")
                    continue
                folder_count += 1
                print(f"[seed-文档] 文件夹: {ws_name}/{folder_title} (id={folder.id})")
                child_folder_id = folder.id
            sub_docs, sub_folders = _document_create_nodes(
                db,
                user,
                workspace_id,
                ws_name,
                table_ids,
                view_ids,
                tag_cache,
                child_folder_id,
                _iter_document_entries(entry),
            )
            doc_count += sub_docs
            folder_count += sub_folders
            continue

        meta, body = _parse_document_front_matter(entry.read_text(encoding="utf-8"))
        title = str(meta.get("title") or _document_title_from_name(entry.stem)).strip()
        status = str(meta.get("status", "published"))
        if status not in _DOC_STATUSES:
            print(f"[seed-文档] 非法 status={status!r}，按 published 处理: {ws_name}/{title}")
            status = "published"
        if _document_find_existing(db, workspace_id, parent_id, title) is not None:
            print(f"[seed-文档] 跳过已存在文档: {ws_name}/{title}")
            continue

        resolved = _resolve_document_table_refs(body, table_ids, view_ids)
        try:
            doc = doc_content.create_document(
                db,
                workspace_id,
                user,
                title=title,
                content=resolved,
                parent_id=parent_id,
                status=status,
                tag_ids=[_document_ensure_tag(db, workspace_id, t, tag_cache) for t in meta.get("tags", [])],
                sort_order=sort_order,
                change_type=CHANGE_TYPE_IMPORT,
            )
        except Exception as exc:  # 单文档失败不阻断其它
            db.rollback()
            print(f"[seed-文档] 文档创建失败: {ws_name}/{title}: {exc}")
            continue
        if meta.get("author") or meta.get("summary"):
            doc.author = str(meta.get("author") or doc.author)
            doc.summary = str(meta.get("summary") or doc.summary)
            db.commit()
        doc_count += 1
        print(f"[seed-文档] {ws_name}/{title} ({status}, {doc.content_size} 字节, id={doc.id})")

    return doc_count, folder_count
