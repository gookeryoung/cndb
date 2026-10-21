/** 认证页 Perlin 流场粒子背景（ADR 0016）.
 *
 * 默认导出供 AuthLayout 以 React.lazy 动态引入：引擎与流场只随认证页 chunk 下载，
 * 不进入主入口（D10）。组件只负责把设备 / 动效偏好交给引擎。
 */

import { useEffect, useRef, useState } from 'react'

import { useResponsive } from '@/hooks/useResponsive'

import { mountAuthBackground } from './engine'

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function readReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia(REDUCED_MOTION_QUERY).matches
}

/** 跟随系统「减少动态」偏好；运行期切换时立即停 / 启 rAF */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(readReducedMotion)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(REDUCED_MOTION_QUERY)
    const onChange = () => setReduced(query.matches)
    query.addEventListener?.('change', onChange)
    return () => query.removeEventListener?.('change', onChange)
  }, [])

  return reduced
}

export default function AuthBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const { isMobile } = useResponsive()
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    return mountAuthBackground(canvas, { isMobile, reducedMotion })
  }, [isMobile, reducedMotion])

  return (
    <div className="auth-bg-layer" aria-hidden="true" data-effect="flowfield">
      <canvas ref={canvasRef} className="auth-bg-canvas" />
    </div>
  )
}
