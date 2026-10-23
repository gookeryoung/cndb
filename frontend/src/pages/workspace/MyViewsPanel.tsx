/** 主页「我的视图」面板 — 个人收藏的视图列表（ADR 0021）.
 *
 * 交互口径：
 *  - 行内展开详情：视图类型、`工作区 › 数据表`、可见性 / 默认标记、筛选与排序条数；
 *  - 打开视图不要求先展开：收起态行尾即有「打开」图标按钮，深链
 *    `/w/{wid}/tables/{tid}?view={vid}` 一步直达（与 GridPage 的 `?view=` 激活逻辑一致），
 *    展开区内的「打开视图」按钮保留给读完详情再进入的场景；
 *  - 行首把手拖拽调整顺序，顺序即 `preferences.favorite_views`（全量替换，乐观更新）；
 *  - 取消收藏走 `useToggleFavoriteView`（先读最新偏好再替换，避免用过期列表覆盖其他标签页的写入）。
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Empty, Skeleton, Tag, Tooltip, App as AntApp } from 'antd'
import {
  ApartmentOutlined, AppstoreOutlined, ArrowRightOutlined, BarChartOutlined, CalendarOutlined,
  CaretRightOutlined, HolderOutlined, LineChartOutlined, NodeIndexOutlined,
  PictureOutlined, StarFilled, StockOutlined, TableOutlined,
} from '@ant-design/icons'
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter,
  useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useNavigate } from 'react-router-dom'
import { useFavoriteViews, useSetFavoriteViews, useToggleFavoriteView } from '@/hooks/useFavoriteViews'
import type { FavoriteViewSummary } from '@/api'

/** 视图类型 → 中文名（与视图栏 `viewModes` 的 ViewMode 集合对齐） */
const VIEW_TYPE_LABEL: Record<string, string> = {
  grid: '表格', tree: '树形', kanban: '看板', gallery: '画廊', calendar: '日历', gantt: '甘特图',
  wbs: 'WBS', matrix: '矩阵', chart: '图表', kline: 'K 线图', flow: '流程图',
}

/** 视图类型 → 行首图标 */
const VIEW_TYPE_ICON: Record<string, ReactNode> = {
  grid: <TableOutlined />,
  tree: <ApartmentOutlined />,
  kanban: <AppstoreOutlined />,
  gallery: <PictureOutlined />,
  calendar: <CalendarOutlined />,
  gantt: <BarChartOutlined />,
  wbs: <ApartmentOutlined />,
  matrix: <TableOutlined />,
  chart: <LineChartOutlined />,
  kline: <StockOutlined />,
  flow: <NodeIndexOutlined />,
}

const VISIBILITY_LABEL: Record<string, string> = {
  table: '全表可见', shared: '指定成员', private: '仅本人',
}

const VISIBILITY_COLOR: Record<string, string> = {
  table: 'default', shared: 'cyan', private: 'purple',
}

