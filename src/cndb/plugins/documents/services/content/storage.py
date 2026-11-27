"""文档内容的分级存储与读取：内联 / 内联 gzip / 外存三层策略.

``_DOCS_DIR`` 的物理定义在包顶层 ``content/__init__.py``（I3 单一可变状态），
本模块只经 ``_docs_root()`` 延迟读取，因此 ``monkeypatch.setattr(content, "_DOCS_DIR", …)``
对所有外存路径立即生效（ADR 0180 D3）。
"""

from __future__ import annotations

import base64
import gzip
import logging
import zlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.documents.models import EXTERNAL_MIN_SIZE, Document, DocumentVersion

# 固定全名而非 __name__：拆包后日志分类必须仍是 …services.content（ADR 0180 D7）
logger = logging.getLogger("cndb.plugins.documents.services.content")

_COMPRESSED_PREFIX = "gz:"

# 低于该体积直接内联原文：压缩收益不足以抵消解压与 base64 膨胀开销。
# 4KB 起压缩可显著降低「长文档 × 多版本」的 DB / 备份体积（格式与读取路径不变）。
RAW_INLINE_MAX_SIZE = 4 * 1024


def _docs_root() -> Path:
    """外存根目录：**运行时**读取包顶层 ``_DOCS_DIR``（ADR 0180 I3 / D3）.

    不能在 import 期快照：``tests/conftest.py`` 的 session 级 fixture 会
    ``monkeypatch.setattr(content, "_DOCS_DIR", tmp_path)`` 重定向外存根，
    快照会让全部外存用例静默写进真实 ``data/docs``。
    """
    from cndb.plugins.documents.services import content as _pkg

    return _pkg._DOCS_DIR


def _external_dir(doc_id: int, root: Path | None = None) -> Path:
    return (root if root is not None else _docs_root()) / str(doc_id)


def external_version_path(doc_id: int, version_number: int, root: Path | None = None) -> Path:
    """外存内容文件路径：``data/docs/{doc_id}/v{n}.md.gz``.

    文件名自描述版本号，是外存内容的唯一权威定位方式；``Document.content_path``
    只是"最新外存版本"的兼容冗余字段，多版本时会被后来者覆盖，**不可**用于读取
    历史版本（否则所有历史版本都会串到最新内容）。

    Args:
        root: 自定义外存根目录（体检/回收集成测试用；默认跟随数据库目录）。
    """
    return _external_dir(doc_id, root) / f"v{version_number}.md.gz"


def load_content(version: DocumentVersion | None, doc: Document) -> str:
    """从版本记录加载内容，自动识别压缩/外存策略.

    外存版本按 ``data/docs/{doc_id}/v{version_number}.md.gz`` 定位（文件名自描述
    版本号）；内容缺失/损坏时降级为空串并记 warning —— 读取路径（详情 / 版本 /
    diff / 检索 / 分享）不应因单个坏文件整体 500。
    """
    if version is None:
        return ""
    raw = version.content or ""
    if raw == "" and version.content_size > 0:
        return _read_external_content(doc, version)
    if raw.startswith(_COMPRESSED_PREFIX):
        return decode_inline_compressed(raw)
    return raw


def _read_external_content(doc: Document, version: DocumentVersion) -> str:
    """读取外存版本内容，失败降级为空串."""
    path = external_version_path(doc.id, version.version_number)
    if not path.is_file() and doc.content_path:
        # 兼容历史非标准落盘位置：仅当冗余路径确为当前版本的文件名时才采用，
        # 避免"多版本共用 doc.content_path"把历史版本读成最新内容。
        legacy = Path(doc.content_path)
        if legacy.name == path.name and legacy.is_file():
            path = legacy
    if not path.is_file():
        logger.warning("外存内容文件缺失: %s（doc=%s v%s）", path, doc.id, version.version_number)
        return ""
    try:
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        logger.warning("外存内容文件损坏，已降级为空内容: %s（%s）", path, exc)
        return ""


def decode_inline_compressed(raw: str) -> str:
    """解码内联 gzip+base64 内容，失败降级为空串."""
    try:
        return gzip.decompress(base64.b64decode(raw[len(_COMPRESSED_PREFIX) :])).decode("utf-8")
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        logger.warning("内联压缩内容损坏，已降级为空内容: %s", exc)
        return ""


def latest_version(db: Session, doc_id: int) -> DocumentVersion | None:
    """最新版本记录（version_number 最大）。"""
    return db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def version_count(db: Session, doc_id: int) -> int:
    return int(db.execute(select(func.count()).where(DocumentVersion.document_id == doc_id)).scalar_one())


def store_content_bytes(doc: Document, next_num: int, content: str, raw_size: int) -> str:
    """按分级存储策略落盘，返回 DB content 字段应存的值.

    - ≤4KB：原文内联
    - 4KB–2MB：gz base64 内联（``gz:`` 前缀）
    - >2MB：gzip 写 ``data/docs/{doc_id}/v{n}.md.gz``，返回 ""；同时刷新
      ``doc.content_path``（仅作"最新外存版本"冗余标记，读取以版本号定位为准）
    """
    if raw_size <= RAW_INLINE_MAX_SIZE:
        return content
    compressed = gzip.compress(content.encode("utf-8"), compresslevel=6)
    if raw_size > EXTERNAL_MIN_SIZE:
        path = external_version_path(doc.id, next_num)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        doc.content_path = str(path)
        return ""
    return _COMPRESSED_PREFIX + base64.b64encode(compressed).decode("ascii")
