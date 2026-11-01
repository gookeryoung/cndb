/** IR → three.js 几何求值（ADR 0079 D4）.
 *
 * 本模块是前端唯一消费 IR 的位置（I1：前端零解析、零求值，只把编译好的
 * 字面量 IR 落成几何）。布尔树自顶向下求值：
 * - 图元 → three 内置几何（tube 为「外圆柱 − 内圆柱」CSG 结果）；
 * - 变换栈按「先外后内」复合（ops[0] 为最外层，M = M0·M1·…·Mn）；
 * - union / difference / intersection 经 three-bvh-csg 求值（首个子实例为保留体）。
 *
 * 单位固定 mm / deg（I5）：不做任何缩放；deg → rad 仅在 rotate 一处换算。
 * 本文件只做纯几何构造（jsdom 可测），WebGL 挂载见 PreviewCanvas。
 */

import * as THREE from 'three'
import { ADDITION, Brush, Evaluator, INTERSECTION, SUBTRACTION } from 'three-bvh-csg'
import type { DesignIR, DesignIRNode, DesignPrimitiveNode, DesignTransformKind } from '@/api'

const DEG2RAD = Math.PI / 180

/** CSG 求值器（单例复用；无状态、线程安全仅限主线程渲染场景） */
let evaluator: Evaluator | null = null
function getEvaluator(): Evaluator {
  evaluator ??= new Evaluator()
  return evaluator
}

/** 把两个几何按布尔算子合并，失败（退化输入）返回 null */
export function evaluatePair(
  a: THREE.BufferGeometry,
  b: THREE.BufferGeometry,
  op: 'union' | 'difference' | 'intersection',
): THREE.BufferGeometry | null {
  const brushA = new Brush(a)
  const brushB = new Brush(b)
  brushA.updateMatrixWorld()
  brushB.updateMatrixWorld()
  const operation = op === 'union' ? ADDITION : op === 'difference' ? SUBTRACTION : INTERSECTION
  try {
    const result = getEvaluator().evaluate(brushA, brushB, operation)
    const geometry = result.geometry
    if (!geometry.getAttribute('position') || geometry.getAttribute('position').count === 0) return null
    return geometry
  } catch {
    return null
  }
}

/** 单个变换 → 矩阵（deg 语义：绕 X、再绕 Y、再绕 Z，OpenSCAD 同序） */
export function opMatrix(kind: DesignTransformKind, v: [number, number, number]): THREE.Matrix4 {
  const [x, y, z] = v
  switch (kind) {
    case 'translate':
      return new THREE.Matrix4().makeTranslation(x, y, z)
    case 'rotate': {
      // 先绕 X 再绕 Y 再绕 Z：M = Rz·Ry·Rx（列向量右乘语义）
      const rx = new THREE.Matrix4().makeRotationX(x * DEG2RAD)
      const ry = new THREE.Matrix4().makeRotationY(y * DEG2RAD)
      const rz = new THREE.Matrix4().makeRotationZ(z * DEG2RAD)
      return new THREE.Matrix4().multiplyMatrices(rz, new THREE.Matrix4().multiplyMatrices(ry, rx))
    }
    case 'scale':
      return new THREE.Matrix4().makeScale(x, y, z)
    case 'mirror': {
      // 关于法向量为 (x,y,z) 过原点平面的镜像：M = I − 2nnᵀ/(n·n)
      const d = x * x + y * y + z * z
      if (d === 0) return new THREE.Matrix4()
      return new THREE.Matrix4().set(
        1 - (2 * x * x) / d, (-2 * x * y) / d, (-2 * x * z) / d, 0,
        (-2 * y * x) / d, 1 - (2 * y * y) / d, (-2 * y * z) / d, 0,
        (-2 * z * x) / d, (-2 * z * y) / d, 1 - (2 * z * z) / d, 0,
        0, 0, 0, 1,
      )
    }
    default:
      return new THREE.Matrix4()
  }
}

