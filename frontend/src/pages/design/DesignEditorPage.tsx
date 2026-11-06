/** 设计编辑器页 —— DSL 源码（CodeMirror）+ 3D 实时预览（three.js）+ 参数｜约束常驻面板.
 *
 * 数据流（ADR 0079 I1/D3/D4）：
 * - 编辑防抖 300ms → POST /designs/preview（无落库）→ 结构化诊断回显错误行；
 * - 渲染只消费后端编译的 IR（前端零解析零求值），three 相关全部在 lazy chunk；
 * - 保存：编译在后端通过才落库并落新版本，失败保留草稿（边界 #2）；
 * - 版本历史（回看 / 恢复）与导出收进「更多」菜单（ADR 0103 D6），功能不变。
 *
 * 布局（ADR 0103）：
 * - 工具栏恒单行：返回 / 标题 / 版本 / 编译状态 / 分栏预设 / 更多 / 保存（C6 D6）；
 * - 左右可拖分栏 + 三档预设，比例存 localStorage（C2 D3 D10，窄屏纵向堆叠）；
 * - 视口右上悬浮工具条（七向定向 / 布满 / 网格）+ 左下状态条（单位 / 节点 / 三角）（C3 C4）；
 * - 预览栏底部「参数｜约束」常驻可折叠面板替代参数抽屉（C5 D2）；
 * - 树↔视口联动：`?line=` 变化 → 大纲归属 → 顶层 nodes 下标 → 视口高亮 3s 渐隐（C7 D8/D9）。
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, Dropdown, Empty, Popconfirm, Segmented, Skeleton, Space, Tag, Tooltip,
  Typography,
} from 'antd'
import type { InputNumberProps } from 'antd'
import {
  ArrowLeftOutlined, BorderOutlined, CheckCircleFilled, CloseCircleFilled, CompassOutlined,
  ExperimentOutlined, ExpandOutlined, LoadingOutlined, RollbackOutlined, SaveOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignDiagnostic, DesignVersionItem } from '@/api'
import { formatDateTime } from '@/utils/datetime'
import DslEditor from './DslEditor'
import DesignParamsPanel from './DesignParamsPanel'
import type { DslPartOption } from './designCompletion'
import { collectNodeIndices, resolveOutlinePath } from './designOutline'
import { useDesignPreview } from './useDesignPreview'
import type { PreviewStats, ViewportApi } from './PreviewCanvas'
import { VIEW_PRESETS, type ViewOrientation } from './viewOrient'

// three 渲染整块 lazy：three + three-bvh-csg 只进设计编辑器 chunk（D4 体积预算）
const PreviewCanvas = lazy(() => import('./PreviewCanvas'))
// 「更多」菜单同样落在 three lazy 边界（exporters 引 three，ADR 0079 D5）
const DesignMoreMenu = lazy(() => import('./DesignMoreMenu'))

const { Text } = Typography

/** UI 偏好键（I5：只存本地，不进后端 / 备份） */
export const SPLIT_KEY = 'cn-design-editor-split'
export const PARAMS_COLLAPSED_KEY = 'cn-design-params-collapsed'
export const DEFAULT_SPLIT = 50
/** 分栏比例上下限（D3）：任一侧不窄于 25% */
export const SPLIT_MIN = 25
export const SPLIT_MAX = 75
/** 窄屏断点：与 index.css 的 1023.98px 媒体查询口径一致（C2 降级路径） */
const NARROW_QUERY = '(max-width: 1023.98px)'

function readSplit(): number {
  try {
    const raw = window.localStorage.getItem(SPLIT_KEY)
    const value = raw == null ? NaN : Number(raw)
    if (!Number.isFinite(value)) return DEFAULT_SPLIT
    return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, value))
  } catch {
    return DEFAULT_SPLIT
  }
}

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(PARAMS_COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

/** 窄屏判定（splitter 不渲染、比例不生效，§4#7） */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => (
    typeof window.matchMedia === 'function' ? window.matchMedia(NARROW_QUERY).matches : false
  ))
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(NARROW_QUERY)
    const onChange = (event: MediaQueryListEvent) => setNarrow(event.matches)
    setNarrow(query.matches)
    query.addEventListener?.('change', onChange)
    return () => query.removeEventListener?.('change', onChange)
  }, [])
  return narrow
}

