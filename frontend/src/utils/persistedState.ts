/** 轻量持久化状态 —— localStorage / sessionStorage 的 React 封装.
 *
 * 约定：
 *  - 用户偏好（侧栏折叠等）用 `local`，页面会话上下文（展开态 / 过滤词）用 `session`；
 *  - storage 不可用（隐私模式 / 配额满）或数据损坏时静默回落到 fallback，不阻塞渲染；
 *  - key 变化（如切换工作区）时重读，避免沿用上一个工作区的状态。
 */

import { useCallback, useState } from 'react'

export type StorageKind = 'local' | 'session'

function resolveStorage(kind: StorageKind): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

/** 读取持久化值；未命中 / 损坏 / storage 不可用时返回 fallback */
export function readPersisted<T>(key: string, fallback: T, kind: StorageKind = 'local'): T {
  const storage = resolveStorage(kind)
  if (!storage) return fallback
  try {
    const raw = storage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

/** 写入持久化值；失败静默忽略 */
export function writePersisted<T>(key: string, value: T, kind: StorageKind = 'local'): void {
  const storage = resolveStorage(kind)
  if (!storage) return
  try {
    storage.setItem(key, JSON.stringify(value))
  } catch {
    /* 配额满 / 隐私模式：不影响本次会话 */
  }
}

/** 持久化 state hook：返回值与 setState 用法一致（支持函数式更新） */
export function usePersistedState<T>(
  key: string,
  fallback: T,
  kind: StorageKind = 'local',
): [T, (next: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => readPersisted(key, fallback, kind))
  const [activeKey, setActiveKey] = useState(key)

  // key 变化（切换工作区）时在渲染期同步重读 —— React 官方推荐的「派生 state 重置」模式，
  // 避免先用旧值渲染一帧再在 effect 里纠正。
  if (activeKey !== key) {
    setActiveKey(key)
    setValue(readPersisted(key, fallback, kind))
  }

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setValue(prev => {
      const resolved = typeof next === 'function' ? (next as (prev: T) => T)(prev) : next
      writePersisted(key, resolved, kind)
      return resolved
    })
  }, [key, kind])

  return [value, set]
}
