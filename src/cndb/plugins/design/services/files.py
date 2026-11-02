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

from cndb.plugins.design.models import DesignDesign, DesignDesignref, DesignDesignVersion
from cndb.plugins.design.services.dsl.compile import compile_design
from cndb.plugins.design.services.dsl.nodes import (
    BooleanCall,
    CompileResult,
    ConstraintDecl,
    FileSource,
    Instance,
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


def compile_design_file(
    db: Session,
    design: DesignDesign,
    content: str | None = None,
    *,
    pinned: dict[str, int] | None = None,
) -> CompileResult:
    """以设计文件身份编译（kind / file_id / 工作区 resolver），只走唯一入口."""
    return compile_design(
        design.content if content is None else content,
        file_kind=design.kind,
        file_id=design.id,
        resolver=build_resolver(db, design.workspace_id, pinned=pinned),
    )


def _iter_instances(items: Iterable[Instance]) -> Iterator[Instance]:
    for inst in items:
        yield inst
        if isinstance(inst, TransformCall | BooleanCall):
            yield from _iter_instances(inst.children)


def direct_use_keys(content: str) -> list[str]:
    """根文件直接 ``use`` 的 file_key 列表（按出现顺序去重）.

    覆盖顶层实例 / module 体 / system 体（module 是根文件的一部分，其实例化
    发生在根文件作用域，故 module 体内的 use 也算直接引用）。
    """
    program = parse_program(content)
    keys: list[str] = []
    for inst in _iter_instances(program.instances):
        if isinstance(inst, UseCall) and inst.file_key not in keys:
            keys.append(inst.file_key)
    for module in program.modules:
        for inst in _iter_instances(module.body):
            if isinstance(inst, UseCall) and inst.file_key not in keys:
                keys.append(inst.file_key)
    for system in program.systems:
        for inst in _iter_instances(item for item in system.body if not isinstance(item, ConstraintDecl)):
            if isinstance(inst, UseCall) and inst.file_key not in keys:
                keys.append(inst.file_key)
    return keys


def sync_refs(db: Session, design: DesignDesign, keys: Iterable[str]) -> None:
    """按直接引用重建 ``design_designref``（幂等：全删全插；自引用跳过）."""
    # ORM delete（而非 query.delete）：已加载的 ref 对象要从 identity map 正确移除，
    # 否则同主键重插会触发 SAWarning
    for ref in db.query(DesignDesignref).filter(DesignDesignref.design_id == design.id).all():
        db.delete(ref)
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
    "build_resolver",
    "compile_design_file",
    "content_hash",
    "direct_use_keys",
    "latest_version_map",
    "latest_version_number",
    "mark_referrers_stale",
    "sync_refs",
]
