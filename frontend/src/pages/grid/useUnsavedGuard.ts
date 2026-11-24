/** 未保存编辑的离开拦截（路线图 0141 P0-3）.
 *
 * 数据表行内编辑是「整行草稿 + 显式保存」：草稿只存在组件状态里，切视图 / 切表 /
 * 刷新 / 关标签页都会丢。本 hook 提供两件事：
 *
 * 1. `beforeunload` 守卫（浏览器级）——刷新、关标签页、地址栏跳转时由浏览器弹原生确认；
 * 2. `guard(action)`（应用内）——调用方在「自己控制的切换动作」（切视图 / 切模式 /
 *    切表按钮）前调用；脏状态下弹 confirm，用户确认后才执行。
 *
 * 说明：本应用用 `BrowserRouter`（非 data router），没有全局 `useBlocker`。因此侧栏
 * 直接点另一张表这类「跨页面 Link 跳转」目前不在拦截范围内（需要切换到 data router
 * 才能覆盖），已在需求卡 0141 的「已知限制」里登记。
 */

import { useCallback, useEffect, useRef } from 'react'

/** 脏状态提示文案（浏览器原生弹窗只显示通用文案，这里用于应用内确认） */
export const UNSAVED_LEAVE_MESSAGE = '有未保存的行内编辑，离开将丢弃这些修改'

export function useUnsavedGuard(dirty: boolean) {
  // 用 ref 让监听器只注册一次，但始终读到最新 dirty（避免每次输入重绑事件）
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return
      // 现代浏览器忽略自定义文案，但必须 setReturnValue / preventDefault 才会弹确认
      event.preventDefault()
      event.returnValue = UNSAVED_LEAVE_MESSAGE
      return UNSAVED_LEAVE_MESSAGE
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  /**
   * 应用内切换守卫：脏状态下（或 `force` 为 true 时）要求确认。
   * 返回 true 表示可以继续执行动作。
   */
  const confirmLeave = useCallback((force = false): boolean => {
    if (!dirtyRef.current || force) return true
    return window.confirm(UNSAVED_LEAVE_MESSAGE)
  }, [])

  return { dirty, confirmLeave }
}