export default function DesignEditorPage() {
  const { wid = '', designId = '' } = useParams<{ wid: string; designId: string }>()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  // 结构树节点带 ?line= 打开编辑器并定位源行（ADR 0083 D7）
  const [searchParams, setSearchParams] = useSearchParams()
  const revealLine = Number(searchParams.get('line')) || undefined

  const { data: detail, isLoading } = useQuery({
    queryKey: ['designs', wid, designId],
    queryFn: () => designsApi.get(wid, designId),
    enabled: !!wid && !!designId,
  })

  // IR 快照（ADR 0086 D7 / I6）：首屏直用持久化 IR，干净状态不发 preview
  const { data: irResp } = useQuery({
    queryKey: ['designs', wid, designId, 'ir'],
    queryFn: () => designsApi.getIR(wid, designId),
    enabled: !!wid && !!designId,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const isViewer = wsDetail?.current_user_role === 'viewer'

  const [content, setContent] = useState('')
  const [contentReady, setContentReady] = useState(false)
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [saveError, setSaveError] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  // 布局偏好：分栏比例 / 参数面板折叠态（I5）
  const [split, setSplit] = useState<number>(readSplit)
  const [paramsCollapsed, setParamsCollapsed] = useState<boolean>(readCollapsed)
  const narrow = useNarrow()
  const [stats, setStats] = useState<PreviewStats>({ nodes: 0, triangles: 0 })
  const [gridVisible, setGridVisible] = useState(true)
  const viewportApiRef = useRef<ViewportApi | null>(null)
  /** 待高亮的源行（api 未就绪或 IR 未到达时暂存，就绪后补一次） */
  const pendingHighlightLine = useRef<number | null>(null)
  const workbenchRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)
  // 详情到达只回填一次（此后编辑权归用户；保存成功后 dirty 归零再回填最新态）
  const [loadedId, setLoadedId] = useState('')
  useEffect(() => {
    if (detail && loadedId !== String(detail.id)) {
      setContent(detail.content)
      setLoadedId(String(detail.id))
      setContentReady(true)
    }
  }, [detail, loadedId])

  const dirty = contentReady && detail != null && content !== detail.content
  // 干净打开（内容未改且无参数覆盖）：直接消费 IR 快照，不发 preview（I6）
  const clean = !dirty && Object.keys(overrides).length === 0
  const preview = useDesignPreview(wid, content, overrides, {
    enabled: contentReady && !clean,
    designId: detail ? detail.id : null,
    initialIr: irResp?.ir ?? null,
  })

  // 依赖陈旧（ADR 0086 D6）：被引用零件更新后提示刷新，refresh 落新版本并清 stale
  const refresh = useMutation({
    mutationFn: () => designsApi.refresh(wid, designId),
    onSuccess: (updated) => {
      message.success(`依赖已刷新，保存为第 ${updated.version_number} 版`)
      setContent(updated.content)
      setOverrides({})
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '依赖刷新失败'),
  })

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['designs', wid] })
  }, [queryClient, wid])

  // 跨文件零件名补全（C10）：首次触发懒加载 + 会话内缓存；请求失败静默降级为空候选
  const partsCache = useRef<DslPartOption[] | null>(null)
  const partsPending = useRef<Promise<DslPartOption[]> | null>(null)
  const fetchParts = useCallback(async () => {
    if (partsCache.current) return partsCache.current
    if (!partsPending.current) {
      partsPending.current = designsApi.list(wid)
        .then(items => items.map(item => ({
          label: item.file_key,
          detail: `${item.title}（${item.kind === 'assembly' ? '装配' : '零件'}）`,
        })))
        .catch(() => [])
        .then(options => {
          partsCache.current = options
          partsPending.current = null
          return options
        })
    }
    return partsPending.current
  }, [wid])

  const save = useMutation({
    mutationFn: () => designsApi.saveContent(wid, designId, { content }),
    onSuccess: (saved) => {
      message.success(`已保存为第 ${saved.version_number} 版`)
      setSaveError('')
      setContent(saved.content)
      invalidate()
    },
    onError: (err) => {
      // 保存被拒但内容不丢（边界 #2）：草稿保留在编辑器，错误详情在页头回显
      setSaveError(err instanceof Error ? err.message : '保存失败')
    },
  })

  const { data: versions = [] } = useQuery({
    queryKey: ['designs', wid, designId, 'versions'],
    queryFn: () => designsApi.listVersions(wid, designId),
    enabled: !!wid && !!designId,
  })

  // 版本回看（P2）：历史侧栏内点选版本，看该版原文
  const [viewingVersion, setViewingVersion] = useState<DesignVersionItem | null>(null)
  const { data: viewingDetail, isLoading: viewingLoading } = useQuery({
    queryKey: ['designs', wid, designId, 'versions', viewingVersion?.version_number],
    queryFn: () => designsApi.getVersion(wid, designId, viewingVersion!.version_number),
    enabled: viewingVersion != null,
  })

  // 版本恢复（P2）：以历史版原文重编译保存为新版本（viewer 不可用）
  const restore = useMutation({
    mutationFn: () => designsApi.restoreVersion(wid, designId, viewingVersion!.version_number),
    onSuccess: (restored) => {
      message.success(`已恢复 v${viewingVersion?.version_number} 为第 ${restored.version_number} 版`)
      setViewingVersion(null)
      setHistoryOpen(false)
      setContent(restored.content)
      setOverrides({})
      setSaveError('')
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '恢复失败')
    },
  })

  // Ctrl+S 保存（编辑器与全局快捷键都走到这里）
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        if (dirty && !isViewer && !save.isPending) save.mutate()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  /** 参数面板：当前 IR 的参数（改参即重编译，D3 —— 前端不做任何求值） */
  const params = preview.ir?.params ?? []
  const onParamChange = (name: string, value: InputNumberProps['value']) => {
    setOverrides(prev => {
      const next = { ...prev }
      if (value == null || Number.isNaN(value)) delete next[name]
      else next[name] = Number(value)
      return next
    })
  }

  /** 树↔视口联动（C7）：按大纲归属把源行映射到顶层 nodes 下标并高亮 */
  const irRef = useRef(preview.ir)
  irRef.current = preview.ir
  const runHighlight = useCallback((line: number | undefined) => {
    const outline = irRef.current?.outline?.children
    const api = viewportApiRef.current
    if (line == null || !outline || !api) {
      pendingHighlightLine.current = line ?? null
      return
    }
    const path = resolveOutlinePath(outline, line, Number(designId))
    const target = path[path.length - 1]
    if (!target) return
    const indices = collectNodeIndices(target)
    pendingHighlightLine.current = null
    // v4 旧快照无 node_index → 空集合 = 静默不高亮（I2）
    if (indices.length > 0) api.highlight(indices)
  }, [designId])

  useEffect(() => {
    runHighlight(revealLine)
  }, [revealLine, runHighlight])

  // 首屏竞态：IR / 视口 API 比 ?line= 晚到时补一次（pending 只在未成功时保留，
  // 已高亮的场景不会因重编译重复触发，§4#5）
  useEffect(() => {
    if (pendingHighlightLine.current != null) runHighlight(pendingHighlightLine.current)
  }, [preview.ir, runHighlight])

  /** 视口能力就绪：补一次待处理高亮（编译完成前点击也不丢） */
  const onViewportApi = useCallback((api: ViewportApi | null) => {
    viewportApiRef.current = api
    if (!api) return
    api.setGridVisible(gridVisible)
    if (pendingHighlightLine.current != null) runHighlight(pendingHighlightLine.current)
  }, [gridVisible, runHighlight])

  const toggleGrid = () => {
    const next = !gridVisible
    setGridVisible(next)
    viewportApiRef.current?.setGridVisible(next)
  }

  /** 分栏：预设 / 拖拽 / 持久化（D3 D10） */
  const applySplit = (value: number, persist = true) => {
    const clamped = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, Math.round(value)))
    setSplit(clamped)
    if (persist) {
      try {
        window.localStorage.setItem(SPLIT_KEY, String(clamped))
      } catch {
        // localStorage 不可用（隐私模式）时仅本次会话生效
      }
    }
  }

  const splitPreset = split >= 55 ? 'editor' : split <= 45 ? 'viewport' : 'even'
  const onPreset = (value: string | number) => {
    applySplit(value === 'editor' ? 60 : value === 'viewport' ? 40 : DEFAULT_SPLIT)
  }

  const onSplitterDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    draggingRef.current = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const onSplitterMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return
    const host = workbenchRef.current
    const rect = host?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    // 每侧至少 320px：按容器宽度换算成百分比下限，再夹到 25%–75%
    const minRatio = (320 / rect.width) * 100
    const floor = Math.max(SPLIT_MIN, minRatio)
    const ceil = Math.min(SPLIT_MAX, 100 - minRatio)
    const ratio = ((event.clientX - rect.left) / rect.width) * 100
    applySplit(Math.min(ceil, Math.max(floor, ratio)))
  }
  const onSplitterUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    applySplit(split)
  }

  const toggleParamsCollapsed = () => {
    setParamsCollapsed(prev => {
      const next = !prev
      try {
        window.localStorage.setItem(PARAMS_COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        // 忽略存储失败（隐私模式）
      }
      return next
    })
  }

  const diagnostics: DesignDiagnostic[] = useMemo(() => preview.diagnostics, [preview.diagnostics])
  const errorCount = diagnostics.length
  const canSave = dirty && !isViewer && !preview.compiling

  const closeHistory = () => {
    setHistoryOpen(false)
    setViewingVersion(null)
  }

  const revealSourceLine = (line: number) => setSearchParams(
    prev => {
      const next = new URLSearchParams(prev)
      next.set('line', String(line))
      return next
    },
    { replace: true },
  )

  return (
    <div className="cn-dsl-page">
      {/* 顶部工具栏：身份 / 状态标签在左，动作按钮在右；恒单行（C6 D6） */}
      <div className="cn-dsl-toolbar">
        <div className="cn-dsl-toolbar-main">
          <Link to={`/w/${wid}/design`} aria-label="返回设计列表">
            <Button icon={<ArrowLeftOutlined />} type="text" />
          </Link>
          <Text strong className="cn-dsl-title">{detail?.title ?? '设计'}</Text>
          <Space size={4} className="cn-dsl-toolbar-tags">
            {detail && (
              <Tag className="cn-dsl-status-tag" data-testid="design-version-tag">
                v{detail.version_number}
              </Tag>
            )}
            {preview.compiling ? (
              <Tag color="processing" className="cn-dsl-status-tag" data-testid="design-compile-status">
                <LoadingOutlined /> 编译中
              </Tag>
            ) : errorCount > 0 ? (
              <Tag color="error" className="cn-dsl-status-tag" data-testid="design-compile-status">
                <CloseCircleFilled /> {errorCount} 处错误
              </Tag>
            ) : (
              <Tag color="success" className="cn-dsl-status-tag" data-testid="design-compile-ok">
                <CheckCircleFilled /> 编译通过
                {preview.ir && preview.ir.nodes.length === 0 && '（顶层尚无实例）'}
              </Tag>
            )}
            {dirty && <Tag color="warning" className="cn-dsl-status-tag">未保存</Tag>}
            {isViewer && <Tag className="cn-dsl-status-tag">只读</Tag>}
          </Space>
        </div>
        <Space size={8} className="cn-dsl-toolbar-actions">
          {!narrow && (
            <Segmented
              size="small"
              value={splitPreset}
              onChange={onPreset}
              data-testid="design-split-preset"
              options={[
                { value: 'editor', label: '编辑' },
                { value: 'even', label: '均分' },
                { value: 'viewport', label: '视口' },
              ]}
            />
          )}
          <Suspense fallback={<Button icon={<CompassOutlined />} disabled>更多</Button>}>
            <DesignMoreMenu
              ir={preview.ir}
              title={detail?.title ?? '设计'}
              versionCount={versions.length}
              onHistory={() => setHistoryOpen(true)}
            />
          </Suspense>
          <Button
            icon={<SaveOutlined />}
            type="primary"
            disabled={!canSave}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            保存{dirty ? '' : '（无变更）'}
          </Button>
        </Space>
      </div>

      {saveError && (
        <Alert
          type="error"
          showIcon
          message="保存被拒绝（草稿已保留）"
          description={saveError}
          closable
          onClose={() => setSaveError('')}
        />
      )}

      {detail?.dependencies_stale && (
        <Alert
          type="warning"
          showIcon
          data-testid="design-stale-banner"
          message="依赖的零件文件已更新，当前打开的是旧快照"
          description="历史版本按依赖快照复现（不取最新）；点击刷新将以最新依赖重新编译并保存新版本。"
          action={(
            <Button
              size="small"
              type="primary"
              loading={refresh.isPending}
              disabled={isViewer || dirty}
              onClick={() => refresh.mutate()}
            >
              刷新依赖
            </Button>
          )}
        />
      )}

      {/* 诊断条：编译状态用标签表达，具体错误在标签下方单行横向滚动展开 */}
      {errorCount > 0 && (
        <div className="cn-dsl-diag-bar" role="status">
          <ExperimentOutlined />
          {diagnostics.map((item, index) => (
            <div key={`${item.line}-${item.col}-${index}`} className="cn-dsl-diag-item">
              <Tag color="error" style={{ marginInlineEnd: 4 }}>第{item.line}行</Tag>
              <Text type="danger">{item.message}</Text>
            </div>
          ))}
        </div>
      )}

      {/* 左右两栏（可拖分栏）：编辑器 / 预览各自内置滚动，页面不整体滚动 */}
      <div
        ref={workbenchRef}
        className="cn-dsl-workbench"
        data-testid="design-workbench"
        style={narrow
          ? undefined
          : { gridTemplateColumns: `minmax(0, ${split}fr) 6px minmax(0, ${100 - split}fr)` }}
      >
        <div className="cn-dsl-pane cn-dsl-pane--editor">
          <div className="cn-dsl-editor-host">
            {isLoading ? <Skeleton active /> : (
              <DslEditor
                value={content}
                onChange={(next) => { setContent(next); setSaveError('') }}
                diagnostics={diagnostics}
                placeholder="param width = 80&#10;box(size = [width, 40, 12])"
                readOnly={isViewer}
                fetchParts={fetchParts}
                // 原文回填完成后才定位，避免首帧空文档把行号钳到第 1 行
                revealLine={contentReady ? revealLine : undefined}
              />
            )}
          </div>
        </div>

        {!narrow && (
          <div
            className="cn-dsl-splitter"
            role="separator"
            aria-orientation="vertical"
            aria-label="调整编辑器与预览宽度"
            data-testid="design-splitter"
            onPointerDown={onSplitterDown}
            onPointerMove={onSplitterMove}
            onPointerUp={onSplitterUp}
            onPointerCancel={onSplitterUp}
          />
        )}

        <div className="cn-dsl-pane cn-dsl-pane--preview">
          <div className="cn-dsl-viewport">
            <div className="cn-dsl-preview-host">
              <Suspense fallback={<Skeleton active style={{ height: '100%' }} />}>
                <PreviewCanvas ir={preview.ir} onStats={setStats} onViewportApi={onViewportApi} />
              </Suspense>
            </div>
            {/* 视口悬浮工具条（C3）：七向定向 / 布满 / 网格 */}
            <div className="cn-dsl-viewport-toolbar" data-testid="design-viewport-toolbar">
              <Dropdown
                trigger={['click']}
                menu={{
                  items: VIEW_PRESETS.map(preset => ({ key: preset.key, label: preset.label })),
                  onClick: ({ key }) => viewportApiRef.current?.orientTo(key as ViewOrientation),
                }}
              >
                <Button size="small" type="text" icon={<CompassOutlined />} aria-label="视图定向">
                  定向
                </Button>
              </Dropdown>
              <Tooltip title="布满视图">
                <Button
                  size="small"
                  type="text"
                  icon={<ExpandOutlined />}
                  aria-label="布满视图"
                  onClick={() => viewportApiRef.current?.fit()}
                />
              </Tooltip>
              <Tooltip title={gridVisible ? '隐藏网格' : '显示网格'}>
                <Button
                  size="small"
                  type={gridVisible ? 'text' : 'default'}
                  icon={<BorderOutlined />}
                  aria-label="网格显示开关"
                  aria-pressed={gridVisible}
                  data-testid="design-grid-toggle"
                  onClick={toggleGrid}
                />
              </Tooltip>
            </div>
            {/* 视口状态条（C4）：单位取 IR 显式声明（D5），统计来自 onStats */}
            <div className="cn-dsl-statusbar" data-testid="design-statusbar">
              {preview.ir?.units.length ?? '—'} · 节点 {stats.nodes} · 三角 {stats.triangles}
            </div>
          </div>
          <DesignParamsPanel
            params={params}
            constraints={preview.ir?.constraints ?? []}
            overrides={overrides}
            collapsed={paramsCollapsed}
            onToggleCollapsed={toggleParamsCollapsed}
            onParamChange={onParamChange}
            onReset={() => setOverrides({})}
            onReveal={revealSourceLine}
          />
        </div>
      </div>

      {/* 版本历史侧栏：列表 → 选中版本回看原文 + 恢复入口（viewer 只读） */}
      <Drawer
        title={viewingVersion
          ? `版本回看：v${viewingVersion.version_number}`
          : `版本历史（${versions.length}）`}
        open={historyOpen}
        size={460}
        onClose={closeHistory}
        footer={viewingVersion != null && !isViewer ? (
          <Space>
            <Popconfirm
              title={`以 v${viewingVersion.version_number} 原文重新编译并保存为新版本？`}
              onConfirm={() => restore.mutate()}
            >
              <Button type="primary" danger icon={<RollbackOutlined />} loading={restore.isPending}>
                恢复此版本
              </Button>
            </Popconfirm>
            <Button onClick={() => setViewingVersion(null)}>返回列表</Button>
          </Space>
        ) : null}
      >
        {viewingVersion == null ? (
          versions.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本" />
          ) : (
            <div className="cn-dsl-version-list">
              {versions.map(version => (
                <Button
                  key={version.id}
                  type="text"
                  block
                  className="cn-dsl-version-row"
                  aria-label={`回看版本 ${version.version_number}`}
                  onClick={() => setViewingVersion(version)}
                >
                  <Tag style={{ marginInlineEnd: 8 }}>v{version.version_number}</Tag>
                  <span className="cn-dsl-version-text">
                    {version.comment ? version.comment : '未填写变更说明'}
                  </span>
                  <Text type="secondary" className="cn-dsl-version-time">
                    {formatDateTime(version.created_at)}
                  </Text>
                </Button>
              ))}
            </div>
          )
        ) : (
          <>
            <Space size={8} wrap style={{ marginBottom: 8 }}>
              <Tag>第 {viewingVersion.version_number} 版</Tag>
              <Text type="secondary">
                {formatDateTime(viewingDetail?.created_at ?? viewingVersion.created_at)}
              </Text>
            </Space>
            {viewingDetail?.comment && <Text type="secondary">备注：{viewingDetail.comment}</Text>}
            {viewingDetail && viewingDetail.dependencies.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">依赖快照：</Text>
                <Space size={4} wrap>
                  {viewingDetail.dependencies.map(dep => (
                    <Tag key={dep.file_key}>{dep.file_key}@v{dep.version_number}</Tag>
                  ))}
                </Space>
              </div>
            )}
            {viewingLoading ? (
              <Skeleton active />
            ) : (
              <pre data-testid="design-version-content" className="cn-dsl-version-pre">
                {viewingDetail?.content ?? ''}
              </pre>
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}
