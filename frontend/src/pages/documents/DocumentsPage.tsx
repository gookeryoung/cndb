/** 文档管理页 — 顶层系列卡片总览 + 文件夹列表 / 树 / 搜索入口. */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Checkbox,
  Drawer,
  Dropdown,
  Empty,
  Input,
  Listy,
  Menu,
  Modal,
  Popconfirm,
  Popover,
  Radio,
  Segmented,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  TreeSelect,
  Typography,
  message,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { MenuProps } from 'antd'
import MoveDocumentModal, { moveSummary } from './MoveDocumentModal'
import {
  ApartmentOutlined,
  AppstoreOutlined,
  ArrowLeftOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  FileAddOutlined,
  FilterOutlined,
  FolderAddOutlined,
  FolderOutlined,
  ImportOutlined,
  InfoCircleOutlined,
  LockOutlined,
  MoreOutlined,
  PushpinOutlined,
  SearchOutlined,
  SortAscendingOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  describeSort, DOC_SORT_OPTIONS, setDocTitleFilter, sortFlatByDocSort, sortToValue,
  useDocSortPref, useDocTitleFilter, valueToSort,
} from './docTreeSort'
import { clearRecentDocs, loadRecentDocs } from './recentDocs'
import { documentsApi } from '@/api/documents'
import type { DocumentItem, VaultExportStyle } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { useCreateParam } from '@/hooks/useCreateParam'
import { buildDocTree, descendantIds, findNodeById } from './DocumentTree'
import { buildFolderStatusCounts, buildFolderSummaries, buildSeriesStats, seriesStatsOf } from './seriesStats'
import DocumentTable from './DocumentTable'
import { usePersistedState } from '@/utils/persistedState'
import { DOC_STATUS_META, formatDate, formatTime, STATUS_COLORS, STATUS_LABELS } from './documentDisplay'
import { formatMeta } from '@/components/Document/docFormat'
import CnListMeta from '@/components/CnListMeta'
import TrashDrawer from './TrashDrawer'
import DocumentImportModal from './DocumentImportModal'
import type { DocTreeNode } from './DocumentTree'
import { formatSize } from '@/utils/formatSize'
import { formatRelativeTime } from '@/utils/datetime'
import { createPptxPrefetcher, prefetchPptxPreview } from './pptxPrefetch'

const { Text } = Typography

/** 移动端时间分组（需求 0167 C7）：仅展示层分组，不改变 docSort 偏好与权限过滤 */
type DocTimeGroupKey = 'pinned' | 'today' | 'week' | 'earlier'
const DOC_TIME_GROUPS: { key: DocTimeGroupKey; label: string }[] = [
  { key: 'pinned', label: '置顶' },
  { key: 'today', label: '今天' },
  { key: 'week', label: '本周' },
  { key: 'earlier', label: '更早' },
]

function groupDocsByTime(items: DocumentItem[]): Record<DocTimeGroupKey, DocumentItem[]> {
  const groups: Record<DocTimeGroupKey, DocumentItem[]> = { pinned: [], today: [], week: [], earlier: [] }
  const todayStart = dayjs().startOf('day').valueOf()
  // 周一为一周起点（不依赖 dayjs locale 设置）
  const weekStart = dayjs().startOf('day').subtract((dayjs().day() + 6) % 7, 'day').valueOf()
  for (const doc of items) {
    if (doc.pinned) {
      groups.pinned.push(doc)
      continue
    }
    const updated = dayjs(doc.updated_at)
    const ts = updated.isValid() ? updated.valueOf() : Number.NaN
    if (Number.isFinite(ts) && ts >= todayStart) groups.today.push(doc)
    else if (Number.isFinite(ts) && ts >= weekStart) groups.week.push(doc)
    else groups.earlier.push(doc)
  }
  return groups
}


// 测试与内部复用：系列统计的具名导出保留在本模块（实现见 ./seriesStats）
export { buildFolderStatusCounts, buildSeriesStats, seriesStatsOf } from './seriesStats'
export type { SeriesSummary } from './seriesStats'

/** 内容区分块标题：文件夹 / 文档分块，附数量，便于一眼区分两类条目 */
function SectionTitle({ label, count, compact = false }: { label: string; count: number; compact?: boolean }) {
  return (
    <div
      data-testid="doc-section-title"
      style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: compact ? 4 : 8 }}
    >
      <Text strong>{label}</Text>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>{count} 项</Text>
    </div>
  )
}

/** 桌面单行列表的状态降噪：圆点 + 文本，沿用既有色义，不引入新色值 */
const STATUS_BADGE: Record<string, 'default' | 'success' | 'warning'> = {
  draft: 'default',
  published: 'success',
  archived: 'warning',
}

