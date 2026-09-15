/** 新建行页 —— 简化表单. */
import { useState } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { View, Text, ScrollView, Input, Button } from '@tarojs/components'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi } from '@/api/table'
import Loading from '@/components/Loading'
import './index.scss'

export default function RecordNewPage() {
  const router = useRouter()
  const wid = router.params.wid!
  const tid = router.params.tid!
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, string>>({})

  const { data: table, isLoading } = useQuery({
    queryKey: ['table', wid, tid],
    queryFn: () => tableApi.get(wid, tid),
  })

  const createRow = useMutation({
    mutationFn: () => {
      const filtered: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(values)) {
        if (v !== '') {
          const field = table?.fields.find((f) => f.name === k)
          // 数字类型尝试转数字
          if (field?.field_type === 'number' || field?.field_type === 'float') {
            const n = Number(v)
            if (!Number.isNaN(n)) filtered[k] = n
          } else {
            filtered[k] = v
          }
        }
      }
      return recordApi.create(wid, tid, filtered)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', wid, tid] })
      Taro.showToast({ title: '已创建', icon: 'success' })
      setTimeout(() => Taro.navigateBack(), 500)
    },
    onError: (err) => {
      Taro.showToast({
        title: err instanceof Error ? err.message : '创建失败',
        icon: 'none',
      })
    },
  })

  const editableFields = (table?.fields || []).filter((f) => {
    const t = f.field_type
    return ['text', 'longtext', 'number', 'float', 'select'].includes(t) && !f.hidden
  })

  if (isLoading) return <Loading text='加载中...' />

  return (
    <View className='record-new'>
      <ScrollView scrollY className='new-scroll'>
        <View className='form-card'>
          <Text className='form-title'>新增一行</Text>
          {editableFields.map((field) => (
            <View className='form-field' key={field.id}>
              <Text className='form-label'>
                {field.name}
                {field.required && <Text className='required'> *</Text>}
              </Text>
              <Input
                className='form-input'
                value={values[field.name] || ''}
                placeholder={`请输入 ${field.name}`}
                onInput={(e) => setValues({ ...values, [field.name]: e.detail.value })}
              />
            </View>
          ))}
        </View>
      </ScrollView>

      <View className='new-actions'>
        <Button
          className='btn-primary'
          type='primary'
          loading={createRow.isPending}
          onClick={() => createRow.mutate()}
        >
          创建
        </Button>
      </View>
    </View>
  )
}
