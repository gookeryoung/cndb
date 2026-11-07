"""设计文件库的路由层支撑服务（ADR 0086 P1）.

职责（路由层薄壳，判定只进 ``compile_design`` 唯一入口）：

- ``content_hash``：原文 SHA-256（ETag / 依赖快照用）；
- ``latest_version_map``：批量取设计当前最新版本号；
- ``build_resolver``：按 ``file_key`` 构建 ``compile_design`` 的 resolver 回调
  （同工作区、未软删；``pinned`` 支持按版本快照复现历史编译，I5）；
- ``compile_design_file``：以设计文件身份编译（kind / file_id / resolver）；
- ``direct_use_keys``：从 AST 提取根文件直接 ``use`` 的 file_key（design_designref
  是**直接**引用索引，闭包里的传递依赖不落表）；
- ``sync_refs``：按直接引用重建 ``design_designref``；
- ``mark_referrers_stale``：被引用文件保存后沿反向引用图传播 ``dependencies_stale``。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator

from sqlalchemy.orm import Session

from cndb.plugins.design.models import (
    LIBRARY_VISIBILITY_PUBLIC,
    DesignDesign,
    DesignDesignref,
    DesignDesignVersion,
    DesignLibraryModule,
    DesignLibraryref,
    DesignLibraryVersion,
)
from cndb.plugins.design.services.dsl.compile import compile_design
from cndb.plugins.design.services.dsl.nodes import (
    BooleanCall,
    CompileResult,
    ConstraintDecl,
    FileSource,
    Instance,
    LibraryRef,
    LibrarySource,
    TransformCall,
    UseCall,
)
from cndb.plugins.design.services.dsl.parse import parse_program


def content_hash(content: str) -> str:
    """原文 SHA-256 十六进制（ETag / 依赖快照 content_hash 的统一口径）."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def latest_version_map(db: Session, design_ids: Iterable[int]) -> dict[int, int]:
    """批量取设计当前最新版本号（无版本返回 0）."""
    ids = list(design_ids)
    if not ids:
        return {}
    rows = (
        db.query(DesignDesignVersion.design_id, DesignDesignVersion.version_number)
        .filter(DesignDesignVersion.design_id.in_(ids))
        .order_by(DesignDesignVersion.design_id, DesignDesignVersion.version_number.desc())
        .all()
    )
    result: dict[int, int] = {}
    for design_id, number in rows:
        result.setdefault(int(design_id), int(number))
    return result


def latest_version_number(db: Session, design_id: int) -> int:
    """单个设计的最新版本号（无版本返回 0）."""
    return latest_version_map(db, [design_id]).get(design_id, 0)


def build_resolver(
    db: Session,
    workspace_id: int,
    *,
    pinned: dict[str, int] | None = None,
) -> Callable[[str], FileSource | None]:
    """构建 ``compile_design`` 的 resolver：file_key → 同工作区文件快照.

    ``pinned``（file_key → version_number）为版本依赖快照复现模式：只解析快照
    里记录的版本（内容取该版本原文），快照外的 key 视为缺失（I5：历史按快照
    编译，缺依赖显式报错而非取最新）。
    """
    pinned = pinned or {}
    if pinned:
        rows = (
            db.query(DesignDesign, DesignDesignVersion)
            .join(DesignDesignVersion, DesignDesignVersion.design_id == DesignDesign.id)
            .filter(
                DesignDesign.workspace_id == workspace_id,
                DesignDesign.is_deleted.is_(False),
                DesignDesign.file_key.in_(pinned.keys()),
            )
            .all()
        )
        by_key: dict[str, FileSource] = {}
        for design, version in rows:
            if pinned.get(design.file_key) != version.version_number:
                continue
            by_key[design.file_key] = FileSource(
                file_id=design.id,
                file_key=design.file_key,
                kind=design.kind,
                content=version.content,
                version_number=version.version_number,
                content_hash=content_hash(version.content),
            )
        return by_key.get

    cache: dict[str, FileSource | None] = {}

    def resolve(file_key: str) -> FileSource | None:
        if file_key not in cache:
            row = (
                db.query(DesignDesign)
                .filter(
                    DesignDesign.workspace_id == workspace_id,
                    DesignDesign.file_key == file_key,
                    DesignDesign.is_deleted.is_(False),
                )
                .first()
            )
            if row is None:
                cache[file_key] = None
            else:
                cache[file_key] = FileSource(
                    file_id=row.id,
                    file_key=row.file_key,
                    kind=row.kind,
                    content=row.content,
                    version_number=latest_version_number(db, row.id),
                    content_hash=content_hash(row.content),
                )
        return cache[file_key]

    return resolve


