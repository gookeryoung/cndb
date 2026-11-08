/** 3D 实时预览画布 —— three.js WebGL2 渲染 + 轨道拖拽（ADR 0079 D4）.
 *
 * 本组件是 three 渲染管线的唯一挂载点，与 renderTree（纯几何求值）拆开：
 * 纯求值可在 jsdom 单测，WebGL 挂载只在真实浏览器 / e2e 下运行。
 * 视角口径：机械制图 Z 轴向上（Object3D.DEFAULT_UP 全局置一次，仅本 chunk 生效）。
 */

import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type { DesignIR } from '@/api'
import {
  approximatePrimitives,
  buildIRMeshes,
  deserializeGeometry,
  evalNode,
  type SerializedGeometry,
} from './renderTree'
import { viewPreset, type ViewOrientation } from './viewOrient'

// 机械制图 Z 轴向上：模块加载时置一次（本 chunk 才会 import three）
THREE.Object3D.DEFAULT_UP.set(0, 0, 1)

/** 合并前的属性归一：mergeGeometries 要求所有几何 indexed/非 indexed 一致且属性集相同
 *（CSG 结果非 indexed、图元 indexed，混合必失败），统一转非 indexed 并裁剪到 position/normal。 */
function toMergable(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  const normalized = geometry.index ? geometry.toNonIndexed() : geometry
  for (const key of Object.keys(normalized.attributes)) {
    if (key !== 'position' && key !== 'normal') normalized.deleteAttribute(key)
  }
  if (!normalized.getAttribute('normal')) normalized.computeVertexNormals()
  return normalized
}

export interface PreviewStats {
  nodes: number
  triangles: number
}

/** 视口控制 API（ADR 0103 D4）：工具条 UI 在编辑器页，能力由本组件按引用暴露 */
export interface ViewportApi {
  /** 七向定向（D11 术语表） */
  orientTo: (key: ViewOrientation) => void
  /** 布满视图（框住当前包围盒） */
  fit: () => void
  /** 地面网格受控显隐 */
  setGridVisible: (visible: boolean) => void
  /** 树↔视口联动高亮（D8）：顶层 nodes 下标集合，emissive tint 3s 渐隐 */
  highlight: (indices: number[]) => void
}

interface PreviewCanvasProps {
  ir: DesignIR | null
  /** 渲染完成 / IR 清空时回传统计（信息条展示） */
  onStats?: (stats: PreviewStats) => void
  /** 视口能力就绪回调（挂载后调用一次；卸载时回调 null） */
  onViewportApi?: (api: ViewportApi | null) => void
}

/** 高亮渐隐时长（ms）：常亮 2.4s 后 0.6s 线性淡出（D8） */
const HIGHLIGHT_HOLD = 2400
const HIGHLIGHT_FADE = 600

/** Worker 节点结果消息 */
interface WorkerNodeMessage {
  type: 'node'
  gen: number
  index: number
  geometry: SerializedGeometry | null
}

/** 创建渲染 Worker（失败返回 null：jsdom / 环境不支持时回退主线程同步求值） */
function createDesignWorker(): Worker | null {
  try {
    return new Worker(new URL('./designWorker.ts', import.meta.url), { type: 'module' })
  } catch {
    return null
  }
}

/** 共享材质（进程级单例；仅挂材质、不随几何销毁） */
let sharedMaterial: THREE.MeshStandardMaterial | null = null
function getMaterial(): THREE.MeshStandardMaterial {
  sharedMaterial ??= new THREE.MeshStandardMaterial({ color: 0x9fb4cc, metalness: 0.15, roughness: 0.55 })
  return sharedMaterial
}

/** 自适应框选距离（纯数学）：取水平 / 竖直视场角中较小者，保证两个方向都框入 */
export function fitDistance(fovDeg: number, aspect: number, radius: number, padding = 1.6): number {
  const halfV = (fovDeg * Math.PI) / 360
  const halfH = Math.atan(Math.tan(halfV) * Math.max(aspect, 1e-6))
  return (Math.max(radius, 1) * padding) / Math.tan(Math.min(halfV, halfH))
}

