/** Grid 视图切换栏 — 可拖拽视图 Segmented + 右侧紧凑按钮组（从 GridPage 抽出）.
 *
 * 移动端（<768px）布局：视图 Segmented 占满剩余宽度（首要入口，支持横向滚动），
 * 右侧仅保留「视图模式下拉 + 筛选 + 更多」三个控件；新建/编辑/删除/导入/导出/
 * 表格设置收进「更多」菜单，搜索折叠为可展开的第二行。桌面端布局保持不变。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Input, Segmented, Space, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  PlusOutlined, DeleteOutlined, FilterOutlined, MoreOutlined,
  SearchOutlined, SettingOutlined, EditOutlined, ImportOutlined, ExportOutlined,
  HolderOutlined, LeftOutlined, RightOutlined, DownOutlined, SafetyOutlined,
  StarOutlined, StarFilled,
} from '@ant-design/icons'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { viewApi } from '@/api'
import type { View } from '@/api'
import { Tag, App as AntApp } from 'antd'
import { useResponsive } from '@/hooks/useResponsive'
import { MAX_FAVORITE_VIEWS, usePreferences, useToggleFavoriteView } from '@/hooks/useFavoriteViews'
import TooltipDropdown from '@/components/TooltipDropdown'
import type { ViewMode } from './views/viewModes'
import ViewPermissionDrawer from './ViewPermissionDrawer'

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
      {/* 档位标识：table 档对全表可见，不加标识；private = 仅本人可见；shared = 本人 + 指定成员。
          ****不能再用 `owner_id != null` 判个人视图**** —— 新模型下 table 档视图也带 owner（创建者），
          那样会给每个自建视图都打上「我的」。`visibility` 缺失（老响应 / mock）时回落到旧判据。 */}
      {view.visibility === 'private' && <Tag color="purple" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>我的</Tag>}
      {view.visibility === 'shared' && <Tag color="cyan" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>指定成员</Tag>}
      {view.visibility === undefined && view.owner_id != null && <Tag color="purple" style={{ marginLeft: 0, fontSize: 11, lineHeight: '14px', padding: '0 4px' }}>我的</Tag>}
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
  /** 是否有视图管理权限（EDIT_VIEWS）：控制拖拽把手与 table 档视图的编辑/删除，
   *  同时决定「表内所有人可见」档可否单选（ADR 0003 决策 D4） */
  canManageViews: boolean
  onCreate: () => void
  onEdit: () => void
  onDelete: () => void
  onImport: () => void
  onOpenViewConfig: () => void
  /** 打开「个人设置 → 表格」页签（显示模式与操作风格全局快捷入口） */
  onOpenTableSettings: () => void
  /** 视图档位/共享名单变更后回调（父级据此失效 `table-views` 缓存） */
  onViewsChanged?: () => void
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
  onOpenViewConfig, onOpenTableSettings, onViewsChanged,
}: GridViewBarProps) {
  const { message, modal } = AntApp.useApp()
  const { isMobile } = useResponsive()
  const [permOpen, setPermOpen] = useState(false)
  const viewDragSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  const activeView = activeViewId != null ? views.find(v => String(v.id) === String(activeViewId)) : null

  // 收藏状态（ADR 0021）：读当前用户偏好；收藏 / 取消收藏走全量替换端点
  const { data: prefs } = usePreferences()
  const toggleFavorite = useToggleFavoriteView()
  const favoriteIds = (prefs?.favorite_view_ids ?? []).map(Number)
  const isFavorite = activeView != null && favoriteIds.includes(Number(activeView.id))
  const favoriteLimitReached = favoriteIds.length >= MAX_FAVORITE_VIEWS

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

  /** 视图编辑入口的可用性（与后端 `VIEW_EDIT` 同口径）：
   *  `table` 档对全表可见 → 改它要 `EDIT_VIEWS`；`private`/`shared` 档 → 本人（后端还要求持表 READ）。
   *  ****判据是 `visibility`，不是 `owner_id`**** —— 新模型下 table 档视图也带 owner（创建者），
   *  用它当"个人视图"的代理会让 viewer 对他人 table 档视图拿到编辑入口（点下去 403）。
   *  `visibility` 缺失（老响应 / mock）时回落到旧判据：无 owner = 公共视图 = 需要 EDIT_VIEWS。 */
  const activeVisibility = activeView?.visibility
  const activeIsTableTier = activeVisibility === undefined
    ? activeView?.owner_id == null
    : activeVisibility === 'table'
  const editDisabled = !activeView || (!canManageViews && activeIsTableTier)
  /** 能否打开权限 Drawer：优先用后端下发的 `can_manage`（三档判定唯一口径）；
   *  缺失（老响应 / mock）时回落旧判据 —— table 档需 EDIT_VIEWS，其余档本人即可。 */
  const canManageActive = activeView != null
    && (activeView.can_manage !== undefined ? activeView.can_manage : !activeIsTableTier || canManageViews)
  const currentModeBtn = modeButtons.find(b => b.mode === mode)

  /** 收藏 / 取消收藏当前视图（桌面星标按钮与移动端菜单共用） */
  const handleToggleFavorite = useCallback(() => {
    if (!activeView) return
    if (!isFavorite && favoriteLimitReached) {
      message.warning(`最多收藏 ${MAX_FAVORITE_VIEWS} 个视图`)
      return
    }
    toggleFavorite.mutate(
      { viewId: activeView.id, favorited: !isFavorite },
      {
        onSuccess: () => message.success(
          isFavorite ? `已取消收藏「${activeView.name}」` : `已收藏「${activeView.name}」`,
        ),
        onError: (err) => message.error(err instanceof Error ? err.message : '收藏失败，请稍后重试'),
      },
    )
  }, [activeView, isFavorite, favoriteLimitReached, toggleFavorite, message])

  const desktopMoreItems: MenuProps['items'] = [
    { key: 'permission', icon: <SafetyOutlined />, label: '视图权限', disabled: !canManageActive, onClick: () => setPermOpen(true) },
    { type: 'divider' },
    { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除当前视图', disabled: !activeView, onClick: confirmDeleteView },
    { type: 'divider' },
    { key: 'import', icon: <ImportOutlined />, label: '导入视图', onClick: onImport },
    { key: 'export', icon: <ExportOutlined />, label: '导出视图', onClick: handleExportViews },
  ]

  /** 移动端「更多」：桌面端的全部入口 + 搜索开关 + 表格设置（避免窄屏按钮挤压视图页签） */
  const mobileMoreItems: MenuProps['items'] = [
    { key: 'create', icon: <PlusOutlined />, label: '新建视图', onClick: onCreate },
    { key: 'edit', icon: <EditOutlined />, label: '编辑当前视图', disabled: editDisabled, onClick: onEdit },
    {
      key: 'favorite',
      icon: isFavorite ? <StarFilled style={{ color: '#f59e0b' }} /> : <StarOutlined />,
      label: (
        <span data-testid="view-favorite-menu-item">
          {isFavorite ? '取消收藏当前视图' : '收藏当前视图'}
        </span>
      ),
      disabled: !activeView,
      onClick: handleToggleFavorite,
    },
    { key: 'permission', icon: <SafetyOutlined />, label: '视图权限', disabled: !canManageActive, onClick: () => setPermOpen(true) },
    { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除当前视图', disabled: !activeView, onClick: confirmDeleteView },
    { type: 'divider' },
    { key: 'import', icon: <ImportOutlined />, label: '导入视图', onClick: onImport },
    { key: 'export', icon: <ExportOutlined />, label: '导出视图', onClick: handleExportViews },
    { type: 'divider' },
    { key: 'search', icon: <SearchOutlined />, label: '搜索当前视图', onClick: () => setMobileSearchOpen(v => !v) },
    { key: 'table-settings', icon: <SettingOutlined />, label: '表格设置', onClick: onOpenTableSettings },
  ]

  const modeDropdown = showModeSwitch && (
    <TooltipDropdown
      title="切换视图模式：表格 / 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表"
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
      <Button
        size="middle"
        type="text"
        data-testid="view-mode-dropdown"
        aria-label="切换视图模式"
        icon={<>{currentModeBtn?.icon}{<DownOutlined style={{ fontSize: 10 }} />}</>}
      />
    </TooltipDropdown>
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
        minHeight: isMobile ? 40 : 32,
      }}>
        {/* Segmented —— flex:1 占满弹性空间，min-width:0 允许在窄屏下被压缩从而触发内部滚动 */}
        <div
          ref={segmentedWrapRef}
          className={[
            'cn-segmented-wrap',
            canScrollLeft ? 'is-scroll-left' : '',
            canScrollRight ? 'is-scroll-right' : '',
          ].filter(Boolean).join(' ')}
          style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', padding: '2px 0 2px 12px' }}
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
            <TooltipDropdown title="更多视图操作：新建 / 编辑 / 删除 / 导入 / 导出 / 搜索 / 表格设置" menu={{ items: mobileMoreItems }}>
              <Button
                size="middle"
                type="text"
                icon={<MoreOutlined />}
                data-testid="view-more-btn"
                aria-label="更多视图操作"
              />
            </TooltipDropdown>
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
            <Tooltip title={isFavorite ? '取消收藏当前视图' : '收藏当前视图（显示在主页「我的视图」）'}>
              <Button
                size="small"
                type="text"
                aria-pressed={isFavorite}
                aria-label={isFavorite ? '取消收藏当前视图' : '收藏当前视图'}
                data-testid="view-favorite-btn"
                icon={isFavorite ? <StarFilled style={{ color: '#f59e0b' }} /> : <StarOutlined />}
                onClick={handleToggleFavorite}
                disabled={!activeView}
              />
            </Tooltip>
            <TooltipDropdown title="视图更多操作" menu={{ items: desktopMoreItems }}>
              <Button size="small" type="text" icon={<MoreOutlined />} />
            </TooltipDropdown>

            <div style={{ width: 1, height: 14, background: 'var(--cn-border)', margin: '0 3px' }} />

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
        <div style={{ padding: '0 8px 6px' }} data-testid="view-search-row">
          {searchInput}
        </div>
      )}

      {/* 视图权限 Drawer —— 三档可见性 + 共享名单（ADR 0003 P3）。
          `canManageViews` 即表 EDIT_VIEWS，用于门控「表内所有人可见」档（D4）。 */}
      <ViewPermissionDrawer
        open={permOpen}
        onClose={() => setPermOpen(false)}
        wid={wid}
        tid={tid}
        view={activeView ?? null}
        canPublishToTable={canManageViews}
        onUpdated={() => onViewsChanged?.()}
      />
    </div>
  )
}
