/** Grid 视图切换栏 — 可拖拽视图 Segmented + 右侧紧凑按钮组（从 GridPage 抽出）. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Dropdown, Input, Segmented, Space, Tooltip } from 'antd'
import {
  PlusOutlined, DeleteOutlined, FilterOutlined, MoreOutlined,
  SearchOutlined, SettingOutlined, EditOutlined, ImportOutlined, ExportOutlined,
  HolderOutlined, LeftOutlined, RightOutlined,
} from '@ant-design/icons'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { viewApi } from '@/api'
import type { View } from '@/api'
import { Tag, Modal, App as AntApp } from 'antd'
import type { ViewMode } from './views/viewModes'

/** 可拖拽视图 Tab 标签 —— 供 Segmented.options.label 使用，配合 DndContext + SortableContext. */
function DndViewTab({ view, active, onClick }: { view: View; active: boolean; onClick: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: String(view.id),
  })
  return (
    <span
      ref={setNodeRef}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
        cursor: active ? 'pointer' : 'grab',
        userSelect: 'none',
      }}
      data-testid={`view-tab-${view.id}`}
      {...attributes}
      {...listeners}
      onClick={(e) => { e.stopPropagation(); onClick() }}
    >
      <HolderOutlined style={{ fontSize: 10, color: '#bfbfbf' }} />
      <span>{view.name}</span>
      {view.is_default && <Tag color="blue" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>默认</Tag>}
    </span>
  )
}

interface GridViewBarProps {
  wid: string
  tid: string
  views: View[]
  activeViewId: string | number | null
  mode: ViewMode
  modeButtons: ReadonlyArray<{ mode: ViewMode; tooltip: string; icon: React.ReactNode }>
  showModeSwitch: boolean
  hasFilters: boolean
  searchQuery: string
  onSearchChange: (q: string) => void
  onSelectView: (v: View | null) => void
  onModeChange: (m: ViewMode) => void
  onDragEnd: (event: DragEndEvent) => void
  onCreate: () => void
  onEdit: () => void
  onDelete: () => void
  onImport: () => void
  onOpenViewConfig: () => void
  onOpenDisplaySettings: () => void
}

/** 根据可滚动容器的 scrollLeft / scrollWidth / clientWidth 计算左右两端是否可继续滚动. */
function computeScrollState(el: HTMLElement | null): { canLeft: boolean; canRight: boolean } {
  if (!el) return { canLeft: false, canRight: false }
  const sl = el.scrollLeft
  const maxLeft = el.scrollWidth - el.clientWidth
  // 容差 2px 避免 subpixel 误差导致边界抖动
  return { canLeft: sl > 2, canRight: sl < maxLeft - 2 }
}

