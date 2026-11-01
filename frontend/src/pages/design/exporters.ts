/** 设计产物导出（ADR 0079 D5）：STL（二进制）/ OBJ / GLB + 正交三视图 PNG.
 *
 * 全部从「IR 求值出的网格」生成（I1：前端不解析 DSL、只消费后端 IR；
 * 导出文件以前端求值结果为准，边界 #5）。GLB 用 three 自带 GLTFExporter，
 * STL / OBJ 为小体量手写序列化（D5：零新增依赖）。
 *
 * 三视图 PNG 需要真实 WebGL 渲染：``captureViews`` 允许注入 renderer
 * （jsdom 单测用 fake renderer 断言相机与产物，真实路径由编辑器传
 * three 的 WebGLRenderer；无 WebGL 环境抛 DesignExportError）。
 */

import * as THREE from 'three'
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js'
import type { DesignIR } from '@/api'
import { buildIRMeshes } from './renderTree'

/** 导出失败（如环境不支持 WebGL）：调用方按 message 提示，不影响编辑与保存 */
export class DesignExportError extends Error {}

/** 网格 → 非索引三角形顶点流（世界坐标；CSG 结果可能是索引几何） */
function trianglesOf(meshes: THREE.Mesh[]): Float32Array[] {
  const out: Float32Array[] = []
  for (const mesh of meshes) {
    mesh.updateMatrixWorld()
    let geometry = mesh.geometry
    if (geometry.index) geometry = geometry.toNonIndexed()
    const position = geometry.getAttribute('position')
    if (!position) continue
    const points = new Float32Array(position.count * 3)
    const vertex = new THREE.Vector3()
    for (let i = 0; i < position.count; i += 1) {
      vertex.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld)
      points[i * 3] = vertex.x
      points[i * 3 + 1] = vertex.y
      points[i * 3 + 2] = vertex.z
    }
    out.push(points)
  }
  return out
}

/** STL 二进制（小端）：80 字节头 + uint32 三角形数 + 每三角形 50 字节 */
export function buildSTL(meshes: THREE.Mesh[]): ArrayBuffer {
  const parts = trianglesOf(meshes)
  const triangleCount = parts.reduce((sum, pts) => sum + pts.length / 9, 0)
  if (!Number.isInteger(triangleCount) || triangleCount <= 0) {
    throw new DesignExportError('模型没有可导出的三角形（顶层尚无实例或布尔求值为空）')
  }
  const buffer = new ArrayBuffer(84 + triangleCount * 50)
  const view = new DataView(buffer)
  const header = 'cndb design stl'
  for (let i = 0; i < header.length; i += 1) view.setUint8(i, header.charCodeAt(i))
  view.setUint32(80, triangleCount, true)

  let offset = 84
  for (const pts of parts) {
    for (let i = 0; i < pts.length; i += 9) {
      const a = new THREE.Vector3(pts[i], pts[i + 1], pts[i + 2])
      const b = new THREE.Vector3(pts[i + 3], pts[i + 4], pts[i + 5])
      const c = new THREE.Vector3(pts[i + 6], pts[i + 7], pts[i + 8])
      const normal = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a)).normalize()
      view.setFloat32(offset, normal.x, true)
      view.setFloat32(offset + 4, normal.y, true)
      view.setFloat32(offset + 8, normal.z, true)
      view.setFloat32(offset + 12, a.x, true)
      view.setFloat32(offset + 16, a.y, true)
      view.setFloat32(offset + 20, a.z, true)
      view.setFloat32(offset + 24, b.x, true)
      view.setFloat32(offset + 28, b.y, true)
      view.setFloat32(offset + 32, b.z, true)
      view.setFloat32(offset + 36, c.x, true)
      view.setFloat32(offset + 40, c.y, true)
      view.setFloat32(offset + 44, c.z, true)
      view.setUint16(offset + 48, 0, true)
      offset += 50
    }
  }
  return buffer
}

/** OBJ 文本（v + f，1-based 顶点编号跨网格累计） */
export function buildOBJ(meshes: THREE.Mesh[]): string {
  const parts = trianglesOf(meshes)
  const lines: string[] = ['# cndb design', 'o design']
  let vertexBase = 0
  for (const pts of parts) {
    for (let i = 0; i < pts.length; i += 3) {
      lines.push(`v ${pts[i].toFixed(6)} ${pts[i + 1].toFixed(6)} ${pts[i + 2].toFixed(6)}`)
    }
    for (let i = 0; i < pts.length; i += 9) {
      const a = vertexBase + i / 3 + 1
      lines.push(`f ${a} ${a + 1} ${a + 2}`)
    }
    vertexBase += pts.length / 3
  }
  return `${lines.join('\n')}\n`
}

