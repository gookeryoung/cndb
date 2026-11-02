"""装配约束求解（ADR 0086 D4/D5）：确定性位姿传播.

输入为同一作用域内的约束声明与「实例标签 → 已展开节点」映射，输出：
- 每个约束的 IR 记录（id / type / a / b / status / 行 / 列）；
- 求解出的组件附加位姿（以最外层变换下推到该组件的全部图元节点）；
- 欠约束 / 冲突诊断所需的错误（``ConstraintError``，含行 / 列）。

求解口径（与 ADR 0086 §3 一致）：
1. ``fixed`` 锁定作者位姿；无 ``fixed`` 时取作用域内第一个被约束的组件隐式接地；
2. 以接地组件为根，按约束声明顺序 BFS 传播；两端已求解时复验；
3. 复验失败 = 冲突；两端都未接地且不连通 → 该连通分量首个组件接地；
4. 未被任何约束触达的带标签组件给欠约束警告（无标签组件保持作者位姿）。

本模块只做纯几何运算（无 IO / 无随机），保证同输入同输出（I3）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cndb.plugins.design.services.dsl.expressions import eval_expr, eval_vector
from cndb.plugins.design.services.dsl.nodes import ConstraintDecl

Vec3 = tuple[float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]

#: 求解容差（平移 / 角度，ADR 0086 §3）
TOL = 1e-6

_IDENTITY_MAT: Mat3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_ANCHOR_POINTS: dict[str, Vec3] = {
    "origin": (0.0, 0.0, 0.0),
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}
_AXES: dict[str, Vec3] = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}


class ConstraintError(Exception):
    """约束求解错误（引用缺失 / 冲突 / 过约束 / 参数非法），携带 1 基行 / 列."""

    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


@dataclass(frozen=True, slots=True)
class Pose:
    """刚体位姿：``p_world = rotation · p_local + translation``."""

    rotation: Mat3
    translation: Vec3


IDENTITY_POSE = Pose(rotation=_IDENTITY_MAT, translation=(0.0, 0.0, 0.0))


# ── 向量 / 矩阵 ───────────────────────────────────────────


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3) -> Vec3 | None:
    n = _norm(a)
    if n <= 1e-12:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _mat_vec(m: Mat3, v: Vec3) -> Vec3:
    return (_dot(m[0], v), _dot(m[1], v), _dot(m[2], v))


def _mat_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(  # type: ignore[return-value]
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def _apply(pose: Pose, point: Vec3) -> Vec3:
    return _add(_mat_vec(pose.rotation, point), pose.translation)


def _direction(pose: Pose, axis: Vec3) -> Vec3 | None:
    return _normalize(_mat_vec(pose.rotation, axis))


def _compose(outer: Pose, inner: Pose) -> Pose:
    return Pose(
        rotation=_mat_mul(outer.rotation, inner.rotation),
        translation=_add(_mat_vec(outer.rotation, inner.translation), outer.translation),
    )


def _rotation(axis: Vec3, angle_rad: float) -> Mat3:
    """罗德里格斯旋转（axis 先归一化）."""
    unit = _normalize(axis) or (0.0, 0.0, 1.0)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    k = 1.0 - c
    x, y, z = unit
    return (
        (c + x * x * k, x * y * k - z * s, x * z * k + y * s),
        (y * x * k + z * s, c + y * y * k, y * z * k - x * s),
        (z * x * k - y * s, z * y * k + x * s, c + z * z * k),
    )


def _any_perpendicular(v: Vec3) -> Vec3:
    """确定性取一个与 v 垂直的非零向量（按 +X / +Y / +Z 顺序试探）."""
    for candidate in _AXES.values():
        axis = _cross(v, candidate)
        if _norm(axis) > 1e-9:
            return axis
    return (0.0, 0.0, 1.0)  # pragma: no cover - 单位向量必有垂直轴


def _rotation_between(source: Vec3, target: Vec3) -> Mat3:
    """把方向 source 转到 target 的最短弧旋转."""
    u = _normalize(source) or (0.0, 0.0, 1.0)
    v = _normalize(target) or (0.0, 0.0, 1.0)
    cosine = max(-1.0, min(1.0, _dot(u, v)))
    axis = _cross(u, v)
    sine = _norm(axis)
    if sine <= 1e-12:
        if cosine > 0:
            return _IDENTITY_MAT
        return _rotation(_any_perpendicular(u), math.pi)
    return _rotation(axis, math.atan2(sine, cosine))


def _euler_zyx(m: Mat3) -> Vec3:
    """旋转矩阵 → (rx, ry, rz) 角度；与前端 ``M = Rz·Ry·Rx`` 口径一致."""
    sin_beta = max(-1.0, min(1.0, -m[2][0]))
    beta = math.asin(sin_beta)
    cos_beta = math.cos(beta)
    if abs(cos_beta) > 1e-9:
        alpha = math.atan2(m[2][1], m[2][2])
        gamma = math.atan2(m[1][0], m[0][0])
    else:  # 万向节锁：固定 alpha=0，gamma 由其余项决定
        alpha = 0.0
        gamma = math.atan2(-m[0][1], m[1][1])
    return (math.degrees(alpha), math.degrees(beta), math.degrees(gamma))


# ── 作者位姿（变换栈 → 刚体位姿） ────────────────────


def _op_pose(kind: str, v: Sequence[float]) -> Pose:
    """单个变换 → 位姿（rotate 与前端同序：绕 X、再绕 Y、再绕 Z）."""
    vec: Vec3 = (float(v[0]), float(v[1]), float(v[2]))
    if kind == "translate":
        return Pose(rotation=_IDENTITY_MAT, translation=vec)
    if kind == "rotate":
        rx = _rotation(_AXES["x"], math.radians(vec[0]))
        ry = _rotation(_AXES["y"], math.radians(vec[1]))
        rz = _rotation(_AXES["z"], math.radians(vec[2]))
        return Pose(rotation=_mat_mul(rz, _mat_mul(ry, rx)), translation=(0.0, 0.0, 0.0))
    if kind == "scale":
        return Pose(rotation=((vec[0], 0.0, 0.0), (0.0, vec[1], 0.0), (0.0, 0.0, vec[2])), translation=(0.0, 0.0, 0.0))
    # mirror：反射矩阵（非刚体，但位姿复验按点映射仍成立）
    d = _dot(vec, vec)
    if d == 0:
        return IDENTITY_POSE
    x, y, z = vec
    return Pose(
        rotation=(
            (1 - 2 * x * x / d, -2 * x * y / d, -2 * x * z / d),
            (-2 * y * x / d, 1 - 2 * y * y / d, -2 * y * z / d),
            (-2 * z * x / d, -2 * z * y / d, 1 - 2 * z * z / d),
        ),
        translation=(0.0, 0.0, 0.0),
    )


def authored_pose(ops: Sequence[tuple[str, Sequence[float]]]) -> Pose:
    """变换栈（ops[0] 为最外层）复合为作者位姿."""
    pose = IDENTITY_POSE
    for kind, v in ops:
        pose = _compose(pose, _op_pose(kind, v))
    return pose


def apply_pose(nodes: Iterable[dict[str, Any]], pose: Pose) -> None:
    """把求解位姿作为最外层变换下推到全部图元叶子（原地修改）."""
    if pose.rotation == _IDENTITY_MAT and pose.translation == (0.0, 0.0, 0.0):
        return
    ops: list[list[Any]] = [[kind, list(v)] for kind, v in _pose_ops(pose)]
    for node in nodes:
        _prepend_ops(node, ops)


def _pose_ops(pose: Pose) -> tuple[tuple[str, Vec3], ...]:
    """位姿 → 最外层变换序列（translate · rotate）."""
    rx, ry, rz = _euler_zyx(pose.rotation)
    ops: list[tuple[str, Vec3]] = []
    if any(abs(v) > 1e-12 for v in pose.translation):
        ops.append(("translate", pose.translation))
    if any(abs(v) > 1e-12 for v in (rx, ry, rz)):
        ops.append(("rotate", (rx, ry, rz)))
    return tuple(ops)


def _prepend_ops(node: dict[str, Any], ops: list[list[Any]]) -> None:
    if "children" in node:
        for child in node["children"]:
            _prepend_ops(child, ops)
        return
    existing = node.get("transform")
    merged = [list(item) for item in (existing or {}).get("ops", [])]
    node["transform"] = {"ops": [*ops, *merged]}


# ── 约束求解 ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Anchor:
    point: Vec3
    axis: Vec3 | None
    line: int
    col: int


def _anchor(ref_anchor: str, line: int, col: int) -> _Anchor:
    return _Anchor(point=_ANCHOR_POINTS[ref_anchor], axis=_AXES.get(ref_anchor), line=line, col=col)


def _compose_label_pose(authored: Pose, solved: Pose) -> Pose:
    return _compose(solved, authored)


def _world(component: Pose, anchor: _Anchor) -> tuple[Vec3, Vec3 | None]:
    point = _apply(component, anchor.point)
    axis = _direction(component, anchor.axis) if anchor.axis is not None else None
    return point, axis


def _check_spec(decl: ConstraintDecl) -> None:
    """校验约束参数组合（类型 → 必需引用 / 数值键）."""
    has_a = "a" in decl.refs
    has_b = "b" in decl.refs
    bad = sorted(set(decl.values) - {"offset", "value"})
    if bad:
        raise ConstraintError(f"约束 '{decl.id}' 不支持参数 '{bad[0]}'（可用：offset / value）", decl.line, decl.col)
    if decl.kind == "fixed":
        if not has_a or has_b:
            raise ConstraintError(f"约束 '{decl.id}'（fixed）只接受 a = 实例.基准", decl.line, decl.col)
        if decl.values:
            raise ConstraintError(f"约束 '{decl.id}'（fixed）不接受数值参数", decl.line, decl.col)
        return
    if not (has_a and has_b):
        raise ConstraintError(f"约束 '{decl.id}'（{decl.kind}）需要 a 与 b 两个引用", decl.line, decl.col)
    if decl.kind in ("concentric", "angle"):
        for key in ("a", "b"):
            if decl.refs[key].anchor == "origin":
                raise ConstraintError(
                    f"约束 '{decl.id}'（{decl.kind}）的 {key} 须为轴向基准（x / y / z）",
                    decl.refs[key].line,
                    decl.refs[key].col,
                )
    if decl.kind in ("distance", "angle") and "value" not in decl.values:
        raise ConstraintError(f"约束 '{decl.id}'（{decl.kind}）缺少 value", decl.line, decl.col)


def _validate_labels(decl: ConstraintDecl, labels: Mapping[str, Sequence[dict[str, Any]]]) -> None:
    for ref in decl.refs.values():
        if ref.label not in labels:
            raise ConstraintError(
                f"约束 '{decl.id}' 引用了未声明的实例标签 '{ref.label}'",
                ref.line,
                ref.col,
            )


def _point(decl: ConstraintDecl, env: Mapping[str, float]) -> Vec3:
    """``offset`` 数值参数 → 三维向量（缺省零向量）."""
    if "offset" not in decl.values:
        return (0.0, 0.0, 0.0)
    return eval_vector(decl.values["offset"], dict(env))


def _scalar(decl: ConstraintDecl, key: str, env: Mapping[str, float]) -> float:
    return eval_expr(decl.values[key], dict(env))


def _solve_unknown(
    decl: ConstraintDecl,
    known: str,
    unknown: str,
    poses: Mapping[str, Pose],
    authored: Mapping[str, Pose],
    env: Mapping[str, float],
) -> Pose:
    """已知一端位姿，解另一端（返回「附加位姿」，作者位姿已并入锚点映射）."""
    known_anchor = _anchor(decl.refs[known].anchor, decl.refs[known].line, decl.refs[known].col)
    unknown_anchor = _anchor(decl.refs[unknown].anchor, decl.refs[unknown].line, decl.refs[unknown].col)
    known_pose = poses[decl.refs[known].label]
    known_point, known_axis = _world(known_pose, known_anchor)
    # 未知端的局部锚点先经作者位姿映射：unknown_local = authored · anchor
    local_point = _apply(authored[decl.refs[unknown].label], unknown_anchor.point)
    local_axis = (
        _normalize(_mat_vec(authored[decl.refs[unknown].label].rotation, unknown_anchor.axis))
        if unknown_anchor.axis
        else None
    )

    if decl.kind == "coincident":
        target = _add(known_point, _point(decl, env))
        return Pose(rotation=_IDENTITY_MAT, translation=_sub(target, local_point))
    if decl.kind == "distance":
        value = _scalar(decl, "value", env)
        direction = _normalize(_sub(local_point, known_point))
        if direction is None:
            direction = (0.0, 0.0, 1.0)
        target = _add(known_point, _scale(direction, value))
        return Pose(rotation=_IDENTITY_MAT, translation=_sub(target, local_point))
    if decl.kind == "concentric":
        if known_axis is None or local_axis is None:  # pragma: no cover - _check_spec 已拦截
            raise ConstraintError(f"约束 '{decl.id}'（concentric）缺少轴向基准", decl.line, decl.col)
        rotation = _rotation_between(local_axis, known_axis)
        return Pose(rotation=rotation, translation=_sub(known_point, _mat_vec(rotation, local_point)))
    if decl.kind == "angle":
        if known_axis is None or local_axis is None:  # pragma: no cover - _check_spec 已拦截
            raise ConstraintError(f"约束 '{decl.id}'（angle）缺少轴向基准", decl.line, decl.col)
        value = _scalar(decl, "value", env)
        target_axis = _mat_vec(_rotation(_any_perpendicular(known_axis), math.radians(value)), known_axis)
        rotation = _rotation_between(local_axis, target_axis)
        return Pose(rotation=rotation, translation=(0.0, 0.0, 0.0))
    raise ConstraintError(f"未知约束类型 '{decl.kind}'", decl.line, decl.col)  # pragma: no cover


def _verify(
    decl: ConstraintDecl,
    poses: Mapping[str, Pose],
    authored: Mapping[str, Pose],
    env: Mapping[str, float],
) -> None:
    """两端已求解后复验约束；不满足即冲突（带约束 id / 行 / 列）."""
    if decl.kind == "fixed":
        pose = poses[decl.refs["a"].label]
        if _norm(_sub(pose.translation, (0.0, 0.0, 0.0))) > TOL or any(
            abs(pose.rotation[i][j] - _IDENTITY_MAT[i][j]) > TOL for i in range(3) for j in range(3)
        ):
            raise ConstraintError(f"约束 '{decl.id}'（fixed）与其它约束冲突", decl.line, decl.col)
        return
    a_anchor = _anchor(decl.refs["a"].anchor, decl.refs["a"].line, decl.refs["a"].col)
    b_anchor = _anchor(decl.refs["b"].anchor, decl.refs["b"].line, decl.refs["b"].col)
    a_point, a_axis = _world(_compose_label_pose(authored[decl.refs["a"].label], poses[decl.refs["a"].label]), a_anchor)
    b_point, b_axis = _world(_compose_label_pose(authored[decl.refs["b"].label], poses[decl.refs["b"].label]), b_anchor)
    if decl.kind == "coincident":
        target = _add(a_point, _point(decl, env))
        if _norm(_sub(b_point, target)) > TOL:
            raise ConstraintError(f"约束 '{decl.id}'（coincident）与其它约束冲突", decl.line, decl.col)
    elif decl.kind == "distance":
        value = _scalar(decl, "value", env)
        if abs(_norm(_sub(b_point, a_point)) - value) > TOL:
            raise ConstraintError(f"约束 '{decl.id}'（distance）与其它约束冲突", decl.line, decl.col)
    elif decl.kind == "concentric":
        if a_axis is None or b_axis is None:  # pragma: no cover - _check_spec 已拦截
            raise ConstraintError(f"约束 '{decl.id}'（concentric）缺少轴向基准", decl.line, decl.col)
        if _norm(_cross(a_axis, b_axis)) > TOL:
            raise ConstraintError(f"约束 '{decl.id}'（concentric）轴不平行", decl.line, decl.col)
        normal = _cross(_sub(b_point, a_point), a_axis)
        if _norm(normal) > TOL:
            raise ConstraintError(f"约束 '{decl.id}'（concentric）轴线不共线", decl.line, decl.col)
    elif decl.kind == "angle":
        if a_axis is None or b_axis is None:  # pragma: no cover - _check_spec 已拦截
            raise ConstraintError(f"约束 '{decl.id}'（angle）缺少轴向基准", decl.line, decl.col)
        cosine = max(-1.0, min(1.0, _dot(a_axis, b_axis)))
        angle = math.degrees(math.acos(cosine))
        value = _scalar(decl, "value", env)
        if abs(angle - value) > TOL:
            raise ConstraintError(f"约束 '{decl.id}'（angle）与其它约束冲突", decl.line, decl.col)


def solve_constraints(
    constraints: Sequence[ConstraintDecl],
    labels: Mapping[str, Sequence[dict[str, Any]]],
    ordered_labels: Sequence[str],
    authored: Mapping[str, Pose],
    env: Mapping[str, float],
) -> tuple[list[dict[str, Any]], list[tuple[str, int, int, str]]]:
    """求解一个作用域的约束，返回 (IR 约束记录, 警告列表) 并原地下推位姿.

    警告项为 ``(code, line, col, message)``；错误抛 ``ConstraintError``。
    """
    if not constraints:
        return [], []

    seen_ids: set[str] = set()
    for decl in constraints:
        if decl.id in seen_ids:
            raise ConstraintError(f"重复的约束 id '{decl.id}'", decl.line, decl.col)
        seen_ids.add(decl.id)
        _check_spec(decl)
        _validate_labels(decl, labels)

    poses: dict[str, Pose] = {}
    auto_grounded: set[str] = set()
    warnings: list[tuple[str, int, int, str]] = []

    for decl in constraints:
        if decl.kind != "fixed":
            continue
        label = decl.refs["a"].label
        if label in poses and not _is_identity(poses[label]):
            raise ConstraintError(f"约束 '{decl.id}'（fixed）与其它约束冲突", decl.line, decl.col)
        poses[label] = IDENTITY_POSE

    if not poses:
        candidates = _constraint_labels(constraints, ordered_labels)
        if candidates:
            first = candidates[0]
            poses[first] = IDENTITY_POSE
            auto_grounded.add(first)
            warnings.append(
                (
                    "constraint_underconstrained",
                    constraints[0].line,
                    constraints[0].col,
                    f"没有 fixed 约束，已隐式接地组件 '{first}'",
                )
            )

    changed = True
    while changed:
        changed = False
        for decl in constraints:
            if decl.kind == "fixed":
                continue
            a_label = decl.refs["a"].label
            b_label = decl.refs["b"].label
            if a_label == b_label:
                raise ConstraintError(f"约束 '{decl.id}' 的 a 与 b 指向同一组件", decl.line, decl.col)
            if a_label in poses and b_label in poses:
                _verify(decl, poses, authored, env)
                continue
            if a_label in poses:
                poses[b_label] = _solve_unknown(decl, "a", "b", poses, authored, env)
            elif b_label in poses:
                poses[a_label] = _solve_unknown(decl, "b", "a", poses, authored, env)
            else:
                # 连通分量两端都未接地：取 a 端接地（确定性）
                poses[a_label] = IDENTITY_POSE
                auto_grounded.add(a_label)
                warnings.append(
                    (
                        "constraint_underconstrained",
                        decl.line,
                        decl.col,
                        f"约束分量未接地，已隐式接地组件 '{a_label}'",
                    )
                )
            changed = True

    # 两端都求解后仍需复验（上面循环在两端已知时已复验；此处兜底固定约束）
    for decl in constraints:
        if decl.kind == "fixed":
            _verify(decl, poses, authored, env)
            continue
        if decl.refs["a"].label in poses and decl.refs["b"].label in poses:
            _verify(decl, poses, authored, env)

    for label in ordered_labels:
        if label not in poses:
            warnings.append(
                (
                    "constraint_underconstrained",
                    0,
                    0,
                    f"组件 '{label}' 未被任何约束定位（保持作者位姿）",
                )
            )

    entries: list[dict[str, Any]] = []
    for decl in constraints:
        entry_labels = {ref.label for ref in decl.refs.values()}
        status = "warning" if entry_labels & auto_grounded else "ok"
        entry: dict[str, Any] = {
            "id": decl.id,
            "type": decl.kind,
            "a": _ref_text(decl, "a"),
            "status": status,
            "line": decl.line,
            "col": decl.col,
        }
        if "b" in decl.refs:
            entry["b"] = _ref_text(decl, "b")
        entries.append(entry)

    for label, pose in poses.items():
        apply_pose(labels.get(label, ()), pose)
    return entries, warnings


def _ref_text(decl: ConstraintDecl, key: str) -> str:
    ref = decl.refs[key]
    return f"{ref.label}.{ref.anchor}"


def _constraint_labels(constraints: Sequence[ConstraintDecl], ordered_labels: Sequence[str]) -> list[str]:
    """按作用域内组件出现顺序返回被约束到的标签（隐式接地用）."""
    referenced = {ref.label for decl in constraints for ref in decl.refs.values()}
    return [label for label in ordered_labels if label in referenced]


def _is_identity(pose: Pose) -> bool:
    return pose.translation == (0.0, 0.0, 0.0) and all(
        abs(pose.rotation[i][j] - _IDENTITY_MAT[i][j]) <= TOL for i in range(3) for j in range(3)
    )


__all__ = [
    "IDENTITY_POSE",
    "ConstraintError",
    "Pose",
    "apply_pose",
    "authored_pose",
    "solve_constraints",
]