export default function GridViewBar({
  wid, tid, views, activeViewId, mode, modeButtons, showModeSwitch,
  hasFilters, searchQuery, onSearchChange, onSelectView, onModeChange, onDragEnd,
  onCreate, onEdit, onDelete, onImport,
  onOpenViewConfig, onOpenDisplaySettings,
}: GridViewBarProps) {
  const { message } = AntApp.useApp()
  const viewDragSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // 滚动控制：获取 Segmented 内部的可横向滚动容器
  const segmentedWrapRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLElement | null>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  /** 查询并缓存内部的 .ant-segmented-group 元素 */
  const resolveScrollContainer = useCallback((): HTMLElement | null => {
    const el = segmentedWrapRef.current?.querySelector('.cn-segmented > .ant-segmented-group') as HTMLElement | null
    scrollContainerRef.current = el
    return el
  }, [])

  /** 根据 DOM 当前状态更新左右可滚动标记 */
  const refreshScrollState = useCallback(() => {
    const el = resolveScrollContainer()
    const s = computeScrollState(el)
    setCanScrollLeft(s.canLeft)
    setCanScrollRight(s.canRight)
  }, [resolveScrollContainer])

  /** 平滑横向滚动指定像素 */
  const scrollBy = useCallback((delta: number) => {
    const el = scrollContainerRef.current
    if (!el) return
    el.scrollBy({ left: delta, behavior: 'smooth' })
  }, [])

  /** 选中项若不在可见区域内，平滑滚动使其完全可见 */
  const scrollSelectedIntoView = useCallback(() => {
    const container = resolveScrollContainer()
    if (!container) return
    const selected = container.querySelector('.ant-segmented-item-selected') as HTMLElement | null
    if (!selected) return
    const cRect = container.getBoundingClientRect()
    const sRect = selected.getBoundingClientRect()
    if (sRect.left < cRect.left || sRect.right > cRect.right) {
      selected.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' })
    }
  }, [resolveScrollContainer])

  // 挂载后绑定 scroll 监听 + ResizeObserver；视图变化、窗口尺寸变化时刷新可滚动状态
  useEffect(() => {
    const container = resolveScrollContainer()
    if (!container) return

    const onScroll = () => refreshScrollState()
    container.addEventListener('scroll', onScroll, { passive: true })

    let ro: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => refreshScrollState())
      ro.observe(container)
      // 同时观察 wrap 根，防止外部 flex 变化导致宽度变化
      if (segmentedWrapRef.current) ro.observe(segmentedWrapRef.current)
    }

    refreshScrollState()
    return () => {
      container.removeEventListener('scroll', onScroll)
      ro?.disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [views.length])

  // activeViewId 变化时，选中项自动滚入可见区
  useEffect(() => {
    // 用 rAF 等 Segmented indicator 布局完成
    const raf = requestAnimationFrame(() => {
      scrollSelectedIntoView()
      refreshScrollState()
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeViewId, views.length])

  // 视图 Segmented 选项（支持拖拽排序）
  // 注意：loadView 未用 useCallback 包裹，随渲染重建；此处直接计算，避免 lint 缺依赖警告
  const segmentedOptions = views.map(v => ({
    label: (
      <DndViewTab
        view={v}
        active={activeViewId != null && String(v.id) === String(activeViewId)}
        onClick={() => onSelectView(v)}
      />
    ),
    value: String(v.id),
  }))

  return (
    <div style={{
      padding: '0 8px 0 0',
      background: 'var(--cn-bg-container)',
      borderBottom: '1px solid var(--cn-border)',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      minHeight: 36,
    }}>
      {/* Segmented —— flex:1 占满弹性空间，min-width:0 允许在窄屏下被压缩从而触发内部滚动 */}
      <div
        ref={segmentedWrapRef}
        className={[
          'cn-segmented-wrap',
          canScrollLeft ? 'is-scroll-left' : '',
          canScrollRight ? 'is-scroll-right' : '',
        ].filter(Boolean).join(' ')}
        style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', padding: '4px 0 4px 16px' }}
      >
        <DndContext sensors={viewDragSensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={views.map(v => String(v.id))} strategy={horizontalListSortingStrategy}>
            <Segmented
              value={activeViewId != null ? String(activeViewId) : undefined}
              onChange={(v) => {
                const key = String(v)
                onSelectView(views.find(vv => String(vv.id) === key) || null)
              }}
              options={segmentedOptions}
              className="cn-segmented"
              style={{ width: '100%' }}
            />
          </SortableContext>
        </DndContext>

        {/* 左右滚动箭头按钮 —— 仅对应方向可滚动时出现；置于渐隐遮罩之上 */}
        {canScrollLeft && (
          <button
            type="button"
            className="cn-seg-scroll-btn cn-seg-scroll-btn-left"
            aria-label="向左滚动视图列表"
            onClick={() => scrollBy(-160)}
          >
            <LeftOutlined />
          </button>
        )}
        {canScrollRight && (
          <button
            type="button"
            className="cn-seg-scroll-btn cn-seg-scroll-btn-right"
            aria-label="向右滚动视图列表"
            onClick={() => scrollBy(160)}
          >
            <RightOutlined />
          </button>
        )}
      </div>

      {/* 右侧紧凑按钮组 —— flex-shrink:0 保证不被 Segmented 挤压 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, paddingRight: 8 }}>
        {/* 视图新建（常显）+ 更多操作收进 Dropdown */}
        <Tooltip title="新建视图">
          <Button size="small" type="text" icon={<PlusOutlined />} onClick={onCreate} />
        </Tooltip>
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              {
                key: 'edit',
                icon: <EditOutlined />,
                label: '编辑当前视图',
                disabled: !activeView,
                onClick: onEdit,
              },
              {
                key: 'delete',
                icon: <DeleteOutlined />,
                danger: true,
                label: '删除当前视图',
                disabled: !activeView,
                onClick: () => {
                  if (activeView) {
                    Modal.confirm({
                      title: '确定删除此视图？',
                      content: activeView.name,
                      okText: '删除',
                      okType: 'danger',
                      cancelText: '取消',
                      onOk: () => activeViewId != null && onDelete(),
                    })
                  }
                },
              },
              { type: 'divider' },
              { key: 'import', icon: <ImportOutlined />, label: '导入视图', onClick: onImport },
              {
                key: 'export',
                icon: <ExportOutlined />,
                label: '导出视图',
                onClick: async () => {
                  try {
                    const data = await viewApi.exportViews(wid, tid)
                    if (!data.length) {
                      message.warning('当前表暂无视图可导出')
                      return
                    }
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = 'views.json'
                    document.body.appendChild(a)
                    a.click()
                    document.body.removeChild(a)
                    URL.revokeObjectURL(url)
                    message.success(`已导出 ${data.length} 个视图`)
                  } catch (err) {
                    message.error(err instanceof Error ? err.message : '导出失败')
                  }
                },
              },
            ],
          }}
        >
          <Tooltip title="视图更多操作">
            <Button size="small" type="text" icon={<MoreOutlined />} />
          </Tooltip>
        </Dropdown>

        <div style={{ width: 1, height: 16, background: 'var(--cn-border)', margin: '0 4px' }} />

        {/* 视图模式切换 —— 仅渲染数据表实际拥有的视图类型；仅 grid 一种时隐藏 */}
        {showModeSwitch && (
          <Space.Compact size="small" data-testid="view-mode-switch">
            {modeButtons.map((b) => (
              <Tooltip key={b.mode} title={b.tooltip}>
                <Button
                  size="small"
                  type={mode === b.mode ? 'primary' : 'default'}
                  icon={b.icon}
                  data-mode={b.mode}
                  onClick={() => onModeChange(b.mode)}
                />
              </Tooltip>
            ))}
          </Space.Compact>
        )}

        <Input.Search
          size="small"
          placeholder="搜索当前视图..."
          allowClear
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={e => onSearchChange(e.target.value)}
          style={{ width: 160 }}
        />
        <Tooltip title="筛选规则：按字段条件过滤当前视图的行，规则保存在视图中">
          <Button
            size="small"
            icon={<FilterOutlined />}
            type={hasFilters ? 'primary' : 'default'}
            data-testid="view-filter-btn"
            onClick={onOpenViewConfig}
          />
        </Tooltip>
        <Tooltip title="显示模式：设置行密度、边框、斑马纹等（对所有视图生效）">
          <Button
            size="small"
            icon={<SettingOutlined />}
            data-testid="display-settings-btn"
            onClick={onOpenDisplaySettings}
          />
        </Tooltip>
      </div>
    </div>
  )
}
