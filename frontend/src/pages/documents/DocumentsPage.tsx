/** 文档管理页 — 顶层系列卡片总览 + 文件夹列表 / 树 / 搜索入口. */

import { useCallback, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Checkbox,
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Tooltip,
  TreeSelect,
  Typography,
  message,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { MenuProps } from 'antd'
import {
  LockOutlined,
  ClockCircleOutlined,
  ApartmentOutlined,
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  FileAddOutlined,
  FolderAddOutlined,
  FolderOutlined,
  ImportOutlined,
  MoreOutlined,
  PushpinOutlined,
  SearchOutlined,
  SortAscendingOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  describeSort, DOC_SORT_OPTIONS, setDocTitleFilter, sortFlatByDocSort, sortToValue,
  useDocSortPref, useDocTitleFilter, valueToSort,
} from './docTreeSort'
import { clearRecentDocs, loadRecentDocs } from './recentDocs'
import { documentsApi } from '@/api/documents'
import type { DocumentItem } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { buildDocTree, descendantIds, findNodeById } from './DocumentTree'
import { buildSeriesStats, seriesStatsOf } from './seriesStats'
import { formatTime, STATUS_COLORS, STATUS_LABELS } from './documentDisplay'
import { formatMeta } from '@/components/Document/docFormat'
import TrashDrawer from './TrashDrawer'
import DocumentImportModal from './DocumentImportModal'
import type { DocTreeNode } from './DocumentTree'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography


// 测试与内部复用：系列统计的具名导出保留在本模块（实现见 ./seriesStats）
export { buildSeriesStats, seriesStatsOf } from './seriesStats'
export type { SeriesSummary } from './seriesStats'

export default function DocumentsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const { isMobile } = useResponsive()

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
  // 通用导入弹窗（单文件 / 文件夹 / Obsidian 库 zip）
  const [fileImportOpen, setFileImportOpen] = useState(false)
  // 最近打开：读取本地历史（清空后用 version 触发重渲染）
  const [recentVersion, setRecentVersion] = useState(0)
  // 批量操作：当前层级多选 + 批量移动弹窗
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchMoveOpen, setBatchMoveOpen] = useState(false)
  const [batchMoveTarget, setBatchMoveTarget] = useState<number>(0)

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

  // Obsidian 库导出（整库 zip：目录结构 + front-matter + 附件）
  const vaultExportMut = useMutation({
    mutationFn: () => documentsApi.vaultExport(workspaceId),
    onSuccess: (blob: Blob) => {
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `obsidian-vault-${ts}.zip`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      message.success('已导出 Obsidian 库')
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

  /** 最近打开（过滤掉已删除/不可见的文档，避免死链） */
  const recentDocs = useMemo(() => {
    const visible = new Set((treeQuery.data ?? []).map(d => d.id))
    return loadRecentDocs(workspaceId).filter(it => visible.has(it.id))
    // recentVersion：清空历史后强制重算（localStorage 不是响应式数据源）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeQuery.data, workspaceId, recentVersion])

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
    return <Alert type="error" message="无效的工作区" />
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
    { key: 'folder', icon: <FolderAddOutlined />, label: '新建文件夹', onClick: () => openCreate('folder') },
    { key: 'import', icon: <ImportOutlined />, label: '导入', onClick: () => setFileImportOpen(true) },
    { key: 'export', icon: <ExportOutlined />, label: '导出 Obsidian 库', onClick: () => vaultExportMut.mutate() },
    { type: 'divider' },
    { key: 'trash', icon: <DeleteOutlined />, label: '回收站', onClick: () => setTrashOpen(true) },
  ]

  return (
    <div style={{ padding: isMobile ? 12 : 16 }}>
      {/* 工具栏 */}
      {isMobile ? (
        <div data-testid="doc-toolbar-mobile" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
          {/* 第一行：返回 + 面包屑 + 更多（导航行常驻） */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            {mobileUpButton}
            <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>{breadcrumbNode}</div>
            <Dropdown menu={{ items: mobileToolbarMenu }} trigger={['click']} placement="bottomRight">
              <Button icon={<MoreOutlined />} aria-label="更多文档操作" data-testid="doc-toolbar-more" />
            </Dropdown>
          </div>
          {/* 第二行：排序 + 搜索 + 标签/状态筛选 + 新建（排序与侧栏共享偏好，需求 0065） */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {renderSortButton('doc-content-sort')}
            {renderSearchInput({ flex: 1, minWidth: 120 })}
            {renderTagSelect({ width: 110 })}
            {renderStatusSelect({ width: 100 })}
            <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>新建</Button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <Space wrap>
            {upButton}
            {breadcrumbNode}
          </Space>
          <Space wrap>
            {renderSortButton('doc-content-sort')}
            {renderSearchInput({ width: 180 })}
            {renderTagSelect({ width: 130 })}
            {renderStatusSelect({ width: 110 })}
            <Button icon={<DeleteOutlined />} data-testid="doc-trash-open" onClick={() => setTrashOpen(true)}>
              回收站
            </Button>
            <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>新建文档</Button>
            <Button icon={<FolderAddOutlined />} onClick={() => openCreate('folder')}>新建文件夹</Button>
            {/* 导入导出按钮组：紧凑并排，避免两个独立按钮占用过多横向空间 */}
            <Space.Compact>
              <Tooltip title="导入：本地文件（Markdown / Word / HTML）单文件或整个文件夹，或整个 Obsidian 库（.zip），自动转 Markdown 并清理排版">
                <Button
                  icon={<ImportOutlined />}
                  data-testid="doc-file-import"
                  onClick={() => setFileImportOpen(true)}
                >
                  导入
                </Button>
              </Tooltip>
              <Tooltip title="把当前工作区文档树导出为 Obsidian 库（.zip）">
                <Button
                  icon={<ExportOutlined />}
                  data-testid="doc-vault-export"
                  loading={vaultExportMut.isPending}
                  onClick={() => vaultExportMut.mutate()}
                >
                  导出
                </Button>
              </Tooltip>
            </Space.Compact>
          </Space>
        </div>
      )}

      {/* 最近打开：本地历史，仅在根层展示；点标题直接进编辑器 */}
      {parentId === null && recentDocs.length > 0 && (
        <div className="cn-doc-recent" data-testid="doc-recent">
          <Space size={4} wrap>
            <ClockCircleOutlined style={{ color: 'var(--cn-text-muted)' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>最近打开</Text>
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
          <Space size={12} wrap>
            <Checkbox
              checked={allSelected}
              indeterminate={selectedIds.length > 0 && !allSelected}
              data-testid="doc-batch-select-all"
              onChange={e => setSelectedIds(e.target.checked ? selectableIds : [])}
            >
              全选
            </Checkbox>
            <Text type="secondary">已选 {selectedIds.length} 项</Text>
            <Button
              icon={<ApartmentOutlined />}
              data-testid="doc-batch-move"
              onClick={() => {
                setBatchMoveTarget(parentId ?? 0)
                setBatchMoveOpen(true)
              }}
            >
              移动到…
            </Button>
            <Popconfirm
              title={`删除选中的 ${selectedIds.length} 项？`}
              description="文件夹将连同其中所有文档一起移入回收站。"
              okText="删除"
              okType="danger"
              cancelText="取消"
              onConfirm={() => batchMut.mutate({ action: 'delete', ids: selectedIds })}
            >
              <Button danger icon={<DeleteOutlined />} data-testid="doc-batch-delete" loading={batchMut.isPending}>
                批量删除
              </Button>
            </Popconfirm>
            <Button type="text" data-testid="doc-batch-clear" onClick={() => setSelectedIds([])}>
              取消选择
            </Button>
          </Space>
        </div>
      )}

      {/* 顶层：系列卡片网格（顶层文件夹即系列）；按标签筛选时隐藏——文件夹本身没有标签，
          与后端 list 端点按 tag_id 过滤后不含文件夹的口径保持一致 */}
      {parentId === null && tagFilter === undefined && seriesList.length > 0 && (
        <Row gutter={isMobile ? [12, 12] : [16, 16]} data-testid="doc-series-grid" style={{ marginBottom: 8 }}>
          {seriesList.map(s => (
            <Col xs={24} sm={12} md={8} key={s.folder.id}>
              <Card
                hoverable
                size="small"
                data-testid={`doc-series-card-${s.folder.id}`}
                styles={{ body: { padding: isMobile ? 12 : 16 } }}
                onClick={() => setParentId(s.folder.id)}
              >
                <Space size={8} style={{ marginBottom: 8 }}>
                  {/* 外层 span 阻止冒泡：点击勾选框不会触发卡片跳转，同时保留 Checkbox 自身交互 */}
                  <span onClick={e => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedIds.includes(s.folder.id)}
                      data-testid={`doc-select-${s.folder.id}`}
                      aria-label={`选择 ${s.folder.title}`}
                      onChange={() => toggleSelected(s.folder.id)}
                    />
                  </span>
                  <FolderOutlined style={{ fontSize: 20, color: 'var(--cn-warning, #faad14)' }} />
                  <Text strong style={{ fontSize: 15 }}>{s.folder.title}</Text>
                  {s.folder.pinned && <Tag color="blue" data-testid={`doc-pinned-tag-${s.folder.id}`}>置顶</Tag>}
                </Space>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, color: 'var(--cn-text-secondary, #666)' }}>
                  <span>{s.docCount} 篇文档</span>
                  {s.subFolderCount > 0 && <span>{s.subFolderCount} 个子文件夹</span>}
                  {s.tagCount > 0 && <span>{s.tagCount} 个标签</span>}
                </div>
                <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                  {Object.entries(s.statusCounts).map(([st, n]) => (
                    <Tag key={st} color={STATUS_COLORS[st] ?? 'default'} style={{ marginRight: 0 }}>
                      {STATUS_LABELS[st] ?? st} {n}
                    </Tag>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                    更新 {formatTime(s.latestUpdate)}
                  </Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 系列详情头部：图标 + 名称 + 递归统计 + 系列级操作（重命名/移动/删除） */}
      {parentId !== null && currentSeries && (
        <Card size="small" data-testid="doc-series-detail" styles={{ body: { padding: isMobile ? 12 : 16 } }} style={{ marginBottom: isMobile ? 12 : 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <FolderOutlined style={{ fontSize: 24, color: 'var(--cn-warning, #faad14)' }} />
            <div style={{ flex: 1, minWidth: 180 }}>
              <Space size={8} wrap>
                <Text strong style={{ fontSize: 16 }}>{currentSeries.folder.title}</Text>
                {Object.entries(currentSeries.statusCounts).map(([st, n]) => (
                  <Tag key={st} color={STATUS_COLORS[st] ?? 'default'} style={{ marginRight: 0 }}>
                    {STATUS_LABELS[st] ?? st} {n}
                  </Tag>
                ))}
              </Space>
              <div style={{ fontSize: 12, color: 'var(--cn-text-secondary, #666)', marginTop: 4 }}>
                {currentSeries.docCount} 篇文档 · {currentSeries.subFolderCount} 个子文件夹
                {currentSeries.tagCount > 0 && ` · ${currentSeries.tagCount} 个标签`}
                {' · '}更新 {formatTime(currentSeries.latestUpdate)}
              </div>
            </div>
            <Space wrap>
              <Button
                size="small"
                icon={<EditOutlined />}
                data-testid="doc-series-rename"
                onClick={() => {
                  setRenameValue(currentSeries.folder.title)
                  setRenameTarget({ id: currentSeries.folder.id, title: currentSeries.folder.title, isSeries: true })
                }}
              >
                重命名
              </Button>
              <Button
                size="small"
                icon={<ApartmentOutlined />}
                data-testid="doc-series-move"
                onClick={() => {
                  setMoveTarget(currentSeries.folder.parent_id ?? 0)
                  setMoveOpen(true)
                }}
              >
                移动
              </Button>
              <Popconfirm
                title="删除系列将同时删除其中全部文档与子文件夹，确认？"
                okType="danger"
                okText="删除"
                cancelText="取消"
                onConfirm={() => deleteMut.mutate(currentSeries.folder.id)}
              >
                <Button size="small" danger icon={<DeleteOutlined />} data-testid="doc-series-delete">
                  删除
                </Button>
              </Popconfirm>
            </Space>
          </div>
        </Card>
      )}

      {/* 列表：顶层散文档 / 子级全部子项 */}
      {docsQuery.isLoading ? (
        <List loading />
      ) : listItems.length === 0 && (parentId !== null || seriesList.length === 0) ? (
        <Empty description="暂无文档" style={{ marginTop: 80 }}>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>
            创建第一篇文档
          </Button>
        </Empty>
      ) : (
        <List
          className="cn-doc-list"
          data-testid="doc-list"
          dataSource={listItems}
          renderItem={doc => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() =>
                doc.is_folder
                  ? setParentId(doc.id)
                  : navigate(`/w/${workspaceId}/documents/${doc.id}`)
              }
              actions={[
                <Tooltip key="rename" title="重命名">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    aria-label={`重命名 ${doc.title}`}
                    data-testid={`doc-row-rename-${doc.id}`}
                    onClick={e => {
                      e.stopPropagation()
                      setRenameValue(doc.title)
                      setRenameTarget({ id: doc.id, title: doc.title, isSeries: false })
                    }}
                  />
                </Tooltip>,
                <Tooltip key="move" title="移动">
                  <Button
                    type="text"
                    size="small"
                    icon={<ApartmentOutlined />}
                    aria-label={`移动 ${doc.title}`}
                    data-testid={`doc-row-move-${doc.id}`}
                    onClick={e => {
                      e.stopPropagation()
                      setRowMove({ id: doc.id, title: doc.title, parent: doc.parent_id ?? 0 })
                    }}
                  />
                </Tooltip>,
                <Tooltip key="pin" title={doc.pinned ? '取消置顶' : '置顶'}>
                  <Button
                    type="text"
                    size="small"
                    icon={<PushpinOutlined />}
                    aria-label={doc.pinned ? `取消置顶 ${doc.title}` : `置顶 ${doc.title}`}
                    data-testid={`doc-row-pin-${doc.id}`}
                    onClick={e => {
                      e.stopPropagation()
                      pinMut.mutate(doc)
                    }}
                  />
                </Tooltip>,
                <Tooltip key="del" title="删除">
                  <Popconfirm
                    title={doc.is_folder ? '删除文件夹将同时删除其中所有文档，确认？' : '确认删除此文档？'}
                    onConfirm={e => {
                      e?.stopPropagation()
                      deleteMut.mutate(doc.id)
                    }}
                    onCancel={e => e?.stopPropagation()}
                  >
                    <Button
                      type="text"
                      danger
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={e => e.stopPropagation()}
                      aria-label="删除文档"
                      data-testid={`doc-row-delete-${doc.id}`}
                    />
                  </Popconfirm>
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <Space size={4}>
                    <span onClick={e => e.stopPropagation()}>
                      <Checkbox
                        checked={selectedIds.includes(doc.id)}
                        data-testid={`doc-select-${doc.id}`}
                        aria-label={`选择 ${doc.title}`}
                        onChange={() => toggleSelected(doc.id)}
                      />
                    </span>
                    {doc.is_folder ? (
                      <FolderOutlined style={{ fontSize: 22, color: '#faad14' }} />
                    ) : (
                      (() => {
                        const fmt = formatMeta(doc.content_type)
                        const FormatIcon = fmt.Icon
                        return (
                          <FormatIcon
                            aria-label={`格式：${fmt.label}`}
                            data-testid={`doc-list-format-${doc.id}`}
                            style={{ fontSize: 22, color: fmt.color }}
                          />
                        )
                      })()
                    )}
                  </Space>
                }
                title={
                  <Space size={8}>
                    <Text strong>{doc.title}</Text>
                    {doc.pinned && <Tag color="blue" data-testid={`doc-pinned-tag-${doc.id}`}>置顶</Tag>}
                    <Tag color={STATUS_COLORS[doc.status]}>{STATUS_LABELS[doc.status]}</Tag>
                    {/* 可见性提示：未发布的文档同事看不到，明确告知以免误以为文档丢失 */}
                    {doc.visibility === 'private' && (
                      <Tooltip title="未发布：仅你与工作区所有者可见">
                        <Tag
                          icon={<LockOutlined />}
                          data-testid={`doc-list-visibility-${doc.id}`}
                          aria-label="仅自己可见"
                          style={{ fontSize: 11, lineHeight: '18px' }}
                        >
                          仅自己可见
                        </Tag>
                      </Tooltip>
                    )}
                    {doc.tag_ids.length > 0 && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {doc.tag_ids.length} 个标签
                      </Text>
                    )}
                  </Space>
                }
                description={
                  <Space size={16} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      更新于 {formatTime(doc.updated_at)}
                    </Text>
                    {!doc.is_folder && (
                      <>
                        <Text type="secondary" style={{ fontSize: 12 }}>{formatSize(doc.content_size)}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>v{doc.version_count}</Text>
                      </>
                    )}
                    {doc.summary && (
                      <Text type="secondary" style={{ fontSize: 12, maxWidth: 480 }} ellipsis>
                        {doc.summary}
                      </Text>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}

      {/* 新建弹窗 */}
      <Modal
        title={createType === 'folder' ? '新建文件夹' : '新建文档'}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMut.mutate()}
        okButtonProps={{ disabled: !newTitle.trim(), loading: createMut.isPending }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
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

      {/* 通用导入：单文件 / 文件夹 / Obsidian 库 zip，默认落在当前文件夹 */}
      <DocumentImportModal
        open={fileImportOpen}
        onClose={() => setFileImportOpen(false)}
        workspaceId={workspaceId}
        parentId={parentId}
        parentLabel={currentFolderNode?.title}
      />
    </div>
  )
}