def build_library_resolver(
    db: Session,
    workspace_id: int,
    *,
    granted_keys: frozenset[tuple[str, int]] = frozenset(),
) -> Callable[[str, int], LibrarySource | None]:
    """构建复用模块解析器：``(module_key, version)`` → 版本快照（ADR 0118 C2/C4）.

    权限口径（D4/D8）：``public`` 任意工作区可解析；``workspace`` 仅所有者工作区；
    归档模块只对 ``granted_keys``（已落库的既有引用）放行。无权访问统一返回
    ``None``，由编译器报「未找到」且不泄露私有 / 归档原因。
    """
    cache: dict[tuple[str, int], LibrarySource | None] = {}

    def resolve(module_key: str, version_number: int) -> LibrarySource | None:
        key = (module_key, version_number)
        if key in cache:
            return cache[key]
        module = db.query(DesignLibraryModule).filter(DesignLibraryModule.module_key == module_key).first()
        granted = key in granted_keys
        if module is None:
            cache[key] = None
            return None
        visible = module.visibility == LIBRARY_VISIBILITY_PUBLIC or module.owner_workspace_id == workspace_id
        if not (visible or granted) or (module.is_archived and not granted):
            cache[key] = None
            return None
        version = (
            db.query(DesignLibraryVersion)
            .filter(
                DesignLibraryVersion.module_id == module.id,
                DesignLibraryVersion.version_number == version_number,
            )
            .first()
        )
        if version is None:
            cache[key] = None
            return None
        files = tuple(
            FileSource(
                file_id=0,
                file_key=str(item.get("file_key", "")),
                kind=str(item.get("kind", "part")),
                content=str(item.get("content", "")),
                version_number=version.version_number,
                content_hash=str(item.get("content_hash", content_hash(str(item.get("content", ""))))),
                source="library",
                module_id=module.id,
                module_version_id=version.id,
                module_key=module.module_key,
            )
            for item in version.files
        )
        source = LibrarySource(
            module_id=module.id,
            module_version_id=version.id,
            module_key=module.module_key,
            version_number=version.version_number,
            content=version.content,
            content_hash=version.content_hash,
            bundle_hash=version.bundle_hash,
            files=files,
            params=tuple(version.params),
        )
        cache[key] = source
        return source

    return resolve


def library_grants(db: Session, design_id: int) -> frozenset[tuple[str, int]]:
    """既有引用授权集合：``(module_key, version_number)``，用于转私有 / 归档后继续编译."""
    rows = (
        db.query(DesignLibraryModule.module_key, DesignLibraryVersion.version_number)
        .select_from(DesignLibraryref)
        .join(DesignLibraryVersion, DesignLibraryVersion.id == DesignLibraryref.module_version_id)
        .join(DesignLibraryModule, DesignLibraryModule.id == DesignLibraryref.module_id)
        .filter(DesignLibraryref.design_id == design_id)
        .all()
    )
    return frozenset((str(module_key), int(version_number)) for module_key, version_number in rows)


def compile_design_file(
    db: Session,
    design: DesignDesign,
    content: str | None = None,
    *,
    pinned: dict[str, int] | None = None,
    granted_library_keys: frozenset[tuple[str, int]] | None = None,
    allow_library: bool = True,
) -> CompileResult:
    """以设计文件身份编译（kind / file_id / 工作区 resolver / 库解析器），只走唯一入口."""
    library_resolver = (
        build_library_resolver(
            db,
            design.workspace_id,
            granted_keys=library_grants(db, design.id) if granted_library_keys is None else granted_library_keys,
        )
        if allow_library
        else None
    )
    return compile_design(
        design.content if content is None else content,
        file_kind=design.kind,
        file_id=design.id,
        resolver=build_resolver(db, design.workspace_id, pinned=pinned),
        library_resolver=library_resolver,
    )


def _iter_instances(items: Iterable[Instance]) -> Iterator[Instance]:
    for inst in items:
        yield inst
        if isinstance(inst, TransformCall | BooleanCall):
            yield from _iter_instances(inst.children)


