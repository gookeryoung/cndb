/** 工作区列表 —— 卡片式. */
import { useEffect } from 'react'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import { View, Text, ScrollView } from '@tarojs/components'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/store/auth'
import { workspaceApi } from '@/api/workspace'
import Loading from '@/components/Loading'
import EmptyState from '@/components/EmptyState'
import './index.scss'

function VisibilityTag({ value }: { value: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    public: { cls: 'tag-green', label: '公开' },
    member: { cls: 'tag-blue', label: '成员' },
    private: { cls: 'tag-default', label: '私有' },
  }
  const conf = map[value] || map.member
  return (
    <View className={conf.cls}>
      <Text>{conf.label}</Text>
    </View>
  )
}

export default function WorkspacesPage() {
  const { user, isAuthenticated } = useAuth()
  const queryClient = useQueryClient()

  const { data: workspaces, isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: workspaceApi.list,
    enabled: isAuthenticated,
    staleTime: 30_000,
  })

  const pin = useMutation({
    mutationFn: (wid: number) => workspaceApi.togglePin(wid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })

  usePullDownRefresh(async () => {
    await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    Taro.stopPullDownRefresh()
  })

  useEffect(() => {
    if (!isAuthenticated && !isLoading) {
      Taro.reLaunch({ url: '/pages/login/index' })
    }
  }, [isAuthenticated, isLoading])

  if (isLoading || !isAuthenticated) {
    return <Loading text='加载工作区...' />
  }

  const list = (workspaces || []).slice().sort(
    (a, b) => Number(!!b.pinned) - Number(!!a.pinned) || Number(a.id) - Number(b.id),
  )

  if (list.length === 0) {
    return <EmptyState text='还没有工作区' />
  }

  return (
    <View className='workspaces-page'>
      <View className='page-header'>
        <View>
          <Text className='page-title'>我的工作区</Text>
          <Text className='page-sub'>你好，{user?.nickname || user?.username}</Text>
        </View>
      </View>

      <ScrollView scrollY className='workspaces-scroll'>
        {list.map((ws) => (
          <View
            className='ws-card'
            key={ws.id}
            onClick={() => Taro.navigateTo({ url: `/pages/tables/${ws.id}/index` })}
          >
            <View className='ws-card-header'>
              <View className='ws-card-title-row'>
                {ws.pinned && <View className='tag-gold ws-tag-pin'><Text>📌</Text></View>}
                <Text className='ws-name'>{ws.name}</Text>
              </View>
              <VisibilityTag value={ws.visibility || 'member'} />
            </View>

            {ws.description && (
              <Text className='ws-desc'>{ws.description}</Text>
            )}

            <View className='ws-card-footer'>
              <View className='ws-stats'>
                <Text className='ws-stat'>{ws.table_count ?? 0} 表</Text>
                <Text className='ws-stat'>{ws.member_count ?? 1} 成员</Text>
              </View>
              <View
                className='ws-pin-btn'
                onClick={(e) => { e.stopPropagation(); pin.mutate(ws.id) }}
              >
                {ws.pinned ? '取消置顶' : '置顶'}
              </View>
            </View>
          </View>
        ))}
      </ScrollView>
    </View>
  )
}
