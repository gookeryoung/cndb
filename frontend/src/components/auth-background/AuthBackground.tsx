/** 认证页静态晶格背景（ADR 0016）.
 *
 * 默认导出供 AuthLayout 以 React.lazy 动态引入：引擎与晶格绘制只随认证页 chunk
 * 下载，不进入主入口（D6）。组件只负责画布挂载与设备档位，绘制细节交给引擎。
 */

import { useEffect, useRef } from 'react'

import { useResponsive } from '@/hooks/useResponsive'

import { mountAuthBackground } from './engine'

export default function AuthBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const { isMobile } = useResponsive()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    return mountAuthBackground(canvas, { isMobile })
  }, [isMobile])

  return (
    <div className="auth-bg-layer" aria-hidden="true">
      <canvas ref={canvasRef} className="auth-bg-canvas" />
    </div>
  )
}