/** 变换栈复合：ops[0] 为最外层，M = M0·M1·…·Mn（内层先作用于点） */
export function composeTransform(ops: Array<[DesignTransformKind, [number, number, number]]> | undefined): THREE.Matrix4 {
  const m = new THREE.Matrix4()
  for (const [kind, v] of ops ?? []) m.multiply(opMatrix(kind, v))
  return m
}

/** fn 分段数 → 高度向 / 截面辅助分段（球与环体的另一维取一半，下限 3） */
function halfSegments(fn: number): number {
  return Math.max(3, Math.round(fn / 2))
}

/** 图元节点 → 几何（六种，op 与 DSL 图元名一一对应；图元均以原点为中心） */
export function primitiveGeometry(node: DesignPrimitiveNode): THREE.BufferGeometry | null {
  let geometry: THREE.BufferGeometry | null = null
  switch (node.op) {
    case 'box':
      geometry = new THREE.BoxGeometry(node.size[0], node.size[1], node.size[2])
      break
    case 'cyl':
      // DSL 约定 cyl 沿 Z 轴：three 圆柱默认沿 Y，绕 X 旋 90° 把 Y 对到 Z
      geometry = new THREE.CylinderGeometry(node.d / 2, node.d / 2, node.h, node.fn).rotateX(Math.PI / 2)
      break
    case 'sphere':
      geometry = new THREE.SphereGeometry(node.r, node.fn, halfSegments(node.fn))
      break
    case 'cone':
      // d1 为底径（−Z 端）、d2 为顶径（+Z 端）
      geometry = new THREE.CylinderGeometry(node.d2 / 2, node.d1 / 2, node.h, node.fn).rotateX(Math.PI / 2)
      break
    case 'torus':
      // three 环体默认绕 Z 轴（XY 平面内），与机械口径一致
      geometry = new THREE.TorusGeometry(node.r, node.tube, halfSegments(node.fn), node.fn)
      break
    case 'tube':
      geometry = evaluatePair(
        new THREE.CylinderGeometry(node.od / 2, node.od / 2, node.h, node.fn).rotateX(Math.PI / 2),
        new THREE.CylinderGeometry(node.id / 2, node.id / 2, node.h, node.fn).rotateX(Math.PI / 2),
        'difference',
      )
      break
    default:
      geometry = null
  }
  if (geometry) geometry.applyMatrix4(composeTransform(node.transform?.ops))
  return geometry
}

/** IR 节点 → 几何（布尔树递归求值；空结果 / 全部子体退化时返回 null） */
export function evalNode(node: DesignIRNode): THREE.BufferGeometry | null {
  if (!('children' in node)) return primitiveGeometry(node)
  const parts: THREE.BufferGeometry[] = []
  for (const child of node.children) {
    const part = evalNode(child)
    if (part) parts.push(part)
  }
  if (parts.length === 0) return null
  let acc = parts[0]
  for (let i = 1; i < parts.length; i += 1) {
    const merged = evaluatePair(acc, parts[i], node.op)
    if (!merged) return null
    acc = merged
  }
  return acc
}

/** IR 统计（预览信息条 / 测试断言用） */
export function irStats(ir: DesignIR | null | undefined): { nodes: number; triangles: number } {
  let triangles = 0
  for (const node of ir?.nodes ?? []) {
    const geometry = evalNode(node)
    const position = geometry?.getAttribute('position')
    if (position) triangles += Math.floor(position.count / 3)
  }
  return { nodes: ir?.nodes.length ?? 0, triangles }
}

/** IR → 三维网格组（材质统一由 PreviewCanvas 提供；本函数只产几何） */
export function buildIRMeshes(ir: DesignIR | null | undefined): THREE.Mesh[] {
  const material = new THREE.MeshStandardMaterial({ color: 0x9fb4cc, metalness: 0.15, roughness: 0.55 })
  const meshes: THREE.Mesh[] = []
  for (const node of ir?.nodes ?? []) {
    const geometry = evalNode(node)
    if (!geometry) continue
    meshes.push(new THREE.Mesh(geometry, material))
  }
  return meshes
}
