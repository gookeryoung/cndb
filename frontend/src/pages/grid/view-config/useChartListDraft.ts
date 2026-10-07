/** chart 多图条目草稿管理（共享 hook）—— ViewConfigDialog 与 CreateEditViewForm 的统一真相源.
*
* 封装「图表条目列表」的编辑态：当前条目索引、条目级 patch、新增、删除，
* 以及单图（扁平键）↔ 多图（charts[]）双形态写回规则：
*   - 条目数 ==1 → 写回扁平键形态（charts 键删除，CHART_OPTIONS 扁平键清除后合入条目）
*   - 条目数 >1  → 写回 charts[] 形态（扁平键不再写入，双形态不并存）
*/

import { useState } from 'react'
import { CHART_OPTIONS, normalizeChartList } from './viewOptionSchema'

/** 把条目列表写回 draft 对象（不可变更新；单条目写回扁平键、多条目写回 charts[]） */
export function writeBackChartList(
  prev: Record<string, unknown>,
  list: Array<Record<string, unknown>>,
): Record<string, unknown> {
  const next = { ...prev }
  if (list.length === 1) {
    delete next.charts
    for (const opt of CHART_OPTIONS) delete next[opt.key]
    Object.assign(next, list[0])
  } else {
    next.charts = list
  }
  return next
}

export interface ChartListDraft {
  /** 归一后的图表条目列表（至少 1 条） */
  list: Array<Record<string, unknown>>
  /** 当前编辑条目索引（clamp 到列表范围内） */
  activeIdx: number
  /** 当前编辑条目（list[activeIdx]，恒有值） */
  activeEntry: Record<string, unknown>
  /** 切换当前编辑条目 */
  setActiveIdx: (idx: number) => void
  /** 把 patch 合入当前条目 */
  patchEntry: (patch: Record<string, unknown>) => void
  /** 新增空条目并切为当前编辑对象（上限 6 由调用方 UI 控制禁用态） */
  addEntry: () => void
  /** 删除当前条目（至少保留 1 个） */
  removeEntry: () => void
}

export function useChartListDraft(
  draft: Record<string, unknown>,
  setDraft: (updater: (prev: Record<string, unknown>) => Record<string, unknown>) => void,
): ChartListDraft {
  const [activeIdxRaw, setActiveIdx] = useState(0)
  const list = normalizeChartList(draft)
  const activeIdx = Math.min(activeIdxRaw, list.length - 1)
  const activeEntry = list[activeIdx] ?? {}

  const patchEntry = (patch: Record<string, unknown>) => {
    setDraft(prev => {
      const l = normalizeChartList(prev)
      const idx = Math.min(activeIdx, l.length - 1)
      const entry = { ...(l[idx] ?? {}) }
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined) delete entry[k]
        else entry[k] = v
      }
      l[idx] = entry
      return writeBackChartList(prev, l)
    })
  }

  const addEntry = () => {
    setActiveIdx(list.length)
    setDraft(prev => ({ ...prev, charts: [...normalizeChartList(prev), {}] }))
  }

  const removeEntry = () => {
    const idx = activeIdx
    setDraft(prev => writeBackChartList(
      prev,
      normalizeChartList(prev).filter((_, i) => i !== idx),
    ))
    setActiveIdx(Math.max(0, idx - 1))
  }

  return { list, activeIdx, activeEntry, setActiveIdx, patchEntry, addEntry, removeEntry }
}
