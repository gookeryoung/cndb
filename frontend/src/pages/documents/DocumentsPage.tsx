/** 文档管理页 — 顶层系列卡片总览 + 文件夹列表 / 树 / 搜索入口. */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Drawer,
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
import { documentsApi } from '@/api/documents'
import type { DocumentItem, SearchHitItem, TrashItem } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { buildDocTree, descendantIds, findNodeById } from './DocumentTree'
import type { DocTreeNode } from './DocumentTree'
import { parseHitHighlight } from '@/components/Document/outline'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'default',
  published: 'green',
  archived: 'orange',
}

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '归档',
}

/** 顶层系列（文件夹）聚合统计 — 卡片总览数据源 */
export interface SeriesSummary {
  folder: DocumentItem
  /** 递归子孙文档数（不含子文件夹本身） */
  docCount: number
  /** 递归子文件夹数 */
  subFolderCount: number
  /** 子孙文档标签去重数 */
  tagCount: number
  /** 子孙最近更新时间（含文件夹自身） */
  latestUpdate: string
  /** 子孙文档状态分布（draft/published/archived → 计数） */
  statusCounts: Record<string, number>
}

/** 顶层文件夹即系列：按递归子孙聚合文档数/标签/状态/最近更新 */
export function buildSeriesStats(items: DocumentItem[]): SeriesSummary[] {
  return buildDocTree(items)
    .filter(node => node.is_folder)
    .map(seriesStatsOf)
}

/** 单个文件夹的系列聚合统计（递归子孙；系列详情头部复用） */
export function seriesStatsOf(folder: DocTreeNode): SeriesSummary {
  const descendants: DocumentItem[] = []
  const walk = (nodes: DocTreeNode[]) => {
    for (const n of nodes) {
      descendants.push(n)
      walk(n.children)
    }
  }
  walk(folder.children)
  const docs = descendants.filter(d => !d.is_folder)
  const tags = new Set<number>()
  const statusCounts: Record<string, number> = {}
  for (const d of docs) {
    for (const t of d.tag_ids) tags.add(t)
    statusCounts[d.status] = (statusCounts[d.status] ?? 0) + 1
  }
  const latestUpdate = descendants.reduce(
    (max, d) => (d.updated_at > max ? d.updated_at : max),
    folder.updated_at,
  )
  return {
    folder,
    docCount: docs.length,
    subFolderCount: descendants.filter(d => d.is_folder).length,
    tagCount: tags.size,
    latestUpdate,
    statusCounts,
  }
}

