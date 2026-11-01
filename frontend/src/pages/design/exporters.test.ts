/** exporters 测试（ADR 0079 §7 / D5）：STL 头部与三角形计数、OBJ 行、GLB magic、
 * 三视图相机方位与产物（注入 fake renderer，jsdom 无 WebGL）、空模型拒绝导出。 */

import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import {
  DesignExportError,
  buildGLB,
  buildOBJ,
  buildSTL,
  captureViews,
  downloadBlob,
  downloadDataURL,
  orthoViewCamera,
} from './exporters'
import type { DesignIR } from '@/api'
import { buildIRMeshes } from './renderTree'

const BOX_IR: DesignIR = {
  version: 1,
  units: { length: 'mm', angle: 'deg' },
  params: [],
  nodes: [{ op: 'box', size: [10, 10, 10] }],
}

const PLATE_IR: DesignIR = {
  version: 1,
  units: { length: 'mm', angle: 'deg' },
  params: [{ name: 'width', value: 80 }],
  nodes: [
    {
      op: 'difference',
      children: [
        { op: 'box', size: [80, 40, 12] },
        { op: 'cyl', d: 8, h: 14, fn: 16, transform: { ops: [['translate', [40, 20, -1]]] } },
      ],
    },
  ],
}

/** 前视图（-Y 方向朝原点看）在 80×40×12 法兰板上的期望相机位 */
const FRONT_Y = -25.9 // 大致量级断言（相机在包围盒 -Y 侧外）

describe('buildSTL（二进制）', () => {
  it('头部 80 字节 + 三角形数小端；盒体 = 12 个三角形', () => {
    const buffer = buildSTL(buildIRMeshes(BOX_IR))
    const view = new DataView(buffer)
    // 头部以 cndb design stl 开头
    expect(String.fromCharCode(view.getUint8(0))).toBe('c')
    expect(new TextDecoder().decode(new Uint8Array(buffer, 0, 15))).toBe('cndb design stl')
    expect(view.getUint32(80, true)).toBe(12)
    expect(buffer.byteLength).toBe(84 + 12 * 50)
  })

  it('布尔求值后的网格可导出（三角形数 > 0 且首顶点落在盒体表面）', () => {
    const buffer = buildSTL(buildIRMeshes(PLATE_IR))
    const view = new DataView(buffer)
    const count = view.getUint32(80, true)
    expect(count).toBeGreaterThan(0)
    // 首三角形顶点必须落在 80×40×12 盒体内（包围盒界检查）
    for (let i = 0; i < 3; i += 1) {
      const x = view.getFloat32(84 + 12 + i * 12, true)
      const y = view.getFloat32(84 + 16 + i * 12, true)
      const z = view.getFloat32(84 + 20 + i * 12, true)
      expect(Math.abs(x)).toBeLessThanOrEqual(40.001)
      expect(Math.abs(y)).toBeLessThanOrEqual(20.001)
      expect(Math.abs(z)).toBeLessThanOrEqual(6.001)
    }
  })

  it('空模型抛 DesignExportError（边界 #3：顶层无实例）', () => {
    const emptyIR: DesignIR = { ...BOX_IR, nodes: [] }
    expect(() => buildSTL(buildIRMeshes(emptyIR))).toThrow(DesignExportError)
  })
})

describe('buildOBJ', () => {
  it('v 行数 = f 行数 × 3，f 编号从 1 递增', () => {
    const text = buildOBJ(buildIRMeshes(BOX_IR))
    const lines = text.split('\n')
    const vLines = lines.filter(l => l.startsWith('v '))
    const fLines = lines.filter(l => l.startsWith('f '))
    expect(vLines).toHaveLength(36) // 12 三角形 × 3 顶点
    expect(fLines).toHaveLength(12)
    expect(fLines[0]).toBe('f 1 2 3')
    expect(fLines[11]).toBe('f 34 35 36')
  })
})

describe('buildGLB', () => {
  it('产出 glTF 2.0 二进制（magic = glTF，版本 2）', async () => {
    const blob = await buildGLB(buildIRMeshes(BOX_IR))
    const buffer = await blob.arrayBuffer()
    const view = new DataView(buffer)
    expect(String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3))).toBe('glTF')
    expect(view.getUint32(4, true)).toBe(2)
    expect(blob.type).toBe('model/gltf-binary')
  })
})

describe('orthoViewCamera / captureViews', () => {
  const meshes = buildIRMeshes(PLATE_IR)

  it('三视图相机分别位于 -Y / +Z / +X 外侧，朝向包围盒中心', () => {
    const front = orthoViewCamera('front', meshes)
    const top = orthoViewCamera('top', meshes)
    const right = orthoViewCamera('right', meshes)
    expect(front.position.y).toBeLessThan(FRONT_Y)
    expect(front.position.z).toBeCloseTo(0, 5)
    expect(top.position.z).toBeGreaterThan(25)
    expect(top.position.x).toBeCloseTo(0, 5)
    expect(right.position.x).toBeGreaterThan(40)
    expect(right.position.y).toBeCloseTo(0, 5)
    // 视野为覆盖三向最大跨度的正方形（80 × 1.1）
    expect(front.right - front.left).toBeCloseTo(88, 5)
    expect(front.top - front.bottom).toBeCloseTo(88, 5)
  })

  it('注入 fake renderer：依次渲染前/上/右并取三张 PNG dataURL', () => {
    const renders: string[] = []
    const fake = {
      render: (_scene: THREE.Scene, camera: THREE.Camera) => { renders.push((camera as THREE.OrthographicCamera).uuid) },
      setSize: vi.fn(),
      domElement: Object.assign(document.createElement('canvas'), {
        toDataURL: () => 'data:image/png;base64,FAKE',
      }),
    }
    const result = captureViews(meshes, 320, () => fake as unknown as THREE.WebGLRenderer)
    expect(result).toEqual({ front: 'data:image/png;base64,FAKE', top: 'data:image/png;base64,FAKE', right: 'data:image/png;base64,FAKE' })
    expect(fake.setSize).toHaveBeenCalledWith(320, 320)
    expect(renders).toHaveLength(3)
  })

  it('WebGL 不可用（rendererFactory 抛错）时抛 DesignExportError 且文案提示不影响 STL 导出', () => {
    expect(() => captureViews(meshes, 320, () => { throw new Error('no webgl') })).toThrow(DesignExportError)
    try {
      captureViews(meshes, 320, () => { throw new Error('no webgl') })
    } catch (error) {
      expect((error as Error).message).toContain('不支持 WebGL')
      expect((error as Error).message).toContain('STL / OBJ / GLB 导出不受影响')
    }
  })
})

describe('download helpers', () => {
  it('downloadBlob 经 createObjectURL 触发下载并回收 URL', () => {
    const createObjectURL = vi.fn(() => 'blob:fake')
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const click = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(click)

    downloadBlob(new Blob(['x']), 'a.stl')
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake')
  })

  it('downloadDataURL 直接以 dataURL 触发下载', () => {
    const click = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(click)
    downloadDataURL('data:image/png;base64,FAKE', 'a.png')
    expect(click).toHaveBeenCalledOnce()
  })
})
