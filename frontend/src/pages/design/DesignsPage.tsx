/** 「设计结构」根页（ADR 0109 D1 / D3 / D7）
 *
 * 设计模块收敛为单一工作台：侧栏承载「产品列表 ↔ 结构树」两态（DesignStructureNav），
 * Content 只保留 DSL 编辑器与 3D 视图（DesignEditorPage）。
 * 本页仅负责入口选择：清单就绪后自动打开最近更新的设计（replace 到 /design/:id），
 * 工作区没有设计时在 Content 展示引导空态，不占用侧栏。
 */

import { useEffect, useMemo } from 'react'
import { Empty, Spin, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import { designEditorPath, latestDesignId } from './designOutline'
import { prefetchDesignEditorChunks } from './prefetchEditor'

export {
  DEFAULT_ASSEMBLY_CONTENT, DEFAULT_DESIGN_CONTENT, DEFAULT_PART_CONTENT,
} from './designDefaults'

const { Text } = Typography

export default function DesignsPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const navigate = useNavigate()

  const { data: designs = [], isLoading, isError } = useQuery({
    queryKey: ['designs', wid],
    queryFn: () => designsApi.list(wid),
    enabled: !!wid,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const isViewer = wsDetail?.current_user_role === 'viewer'

  const latestId = useMemo(() => latestDesignId(designs), [designs])

  // 空闲预取编辑器 / 3D chunk（ADR 0086 C9）：默认打开前的窗口也把点击成本移出首屏
  useEffect(() => {
    if (typeof requestIdleCallback === 'function') {
      const id = requestIdleCallback(() => prefetchDesignEditorChunks())
      return () => cancelIdleCallback(id)
    }
    const timer = window.setTimeout(() => prefetchDesignEditorChunks(), 200)
    return () => window.clearTimeout(timer)
  }, [])

  // 进入设计模块直接落到最近更新的产品编辑器（ADR 0109 D3 / 边界 #2）：
  // 清单加载完成后再判定，避免首帧闪空态或误把「加载中」当成「没有设计」
  useEffect(() => {
    if (isLoading || isError || latestId == null) return
    navigate(designEditorPath(wid, latestId), { replace: true })
  }, [isLoading, isError, latestId, wid, navigate])

  if (isLoading || (!isError && latestId != null)) {
    return (
      <div className="cn-design-root-state" data-testid="designs-redirecting">
        <Spin />
      </div>
    )
  }

  return (
    <div className="cn-design-root-state" data-testid="designs-empty">
      <Empty
        description={isError
          ? '设计清单加载失败，请稍后重试'
          : isViewer
            ? '当前工作区还没有结构设计'
            : '还没有结构设计，从左侧产品列表新建第一个设计'}
      />
      {!isViewer && !isError && (
        <Text type="secondary" className="cn-design-root-hint">
          新建后可直接在右侧编辑 DSL 并实时预览 3D 结构。
        </Text>
      )}
    </div>
  )
}
