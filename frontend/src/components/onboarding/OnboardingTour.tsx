/** OnboardingTour — driver.js 新手引导封装.
 *
 * 挂载在 MainLayout：
 * - 自动触发：首次进入数据表格页（/w/:wid/tables/:tid）且未完成过引导
 * - 重放触发：帮助中心「重新播放新手引导」发出 tourRequested 信号
 * - 移动端降级：引导基于桌面布局，移动端直接标记完成不弹出
 * - 完成或中途关闭（onDestroyed）→ 写入完成标记，之后不再自动弹出
 */

import { useCallback, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import type { DriveStep } from 'driver.js'
import { useOnboardingStore } from '@/store/onboarding'
import { useResponsive } from '@/hooks/useResponsive'
import { buildSteps } from './onboardingSteps'

/** 数据表格页路由（引导触发页，MainLayout 同屏可高亮全部核心元素） */
const GRID_PAGE_RE = /\/w\/[^/]+\/tables\/[^/]+/

export default function OnboardingTour() {
  const location = useLocation()
  const { isMobile } = useResponsive()
  const tourDone = useOnboardingStore(s => s.tourDone)
  const tourRequested = useOnboardingStore(s => s.tourRequested)
  const markTourDone = useOnboardingStore(s => s.markTourDone)
  const clearTourRequest = useOnboardingStore(s => s.clearTourRequest)
  const driverRef = useRef<ReturnType<typeof driver> | null>(null)

  /** 启动引导（幂等：进行中不重复启动） */
  const startTour = useCallback(() => {
    if (driverRef.current?.isActive()) return
    driverRef.current = driver({
      steps: buildSteps() as DriveStep[],
      showProgress: true,
      allowClose: true,
      // 关闭高亮动画：driver.js 1.8 在 400ms 动画完成前 __activeElement/__activeStep
      // 尚未写入内部 state，此时点关闭会跳过 onDestroyed 回调（完成标记不落盘）
      animate: false,
      // 目标元素不存在（如空表）时降级为居中展示，不报错不中断
      skipMissingElement: true,
      popoverClass: 'cn-driver-theme',
      progressText: '{{current}} / {{total}}',
      nextBtnText: '下一步',
      prevBtnText: '上一步',
      doneBtnText: '完成',
      onDestroyed: () => {
        // 走完最后一步或中途关闭都视为完成，之后不再自动弹出
        markTourDone()
        clearTourRequest()
      },
    })
    driverRef.current.drive()
  }, [markTourDone, clearTourRequest])

  // 自动触发：进入数据表格页且未完成过引导
  useEffect(() => {
    if (isMobile) {
      // 移动端布局差异大，直接标记完成，避免每次进入都判定
      if (!tourDone) markTourDone()
      return
    }
    if (tourDone || driverRef.current?.isActive()) return
    if (GRID_PAGE_RE.test(location.pathname)) {
      // 延迟一拍等待 GridPage lazy chunk 与工具栏挂载；元素缺失由 skipMissingElement 兜底
      const timer = window.setTimeout(() => startTour(), 800)
      return () => window.clearTimeout(timer)
    }
  }, [location.pathname, isMobile, tourDone, markTourDone, startTour])

  // 帮助中心重放：收到信号即启动，并立即消费掉信号（避免 effect 重复触发）
  useEffect(() => {
    if (tourRequested && !isMobile) {
      clearTourRequest()
      startTour()
    }
  }, [tourRequested, isMobile, startTour, clearTourRequest])

  return null
}
