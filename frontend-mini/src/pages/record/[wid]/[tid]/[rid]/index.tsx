/** 行详情页. */
import { useMemo, useState } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { View, Text, ScrollView, Button, Input } from '@tarojs/components'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi } from '@/api/table'
import type { Field } from '@/api/table'
import FieldRenderer from '@/components/FieldRenderer'
import Loading from '@/components/Loading'
import EmptyState from '@/components/EmptyState'
import './index.scss'

export default function RecordDetailPage() {
  const router = useRouter()
  const wid = router.params.wid!
  const tid = router.params.tid!
  const rid = router.params.rid!
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})

  // 表结构（字段定义）
  const { data: table, isLoading: tableLoading } = useQuery({
    queryKey: ['table', wid, tid],
    queryFn: () => tableApi.get(wid, tid),
  })

  // 行数据
  const { data: row, isLoading: rowLoading } = useQuery({
    queryKey: ['record', wid, tid, rid],
    queryFn: () => recordApi.get(wid, tid, rid),
    enabled: !!table,
  })

  // 更新行
  const updateRow = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      recordApi.update(wid, tid, rid, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['record', wid, tid, rid] })
      queryClient.invalidateQueries({ queryKey: ['table-records', wid, tid] })
      Taro.showToast({ title: '已保存', icon: 'success' })
      setEditing(false)
    },
    onError: (err) => {
      Taro.showToast({
        title: err instanceof Error ? err.message : '保存失败',
        icon: 'none',
      })
    },
  })

  // 只展示 text / number / float / select / multiselect / date / datetime 类型的字段可编辑
  const editableFields = useMemo(() => {
    return (table?.fields || []).filter((f) => {
      const t = f.field_type
      return ['text', 'longtext', 'number', 'float', 'select', 'multiselect'].includes(t)
    })
  }, [table])

  function handleStartEdit() {
    if (!row) return
    const init: Record<string, unknown> = {}
    for (const f of editableFields) {
      init[f.name] = row[f.name] ?? ''
    }
    setDraft(init)
    setEditing(true)
  }

  function handleSave() {
    // 过滤空字符串（避免误清数据）
    const values: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(draft)) {
      if (v !== '' && v !== undefined && v !== null) values[k] = v
    }
    updateRow.mutate(values)
  }

  if (tableLoading || rowLoading) {
    return <Loading text='加载中...' />
  }
  if (!table || !row) {
    return <EmptyState text='数据不存在' />
  }

  return (
    <View className='record-detail'>
      <ScrollView scrollY className='detail-scroll'>
        {/* 字段分组展示 */}
        <View className='field-group'>
          <View className='group-header'>
            <Text className='group-title'>基本信息</Text>
          </View>
          <View className='field-list'>
            {(table.fields as Field[]).filter((f) => !f.hidden).map((field) => (
              <View className='field-item' key={field.id}>
                <Text className='field-name'>{field.name}</Text>
                {editing && editableFields.some((ef) => ef.id === field.id) ? (
                  <Input
                    className='field-input'
                    value={String(draft[field.name] ?? '')}
                    placeholder={`输入 ${field.name}`}
                    onInput={(e) => setDraft({ ...draft, [field.name]: e.detail.value })}
                  />
                ) : (
                  <View className='field-value'>
                    <FieldRenderer field={field} value={row[field.name]} />
                  </View>
                )}
              </View>
            ))}
          </View>
        </View>

        {/* 元信息 */}
        <View className='meta-section'>
          <Text className='meta-item'>创建: {formatDate(row.created_at as string)}</Text>
          {row.updated_at && (
            <Text className='meta-item'>更新: {formatDate(row.updated_at as string)}</Text>
          )}
        </View>
      </ScrollView>

      {/* 底部操作栏 */}
      <View className='detail-actions'>
        {!editing ? (
          <Button className='btn-primary' type='primary' onClick={handleStartEdit}>
            编辑
          </Button>
        ) : (
          <>
            <Button className='btn-cancel' onClick={() => setEditing(false)}>取消</Button>
            <Button className='btn-primary' type='primary' loading={updateRow.isPending} onClick={handleSave}>
              保存
            </Button>
          </>
        )}
      </View>
    </View>
  )
}

function formatDate(s: string): string {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 16)
}
