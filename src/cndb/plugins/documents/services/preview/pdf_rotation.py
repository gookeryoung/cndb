"""PDF 派生副本：页面方向读取与旋转 / 水平镜像（ADR 0164 P0）.

口径：

- **只读输入**：只读取原件字节，派生副本写内存，不回写原件（ADR 0164 I1）；
- **单一方向来源**：先把页面既有 ``/Rotate`` 烘焙进内容流，再应用用户旋转 / 镜像，
  输出页 ``/Rotate`` 恒为 0，避免浏览器与本功能叠加两次方向（ADR 0164 I2）；
- **有界**：输入 / 输出体积沿用原件上限，超过即报错；
- **缓存**：进程内 LRU，键含文档与原件文件 key，覆盖上传自然换键。
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter, Transformation

from cndb.plugins.documents.services.importers.formats import MAX_ASSET_BYTES

#: 允许的旋转角度（顺时针，度数）
VALID_ROTATIONS = (0, 90, 180, 270)

#: 派生副本缓存总字节上限
CACHE_MAX_BYTES = 64 * 1024 * 1024


class PdfRotationError(Exception):
    """PDF 无法解析或无法生成派生副本（路由层映射为 422）."""


@dataclass(frozen=True)
class PageOrientation:
    """单页声明的方向与页面尺寸（未应用 ``/Rotate`` 的 MediaBox 宽高）."""

    rotate: int
    width: float
    height: float


def _open_reader(data: bytes) -> PdfReader:
    """打开 PDF 并做加密校验；任何解析异常统一转 :class:`PdfRotationError`."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfRotationError("加密 PDF 不支持旋转")
        return reader
    except PdfRotationError:
        raise
    except Exception as exc:  # pypdf 抛错类型不稳定，统一包装
        raise PdfRotationError("PDF 解析失败") from exc


def read_page_orientations(data: bytes) -> list[PageOrientation]:
    """读取每页 ``/Rotate`` 与 MediaBox 尺寸（不做内容改写）."""
    reader = _open_reader(data)
    pages: list[PageOrientation] = []
    try:
        for page in reader.pages:
            box = page.mediabox
            raw = page.get("/Rotate", 0) or 0
            pages.append(
                PageOrientation(
                    rotate=int(raw) % 360,
                    width=float(box.width),
                    height=float(box.height),
                )
            )
    except PdfRotationError:
        raise
    except Exception as exc:  # 同上
        raise PdfRotationError("PDF 解析失败") from exc
    if not pages:
        raise PdfRotationError("PDF 没有可读页面")
    return pages


def render_rotated(data: bytes, *, rotate: int, flip: bool) -> bytes:
    """生成旋转 / 水平镜像后的派生副本.

    Args:
        data: 原件 PDF 字节。
        rotate: 顺时针旋转角度，取值 ``0 / 90 / 180 / 270``。
        flip: 是否在最终显示方向做水平镜像。

    Raises:
        PdfRotationError: 解析失败、加密、无页面或输出超限。
    """
    if rotate not in VALID_ROTATIONS:
        raise ValueError(f"不支持的旋转角度: {rotate}")
    if len(data) > MAX_ASSET_BYTES:
        raise PdfRotationError("原件超出体积上限")

    reader = _open_reader(data)
    try:
        writer = PdfWriter(clone_from=reader)
        for page in writer.pages:
            # 先烘焙页面既有方向，再叠加用户旋转，保证「只应用一次方向」（I2）
            page.transfer_rotation_to_content()
            if rotate:
                page.rotate(rotate)
                page.transfer_rotation_to_content()
            if flip:
                width = float(page.mediabox.width)
                page.add_transformation(Transformation().scale(-1, 1).translate(tx=width, ty=0))
        out = io.BytesIO()
        writer.write(out)
    except PdfRotationError:
        raise
    except Exception as exc:  # 同上
        raise PdfRotationError("PDF 无法生成旋转副本") from exc

    result = out.getvalue()
    if len(result) > MAX_ASSET_BYTES:
        raise PdfRotationError("旋转副本超出体积上限")
    return result


# ── 进程内 LRU 缓存 ───────────────────────────────────────────────────────────


class _DerivedCache:
    """按字节数设上限的 LRU；键含文档与原件文件 key，覆盖上传自然换键."""

    def __init__(self, max_bytes: int = CACHE_MAX_BYTES) -> None:
        self._items: OrderedDict[tuple[object, ...], bytes] = OrderedDict()
        self._total = 0
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._total = 0

    def get_or_create(self, key: tuple[object, ...], factory: Callable[[], bytes]) -> bytes:
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return cached

        result = factory()

        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                return existing
            if len(result) <= self._max_bytes:
                self._items[key] = result
                self._total += len(result)
                while self._total > self._max_bytes and self._items:
                    _, evicted = self._items.popitem(last=False)
                    self._total -= len(evicted)
            return result


_CACHE = _DerivedCache()


def clear_cache() -> None:
    """清空派生副本缓存（测试与运维用）."""
    _CACHE.clear()


def get_derived(data: bytes, *, doc_id: int, file_key: str, rotate: int, flip: bool) -> bytes:
    """按 ``(doc_id, file_key, rotate, flip)`` 取派生副本，未命中则生成并缓存."""
    key: tuple[object, ...] = (doc_id, file_key, rotate, flip)
    return _CACHE.get_or_create(key, lambda: render_rotated(data, rotate=rotate, flip=flip))
