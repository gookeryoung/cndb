/** 视图设置 Provider — 维护用户级视图配置并注入 Context. */

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { loadTableSettings, saveTableSettings, DEFAULT_TABLE_SETTINGS, type TableSettings } from '@/theme/tableSettings'

interface TableSettingsContextValue {
  settings: TableSettings
  /** 批量更新 — 传入部分字段，会合并并持久化 */
  updateSettings: (patch: Partial<TableSettings>) => void
  /** 重置为默认值 */
  resetSettings: () => void
}

const TableSettingsContext = createContext<TableSettingsContextValue | undefined>(undefined)

export function TableSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<TableSettings>(() => loadTableSettings())

  const updateSettings = useCallback((patch: Partial<TableSettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...patch }
      saveTableSettings(next)
      return next
    })
  }, [])

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_TABLE_SETTINGS)
    saveTableSettings(DEFAULT_TABLE_SETTINGS)
  }, [])

  const value = useMemo<TableSettingsContextValue>(
    () => ({ settings, updateSettings, resetSettings }),
    [settings, updateSettings, resetSettings],
  )

  return (
    <TableSettingsContext.Provider value={value}>
      {children}
    </TableSettingsContext.Provider>
  )
}

/** 消费视图设置的 hook，必须在 TableSettingsProvider 内使用. */
export function useTableSettings(): TableSettingsContextValue {
  const ctx = useContext(TableSettingsContext)
  if (!ctx) throw new Error('useTableSettings must be used inside <TableSettingsProvider>')
  return ctx
}
