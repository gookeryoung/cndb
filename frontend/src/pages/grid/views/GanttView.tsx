/** 甘特图视图组件 — 时间轴 + 任务进度条.
 *
 * view_options 配置字段（由 GANTT_OPTIONS schema 定义）:
 * - start_date_field / end_date_field: 任务起止日期（date/datetime，必填）
 * - actual_end_field:  实际完成日期（可选，对比计划/实际）
 * - title_field / group_field / progress_field / assignee_field
 * - time_scale:        时间粒度 'day' | 'week' | 'month' | 'quarter'（默认 'month'）
 * - show_today_line:   是否显示今日标线（默认 true）
 *
 * 滚动策略：右侧 body 是唯一的真实滚动容器（横纵双轴 overflow: auto），
 * 顶层 header 通过 scrollLeft 单向跟随 body 横向滚动。
 * 双轴同容器保证横向可达范围与行内容裁剪窗口一致，行右端不会被自身纵向
 * 滚动条裁掉；header 独立持有避免为跟随纵向滚动而重排表头。
 * 同时支持 Shift+滚轮横向、滚动到今天按钮与挂载后自动定位到今日标线。
 *
 * 纵向虚拟化：任务行（含分组头）展平为定高序列，用 @tanstack/react-virtual 切片渲染，
 * 左侧任务名列与右侧时间轴共享同一个 virtualizer，两侧窗口与滚动位置严格对齐。
 *
 * 子模块：gantt/ 下按「尺寸预设 / 任务构建 / 类型 / 条渲染 / 左列 / 右列虚拟行」拆分。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { VirtualItem } from '@tanstack/react-virtual'
import { Button, Empty, Segmented, Tooltip } from 'antd'
import { CalendarOutlined, HomeOutlined, LeftOutlined, ReloadOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons'
import type { Field, RowResponse, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { groupColor } from '@/utils/paletteColor'
import { GANTT_OPTIONS, resolveOpts } from '../view-config/viewOptionSchema'
import { fmtDate } from '../cells/dateUtils'
import type { TimeScale } from './ganttTimeline'
import { ZOOM_LEVELS, autoAdjustLevel, buildDualTimeline, computeTimeRange, daysBetween, selectZoomLevelForScale } from './ganttTimeline'
import { densityStyle } from './gantt/ganttDensity'
import { buildGanttTasks } from './gantt/ganttTasks'
import { GanttFlatItem, GanttGroup } from './gantt/ganttTypes'
import { RightBoundaryLine, TodayLine } from './gantt/ganttBars'
import { LeftColBody } from './gantt/ganttLeftColumn'
import { VirtualGroupHeader, VirtualTaskRow } from './gantt/ganttVirtualRows'

interface GanttViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
  /** PDF 导出模式：绕过纵向虚拟化全量渲染行，并放开表头裁剪使整个时间轴进入快照 */
  pdfExporting?: boolean
}

