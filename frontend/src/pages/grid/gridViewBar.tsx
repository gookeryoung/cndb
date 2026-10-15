/** Grid 视图切换栏 — 可拖拽视图 Segmented + 右侧紧凑按钮组（从 GridPage 抽出）.
 *
 * 移动端（<768px）布局：视图 Segmented 占满剩余宽度（首要入口，支持横向滚动），
 * 右侧仅保留「视图模式下拉 + 筛选 + 更多」三个控件；新建/编辑/删除/导入/导出/
 * 表格设置收进「更多」菜单，搜索折叠为可展开的第二行。桌面端布局保持不变。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Dropdown, Input, Segmented, Space, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  PlusOutlined, DeleteOutlined, FilterOutlined, MoreOutlined,
  SearchOutlined, SettingOutlined, EditOutlined, ImportOutlined, ExportOutlined,
  HolderOutlined, LeftOutlined, RightOutlined, DownOutlined,
} from '@ant-design/icons'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { viewApi } from '@/api'
import type { View } from '@/api'
import { Tag, App as AntApp } from 'antd'
import { useResponsive } from '@/hooks/useResponsive'
import type { ViewMode } from './views/viewModes'

/** 可拖拽视图 Tab 标签 —— 供 Segmented.options.label 使用，配合 DndContext + SortableContext. */
function DndViewTab({ view, active, draggable, onClick }: { view: View; active: boolean; draggable: boolean; onClick: () => void }) {
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
      {...(draggable ? listeners : undefined)}
      onClick={(e) => { e.stopPropagation(); onClick() }}
    >
      {/* 拖拽把手：仅视图管理权限（EDIT_VIEWS）启用；个人视图本人可拖自己的排序? 否 —— 排序是表级公共属性，个人视图不开放 */}
      <HolderOutlined
        style={{ fontSize: 10, color: '#bfbfbf', cursor: draggable ? 'grab' : 'default', opacity: draggable ? 1 : 0.35 }}
      />
      <span>{view.name}</span>
      {view.is_default && <Tag color="blue" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>默认</Tag>}
      {/* 个人视图标识（紫色）—— 与公共视图区分：仅创建者可见可改，不影响他人 */}
      {view.owner_id != null && <Tag color="purple" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>我的</Tag>}
    </span>
  )
}

