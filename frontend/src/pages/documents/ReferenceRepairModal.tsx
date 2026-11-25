/** 跨工作区移动后的引用修复（ADR 0156）.
 *
 * 交互范式与 AI 动作一致：**建议 → 预览 → 确认**。
 * - 先选「引用来源工作区」（被移动文档此前所在的工作区）与策略；
 * - 预览列出每条「原文 → 新文」与受影响文档，不落库；
 * - 确认后才执行（后端按最新版本重算并生成 `move_repair` 版本，可回滚）。
 *
 * 默认策略 `none`（不改正文）；`annotate` 改写为带说明的静态文本；
 * `snapshot` 额外把 `{{table:…}}` 落为修复时刻的静态表格快照（不再更新）。
 */

import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Modal, Select, Table, Tag, Tooltip, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import { documentsApi } from '@/api/documents'
import type { ReferenceRepairPreview, ReferenceRepairStrategy } from '@/api/documents'
import { REPAIR_STRATEGY_OPTIONS, repairReasonLabel } from './referenceRepairOptions'

const { Text } = Typography

export interface ReferenceRepairModalProps {
  open: boolean
  /** 文档当前所在工作区（移动后的目标工作区） */
  workspaceId: number
  /** 需要修复引用的文档（通常是刚移动的那些） */
  documentIds: number[]
  /** 预选的「引用来源工作区」（移动前的源工作区），可空 */
  initialSourceWorkspaceId?: number | null
  onClose: () => void
  onRepaired?: (changedReferences: number) => void
}

export default function ReferenceRepairModal({
  open, workspaceId, documentIds, initialSourceWorkspaceId, onClose, onRepaired,
}: ReferenceRepairModalProps) {
  const { message } = App.useApp()
  const [sourceId, setSourceId] = useState<number | null>(initialSourceWorkspaceId ?? null)
  const [strategy, setStrategy] = useState<ReferenceRepairStrategy>('annotate')
  const [submitting, setSubmitting] = useState(false)

  // 可选来源工作区：当前用户在这些工作区有写权限（owner/editor），排除文档当前所在工作区
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: () => workspaceApi.list(), enabled: open })
  const sourceOptions = useMemo(
    () =>
      (workspacesQuery.data ?? [])
        .filter(ws => String(ws.id) !== String(workspaceId))
        .filter(ws => ws.current_user_role === 'owner' || ws.current_user_role === 'editor')
        .map(ws => ({ value: ws.id, label: ws.name })),
    [workspacesQuery.data, workspaceId],
  )

  useEffect(() => {
    if (!open) return
    setSourceId(initialSourceWorkspaceId ?? null)
    setStrategy('annotate')
  }, [open, initialSourceWorkspaceId])

  const previewQuery = useQuery({
    queryKey: ['reference-repair-preview', sourceId, workspaceId, documentIds.join(','), strategy],
    queryFn: () =>
      documentsApi.previewReferenceRepair(sourceId as number, {
        document_ids: documentIds,
        target_workspace_id: workspaceId,
        strategy,
      }),
    enabled: open && sourceId !== null && documentIds.length > 0 && strategy !== 'none',
  })
  const previews = previewQuery.data?.previews ?? []
  const noIssues = previewQuery.isSuccess && previews.length === 0

  const submit = async () => {
    if (sourceId === null) {
      message.warning('请选择引用来源工作区')
      return
    }
    setSubmitting(true)
    try {
      const result = await documentsApi.repairReferences(sourceId, {
        document_ids: documentIds,
        target_workspace_id: workspaceId,
        strategy,
      })
      message.success(
        result.changed_references > 0
          ? `已修复 ${result.changed_documents} 篇文档中的 ${result.changed_references} 条引用`
          : '没有需要修复的引用',
      )
      onRepaired?.(result.changed_references)
      onClose()
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      message.error(detail ? `修复失败：${detail}` : '修复失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="跨工作区引用修复"
      open={open}
      onCancel={onClose}
      onOk={() => void submit()}
      okText="确认修复"
      cancelText="取消"
      okButtonProps={{ disabled: sourceId === null || strategy === 'none' || previews.length === 0 }}
      confirmLoading={submitting}
      width={720}
      destroyOnHidden
    >
      <div data-testid="reference-repair-body" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--cn-space-sm)' }}>
        <div style={{ display: 'flex', gap: 'var(--cn-space-sm)', flexWrap: 'wrap' }}>
          <Select
            data-testid="reference-repair-source"
            style={{ minWidth: 220 }}
            placeholder="引用来源工作区（移动前所在）"
            value={sourceId ?? undefined}
            onChange={value => setSourceId(value)}
            options={sourceOptions}
            showSearch
            optionFilterProp="label"
          />
          <Select
            data-testid="reference-repair-strategy"
            style={{ minWidth: 180 }}
            value={strategy}
            onChange={value => setStrategy(value)}
            options={REPAIR_STRATEGY_OPTIONS.filter(option => option.value !== 'none')}
          />
        </div>

        <Alert
          type="info"
          showIcon
          message="修复会改写正文并生成新版本（可回滚）"
          description="只替换失效的引用片段，代码块内文本与其余内容不变；「表格快照」是修复时刻的静态数据，之后不会随原表更新。"
        />

        {previewQuery.isLoading && <Text type="secondary">正在分析引用…</Text>}
        {noIssues && (
          <Text type="secondary" data-testid="reference-repair-empty">
            没有发现需要修复的引用。
          </Text>
        )}
        {previews.length > 0 && (
          <Table<ReferenceRepairPreview>
            size="small"
            rowKey={row => `${row.document_id}-${row.raw}`}
            dataSource={previews}
            pagination={{ pageSize: 8, hideOnSinglePage: true }}
            data-testid="reference-repair-table"
            columns={[
              {
                title: '原因',
                dataIndex: 'reason',
                width: 150,
                render: (reason: ReferenceRepairPreview['reason']) => (
                  <Tooltip title={reason}>
                    <Tag>{repairReasonLabel(reason)}</Tag>
                  </Tooltip>
                ),
              },
              {
                title: '原文',
                dataIndex: 'raw',
                render: (raw: string) => <code style={{ fontSize: 'var(--cn-text-xs)' }}>{raw}</code>,
              },
              {
                title: '修复后',
                dataIndex: 'next',
                render: (next: string) => (
                  <span style={{ fontSize: 'var(--cn-text-xs)', whiteSpace: 'pre-wrap' }}>{next}</span>
                ),
              },
            ]}
          />
        )}
      </div>
    </Modal>
  )
}