export default function GanttView({
  rows,
  fields,
  view,
  density,
  sortings,
  onRowClick,
  pdfExporting,
}: GanttViewProps & {
  sortings?: Array<{ field_name: string; direction: 'asc' | 'desc' }>
}) {
  const opts = useMemo(
    () => resolveOpts(view?.view_options as Record<string, unknown> | undefined, GANTT_OPTIONS),
    [view?.view_options],
  )

  const ds = densityStyle(density)
  const defaultScale = (opts.time_scale as TimeScale) || 'month'
  const [scale, setScale] = useState<TimeScale>(defaultScale)
  const [zoomLevel, setZoomLevel] = useState<number | null>(null)

  // 切换 view 时，本地 scale + zoomLevel 同步到新 view 的默认值
  useEffect(() => {
    setScale(defaultScale)
    setZoomLevel(null) // 触发 selectZoomLevelForScale 重新计算
  }, [defaultScale])

  const showToday = opts.show_today_line !== false
  const groupField = opts.group_field as string | undefined

  // 构建任务列表
  const tasks = useMemo(
    () => buildGanttTasks(rows, fields, opts, sortings),
    [rows, fields, opts, sortings],
  )

  // 计算时间轴
  const timeRange = useMemo(
    () => computeTimeRange(tasks),
    [tasks],
  )

  // 根据 scale + 时间跨度自动选初始 zoomLevel
  const totalDays = timeRange ? daysBetween(timeRange.min, timeRange.max) : 365
  const resolvedLevel = zoomLevel ?? (timeRange ? selectZoomLevelForScale(scale, totalDays) : 2)

  // 只有用户还没手动调过 zoom 时才做视口宽度微调（避免覆盖用户手动选择）。
  // 传入 scale 限制 autoAdjustLevel 只在同粒度档位内调整，避免用户切换天/周/月/季时粒度漂移。
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1200
  const finalLevel = zoomLevel == null && timeRange
    ? autoAdjustLevel(resolvedLevel, totalDays, viewportWidth, scale)
    : resolvedLevel

  // 构建双层时间轴
  const dualTimeline = useMemo(
    () => timeRange ? buildDualTimeline(timeRange, finalLevel) : {
      anchorSegments: [], currentSegments: [], pxPerDay: 6, level: 2, levelDef: ZOOM_LEVELS[2],
    },
    [timeRange, finalLevel],
  )

  const { anchorSegments, currentSegments, pxPerDay, levelDef } = dualTimeline
  const totalTimelineWidth = anchorSegments.reduce((s, t) => s + t.width, 0)

  // 次分隔线（day/week 段严格等宽）：用单层 repeating 渐变替代每段一个 0 宽 div，
  // 避免大跨度（如上千天）下产生上千个常驻 DOM 节点
  const secondaryGrid = useMemo(() => {
    if (levelDef.anchorScale !== 'month') return null
    if (levelDef.currentScale !== 'day' && levelDef.currentScale !== 'week') return null
    if (currentSegments.length < 2) return null
    const segWidth = currentSegments[0].width
    return { segWidth, width: (currentSegments.length - 1) * segWidth }
  }, [levelDef.anchorScale, levelDef.currentScale, currentSegments])

  // ── 滚动容器 —— body 是唯一真实滚动容器（横纵双轴）──
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const [bodyEl, setBodyEl] = useState<HTMLDivElement | null>(null)
  const attachBody = useCallback((el: HTMLDivElement | null) => {
    bodyRef.current = el
    setBodyEl(el)
  }, [])
  const headerScrollRef = useRef<HTMLDivElement>(null)

  const scrollTo = useCallback((delta: number) => {
    bodyRef.current?.scrollBy({ left: delta, behavior: 'smooth' })
  }, [])

  const scrollToToday = useCallback(() => {
    const el = bodyRef.current
    if (!el || !timeRange) return
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    if (today < timeRange.min || today > timeRange.max) return
    const offsetDays = daysBetween(timeRange.min, today) - 1
    const todayLeft = offsetDays * pxPerDay
    const target = Math.max(0, todayLeft - el.clientWidth / 2)
    el.scrollTo({ left: target, behavior: 'smooth' })
  }, [timeRange, pxPerDay])

  // 挂载后自动横向定位到今日标线（不动画），让进度基准线直接可见
  const didInitScroll = useRef(false)
  useEffect(() => {
    const el = bodyRef.current
    if (didInitScroll.current || !el || !timeRange) return
    didInitScroll.current = true
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    if (today < timeRange.min || today > timeRange.max) return
    const offsetDays = daysBetween(timeRange.min, today) - 1
    el.scrollLeft = Math.max(0, offsetDays * pxPerDay - el.clientWidth / 2)
  }, [timeRange, pxPerDay])

  // header 横向跟随 body：body 是横向滚动真理源；header 为 overflow:hidden 裁剪容器，
  // 但 Shift+滚轮仍可能触发其 scroll 事件，故做带防抖标志的双向同步（同左列模式）
  useEffect(() => {
    const body = bodyRef.current
    const header = headerScrollRef.current
    if (!body || !header) return
    let syncing = false
    const onBodyScroll = () => {
      if (syncing) return
      syncing = true
      header.scrollLeft = body.scrollLeft
      requestAnimationFrame(() => { syncing = false })
    }
    const onHeaderScroll = () => {
      if (syncing) return
      syncing = true
      body.scrollLeft = header.scrollLeft
      requestAnimationFrame(() => { syncing = false })
    }
    body.addEventListener('scroll', onBodyScroll)
    header.addEventListener('scroll', onHeaderScroll)
    return () => {
      body.removeEventListener('scroll', onBodyScroll)
      header.removeEventListener('scroll', onHeaderScroll)
    }
  }, [bodyEl])

  // 按分组聚合（用于左侧分组分隔 + WBS 编号）
  const groupedTasks = useMemo<GanttGroup[]>(() => {
    const groups: GanttGroup[] = []
    for (const t of tasks) {
      const gkey = t.groupValue || '__nogroup__'
      let g = groups.find(g => g.key === gkey)
      if (!g) {
        g = {
          key: gkey,
          label: t.groupValue || '未分组',
          tasks: [],
          color: groupColor(gkey),
          index: groups.length + 1,
        }
        groups.push(g)
      }
      g.tasks.push(t)
    }
    return groups
  }, [tasks])

  // 展平为「组头 + 任务行」定高序列 —— 左右两栏共享同一个 virtualizer，
  // 保证滚动窗口内两侧行严格对齐
  const hasGroup = !!groupField
  const flatItems = useMemo<GanttFlatItem[]>(() => {
    const items: GanttFlatItem[] = []
    for (const group of groupedTasks) {
      if (hasGroup) {
        items.push({ kind: 'group', key: `g-${group.key}`, size: ds.groupHeaderHeight, group })
      }
      group.tasks.forEach((task, tIndex) => {
        items.push({ kind: 'task', key: `t-${String(task.row.id)}`, size: ds.rowHeight, group, task, tIndex })
      })
    }
    return items
  }, [groupedTasks, hasGroup, ds.groupHeaderHeight, ds.rowHeight])

  // 纵向虚拟化：body 元素（见上方 attachBody）即 virtualizer 滚动元素；
  // 空态分支不挂载该元素
  const rowVirtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => bodyEl,
    estimateSize: (index) => flatItems[index]?.size ?? ds.rowHeight,
    getItemKey: (index) => flatItems[index].key,
    overscan: 8,
  })
  // PDF 导出模式：行高全部为定高常量，手动累计偏移合成全量窗口替代虚拟切片，
  // 左右两栏共用同一序列保证严格对齐（enabled:false 会使 getVirtualItems 返回空，不可用）
  const exportVirtualItems = useMemo<Array<VirtualItem> | null>(() => {
    if (!pdfExporting) return null
    let y = 0
    return flatItems.map((item, index) => {
      const start = y
      y += item.size
      return { index, key: item.key, start, end: y, size: item.size, lane: 0 }
    })
  }, [pdfExporting, flatItems])
  const virtualItems = exportVirtualItems ?? rowVirtualizer.getVirtualItems()
  const totalBodyHeight = exportVirtualItems
    ? (exportVirtualItems[exportVirtualItems.length - 1]?.end ?? 0)
    : rowVirtualizer.getTotalSize()

  // 空状态
  const startField = opts.start_date_field as string | undefined
  const endField = opts.end_date_field as string | undefined
  if (!startField || !endField) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="甘特图视图需要配置 start_date_field（开始日期）和 end_date_field（结束日期）" />
      </div>
    )
  }
  if (tasks.length === 0 || !timeRange) {
    return (
      <div style={{ padding: 24 }}>
        <Empty
          description={
            rows.length === 0
              ? '暂无数据'
              : '当前时间范围内没有有效任务（请检查开始/结束日期字段）'
          }
        />
      </div>
    )
  }

  // 导航步长自适应：视口宽度的 30%
  const navStep = typeof window !== 'undefined' ? Math.max(120, Math.floor(window.innerWidth * 0.3)) : 200

  return (
    <div data-testid="gantt-view" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 工具栏 */}
      <div
        style={{
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
          flexShrink: 0,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: ds.headerFontSize + 2, display: 'flex', alignItems: 'center', gap: 6 }}>
          <CalendarOutlined style={{ color: 'var(--cn-brand-color)' }} />
          甘特图视图
        </div>

        <div data-testid="gantt-scale-switch">
          <Segmented
            size="small"
            value={scale}
            onChange={(v) => {
              const newScale = v as TimeScale
              setScale(newScale)
              setZoomLevel(null) // 让 zoomLevel 重新按 newScale 自动选择
            }}
            options={[
              { value: 'day', label: '天' },
              { value: 'week', label: '周' },
              { value: 'month', label: '月' },
              { value: 'quarter', label: '季' },
            ]}
          />
        </div>

        {/* 缩放控件 —— 连续缩放 8 档 */}
        <div
          data-testid="gantt-scale-info"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '0 8px',
            height: 24,
            borderRadius: 4,
            border: '1px solid var(--cn-border)',
            fontSize: ds.headerFontSize,
            color: 'var(--cn-text-muted)',
            background: 'var(--cn-bg-subtle)',
          }}
          title={`${levelDef.name} · ${pxPerDay.toFixed(1)} px/天`}
        >
          <Button
            size="small"
            type="text"
            icon={<ZoomOutOutlined />}
            disabled={finalLevel <= 0}
            onClick={() => setZoomLevel(finalLevel - 1)}
            title="缩小"
          />
          <span style={{ minWidth: 44, textAlign: 'center', fontWeight: 500, color: 'var(--cn-text)' }}>
            {levelDef.name}
          </span>
          <Button
            size="small"
            type="text"
            icon={<ZoomInOutlined />}
            disabled={finalLevel >= ZOOM_LEVELS.length - 1}
            onClick={() => setZoomLevel(finalLevel + 1)}
            title="放大"
          />
        </div>

        <div style={{ marginLeft: 'auto', fontSize: ds.headerFontSize, color: 'var(--cn-text-muted)' }}>
          共 {tasks.length} 个任务 · {groupedTasks.length} 个分组
        </div>
      </div>

      {/* ─── 主体：左列固定 + 右列横向可滚动 ─── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左侧固定列（header + body 合并为一个区域）；
            PDF 导出模式放开 hidden 裁剪，全量行溢出列框渲染才能进入快照 */}
        <div
          style={{
            width: ds.leftColWidth,
            minWidth: ds.leftColWidth,
            borderRight: '1px solid var(--cn-border)',
            background: 'var(--cn-bg-container)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
            overflow: pdfExporting ? 'visible' : 'hidden',
          }}
        >
          {/* 左侧 header —— 高度对齐右侧双层表头（2 × headerHeight），保证左右行不错位 */}
          <div
            style={{
              height: ds.headerHeight * 2,
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              padding: '0 12px',
              fontWeight: 600,
              fontSize: ds.headerFontSize,
              borderBottom: '1px solid var(--cn-border)',
              background: 'var(--cn-bg-subtle)',
            }}
          >
            {groupField ? '任务分组' : '任务名称'}
          </div>

          {/* 左侧 body —— 与右侧共享虚拟窗口，滚动位置双向同步 */}
          <LeftColBody
            items={flatItems}
            virtualItems={virtualItems}
            totalSize={totalBodyHeight}
            hasGroup={hasGroup}
            ds={ds}
            onRowClick={onRowClick}
            bodyRef={bodyRef}
          />
        </div>

        {/* 右侧时间轴区域 —— header 裁剪跟随 + body 双轴真实滚动 */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
          }}
        >
          {/* header —— 双层；overflow:hidden 裁剪，scrollLeft 由同步逻辑跟随 body */}
          <div ref={headerScrollRef} data-testid="gantt-header-scroll" style={{ flexShrink: 0, minWidth: 0, overflow: pdfExporting ? 'visible' : 'hidden' }}>
            <div style={{ minWidth: totalTimelineWidth }}>
              {/* 上层：锚定层（month / year）—— 合并渲染 */}
              <div
                data-testid="gantt-header-row"
                data-layer="anchor"
                style={{
                  height: ds.headerHeight,
                  position: 'relative',
                  minWidth: totalTimelineWidth,
                  borderBottom: '1px solid var(--cn-border)',
                  background: 'var(--cn-bg-container)',
                }}
              >
                {anchorSegments.map((seg) => (
                  <div
                    key={`a-${seg.left}`}
                    data-testid={seg.showLabel ? 'gantt-timeline-label' : undefined}
                    data-layer="anchor"
                    style={{
                      position: 'absolute',
                      left: seg.left,
                      top: 0,
                      bottom: 0,
                      width: seg.width,
                      padding: '0 6px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-start',
                      borderRight: '1px solid var(--cn-border)',
                      fontSize: ds.headerFontSize,
                      fontWeight: 600,
                      color: 'var(--cn-text)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {seg.showLabel ? seg.label : null}
                  </div>
                ))}
                {/* 时间轴右边界虚线 */}
                <RightBoundaryLine totalWidth={totalTimelineWidth} />
              </div>

              {/* 下层：当前刻度层（day / week / month / quarter）。
                day/week 段等宽且标签稀疏：竖线交给单层渐变，仅渲染带标签的段（absolute）；
                month/quarter 段数少且全部带标签，保留 flex 布局 */}
              <div
                data-testid="gantt-header-row"
                data-layer="current"
                style={{
                  position: 'relative',
                  height: ds.headerHeight,
                  minWidth: totalTimelineWidth,
                  background: 'var(--cn-bg-subtle)',
                }}
              >
                {secondaryGrid && (
                  <div
                    aria-hidden
                    style={{
                      position: 'absolute',
                      top: 0,
                      bottom: 0,
                      left: 0,
                      width: totalTimelineWidth,
                      backgroundImage: `repeating-linear-gradient(to right, transparent 0, transparent ${secondaryGrid.segWidth - 1}px, var(--cn-border-secondary, #f0f0f0) ${secondaryGrid.segWidth - 1}px, var(--cn-border-secondary, #f0f0f0) ${secondaryGrid.segWidth}px)`,
                    }}
                  />
                )}
                {currentSegments.map((seg) => {
                  // day/week 的无标签空段不渲染（竖线由渐变层承担）
                  if (secondaryGrid && !seg.showLabel) return null
                  return (
                    <div
                      key={`c-${seg.left}`}
                      data-testid={seg.showLabel ? 'gantt-timeline-label' : undefined}
                      data-layer="current"
                      style={{
                        position: 'absolute',
                        left: seg.left,
                        top: 0,
                        height: '100%',
                        width: seg.width,
                        padding: '0 3px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRight: secondaryGrid
                          ? undefined
                          : `1px solid ${levelDef.anchorScale === 'year' ? 'var(--cn-border)' : 'var(--cn-border-secondary, #f0f0f0)'}`,
                        fontSize: ds.headerFontSize,
                        color: 'var(--cn-text-muted)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        background: 'var(--cn-bg-subtle)',
                        boxSizing: 'border-box',
                      }}
                    >
                      {seg.showLabel ? seg.label : null}
                    </div>
                  )
                })}
                {/* 时间轴右边界虚线 */}
                <RightBoundaryLine totalWidth={totalTimelineWidth} />
              </div>
            </div>
          </div>

          {/* body 行区 —— 唯一真实滚动容器（横纵双轴）：
              双轴同容器保证横向可达范围与行裁剪窗口一致，行右端不会被纵向滚动条裁掉；
              本元素同时是左列纵向滚动同步源 */}
          <div
            ref={attachBody}
            data-testid="gantt-body"
            style={{
              position: 'relative',
              flex: 1,
              minWidth: 0,
              overflowY: 'auto',
              overflowX: 'auto',
            }}
          >
            {/* 时间轴网格背景层 —— 双层：主分隔（锚定粒度深色）+ 次分隔（当前粒度浅色） */}
            <div
              aria-hidden
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: totalTimelineWidth,
                height: totalBodyHeight,
                pointerEvents: 'none',
                zIndex: 0,
              }}
            >
              {/* 主分隔线：锚定粒度 */}
              {anchorSegments.map((seg) => (
                <div
                  key={`ag-${seg.left}`}
                  style={{
                    position: 'absolute',
                    left: seg.left,
                    top: 0,
                    bottom: 0,
                    width: seg.width,
                    borderRight: '1px solid var(--cn-border)',
                  }}
                />
              ))}
              {/* 次分隔线：当前粒度（day/week 等宽段，渐变周期复刻每段右边界 1px 线） */}
              {secondaryGrid && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: secondaryGrid.width,
                    backgroundImage: `repeating-linear-gradient(to right, transparent 0, transparent ${secondaryGrid.segWidth - 1}px, var(--cn-border-secondary, #eee) ${secondaryGrid.segWidth - 1}px, var(--cn-border-secondary, #eee) ${secondaryGrid.segWidth}px)`,
                  }}
                />
              )}
              {showToday && timeRange && <TodayLine range={timeRange} pxPerDay={pxPerDay} />}
              {/* 时间轴右边界虚线 —— 覆盖 body grid 背景右边界 */}
              <RightBoundaryLine totalWidth={totalTimelineWidth} />
            </div>

            {/* 虚拟行容器：仅渲染滚动窗口（含 overscan）内的组头与任务行 */}
            <div
              style={{
                position: 'relative',
                width: totalTimelineWidth,
                height: totalBodyHeight,
                zIndex: 1,
              }}
            >
              {virtualItems.map((vi) => {
                const item = flatItems[vi.index]
                if (item.kind === 'group') {
                  return (
                    <VirtualGroupHeader
                      key={vi.key}
                      top={vi.start}
                      width={totalTimelineWidth}
                      height={item.size}
                      color={item.group.color}
                    />
                  )
                }
                return (
                  <VirtualTaskRow
                    key={vi.key}
                    task={item.task}
                    top={vi.start}
                    height={item.size}
                    width={totalTimelineWidth}
                    timeRange={timeRange!}
                    pxPerDay={pxPerDay}
                    barHeight={ds.barHeight}
                    onRowClick={onRowClick}
                  />
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* 底部导航栏 */}
      <div
        style={{
          padding: '6px 12px',
          borderTop: '1px solid var(--cn-border)',
          background: 'var(--cn-bg-container)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <Tooltip title="时间轴左移">
          <Button size="small" icon={<LeftOutlined />} onClick={() => scrollTo(-navStep)} />
        </Tooltip>
        <Tooltip title="时间轴右移">
          <Button size="small" icon={<RightOutlined />} onClick={() => scrollTo(navStep)} />
        </Tooltip>
        <Tooltip title="滚动到今天">
          <Button size="small" icon={<HomeOutlined />} onClick={scrollToToday} />
        </Tooltip>
        <Tooltip title="回到起点">
          <Button size="small" icon={<ReloadOutlined />} onClick={() => bodyRef.current?.scrollTo({ left: 0, behavior: 'smooth' })} />
        </Tooltip>
        <span style={{ fontSize: ds.metaFontSize, color: 'var(--cn-text-muted)' }}>
          {fmtDate(timeRange.min)} ~ {fmtDate(timeRange.max)}
        </span>
      </div>
    </div >
  )
}