export default function DocumentsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const { isMobile, width } = useResponsive()
  // 窄桌面（如 900px 且侧栏展开）：标签 / 状态收进「筛选」气泡，保证页头仍为单行
  const isNarrowDesktop = !isMobile && width < 1100

  // 桌面端悬停 PPTX 行时防抖预取渲染库与原件；移出 / 卸载即取消（需求 0128 C5）
  const pptxPrefetcher = useMemo(
    () => createPptxPrefetcher(doc => prefetchPptxPreview(qc, workspaceId, doc)),
    [qc, workspaceId],
  )
  useEffect(() => () => pptxPrefetcher.cancel(), [pptxPrefetcher])

  // 当前文件夹写入 URL（?parent=）：支持从编辑器面包屑深链、刷新与分享
  const parentParam = searchParams.get('parent')
  const parentId = parentParam !== null && parentParam !== '' ? Number(parentParam) : null
  // 标签筛选写入 URL（?tag=）：可分享、可刷新
  const tagParam = searchParams.get('tag')
  const tagFilter = tagParam !== null && tagParam !== '' && !Number.isNaN(Number(tagParam))
    ? Number(tagParam)
    : undefined
  // 状态筛选写入 URL（?status=），控件在内容区顶部（需求 0065），与 parent / tag 同机制
  const statusParam = searchParams.get('status')
  const statusFilter = ['draft', 'published', 'archived'].includes(statusParam ?? '')
    ? (statusParam as string)
    : undefined
  // 排序口径：与侧栏树共享同一本地偏好（docTreeSort），两处 UI 实时同步（需求 0065 三次修订）
  const [docSort, setDocSort] = useDocSortPref()
  // 视图偏好（需求 0162）：列表为主，网格保留为可选；本地偏好跨文件夹共享
  const [docView, setDocView] = usePersistedState<'list' | 'grid'>('cndb_doc_view_v1', 'list')

  const updateParams = useCallback((patch: { parent?: number | null; tag?: number | null; status?: string | null }) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (patch.parent !== undefined) {
        if (patch.parent === null) next.delete('parent')
        else next.set('parent', String(patch.parent))
      }
      if (patch.tag !== undefined) {
        if (patch.tag === null) next.delete('tag')
        else next.set('tag', String(patch.tag))
      }
      if (patch.status !== undefined) {
        if (patch.status === null) next.delete('status')
        else next.set('status', patch.status)
      }
      return next
    }, { replace: true })
  }, [setSearchParams])

  const setParentId = useCallback((id: number | null) => {
    setSelectedIds([])  // 进入下一层级时清空多选，避免跨层级误操作
    updateParams({ parent: id })
  }, [updateParams])

  // 标题过滤关键词：与侧栏「过滤标题」联动（共享同一关键词，一套 UI 两处生效）
  const [titleKeyword] = useDocTitleFilter()
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState<'doc' | 'folder'>('doc')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  // 重命名弹窗（系列与列表行共用）：target 区分来源，决定标题文案与输入框 testid
  const [renameTarget, setRenameTarget] = useState<{ id: number; title: string; isSeries: boolean } | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [moveOpen, setMoveOpen] = useState(false)
  const [moveTarget, setMoveTarget] = useState<number>(0)
  // 列表行「移动」弹窗：目标 = { id, title, parent 初始值（0 = 根目录） }
  const [rowMove, setRowMove] = useState<{ id: number; title: string; parent: number } | null>(null)
  // 回收站抽屉
  const [trashOpen, setTrashOpen] = useState(false)
  // 通用导入弹窗（多文件 / 压缩包 / Obsidian 库 zip）
  const [fileImportOpen, setFileImportOpen] = useState(false)
  // 最近打开：读取本地历史（清空后用 version 触发重渲染）
  const [recentVersion, setRecentVersion] = useState(0)
  // 批量操作：当前层级多选 + 批量移动弹窗
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchMoveOpen, setBatchMoveOpen] = useState(false)
  // 跨工作区移动（ADR 0155）：与工作区内「移动到…」并列
  const [moveWorkspaceOpen, setMoveWorkspaceOpen] = useState(false)
  const [batchMoveTarget, setBatchMoveTarget] = useState<number>(0)
  // 移动端筛选抽屉（第三行，默认收起）：标签 / 状态是低频筛选，收起后顶栏只留一行操作
  const [filterOpen, setFilterOpen] = useState(false)
  // 移动端多选模式（需求 0166 C6）：勾选框按需出现，退出时清空选择
  const [selectMode, setSelectMode] = useState(false)
  // 移动端行详情（需求 0166 C3）：大小 / 版本 / 状态分布等低频信息不占列表行
  const [detailDoc, setDetailDoc] = useState<DocumentItem | null>(null)
  // 移动端搜索默认收起为图标，点击后原地展开（需求 0167 C2）
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  // 移动端长按行的快捷菜单（需求 0167 C6）；⋯ 菜单仍是常规路径
  const [quickDoc, setQuickDoc] = useState<DocumentItem | null>(null)
  const longPressTimer = useRef<number | null>(null)
  const suppressRowClick = useRef(false)
  const startLongPress = (doc: DocumentItem) => {
    if (longPressTimer.current !== null) window.clearTimeout(longPressTimer.current)
    longPressTimer.current = window.setTimeout(() => {
      suppressRowClick.current = true
      setQuickDoc(doc)
    }, 500)
  }
  const cancelLongPress = () => {
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
  }
  useEffect(() => cancelLongPress, [])
  // hook 版 Modal：确认框走当前 ConfigProvider 主题（静态 Modal.confirm 读不到动态主题）
  const [modal, modalContextHolder] = Modal.useModal()

  // 全量树：顶层系列统计 + 面包屑祖先链 + 系列详情共用（React Query 按 key 共享缓存）
  const treeQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tree'],
    queryFn: () => documentsApi.tree(workspaceId),
    enabled: Number.isFinite(workspaceId),
  })

  // 当前系列详情（进入文件夹后）：节点定位 + 递归聚合统计
  const currentFolderNode = useMemo(() => {
    if (parentId === null) return null
    const node = findNodeById(buildDocTree(treeQuery.data ?? []), parentId)
    return node && node.is_folder ? node : null
  }, [treeQuery.data, parentId])
  const currentSeries = useMemo(
    () => (currentFolderNode ? seriesStatsOf(currentFolderNode) : null),
    [currentFolderNode],
  )
  // 文件夹行的状态展示：按递归子孙文档聚合，与系列卡片 / 系列详情头部同一口径。
  // 修复：父级列表里文件夹曾直接显示自身 status（多为 draft），与进入该文件夹后看到的
  // 「已发布」统计不一致。
  const folderStatusCounts = useMemo(
    () => buildFolderStatusCounts(treeQuery.data ?? []),
    [treeQuery.data],
  )
  // 文件夹行副标题：递归文档数 / 子文件夹数 / 标签数（与卡片同口径）
  const folderSummaries = useMemo(
    () => buildFolderSummaries(treeQuery.data ?? []),
    [treeQuery.data],
  )

  const docsQuery = useQuery({
    queryKey: ['documents', workspaceId, 'list', parentId, statusFilter, tagFilter],
    queryFn: () =>
      documentsApi.list(workspaceId, {
        parent_id: parentId ?? undefined,
        status: statusFilter,
        tag_id: tagFilter,
        limit: 200,
      }),
    // 子级列表走 list 端点；顶层散文档由全量树派生（list 不传 parent_id 会返回全部层级）
    enabled: Number.isFinite(workspaceId) && parentId !== null,
  })

  // 标签筛选选项（需求 0065：筛选控件在内容区顶部）
  const tagsQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tags'],
    queryFn: () => documentsApi.tags(workspaceId),
    enabled: Number.isFinite(workspaceId),
  })

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
  }, [qc, workspaceId])

  const createMut = useMutation({
    mutationFn: () =>
      documentsApi.create(workspaceId, {
        title: newTitle.trim(),
        content: createType === 'doc' ? newContent : '',
        is_folder: createType === 'folder',
        parent_id: parentId,
      }),
    onSuccess: doc => {
      message.success(createType === 'folder' ? '文件夹已创建' : '文档已创建')
      setCreateOpen(false)
      setNewTitle('')
      setNewContent('')
      invalidate()
      if (createType === 'doc') navigate(`/w/${workspaceId}/documents/${doc.id}`)
    },
    onError: () => message.error('创建失败'),
  })

  const deleteMut = useMutation({
    mutationFn: (docId: number) => documentsApi.remove(workspaceId, docId),
    onSuccess: (_data, docId) => {
      message.success('已删除')
      // 删除的是当前系列详情时回退到其上级
      if (docId === parentId) {
        const folderDoc = currentSeries?.folder
        setParentId(folderDoc?.parent_id ?? null)
      }
      invalidate()
    },
    onError: () => message.error('删除失败'),
  })

  // 文档导出（需求 0088）：两种方式均为 .zip —— 压缩文档（默认）/ Obsidian 库；
  // 原件族（PDF / Office / 图片等）按原件导出，Markdown 导出正文
  const [exportOpen, setExportOpen] = useState(false)
  const [exportStyle, setExportStyle] = useState<VaultExportStyle>('archive')
  const vaultExportMut = useMutation({
    mutationFn: (style: VaultExportStyle) => documentsApi.vaultExport(workspaceId, style),
    onSuccess: ({ blob, filename }) => {
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      // 优先用后端 Content-Disposition 的统一命名（{工作区名}-{方式}-{时间戳}.zip）
      link.download = filename ?? `documents-${ts}.zip`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      message.success(exportStyle === 'archive' ? '已导出压缩文档' : '已导出 Obsidian 库')
      setExportOpen(false)
    },
    onError: (err: unknown) => message.error(err instanceof Error ? err.message : '导出失败'),
  })

  // 重命名（PATCH title；系列与列表行共用）
  const renameMut = useMutation({
    mutationFn: () =>
      documentsApi.updateMeta(workspaceId, renameTarget!.id, {
        title: renameValue.trim(),
      }),
    onSuccess: () => {
      message.success('已重命名')
      setRenameTarget(null)
      invalidate()
    },
    onError: () => message.error('重命名失败'),
  })

  // 列表行移动（PATCH parent_id；0 = 根目录约定）
  const rowMoveMut = useMutation({
    mutationFn: () =>
      documentsApi.updateMeta(workspaceId, rowMove!.id, {
        parent_id: rowMove!.parent,
      }),
    onSuccess: () => {
      message.success('已移动')
      setRowMove(null)
      invalidate()
    },
    onError: () => message.error('移动失败'),
  })

  // 置顶 / 取消置顶（用户级标记：POST / DELETE /pin）
  const pinMut = useMutation({
    mutationFn: (doc: DocumentItem) =>
      doc.pinned
        ? documentsApi.unpinDocument(workspaceId, doc.id)
        : documentsApi.pinDocument(workspaceId, doc.id),
    onSuccess: (_res, doc) => {
      message.success(doc.pinned ? '已取消置顶' : '已置顶')
      invalidate()
    },
    onError: () => message.error('置顶操作失败'),
  })

  // 系列移动（PATCH parent_id；0 = 根目录约定）
  const seriesMoveMut = useMutation({
    mutationFn: () =>
      documentsApi.updateMeta(workspaceId, currentSeries!.folder.id, {
        parent_id: moveTarget,
      }),
    onSuccess: () => {
      message.success('已移动')
      setMoveOpen(false)
      // 移出当前层级后回到总览（新位置在树中呈现）
      setParentId(null)
      invalidate()
    },
    onError: () => message.error('移动失败'),
  })

  /** 批量移动 / 删除（后端逐项校验，skipped 为被跳过项明细） */
  const batchMut = useMutation({
    mutationFn: (payload: { action: 'move' | 'delete'; ids: number[]; parent_id?: number | null }) =>
      documentsApi.batch(workspaceId, payload),
    onSuccess: res => {
      const actionLabel = res.action === 'move' ? '移动' : '删除'
      const skipped = res.skipped.length
      if (skipped > 0) {
        message.warning(`已${actionLabel} ${res.updated} 项，跳过 ${skipped} 项（${res.skipped[0].reason}）`)
      } else {
        message.success(`已${actionLabel} ${res.updated} 项`)
      }
      setSelectedIds([])
      setBatchMoveOpen(false)
      invalidate()
    },
    onError: () => message.error('批量操作失败'),
  })

  const toggleSelected = (docId: number) => {
    setSelectedIds(prev => (prev.includes(docId) ? prev.filter(id => id !== docId) : [...prev, docId]))
  }
  const toggleSelectMode = () => {
    if (selectMode) setSelectedIds([])
    setSelectMode(v => !v)
  }

  const seriesList = useMemo(() => {
    const all = buildSeriesStats(treeQuery.data ?? [])
    const kw = titleKeyword.trim().toLowerCase()
    const hit = kw ? all.filter(s => s.folder.title.toLowerCase().includes(kw)) : all
    // 根层主体是系列卡片，与侧栏树共用同一排序偏好（最新更新时间取整个系列的聚合值）
    return sortFlatByDocSort(
      hit.map(s => ({
        ...s,
        id: s.folder.id,
        title: s.folder.title,
        is_folder: true,
        sort_order: s.folder.sort_order,
        created_at: s.folder.created_at,
        updated_at: s.latestUpdate ?? s.folder.updated_at,
        pinned: s.folder.pinned,
      })),
      docSort,
    )
  }, [treeQuery.data, titleKeyword, docSort])

  const breadcrumbItems = useMemo(() => {
    const map = new Map<number, DocumentItem>()
    for (const d of treeQuery.data ?? []) map.set(d.id, d)
    const chain: DocumentItem[] = []
    let cur = parentId
    while (cur !== null) {
      const node = map.get(cur)
      if (!node) break
      chain.unshift(node)
      cur = node.parent_id
    }
    return chain
  }, [treeQuery.data, parentId])

  const filtered = useMemo(() => {
    const items = docsQuery.data?.items ?? []
    if (!titleKeyword.trim()) return items
    const kw = titleKeyword.trim().toLowerCase()
    return items.filter(d => d.title.toLowerCase().includes(kw))
  }, [docsQuery.data, titleKeyword])

  // 列表数据：顶层散文档由全量树派生（根级非文件夹项，前端应用标题/状态过滤）；
  // 子级列全部子项（list 端点按 parent_id 过滤）
  const listItems = useMemo(() => {
    const raw = parentId !== null
      ? filtered
      : (treeQuery.data ?? []).filter(
        d =>
          d.parent_id == null &&
          !d.is_folder &&
          (!titleKeyword.trim() || d.title.toLowerCase().includes(titleKeyword.trim().toLowerCase())) &&
          (!statusFilter || d.status === statusFilter) &&
          (tagFilter === undefined || d.tag_ids.includes(tagFilter)),
      )
    // 置顶优先 + 与侧栏树共用的排序偏好
    return sortFlatByDocSort(raw, docSort)
  }, [filtered, parentId, treeQuery.data, titleKeyword, statusFilter, tagFilter, docSort])

  // 子级内容分块：文件夹与文档分开渲染，避免混排难区分（顶层文件夹由上方系列卡片承载）
  const subFolders = useMemo(
    () => (parentId !== null ? listItems.filter(d => d.is_folder) : []),
    [parentId, listItems],
  )
  const fileItems = useMemo(
    () => (parentId !== null ? listItems.filter(d => !d.is_folder) : listItems),
    [parentId, listItems],
  )

  /** 当前层级**可见**的可选项（根层为系列卡片 + 散文档，子层为列表项）：全选与已选统计只用它 */
  const selectableIds = useMemo(
    () =>
      parentId === null
        ? [...seriesList.map(s => s.folder.id), ...listItems.map(d => d.id)]
        : listItems.map(d => d.id),
    [parentId, seriesList, listItems],
  )
  const allSelected = selectableIds.length > 0 && selectedIds.length === selectableIds.length

  const openCreate = (type: 'doc' | 'folder') => {
    setCreateType(type)
    setCreateOpen(true)
  }

  /** 列表行打开：文件夹下钻当前层级，文档进编辑器（网格卡片与列表共用） */
  const openDoc = (doc: DocumentItem) => {
    if (doc.is_folder) setParentId(doc.id)
    else navigate(`/w/${workspaceId}/documents/${doc.id}`)
  }

  // 命令面板「新建文档」经 URL ?create=1 触发（0067 C3）
  useCreateParam(() => openCreate('doc'))

  /** 最近打开（过滤掉已删除/不可见的文档，避免死链） */
  const recentDocs = useMemo(() => {
    const visible = new Set((treeQuery.data ?? []).map(d => d.id))
    return loadRecentDocs(workspaceId).filter(it => visible.has(it.id))
    // recentVersion：清空历史后强制重算（localStorage 不是响应式数据源）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeQuery.data, workspaceId, recentVersion])

  /** 批量跨工作区移动时的「含几个文件夹」提示（ADR 0155） */
  const selectedFolderCount = useMemo(() => {
    const all = [...(treeQuery.data ?? []), ...(docsQuery.data?.items ?? [])]
    const byId = new Map(all.map(item => [item.id, item]))
    return selectedIds.filter(id => byId.get(id)?.is_folder).length
  }, [selectedIds, treeQuery.data, docsQuery.data])

  /** 批量移动目标下拉：根目录 + 全部文件夹，排除所选节点及其子孙（防环） */
  const batchMoveTreeData = useMemo(() => {
    if (!batchMoveOpen) return []
    const roots = buildDocTree(treeQuery.data ?? [])
    const excluded = new Set<number>()
    for (const id of selectedIds) {
      const node = findNodeById(roots, id)
      if (node) for (const cid of descendantIds(node)) excluded.add(cid)
    }
    const toOption = (node: DocTreeNode): DataNode & { value: number } => ({
      key: node.id,
      value: node.id,
      title: node.title,
      disabled: excluded.has(node.id),
      children: node.children.filter(c => c.is_folder).map(toOption),
    })
    return [{ value: 0, title: '（根目录）', children: roots.filter(n => n.is_folder).map(toOption) }]
  }, [batchMoveOpen, selectedIds, treeQuery.data])

  // 系列移动目标下拉：根目录 + 全部文件夹（排除自身及子孙，防环）
  const seriesMoveTreeData = useMemo(() => {
    if (!moveOpen || !currentFolderNode) return []
    const excluded = new Set(descendantIds(currentFolderNode))
    const toOption = (node: DocTreeNode): DataNode & { value: number } => ({
      key: node.id,
      value: node.id,
      title: node.title,
      disabled: excluded.has(node.id),
      children: node.children.filter(c => c.is_folder).map(toOption),
    })
    const roots = buildDocTree(treeQuery.data ?? [])
    return [
      { value: 0, title: '（根目录）', children: roots.filter(n => n.is_folder).map(toOption) },
    ]
  }, [moveOpen, currentFolderNode, treeQuery.data])

  // 列表行移动目标下拉：根目录 + 全部文件夹（排除该节点自身及其子孙，防环）
  const rowMoveTreeData = useMemo(() => {
    if (!rowMove) return []
    const roots = buildDocTree(treeQuery.data ?? [])
    const node = findNodeById(roots, rowMove.id)
    const excluded = new Set(node ? descendantIds(node) : [])
    const toOption = (n: DocTreeNode): DataNode & { value: number } => ({
      key: n.id,
      value: n.id,
      title: n.title,
      disabled: excluded.has(n.id),
      children: n.children.filter(c => c.is_folder).map(toOption),
    })
    return [{ value: 0, title: '（根目录）', children: roots.filter(n => n.is_folder).map(toOption) }]
  }, [rowMove, treeQuery.data])

  if (!Number.isFinite(workspaceId)) {
    return <Alert type="error" title="无效的工作区" />
  }

  /** 返回上级：以当前面包屑末项的 parent_id 为目标 */
  const goUp = () => {
    const parentDoc = breadcrumbItems[breadcrumbItems.length - 1]
    setParentId(parentDoc?.parent_id ?? null)
  }

  const upButton = parentId !== null && (
    <Button icon={<ArrowLeftOutlined />} onClick={goUp}>上一级</Button>
  )
  /** 移动端返回：纯图标，把横向空间让给面包屑 */
  const mobileUpButton = parentId !== null && (
    <Button icon={<ArrowLeftOutlined />} aria-label="上一级" onClick={goUp} />
  )
  const breadcrumbNode = (
    <Breadcrumb
      items={[
        { title: <a onClick={() => setParentId(null)}>文档</a> },
        ...breadcrumbItems.map(b => ({ title: b.title })),
      ]}
    />
  )
  /** 移动端面包屑（需求 0167 C3）：层级过深时中间折叠为「…」，首尾始终可见 */
  const mobileBreadcrumbNode = (
    <Breadcrumb
      items={[
        { title: <a onClick={() => setParentId(null)}>文档</a> },
        ...(breadcrumbItems.length > 2 ? [{ title: '…' }] : []),
        ...(breadcrumbItems.length > 2 ? breadcrumbItems.slice(-2) : breadcrumbItems).map(b => ({ title: b.title })),
      ]}
    />
  )
  const renderSearchInput = (style: CSSProperties) => (
    <Input
      allowClear
      prefix={<SearchOutlined />}
      placeholder="过滤标题"
      style={style}
      value={titleKeyword}
      onChange={e => setDocTitleFilter(e.target.value)}
    />
  )
  /** 标签 / 状态筛选（需求 0065 第二次修订）：写 URL（?tag=&status=），与 parent / order 同机制 */
  const renderTagSelect = (style: CSSProperties) => (
    <Select
      allowClear
      placeholder="标签"
      style={style}
      value={tagFilter}
      data-testid="doc-tag-filter"
      onChange={(v?: number) => updateParams({ tag: v ?? null })}
      options={(tagsQuery.data ?? []).map(tag => ({ value: tag.id, label: tag.name }))}
    />
  )
  const renderStatusSelect = (style: CSSProperties) => (
    <Select
      allowClear
      placeholder="状态"
      style={style}
      value={statusFilter}
      data-testid="doc-status-filter"
      onChange={(v?: string) => updateParams({ status: v ?? null })}
      options={[
        { value: 'draft', label: '草稿' },
        { value: 'published', label: '已发布' },
        { value: 'archived', label: '归档' },
      ]}
    />
  )
  /** 排序按钮（需求 0065 三次修订）：与侧栏树排序共享同一偏好，两处 UI 改一处即同步 */
  const renderSortButton = (testid: string) => (
    <Dropdown
      menu={{
        items: DOC_SORT_OPTIONS.map(o => ({ key: o.value, label: o.label })),
        selectable: true,
        selectedKeys: [sortToValue(docSort)],
        onClick: ({ key }) => setDocSort(valueToSort(key)),
      }}
      trigger={['click']}
    >
      <Tooltip title={`排序：${describeSort(docSort)}`}>
        <Button
          icon={<SortAscendingOutlined />}
          aria-label={`排序方式：${describeSort(docSort)}`}
          data-testid={testid}
        />
      </Tooltip>
    </Dropdown>
  )
  /** 窄屏次级操作：收录进「更多」菜单，避免顶栏折成三行 */
  const mobileToolbarMenu: MenuProps['items'] = [
    {
      key: 'select',
      icon: <CheckSquareOutlined />,
      label: <span data-testid="doc-toolbar-select-mode">{selectMode ? '退出多选' : '多选'}</span>,
      onClick: toggleSelectMode,
    },
    {
      key: 'view',
      icon: docView === 'list' ? <AppstoreOutlined /> : <UnorderedListOutlined />,
      label: (
        <span
          data-testid="doc-view-toggle"
          aria-label={docView === 'list' ? '切换为网格视图' : '切换为列表视图'}
        >
          {docView === 'list' ? '网格视图' : '列表视图'}
        </span>
      ),
      onClick: () => setDocView(docView === 'list' ? 'grid' : 'list'),
    },
    { type: 'divider' },
    { key: 'folder', icon: <FolderAddOutlined />, label: '新建文件夹', onClick: () => openCreate('folder') },
    { key: 'import', icon: <ImportOutlined />, label: '导入', onClick: () => setFileImportOpen(true) },
    { key: 'export', icon: <ExportOutlined />, label: '导出', onClick: () => setExportOpen(true) },
    { type: 'divider' },
    { key: 'trash', icon: <DeleteOutlined />, label: '回收站', onClick: () => setTrashOpen(true) },
  ]

  /** 桌面「更多」：导入 / 导出收进下拉，给工具栏让出横向空间（需求 0162 C3） */
  const desktopMoreMenu: MenuProps['items'] = [
    {
      key: 'import',
      icon: <ImportOutlined />,
      label: <span data-testid="doc-file-import">导入</span>,
      onClick: () => setFileImportOpen(true),
    },
    {
      key: 'export',
      icon: <ExportOutlined />,
      label: <span data-testid="doc-vault-export">导出</span>,
      onClick: () => setExportOpen(true),
    },
  ]

  /** 移动端筛选按钮：标签 / 状态是低频筛选，收起后用计数徽标 + aria-label 保留「已应用」感知 */
  const activeFilterCount = (tagFilter !== undefined ? 1 : 0) + (statusFilter ? 1 : 0)
  const mobileFilterLabel = activeFilterCount > 0 ? `筛选（已应用 ${activeFilterCount} 项）` : '筛选'

  /** 行菜单项：行尾 ⋯ 与移动端长按快捷菜单共用同一份能力（需求 0167 C6） */
  const rowActionItems = (doc: DocumentItem): MenuProps['items'] => {
    // 移动端详情承载从行内移出的低频元信息（需求 0166 C3）；桌面表格不需要
    const detailItems: MenuProps['items'] = isMobile ? [
      {
        key: 'detail',
        icon: <InfoCircleOutlined />,
        label: <span data-testid={`doc-row-detail-${doc.id}`}>详情</span>,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation()
          setDetailDoc(doc)
        },
      },
      { type: 'divider' },
    ] : []
    const items: MenuProps['items'] = [
      ...detailItems,
      {
        key: 'rename',
        icon: <EditOutlined />,
        label: <span data-testid={`doc-row-rename-${doc.id}`}>重命名</span>,
        onClick: ({ domEvent }) => {
          // 菜单是 Portal：React 事件仍沿组件树冒泡到整行，不拦截会触发行跳转
          domEvent.stopPropagation()
          setRenameValue(doc.title)
          setRenameTarget({ id: doc.id, title: doc.title, isSeries: false })
        },
      },
      {
        key: 'move',
        icon: <ApartmentOutlined />,
        label: <span data-testid={`doc-row-move-${doc.id}`}>移动</span>,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation()
          setRowMove({ id: doc.id, title: doc.title, parent: doc.parent_id ?? 0 })
        },
      },
      {
        key: 'pin',
        icon: <PushpinOutlined />,
        label: <span data-testid={`doc-row-pin-${doc.id}`}>{doc.pinned ? '取消置顶' : '置顶'}</span>,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation()
          pinMut.mutate(doc)
        },
      },
      { type: 'divider' },
      {
        key: 'delete',
        danger: true,
        icon: <DeleteOutlined />,
        label: <span data-testid={`doc-row-delete-${doc.id}`}>删除</span>,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation()
          modal.confirm({
            title: doc.is_folder ? '删除文件夹将同时删除其中所有文档，确认？' : '确认删除此文档？',
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: () => deleteMut.mutate(doc.id),
          })
        },
      },
    ]
    return items
  }

  /** 行尾操作：桌面 / 移动端统一收进单枚「更多」下拉，给标题与右侧 meta 列让出横向空间 */
  const renderRowActions = (doc: DocumentItem) => (
    <div className="cn-list-item-actions">
      <Dropdown menu={{ items: rowActionItems(doc) }} trigger={['click']} placement="bottomRight">
        <Button
          type="text"
          size="small"
          icon={<MoreOutlined />}
          aria-label={`更多操作 ${doc.title}`}
          data-testid={`doc-row-more-${doc.id}`}
          onClick={e => e.stopPropagation()}
        />
      </Dropdown>
    </div>
  )

  /** 移动端搜索命中高亮（需求 0167 C8）：完整标题仍在 title，桌面表格不改动 */
  const renderDocTitle = (title: string) => {
    const kw = titleKeyword.trim()
    if (!isMobile || !kw) return title
    const idx = title.toLowerCase().indexOf(kw.toLowerCase())
    if (idx < 0) return title
    return (
      <>
        {title.slice(0, idx)}
        <mark className="cn-doc-hit">{title.slice(idx, idx + kw.length)}</mark>
        {title.slice(idx + kw.length)}
      </>
    )
  }

  /** 文档块：移动端按置顶 / 今天 / 本周 / 更早分组（0167 C7），桌面沿用列对齐表格 */
  const renderFileBlock = (items: DocumentItem[]) => {
    if (!isMobile) {
      return (
        <DocumentTable
          testId="doc-file-table"
          items={items}
          folderStatusCounts={folderStatusCounts}
          folderSummaries={folderSummaries}
          selectedIds={selectedIds}
          onToggleSelected={toggleSelected}
          onOpen={openDoc}
          renderRowActions={renderRowActions}
        />
      )
    }
    const groups = groupDocsByTime(items)
    return (
      <div className="cn-doc-time-groups">
        {DOC_TIME_GROUPS.map(g => groups[g.key].length > 0 && (
          <section key={g.key} className="cn-doc-time-group" data-testid={`doc-time-group-${g.key}`}>
            <div className="cn-doc-time-group-title">{g.label}</div>
            <Listy
              className="cn-doc-list"
              items={groups[g.key]}
              rowKey={doc => doc.id}
              itemRender={renderDocRow}
            />
          </section>
        ))}
      </div>
    )
  }

  /** 单个文档 / 文件夹行（文件夹块与文档块共用；桌面与移动端均为单行，移动端紧凑化见需求 0166） */
  const renderDocRow = (doc: DocumentItem) => {
    // 文件夹状态取子孙文档聚合（空文件夹无状态），文档保持自身状态
    const statusCounts = doc.is_folder
      ? folderStatusCounts.get(doc.id) ?? {}
      : { [doc.status]: 1 }
    const statusEntries = Object.entries(statusCounts)
    const showPrivate = doc.is_folder
      ? statusEntries.some(([st]) => st !== 'published')
      : doc.visibility === 'private'
    const visibilityTip = doc.is_folder
      ? '含未发布内容：其中草稿 / 归档仅你与工作区所有者可见'
      : '未发布：仅你与工作区所有者可见'
    // 单行只放一枚主状态图标：未发布优先提醒，其次归档，最后已发布（需求 0166 C2）
    const primaryStatus = doc.is_folder
      ? ['draft', 'archived', 'published'].find(st => statusCounts[st]) ?? null
      : doc.status
    const statusMeta = primaryStatus ? DOC_STATUS_META[primaryStatus] : undefined
    const StatusIcon = statusMeta?.Icon
    const statusTip = statusEntries
      .map(([st, n]) => `${STATUS_LABELS[st] ?? st}${doc.is_folder ? ` ${n}` : ''}`)
      .join(' · ')
    return (
              <div
                className="cn-list-item"
                style={{ cursor: 'pointer' }}
                onMouseEnter={isMobile ? undefined : () => pptxPrefetcher.schedule(doc)}
                onMouseLeave={isMobile ? undefined : pptxPrefetcher.cancel}
                onClick={() => {
                  // 长按结束后的 click 不再触发跳转（需求 0167 C6）
                  if (suppressRowClick.current) {
                    suppressRowClick.current = false
                    return
                  }
                  // 多选模式下整行点击切换选中，避免误跳转（需求 0166 C6）
                  if (isMobile && selectMode) {
                    toggleSelected(doc.id)
                    return
                  }
                  openDoc(doc)
                }}
                onTouchStart={isMobile ? () => startLongPress(doc) : undefined}
                onTouchEnd={isMobile ? cancelLongPress : undefined}
                onTouchMove={isMobile ? cancelLongPress : undefined}
              >
                <CnListMeta
                  avatar={
                    <Space size={4}>
                      {(!isMobile || selectMode) && (
                        <span onClick={e => e.stopPropagation()}>
                          <Checkbox
                            checked={selectedIds.includes(doc.id)}
                            data-testid={`doc-select-${doc.id}`}
                            aria-label={`选择 ${doc.title}`}
                            onChange={() => toggleSelected(doc.id)}
                          />
                        </span>
                      )}
                      {doc.is_folder ? (
                        <FolderOutlined style={{ fontSize: isMobile ? 18 : 22, color: '#faad14' }} />
                      ) : (
                        (() => {
                          const fmt = formatMeta(doc.content_type)
                          const FormatIcon = fmt.Icon
                          return (
                            <FormatIcon
                              aria-label={`格式：${fmt.label}`}
                              data-testid={`doc-list-format-${doc.id}`}
                              style={{ fontSize: isMobile ? 18 : 22, color: fmt.color }}
                            />
                          )
                        })()
                      )}
                    </Space>
                  }
                  title={
                  isMobile ? (
                    /* 移动端单行（需求 0166）：标题占满剩余宽度省略；状态 / 置顶 / 私有图标与相对时间收在行尾，
                       低频元信息（大小 / 版本 / 多状态分布）移入「⋯ → 详情」 */
                    <div className="cn-doc-row-title-line">
                      <Text strong className="cn-doc-title-ellipsis" title={doc.title}>{renderDocTitle(doc.title)}</Text>
                      {doc.is_folder && (
                        <Text type="secondary" className="cn-doc-row-count">
                          {Object.values(statusCounts).reduce((sum, n) => sum + n, 0)} 项
                        </Text>
                      )}
                      {StatusIcon && statusMeta && (
                        <Tooltip title={statusTip}>
                          <StatusIcon
                            aria-label={`状态：${statusMeta.label}`}
                            data-testid={`doc-list-status-${doc.id}-${primaryStatus}`}
                            style={{ color: statusMeta.color, fontSize: 'var(--cn-text-sm)', flexShrink: 0 }}
                          />
                        </Tooltip>
                      )}
                      {doc.pinned && (
                        <PushpinOutlined
                          aria-label="置顶"
                          data-testid={`doc-pinned-tag-${doc.id}`}
                          style={{ color: 'var(--cn-brand-color)', fontSize: 'var(--cn-text-sm)', flexShrink: 0 }}
                        />
                      )}
                      {showPrivate && (
                        <Tooltip title={visibilityTip}>
                          <LockOutlined
                            data-testid={`doc-list-visibility-${doc.id}`}
                            aria-label="仅自己可见"
                            style={{ color: 'var(--cn-text-muted)', fontSize: 'var(--cn-text-sm)', flexShrink: 0 }}
                          />
                        </Tooltip>
                      )}
                      <Text type="secondary" className="cn-doc-row-time" title={formatTime(doc.updated_at)}>
                        {formatRelativeTime(doc.updated_at)}
                      </Text>
                    </div>
                  ) : (
                    /* 桌面端单行：标题按内容宽度、超长才省略；置顶 / 状态 / 可见性 / 标签计数降噪为图标与计数 */
                    <div className="cn-doc-row-title-line">
                      <Text strong className="cn-doc-title-single" title={doc.title}>{doc.title}</Text>
                      {doc.pinned && (
                        <PushpinOutlined
                          aria-label="置顶"
                          data-testid={`doc-pinned-tag-${doc.id}`}
                          style={{ color: 'var(--cn-brand-color)', fontSize: 'var(--cn-text-sm)' }}
                        />
                      )}
                      {statusEntries.map(([st, n]) => (
                        <Badge
                          key={st}
                          data-testid={`doc-list-status-${doc.id}-${st}`}
                          status={STATUS_BADGE[st] ?? 'default'}
                          text={doc.is_folder ? `${STATUS_LABELS[st] ?? st} ${n}` : STATUS_LABELS[st]}
                        />
                      ))}
                      {/* 可见性提示：未发布的文档同事看不到，明确告知以免误以为文档丢失 */}
                      {showPrivate && (
                        <Tooltip title={visibilityTip}>
                          <LockOutlined
                            data-testid={`doc-list-visibility-${doc.id}`}
                            aria-label="仅自己可见"
                            style={{ color: 'var(--cn-text-muted)', fontSize: 'var(--cn-text-xs)' }}
                          />
                        </Tooltip>
                      )}
                      {doc.tag_ids.length > 0 && (
                        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                          {doc.tag_ids.length} 个标签
                        </Text>
                      )}
                    </div>
                  )
                }
                />

                {!isMobile && (
                  /* 桌面端右侧 meta 列：大小 / 更新时间右对齐，文件夹大小留空占位保证跨行对齐 */
                  <div className="cn-doc-row-meta" data-testid={`doc-row-meta-${doc.id}`}>
                    <span className="cn-doc-meta-size">
                      {doc.is_folder ? '' : formatSize(doc.content_size)}
                    </span>
                    <span className="cn-doc-meta-date" title={formatTime(doc.updated_at)}>
                      {formatDate(doc.updated_at)}
                    </span>
                  </div>
                )}
                {renderRowActions(doc)}
              </div>
            )
  }

  // 行详情弹窗的派生展示（需求 0166 C3）；文件夹沿用子孙聚合状态口径
  const detailCounts = detailDoc
    ? (detailDoc.is_folder ? folderStatusCounts.get(detailDoc.id) ?? {} : { [detailDoc.status]: 1 })
    : {}
  const detailStatusText = Object.entries(detailCounts)
    .map(([st, n]) => `${STATUS_LABELS[st] ?? st} ${n}`)
    .join(' · ') || '—'
  const detailPrivate = detailDoc
    ? (detailDoc.is_folder
      ? Object.keys(detailCounts).some(st => st !== 'published')
      : detailDoc.visibility === 'private')
    : false

  return (
    <div style={{ padding: isMobile ? 10 : 16 }}>
      {/* 工具栏 */}
      {isMobile ? (
        /* 移动端工具栏（需求 0167 C1）：只保留一行；搜索按需展开，筛选进底部 Drawer */
        <div
          data-testid="doc-toolbar-mobile"
          className="cn-doc-toolbar-mobile"
          style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, minWidth: 0 }}
        >
          {mobileUpButton}
          {mobileSearchOpen ? (
            <div style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, gap: 2 }}>
              {renderSearchInput({ flex: 1, minWidth: 0 })}
              <Button
                type="text"
                icon={<CloseOutlined />}
                aria-label="关闭搜索"
                data-testid="doc-toolbar-search-close"
                onClick={() => {
                  setMobileSearchOpen(false)
                  setDocTitleFilter('')
                }}
              />
            </div>
          ) : (
            <>
              <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>{mobileBreadcrumbNode}</div>
              <Button
                icon={<SearchOutlined />}
                aria-label="搜索文档"
                data-testid="doc-toolbar-search"
                onClick={() => setMobileSearchOpen(true)}
              />
            </>
          )}
          {renderSortButton('doc-content-sort')}
          <Badge count={activeFilterCount} size="small">
            <Button
              icon={<FilterOutlined />}
              aria-label={mobileFilterLabel}
              aria-expanded={filterOpen}
              data-testid="doc-toolbar-filter"
              onClick={() => setFilterOpen(true)}
            />
          </Badge>
          <Button
            type="primary"
            icon={<FileAddOutlined />}
            aria-label="新建文档"
            data-testid="doc-toolbar-create"
            onClick={() => openCreate('doc')}
          />
          <Dropdown menu={{ items: mobileToolbarMenu }} trigger={['click']} placement="bottomRight">
            <Button icon={<MoreOutlined />} aria-label="更多文档操作" data-testid="doc-toolbar-more" />
          </Dropdown>
        </div>
      ) : (
        <div className="cn-doc-head" data-testid="doc-toolbar-desktop">
          <div className="cn-doc-head-left">
            {upButton}
            {breadcrumbNode}
          </div>
          <div className="cn-doc-head-actions">
            {renderSortButton('doc-content-sort')}
            {renderSearchInput({ width: isNarrowDesktop ? 132 : 160 })}
            {isNarrowDesktop ? (
              <Popover
                trigger="click"
                placement="bottomRight"
                title="筛选"
                content={
                  <div className="cn-doc-filter-panel">
                    {renderTagSelect({ width: '100%' })}
                    {renderStatusSelect({ width: '100%' })}
                  </div>
                }
              >
                <Button
                  icon={<FilterOutlined />}
                  data-testid="doc-filter-menu"
                  aria-label="筛选标签或状态"
                >
                  {tagFilter !== undefined || statusFilter ? '筛选 ·' : '筛选'}
                </Button>
              </Popover>
            ) : (
              <>
                {renderTagSelect({ width: 110 })}
                {renderStatusSelect({ width: 96 })}
              </>
            )}
            <Tooltip title="回收站">
              <Button
                icon={<DeleteOutlined />}
                aria-label="回收站"
                data-testid="doc-trash-open"
                onClick={() => setTrashOpen(true)}
              />
            </Tooltip>
            {parentId === null && (
              <Segmented
                size="small"
                value={docView}
                onChange={value => setDocView(value as 'list' | 'grid')}
                data-testid="doc-view-toggle"
                options={[
                  { value: 'list', label: <Tooltip title="列表视图"><UnorderedListOutlined /></Tooltip> },
                  { value: 'grid', label: <Tooltip title="网格视图"><AppstoreOutlined /></Tooltip> },
                ]}
              />
            )}
            <Dropdown
              menu={{
                items: [
                  { key: 'doc', icon: <FileAddOutlined />, label: '新建文档', onClick: () => openCreate('doc') },
                  { key: 'folder', icon: <FolderAddOutlined />, label: '新建文件夹', onClick: () => openCreate('folder') },
                ],
              }}
              trigger={['click']}
              placement="bottomRight"
            >
              <Button type="primary" icon={<FileAddOutlined />} data-testid="doc-create-menu">新建</Button>
            </Dropdown>
            <Dropdown menu={{ items: desktopMoreMenu }} trigger={['click']} placement="bottomRight">
              <Button icon={<MoreOutlined />} aria-label="更多文档操作" data-testid="doc-toolbar-more-desktop" />
            </Dropdown>
          </div>
        </div>
      )}

      {/* 最近打开：本地历史，仅在根层展示；点标题直接进编辑器 */}
      {parentId === null && recentDocs.length > 0 && (
        <div className="cn-doc-recent" data-testid="doc-recent">
          <Space size={4} wrap>
            <ClockCircleOutlined style={{ color: 'var(--cn-text-muted)' }} />
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>最近打开</Text>
            {recentDocs.map(it => (
              <Button
                key={it.id}
                type="text"
                size="small"
                data-testid={`doc-recent-${it.id}`}
                onClick={() => navigate(`/w/${workspaceId}/documents/${it.id}`)}
              >
                {it.title}
              </Button>
            ))}
            <Button
              type="text"
              size="small"
              data-testid="doc-recent-clear"
              onClick={() => {
                clearRecentDocs(workspaceId)
                setRecentVersion(v => v + 1)
              }}
            >
              清除
            </Button>
          </Space>
        </div>
      )}

      {/* 批量操作栏：选中任意项后出现 */}
      {selectedIds.length > 0 && (
        <div className="cn-doc-batch-bar" data-testid="doc-batch-bar">
          <Space size={isMobile ? 6 : 12} wrap>
            <Checkbox
              checked={allSelected}
              indeterminate={selectedIds.length > 0 && !allSelected}
              data-testid="doc-batch-select-all"
              onChange={e => setSelectedIds(e.target.checked ? selectableIds : [])}
            >
              全选
            </Checkbox>
            <Text type="secondary">已选 {selectedIds.length} 项</Text>
            {/* 窄屏只留图标：批量栏是一行，文字按钮会把操作挤到第二行 */}
            <Tooltip title="移动到…">
              <Button
                icon={<ApartmentOutlined />}
                aria-label="移动到…"
                data-testid="doc-batch-move"
                onClick={() => {
                  setBatchMoveTarget(parentId ?? 0)
                  setBatchMoveOpen(true)
                }}
              >
                {!isMobile && '移动到…'}
              </Button>
            </Tooltip>
            <Tooltip title="移动到其它工作区">
              <Button
                icon={<ExportOutlined />}
                aria-label="移动到工作区"
                data-testid="doc-batch-move-workspace"
                onClick={() => setMoveWorkspaceOpen(true)}
              >
                {!isMobile && '移动到工作区'}
              </Button>
            </Tooltip>
            <Popconfirm
              title={`删除选中的 ${selectedIds.length} 项？`}
              description="文件夹将连同其中所有文档一起移入回收站。"
              okText="删除"
              okType="danger"
              cancelText="取消"
              onConfirm={() => batchMut.mutate({ action: 'delete', ids: selectedIds })}
            >
              <Button
                danger
                icon={<DeleteOutlined />}
                aria-label="批量删除"
                data-testid="doc-batch-delete"
                loading={batchMut.isPending}
              >
                {!isMobile && '批量删除'}
              </Button>
            </Popconfirm>
            <Button type="text" data-testid="doc-batch-clear" onClick={() => setSelectedIds([])}>
              取消选择
            </Button>
          </Space>
        </div>
      )}

      {/* 顶层网格视图：桌面仅在切到网格时渲染；移动端沿用卡片（需求 0162 C1/C6） */}
      {parentId === null && docView === 'grid' && tagFilter === undefined && seriesList.length > 0 && (
        <section data-testid="doc-folder-block" style={{ marginBottom: isMobile ? 10 : 16 }}>
        <SectionTitle label="文件夹" count={seriesList.length} compact={isMobile} />
        <div
          data-testid="doc-series-grid"
          style={{
            display: 'grid',
            // 手机端收窄卡片最小宽度：390px 宽屏可排两列，平板自动增列；桌面维持 240px 大卡
            gridTemplateColumns: isMobile ? 'repeat(auto-fill, minmax(150px, 1fr))' : 'repeat(auto-fill, minmax(240px, 1fr))',
            gap: isMobile ? 8 : 16,
            marginBottom: 8,
          }}
        >
          {seriesList.map(s => (
            <Card
              key={s.folder.id}
              hoverable
              size="small"
              data-testid={`doc-series-card-${s.folder.id}`}
              className="cn-folder-card"
              styles={{ body: { padding: isMobile ? 10 : 12 } }}
              onClick={() => {
                if (isMobile && selectMode) toggleSelected(s.folder.id)
                else setParentId(s.folder.id)
              }}
            >
              {/* 文件夹卡片压成两行：标题行（勾选 / 图标 / 名称 / 置顶）+ 元信息行（计数 / 状态 / 更新日期） */}
              <div className="cn-doc-row-title-line" style={{ marginBottom: 'var(--cn-space-xs)' }}>
                {/* 移动端默认不渲染勾选框（需求 0166 C6）；外层 span 阻止冒泡，点勾选不触发卡片跳转 */}
                {(!isMobile || selectMode) && (
                  <span onClick={e => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedIds.includes(s.folder.id)}
                      data-testid={`doc-select-${s.folder.id}`}
                      aria-label={`选择 ${s.folder.title}`}
                      onChange={() => toggleSelected(s.folder.id)}
                    />
                  </span>
                )}
                <FolderOutlined style={{ fontSize: 'var(--cn-text-lg)', color: 'var(--cn-warning, #faad14)', flexShrink: 0 }} />
                <Text strong className="cn-doc-title-single" title={s.folder.title} style={{ fontSize: 'var(--cn-text-md)' }}>
                  {s.folder.title}
                </Text>
                {s.folder.pinned && (
                  <PushpinOutlined
                    aria-label="置顶"
                    data-testid={`doc-pinned-tag-${s.folder.id}`}
                    style={{ color: 'var(--cn-brand-color)', fontSize: 'var(--cn-text-sm)' }}
                  />
                )}
              </div>
              <div className="cn-folder-card-meta">
                <span>{s.docCount} 篇文档</span>
                {s.subFolderCount > 0 && <span>{s.subFolderCount} 个子文件夹</span>}
                {s.tagCount > 0 && <span>{s.tagCount} 个标签</span>}
                {Object.entries(s.statusCounts).map(([st, n]) => (
                  <Badge key={st} status={STATUS_BADGE[st] ?? 'default'} text={`${STATUS_LABELS[st] ?? st} ${n}`} />
                ))}
                <span className="cn-folder-card-date" title={formatTime(s.latestUpdate)}>
                  更新 {formatDate(s.latestUpdate)}
                </span>
              </div>
            </Card>
          ))}
        </div>
        </section>
      )}

      {/* 系列详情头部（需求 0162 C4）：压缩为单行工具条，名称 / 统计 / 操作保持原能力 */}
      {parentId !== null && currentSeries && (
        <div className="cn-doc-series-bar" data-testid="doc-series-detail">
          <FolderOutlined className="cn-doc-series-icon" />
          <Text strong className="cn-doc-series-name" title={currentSeries.folder.title}>
            {currentSeries.folder.title}
          </Text>
          {Object.entries(currentSeries.statusCounts).map(([st, n]) => (
            <Tag key={st} color={STATUS_COLORS[st] ?? 'default'} className="cn-doc-series-tag">
              {STATUS_LABELS[st] ?? st} {n}
            </Tag>
          ))}
          <span className="cn-doc-series-meta">
            <span>{currentSeries.docCount} 篇文档</span>
            <span>{currentSeries.subFolderCount} 个子文件夹</span>
            {currentSeries.tagCount > 0 && <span>{currentSeries.tagCount} 个标签</span>}
            <span title={formatTime(currentSeries.latestUpdate)}>更新 {formatDate(currentSeries.latestUpdate)}</span>
          </span>
          <Space size={4} className="cn-doc-series-actions">
            <Tooltip title="重命名系列">
              <Button
                size="small"
                icon={<EditOutlined />}
                aria-label="重命名系列"
                data-testid="doc-series-rename"
                onClick={() => {
                  setRenameValue(currentSeries.folder.title)
                  setRenameTarget({ id: currentSeries.folder.id, title: currentSeries.folder.title, isSeries: true })
                }}
              />
            </Tooltip>
            <Tooltip title="移动系列">
              <Button
                size="small"
                icon={<ApartmentOutlined />}
                aria-label="移动系列"
                data-testid="doc-series-move"
                onClick={() => {
                  setMoveTarget(currentSeries.folder.parent_id ?? 0)
                  setMoveOpen(true)
                }}
              />
            </Tooltip>
            <Popconfirm
              title="删除系列将同时删除其中全部文档与子文件夹，确认？"
              okType="danger"
              okText="删除"
              cancelText="取消"
              onConfirm={() => deleteMut.mutate(currentSeries.folder.id)}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label="删除系列"
                data-testid="doc-series-delete"
              />
            </Popconfirm>
          </Space>
        </div>
      )}

      {/* 列表：桌面默认列对齐表格（需求 0162）；移动端沿用原两行列表，信息架构不变 */}
      {docsQuery.isLoading ? (
        // antd List 弃用（ADR 0074）：加载态用 Skeleton 占位（v5 List loading 同为骨架行）
        <div className="cn-doc-list" aria-busy="true">
          <Skeleton active title={false} paragraph={{ rows: 1 }} style={{ padding: isMobile ? '10px 12px' : '16px 24px' }} />
          <Skeleton active title={false} paragraph={{ rows: 1 }} style={{ padding: isMobile ? '10px 12px' : '16px 24px' }} />
          <Skeleton active title={false} paragraph={{ rows: 1 }} style={{ padding: isMobile ? '10px 12px' : '16px 24px' }} />
        </div>
      ) : listItems.length === 0 && (parentId !== null || seriesList.length === 0) ? (
        <Empty description="暂无文档" style={{ marginTop: isMobile ? 32 : 80 }}>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>
            创建第一篇文档
          </Button>
        </Empty>
      ) : (
        <div data-testid="doc-list">
          {parentId === null ? (
            <>
              {/* 根层：文件夹行在前（列表视图；网格视图由上方卡片承载） */}
              {docView === 'list' && tagFilter === undefined && seriesList.length > 0 && (
                <section data-testid="doc-folder-block" className="cn-doc-section">
                  <SectionTitle label="文件夹" count={seriesList.length} compact={isMobile} />
                  {isMobile ? (
                    <Listy
                      className="cn-doc-list"
                      items={seriesList.map(series => series.folder)}
                      rowKey={doc => doc.id}
                      itemRender={renderDocRow}
                    />
                  ) : (
                    <DocumentTable
                      testId="doc-folder-table"
                      items={seriesList.map(series => series.folder)}
                      folderStatusCounts={folderStatusCounts}
                      folderSummaries={folderSummaries}
                      selectedIds={selectedIds}
                      onToggleSelected={toggleSelected}
                      onOpen={openDoc}
                      renderRowActions={renderRowActions}
                    />
                  )}
                </section>
              )}
              {fileItems.length > 0 && (
                <section data-testid="doc-file-block">
                  <SectionTitle label="文档" count={fileItems.length} compact={isMobile} />
                  {renderFileBlock(fileItems)}
                </section>
              )}
            </>
          ) : (
            <>
              {/* 子级：文件夹块在前、文档块在后 */}
              {subFolders.length > 0 && (
                <section data-testid="doc-subfolder-block" className="cn-doc-section">
                  <SectionTitle label="文件夹" count={subFolders.length} compact={isMobile} />
                  {isMobile ? (
                    <Listy
                      className="cn-doc-list"
                      items={subFolders}
                      rowKey={doc => doc.id}
                      itemRender={renderDocRow}
                    />
                  ) : (
                    <DocumentTable
                      testId="doc-subfolder-table"
                      items={subFolders}
                      folderStatusCounts={folderStatusCounts}
                      folderSummaries={folderSummaries}
                      selectedIds={selectedIds}
                      onToggleSelected={toggleSelected}
                      onOpen={openDoc}
                      renderRowActions={renderRowActions}
                    />
                  )}
                </section>
              )}
              {fileItems.length > 0 && (
                <section data-testid="doc-file-block">
                  <SectionTitle label="文档" count={fileItems.length} compact={isMobile} />
                  {renderFileBlock(fileItems)}
                </section>
              )}
            </>
          )}
        </div>
      )}

      {/* 移动端行详情（需求 0166 C3）：低频元信息不占列表行，完整时间在这里保留 */}
      <Modal
        title={detailDoc?.title}
        open={detailDoc !== null}
        onCancel={() => setDetailDoc(null)}
        footer={null}
        destroyOnHidden
      >
        <Space orientation="vertical" size={4} style={{ width: '100%' }} data-testid="doc-row-detail-modal">
          <div>状态：{detailStatusText}</div>
          <div>可见性：{detailPrivate ? '私有（仅创建者与工作区所有者可见）' : '工作区可见'}</div>
          <div>更新时间：{detailDoc ? formatTime(detailDoc.updated_at) : ''}</div>
          {detailDoc && !detailDoc.is_folder && (
            <>
              <div>大小：{formatSize(detailDoc.content_size)}</div>
              <div>版本：v{detailDoc.version_count}</div>
              <div>标签：{detailDoc.tag_ids.length} 个</div>
            </>
          )}
          {detailDoc?.is_folder && (
            <div>
              内容：{folderSummaries.get(detailDoc.id)?.docCount ?? 0} 篇文档 ·{' '}
              {folderSummaries.get(detailDoc.id)?.subFolderCount ?? 0} 个子文件夹
            </div>
          )}
        </Space>
      </Modal>

      {/* 移动端筛选抽屉（需求 0167 C4）：标签 / 状态低频筛选不占顶栏高度 */}
      {isMobile && (
        <Drawer
          title="筛选"
          placement="bottom"
          size="auto"
          open={filterOpen}
          onClose={() => setFilterOpen(false)}
          data-testid="doc-toolbar-filters"
          destroyOnHidden
        >
          <div className="cn-doc-filter-sheet">
            {renderTagSelect({ width: '100%' })}
            {renderStatusSelect({ width: '100%' })}
            <div className="cn-doc-filter-sheet-actions">
              <Button onClick={() => updateParams({ tag: null, status: null })}>重置</Button>
              <Button type="primary" onClick={() => setFilterOpen(false)}>完成</Button>
            </div>
          </div>
        </Drawer>
      )}

      {/* 移动端长按快捷菜单（需求 0167 C6）：与行尾 ⋯ 共用菜单项，不替换常规路径 */}
      {isMobile && (
        <Drawer
          title={quickDoc?.title}
          placement="bottom"
          size="auto"
          open={quickDoc !== null}
          onClose={() => setQuickDoc(null)}
          data-testid="doc-quick-actions"
          destroyOnHidden
        >
          {quickDoc && <Menu mode="inline" items={rowActionItems(quickDoc)} onClick={() => setQuickDoc(null)} />}
        </Drawer>
      )}

      {/* 新建弹窗 */}
      <Modal
        title={createType === 'folder' ? '新建文件夹' : '新建文档'}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMut.mutate()}
        okButtonProps={{ disabled: !newTitle.trim(), loading: createMut.isPending }}
      >
        <Space orientation="vertical" style={{ width: '100%' }} size={12}>
          <Input
            placeholder={createType === 'folder' ? '文件夹名称' : '文档标题'}
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            autoFocus
          />
          {createType === 'doc' && (
            <Input.TextArea
              placeholder="初始 Markdown 内容（可选）"
              rows={6}
              value={newContent}
              onChange={e => setNewContent(e.target.value)}
            />
          )}
        </Space>
      </Modal>

      {/* 导出方式选择弹窗（需求 0088）：两种方式均为 .zip，原件族按原文件导出 */}
      <Modal
        title="导出文档"
        open={exportOpen}
        onCancel={() => setExportOpen(false)}
        onOk={() => vaultExportMut.mutate(exportStyle)}
        okText="导出"
        cancelText="取消"
        okButtonProps={{ loading: vaultExportMut.isPending, 'data-testid': 'doc-export-confirm' }}
        destroyOnHidden
      >
        <Radio.Group
          value={exportStyle}
          onChange={e => setExportStyle(e.target.value as VaultExportStyle)}
          data-testid="doc-export-style"
          style={{ width: '100%' }}
        >
          <Space orientation="vertical" style={{ width: '100%' }} size={12}>
            <Radio value="archive">
              <Space orientation="vertical" size={0}>
                <Text>压缩文档（.zip）</Text>
                <Text type="secondary">
                  按文档树打包：Markdown 导出正文，PDF / Word / Excel / PPT / 图片等按原件导出
                </Text>
              </Space>
            </Radio>
            <Radio value="obsidian">
              <Space orientation="vertical" size={0}>
                <Text>Obsidian 库（.zip）</Text>
                <Text type="secondary">
                  在压缩文档基础上追加 front-matter 与最小 .obsidian 配置，解压后可直接作为库打开
                </Text>
              </Space>
            </Radio>
          </Space>
        </Radio.Group>
      </Modal>

      {/* 重命名弹窗（系列 / 列表行共用：文案与 testid 按来源区分） */}
      <Modal
        title={renameTarget?.isSeries ? `重命名系列「${renameTarget.title}」` : `重命名「${renameTarget?.title ?? ''}」`}
        open={renameTarget !== null}
        onCancel={() => setRenameTarget(null)}
        onOk={() => renameMut.mutate()}
        okButtonProps={{ disabled: !renameValue.trim(), loading: renameMut.isPending }}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Input
          placeholder={renameTarget?.isSeries ? '系列名称' : '文档标题'}
          value={renameValue}
          onChange={e => setRenameValue(e.target.value)}
          onPressEnter={() => renameValue.trim() && renameMut.mutate()}
          autoFocus
          data-testid={renameTarget?.isSeries ? 'doc-series-rename-input' : 'doc-rename-input'}
        />
      </Modal>

      {/* 列表行移动弹窗：TreeSelect 选目标文件夹（排除自身及子孙，防环由后端二次校验） */}
      <Modal
        title={`移动「${rowMove?.title ?? ''}」到…`}
        open={rowMove !== null}
        onCancel={() => setRowMove(null)}
        onOk={() => rowMoveMut.mutate()}
        confirmLoading={rowMoveMut.isPending}
        okText="移动"
        cancelText="取消"
        destroyOnHidden
      >
        <TreeSelect
          style={{ width: '100%' }}
          treeDefaultExpandAll
          value={rowMove?.parent}
          onChange={(v: number) => setRowMove(prev => (prev ? { ...prev, parent: v } : prev))}
          treeData={rowMoveTreeData}
          data-testid="doc-row-move-target"
        />
      </Modal>

      {/* 批量移动弹窗：目标文件夹排除所选节点及其子孙（防环由后端二次校验） */}
      <Modal
        title={`移动选中的 ${selectedIds.length} 项到…`}
        open={batchMoveOpen}
        onCancel={() => setBatchMoveOpen(false)}
        onOk={() => batchMut.mutate({ action: 'move', ids: selectedIds, parent_id: batchMoveTarget })}
        confirmLoading={batchMut.isPending}
        okText="移动"
        cancelText="取消"
        destroyOnHidden
      >
        <TreeSelect
          style={{ width: '100%' }}
          value={batchMoveTarget}
          onChange={(v: number) => setBatchMoveTarget(v)}
          treeData={batchMoveTreeData}
          treeDefaultExpandAll
          data-testid="doc-batch-move-target"
        />
      </Modal>

      {/* 跨工作区移动（ADR 0155）：选中项（含文件夹子树）整体迁到目标工作区 */}
      <MoveDocumentModal
        open={moveWorkspaceOpen}
        workspaceId={Number(workspaceId)}
        documentIds={selectedIds}
        summary={moveSummary(selectedIds.length, selectedFolderCount)}
        onClose={() => setMoveWorkspaceOpen(false)}
        onMoved={() => {
          setSelectedIds([])
          qc.invalidateQueries({ queryKey: ['documents'] })
        }}
      />

      {/* 系列移动弹窗：TreeSelect 选目标文件夹（排除自身及子孙） */}
      <Modal
        title={`移动系列「${currentSeries?.folder.title ?? ''}」到…`}
        open={moveOpen}
        onCancel={() => setMoveOpen(false)}
        onOk={() => seriesMoveMut.mutate()}
        confirmLoading={seriesMoveMut.isPending}
        okText="移动"
        cancelText="取消"
        destroyOnHidden
      >
        <TreeSelect
          style={{ width: '100%' }}
          treeDefaultExpandAll
          value={moveTarget}
          onChange={(v: number) => setMoveTarget(v)}
          treeData={seriesMoveTreeData}
          data-testid="doc-series-move-target"
        />
      </Modal>

      <TrashDrawer open={trashOpen} onClose={() => setTrashOpen(false)} wid={workspaceId} />

      {/* 通用导入：多文件 / 压缩包 / Obsidian 库 zip，默认落在当前文件夹 */}
      <DocumentImportModal
        open={fileImportOpen}
        onClose={() => setFileImportOpen(false)}
        workspaceId={workspaceId}
        parentId={parentId}
        parentLabel={currentFolderNode?.title}
      />

      {/* hook 版 Modal 的上下文占位（移动端「更多 → 删除」确认框） */}
      {modalContextHolder}
    </div>
  )
}
