/** 认证页背景画布（ADR 0016 §6）.
 *
 * 默认导出供 AuthLayout 以 React.lazy 动态引入：引擎与 5 个变体只随认证页 chunk 下载，
 * 不进入主入口（D10）。组件只负责把主题 / 设备 / 动效偏好交给引擎。
 */

import { useEffect, useRef, useState } from 'react'

import { useResponsive } from '@/hooks/useResponsive'
import { useTheme } from '@/theme/ThemeProvider'

import { mountAuthBackground } from './engine'
import type { AuthBackgroundVariant } from './types'

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

export interface AuthBackgroundProps {
  variant: AuthBackgroundVariant
}

export default function AuthBackground({ variant }: AuthBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const { isDark, mode } = useTheme()
  const { isMobile } = useResponsive()
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    // mode 进入依赖：同为深色的 github-dark / midnight / oled 之间切换时 isDark 不变，
    // 但 --cn-brand-color 会变，必须用新色板重建引擎（I3）。
    return mountAuthBackground(canvas, { variant, isDark, isMobile, reducedMotion })
  }, [variant, isDark, isMobile, reducedMotion, mode])

  return (
    <div className="auth-bg-layer" aria-hidden="true" data-variant={variant} data-theme={mode}>
      <canvas ref={canvasRef} className="auth-bg-canvas" />
    </div>
  )
}
