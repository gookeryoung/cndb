"""WPS 嵌入单元格图片解析 — DISPLIMG 公式识别、cellimages 映射提取与落盘.

WPS 表格的「插入单元格图片」在 xlsx 中的存储机制：
1. 单元格值是公式 ``=DISPLIMG("ID_XXX", 1)``（兼容导出时的 ``_xlfn.DISPLIMG`` 前缀）；
2. ``xl/cellimages.xml``（WPS 私有扩展）定义 ID → 图片关系（经 rId 指向 media 文件）；
3. ``xl/_rels/cellimages.xml.rels`` 把 rId 映射到 ``xl/media/`` 下的图片二进制。

本模块把 1+2+3 串起来：识别单元格里的 DISPLIMG 公式，按 ID 取出图片二进制，
可选落盘到工作区上传目录（与 files 路由同款存储布局），产出附件同构的
图片元数据 dict 供 image / attachment 字段直接消费。
"""

from __future__ import annotations

import datetime as dt
import logging
import mimetypes
import re
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from cndb.core.config import settings
from cndb.plugins.tables.field_types import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

# 与 files 路由上传端点一致的单文件上限（50 MB）
_MAX_WPS_IMAGE_BYTES = 50 * 1024 * 1024

# WPS 单元格图片公式：=DISPLIMG("ID_XXX", 1)
# - 前导 '=' 可省（openpyxl 读 <f> 元素时不含 '='）；
# - 兼容 Excel 兼容导出的 _xlfn. 前缀与大小写变体；
# - 第二参数为任意整数（固定为 1，宽松匹配）。
_DISPLIMG_RE = re.compile(
    r"""^\s*=?\s*(?:_xlfn\.)?DISPLIMG\(\s*["']([^"']+)["']\s*,\s*-?\d+\s*\)\s*$""",
    re.IGNORECASE,
)


@dataclass
class WpsCellImage:
    """WPS cellimages.xml 中定义的单张单元格图片."""

    displimg_id: str
    filename: str
    data: bytes
    mime_type: str


def match_displimg_formula(value: Any) -> str | None:
    """匹配 WPS 单元格图片公式值，返回其中的图片 ID；非该公式返回 None."""
    if not isinstance(value, str):
        return None
    # 快速预筛：绝大多数单元格不含 DISPLIMG，子串检查比正则便宜一个量级
    if "DISPLIMG" not in value.upper():
        return None
    m = _DISPLIMG_RE.match(value)
    return m.group(1) if m else None


def _local_tag(tag: str) -> str:
    """去掉 XML 元素名的命名空间前缀（{ns}name → name）."""
    return tag.rsplit("}", 1)[-1]


def _iter_descendants(root: Any) -> Any:
    """遍历 root 全部后代元素（含 root 自身）."""
    yield root
    yield from root.iter()


def _resolve_media_path(cellimages_dir: str, target: str) -> str:
    """把 rels 的相对 Target 解析为 zip 内绝对路径（posix 风格）."""
    parts: list[str] = []
    for seg in f"{cellimages_dir}/{target}".split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def parse_wps_cell_images(xlsx_bytes: bytes) -> dict[str, WpsCellImage]:
    """从 xlsx 字节串提取 WPS 单元格图片映射.

    Returns:
        ``{displimg_id: WpsCellImage}``；非 WPS 文件（无 ``xl/cellimages.xml``）
        返回空 dict。单个部件损坏只记 warning 跳过，不中断整体解析。
    """
    try:
        zf = zipfile.ZipFile(BytesIO(xlsx_bytes))
    except (zipfile.BadZipFile, OSError):
        logger.debug("WPS 图片解析：文件不是合法 zip，跳过", exc_info=True)
        return {}

    with zf:
        if "xl/cellimages.xml" not in zf.namelist():
            return {}

        import xml.etree.ElementTree as ET

        # 1) rId → media 路径
        rels_map: dict[str, str] = {}
        try:
            rels_root = ET.fromstring(zf.read("xl/_rels/cellimages.xml.rels"))
            for el in _iter_descendants(rels_root):
                if _local_tag(el.tag) != "Relationship":
                    continue
                rid = el.get("Id")
                target = el.get("Target") or ""
                if rid and target:
                    rels_map[rid] = _resolve_media_path("xl", target)
        except (KeyError, ET.ParseError):
            logger.warning("WPS 图片解析：cellimages.xml.rels 缺失或损坏，忽略单元格图片", exc_info=True)
            return {}

        # 2) cellimage 项：cNvPr@name（= DISPLIMG ID）→ blip@embed（= rId）
        id_to_rid: dict[str, str] = {}
        try:
            ci_root = ET.fromstring(zf.read("xl/cellimages.xml"))
            for el in _iter_descendants(ci_root):
                if _local_tag(el.tag) != "cellimage":
                    continue
                name = None
                embed = None
                for sub in el.iter():
                    tag = _local_tag(sub.tag)
                    if tag == "cNvPr" and name is None:
                        name = sub.get("name")
                    elif tag == "blip" and embed is None:
                        # r:embed 属性带命名空间，按 local 名匹配
                        for attr_key, attr_val in sub.attrib.items():
                            if _local_tag(attr_key) == "embed":
                                embed = attr_val
                                break
                if name and embed:
                    id_to_rid[name] = embed
        except ET.ParseError:
            logger.warning("WPS 图片解析：cellimages.xml 损坏，忽略单元格图片", exc_info=True)
            return {}

        # 3) 组装 ID → 图片二进制
        images: dict[str, WpsCellImage] = {}
        for displimg_id, rid in id_to_rid.items():
            media_path = rels_map.get(rid)
            if not media_path:
                logger.warning("WPS 图片 %s 的关系 %s 未映射到 media 文件，跳过", displimg_id, rid)
                continue
            try:
                data = zf.read(media_path)
            except KeyError:
                logger.warning("WPS 图片 media 文件 %s 不存在，跳过", media_path)
                continue
            filename = media_path.rsplit("/", 1)[-1]
            mime = mimetypes.guess_type(filename)[0] or "image/png"
            images[displimg_id] = WpsCellImage(
                displimg_id=displimg_id,
                filename=filename,
                data=data,
                mime_type=mime,
            )
        return images


