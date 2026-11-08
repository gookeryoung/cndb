"""设计内容落版唯一入口（ADR 0125 D8 / I1 / I4）.

职责：把「编译 → 写当前内容 → 落版本 → 同步引用索引 → 依赖陈旧传播」收敛到
一处，供手动保存、自动检查点、依赖刷新、历史恢复四条写路径共用。

路由层只负责权限与请求编排，不再各自拼写 ``DesignDesign`` / 版本字段。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError
from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
from cndb.plugins.design.services.dsl.compile import CompileResult
from cndb.plugins.design.services.files import (
    compile_design_file,
    direct_library_refs,
    direct_use_keys,
    latest_version_number,
    mark_referrers_stale,
    sync_refs,
)


def latest_version(db: Session, design_id: int) -> DesignDesignVersion | None:
    """取设计最新版本行（无版本返回 None；保存去重与检查点判定用）."""
    return (
        db.query(DesignDesignVersion)
        .filter(DesignDesignVersion.design_id == design_id)
        .order_by(DesignDesignVersion.version_number.desc())
        .first()
    )


def dependency_tuples(result: CompileResult) -> list[dict[str, Any]]:
    """CompileResult.dependencies → 可 JSON 化的闭包列表（ADR 0118 C8 超集）."""
    items: list[dict[str, Any]] = []
    for item in result.dependencies:
        entry: dict[str, Any] = {
            "source": item.source,
            "file_key": item.file_key,
            "version_number": item.version_number,
            "content_hash": item.content_hash,
        }
        if item.source == "library":
            entry.update(
                {
                    "module_id": item.module_id,
                    "module_version_id": item.module_version_id,
                    "bundle_hash": item.bundle_hash,
                }
            )
        else:
            entry["file_id"] = item.file_id
        items.append(entry)
    return items


def add_version(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    content: str,
    compiled: dict[str, Any],
    change_type: str,
    comment: str = "",
    dependencies: list[dict[str, Any]] | None = None,
) -> int:
    """为设计落一个新版本，返回版本号（I2：单序列；I5：依赖闭包随版本快照）."""
    number = latest_version_number(db, design.id) + 1
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=design.workspace_id,
            version_number=number,
            change_type=change_type,
            content=content,
            compiled=compiled,
            dependencies=[dict(item) for item in (dependencies or [])],
            comment=comment,
            created_by_id=user.id,
        )
    )
    return number


def compile_for_design(
    db: Session,
    design: DesignDesign,
    content: str | None = None,
    *,
    pinned: dict[str, int] | None = None,
    granted_library_keys: frozenset[tuple[str, int]] | None = None,
) -> CompileResult:
    """以设计文件身份编译（kind / file_id / 工作区 resolver / 库解析器），失败 400."""
    result = compile_design_file(
        db,
        design,
        content,
        pinned=pinned,
        granted_library_keys=granted_library_keys,
    )
    if not result.ok:
        raise BadRequestError(
            "；".join(f"第{d.line}行第{d.col}列：{d.message}" for d in result.diagnostics) or "编译失败",
            code="design_compile_failed",
        )
    return result


def persist_design_content(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    content: str,
    change_type: str,
    comment: str = "",
    pinned: dict[str, int] | None = None,
    granted_library_keys: frozenset[tuple[str, int]] | None = None,
    propagate_stale: bool = True,
) -> int:
    """编译并落一个新版本，更新当前正式内容；**不 commit**，由调用方提交.

    ``propagate_stale=False`` 供依赖刷新使用：原文与直接引用未变，无需沿反向
    引用图重复置陈旧标记。
    """
    result = compile_for_design(
        db,
        design,
        content,
        pinned=pinned,
        granted_library_keys=granted_library_keys,
    )
    assert result.ir is not None
    design.content = content
    design.compiled = result.ir
    design.dependencies = dependency_tuples(result)
    design.updated_by_id = user.id
    number = add_version(
        db,
        design,
        user,
        content=content,
        compiled=result.ir,
        change_type=change_type,
        comment=comment,
        dependencies=dependency_tuples(result),
    )
    sync_refs(db, design, direct_use_keys(design.content), direct_library_refs(design.content))
    if propagate_stale:
        mark_referrers_stale(db, design.id)
    return number