/** 计算把相机放到能框住包围盒的距离（对角视角） */
export function frameCamera(camera: THREE.PerspectiveCamera, box: THREE.Box3, fit = 1.6): boolean {
  if (box.isEmpty()) return false
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const radius = Math.max(size.length() / 2, 1)
  const distance = radius * fit / Math.tan((camera.fov * Math.PI / 180) / 2)
  // 经典等轴测视角：+X 前、−Y 左、+Z 上（Z-up 世界）
  const dir = new THREE.Vector3(1, -1, 0.65).normalize()
  camera.position.copy(center).addScaledVector(dir, distance)
  camera.near = Math.max(distance / 1000, 0.1)
  camera.far = distance * 100
  camera.updateProjectionMatrix()
  camera.lookAt(center)
  return true
}

export default function PreviewCanvas({ ir, onStats, onViewportApi }: PreviewCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const groupRef = useRef<THREE.Group | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const controlsRef = useRef<OrbitControls | null>(null)
  const statsRef = useRef(onStats)
  statsRef.current = onStats
  const viewportApiRef = useRef(onViewportApi)
  viewportApiRef.current = onViewportApi
  // 最新 IR：高亮按所需下标即时求值单个节点（不额外常驻几何，ADR 0103 D8）
  const irRef = useRef<DesignIR | null>(ir)
  irRef.current = ir
  const [unsupported, setUnsupported] = useState(false)
  // 高亮中的实体数：写进宿主 data 属性，供 e2e 断言联动（canvas 内部状态无法外部观测）
  const [highlightCount, setHighlightCount] = useState(0)
  // Worker（C8）：惰性创建一次；消息处理经 handlerRef 转发到最新 IR effect
  const workerRef = useRef<Worker | null>(null)
  const handlerRef = useRef<((event: MessageEvent) => void) | null>(null)
  const genRef = useRef(0)
  const nodeGroupsRef = useRef<Map<number, THREE.Group>>(new Map())
  const trianglesRef = useRef(0)
  const lastStatsAtRef = useRef(0)

  // 统一统计上报：nodes 固定为顶层节点数，triangles 取当前已挂载几何合计。
  // 节流：渐进替换期间每个节点都会变化，限频 200ms 防止整页 React 重渲染风暴
  const reportStats = (ir: DesignIR | null, force = false) => {
    const now = performance.now()
    if (!force && now - lastStatsAtRef.current < 200) return
    lastStatsAtRef.current = now
    statsRef.current?.({ nodes: ir?.nodes.length ?? 0, triangles: trianglesRef.current })
  }

  // ── WebGL 场景：仅挂载一次（上下文创建失败降级为提示块，不抛错） ──
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x1c2430)

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000)
    cameraRef.current = camera

    // 预览性能优先（C8）：不开 MSAA（SwiftShader / 低端 GPU 上初始化与渲染代价高），
    // 以高 pixelRatio + 材质 roughness 弥补观感
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: false })
    } catch {
      // WebGL 不可用（无 GPU / 远程会话 / 旧内核 headless）：显示提示而非白屏
      setUnsupported(true)
      return
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    host.appendChild(renderer.domElement)
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'
    renderer.domElement.setAttribute('data-testid', 'design-preview-canvas')

    // 灯光：环境 + 两盏平行光（主光 + 补光），无阴影（预览性能优先）
    scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 1.1))
    const key = new THREE.DirectionalLight(0xffffff, 1.6)
    key.position.set(120, -160, 220)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xffffff, 0.5)
    fill.position.set(-180, 120, -80)
    scene.add(fill)

    // 地面网格（XY 平面，Z-up）：机械图视角参考系；显隐由视口工具条控制（C3）
    const grid = new THREE.GridHelper(400, 20, 0x3a4656, 0x2a3342)
    grid.rotation.x = Math.PI / 2
    scene.add(grid)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.12
    controlsRef.current = controls

    const group = new THREE.Group()
    groupRef.current = group
    scene.add(group)

    // ── 视口能力（ADR 0103 C3 / C4 / C7）：定向 / fit / 网格 / 高亮 ──
    const highlightGroup = new THREE.Group()
    scene.add(highlightGroup)
    const highlightMaterial = new THREE.MeshStandardMaterial({
      color: 0xffb44d,
      emissive: 0xff8a1e,
      emissiveIntensity: 0.9,
      transparent: true,
      opacity: 0.85,
      // 与静态合并网格同面高亮：深度偏移避免 z-fighting
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    })
    let fadeTimer = 0
    let fadeFrame = 0
    let disposed = false
    const clearHighlight = () => {
      window.clearTimeout(fadeTimer)
      window.cancelAnimationFrame(fadeFrame)
      for (const child of highlightGroup.children) {
        if (child instanceof THREE.Mesh) child.geometry.dispose()
      }
      highlightGroup.clear()
      highlightMaterial.opacity = 0.85
      if (!disposed) setHighlightCount(0)
    }
    const fadeHighlight = () => {
      const started = performance.now()
      const step = () => {
        if (disposed) return
        const progress = Math.min(1, (performance.now() - started) / HIGHLIGHT_FADE)
        highlightMaterial.opacity = 0.85 * (1 - progress)
        if (progress < 1) fadeFrame = window.requestAnimationFrame(step)
        else clearHighlight()
      }
      fadeFrame = window.requestAnimationFrame(step)
    }
    const highlight = (indices: number[]) => {
      clearHighlight()
      const current = irRef.current
      if (!current || indices.length === 0) return
      let count = 0
      for (const index of indices) {
        const node = current.nodes[index]
        if (!node) continue
        const geometry = evalNode(node)
        if (!geometry) continue
        highlightGroup.add(new THREE.Mesh(geometry, highlightMaterial))
        count += 1
      }
      if (count === 0) return
      setHighlightCount(count)
      fadeTimer = window.setTimeout(fadeHighlight, HIGHLIGHT_HOLD)
    }
    const boxOf = (): THREE.Box3 | null => {
      const box = new THREE.Box3().setFromObject(group)
      return box.isEmpty() ? null : box
    }
    const orientTo = (key: ViewOrientation) => {
      const preset = viewPreset(key)
      if (!preset) return
      const box = boxOf()
      const center = box ? box.getCenter(new THREE.Vector3()) : controls.target.clone()
      const radius = box ? Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1) : 1
      const distance = Math.max(camera.position.distanceTo(controls.target), radius * 0.5)
      camera.up.set(preset.up[0], preset.up[1], preset.up[2])
      camera.position.copy(center).addScaledVector(
        new THREE.Vector3(preset.dir[0], preset.dir[1], preset.dir[2]).normalize(),
        distance,
      )
      camera.lookAt(center)
      controls.target.copy(center)
      controls.update()
    }
    const fit = () => {
      const box = boxOf()
      if (!box) return
      const center = box.getCenter(new THREE.Vector3())
      // 自适应缩放：沿用当前视线方向与 up，仅按视口宽高比调整相机距离，
      // 不改视图方位（定向由 orientTo 负责）
      const dir = camera.position.clone().sub(controls.target)
      if (dir.lengthSq() < 1e-9) dir.set(1, -1, 0.65) // 尚未定向（相机与目标重合）时借等轴测方向
      dir.normalize()
      const size = box.getSize(new THREE.Vector3())
      const distance = fitDistance(camera.fov, camera.aspect, size.length() / 2)
      camera.position.copy(center).addScaledVector(dir, distance)
      camera.near = Math.max(distance / 1000, 0.1)
      camera.far = distance * 100
      camera.updateProjectionMatrix()
      camera.lookAt(center)
      controls.target.copy(center)
      controls.update()
    }
    viewportApiRef.current?.({
      orientTo,
      fit,
      setGridVisible: (visible: boolean) => { grid.visible = visible },
      highlight,
    })

    const resize = () => {
      const w = host.clientWidth || 1
      const h = host.clientHeight || 1
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h, false)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(host)

    let raf = 0
    const tick = () => {
      controls.update()
      renderer.render(scene, camera)
      raf = window.requestAnimationFrame(tick)
    }
    raf = window.requestAnimationFrame(tick)

    return () => {
      disposed = true
      viewportApiRef.current?.(null)
      window.clearTimeout(fadeTimer)
      window.cancelAnimationFrame(fadeFrame)
      window.cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      highlightMaterial.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      // 几何与材质在 IR 切换 effect 中清理，这里只兜底清空
      group.traverse(obj => {
        if (obj instanceof THREE.Mesh) obj.geometry.dispose()
      })
      scene.clear()
    }
  }, [])

  // ── Worker 生命周期：挂载创建、卸载终止 ──
  useEffect(() => {
    const worker = createDesignWorker()
    if (!worker) {
      console.warn('[design-worker] 创建失败，回退主线程同步求值')
    } else {
      worker.onerror = (event) => console.error('[design-worker] 错误', event.message ?? event)
      worker.onmessage = (event: MessageEvent) => handlerRef.current?.(event)
      workerRef.current = worker
    }
    return () => {
      if (workerRef.current) {
        workerRef.current.onmessage = null
        workerRef.current.terminate()
        workerRef.current = null
      }
    }
  }, [])

  // ── IR 变更：首帧同步近似骨架，CSG 精确几何由 Worker 渐进替换（ADR 0086 C8） ──
  useEffect(() => {
    const group = groupRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    if (!group || !camera) return
    // 清理旧几何（Worker 结果替换在 gen 校验后操作 nodeGroups，不会跨 IR 串扰）
    for (const nodeGroup of nodeGroupsRef.current.values()) {
      nodeGroup.traverse(obj => {
        if (obj instanceof THREE.Mesh) obj.geometry.dispose()
      })
    }
    nodeGroupsRef.current.clear()
    group.clear()
    trianglesRef.current = 0
    if (!ir || ir.nodes.length === 0) {
      reportStats(ir)
      return
    }

    const worker = workerRef.current
    if (!worker) {
      // 回退路径（无 Worker 环境）：主线程同步全量求值（原行为）
      const meshes = buildIRMeshes(ir)
      for (const mesh of meshes) {
        group.add(mesh)
        const position = mesh.geometry.getAttribute('position')
        trianglesRef.current += Math.floor(position.count / 3)
      }
      const box = new THREE.Box3().setFromObject(group)
      if (frameCamera(camera, box) && controls) {
        controls.target.copy(box.getCenter(new THREE.Vector3()))
        controls.update()
      }
      statsRef.current?.({ nodes: meshes.length, triangles: trianglesRef.current })
      return
    }

    // 首帧骨架：图元展开按 rAF 分批构建（每批一小片，避免单次长任务，C9）；
    // Worker 的 CSG 精确求值与骨架并行推进
    const gen = genRef.current + 1
    genRef.current = gen
    let batchIndex = 0
    const BATCH = 25
    const buildBatch = () => {
      if (gen !== genRef.current) return // IR 已变：骨架构建作废
      const end = Math.min(batchIndex + BATCH, ir.nodes.length)
      for (; batchIndex < end; batchIndex += 1) {
        const index = batchIndex
        const nodeGroup = new THREE.Group()
        const geometries = approximatePrimitives(ir.nodes[index])
        // 按节点合并为单个网格：draw call 从图元数降到节点数（软渲染首帧代价线性相关）
        let merged: THREE.BufferGeometry | null = null
        if (geometries.length > 1) {
          try {
            merged = mergeGeometries(geometries.map(toMergable), false)
          } catch {
            merged = null
          }
        }
        if (merged) {
          for (const geometry of geometries) geometry.dispose()
          merged.computeVertexNormals()
          nodeGroup.add(new THREE.Mesh(merged, getMaterial()))
          trianglesRef.current += Math.floor(merged.getAttribute('position').count / 3)
        } else {
          for (const geometry of geometries) {
            nodeGroup.add(new THREE.Mesh(geometry, getMaterial()))
            trianglesRef.current += Math.floor(geometry.getAttribute('position').count / 3)
          }
        }
        nodeGroupsRef.current.set(index, nodeGroup)
        group.add(nodeGroup)
      }
      const box = new THREE.Box3().setFromObject(group)
      if (frameCamera(camera, box) && controls) {
        controls.target.copy(box.getCenter(new THREE.Vector3()))
        controls.update()
      }
      reportStats(ir)
      if (batchIndex < ir.nodes.length) {
        window.requestAnimationFrame(buildBatch)
      } else {
        reportStats(ir, true) // 骨架构建完成：强制上报一次最终统计
      }
    }
    buildBatch()

    // Worker 渐进替换：gen 不匹配（新 IR 已到）的消息一律丢弃
    handlerRef.current = (event: MessageEvent) => {
      const message = event.data as WorkerNodeMessage & { type: string }
      if (message.type === 'node') {
        if (message.gen !== gen) return
        const nodeGroup = nodeGroupsRef.current.get(message.index)
        if (!nodeGroup) return
        nodeGroup.traverse(obj => {
          if (obj instanceof THREE.Mesh) obj.geometry.dispose()
        })
        nodeGroup.clear()
        if (message.geometry) {
          const geometry = deserializeGeometry(message.geometry)
          nodeGroup.add(new THREE.Mesh(geometry, getMaterial()))
          trianglesRef.current += Math.floor(geometry.getAttribute('position').count / 3)
        }
        reportStats(ir)
      } else if (message.type === 'done' && message.gen === gen) {
        // 全部节点替换完成：合并为单一静态网格（draw call 200 → 1，
        // 软渲染 / 低端 GPU 上每帧代价与 draw call 线性相关，C9）
        const geometries: THREE.BufferGeometry[] = []
        for (const nodeGroup of nodeGroupsRef.current.values()) {
          nodeGroup.traverse(obj => {
            if (obj instanceof THREE.Mesh) geometries.push(obj.geometry)
          })
        }
        let staticMesh: THREE.Mesh | null = null
        if (geometries.length > 1) {
          try {
            const merged = mergeGeometries(geometries.map(toMergable), false)
            if (merged) {
              for (const geometry of geometries) geometry.dispose()
              staticMesh = new THREE.Mesh(merged, getMaterial())
            }
          } catch {
            staticMesh = null
          }
        }
        if (staticMesh) {
          group.clear()
          nodeGroupsRef.current.clear()
          group.add(staticMesh)
        }
        reportStats(ir, true) // CSG 替换完成：强制上报最终统计
        handlerRef.current = null
      }
    }
    worker.postMessage({ type: 'eval', gen, nodes: ir.nodes })
  }, [ir])

  if (unsupported) {
    return (
      <div
        data-testid="design-preview-webgl-unsupported"
        style={{
          width: '100%', height: '100%', minHeight: 320, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          color: 'rgba(128, 128, 128, 0.9)', fontSize: 'var(--cn-text-sm)',
        }}
      >
        当前环境不支持 WebGL，无法渲染 3D 预览（DSL 编辑与保存不受影响）
      </div>
    )
  }

  return (
    <div
      ref={hostRef}
      data-testid="design-preview-host"
      data-highlight-nodes={highlightCount > 0 ? highlightCount : undefined}
      style={{ width: '100%', height: '100%', minHeight: 320 }}
    />
  )
}
