"""复用模块发布服务（ADR 0118 P0 §4）.

发布口径：零件设计 → 全局稳定 ``module_key`` + 不可变版本（根原文 + 自包含
依赖包 + 公开参数签名）。发布前必须编译通过，且模块内部不允许再出现
``lib:`` 引用（MVP 边界，D3）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import (
    LIBRARY_VISIBILITY_PUBLIC,
    LIBRARY_VISIBILITY_VALUES,
    DesignDesign,
    DesignDesignVersion,
    DesignLibraryModule,
    DesignLibraryVersion,
)
from cndb.plugins.design.services.dsl.compile import CompileResult, compile_design
from cndb.plugins.design.services.dsl.nodes import FileSource
from cndb.plugins.design.services.dsl.parse import DslSyntaxError
from cndb.plugins.design.services.files import compile_design_file, content_hash, direct_use_calls
from cndb.plugins.design.services.keys import generate_module_key


class LibraryPublishError(Exception):
    """发布失败：可定位诊断由路由层转 400（不落半成品版本）."""

    def __init__(self, message: str, line: int = 1, col: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


def _bundle_hash(files: list[dict[str, object]]) -> str:
    """依赖包规范 JSON 的 SHA-256（跨环境完整性校验口径）."""
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bundle_files(
    db: Session, design: DesignDesign, dependencies: list[tuple[int, int, str]]
) -> list[dict[str, object]]:
    """按依赖快照读取每个文件的该版本原文，形成自包含依赖包."""
    files: list[dict[str, object]] = []
    for file_id, version_number, file_key in dependencies:
        row = (
            db.query(DesignDesign.kind, DesignDesignVersion.content)
            .join(DesignDesignVersion, DesignDesignVersion.design_id == DesignDesign.id)
            .filter(
                DesignDesign.id == file_id,
                DesignDesign.workspace_id == design.workspace_id,
                DesignDesignVersion.version_number == version_number,
            )
            .first()
        )
        if row is None:
            raise LibraryPublishError(f"依赖快照缺失，无法发布：{file_key}", 1, 1)
        kind, content = row
        files.append(
            {
                "file_key": file_key,
                "kind": str(kind),
                "content": str(content),
                "content_hash": content_hash(str(content)),
            }
        )
    files.sort(key=lambda item: str(item["file_key"]))
    return files


def publish_design(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    visibility: str,
    name: str | None = None,
    description: str | None = None,
    comment: str = "",
) -> tuple[DesignLibraryModule, DesignLibraryVersion]:
    """发布设计为复用模块新版本（首次创建模块）；失败抛 ``LibraryPublishError``."""
    if design.kind != "part":
        raise LibraryPublishError("只有零件文件（part）可以发布为复用模块", 1, 1)
    if visibility not in LIBRARY_VISIBILITY_VALUES:
        raise LibraryPublishError("可见性仅支持 public / workspace", 1, 1)
    try:
        calls = direct_use_calls(design.content)
    except DslSyntaxError as exc:
        raise LibraryPublishError(exc.message, exc.line, exc.col) from exc
    for call in calls:
        if call.library is not None:
            raise LibraryPublishError("复用模块内部不允许再引用复用模块", call.line, call.col)

    result = compile_design_file(db, design, allow_library=False)
    if not result.ok:
        first = result.diagnostics[0] if result.diagnostics else None
        raise LibraryPublishError(
            first.message if first is not None else "编译失败",
            first.line if first is not None else 1,
            first.col if first is not None else 1,
        )
    assert result.ir is not None

    local_deps = [
        (item.file_id, item.version_number, item.file_key) for item in result.dependencies if item.source == "workspace"
    ]
    files = _bundle_files(db, design, local_deps)
    params = [
        {"name": str(item.get("name", "")), "default": item.get("value")}
        for item in result.ir.get("params", [])
        if isinstance(item, dict) and item.get("name")
    ]

    module = (
        db.query(DesignLibraryModule)
        .filter(
            DesignLibraryModule.source_design_id == design.id,
            DesignLibraryModule.owner_workspace_id == design.workspace_id,
        )
        .order_by(DesignLibraryModule.id)
        .first()
    )
    if module is not None and module.is_archived:
        raise LibraryPublishError("复用模块已归档，不能继续发布新版本", 1, 1)
    if module is None:
        module = DesignLibraryModule(
            module_key=generate_module_key(db, name or design.title),
            name=name or design.title,
            description=description or design.description,
            visibility=visibility,
            owner_workspace_id=design.workspace_id,
            source_design_id=design.id,
            is_archived=False,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
        db.add(module)
        db.flush()
    else:
        if name:
            module.name = name
        if description is not None:
            module.description = description
        module.visibility = visibility
        module.updated_by_id = user.id

    next_number = (
        int(
            db.query(func.max(DesignLibraryVersion.version_number))
            .filter(DesignLibraryVersion.module_id == module.id)
            .scalar()
            or 0
        )
        + 1
    )
    version = DesignLibraryVersion(
        module_id=module.id,
        version_number=next_number,
        content=design.content,
        files=files,
        params=params,
        content_hash=content_hash(design.content),
        bundle_hash=_bundle_hash(files),
        comment=comment,
        created_by_id=user.id,
    )
    db.add(version)
    db.flush()
    return module, version


def list_library_modules(
    db: Session,
    workspace_id: int,
    *,
    q: str | None = None,
    visibility: str | None = None,
    owned_only: bool = False,
    include_archived: bool = False,
) -> list[DesignLibraryModule]:
    """浏览可见模块：公开模块 + 当前工作区发布的私有模块（ADR 0118 §5）."""
    query = db.query(DesignLibraryModule).filter(
        or_(
            DesignLibraryModule.visibility == LIBRARY_VISIBILITY_PUBLIC,
            DesignLibraryModule.owner_workspace_id == workspace_id,
        )
    )
    if owned_only:
        query = query.filter(DesignLibraryModule.owner_workspace_id == workspace_id)
    if visibility is not None:
        query = query.filter(DesignLibraryModule.visibility == visibility)
    if not include_archived:
        query = query.filter(DesignLibraryModule.is_archived.is_(False))
    if q:
        query = query.filter(or_(DesignLibraryModule.name.contains(q), DesignLibraryModule.module_key.contains(q)))
    return query.order_by(DesignLibraryModule.updated_at.desc(), DesignLibraryModule.id.desc()).all()


def module_version_stats(db: Session, module_ids: Iterable[int]) -> dict[int, tuple[int, int]]:
    """批量统计模块版本数 / 最新版本号（列表页展示用）."""
    ids = list(module_ids)
    if not ids:
        return {}
    rows = (
        db.query(
            DesignLibraryVersion.module_id,
            func.count(DesignLibraryVersion.id),
            func.max(DesignLibraryVersion.version_number),
        )
        .filter(DesignLibraryVersion.module_id.in_(ids))
        .group_by(DesignLibraryVersion.module_id)
        .all()
    )
    return {int(module_id): (int(count), int(latest)) for module_id, count, latest in rows}


def module_latest_versions(db: Session, module_ids: Iterable[int]) -> dict[int, DesignLibraryVersion]:
    """批量取模块最新版本行（参数签名 / 哈希展示用）."""
    stats = module_version_stats(db, module_ids)
    if not stats:
        return {}
    pairs = {(module_id, latest) for module_id, (_count, latest) in stats.items()}
    rows = (
        db.query(DesignLibraryVersion)
        .filter(DesignLibraryVersion.module_id.in_([module_id for module_id, _ in pairs]))
        .all()
    )
    return {row.module_id: row for row in rows if (row.module_id, row.version_number) in pairs}


def module_versions(db: Session, module_id: int) -> list[DesignLibraryVersion]:
    """模块版本列表（按版本号倒序）."""
    return (
        db.query(DesignLibraryVersion)
        .filter(DesignLibraryVersion.module_id == module_id)
        .order_by(DesignLibraryVersion.version_number.desc())
        .all()
    )


def module_version(db: Session, module_id: int, version_number: int) -> DesignLibraryVersion | None:
    """按模块 + 版本号取不可变版本行."""
    return (
        db.query(DesignLibraryVersion)
        .filter(
            DesignLibraryVersion.module_id == module_id,
            DesignLibraryVersion.version_number == version_number,
        )
        .first()
    )


def is_system_admin(user: User) -> bool:
    """系统管理员判定（模块管理 / 归档列表的唯一口径）."""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", None) == "system_admin")


def can_manage_module(user: User) -> bool:
    """归档 / 可见性管理门槛：系统管理员恒可（工作区 owner 由路由层校验）."""
    return is_system_admin(user)


def preview_library_version(
    version: DesignLibraryVersion,
    overrides: dict[str, float] | None = None,
) -> CompileResult:
    """只读预览模块版本：依赖包内解析，不回落消费方工作区（与消费编译同口径）."""
    bundle = {
        str(item.get("file_key", "")): FileSource(
            file_id=0,
            file_key=str(item.get("file_key", "")),
            kind=str(item.get("kind", "part")),
            content=str(item.get("content", "")),
            version_number=version.version_number,
            content_hash=str(item.get("content_hash", content_hash(str(item.get("content", ""))))),
            source="library",
            module_version_id=version.id,
        )
        for item in version.files
    }
    return compile_design(
        version.content,
        overrides,
        file_kind="part",
        resolver=bundle.get,
    )


__all__ = [
    "LibraryPublishError",
    "can_manage_module",
    "is_system_admin",
    "list_library_modules",
    "module_latest_versions",
    "module_version",
    "module_version_stats",
    "module_versions",
    "preview_library_version",
    "publish_design",
]
