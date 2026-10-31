/** dashboard 编辑草稿 hook（ADR 0023 P1）.
 *
 * 把纯函数 `dashboardDraft` 包成可撤销/重做/脏检查的状态容器；
 * 编辑态的所有变更只留在本地 draft，显式保存才写库（I5）。
 */

import { useCallback, useState } from 'react'
import type { Field } from '@/api'
import type { DashboardConfig, DashboardWidget, DashboardWidgetType } from './dashboardModel'
import {
  addWidget as addWidgetPure,
  applyLayoutPreset,
  commitHistory,
  createHistory,
  isDirty,
  patchCanvas,
  patchSettings,
  patchWidget,
  removeWidget as removeWidgetPure,
  redoHistory,
  undoHistory,
  withLayouts,
  type DraftHistory,
} from './dashboardDraft'
import type { LayoutPresetKey, WidgetBox } from './dashboardLayout'

export interface DashboardDraftApi {
  config: DashboardConfig
  baseline: DashboardConfig
  dirty: boolean
  canUndo: boolean
  canRedo: boolean
  reset: (baseline?: DashboardConfig) => void
  setLayouts: (boxes: WidgetBox[]) => void
  addWidget: (type: DashboardWidgetType, fields: Field[]) => string | null
  removeWidget: (id: string) => void
  updateWidget: (id: string, updater: (widget: DashboardWidget) => DashboardWidget) => void
  applyPreset: (preset: LayoutPresetKey) => void
  updateCanvas: (patch: Partial<DashboardConfig['canvas']>) => void
  updateSettings: (patch: Partial<DashboardConfig['settings']>) => void
  undo: () => void
  redo: () => void
  /** 保存成功后把当前草稿作为新基线 */
  markSaved: () => void
}

export function useDashboardDraft(baseline: DashboardConfig): DashboardDraftApi {
  const [history, setHistory] = useState<DraftHistory>(() => createHistory(baseline))
  const [saved, setSaved] = useState<DashboardConfig>(baseline)

  const config = history.present
  const dirty = isDirty(config, saved)

  const reset = useCallback((next?: DashboardConfig) => {
    const target = next ?? baseline
    setHistory(createHistory(target))
    setSaved(target)
  }, [baseline])

  const setLayouts = useCallback((boxes: WidgetBox[]) => {
    setHistory((h) => commitHistory(h, withLayouts(h.present, boxes)))
  }, [])

  const addWidget = useCallback((type: DashboardWidgetType, fields: Field[]): string | null => {
    const next = addWidgetPure(config, type, fields)
    if (next.widgets.length === config.widgets.length) return null
    setHistory((h) => commitHistory(h, next))
    return next.widgets.at(-1)?.id ?? null
  }, [config])

  const removeWidget = useCallback((id: string) => {
    setHistory((h) => commitHistory(h, removeWidgetPure(h.present, id)))
  }, [])

  const updateWidget = useCallback((id: string, updater: (widget: DashboardWidget) => DashboardWidget) => {
    setHistory((h) => commitHistory(h, patchWidget(h.present, id, updater)))
  }, [])

  const applyPreset = useCallback((preset: LayoutPresetKey) => {
    setHistory((h) => commitHistory(h, applyLayoutPreset(h.present, preset)))
  }, [])

  const updateCanvas = useCallback((patch: Partial<DashboardConfig['canvas']>) => {
    setHistory((h) => commitHistory(h, patchCanvas(h.present, patch)))
  }, [])

  const updateSettings = useCallback((patch: Partial<DashboardConfig['settings']>) => {
    setHistory((h) => commitHistory(h, patchSettings(h.present, patch)))
  }, [])

  const undo = useCallback(() => setHistory((h) => undoHistory(h)), [])
  const redo = useCallback(() => setHistory((h) => redoHistory(h)), [])

  const markSaved = useCallback(() => {
    setSaved(config)
  }, [config])

  return {
    config,
    baseline: saved,
    dirty,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    reset,
    setLayouts,
    addWidget,
    removeWidget,
    updateWidget,
    applyPreset,
    updateCanvas,
    updateSettings,
    undo,
    redo,
    markSaved,
  }
}
