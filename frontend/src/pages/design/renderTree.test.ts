/** renderTree 测试 —— IR 分派 / 变换矩阵 / 布尔求值（ADR 0079 D4）.
 *
 * jsdom 下只测纯几何构造（three / three-bvh-csg 均为纯 JS 求值，
 * 不需要 WebGL 上下文）；WebGL 挂载由 e2e 覆盖。
 */

import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import type { DesignIR, DesignPrimitiveNode } from '@/api'
import {
  buildIRMeshes, composeTransform, evalNode, irStats, opMatrix, primitiveGeometry,
} from './renderTree'

/** 变换矩阵应用到点，断言近似相等 */
function applied(matrix: THREE.Matrix4, point: [number, number, number]): [number, number, number] {
  const v = new THREE.Vector3(...point).applyMatrix4(matrix)
  return [v.x, v.y, v.z]
}

function close(actual: [number, number, number], expected: [number, number, number]) {
  expect(actual[0]).toBeCloseTo(expected[0], 6)
  expect(actual[1]).toBeCloseTo(expected[1], 6)
  expect(actual[2]).toBeCloseTo(expected[2], 6)
}

describe('opMatrix 变换口径', () => {
  it('translate 平移', () => {
    close(applied(opMatrix('translate', [1, 2, 3]), [0, 0, 0]), [1, 2, 3])
  })

  it('rotate 用 deg：绕 Z 转 90° 把 +X 转到 +Y', () => {
    close(applied(opMatrix('rotate', [0, 0, 90]), [10, 0, 0]), [0, 10, 0])
  })

  it('rotate 按 X→Y→Z 顺序：先绕 X 90° 再绕 Y 90°（组合后非交换可分辨）', () => {
    // 先 X90：+Y→+Z；再 Y90：+Z→+X ⇒ +Y 最终落到 +X
    close(applied(opMatrix('rotate', [90, 90, 0]), [0, 1, 0]), [1, 0, 0])
  })

  it('scale 各轴独立', () => {
    close(applied(opMatrix('scale', [2, 3, 4]), [1, 1, 1]), [2, 3, 4])
  })

  it('mirror([1,0,0]) 翻转 X', () => {
    close(applied(opMatrix('mirror', [1, 0, 0]), [5, 6, 7]), [-5, 6, 7])
  })

  it('mirror([1,-1,0]) 沿 x=y 面翻转：X↔Y 互换', () => {
    close(applied(opMatrix('mirror', [1, -1, 0]), [3, 7, 9]), [7, 3, 9])
  })

  it('mirror([1,1,0]) 沿 x+y=0 面翻转：p - 2(p·n̂)n̂', () => {
    close(applied(opMatrix('mirror', [1, 1, 0]), [3, 7, 9]), [-7, -3, 9])
  })

  it('mirror 零向量为单位阵（不产生 NaN）', () => {
    close(applied(opMatrix('mirror', [0, 0, 0]), [1, 2, 3]), [1, 2, 3])
  })
})

describe('composeTransform 变换栈', () => {
  it('ops[0] 为最外层：先作用内层（OpenSCAD 语义）', () => {
    // translate 外、rotate 内：先绕 Z 转 90°，再平移
    const m = composeTransform([
      ['translate', [10, 0, 0]],
      ['rotate', [0, 0, 90]],
    ])
    close(applied(m, [1, 0, 0]), [10, 1, 0])
  })

  it('无变换时为单位阵', () => {
    close(applied(composeTransform(undefined), [1, 2, 3]), [1, 2, 3])
  })
})

describe('primitiveGeometry 图元分派', () => {
  it('box 尺寸生效且无变换时位于原点', () => {
    const geometry = primitiveGeometry({ op: 'box', size: [80, 40, 12] })!
    const box = new THREE.Box3().setFromBufferAttribute(geometry.getAttribute('position') as THREE.BufferAttribute)
    expect(box.min.x).toBeCloseTo(-40, 6)
    expect(box.min.y).toBeCloseTo(-20, 6)
    expect(box.min.z).toBeCloseTo(-6, 6)
  })

  it('cyl 沿 Z 轴：高度落在 Z 向', () => {
    const geometry = primitiveGeometry({ op: 'cyl', d: 8, h: 14, fn: 32 })!
    const box = new THREE.Box3().setFromBufferAttribute(geometry.getAttribute('position') as THREE.BufferAttribute)
    expect(box.max.z).toBeCloseTo(7, 4)
    expect(box.max.x).toBeCloseTo(4, 4)
  })

  it('sphere 半径生效', () => {
    const geometry = primitiveGeometry({ op: 'sphere', r: 5, fn: 32 })!
    const box = new THREE.Box3().setFromBufferAttribute(geometry.getAttribute('position') as THREE.BufferAttribute)
    expect(box.max.x).toBeCloseTo(5, 4)
  })

  it('图元携带变换栈时被下推应用', () => {
    const geometry = primitiveGeometry({
      op: 'box',
      size: [10, 10, 10],
      transform: { ops: [['translate', [40, 20, -1]]] },
    })
    expect(geometry).not.toBeNull()
    const box = new THREE.Box3().setFromBufferAttribute(geometry!.getAttribute('position') as THREE.BufferAttribute)
    expect(box.min.x).toBeCloseTo(35, 4)
    expect(box.min.z).toBeCloseTo(-6, 4)
  })

  it('tube（od>id）产出中空几何：外径 / 内径边界都在', () => {
    const geometry = primitiveGeometry({ op: 'tube', od: 20, id: 10, h: 5, fn: 32 })!
    expect(geometry).not.toBeNull()
    const xs = (geometry.getAttribute('position') as THREE.BufferAttribute).array as ArrayLike<number>
    let maxR = 0
    let minR = Infinity
    for (let i = 0; i < xs.length; i += 3) {
      const r = Math.hypot(xs[i]!, xs[i + 1]!)
      maxR = Math.max(maxR, r)
      minR = Math.min(minR, r)
    }
    expect(maxR).toBeCloseTo(10, 4)
    expect(minR).toBeCloseTo(5, 4)
  })
})

