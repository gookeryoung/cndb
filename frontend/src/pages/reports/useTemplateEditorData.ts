/** 报表模板编辑器的数据层：跨工作区表解析、字段/视图/预览取数，以及由它们派生的下拉选项.
 *
 * 从 TemplateEditorModal.tsx 的 TemplateEditor 抽出。组件只保留表单状态、交互状态与
 * 业务 handler，服务端派生的一切都收敛到这里。
 *
 * 入参中的 `selectedTableId` / `extraTableIds` / `importWsId` 仍由组件持有（它们同时也是
 * 表单受控值），hook 只读不写；`crossTableInfo` 的写入完全发生在 hook 内部，仅把
 * setter 一并暴露给「跨工作区引入」handler 使用。
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fieldApi, recordApi, tableApi, viewApi, workspaceApi } from '@/api'
import type { Field, TableSummary, View, Workspace } from '@/api'

export function useTemplateEditorData({
  open,
  workspaceId,
  tables,
  selectedTableId,
  extraTableIds,
  importWsId,
}: {
  open: boolean
  workspaceId: string
  /** 当前工作区的表列表（由页面传入，避免重复请求） */
  tables: TableSummary[]
  selectedTableId: number | null
  extraTableIds: number[]
  importWsId: string
}) {
  const tableOptions = useMemo(() => tables.map(t => ({ value: t.id, label: t.name })), [tables])

  // 跨工作区表信息：tableId -> {name, wsId}（级联引入与编辑回显扫描共同填充）
  const [crossTableInfo, setCrossTableInfo] = useState<Record<number, { name: string; wsId: string }>>({})

  // 工作区列表（跨工作区级联选择器数据源）
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
    enabled: open,
  })

  // 源工作区的表列表（级联第二步）
  const { data: importWsTables = [] } = useQuery({
    queryKey: ['workspaces', importWsId, 'tables'],
    queryFn: () => tableApi.list(importWsId!),
    enabled: open && !!importWsId && importWsId !== workspaceId,
  })

  // 编辑回显：主表或 extra_table_ids 中归属未知的表（如 seed 生成的跨工作区模板），扫描全部工作区补全信息
  const primaryTableMissing = selectedTableId !== null && !tables.some(t => t.id === selectedTableId) && !crossTableInfo[selectedTableId]
  const missingScan = open && (primaryTableMissing || extraTableIds.some(tid => !tables.some(t => t.id === tid) && !crossTableInfo[tid]))
  useEffect(() => {
    if (!missingScan) return
    let cancelled = false
    workspaceApi.list().then(async (wsList) => {
      const info: Record<number, { name: string; wsId: string }> = {}
      for (const ws of wsList) {
        if (String(ws.id) === workspaceId) continue
        const wsTables = await tableApi.list(ws.id).catch(() => [])
        for (const t of wsTables) info[Number(t.id)] = { name: t.name, wsId: String(ws.id) }
      }
      if (!cancelled) setCrossTableInfo(prev => ({ ...info, ...prev }))
    }).catch(() => { /* 扫描失败静默，字段/预览退化为本工作区行为 */ })
    return () => { cancelled = true }
  }, [missingScan, workspaceId])

  // 主表归属工作区：本区表直接用当前工作区，跨工作区表（seed 模板等）经 crossTableInfo 解析
  const primaryTableWsId = selectedTableId !== null
    ? (crossTableInfo[selectedTableId]?.wsId ?? workspaceId)
    : workspaceId

  // 关联表的字段列表
  const { data: fields = [] } = useQuery<Field[]>({
    queryKey: ['workspaces', primaryTableWsId, 'tables', selectedTableId, 'fields'],
    queryFn: () => fieldApi.list(primaryTableWsId, selectedTableId!),
    enabled: !!selectedTableId,
  })

  // 关联表的视图列表（报表可选绑定视图，渲染时按视图过滤/排序取数）
  const { data: tableViews = [] } = useQuery<View[]>({
    queryKey: ['workspaces', primaryTableWsId, 'tables', selectedTableId, 'views'],
    queryFn: () => viewApi.list(primaryTableWsId, selectedTableId!),
    enabled: open && !!selectedTableId,
  })

  // 额外表归属工作区是否全部解析（跨工作区表需等扫描补全后才能按正确工作区请求）
  const extrasResolved = extraTableIds.every(tid =>
    tables.some(t => t.id === tid) || !!crossTableInfo[tid])
  // 额外表归属工作区签名（进入 query key，解析结果变化时触发重新请求）
  const extraWsKey = extraTableIds.map(tid => crossTableInfo[tid]?.wsId ?? 'local').join(',')

  // 额外表的字段列表（批量加载；跨工作区表按其归属工作区请求）
  const { data: extraFieldsMap = {} } = useQuery<Record<number, Field[]>>({
    queryKey: ['workspaces', workspaceId, 'extra-fields', extraTableIds, extraWsKey],
    queryFn: async () => {
      const result: Record<number, Field[]> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        const wid = crossTableInfo[tid]?.wsId ?? workspaceId
        result[tid] = await fieldApi.list(wid, tid)
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && extrasResolved,
  })

  // 关联表的前 10 行真实数据（用于预览；跨工作区主表按其归属工作区请求）
  const { data: previewRows = [], isLoading: previewLoading } = useQuery({
    queryKey: ['workspaces', primaryTableWsId, 'tables', selectedTableId, 'records', 'preview'],
    queryFn: async () => {
      const resp = await recordApi.list(primaryTableWsId, selectedTableId!, { limit: 10 })
      return resp.items.map(r => {
        const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
        return rest
      }) as Array<Record<string, unknown>>
    },
    enabled: !!selectedTableId && !!workspaceId,
  })

  // 额外表的预览数据（用于 PreviewPanel records_by_table；跨工作区表按其归属工作区请求）
  const { data: extraPreviewMap = {} } = useQuery<Record<number, Array<Record<string, unknown>>>>({
    queryKey: ['workspaces', workspaceId, 'extra-preview', extraTableIds, extraWsKey],
    queryFn: async () => {
      const result: Record<number, Array<Record<string, unknown>>> = {}
      await Promise.all(extraTableIds.map(async (tid) => {
        const wid = crossTableInfo[tid]?.wsId ?? workspaceId
        const resp = await recordApi.list(wid, tid, { limit: 5 })
        result[tid] = resp.items.map(r => {
          const { id: _id, created_at: _ca, updated_at: _ua, created_by: _cb, updated_by: _ub, ...rest } = r as any
          return rest
        })
      }))
      return result
    },
    enabled: extraTableIds.length > 0 && extrasResolved,
  })

  // 跨工作区级联选项（排除当前工作区——本区表直接在额外引用表里选）
  const importWsOptions = useMemo<Array<{ value: string; label: string }>>(
    () => workspaces.filter((w: Workspace) => String(w.id) !== workspaceId).map((w: Workspace) => ({ value: String(w.id), label: w.name })),
    [workspaces, workspaceId],
  )
  const importTableOptions = useMemo<Array<{ value: number; label: string }>>(
    () => importWsTables.filter(t => t.id !== selectedTableId).map(t => ({ value: Number(t.id), label: t.name })),
    [importWsTables, selectedTableId],
  )

  // 跨工作区表名解析：本区 tables 优先，其次 crossTableInfo（级联引入 + 回显扫描）
  const resolveTableName = (tid: number): string | undefined =>
    tables.find(t => t.id === tid)?.name ?? crossTableInfo[tid]?.name

  // 主表名解析：本区表优先，其次 crossTableInfo（跨工作区主表，如 seed 模板的关联表）
  const selectedTableName = selectedTableId !== null ? resolveTableName(selectedTableId) : undefined

  // 关联表下拉选项：本区表 + 跨工作区主表（避免编辑 seed 模板时仅显示 "#id"）
  const tableSelectOptions = useMemo(() => {
    if (selectedTableId === null) return tableOptions
    const existing = tableOptions.some(o => o.value === selectedTableId)
    if (existing) return tableOptions
    const name = resolveTableName(selectedTableId)
    if (name === undefined) return tableOptions
    return [{ value: selectedTableId, label: name }, ...tableOptions]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableOptions, selectedTableId, crossTableInfo, tables])

  // 构建多表字段分组
  const tableGroups = useMemo(() => {
    const groups: Array<{ tableId: number; tableName: string; fields: Field[]; isPrimary: boolean }> = []
    if (selectedTableId !== null && selectedTableName) {
      groups.push({ tableId: selectedTableId, tableName: selectedTableName, fields, isPrimary: true })
    }
    for (const eid of extraTableIds) {
      const tname = resolveTableName(eid)
      const efields = extraFieldsMap[eid] || []
      if (tname) {
        groups.push({ tableId: eid, tableName: tname, fields: efields, isPrimary: false })
      }
    }
    return groups
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTableId, selectedTableName, fields, extraTableIds, extraFieldsMap, tables, crossTableInfo])

  // 构建 recordsByTable
  const recordsByTable = useMemo(() => {
    const result: Record<string, Array<Record<string, unknown>>> = {}
    for (const eid of extraTableIds) {
      const tname = resolveTableName(eid)
      if (tname && extraPreviewMap[eid]) {
        result[tname] = extraPreviewMap[eid]
      }
    }
    return result
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraTableIds, extraPreviewMap, tables, crossTableInfo])

  // extra 表选项（排除已选的主表）
  const extraTableOptions = useMemo(() => {
    return tableOptions.filter(o => o.value !== selectedTableId)
  }, [tableOptions, selectedTableId])

  // 关联视图下拉选项（视图归属主表；主表未选时为空）
  const viewSelectOptions = useMemo(
    () => tableViews.map(v => ({ value: Number(v.id), label: v.name })),
    [tableViews],
  )

  return {
    setCrossTableInfo,
    importWsTables,
    fields,
    previewRows,
    previewLoading,
    importWsOptions,
    importTableOptions,
    selectedTableName,
    tableSelectOptions,
    tableGroups,
    recordsByTable,
    extraTableOptions,
    viewSelectOptions,
  }
}
