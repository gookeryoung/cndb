/** 工作区附件管理页（需求 0174）.
 *
 * 列出 `data/uploads/{workspace_id}` 下的附件与归属文档；「体检」扫描正文与原件字段的
 * 引用次数并标出孤儿（无归属且未被引用）；「回收孤儿」仅 owner 可用，默认二次确认。
 * 列表与体检均为 editor+，viewer 不可见（附件键近似 capability URL）。
 */

import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { DeleteOutlined, PaperClipOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { documentsApi } from '@/api/documents'
import type { AttachmentItem, AttachmentScanResult } from '@/api/documents'
import { workspaceApi } from '@/api/workspaces'
import { SPACE } from '@/theme/tokens'
import { formatDateTime } from '@/utils/datetime'
import { formatSize } from '@/utils/formatSize'

const { Text } = Typography

export default function DocumentAttachmentsPage() {
  const { wid } = useParams<{ wid: string }>()
  const workspaceId = wid ?? ''
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [scan, setScan] = useState<AttachmentScanResult | null>(null)

  const listQuery = useQuery({
    queryKey: ['document-attachments', workspaceId, keyword, page, pageSize],
    queryFn: () =>
      documentsApi.listAttachments(workspaceId, {
        q: keyword.trim() || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      }),
  })

  const capabilitiesQuery = useQuery({
    queryKey: ['workspace-capabilities', workspaceId],
    queryFn: () => workspaceApi.capabilities(workspaceId),
  })
  const isOwner = capabilitiesQuery.data?.data_role === 'owner'

  const scanMut = useMutation({
    mutationFn: () => documentsApi.scanAttachments(workspaceId),
    onSuccess: result => setScan(result),
    onError: () => message.error('附件体检失败'),
  })

  const purgeMut = useMutation({
    mutationFn: () => documentsApi.purgeAttachments(workspaceId, false),
    onSuccess: result => {
      message.success(`已回收 ${result.removed_files} 个孤儿附件（${formatSize(result.removed_bytes)}）`)
      setScan(null)
      void listQuery.refetch()
    },
    onError: () => message.error('回收失败'),
  })

  /** 体检结果按 file_key 索引，列表行据此展示引用数与孤儿标记 */
  const scanMap = useMemo(() => {
    const map = new Map<string, { refCount: number; orphan: boolean }>()
    for (const item of scan?.items ?? []) {
      map.set(item.file_key, { refCount: item.ref_count, orphan: item.orphan })
    }
    return map
  }, [scan])

  const columns: ColumnsType<AttachmentItem> = [
    {
      title: '文件名',
      dataIndex: 'name',
      ellipsis: true,
      render: (name: string) => <Text title={name}>{name}</Text>,
    },
    {
      title: '大小',
      dataIndex: 'size',
      width: 100,
      align: 'right',
      render: (size: number) => formatSize(size),
    },
    {
      title: '归属文档',
      dataIndex: 'document_title',
      width: 220,
      ellipsis: true,
      render: (_value, row) =>
        row.document_title ? (
          <Text>{row.document_title}</Text>
        ) : (
          <Text type="secondary">未登记归属</Text>
        ),
    },
    {
      title: '状态',
      key: 'status',
      width: 160,
      render: (_value, row) => {
        const meta = scanMap.get(row.file_key)
        if (!meta) return <Text type="secondary">未体检</Text>
        if (meta.orphan) return <Tag color="red">孤儿</Tag>
        return <Tag color="green">引用 {meta.refCount}</Tag>
      },
    },
    {
      title: '上传时间',
      dataIndex: 'uploaded_at',
      width: 160,
      render: (value: number) => formatDateTime(new Date(value * 1000).toISOString()),
    },
  ]

  return (
    <div className="cn-page" data-testid="document-attachments-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><PaperClipOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">附件</h1>
            <div className="cn-page-head-sub">
              工作区上传的图片与原件文件；体检会扫描正文引用，孤儿可回收
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Space size={SPACE.sm}>
            <Button
              size="small"
              icon={<SafetyCertificateOutlined />}
              loading={scanMut.isPending}
              data-testid="attachment-scan"
              onClick={() => scanMut.mutate()}
            >
              体检
            </Button>
            {isOwner && (
              <Popconfirm
                title={`回收 ${scan?.orphan_count ?? 0} 个孤儿附件？`}
                description="仅删除无归属且未被正文引用的文件，操作不可撤销"
                okText="回收"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                disabled={!scan || scan.orphan_count === 0}
                onConfirm={() => purgeMut.mutate()}
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!scan || scan.orphan_count === 0}
                  loading={purgeMut.isPending}
                  data-testid="attachment-purge"
                >
                  回收孤儿
                </Button>
              </Popconfirm>
            )}
          </Space>
        </div>
      </header>

      {scan && (
        <Alert
          type={scan.orphan_count > 0 ? 'warning' : 'success'}
          showIcon
          style={{ marginBottom: SPACE.lg }}
          title={
            scan.orphan_count > 0
              ? `体检完成：${scan.orphan_count} 个孤儿附件，可回收 ${formatSize(scan.orphan_bytes)}`
              : '体检完成：未发现孤儿附件'
          }
        />
      )}

      <Space orientation="vertical" size={SPACE.md} style={{ width: '100%' }}>
        <Input.Search
          allowClear
          placeholder="按文件名搜索"
          style={{ maxWidth: 320 }}
          data-testid="attachment-search"
          onSearch={value => {
            setKeyword(value)
            setPage(1)
          }}
        />
        <Table<AttachmentItem>
          size="small"
          rowKey="file_key"
          columns={columns}
          dataSource={listQuery.data?.items ?? []}
          loading={listQuery.isLoading}
          pagination={{
            current: page,
            pageSize,
            total: listQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextSize) => {
              setPage(nextPage)
              setPageSize(nextSize)
            },
          }}
        />
      </Space>
    </div>
  )
}
