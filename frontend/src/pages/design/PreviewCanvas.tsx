/** 3D 实时预览画布 —— three.js WebGL2 渲染 + 轨道拖拽（ADR 0079 D4）.
 *
 * 本组件是 three 渲染管线的唯一挂载点，与 renderTree（纯几何求值）拆开：
 * 纯求值可在 jsdom 单测，WebGL 挂载只在真实浏览器 / e2e 下运行。
 * 视角口径：机械制图 Z 轴向上（Object3D.DEFAULT_UP 全局置一次，仅本 chunk 生效）。
 */

import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { DesignIR } from '@/api'
import { buildIRMeshes } from './renderTree'

// 机械制图 Z 轴向上：模块加载时置一次（本 chunk 才会 import three）
THREE.Object3D.DEFAULT_UP.set(0, 0, 1)

export interface PreviewStats {
  nodes: number
  triangles: number
}

interface PreviewCanvasProps {
  ir: DesignIR | null
  /** 渲染完成 / IR 清空时回传统计（信息条展示） */
  onStats?: (stats: PreviewStats) => void
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

export default function PreviewCanvas({ ir, onStats }: PreviewCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const groupRef = useRef<THREE.Group | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const controlsRef = useRef<OrbitControls | null>(null)
  const statsRef = useRef(onStats)
  statsRef.current = onStats
  const [unsupported, setUnsupported] = useState(false)

  // ── WebGL 场景：仅挂载一次（上下文创建失败降级为提示块，不抛错） ──
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x1c2430)

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000)
    cameraRef.current = camera

    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true })
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

    // 地面网格（XY 平面，Z-up）：机械图视角参考系
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
      window.cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      // 几何与材质在 IR 切换 effect 中清理，这里只兜底清空
      group.traverse(obj => {
        if (obj instanceof THREE.Mesh) obj.geometry.dispose()
      })
      scene.clear()
    }
  }, [])

  // ── IR 变更：重建网格组并重新取景 ──
  useEffect(() => {
    const group = groupRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    if (!group || !camera) return
    group.traverse(obj => {
      if (obj instanceof THREE.Mesh) obj.geometry.dispose()
    })
    group.clear()
    const meshes = buildIRMeshes(ir)
    let triangles = 0
    for (const mesh of meshes) {
      group.add(mesh)
      const position = mesh.geometry.getAttribute('position')
      triangles += Math.floor(position.count / 3)
    }
    statsRef.current?.({ nodes: meshes.length, triangles })
    const box = new THREE.Box3().setFromObject(group)
    if (frameCamera(camera, box) && controls) {
      controls.target.copy(box.getCenter(new THREE.Vector3()))
      controls.update()
    }
  }, [ir])

  if (unsupported) {
    return (
      <div
        data-testid="design-preview-webgl-unsupported"
        style={{
          width: '100%', height: '100%', minHeight: 320, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          color: 'rgba(128, 128, 128, 0.9)', fontSize: 13,
        }}
      >
        当前环境不支持 WebGL，无法渲染 3D 预览（DSL 编辑与保存不受影响）
      </div>
    )
  }

  return <div ref={hostRef} style={{ width: '100%', height: '100%', minHeight: 320 }} />
}
