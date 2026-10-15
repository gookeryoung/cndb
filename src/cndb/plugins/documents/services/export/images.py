"""导出时的站内图片解析 —— `![alt](file:<file_key>)` → 本地文件字节.

背景：编辑器插入图片时写入的是**应用内引用** ``file:<file_key>``（见前端 `imageRef.ts`），
文件实际存放在 ``settings.UPLOAD_DIR/{workspace_id}/{file_key}``。导出 Word / PDF 时必须把
引用替换为真实图片，否则导出物里只剩一行 markdown 文本。

安全：`file_key` 只接受「无路径分隔符、不以点开头、不含 `..`」的文件名（与上传路由
`tables/routers/files.py::_file_path` 同一套约束），再把解析后的绝对路径限制在工作区目录内，
避免导出接口被当成任意文件读取（如 ``file:../../../etc/passwd``）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

FILE_REF_PREFIX = "file:"

# 独占一行的图片引用（编辑器插入时即按独占段落写回）
IMAGE_LINE_RE = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\(file:(?P<key>[^)\s]+)\)\s*$")

# 行内出现的图片引用（用于提取需要解析的 file_key）
INLINE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(file:(?P<key>[^)\s]+)\)")

# 解析结果：file_key → (图片字节, 原始文件名) ；返回 None 表示找不到或不合法
ImageResolver = Callable[[str], "tuple[bytes, str] | None"]


def is_safe_file_key(file_key: str) -> bool:
    """file_key 是否安全（无路径分隔符 / 不以点开头 / 不含 .. / 长度合理）."""
    if not file_key or len(file_key) > 255:
        return False
    return not (".." in file_key or "/" in file_key or "\\" in file_key or file_key.startswith("."))


def resolve_upload_path(upload_dir: Path, workspace_id: int, file_key: str) -> Path | None:
    """把 file_key 解析为工作区上传目录内的真实文件路径（越界 / 缺失返回 None）."""
    if not is_safe_file_key(file_key):
        return None
    work_dir = (Path(upload_dir) / str(workspace_id)).resolve()
    candidate = (work_dir / file_key).resolve()
    # 前缀校验：字符串拼接在 Windows 反斜杠下会误判，统一用 is_relative_to
    if candidate != work_dir and not candidate.is_relative_to(work_dir):
        return None
    return candidate if candidate.is_file() else None


def make_image_resolver(upload_dir: Path, workspace_id: int) -> ImageResolver:
    """构造导出用解析器：返回 None 的引用会被渲染为占位文本."""

    def _resolve(file_key: str) -> tuple[bytes, str] | None:
        path = resolve_upload_path(upload_dir, workspace_id, file_key)
        if path is None:
            return None
        try:
            return path.read_bytes(), path.name
        except OSError:  # pragma: no cover - 极少数读失败场景
            return None

    return _resolve


def referenced_file_keys(markdown_text: str) -> list[str]:
    """按出现顺序去重列出正文引用的 file_key（供统计 / 校验用）."""
    seen: list[str] = []
    for m in INLINE_IMAGE_RE.finditer(markdown_text or ""):
        key = m.group("key")
        if key not in seen:
            seen.append(key)
    return seen
