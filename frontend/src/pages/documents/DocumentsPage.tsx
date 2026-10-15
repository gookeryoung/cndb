/** 文档管理页 — 顶层系列卡片总览 + 文件夹列表 / 树 / 搜索入口. */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
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
import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderAddOutlined,
  FolderOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DOCUMENT_ORDER_OPTIONS, sortDocuments, type DocumentOrder } from './documentSort'
import { documentsApi } from '@/api/documents'
import type { DocumentItem } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { buildDocTree, descendantIds, findNodeById } from './DocumentTree'
import { buildSeriesStats, seriesStatsOf } from './seriesStats'
import { formatTime, STATUS_COLORS, STATUS_LABELS } from './documentDisplay'
import SearchDrawer from './SearchDrawer'
import TrashDrawer from './TrashDrawer'
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

  // 当前文件夹与排序口径写入 URL（?parent=&order=）：支持从编辑器面包屑深链、刷新与分享
  const parentParam = searchParams.get('parent')
  const parentId = parentParam !== null && parentParam !== '' ? Number(parentParam) : null
  const orderParam = searchParams.get('order') as DocumentOrder | null
  const orderBy: DocumentOrder = DOCUMENT_ORDER_OPTIONS.some(o => o.value === orderParam)
    ? (orderParam as DocumentOrder)
    : 'sort'

  const updateParams = useCallback((patch: { parent?: number | null; order?: DocumentOrder }) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (patch.parent !== undefined) {
        if (patch.parent === null) next.delete('parent')
        else next.set('parent', String(patch.parent))
      }
      if (patch.order !== undefined) {
        if (patch.order === 'sort') next.delete('order')
        else next.set('order', patch.order)
      }
      return next
    }, { replace: true })
  }, [setSearchParams])

  const setParentId = useCallback((id: number | null) => updateParams({ parent: id }), [updateParams])

  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [titleKeyword, setTitleKeyword] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState<'doc' | 'folder'>('doc')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  // 系列详情：重命名 / 移动弹窗状态
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [moveOpen, setMoveOpen] = useState(false)
  const [moveTarget, setMoveTarget] = useState<number>(0)
  // 全文搜索抽屉
  const [searchOpen, setSearchOpen] = useState(false)
  // 回收站抽屉
  const [trashOpen, setTrashOpen] = useState(false)

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
    queryKey: ['documents', workspaceId, 'list', parentId, statusFilter, orderBy],
    queryFn: () =>
      documentsApi.list(workspaceId, {
        parent_id: parentId ?? undefined,
        status: statusFilter,
        order: orderBy,
        limit: 200,
      }),
    // 子级列表走 list 端点；顶层散文档由全量树派生（list 不传 parent_id 会返回全部层级）
    enabled: Number.isFinite(workspaceId) && parentId !== null,
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

  // 系列重命名（PATCH title）
  const renameMut = useMutation({
    mutationFn: () =>
      documentsApi.updateMeta(workspaceId, currentSeries!.folder.id, {
        title: renameValue.trim(),
      }),
    onSuccess: () => {
      message.success('已重命名')
      setRenameOpen(false)
      invalidate()
    },
    onError: () => message.error('重命名失败'),
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

  const seriesList = useMemo(() => {
    const all = buildSeriesStats(treeQuery.data ?? [])
    const kw = titleKeyword.trim().toLowerCase()
    const hit = kw ? all.filter(s => s.folder.title.toLowerCase().includes(kw)) : all
    // 根层主体是系列卡片，同样按所选口径排序（最新更新时间取整个系列的聚合值）
    return sortDocuments(
      hit.map(s => ({
        ...s,
        title: s.folder.title,
        sort_order: s.folder.sort_order,
        created_at: s.folder.created_at,
        updated_at: s.latestUpdate ?? s.folder.updated_at,
        pinned: s.folder.pinned,
      })),
      orderBy,
    )
  }, [treeQuery.data, titleKeyword, orderBy])

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
          (!statusFilter || d.status === statusFilter),
      )
    // 置顶优先 + 所选口径（与后端 order 参数同口径，保证顶层派生列表也一致）
    return sortDocuments(raw, orderBy)
  }, [filtered, parentId, treeQuery.data, titleKeyword, statusFilter, orderBy])

  const openCreate = (type: 'doc' | 'folder') => {
    setCreateType(type)
    setCreateOpen(true)
  }

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
      { key: 'root', value: 0, title: '（根目录）', children: roots.filter(n => n.is_folder).map(toOption) },
    ]
  }, [moveOpen, currentFolderNode, treeQuery.data])

  if (!Number.isFinite(workspaceId)) {
    return <Alert type="error" message="无效的工作区" />
  }

  return (
    <div style={{ padding: 24 }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <Space wrap>
          {parentId !== null && (
            <Button icon={<ArrowLeftOutlined />} onClick={() => {
              const parentDoc = breadcrumbItems[breadcrumbItems.length - 1]
              setParentId(parentDoc?.parent_id ?? null)
            }}>
              上一级
            </Button>
          )}
          <Breadcrumb
            items={[
              { title: <a onClick={() => setParentId(null)}>文档</a> },
              ...breadcrumbItems.map(b => ({ title: b.title })),
            ]}
          />
        </Space>
        <Space wrap>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="本页标题过滤"
            style={{ width: 180 }}
            value={titleKeyword}
            onChange={e => setTitleKeyword(e.target.value)}
          />
          <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>
            全文搜索
          </Button>
          <Button icon={<DeleteOutlined />} data-testid="doc-trash-open" onClick={() => setTrashOpen(true)}>
            回收站
          </Button>
          <Select
            style={{ width: 120 }}
            value={orderBy}
            data-testid="doc-order-select"
            onChange={(v: DocumentOrder) => updateParams({ order: v })}
            options={DOCUMENT_ORDER_OPTIONS}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 110 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'published', label: '已发布' },
              { value: 'archived', label: '归档' },
            ]}
          />
          <Button icon={<FolderAddOutlined />} onClick={() => openCreate('folder')}>新建文件夹</Button>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>新建文档</Button>
        </Space>
      </div>

      {/* 顶层：系列卡片网格（顶层文件夹即系列） */}
      {parentId === null && seriesList.length > 0 && (
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
                  <FolderOutlined style={{ fontSize: 20, color: 'var(--cn-warning, #faad14)' }} />
                  <Text strong style={{ fontSize: 15 }}>{s.folder.title}</Text>
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
        <Card size="small" data-testid="doc-series-detail" styles={{ body: { padding: isMobile ? 12 : 16 } }} style={{ marginBottom: 16 }}>
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
                  setRenameOpen(true)
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
                      onClick={e => e.stopPropagation()}
                      aria-label="删除文档"
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  doc.is_folder ? (
                    <FolderOutlined style={{ fontSize: 22, color: '#faad14' }} />
                  ) : (
                    <FileTextOutlined style={{ fontSize: 22, color: '#1890ff' }} />
                  )
                }
                title={
                  <Space size={8}>
                    <Text strong>{doc.title}</Text>
                    <Tag color={STATUS_COLORS[doc.status]}>{STATUS_LABELS[doc.status]}</Tag>
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

      {/* 系列重命名弹窗 */}
      <Modal
        title={`重命名系列「${currentSeries?.folder.title ?? ''}」`}
        open={renameOpen}
        onCancel={() => setRenameOpen(false)}
        onOk={() => renameMut.mutate()}
        okButtonProps={{ disabled: !renameValue.trim(), loading: renameMut.isPending }}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Input
          placeholder="系列名称"
          value={renameValue}
          onChange={e => setRenameValue(e.target.value)}
          onPressEnter={() => renameValue.trim() && renameMut.mutate()}
          autoFocus
          data-testid="doc-series-rename-input"
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

      <SearchDrawer open={searchOpen} onClose={() => setSearchOpen(false)} wid={workspaceId} />

      <TrashDrawer open={trashOpen} onClose={() => setTrashOpen(false)} wid={workspaceId} />
    </div>
  )
}