/** GLB（二进制 glTF 2.0）：three 自带 GLTFExporter（D5 零新增依赖） */
export function buildGLB(meshes: THREE.Mesh[]): Promise<Blob> {
  const scene = new THREE.Scene()
  for (const mesh of meshes) scene.add(mesh)
  const exporter = new GLTFExporter()
  return new Promise<Blob>((resolve, reject) => {
    exporter.parse(
      scene,
      (result) => {
        // binary: true 时 result 为 ArrayBuffer
        resolve(new Blob([result as ArrayBuffer], { type: 'model/gltf-binary' }))
      },
      (error) => reject(new DesignExportError(`GLB 导出失败：${String(error)}`)),
      { binary: true },
    )
  })
}

/** 三视图方向（Z-up 世界）：front 从 -Y 看向原点、top 从 +Z 俯视、right 从 +X 看向原点 */
export type OrthoViewKind = 'front' | 'top' | 'right'

/** 正交相机：包围盒适配视野（留 10% 边距），near/far 覆盖模型进深 */
export function orthoViewCamera(kind: OrthoViewKind, meshes: THREE.Mesh[]): THREE.OrthographicCamera {
  const box = new THREE.Box3()
  for (const mesh of meshes) {
    mesh.updateMatrixWorld()
    box.expandByObject(mesh)
  }
  if (box.isEmpty()) box.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1))
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  // 取三个方向最大跨度作正方形视野，保证三视图比例一致
  const span = Math.max(size.x, size.y, size.z) * 1.1 || 1
  const depth = Math.max(size.x, size.y, size.z) * 2 + span
  const camera = new THREE.OrthographicCamera(-span / 2, span / 2, span / 2, -span / 2, -depth, depth)
  const distance = depth / 2
  if (kind === 'front') camera.position.set(center.x, center.y - distance, center.z)
  else if (kind === 'top') camera.position.set(center.x, center.y, center.z + distance)
  else camera.position.set(center.x + distance, center.y, center.z)
  camera.lookAt(center)
  return camera
}

/** WebGL 渲染器最小接口（注入点：单测传 fake，真实路径传 three 的 WebGLRenderer） */
export interface ViewRenderer {
  render: (scene: THREE.Scene, camera: THREE.Camera) => void
  domElement: HTMLCanvasElement & { toDataURL: (type?: string) => string }
  setSize: (width: number, height: number) => void
}

/** 正交三视图（前 / 上 / 右）各渲染一帧并取 PNG dataURL */
export function captureViews(
  meshes: THREE.Mesh[],
  viewSize = 480,
  rendererFactory?: () => ViewRenderer,
): Record<OrthoViewKind, string> {
  let renderer: ViewRenderer
  try {
    renderer = rendererFactory ? rendererFactory() : new THREE.WebGLRenderer({ antialias: true, alpha: true })
  } catch {
    throw new DesignExportError('当前环境不支持 WebGL，无法生成三视图 PNG（STL / OBJ / GLB 导出不受影响）')
  }
  const scene = new THREE.Scene()
  for (const mesh of meshes) scene.add(mesh)
  renderer.setSize(viewSize, viewSize)
  const kinds: OrthoViewKind[] = ['front', 'top', 'right']
  const result = { front: '', top: '', right: '' } as Record<OrthoViewKind, string>
  for (const kind of kinds) {
    renderer.render(scene, orthoViewCamera(kind, meshes))
    result[kind] = renderer.domElement.toDataURL('image/png')
  }
  return result
}

/** 触发浏览器下载（编辑器导出按钮共用） */
export function downloadBlob(data: Blob | ArrayBuffer, filename: string): void {
  const blob = data instanceof Blob ? data : new Blob([data], { type: 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

/** 触发 PNG dataURL 下载 */
export function downloadDataURL(dataURL: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = dataURL
  anchor.download = filename
  anchor.click()
}

/** IR → 导出网格（导出与预览共用同一求值路径，保证所见即所得） */
export function exportMeshesOf(ir: DesignIR | null | undefined): THREE.Mesh[] {
  return buildIRMeshes(ir)
}
