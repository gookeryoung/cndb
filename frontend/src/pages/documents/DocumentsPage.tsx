/** 文档管理页 — 工作区级 Markdown 文档列表 / 树 / 搜索入口. */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Breadcrumb,
  Button,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderAddOutlined,
  FolderOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '@/api/documents'
import type { DocumentItem } from '@/api/documents'

const { Text } = Typography

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

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

export default function DocumentsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const workspaceId = Number(wid)

  const [parentId, setParentId] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [titleKeyword, setTitleKeyword] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createType, setCreateType] = useState<'doc' | 'folder'>('doc')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')

  const docsQuery = useQuery({
    queryKey: ['documents', workspaceId, parentId, statusFilter],
    queryFn: () =>
      documentsApi.list(workspaceId, {
        parent_id: parentId ?? undefined,
        status: statusFilter,
        limit: 200,
      }),
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
    onSuccess: () => {
      message.success('已删除')
      invalidate()
    },
    onError: () => message.error('删除失败'),
  })

  const breadcrumb = useQuery({
    queryKey: ['documents', workspaceId, 'tree'],
    queryFn: () => documentsApi.tree(workspaceId),
    enabled: Number.isFinite(workspaceId) && parentId !== null,
  })

  const breadcrumbItems = useMemo(() => {
    const map = new Map<number, DocumentItem>()
    for (const d of breadcrumb.data ?? []) map.set(d.id, d)
    const chain: DocumentItem[] = []
    let cur = parentId
    while (cur !== null) {
      const node = map.get(cur)
      if (!node) break
      chain.unshift(node)
      cur = node.parent_id
    }
    return chain
  }, [breadcrumb.data, parentId])

  const filtered = useMemo(() => {
    const items = docsQuery.data?.items ?? []
    if (!titleKeyword.trim()) return items
    const kw = titleKeyword.trim().toLowerCase()
    return items.filter(d => d.title.toLowerCase().includes(kw))
  }, [docsQuery.data, titleKeyword])

  const openCreate = (type: 'doc' | 'folder') => {
    setCreateType(type)
    setCreateOpen(true)
  }

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

      {/* 列表 */}
      {docsQuery.isLoading ? (
        <List loading />
      ) : filtered.length === 0 ? (
        <Empty description="暂无文档" style={{ marginTop: 80 }}>
          <Button type="primary" icon={<FileAddOutlined />} onClick={() => openCreate('doc')}>
            创建第一篇文档
          </Button>
        </Empty>
      ) : (
        <List
          dataSource={filtered}
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
    </div>
  )
}