def direct_use_calls(content: str) -> list[UseCall]:
    """根文件直接 ``use`` 调用（按出现顺序，含重复）.

    覆盖顶层实例 / module 体 / system 体（module 是根文件的一部分，其实例化
    发生在根文件作用域，故 module 体内的 use 也算直接引用）。
    """
    program = parse_program(content)
    calls = [inst for inst in _iter_instances(program.instances) if isinstance(inst, UseCall)]
    for module in program.modules:
        calls.extend(inst for inst in _iter_instances(module.body) if isinstance(inst, UseCall))
    for system in program.systems:
        calls.extend(
            inst
            for inst in _iter_instances(item for item in system.body if not isinstance(item, ConstraintDecl))
            if isinstance(inst, UseCall)
        )
    return calls


def direct_use_keys(content: str) -> list[str]:
    """根文件直接引用的同工作区文件 key（按出现顺序去重；库引用不计入）."""
    keys: list[str] = []
    for call in direct_use_calls(content):
        if call.library is None and call.file_key not in keys:
            keys.append(call.file_key)
    return keys


def direct_library_refs(content: str) -> list[LibraryRef]:
    """根文件直接引用的复用模块（按出现顺序去重）."""
    refs: list[LibraryRef] = []
    for call in direct_use_calls(content):
        if call.library is not None and call.library not in refs:
            refs.append(call.library)
    return refs


def sync_refs(
    db: Session,
    design: DesignDesign,
    keys: Iterable[str],
    library_refs: Iterable[LibraryRef] = (),
) -> None:
    """按直接引用重建 ``design_designref`` / ``design_libraryref``（幂等：全删全插）."""
    # ORM delete（而非 query.delete）：已加载的 ref 对象要从 identity map 正确移除，
    # 否则同主键重插会触发 SAWarning
    for ref in db.query(DesignDesignref).filter(DesignDesignref.design_id == design.id).all():
        db.delete(ref)
    for lib_ref in db.query(DesignLibraryref).filter(DesignLibraryref.design_id == design.id).all():
        db.delete(lib_ref)
    db.flush()
    rows = (
        db.query(DesignDesign.id)
        .filter(
            DesignDesign.workspace_id == design.workspace_id,
            DesignDesign.is_deleted.is_(False),
            DesignDesign.file_key.in_(list(keys)),
        )
        .all()
    )
    for (target_id,) in rows:
        if target_id == design.id:
            continue
        db.add(DesignDesignref(workspace_id=design.workspace_id, design_id=design.id, target_design_id=target_id))
    for lib_ref in library_refs:
        row = (
            db.query(DesignLibraryModule.id, DesignLibraryVersion.id)
            .join(DesignLibraryVersion, DesignLibraryVersion.module_id == DesignLibraryModule.id)
            .filter(
                DesignLibraryModule.module_key == lib_ref.module_key,
                DesignLibraryVersion.version_number == lib_ref.version_number,
            )
            .first()
        )
        if row is None:
            continue
        db.add(
            DesignLibraryref(
                workspace_id=design.workspace_id,
                design_id=design.id,
                module_id=int(row[0]),
                module_version_id=int(row[1]),
            )
        )


def mark_referrers_stale(db: Session, design_id: int) -> None:
    """沿反向引用图传播 ``dependencies_stale=True``（直接 + 传递引用方）.

    BFS：从被保存文件出发，把每一层引用方标记 stale 后继续向外扩散；
    已保存文件自身不标记（它刚以最新依赖落库）。
    """
    visited = {design_id}
    frontier = [design_id]
    while frontier:
        rows = (
            db.query(DesignDesignref.design_id)
            .filter(
                DesignDesignref.target_design_id.in_(frontier),
                DesignDesignref.design_id.not_in(visited),
            )
            .all()
        )
        referrer_ids = [int(row[0]) for row in rows]
        if not referrer_ids:
            break
        db.query(DesignDesign).filter(DesignDesign.id.in_(referrer_ids)).update(
            {DesignDesign.dependencies_stale: True}, synchronize_session=False
        )
        visited.update(referrer_ids)
        frontier = referrer_ids


__all__ = [
    "build_library_resolver",
    "build_resolver",
    "compile_design_file",
    "content_hash",
    "direct_library_refs",
    "direct_use_calls",
    "direct_use_keys",
    "latest_version_map",
    "latest_version_number",
    "library_grants",
    "mark_referrers_stale",
    "sync_refs",
]
