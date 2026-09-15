/** Grid 主视图 —— 行列表 + 视图切换 + 悬浮新增按钮. */
import { useMemo, useState } from 'react'
import Taro, { useRouter, usePullDownRefresh } from '@tarojs/taro'
import { View, Text, ScrollView, Button } from '@tarojs/components'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, recordApi, viewApi } from '@/api/table'
import type { Field } from '@/api/table'
import FieldRenderer from '@/components/FieldRenderer'
import Loading from '@/components/Loading'
import EmptyState from '@/components/EmptyState'
import './index.scss'

const PAGE_SIZE = 50

export default function GridPage() {
  const router = useRouter()
  const wid = router.params.wid!
  const tid = router.params.tid!
  const queryClient = useQueryClient()
  const [offset, setOffset] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)

  // 表结构
  const { data: table, isLoading: tableLoading } = useQuery({
    queryKey: ['table', wid, tid],
    queryFn: () => tableApi.get(wid, tid),
  })

  // 视图列表
  const { data: views = [] } = useQuery({
    queryKey: ['table-views', wid, tid],
    queryFn: () => viewApi.list(wid, tid),
    enabled: !!table,
  })

  // 选中视图
  const activeView = useMemo(() => {
    const vid = router.params.view
    if (vid) return views.find(v => String(v.id) === vid) || views.find(v => v.default)
    return views.find(v => v.default) || views[0]
  }, [views, router.params.view])

  // 行列表
  const { data: rowList, isFetching, refetch } = useQuery({
    queryKey: ['table-records', wid, tid, activeView?.id, offset],
    queryFn: () => recordApi.list(wid, tid, {
      offset,
      limit: PAGE_SIZE,
      filters: activeView?.filters as any,
      sorts: activeView?.sortings as any,
    }),
    enabled: !!table,
    staleTime: 30_000,
  })

  // 批量删除
  const bulkDelete = useMutation({
    mutationFn: (ids: Array<number | string>) => recordApi.bulkDelete(wid, tid, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table-records', wid, tid] })
      Taro.showToast({ title: '已删除', icon: 'success' })
    },
  })

  usePullDownRefresh(async () => {
    await refetch()
    Taro.stopPullDownRefresh()
  })

  async function loadMore() {
    if (!rowList || loadingMore) return
    if (offset + PAGE_SIZE >= rowList.total) return
    setLoadingMore(true)
    setOffset((prev) => prev + PAGE_SIZE)
    setLoadingMore(false)
  }

  // 字段过滤：排除 hidden，取前 5 个
  const visibleFields: Field[] = (table?.fields || []).filter((f) => !f.hidden).slice(0, 5)

  if (tableLoading || isFetching && !rowList) {
    return <Loading text='加载中...' />
  }
  if (!table) {
    return <EmptyState text='表不存在或无权限' />
  }
  if (!activeView) {
    return <EmptyState text='还没有视图' />
  }

  const rows = rowList?.items || []
  const hasMore = rowList ? offset + PAGE_SIZE < rowList.total : false

  return (
    <View className='grid-page'>
      {/* 顶部栏 */}
      <View className='grid-header'>
        <View className='grid-title-row'>
          <Text className='grid-title'>{table.name}</Text>
          {table.record_count != null && table.record_count > 0 && (
            <View className='tag-blue grid-count-tag'><Text>{table.record_count}</Text></View>
          )}
        </View>

        {/* 视图 Tab（横向滚动） */}
        {views.length > 1 && (
          <ScrollView scrollX className='grid-view-tabs'>
            <View className='grid-view-tabs-inner'>
              {views.map((v) => (
                <View
                  key={v.id}
                  className={`grid-view-tab ${activeView.id === v.id ? 'active' : ''}`}
                  onClick={() => {
                    setOffset(0)
                    // 重新用新视图加载
                    refetch()
                  }}
                >
                  <Text>{v.name}</Text>
                  {v.default && <View className='tag-blue tag-mini'><Text>默认</Text></View>}
                </View>
              ))}
            </View>
          </ScrollView>
        )}
      </View>

      {/* 行列表 */}
      <ScrollView
        scrollY
        className='grid-scroll'
        lowerThreshold={200}
        onScrollToLower={loadMore}
        enableBackToTop
      >
        {rows.length === 0 ? (
          <EmptyState
            text='暂无数据'
            action='+ 新增行'
            onAction={() => Taro.navigateTo({ url: `/pages/record/new/${wid}/${tid}/index` })}
          />
        ) : (
          <View className='grid-rows'>
            {rows.map((row) => (
              <View
                className='grid-row'
                key={String(row.id)}
                onClick={() => Taro.navigateTo({
                  url: `/pages/record/${wid}/${tid}/${row.id}/index`,
                })}
                onLongPress={() => {
                  Taro.showActionSheet({
                    itemList: ['删除这行'],
                    success: (res) => {
                      if (res.tapIndex === 0) {
                        Taro.showModal({
                          title: '确定删除？',
                          content: '此操作不可恢复',
                          success: (r) => {
                            if (r.confirm) bulkDelete.mutate([row.id as number])
                          },
                        })
                      }
                    },
                  })
                }}
              >
                {visibleFields.map((field) => (
                  <View className='grid-cell' key={field.id}>
                    <Text className='grid-cell-label'>{field.name}</Text>
                    <View className='grid-cell-value'>
                      <FieldRenderer field={field} value={row[field.name]} />
                    </View>
                  </View>
                ))}
              </View>
            ))}
            {loadingMore && <Loading text='加载更多...' small />}
            {!hasMore && rows.length > 0 && (
              <Text className='grid-end'>已加载全部数据</Text>
            )}
          </View>
        )}
      </ScrollView>

      {/* 悬浮新增按钮 */}
      <View
        className='fab-add'
        onClick={() => Taro.navigateTo({ url: `/pages/record/new/${wid}/${tid}/index` })}
      >
        <Text className='fab-text'>+</Text>
      </View>
    </View>
  )
}
