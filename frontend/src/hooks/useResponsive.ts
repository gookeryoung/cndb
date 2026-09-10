import { useState, useEffect } from 'react'

/** 屏幕尺寸断点（与 Ant Design 保持一致） */
export const BREAKPOINTS = {
  mobile: 768,
  tablet: 1024,
  desktop: 1280,
}

export type DeviceType = 'mobile' | 'tablet' | 'desktop'

export interface ResponsiveState {
  deviceType: DeviceType
  isMobile: boolean
  isTablet: boolean
  isDesktop: boolean
  width: number
  height: number
}

/** 根据窗口宽度判断设备类型 */
export function getDeviceType(width: number): DeviceType {
  if (width < BREAKPOINTS.mobile) return 'mobile'
  if (width < BREAKPOINTS.tablet) return 'tablet'
  return 'desktop'
}

/** 获取当前响应式状态（SSR 安全） */
export function getResponsiveState(): ResponsiveState {
  if (typeof window === 'undefined') {
    return {
      deviceType: 'desktop',
      isMobile: false,
      isTablet: false,
      isDesktop: true,
      width: 1280,
      height: 800,
    }
  }
  const width = window.innerWidth
  const height = window.innerHeight
  const deviceType = getDeviceType(width)
  return {
    deviceType,
    isMobile: deviceType === 'mobile',
    isTablet: deviceType === 'tablet',
    isDesktop: deviceType === 'desktop',
    width,
    height,
  }
}

/** 响应式 Hook —— 监听 window.resize，返回设备类型标志 */
export function useResponsive(): ResponsiveState {
  const [state, setState] = useState<ResponsiveState>(getResponsiveState())

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null

    const handleResize = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => setState(getResponsiveState()), 100)
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      if (timer) clearTimeout(timer)
    }
  }, [])

  return state
}
