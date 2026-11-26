/** 文档列表（桌面端）—— 列对齐的 antd Table，文件夹与文档共用同一套列.
 *
 * 设计口径（需求 0162）：
 *  - 默认列表视图，列固定为 名称 / 状态 / 标签 / 大小 / 更新时间 / 操作；
 *  - 文件夹行排在同级文档之前（由调用方分组），名称单元格补一行递归统计；
 *  - 行高、表头、数字列对齐与数据表目录页（TablesList）保持一致；
 *  - 选择、更多操作、可见性锁、置顶标识沿用原 testid，供既有用例与 e2e 复用。
 */

import { Fragment, type ReactNode } from 'react'
import { Badge, Checkbox, Table, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { LockOutlined, PushpinOutlined } from '@ant-design/icons'
import type { DocumentItem } from '@/api/documents'
import { formatMeta } from '@/components/Document/docFormat'
import { formatSize } from '@/utils/formatSize'
import { formatDate, formatTime, STATUS_LABELS } from './documentDisplay'
import type { FolderSummary } from './seriesStats'

const { Text } = Typography

/** 桌面状态降噪：圆点 + 文本，沿用既有色义 */
const STATUS_BADGE: Record<string, 'default' | 'success' | 'warning'> = {
  draft: 'default',
  published: 'success',
  archived: 'warning',
}

export interface DocumentTableProps {
  items: DocumentItem[]
  /** 文件夹状态按递归子孙聚合（空文件夹不出状态） */
  folderStatusCounts: Map<number, Record<string, number>>
  /** 文件夹行副标题（递归文档数 / 子文件夹数 / 标签数） */
  folderSummaries: Map<number, FolderSummary>
  selectedIds: number[]
  onToggleSelected: (id: number) => void
  onOpen: (doc: DocumentItem) => void
  renderRowActions: (doc: DocumentItem) => ReactNode
  emptyText?: ReactNode
  testId?: string
}

export default function DocumentTable({
  items,
  folderStatusCounts,
  folderSummaries,
  selectedIds,
  onToggleSelected,
  onOpen,
  renderRowActions,
  emptyText,
  testId,
}: DocumentTableProps) {
  const columns: ColumnsType<DocumentItem> = [
    {
      key: 'select',
      width: 32,
      render: (_, doc) => (
        <span onClick={event => event.stopPropagation()}>
          <Checkbox
            checked={selectedIds.includes(doc.id)}
            data-testid={`doc-select-${doc.id}`}
            aria-label={`选择 ${doc.title}`}
            onChange={() => onToggleSelected(doc.id)}
          />
        </span>
      ),
    },
    {
      title: '名称',
      key: 'name',
      render: (_, doc) => {
        const fmt = formatMeta(doc.content_type, doc.is_folder)
        const FormatIcon = fmt.Icon
        const statusCounts = doc.is_folder
          ? folderStatusCounts.get(doc.id) ?? {}
          : { [doc.status]: 1 }
        const showPrivate = doc.is_folder
          ? Object.keys(statusCounts).some(status => status !== 'published')
          : doc.visibility === 'private'
        return (
          <div className="cn-doc-table-name">
            <FormatIcon
              aria-label={`格式：${fmt.label}`}
              data-testid={`doc-list-format-${doc.id}`}
              style={{ color: fmt.color, flexShrink: 0 }}
            />
            <div className="cn-doc-table-name-body">
              <div className="cn-doc-row-title-line">
                <Text strong className="cn-doc-title-single" title={doc.title}>{doc.title}</Text>
                {doc.pinned && (
                  <PushpinOutlined
                    aria-label="置顶"
                    data-testid={`doc-pinned-tag-${doc.id}`}
                    style={{ color: 'var(--cn-brand-color)', fontSize: 'var(--cn-text-sm)' }}
                  />
                )}
                {showPrivate && (
                  <Tooltip
                    title={doc.is_folder
                      ? '含未发布内容：其中草稿 / 归档仅你与工作区所有者可见'
                      : '未发布：仅你与工作区所有者可见'}
                  >
                    <LockOutlined
                      data-testid={`doc-list-visibility-${doc.id}`}
                      aria-label="仅自己可见"
                      style={{ color: 'var(--cn-text-muted)', fontSize: 'var(--cn-text-xs)' }}
                    />
                  </Tooltip>
                )}
              </div>
              {doc.is_folder && <FolderSummaryLine summary={folderSummaries.get(doc.id)} />}
            </div>
          </div>
        )
      },
    },
    {
      title: '状态',
      key: 'status',
      width: 130,
      render: (_, doc) => {
        const counts = doc.is_folder
          ? folderStatusCounts.get(doc.id) ?? {}
          : { [doc.status]: 1 }
        return (
          <span className="cn-doc-table-status">
            {Object.entries(counts).map(([status, count]) => (
              <Badge
                key={status}
                data-testid={`doc-list-status-${doc.id}-${status}`}
                status={STATUS_BADGE[status] ?? 'default'}
                text={doc.is_folder ? `${STATUS_LABELS[status] ?? status} ${count}` : STATUS_LABELS[status]}
              />
            ))}
          </span>
        )
      },
    },
    {
      title: '标签',
      key: 'tags',
      width: 64,
      render: (_, doc) => (
        <Text type="secondary" className="cn-doc-table-muted">
          {doc.tag_ids.length > 0 ? `${doc.tag_ids.length} 个` : '—'}
        </Text>
      ),
    },
    {
      title: '大小',
      key: 'size',
      width: 76,
      align: 'right',
      render: (_, doc) => (
        <Text type="secondary" className="cn-doc-table-num">
          {doc.is_folder ? '—' : formatSize(doc.content_size)}
        </Text>
      ),
    },
    {
      title: '更新时间',
      key: 'updated',
      width: 104,
      align: 'right',
      render: (_, doc) => (
        <Tooltip title={formatTime(doc.updated_at)}>
          <Text type="secondary" className="cn-doc-table-num">
            {formatDate(doc.updated_at)}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 48,
      align: 'right',
      render: (_, doc) => renderRowActions(doc),
    },
  ]

  return (
    <div className="cn-doc-list cn-doc-table-card" data-testid={testId}>
      <Table<DocumentItem>
        className="cn-doc-table cn-table-list"
        size="small"
        rowKey="id"
        columns={columns}
        dataSource={items}
        pagination={false}
        tableLayout="fixed"
        locale={{ emptyText: emptyText ?? '暂无内容' }}
        onRow={doc => ({
          onClick: () => onOpen(doc),
          'data-testid': `doc-row-${doc.id}`,
          style: { cursor: 'pointer' },
        })}
      />
    </div>
  )
}

/** 文件夹行第二行：递归统计（文档 / 子文件夹 / 标签），与卡片的元信息同口径 */
function FolderSummaryLine({ summary }: { summary?: FolderSummary }) {
  if (!summary) return null
  const parts = [`${summary.docCount} 篇文档`]
  if (summary.subFolderCount > 0) parts.push(`${summary.subFolderCount} 个子文件夹`)
  if (summary.tagCount > 0) parts.push(`${summary.tagCount} 个标签`)
  return (
    <span className="cn-doc-table-sub">
      {parts.map((part, index) => (
        <Fragment key={part}>
          {index > 0 && <span aria-hidden> · </span>}
          <span>{part}</span>
        </Fragment>
      ))}
    </span>
  )
}