def _build_meta(file_key: str, img: WpsCellImage) -> dict[str, Any]:
    """构造附件同构的图片元数据 dict（与 files 路由上传返回一致）."""
    return {
        "file_key": file_key,
        "filename": img.filename,
        "size": len(img.data),
        "mime_type": img.mime_type,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
    }


def make_displimg_resolver(
    xlsx_bytes: bytes,
    image_saver: Callable[[WpsCellImage], dict[str, Any] | None] | None = None,
) -> Callable[[str], list[dict[str, Any]] | None]:
    """构造 DISPLIMG ID → 图片元数据列表 的解析器.

    cellimages 映射惰性提取（首个 DISPLIMG 命中才开 zip 解析）；
    image_saver 缺省用 ephemeral（不落盘）。解析失败（无映射 / saver
    拒收）返回 None —— 调用方将单元格置空。

    Returns:
        resolve(displimg_id) → ``[元数据 dict]`` 或 None.
    """
    saver = image_saver or ephemeral_image_saver
    cell_images: dict[str, WpsCellImage] | None = None

    def resolve(displimg_id: str) -> list[dict[str, Any]] | None:
        nonlocal cell_images
        if cell_images is None:
            cell_images = parse_wps_cell_images(xlsx_bytes)
        img = cell_images.get(displimg_id)
        if img is None:
            logger.warning("WPS 单元格图片 %s 在 cellimages.xml 中无映射，导入时置空", displimg_id)
            return None
        meta = saver(img)
        if meta is None:
            return None
        return [meta]

    return resolve


def ephemeral_image_saver(img: WpsCellImage) -> dict[str, Any] | None:
    """不落盘的图片解析器 — 供纯 analyze 预览路径做类型推断与样本展示.

    产出与落盘版同构但 ``file_key`` 为空的元数据；非图片扩展名拒收（返回 None）。
    """
    ext = f".{img.filename.rsplit('.', 1)[-1].lower()}" if "." in img.filename else ""
    if ext not in IMAGE_EXTENSIONS:
        return None
    return _build_meta("", img)


def make_workspace_image_saver(workspace_id: int) -> Callable[[WpsCellImage], dict[str, Any] | None]:
    """构造绑定工作区的图片落盘器 — 与 files 路由同款存储布局.

    Returns:
        saver(img) → 附件同构元数据 dict；扩展名不在图片白名单或超过
        50MB 返回 None（调用方将单元格置空）。
    """

    def saver(img: WpsCellImage) -> dict[str, Any] | None:
        ext = f".{img.filename.rsplit('.', 1)[-1].lower()}" if "." in img.filename else ""
        if ext not in IMAGE_EXTENSIONS:
            logger.warning("WPS 图片 %s 扩展名 %s 不在白名单，导入时置空", img.displimg_id, ext)
            return None
        if len(img.data) > _MAX_WPS_IMAGE_BYTES:
            logger.warning("WPS 图片 %s 超过 50MB 上限，导入时置空", img.displimg_id)
            return None
        work_dir = settings.UPLOAD_DIR / str(workspace_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        file_key = f"{uuid.uuid4().hex}{ext}"
        (work_dir / file_key).write_bytes(img.data)
        return _build_meta(file_key, img)

    return saver


__all__ = [
    "WpsCellImage",
    "ephemeral_image_saver",
    "make_displimg_resolver",
    "make_workspace_image_saver",
    "match_displimg_formula",
    "parse_wps_cell_images",
]