interface GridViewBarProps {
  wid: string
  tid: string
  views: View[]
  activeViewId: string | number | null
  mode: ViewMode
  modeButtons: ReadonlyArray<{ mode: ViewMode; label?: string; tooltip: string; icon: React.ReactNode }>
  showModeSwitch: boolean
  hasFilters: boolean
  hasSorts: boolean
  searchQuery: string
  onSearchChange: (q: string) => void
  onSelectView: (v: View | null) => void
  onModeChange: (m: ViewMode) => void
  onDragEnd: (event: DragEndEvent) => void
  /** 是否有视图管理权限（EDIT_VIEWS）：控制拖拽把手与公共视图的编辑/删除 */
  canManageViews: boolean
  onCreate: () => void
  onEdit: () => void
  onDelete: () => void
  onImport: () => void
  onOpenViewConfig: () => void
  /** 打开「个人设置 → 表格」页签（显示模式与操作风格全局快捷入口） */
  onOpenTableSettings: () => void
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
  hasFilters, hasSorts, searchQuery, onSearchChange, onSelectView, onModeChange,
  onDragEnd, canManageViews, onCreate, onEdit, onDelete, onImport,
  onOpenViewConfig, onOpenTableSettings,
}: GridViewBarProps) {
  const { message, modal } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const viewDragSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // 移动端搜索折叠态：默认收起，搜索词非空时保持展开（避免用户看不到已生效的过滤条件）
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const showMobileSearch = isMobile && (mobileSearchOpen || searchQuery.length > 0)

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
  }, [views.length, isMobile])

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
        draggable={canManageViews}
        onClick={() => onSelectView(v)}
      />
    ),
    value: String(v.id),
  }))

  /** 删除当前视图（桌面「更多」菜单与移动端菜单共用） */
  const confirmDeleteView = useCallback(() => {
    if (!activeView) return
    modal.confirm({
      title: '确定删除此视图？',
      content: activeView.name,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => activeViewId != null && onDelete(),
    })
  }, [activeView, activeViewId, modal, onDelete])

  /** 导出全部视图为 views.json（两个菜单共用） */
  const handleExportViews = useCallback(async () => {
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
  }, [wid, tid, message])

  /** 公共视图需 EDIT_VIEWS；个人视图本人可改（筛选/排序） */
  const editDisabled = !activeView || (!canManageViews && activeView?.owner_id == null)
  const currentModeBtn = modeButtons.find(b => b.mode === mode)

  const desktopMoreItems: MenuProps['items'] = [
    { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除当前视图', disabled: !activeView, onClick: confirmDeleteView },
    { type: 'divider' },
    { key: 'import', icon: <ImportOutlined />, label: '导入视图', onClick: onImport },
    { key: 'export', icon: <ExportOutlined />, label: '导出视图', onClick: handleExportViews },
  ]

  /** 移动端「更多」：桌面端的全部入口 + 搜索开关 + 表格设置（避免窄屏按钮挤压视图页签） */
  const mobileMoreItems: MenuProps['items'] = [
    { key: 'create', icon: <PlusOutlined />, label: '新建视图', onClick: onCreate },
    { key: 'edit', icon: <EditOutlined />, label: '编辑当前视图', disabled: editDisabled, onClick: onEdit },
    { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除当前视图', disabled: !activeView, onClick: confirmDeleteView },
    { type: 'divider' },
    { key: 'import', icon: <ImportOutlined />, label: '导入视图', onClick: onImport },
    { key: 'export', icon: <ExportOutlined />, label: '导出视图', onClick: handleExportViews },
    { type: 'divider' },
    { key: 'search', icon: <SearchOutlined />, label: '搜索当前视图', onClick: () => setMobileSearchOpen(v => !v) },
    { key: 'table-settings', icon: <SettingOutlined />, label: '表格设置', onClick: onOpenTableSettings },
  ]

  const modeDropdown = showModeSwitch && (
    <Dropdown
      trigger={['click']}
      menu={{
        selectedKeys: [mode],
        items: modeButtons.map(b => ({
          key: b.mode,
          icon: b.icon,
          label: <span data-testid={`view-mode-item-${b.mode}`}>{b.label ?? b.mode}</span>,
          onClick: () => onModeChange(b.mode),
        })),
      }}
    >
      <Tooltip title="切换视图模式：表格 / 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表">
        <Button
          size="middle"
          type="text"
          data-testid="view-mode-dropdown"
          aria-label="切换视图模式"
          icon={<>{currentModeBtn?.icon}{<DownOutlined style={{ fontSize: 10 }} />}</>}
        />
      </Tooltip>
    </Dropdown>
  )

  const filterButton = (
    <Tooltip title="筛选排序规则：按字段条件过滤和排序当前视图的行，规则保存在视图中">
      <Button
        size={isMobile ? 'middle' : 'small'}
        icon={<FilterOutlined />}
        type={hasFilters || hasSorts ? 'primary' : 'default'}
        data-testid="view-filter-btn"
        onClick={onOpenViewConfig}
      />
    </Tooltip>
  )

  const searchInput = (
    <Input.Search
      size="small"
      placeholder="搜索当前视图..."
      allowClear
      prefix={<SearchOutlined />}
      value={searchQuery}
      onChange={e => onSearchChange(e.target.value)}
      data-testid="view-search-input"
      style={{ width: isMobile ? '100%' : 160 }}
    />
  )

  return (
    <div style={{
      background: 'var(--cn-bg-container)',
      borderBottom: '1px solid var(--cn-border)',
    }}>
      <div style={{
        padding: '0 8px 0 0',
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        minHeight: isMobile ? 44 : 36,
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

        {isMobile ? (
          /* 移动端紧凑按钮组 —— 模式 / 筛选 / 更多（其余入口收进菜单，把宽度留给视图页签） */
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0, paddingRight: 6 }}>
            {modeDropdown}
            {filterButton}
            <Dropdown trigger={['click']} menu={{ items: mobileMoreItems }}>
              <Tooltip title="更多视图操作：新建 / 编辑 / 删除 / 导入 / 导出 / 搜索 / 表格设置">
                <Button
                  size="middle"
                  type="text"
                  icon={<MoreOutlined />}
                  data-testid="view-more-btn"
                  aria-label="更多视图操作"
                />
              </Tooltip>
            </Dropdown>
          </div>
        ) : (
          /* 右侧紧凑按钮组 —— flex-shrink:0 保证不被 Segmented 挤压 */
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, paddingRight: 8 }}>
            {/* 视图新建 + 编辑（均常显）+ 更多操作收进 Dropdown */}
            <Tooltip title="新建视图">
              <Button size="small" type="text" icon={<PlusOutlined />} onClick={onCreate} />
            </Tooltip>
            <Tooltip title="编辑当前视图">
              {/* 编辑按钮：公共视图需 EDIT_VIEWS；个人视图本人可改（筛选/排序） */}
              <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} disabled={editDisabled} />
            </Tooltip>
            <Dropdown trigger={['click']} menu={{ items: desktopMoreItems }}>
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

            {searchInput}
            {filterButton}
            <Tooltip title="表格设置：显示模式与操作风格（全局偏好，在个人设置中维护）">
              <Button
                size="small"
                icon={<SettingOutlined />}
                data-testid="display-settings-btn"
                onClick={onOpenTableSettings}
              />
            </Tooltip>
          </div>
        )}
      </div>

      {/* 移动端搜索行 —— 由「更多 → 搜索当前视图」展开；搜索词非空时常显 */}
      {showMobileSearch && (
        <div style={{ padding: '0 8px 8px' }} data-testid="view-search-row">
          {searchInput}
        </div>
      )}
    </div>
  )
}