describe('evalNode 布尔求值', () => {
  const BIG_BOX = { op: 'box' as const, size: [30, 30, 30] as [number, number, number] }
  const CUT: DesignPrimitiveNode = {
    op: 'cyl', d: 10, h: 40, fn: 24,
    transform: { ops: [['translate', [0, 0, -1]]] },
  }

  it('difference：首个体减去其余（法兰板通孔形态）', () => {
    const geometry = evalNode({ op: 'difference', children: [BIG_BOX, CUT] })
    expect(geometry).not.toBeNull()
    const triangles = Math.floor((geometry!.getAttribute('position') as THREE.BufferAttribute).count / 3)
    expect(triangles).toBeGreaterThan(0)
  })

  it('union 合并两个分离盒体', () => {
    const geometry = evalNode({
      op: 'union',
      children: [
        BIG_BOX,
        { op: 'box', size: [5, 5, 5], transform: { ops: [['translate', [100, 0, 0]]] } },
      ],
    })
    expect(geometry).not.toBeNull()
    const box = new THREE.Box3().setFromBufferAttribute(geometry!.getAttribute('position') as THREE.BufferAttribute)
    expect(box.max.x).toBeCloseTo(102.5, 3)
    expect(box.min.x).toBeCloseTo(-15, 3)
  })

  it('intersection 交集裁剪', () => {
    const geometry = evalNode({
      op: 'intersection',
      children: [
        { op: 'box', size: [20, 20, 20] },
        { op: 'box', size: [10, 30, 30] },
      ],
    })
    expect(geometry).not.toBeNull()
    const box = new THREE.Box3().setFromBufferAttribute(geometry!.getAttribute('position') as THREE.BufferAttribute)
    expect(box.max.x).toBeCloseTo(5, 3)
    expect(box.min.x).toBeCloseTo(-5, 3)
  })

  it('布尔空块返回 null', () => {
    expect(evalNode({ op: 'union', children: [] })).toBeNull()
  })

  it('子体全部退化时返回 null', () => {
    // 两块完全不相交的 intersection 结果为空
    const geometry = evalNode({
      op: 'intersection',
      children: [
        { op: 'box', size: [1, 1, 1] },
        { op: 'box', size: [1, 1, 1], transform: { ops: [['translate', [100, 100, 100]]] } },
      ],
    })
    expect(geometry).toBeNull()
  })
})

describe('irStats / buildIRMeshes', () => {
  const FLANGE: DesignIR = {
    version: 2,
    units: { length: 'mm', angle: 'deg' },
    params: [{ name: 'width', value: 80 }],
    nodes: [{
      op: 'difference',
      children: [
        { op: 'box', size: [80, 40, 12] },
        {
          op: 'cyl', d: 8, h: 14, fn: 24,
          transform: { ops: [['translate', [40, 20, -1]]] },
        },
      ],
    }],
  }

  it('法兰板示例：1 个顶层节点、三角形数 > 0', () => {
    const stats = irStats(FLANGE)
    expect(stats.nodes).toBe(1)
    expect(stats.triangles).toBeGreaterThan(0)
  })

  it('buildIRMeshes 逐顶层节点产网格', () => {
    const meshes = buildIRMeshes(FLANGE)
    expect(meshes).toHaveLength(1)
    expect(meshes[0]).toBeInstanceOf(THREE.Mesh)
  })

  it('空 IR（顶层无实例）产出零网格', () => {
    const empty: DesignIR = { version: 2, units: { length: 'mm', angle: 'deg' }, params: [], nodes: [] }
    expect(buildIRMeshes(empty)).toHaveLength(0)
    expect(irStats(null).nodes).toBe(0)
  })
})
