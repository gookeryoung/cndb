/** 表列表页. */
import Taro, { useRouter } from '@tarojs/taro'
import { View, Text } from '@tarojs/components'
import { useQuery } from '@tanstack/react-query'
import { tableApi } from '@/api/table'
import Loading from '@/components/Loading'
import EmptyState from '@/components/EmptyState'
import './index.scss'

export default function TablesListPage() {
  const router = useRouter()
  const wid = router.params.wid!

  const { data: tables, isLoading } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid),
  })

  const list = tables || []

  return (
    <View className='tables-page'>
      {isLoading ? (
        <Loading text='加载表列表...' />
      ) : list.length === 0 ? (
        <EmptyState text='还没有表，请在 PC 端创建' />
      ) : (
        <View className='tables-list'>
          {list.map((t) => (
            <View
              className='table-card'
              key={t.id}
              onClick={() => Taro.navigateTo({ url: `/pages/grid/${wid}/${t.id}/index` })}
            >
              <View className='table-card-header'>
                <Text className='table-name'>{t.name}</Text>
                {t.record_count != null && (
                  <Text className='table-count'>{t.record_count} 条</Text>
                )}
              </View>
              {t.description && (
                <Text className='table-desc'>{t.description}</Text>
              )}
            </View>
          ))}
        </View>
      )}
    </View>
  )
}