export default function DocumentsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const { isMobile } = useResponsive()

  const [parentId, setParentId] = useState<number | null>(null)
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
  const [searchKeyword, setSearchKeyword] = useState('')
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
    queryKey: ['documents', workspaceId, 'list', parentId, statusFilter],
    queryFn: () =>
      documentsApi.list(workspaceId, {
        parent_id: parentId ?? undefined,
        status: statusFilter,
        limit: 200,
      }),
    // 子级列表走 list 端点；顶层散文档由全量树派生（list 不传 parent_id 会返回全部层级）
    enabled: Number.isFinite(workspaceId) && parentId !== null,
  })

  // 全文搜索（FTS5）：抽屉打开且有关键词时触发
  const searchQuery = useQuery({
    queryKey: ['documents', workspaceId, 'search', searchKeyword],
    queryFn: () => documentsApi.search(workspaceId, searchKeyword, { limit: 30 }),
    enabled: Number.isFinite(workspaceId) && searchOpen && searchKeyword.trim().length > 0,
    placeholderData: prev => prev,
  })

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
  }, [qc, workspaceId])

  // 回收站：软删除文档列表（打开抽屉时拉取，按删除时间倒序）
  const trashQuery = useQuery({
    queryKey: ['documents', workspaceId, 'trash'],
    queryFn: () => documentsApi.trash(workspaceId, { limit: 200 }),
    enabled: Number.isFinite(workspaceId) && trashOpen,
  })

  const restoreMut = useMutation({
    mutationFn: (docId: number) => documentsApi.restore(workspaceId, docId),
    onSuccess: data => {
      message.success(data.reparented_to_root ? '已恢复（原父目录仍在回收站，已挂到根目录）' : '已恢复')
      invalidate()
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? '恢复失败')
    },
  })

  const purgeMut = useMutation({
    mutationFn: (docId: number) => documentsApi.purge(workspaceId, docId),
    onSuccess: data => {
      message.success(`已彻底删除 ${data.purged_count} 项`)
      invalidate()
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? '彻底删除失败')
    },
  })

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
    if (!kw) return all
    return all.filter(s => s.folder.title.toLowerCase().includes(kw))
  }, [treeQuery.data, titleKeyword])

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
    if (parentId !== null) return filtered
    const kw = titleKeyword.trim().toLowerCase()
    return (treeQuery.data ?? [])
      .filter(
        d =>
          d.parent_id == null &&
          !d.is_folder &&
          (!kw || d.title.toLowerCase().includes(kw)) &&
          (!statusFilter || d.status === statusFilter),
      )
  }, [filtered, parentId, treeQuery.data, titleKeyword, statusFilter])

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

      {/* 全文搜索抽屉：FTS5 命中列表，点击进入文档编辑页 */}
      <Drawer
        title="全文搜索"
        width={isMobile ? '100%' : 520}
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
      >
        <Input.Search
          allowClear
          autoFocus
          enterButton
          placeholder="标题 / 正文 / 摘要关键词…"
          data-testid="doc-search-input"
          onSearch={q => setSearchKeyword(q)}
          style={{ marginBottom: 16 }}
        />
        {searchKeyword.trim() === '' ? (
          <Text type="secondary">输入关键词回车搜索（正文全文检索）</Text>
        ) : searchQuery.isLoading ? (
          <div>搜索中…</div>
        ) : (searchQuery.data?.items ?? []).length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无命中结果" />
        ) : (
          <List
            dataSource={searchQuery.data?.items ?? []}
            renderItem={(hit: SearchHitItem) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                data-testid={`doc-search-hit-${hit.id}`}
                onClick={() => {
                  setSearchOpen(false)
                  navigate(`/w/${workspaceId}/documents/${hit.id}`)
                }}
              >
                <List.Item.Meta
                  title={<HitText hit={hit.title_hit} strong />}
                  description={
                    <Space direction="vertical" size={2}>
                      <HitText hit={hit.summary_hit} />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {STATUS_LABELS[hit.status] ?? hit.status} · 更新 {formatTime(hit.updated_at)}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>

      {/* 回收站抽屉：软删除文档列表，支持恢复 / 彻底删除 */}
      <Drawer
        title="回收站"
        width={isMobile ? '100%' : 520}
        open={trashOpen}
        onClose={() => setTrashOpen(false)}
        data-testid="doc-trash-drawer"
      >
        {trashQuery.isLoading ? (
          <div>加载中…</div>
        ) : (trashQuery.data?.items ?? []).length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="回收站为空" />
        ) : (
          <List
            dataSource={trashQuery.data?.items ?? []}
            renderItem={(item: TrashItem) => (
              <List.Item
                key={item.id}
                data-testid={`doc-trash-item-${item.id}`}
                actions={[
                  <Button
                    key="restore"
                    size="small"
                    data-testid={`doc-trash-restore-${item.id}`}
                    loading={restoreMut.isPending && restoreMut.variables === item.id}
                    onClick={() => restoreMut.mutate(item.id)}
                  >
                    恢复
                  </Button>,
                  <Popconfirm
                    key="purge"
                    title={
                      item.is_folder
                        ? '彻底删除将连同回收站中的子项与全部历史版本一并清除，且不可恢复，确认？'
                        : '彻底删除将清除全部历史版本与外存内容，且不可恢复，确认？'
                    }
                    okType="danger"
                    okText="彻底删除"
                    cancelText="取消"
                    onConfirm={() => purgeMut.mutate(item.id)}
                  >
                    <Button size="small" danger data-testid={`doc-trash-purge-${item.id}`}>
                      彻底删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space size={6}>
                      {item.is_folder ? <FolderOutlined /> : <FileTextOutlined />}
                      <Text strong>{item.title}</Text>
                    </Space>
                  }
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.is_folder ? '文件夹' : '文档'} · 删除于{' '}
                      {item.deleted_at ? formatTime(item.deleted_at) : '未知时间'}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>
    </div>
  )
}

/** 搜索命中片段渲染：<mark> 标记部分高亮，其余次级文本 */
function HitText({ hit, strong }: { hit: string; strong?: boolean }) {
  return (
    <>
      {parseHitHighlight(hit).map((p, i) =>
        p.marked ? (
          <Text key={i} mark strong={strong}>
            {p.text}
          </Text>
        ) : (
          <Text key={i} type="secondary" strong={strong}>
            {p.text}
          </Text>
        ),
      )}
    </>
  )
}