/** 单个收藏视图行 —— 拖拽监听只挂在把手上，行点击只做展开 / 收起 */
function MyViewRow({
  view, expanded, onToggle, onOpen, onUnfavorite,
}: {
  view: FavoriteViewSummary
  expanded: boolean
  onToggle: () => void
  onOpen: () => void
  onUnfavorite: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(view.view_id),
  })
  const visibility = view.visibility || 'table'

  return (
    <div
      ref={setNodeRef}
      className={`cn-myviews-row${expanded ? ' is-expanded' : ''}`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
        zIndex: isDragging ? 2 : undefined,
      }}
      data-testid={`my-view-row-${view.view_id}`}
    >
      <div className="cn-myviews-row-main" onClick={onToggle}>
        <Tooltip title="拖拽调整顺序">
          <Button
            type="text"
            size="small"
            className="cn-myviews-drag"
            aria-label={`拖拽排序「${view.name}」`}
            data-testid={`my-view-drag-${view.view_id}`}
            icon={<HolderOutlined />}
            onClick={(e) => e.stopPropagation()}
            {...attributes}
            {...listeners}
          />
        </Tooltip>

        <Tooltip title={expanded ? '收起详情' : '展开详情'}>
          <Button
            type="text"
            size="small"
            className="cn-myviews-toggle"
            aria-expanded={expanded}
            aria-label={`${expanded ? '收起' : '展开'}「${view.name}」`}
            data-testid={`my-view-expand-${view.view_id}`}
            icon={<CaretRightOutlined rotate={expanded ? 90 : 0} />}
            onClick={(e) => { e.stopPropagation(); onToggle() }}
          />
        </Tooltip>

        <span className="cn-myviews-type-icon" aria-hidden>{VIEW_TYPE_ICON[view.view_type] ?? <TableOutlined />}</span>

        <div className="cn-myviews-text">
          <span className="cn-myviews-name" title={view.name}>{view.name}</span>
          <span className="cn-myviews-path" title={`${view.workspace_name} › ${view.table_name}`}>
            {view.workspace_name} › {view.table_name}
          </span>
        </div>

        {view.is_default && <Tag color="blue" className="cn-myviews-row-tag">默认</Tag>}

        {/* 收起态的直达入口：无需先展开详情再点「打开视图」 */}
        <Tooltip title="打开视图">
          <Button
            type="text"
            size="small"
            className="cn-myviews-open"
            aria-label={`打开「${view.name}」`}
            data-testid={`my-view-open-${view.view_id}`}
            icon={<ArrowRightOutlined />}
            onClick={(e) => { e.stopPropagation(); onOpen() }}
          />
        </Tooltip>
      </div>

      {expanded && (
        <div
          className="cn-myviews-detail"
          data-testid={`my-view-detail-${view.view_id}`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="cn-myviews-detail-row">
            <span className="cn-myviews-detail-label">类型</span>
            <Tag color="geekblue">{VIEW_TYPE_LABEL[view.view_type] ?? view.view_type}</Tag>
            <Tag color={VISIBILITY_COLOR[visibility] ?? 'default'}>
              {VISIBILITY_LABEL[visibility] ?? visibility}
            </Tag>
          </div>
          <div className="cn-myviews-detail-row">
            <span className="cn-myviews-detail-label">位置</span>
            <span className="cn-myviews-detail-value">{view.workspace_name} › {view.table_name}</span>
          </div>
          <div className="cn-myviews-detail-row">
            <span className="cn-myviews-detail-label">规则</span>
            <span className="cn-myviews-detail-value">
              筛选 {view.filter_count} 条 · 排序 {view.sort_count} 条
            </span>
          </div>
          <div className="cn-myviews-detail-actions">
            <Button type="primary" size="small" onClick={onOpen} data-testid={`my-view-open-detail-${view.view_id}`}>
              打开视图
            </Button>
            <Button
              size="small"
              icon={<StarFilled style={{ color: '#f59e0b' }} />}
              onClick={onUnfavorite}
              data-testid={`my-view-unfavorite-${view.view_id}`}
            >
              取消收藏
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function MyViewsPanel() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const { data: views = [], isLoading } = useFavoriteViews()
  const setFavoriteViews = useSetFavoriteViews()
  const toggleFavorite = useToggleFavoriteView()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const ids = useMemo(() => views.map(v => String(v.view_id)), [views])

  const toggleExpand = (viewId: number | string) => {
    const key = String(viewId)
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const from = ids.indexOf(String(active.id))
    const to = ids.indexOf(String(over.id))
    if (from < 0 || to < 0) return
    const nextIds = arrayMove(ids, from, to).map(Number)
    setFavoriteViews.mutate(nextIds, {
      onError: (err) => message.error(err instanceof Error ? err.message : '保存排序失败，请重试'),
    })
  }

  const handleUnfavorite = (view: FavoriteViewSummary) => {
    toggleFavorite.mutate(
      { viewId: view.view_id, favorited: false },
      {
        onSuccess: () => message.success(`已取消收藏「${view.name}」`),
        onError: (err) => message.error(err instanceof Error ? err.message : '取消收藏失败，请重试'),
      },
    )
  }

  const handleOpen = (view: FavoriteViewSummary) => {
    navigate(`/w/${view.workspace_id}/tables/${view.table_id}?view=${view.view_id}`)
  }

  return (
    <section className="cn-myviews-panel" data-testid="my-views-panel" aria-label="我的视图">
      <header className="cn-myviews-head">
        <StarFilled style={{ color: '#f59e0b' }} />
        <span className="cn-myviews-title">我的视图</span>
        <span className="cn-myviews-count" data-testid="my-views-count">{views.length}</span>
      </header>

      {isLoading ? (
        <div data-testid="my-views-loading">
          <Skeleton active title={false} paragraph={{ rows: 3, width: '100%' }} />
        </div>
      ) : views.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={(
            <div className="cn-myviews-empty" data-testid="my-views-empty">
              <div>还没有收藏的视图</div>
              <div className="cn-myviews-empty-hint">在数据表的视图栏点击星标即可收藏</div>
            </div>
          )}
        />
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={ids} strategy={verticalListSortingStrategy}>
            <div className="cn-myviews-list">
              {views.map(view => (
                <MyViewRow
                  key={view.view_id}
                  view={view}
                  expanded={expandedIds.has(String(view.view_id))}
                  onToggle={() => toggleExpand(view.view_id)}
                  onOpen={() => handleOpen(view)}
                  onUnfavorite={() => handleUnfavorite(view)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </section>
  )
}
