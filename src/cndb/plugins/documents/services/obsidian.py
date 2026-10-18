"""Obsidian 文档库（vault）导入 / 导出.

导入（zip → 文档树）：
- ``*.md`` / ``*.markdown`` → 文档，zip 目录层级 → 文件夹；
- front-matter 的 ``title`` 作为文档标题（缺省用文件名），``tags`` → 工作区标签；
- ``![[img.png]]`` / ``![[报告.pdf]]`` → 上传附件并改写为站内引用 ``![](file:<key>)``；
- 标准 Markdown 图片 ``![](attachments/x.png)`` 同样按库内路径解析（Obsidian 关闭
  wikilink 时用这种写法）；
- ``[[笔记]]`` → ``[[标题]]``：剥掉路径前缀 / ``.md`` 后缀 / ``#锚点`` / ``|别名``，
  与站内双链口径对齐（反链按标题精确匹配，见 ``services.content.find_backlinks``）；
- 跳过 ``.obsidian`` / ``.trash`` / ``.git`` / ``__MACOSX`` 等隐藏目录（隐藏项一律忽略）。

导出（文档树 → zip）：
- 可见文档树按文件夹层级落盘为 ``<库名>/<文件夹>/<标题>.md``，含 front-matter
  （title / tags / created / updated）；
- 正文 ``![](file:<key>)`` → 附件落到 ``attachments/<key>`` 并改写为 ``![[attachments/…]]``；
- 附带最小 ``.obsidian/app.json``（附件目录指向 ``attachments``），解包即可被 Obsidian 识别为库。

设计约束：
- 两段式（analyze 只读 → import 落库），与数据表导入一致，前端可先看预览与冲突；
- 冲突策略 ``skip`` / ``rename`` / ``overwrite``：``rename`` 追加 `` (2)`` 递增，
  ``overwrite`` 走 ``content.update_content`` 生成新版本（历史可回溯），
  ``change_type`` 统一记为 ``auto_import``；
- 所有权重校验都在服务层：zip 路径穿越 / 解压炸弹 / 非法扩展名 / 非成员的 parent 一律拒绝。
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import unicodedata
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.core.errors import BadRequestError, ConflictError
from cndb.plugins.documents.models import (
    CHANGE_TYPE_IMPORT,
    DOC_STATUS_DRAFT,
    DOC_STATUSES,
    Document,
    DocumentVersion,
    Tag,
)
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services import parse, visibility
from cndb.plugins.documents.services.export.images import INLINE_IMAGE_RE, resolve_upload_path
from cndb.plugins.files.models import FileOwner

# ── 限制与常量 ──

MB = 1024 * 1024

#: 上传 zip 体积上限
MAX_ARCHIVE_BYTES = 200 * MB
#: 解压后总体积上限（防解压炸弹）
MAX_TOTAL_UNCOMPRESSED_BYTES = 600 * MB
#: 单个条目上限
MAX_ENTRY_BYTES = 60 * MB
#: 条目数量上限
MAX_ENTRIES = 20000
#: 单个 markdown 文件上限
MAX_MARKDOWN_BYTES = 8 * MB
#: 全部 markdown 读入内存上限（标题索引需要读全文）
MAX_MARKDOWN_TOTAL_BYTES = 128 * MB

MARKDOWN_SUFFIXES = (".md", ".markdown")

#: 隐藏目录/常见无意义目录（任一层命中即跳过整棵子树）
SKIP_DIR_NAMES = frozenset(
    {
        ".obsidian",
        ".trash",
        ".git",
        ".svn",
        ".hg",
        ".smart-env",
        ".venv",
        ".stfolder",
        "__macosx",
        "node_modules",
    }
)

#: 允许作为附件导入的扩展名（与上传路由的白名单同源，去掉脚本/可执行类）
ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".ico",
        ".tif",
        ".tiff",
        ".pdf",
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".mp4",
        ".webm",
        ".mov",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".csv",
        ".json",
        ".rtf",
    }
)

#: Obsidian 专属结构文件：转成 Markdown 文档导入（原始内容以代码块保留）
CONVERTIBLE_EXTENSIONS = (".canvas", ".base")

CONFLICT_SKIP = "skip"
CONFLICT_RENAME = "rename"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_POLICIES = (CONFLICT_SKIP, CONFLICT_RENAME, CONFLICT_OVERWRITE)

#: 预览返回的条目上限（总量另用计数返回，避免一次性吐几万行）
PREVIEW_LIMIT = 300
#: 导入结果里回传的文档上限
RESULT_DOCS_LIMIT = 200
#: 跳过项/警告明细上限
DETAIL_LIMIT = 100

_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_EMBED_RE = re.compile(r"!\[\[([^\[\]]+?)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*)$")
_UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_EXTERNAL_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", re.IGNORECASE)


# ── zip 读取 ──


def _normalize_entry_path(raw: str) -> str | None:
    """zip 条目名 → 归一化相对路径；不安全 / 目录 / 隐藏项返回 None.

    拒绝：绝对路径、盘符、``..`` 段、空名；统一分隔符为 ``/``。
    """
    name = (raw or "").replace("\\", "/").strip()
    if not name or name.endswith("/"):
        return None
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _is_skipped_path(path: str) -> bool:
    """隐藏项 / 无意义目录：任一层以 ``.`` 开头或命中黑名单即跳过."""
    parts = path.split("/")
    for segment in parts[:-1]:
        if segment.startswith(".") or segment.lower() in SKIP_DIR_NAMES:
            return True
    return parts[-1].startswith(".")


def _common_root(paths: list[str]) -> str:
    """若所有条目同处一个顶层目录（Obsidian 壓縮包常见），返回该目录名."""
    if not paths:
        return ""
    firsts = {p.split("/", 1)[0] for p in paths}
    if len(firsts) != 1:
        return ""
    if not all("/" in p for p in paths):
        return ""
    return next(iter(firsts))


class VaultArchive:
    """受限的 zip 读取器：路径归一化 + 解压炸弹防护 + 懒读取条目内容."""

    def __init__(self, data: bytes, filename: str = "") -> None:
        self.filename = filename
        if not data:
            raise BadRequestError("文件为空")
        if len(data) > MAX_ARCHIVE_BYTES:
            raise BadRequestError(f"压缩包过大（{len(data) // MB}MB > {MAX_ARCHIVE_BYTES // MB}MB）")
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise BadRequestError("不是有效的 zip 压缩包：请把 Obsidian 库文件夹打包为 .zip 后重试") from exc

        infos = [info for info in self._zip.infolist() if not info.is_dir()]
        if len(infos) > MAX_ENTRIES:
            raise BadRequestError(f"压缩包条目过多（{len(infos)} > {MAX_ENTRIES}）")
        total = sum(max(info.file_size, 0) for info in infos)
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise BadRequestError(f"解压后体积过大（{total // MB}MB > {MAX_TOTAL_UNCOMPRESSED_BYTES // MB}MB）")

        self.skipped: list[dict[str, str]] = []
        entries: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            path = _normalize_entry_path(info.filename)
            if path is None:
                self.skipped.append({"path": info.filename, "reason": "路径非法（绝对路径或包含 ..）"})
                continue
            if _is_skipped_path(path):
                self.skipped.append({"path": path, "reason": "隐藏目录或系统目录，已忽略"})
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                self.skipped.append({"path": path, "reason": f"单文件超过 {MAX_ENTRY_BYTES // MB}MB"})
                continue
            entries[path] = info

        root = _common_root(list(entries))
        if root:
            entries = {path[len(root) + 1 :]: info for path, info in entries.items()}

        self._entries = entries
        self.root_dir = root

    @property
    def paths(self) -> list[str]:
        return sorted(self._entries)

    def read(self, path: str) -> bytes:
        info = self._entries.get(path)
        if info is None:
            raise BadRequestError(f"压缩包内不存在条目：{path}")
        with self._zip.open(info) as handle:
            return handle.read()

    def markdown_paths(self) -> list[str]:
        return [p for p in self.paths if Path(p).suffix.lower() in MARKDOWN_SUFFIXES]

    def size_of(self, path: str) -> int:
        info = self._entries.get(path)
        return int(info.file_size) if info is not None else 0

    def attachment_paths(self) -> list[str]:
        return [
            p
            for p in self.paths
            if Path(p).suffix.lower() not in MARKDOWN_SUFFIXES and Path(p).suffix.lower() in ATTACHMENT_EXTENSIONS
        ]

    def convertible_paths(self) -> list[str]:
        """Obsidian 专属结构文件（.canvas / .base），转成文档后导入."""
        return [p for p in self.paths if Path(p).suffix.lower() in CONVERTIBLE_EXTENSIONS]


def _decode_markdown(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


# ── front-matter（容忍 Obsidian 常见写法） ──


def _clean_scalar(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return text.strip()


def parse_vault_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """解析 front-matter，返回 ``(元数据, 正文)``.

    支持 ``key: value``、``key: [a, b]`` 与块状列表（``key:`` 后跟 ``- item``）——
    ``services.parse.parse_front_matter`` 只认单行键值，无法处理 Obsidian 的标签列表。
    """
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, Any] = {}
    current = ""
    for raw_line in match.group(1).splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _LIST_ITEM_RE.match(line)
        if item is not None:
            if not current:
                continue
            value = _clean_scalar(item.group(1))
            if not value:
                continue
            bucket = meta.get(current)
            if not isinstance(bucket, list):
                items: list[str] = []
                bucket = items
                meta[current] = items
            bucket.append(value)
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if not key:
            continue
        current = key
        value = value.strip()
        if not value:
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            meta[key] = [_clean_scalar(part) for part in value[1:-1].split(",") if _clean_scalar(part)]
        else:
            meta[key] = _clean_scalar(value)
    return meta, text[match.end() :]


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return ""
    return str(value or "").strip()


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,\s]+", value) if part.strip()]
    return []


def _normalize_tag_name(raw: str) -> str:
    name = raw.strip().lstrip("#").strip()
    return name[:100]


def _clean_title(raw: str, *, fallback: str = "未命名") -> str:
    """标题清洗：去控制字符 / 多余空白，截断到 Document.title 的 500 上限."""
    text = unicodedata.normalize("NFKC", raw or "").replace("\x00", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:500] or fallback


def _safe_filename(raw: str, *, fallback: str = "未命名") -> str:
    """文件名清洗：剔除文件系统与 Obsidian 链接语法冲突的字符."""
    text = unicodedata.normalize("NFKC", raw or "").strip()
    text = _UNSAFE_NAME_RE.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:120]


# ── 库索引与笔记解析 ──


@dataclass
class VaultNote:
    """一篇库内笔记（markdown，或由 .canvas / .base 转换而来的文档）."""

    path: str
    folder: tuple[str, ...]
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    size: int = 0
    #: 来源类型：markdown / canvas / base
    kind: str = "markdown"


@dataclass
class _VaultIndex:
    """库内路径索引：双链按「相对路径 → 文件名」两级解析."""

    note_by_path: dict[str, str] = field(default_factory=dict)  # lower(relpath 去后缀) → path
    note_by_name: dict[str, str] = field(default_factory=dict)  # lower(文件名去后缀) → path
    titles: dict[str, str] = field(default_factory=dict)  # path → 标题
    attach_by_path: dict[str, str] = field(default_factory=dict)
    attach_by_name: dict[str, str] = field(default_factory=dict)

    def resolve_note(self, target: str, folder: tuple[str, ...]) -> str | None:
        text = target.replace("\\", "/").strip().lstrip("/")
        if text.lower().endswith(MARKDOWN_SUFFIXES):
            text = text.rsplit(".", 1)[0]
        if not text:
            return None
        candidates = [text]
        if folder:
            candidates.insert(0, "/".join(folder) + "/" + text)
        for candidate in candidates:
            hit = self.note_by_path.get(candidate.lower())
            if hit is not None:
                return hit
        return self.note_by_name.get(text.rsplit("/", 1)[-1].lower())

    def resolve_attachment(self, target: str, folder: tuple[str, ...]) -> str | None:
        text = target.replace("\\", "/").strip().lstrip("/")
        if not text:
            return None
        candidates = [text]
        if folder:
            candidates.insert(0, "/".join(folder) + "/" + text)
        for candidate in candidates:
            hit = self.attach_by_path.get(candidate.lower())
            if hit is not None:
                return hit
        return self.attach_by_name.get(text.rsplit("/", 1)[-1].lower())

    def title_of(self, path: str) -> str:
        return self.titles.get(path) or Path(path).stem


def _build_index(notes: list[VaultNote], attachment_paths: Iterable[str]) -> _VaultIndex:
    index = _VaultIndex()
    for note in notes:
        index.note_by_path[note.path.rsplit(".", 1)[0].lower()] = note.path
        index.note_by_name.setdefault(Path(note.path).stem.lower(), note.path)
        index.titles[note.path] = note.title
    for path in attachment_paths:
        index.attach_by_path[path.lower()] = path
        index.attach_by_name.setdefault(Path(path).name.lower(), path)
    return index


def _parse_notes(archive: VaultArchive) -> list[VaultNote]:
    notes: list[VaultNote] = []
    total = 0
    for path in archive.markdown_paths():
        data = archive.read(path)
        if len(data) > MAX_MARKDOWN_BYTES:
            archive.skipped.append({"path": path, "reason": f"markdown 超过 {MAX_MARKDOWN_BYTES // MB}MB"})
            continue
        total += len(data)
        if total > MAX_MARKDOWN_TOTAL_BYTES:
            raise BadRequestError(f"库内 markdown 总体积过大（> {MAX_MARKDOWN_TOTAL_BYTES // MB}MB），请分批导入")
        text = _decode_markdown(data)
        meta, body = parse_vault_front_matter(text)
        parts = path.split("/")
        note = VaultNote(
            path=path,
            folder=tuple(parts[:-1]),
            title=_clean_title(_as_text(meta.get("title")) or Path(path).stem),
            body=body,
            tags=[name for name in (_normalize_tag_name(t) for t in _as_list(meta.get("tags"))) if name],
            size=len(data),
        )
        # 单数 tag 键（部分库使用）
        if not note.tags:
            note.tags = [name for name in (_normalize_tag_name(t) for t in _as_list(meta.get("tag"))) if name]
        notes.append(note)

    # Obsidian 专属结构文件（.canvas / .base）→ Markdown 文档（原文以代码块保留，无损）
    for path in archive.convertible_paths():
        data = archive.read(path)
        if len(data) > MAX_MARKDOWN_BYTES:
            archive.skipped.append({"path": path, "reason": f"文件超过 {MAX_MARKDOWN_BYTES // MB}MB"})
            continue
        suffix = Path(path).suffix.lower()
        parts = path.split("/")
        body = _canvas_to_markdown(data, path) if suffix == ".canvas" else _base_to_markdown(data, path)
        notes.append(
            VaultNote(
                path=path,
                folder=tuple(parts[:-1]),
                title=_clean_title(Path(path).stem),
                body=body,
                size=len(data),
                kind=suffix.lstrip("."),
            )
        )
    return notes


def _canvas_to_markdown(data: bytes, path: str) -> str:
    """Obsidian Canvas（JSON）→ Markdown：卡片 / 连线 / 文件引用 + 原始 JSON.

    文本卡片正文原样保留（其中的双链随后统一走 ``rewrite_note_body`` 规范化）；
    文件卡片输出 ``[[库内路径]]``（图片等附件用嵌入），让同一套解析器处理。
    """
    raw = _decode_markdown(data)
    title = Path(path).name
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return f"> 由 Obsidian Canvas「{title}」转换导入，JSON 解析失败，仅保留原文。\n\n~~~text\n{raw.strip()}\n~~~\n"
    if not isinstance(payload, dict):
        return f"> 由 Obsidian Canvas「{title}」转换导入，结构无法识别，仅保留原文。\n\n~~~json\n{raw.strip()}\n~~~\n"

    nodes: list[Any] = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    edges: list[Any] = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    lines = [
        f"> 由 Obsidian Canvas「{title}」转换导入：{len(nodes)} 个卡片、{len(edges)} 条连线。"
        "原始 JSON 见文末（保留无损，可据此还原）。",
        "",
    ]

    order: dict[Any, int] = {}
    if nodes:
        lines.append("## 卡片")
        lines.append("")
    for index, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            continue
        order[node.get("id")] = index
        node_type = str(node.get("type") or "")
        if node_type == "text":
            text = str(node.get("text") or "").strip()
            lines.extend([f"### 文本卡片 {index}", "", text or "_（空卡片）_", ""])
        elif node_type == "file":
            file_path = str(node.get("file") or "").strip()
            subpath = str(node.get("subpath") or "").strip().lstrip("#")
            if not file_path:
                continue
            target = f"{file_path}#{subpath}" if subpath else file_path
            if Path(file_path).suffix.lower() in ATTACHMENT_EXTENSIONS:
                lines.extend([f"![[{target}]]", ""])
            else:
                lines.extend([f"[[{target}]]", ""])
        elif node_type == "link":
            url = str(node.get("url") or "").strip()
            if url:
                lines.extend([f"- <{url}>", ""])
        elif node_type == "group":
            label = str(node.get("label") or "").strip()
            lines.extend([f"### 分组：{label or f'分组 {index}'}", ""])

    if edges:
        lines.extend(["## 连线", ""])
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            start = order.get(edge.get("fromNode"), "?")
            end = order.get(edge.get("toNode"), "?")
            label = str(edge.get("label") or "").strip()
            suffix = f"（{label}）" if label else ""
            lines.append(f"- 卡片 {start} → 卡片 {end}{suffix}")
        lines.append("")

    pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    lines.extend(["## 原始 JSON", "", "~~~json", pretty, "~~~", ""])
    return "\n".join(lines)


def _base_to_markdown(data: bytes, path: str) -> str:
    """Obsidian Base（YAML 视图配置）→ Markdown：原文放进 yaml 代码块，无损保留."""
    raw = _decode_markdown(data).strip()
    title = Path(path).name
    return (
        f"> 由 Obsidian Base「{title}」转换导入：Base 是 Obsidian 的数据库视图配置，"
        "站内暂不支持还原为交互视图，此处保留原始 YAML 以便查阅与再导出。\n\n"
        f"~~~yaml\n{raw}\n~~~\n"
    )


# ── 正文改写（双链 / 附件） ──


@dataclass
class RewriteResult:
    """正文改写结果：正文 + 本次引用到的附件 + 告警明细."""

    body: str
    attachments: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    normalized_links: int = 0
    missing_attachments: int = 0


def rewrite_note_body(
    note: VaultNote,
    index: _VaultIndex,
    *,
    store_attachment: Callable[[str], str | None],
) -> RewriteResult:
    """把库内语法改写为站内语法.

    - ``![[附件]]`` / ``![[附件|300]]`` → ``![](file:<key>)``（``store_attachment`` 返回 None 表示不导入）
    - ``![[笔记]]`` / ``![[笔记#锚点]]`` → ``[[笔记标题]]``（嵌入无法表达，降级为普通双链）
    - ``[[目标#锚点|别名]]`` → ``[[标题#锚点|别名]]``：**只剥掉路径前缀与 .md 后缀**，
      锚点与别名原样保留（站内双链按标题匹配目标，锚点/别名仅用于展示）
    - ``![](attachments/x.png)`` → 站内引用；``[文字](Note.md)`` → ``[[标题]]``
    """
    result = RewriteResult(body=note.body)

    def _store(target: str) -> str | None:
        key = store_attachment(target)
        if key is None:
            result.missing_attachments += 1
            return None
        if target not in result.attachments:
            result.attachments.append(target)
        return key

    def _embed(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        parts = parse.parse_wikilink(raw)
        target, anchor = parts["target"], parts["anchor"]
        if not target:
            return match.group(0)
        note_path = index.resolve_note(target, note.folder)
        if note_path is not None:
            result.normalized_links += 1
            return parse.format_wikilink(index.title_of(note_path), anchor=anchor)
        attachment = index.resolve_attachment(target, note.folder)
        if attachment is not None:
            key = _store(attachment)
            if key is not None:
                return f"![{_safe_filename(Path(attachment).name)}](file:{key})"
        result.unresolved.append(f"![[{raw}]]")
        return match.group(0)

    def _wikilink(match: re.Match[str]) -> str:
        parts = parse.parse_wikilink(match.group(1))
        target, anchor, alias = parts["target"], parts["anchor"], parts["alias"]
        if not target:
            # [[#本文锚点]]：站内无本文锚点表达，退化为纯文本
            result.normalized_links += 1
            return anchor or match.group(0)

        note_path = index.resolve_note(target, note.folder)
        if note_path is not None:
            title = index.title_of(note_path)
            if title != target:
                result.normalized_links += 1
            return parse.format_wikilink(title, anchor=anchor, alias=alias)

        attachment = index.resolve_attachment(target, note.folder)
        if attachment is not None:
            key = _store(attachment)
            if key is not None:
                return f"![{_safe_filename(Path(attachment).name)}](file:{key})"

        # 未命中：保留锚点/别名，只剥掉库内路径前缀（站内按标题解析，路径无意义）
        cleaned = _strip_note_path(target)
        result.unresolved.append(parse.format_wikilink(cleaned, anchor=anchor, alias=alias))
        if cleaned != target:
            result.normalized_links += 1
        return parse.format_wikilink(cleaned, anchor=anchor, alias=alias)

    def _md_image(match: re.Match[str]) -> str:
        alt, url = match.group(1), match.group(2).strip()
        if _EXTERNAL_URL_RE.match(url):
            return match.group(0)
        attachment = index.resolve_attachment(_unquote(url), note.folder)
        if attachment is None:
            return match.group(0)
        key = _store(attachment)
        if key is None:
            return match.group(0)
        return f"![{alt or _safe_filename(Path(attachment).name)}](file:{key})"

    def _md_link(match: re.Match[str]) -> str:
        text, url = match.group(1), match.group(2).strip()
        if _EXTERNAL_URL_RE.match(url):
            return match.group(0)
        target = _unquote(url).split("#", 1)[0]
        if not target.lower().endswith(MARKDOWN_SUFFIXES):
            return match.group(0)
        note_path = index.resolve_note(target, note.folder)
        if note_path is None:
            return match.group(0)
        result.normalized_links += 1 if text else 0
        return f"[[{index.title_of(note_path)}]]"

    body = _EMBED_RE.sub(_embed, result.body)
    body = _WIKILINK_RE.sub(_wikilink, body)
    body = _MD_IMAGE_RE.sub(_md_image, body)
    body = _MD_LINK_RE.sub(_md_link, body)
    result.body = body
    return result


def _unquote(text: str) -> str:
    from urllib.parse import unquote

    try:
        return unquote(text)
    except Exception:  # pragma: no cover - 非法百分号编码
        return text


def _strip_note_path(target: str) -> str:
    """库内链接目标 → 站内标题：去掉目录前缀与 ``.md`` 后缀（锚点/别名由调用方另存）."""
    text = target.replace("\\", "/").strip().lstrip("/")
    if text.lower().endswith(MARKDOWN_SUFFIXES):
        text = text.rsplit(".", 1)[0]
    return text.rsplit("/", 1)[-1] or text


# ── 冲突检测 ──


def _sibling_map(db: Session, workspace_id: int) -> dict[int, dict[str, Document]]:
    """``parent_id → {小写标题: 文档}``（未删除）；根节点的键为 0."""
    rows = (
        db.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.is_deleted == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    out: dict[int, dict[str, Document]] = {}
    for doc in rows:
        out.setdefault(doc.parent_id or 0, {}).setdefault(doc.title.strip().lower(), doc)
    return out


def _existing_child(siblings: dict[int, dict[str, Document]], parent: int, title: str) -> Document | None:
    return siblings.get(parent, {}).get(title.strip().lower())


def _next_title(siblings: dict[int, dict[str, Document]], parent: int, title: str) -> str:
    """同名递增：``标题 (2)``、``标题 (3)``…"""
    taken = siblings.get(parent, {})
    if title.strip().lower() not in taken:
        return title
    for index in range(2, 1000):
        candidate = f"{title} ({index})"[:500]
        if candidate.strip().lower() not in taken:
            return candidate
    return f"{title} ({uuid.uuid4().hex[:6]})"[:500]


def _folder_chain(folder: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [folder[: i + 1] for i in range(len(folder))]


# ── 分析（只读） ──


def _validate_parent(db: Session, workspace_id: int, parent_id: int | None) -> Document | None:
    if parent_id is None:
        return None
    parent = content_service.get_document_or_404(db, workspace_id, parent_id)
    if not parent.is_folder:
        raise ConflictError("导入目标必须是文件夹")
    return parent


def analyze_vault(
    db: Session,
    workspace_id: int,
    user: Any,
    archive: VaultArchive,
    *,
    parent_id: int | None = None,
) -> dict[str, Any]:
    """解析库并给出导入预览（不写任何数据）."""
    content_service.require_editor(db, workspace_id, user)
    _validate_parent(db, workspace_id, parent_id)

    notes = _parse_notes(archive)
    attachment_paths = archive.attachment_paths()
    index = _build_index(notes, attachment_paths)
    siblings = _sibling_map(db, workspace_id)

    root_key = parent_id or 0
    folders: list[dict[str, Any]] = []
    folder_ids: dict[tuple[str, ...], int] = {}
    folder_status: dict[tuple[str, ...], str] = {}
    for folder in sorted({note.folder for note in notes}, key=lambda f: (len(f), f)):
        parent = root_key
        for chain in _folder_chain(folder):
            if chain in folder_ids:
                parent = folder_ids[chain]
                continue
            existing = _existing_child(siblings, parent, chain[-1])
            if existing is not None and existing.is_folder:
                folder_ids[chain] = existing.id
                folder_status[chain] = "existing"
                parent = existing.id
                continue
            # 新建：分配临时负 id 以区分"未知 id"，仅用于父子挂接与冲突判断
            fake = -(len(folder_ids) + 1)
            folder_ids[chain] = fake
            folder_status[chain] = "new"
            folders.append({"path": "/".join(chain), "title": chain[-1], "status": "new"})
            parent = fake

    items: list[dict[str, Any]] = []
    conflicts = 0
    for note in sorted(notes, key=lambda n: n.path):
        parent = folder_ids.get(note.folder, root_key)
        existing = None if parent < 0 else _existing_child(siblings, parent, note.title)
        status = "conflict" if existing is not None else "new"
        if existing is not None:
            conflicts += 1
        if len(items) < PREVIEW_LIMIT:
            items.append(
                {
                    "path": note.path,
                    "title": note.title,
                    "folder": "/".join(note.folder),
                    "size": note.size,
                    "tags": note.tags[:20],
                    "status": status,
                    "kind": note.kind,
                    "existing_document_id": existing.id if existing else None,
                }
            )

    referenced = sorted({target for note in notes for target in _referenced_attachments(note, index)})
    tag_names = sorted({tag for note in notes for tag in note.tags})
    warnings = _analyze_warnings(notes, archive)
    converted = [note for note in notes if note.kind != "markdown"]

    return {
        "filename": archive.filename,
        "root_dir": archive.root_dir,
        "total_notes": len(notes),
        "total_markdown": len(notes) - len(converted),
        "total_converted": len(converted),
        "total_folders": len(folders),
        "total_attachments": len(referenced),
        "total_attachment_bytes": sum(archive.size_of(path) for path in referenced),
        "total_bytes": sum(note.size for note in notes),
        "ignored_files": len(archive.skipped),
        "conflicts": conflicts,
        "tags": tag_names[:DETAIL_LIMIT],
        "warnings": warnings,
        "skipped": archive.skipped[:DETAIL_LIMIT],
        "preview_truncated": len(items) < len(notes),
        "folders": folders[:PREVIEW_LIMIT],
        "items": items,
    }


def _referenced_attachments(note: VaultNote, index: _VaultIndex) -> list[str]:
    """该笔记引用到的附件（不产生副作用，供预览统计）."""
    found: list[str] = []
    for match in _EMBED_RE.finditer(note.body):
        target = match.group(1).split("|", 1)[0].strip()
        if not target or index.resolve_note(target, note.folder) is not None:
            continue
        hit = index.resolve_attachment(target, note.folder)
        if hit is not None:
            found.append(hit)
    for match in _MD_IMAGE_RE.finditer(note.body):
        url = match.group(2).strip()
        if _EXTERNAL_URL_RE.match(url):
            continue
        hit = index.resolve_attachment(_unquote(url), note.folder)
        if hit is not None:
            found.append(hit)
    return found


def _analyze_warnings(notes: list[VaultNote], archive: VaultArchive) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    # 只有「路径前缀 / .md 后缀」会被剥掉；锚点与别名原样保留
    path_links = sum(
        1 for note in notes for link in _iter_links(note.body) if _strip_note_path(link["target"]) != link["target"]
    )
    if path_links:
        warnings.append(
            {
                "code": "wikilink_normalized",
                "message": f"{path_links} 处双链带路径前缀或 .md 后缀，导入后按标题解析（锚点与别名保留）",
                "count": path_links,
            }
        )
    self_anchors = sum(1 for note in notes for link in _iter_links(note.body) if not link["target"])
    if self_anchors:
        warnings.append(
            {
                "code": "anchor_only_links",
                "message": f"{self_anchors} 处本文内锚点链接（[[#标题]]）站内无法表达，已转为纯文本",
                "count": self_anchors,
            }
        )
    converted = [note for note in notes if note.kind != "markdown"]
    if converted:
        kinds = sorted({note.kind for note in converted})
        warnings.append(
            {
                "code": "converted_files",
                "message": f"{len(converted)} 个 .{'/.'.join(kinds)} 文件将转换为文档导入（卡片/连线转为正文，原始内容以代码块保留）",
                "count": len(converted),
            }
        )

    unsupported = [
        path
        for path in archive.paths
        if Path(path).suffix.lower() not in MARKDOWN_SUFFIXES
        and Path(path).suffix.lower() not in ATTACHMENT_EXTENSIONS
        and Path(path).suffix.lower() not in CONVERTIBLE_EXTENSIONS
    ]
    if unsupported:
        samples = "、".join(unsupported[:5]) + ("…" if len(unsupported) > 5 else "")
        warnings.append(
            {
                "code": "unsupported_files",
                "message": f"{len(unsupported)} 个文件类型不支持导入（{samples}）",
                "count": len(unsupported),
                "samples": unsupported[:10],
            }
        )
    if archive.skipped:
        warnings.append(
            {
                "code": "skipped_entries",
                "message": f"{len(archive.skipped)} 个条目被忽略（隐藏目录 / 系统目录 / 超限文件）",
                "count": len(archive.skipped),
            }
        )
    return warnings


def _iter_links(body: str) -> list[dict[str, str]]:
    """正文中的双链（跳过代码围栏），复用 ``parse.iter_wikilinks``."""
    return parse.iter_wikilinks(body)


# ── 导入 ──


class _TagRegistry:
    """工作区标签按名取用（大小写不敏感），缺失时按需创建.

    一次性载入现有标签，避免"每篇笔记一次 SELECT"的 N+1。
    """

    def __init__(self, db: Session, workspace_id: int, *, create: bool) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.create = create
        self.ids: dict[str, int] = {
            tag.name.strip().lower(): tag.id
            for tag in db.execute(select(Tag).where(Tag.workspace_id == workspace_id)).scalars().all()
        }
        self.created: list[str] = []

    def resolve(self, names: Iterable[str]) -> list[int]:
        out: list[int] = []
        for raw in names:
            name = _normalize_tag_name(raw)
            if not name:
                continue
            key = name.lower()
            tag_id = self.ids.get(key)
            if tag_id is None:
                if not self.create:
                    continue
                tag = Tag(workspace_id=self.workspace_id, name=name, color="#1890FF", description="")
                self.db.add(tag)
                self.db.flush()
                tag_id = tag.id
                self.ids[key] = tag_id
                self.created.append(name)
            if tag_id not in out:
                out.append(tag_id)
        return out


class _AttachmentStore:
    """单次导入的附件落盘器：写工作区上传目录 + 记归属（同一文档内按库内路径去重）."""

    def __init__(self, db: Session, workspace_id: int, user: Any, *, enabled: bool) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user = user
        self.enabled = enabled
        self.written = 0
        self.bytes_written = 0
        self._cache: dict[tuple[int, str], str] = {}
        self._pending: list[str] = []

    def store(self, archive: VaultArchive, vault_path: str) -> str | None:
        if not self.enabled:
            return None
        data = archive.read(vault_path)
        suffix = Path(vault_path).suffix.lower()
        key = f"{uuid.uuid4().hex}{suffix}"
        directory = Path(settings.UPLOAD_DIR) / str(self.workspace_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / key).write_bytes(data)
        self.written += 1
        self.bytes_written += len(data)
        return key

    def bind_owner(self, document_id: int, file_key: str) -> None:
        """文档落库后登记归属（下载按文档权限校验）."""
        self._pending.append(file_key)
        self.db.add(
            FileOwner(
                file_key=file_key,
                workspace_id=self.workspace_id,
                document_id=document_id,
                uploaded_by_id=getattr(self.user, "id", None),
            )
        )
        self._cache[(document_id, file_key)] = file_key

    def flush(self) -> None:
        if self._pending:
            self.db.commit()
            self._pending.clear()


def import_vault(
    db: Session,
    workspace_id: int,
    user: Any,
    archive: VaultArchive,
    *,
    parent_id: int | None = None,
    conflict: str = CONFLICT_RENAME,
    create_tags: bool = True,
    import_attachments: bool = True,
    status: str = DOC_STATUS_DRAFT,
) -> dict[str, Any]:
    """把库导入为文档树（文件夹 + 文档 + 标签 + 附件）."""
    if conflict not in CONFLICT_POLICIES:
        raise BadRequestError(f"不支持的冲突策略：{conflict}，可选 {'/'.join(CONFLICT_POLICIES)}")
    if status not in DOC_STATUSES:
        raise BadRequestError(f"不支持的文档状态：{status}")

    content_service.require_editor(db, workspace_id, user)
    _validate_parent(db, workspace_id, parent_id)

    notes = _parse_notes(archive)
    if not notes:
        raise BadRequestError("压缩包里没有找到 markdown 文档（.md / .markdown）")

    attachment_paths = archive.attachment_paths()
    index = _build_index(notes, attachment_paths)
    siblings = _sibling_map(db, workspace_id)
    store = _AttachmentStore(db, workspace_id, user, enabled=import_attachments)

    root_key = parent_id or 0
    folder_ids: dict[tuple[str, ...], int] = {}
    created_folders = 0

    def ensure_folder(folder: tuple[str, ...]) -> int:
        nonlocal created_folders
        parent = root_key
        for chain in _folder_chain(folder):
            known = folder_ids.get(chain)
            if known is not None:
                parent = known
                continue
            existing = _existing_child(siblings, parent, chain[-1])
            if existing is not None and existing.is_folder:
                folder_ids[chain] = existing.id
                parent = existing.id
                continue
            order = len(siblings.get(parent, {}))
            title = _next_title(siblings, parent, _clean_title(chain[-1], fallback="未命名文件夹"))
            created = content_service.create_document(
                db,
                workspace_id,
                user,
                title=title,
                is_folder=True,
                parent_id=(parent or None),
                status=status,
                sort_order=order,
            )
            folder_ids[chain] = created.id
            siblings.setdefault(parent, {})[title.strip().lower()] = created
            created_folders += 1
            parent = created.id
        return parent

    stats: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "folders_created": 0,
        "attachments": 0,
        "attachment_bytes": 0,
        "tags_created": [],
        "documents": [],
        "converted": 0,
        "skipped_notes": [],
        "warnings": [],
    }
    converted_created = 0
    tag_ids: list[int] = []
    tags = _TagRegistry(db, workspace_id, create=create_tags)
    total_normalized = 0
    unresolved: list[str] = []
    missing_attachments = 0

    for note in sorted(notes, key=lambda n: n.path):
        parent = ensure_folder(note.folder)
        title = _clean_title(note.title)
        existing = _existing_child(siblings, parent, title)

        if existing is not None and existing.is_folder:
            # 目标是文件夹：不能覆盖正文，按重名处理
            title = _next_title(siblings, parent, title)
            existing = None
        elif existing is not None and conflict == CONFLICT_SKIP:
            stats["skipped"] += 1
            if len(stats["skipped_notes"]) < DETAIL_LIMIT:
                stats["skipped_notes"].append({"path": note.path, "title": title, "reason": "同名文档已存在"})
            continue
        elif existing is not None and conflict == CONFLICT_RENAME:
            title = _next_title(siblings, parent, title)
            existing = None

        # 附件落盘 → 正文改写（附件按文档粒度去重）
        attached: dict[str, str] = {}

        def _store(vault_path: str, _attached: dict[str, str] = attached) -> str | None:
            if vault_path in _attached:
                return _attached[vault_path]
            key = store.store(archive, vault_path)
            if key is not None:
                _attached[vault_path] = key
            return key

        rewritten = rewrite_note_body(note, index, store_attachment=_store)
        total_normalized += rewritten.normalized_links
        missing_attachments += rewritten.missing_attachments
        for target in rewritten.unresolved:
            if len(unresolved) < DETAIL_LIMIT:
                unresolved.append(target)

        tag_ids = tags.resolve(note.tags)

        if existing is not None:
            doc = content_service.update_content(
                db,
                workspace_id,
                existing.id,
                user,
                content=rewritten.body,
                change_summary="从 Obsidian 库导入覆盖",
                change_type=CHANGE_TYPE_IMPORT,
            )
            if tag_ids:
                content_service._apply_tags(db, doc, tag_ids, user)
                db.commit()
            stats["updated"] += 1
        else:
            order = len(siblings.get(parent, {}))
            doc = content_service.create_document(
                db,
                workspace_id,
                user,
                title=title,
                content=rewritten.body,
                parent_id=(parent or None),
                status=status,
                tag_ids=tag_ids,
                sort_order=order,
                change_type=CHANGE_TYPE_IMPORT,
            )
            siblings.setdefault(parent, {})[title.strip().lower()] = doc
            stats["created"] += 1

        for key in attached.values():
            store.bind_owner(doc.id, key)
        store.flush()

        if note.kind != "markdown":
            converted_created += 1
        if len(stats["documents"]) < RESULT_DOCS_LIMIT:
            stats["documents"].append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "path": note.path,
                    "kind": note.kind,
                }
            )

    stats["converted"] = converted_created
    stats["folders_created"] = created_folders
    stats["attachments"] = store.written
    stats["attachment_bytes"] = store.bytes_written
    stats["tags_created"] = list(dict.fromkeys(tags.created))
    stats["total"] = stats["created"] + stats["updated"] + stats["skipped"]
    if total_normalized:
        stats["warnings"].append(
            {
                "code": "wikilink_normalized",
                "message": f"{total_normalized} 处双链按标题对齐（锚点与别名保留，仅剥离路径前缀 / .md 后缀）",
                "count": total_normalized,
            }
        )
    if unresolved:
        stats["warnings"].append(
            {
                "code": "unresolved_links",
                "message": f"{len(unresolved)} 处双链在库内找不到目标，按原文保留（导入后为断链）",
                "count": len(unresolved),
                "samples": unresolved[:10],
            }
        )
    if missing_attachments:
        stats["warnings"].append(
            {
                "code": "attachments_not_imported",
                "message": f"{missing_attachments} 处附件引用未导入（附件导入已关闭或超出白名单）",
                "count": missing_attachments,
            }
        )
    if archive.skipped:
        stats["warnings"].append(
            {
                "code": "skipped_entries",
                "message": f"{len(archive.skipped)} 个条目被忽略（隐藏目录 / 系统目录 / 超限文件）",
                "count": len(archive.skipped),
            }
        )
    return stats


# ── 导出 ──


def _front_matter_value(text: str) -> str:
    """YAML 标量：含特殊字符时加双引号（保证 Obsidian 正确解析）."""
    if not text:
        return '""'
    if re.search(r'[:#\[\]{}"\'&*!|>%@`,\n]', text) or text.strip() != text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _render_front_matter(title: str, tags: list[str], doc: Document) -> str:
    # 标题用文档原始标题（文件名可能因去重被加后缀/替换非法字符），换行压成空格保证 YAML 单行
    safe_title = re.sub(r"\s*\n\s*", " ", title or "").strip() or "未命名"
    lines = ["---", f"title: {_front_matter_value(safe_title)}"]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {_front_matter_value(tag)}" for tag in tags)
    created = _iso(doc.created_at)
    updated = _iso(doc.updated_at)
    if created:
        lines.append(f"created: {created}")
    if updated:
        lines.append(f"updated: {updated}")
    lines.append("---")
    return "\n".join(lines)


def _iso(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds")
    return ""


def _visible_documents(db: Session, workspace_id: int, user: Any) -> list[Document]:
    docs = (
        db.execute(
            select(Document)
            .where(Document.workspace_id == workspace_id, Document.is_deleted == False)  # noqa: E712
            .order_by(Document.sort_order, Document.id)
        )
        .scalars()
        .all()
    )
    visible = visibility.filter_visible_documents(db, workspace_id, docs, user)
    visible_ids = {doc.id for doc in visible}
    visible_ids |= visibility.visible_ancestor_ids(docs, visible)
    return [doc for doc in docs if doc.id in visible_ids]


def _latest_contents(db: Session, doc_ids: list[int]) -> dict[int, str]:
    """批量取各文档最新版本正文（避免逐文档查询）."""
    if not doc_ids:
        return {}
    latest = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .where(DocumentVersion.document_id.in_(doc_ids))
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    rows = db.execute(
        select(Document, DocumentVersion)
        .join(latest, latest.c.document_id == Document.id)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == latest.c.document_id)
            & (DocumentVersion.version_number == latest.c.version_number),
        )
        .where(Document.id.in_(doc_ids))
    ).all()
    return {doc.id: content_service.load_content(version, doc) for doc, version in rows}


def _tags_by_document(db: Session, doc_ids: list[int]) -> dict[int, list[str]]:
    from cndb.plugins.documents.models import DocumentTag

    if not doc_ids:
        return {}
    rows = db.execute(
        select(DocumentTag.document_id, Tag.name)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(doc_ids))
        .order_by(Tag.name)
    ).all()
    out: dict[int, list[str]] = {}
    for doc_id, name in rows:
        out.setdefault(int(doc_id), []).append(str(name))
    return out


def export_vault(
    db: Session,
    workspace_id: int,
    user: Any,
    *,
    workspace_name: str = "",
) -> tuple[bytes, str]:
    """把工作区文档树导出为 Obsidian 库（zip）.

    Returns:
        (zip 字节, 建议文件名)
    """
    docs = _visible_documents(db, workspace_id, user)
    if not any(not doc.is_folder for doc in docs):
        raise BadRequestError("当前工作区没有可导出的文档")

    contents = _latest_contents(db, [doc.id for doc in docs if not doc.is_folder])
    tags_map = _tags_by_document(db, [doc.id for doc in docs if not doc.is_folder])

    children: dict[int, list[Document]] = {}
    for doc in docs:
        children.setdefault(doc.parent_id or 0, []).append(doc)
    for bucket in children.values():
        bucket.sort(key=lambda d: (d.sort_order, d.id))

    root_name = _safe_filename(workspace_name or "vault", fallback="vault")
    names: dict[int, str] = {}
    dirs: dict[int, str] = {}  # 文档 id → 相对目录（不含根名）

    used: dict[int, set[str]] = {}
    for parent, bucket in children.items():
        for doc in bucket:
            stem = _safe_filename(doc.title, fallback="未命名")
            taken = used.setdefault(parent, set())
            candidate = stem
            for index in range(2, 1000):
                if candidate.lower() not in taken:
                    break
                candidate = f"{stem} ({index})"
            taken.add(candidate.lower())
            names[doc.id] = candidate
            dirs[doc.id] = f"{dirs.get(parent, '')}/{candidate}" if doc.is_folder else dirs.get(parent, "")

    attachments: dict[str, bytes] = {}
    root_dir = Path(settings.UPLOAD_DIR)
    buffer = io.BytesIO()
    total_notes = 0

    def _rewrite_images(text: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            key = match.group(2).strip()
            path = resolve_upload_path(root_dir, workspace_id, key)
            if path is None:
                return match.group(0)
            name = f"attachments/{key}"
            if name not in attachments:
                try:
                    attachments[name] = path.read_bytes()
                except OSError:  # pragma: no cover - 读失败保留原引用
                    return match.group(0)
            return f"![[{name}]]"

        return INLINE_IMAGE_RE.sub(_replace, text)

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for doc in docs:
            if doc.is_folder:
                archive.writestr(f"{root_name}/{dirs[doc.id].strip('/')}/", "")
                continue
            body = contents.get(doc.id, "")
            body = _rewrite_images(body)
            note_tags = tags_map.get(doc.id, [])
            front = _render_front_matter(doc.title, note_tags, doc)
            text = f"{front}\n\n{body.lstrip()}" if body else f"{front}\n"
            directory = dirs.get(doc.id, "").strip("/")
            rel = f"{root_name}/{directory + '/' if directory else ''}{names[doc.id]}.md"
            archive.writestr(rel, text)
            total_notes += 1

        for rel, data in sorted(attachments.items()):
            archive.writestr(f"{root_name}/{rel}", data)

        # 最小 Obsidian 配置：解包即可作为库打开，附件进 attachments/
        archive.writestr(
            f"{root_name}/.obsidian/app.json",
            '{\n  "attachmentFolderPath": "attachments",\n  "newLinkFormat": "shortest",\n  "useMarkdownLinks": false\n}\n',
        )
        archive.writestr(f"{root_name}/.obsidian/appearance.json", "{}\n")

    if total_notes == 0:  # pragma: no cover - 上面已守卫
        raise BadRequestError("当前工作区没有可导出的文档")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return buffer.getvalue(), f"{root_name}-obsidian-{stamp}.zip"


__all__ = [
    "ATTACHMENT_EXTENSIONS",
    "CONFLICT_OVERWRITE",
    "CONFLICT_POLICIES",
    "CONFLICT_RENAME",
    "CONFLICT_SKIP",
    "MAX_ARCHIVE_BYTES",
    "VaultArchive",
    "VaultNote",
    "analyze_vault",
    "export_vault",
    "import_vault",
    "parse_vault_front_matter",
    "rewrite_note_body",
]
