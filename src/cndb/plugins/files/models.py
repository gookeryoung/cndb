"""文件归属模型：file_key → 所属数据表/文档.

背景：附件此前只是"工作区内的 UUID 文件名"，下载仅校验工作区成员身份 —— 即
**持有 file_key 即可读**（capability URL）。这在使用上可接受（键不可猜、无目录列举），
但无法表达"这个文件属于某张受限表/某份未发布文档"这一事实：

- 受限表（read_role 高于普通成员）里的附件，任何成员只要拿到键就能下载；
- 未发布文档里的图片同理；
- 行级过滤挡掉的行，其附件仍可被有表读权限的人下载。

本模型记录上传时的归属（表 / 行 / 文档），下载与删除时据此按**归属对象的权限**校验；
历史无归属记录的文件保持原行为（工作区成员 + 不可猜键）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cndb.models.base import Base, TimestampMixin


class FileOwner(TimestampMixin, Base):
    """单个上传文件的归属（表/行/文档三者最多一个，均空表示仅工作区级）."""

    __tablename__ = "files_fileowner"
    __table_args__ = {"extend_existing": True}

    file_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces_workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=True, index=True
    )
    row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents_document.id", ondelete="CASCADE"), nullable=True, index=True
    )
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"FileOwner(file_key={self.file_key!r}, ws={self.workspace_id}, "
            f"table={self.table_id}, row={self.row_id}, doc={self.document_id})"
        )


__all__ = ["FileOwner"]
