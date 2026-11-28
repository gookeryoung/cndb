/** 装配结构树显隐状态（需求 0193 C1 / C3 / C4）
 *
 * 结构树勾选（侧栏 DesignStructureNav）与视口显隐（DesignEditorPage / PreviewCanvas）
 * 是两个独立组件（侧栏在 MainLayout，视口在编辑器页），显隐状态必须单一来源，
 * 否则两处勾选会漂移（0193 C3）。这里用「模块级 store + useSyncExternalStore」实现：
 * - key = 设计 id（字符串）：切产品各自独立；刷新即重置为全显（C4 口径）；
 * - 值 = 被取消勾选的大纲树 key 集合（Set<string>，冻结快照，变更时整体替换）；
 * - 订阅粒度按 designId：只通知正在看该设计的组件。
 * 刻意不用 localStorage：显隐是画布会话态，不是用户偏好（0193 C4 明确刷新重置）。
 */

import { useSyncExternalStore } from 'react'

/** designId（字符串）→ 取消勾选的树 key 集合 */
const hiddenByDesign = new Map<string, ReadonlySet<string>>()

type Listener = () => void
const listeners = new Map<string, Set<Listener>>()

function emit(designId: string) {
  for (const listener of listeners.get(designId) ?? []) listener()
}

/** 取当前取消勾选集合（无记录 = 全勾 = 全显示）；返回冻结快照，引用稳定 */
export function getHiddenKeys(designId: number | string): ReadonlySet<string> {
  return hiddenByDesign.get(String(designId)) ?? EMPTY
}

const EMPTY: ReadonlySet<string> = new Set()

/** 整体替换某设计的取消勾选集合（传空集合 = 全部显示，C4） */
export function setHiddenKeys(designId: number | string, keys: ReadonlySet<string>) {
  const id = String(designId)
  if (keys.size === 0) hiddenByDesign.delete(id)
  else hiddenByDesign.set(id, new Set(keys))
  emit(id)
}

/** 切换一个 key：勾上 = 从隐藏集合移除，取消勾 = 加入 */
export function toggleHiddenKey(designId: number | string, key: string, hidden: boolean) {
  const id = String(designId)
  const next = new Set(hiddenByDesign.get(id) ?? [])
  if (hidden) next.add(key)
  else next.delete(key)
  setHiddenKeys(id, next)
}

/** 清空某设计的隐藏集合（「全部显示」C4） */
export function clearHiddenKeys(designId: number | string) {
  setHiddenKeys(designId, EMPTY)
}

function subscribe(designId: string, listener: Listener): () => void {
  let set = listeners.get(designId)
  if (!set) {
    set = new Set()
    listeners.set(designId, set)
  }
  set.add(listener)
  return () => {
    set?.delete(listener)
    if (set?.size === 0) listeners.delete(designId)
  }
}

/** React 绑定：某设计的取消勾选集合（引用稳定，变更才重渲染） */
export function useDesignHiddenKeys(designId: number | string | undefined): ReadonlySet<string> {
  return useSyncExternalStore(
    designId === undefined ? () => () => {} : listener => subscribe(String(designId), listener),
    () => (designId === undefined ? EMPTY : getHiddenKeys(designId)),
    () => EMPTY,
  )
}
