/** 跨工作区移动文档（ADR 0155）.
 *
 * 支持单篇 / 多篇 / 文件夹（后端按子树整体迁移）；目标工作区与目标文件夹都由后端返回
 * 可移动候选（`GET …/documents/move-targets`），前端不猜权限与配额。
 *
 * 交互要点：
 * - 选中目标工作区后懒加载它的文档树，用于选「目标文件夹」（可选，默认根目录）；
 * - 影响说明写清三件事：分享链接继续有效、待审修改申请随文档迁移、`[[双链]]` /
 *   `{{table:…}}` 引用不会自动修复；
 * - 目标配额不足时后端返回 413 + 差额文案，直接在弹窗里提示，禁止提交；
 * - 提交成功后关闭并回调目标工作区 id（调用方决定跳转 / 刷新）。
 */

import { useEffect, useMemo, useState } from 'react'
import { App, Alert, Modal, Select, Spin, Tag, TreeSelect, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { documentsApi, type DocumentMoveTarget } from '@/api/documents'


const { Text } = Typography

export interface MoveDocumentModalProps {
  open: boolean
  /** 源工作区 */
  workspaceId: number
  /** 要移动的根节点（单篇 / 多篇 / 文件夹） */
  documentIds: number[]
  /** 调用方附加的说明（如「共 3 项，含 1 个文件夹」），可空 */
  summary?: string
  onClose: () => void
  /** 移动成功：回调目标工作区 id（调用方可跳转 / 刷新） */
  onMoved?: (targetWorkspaceId: number) => void
}

/** TreeSelect 需要的节点形状（antd 用 value/key/title + children） */
interface FolderOption {
  title: string
  value: number
  key: number
  children?: FolderOption[]
}

/** 文档树 → TreeSelect 的文件夹节点（只为选目标文件夹，按需裁剪空分支） */
function folderNodes(items: Array<{ id: number; title: string; is_folder: boolean; parent_id: number | null }>): FolderOption[] {
  const children = new Map<number | null, typeof items>()
  for (const item of items) {
    if (!item.is_folder) continue
    const bucket = children.get(item.parent_id) ?? []
    bucket.push(item)
    children.set(item.parent_id, bucket)
  }
  const build = (parentId: number | null): FolderOption[] =>
    (children.get(parentId) ?? []).map(item => {
      const kids = build(item.id)
      return { value: item.id, key: item.id, title: item.title, children: kids.length > 0 ? kids : undefined }
    })
  return build(null)
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const mb = bytes / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`
}

export default function MoveDocumentModal({
  open, workspaceId, documentIds, summary, onClose, onMoved,
}: MoveDocumentModalProps) {
  const { message } = App.useApp()
  const [targetId, setTargetId] = useState<number | null>(null)
  const [targetParentId, setTargetParentId] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const targetsQuery = useQuery({
    queryKey: ['doc-move-targets', workspaceId],
    queryFn: () => documentsApi.moveTargets(workspaceId),
    enabled: open,
    staleTime: 0,
  })
  const targets = useMemo(() => targetsQuery.data?.items ?? [], [targetsQuery.data])
  const selected: DocumentMoveTarget | undefined = targets.find(item => item.id === targetId)

  const treeQuery = useQuery({
    queryKey: ['documents', targetId, 'tree'],
    queryFn: () => documentsApi.tree(targetId as number),
    enabled: open && targetId !== null,
  })
  const folderTree = useMemo(
    () => folderNodes((treeQuery.data ?? []) as Array<{ id: number; title: string; is_folder: boolean; parent_id: number | null }>),
    [treeQuery.data],
  )

  // 打开时重置选择；源工作区变化同样重置
  useEffect(() => {
    if (!open) return
    setTargetId(null)
    setTargetParentId(null)
  }, [open, workspaceId])

  const submit = async () => {
    if (targetId === null) {
      message.warning('请选择目标工作区')
      return
    }
    setSubmitting(true)
    try {
      const result = await documentsApi.moveToWorkspace(workspaceId, {
        document_ids: documentIds,
        target_workspace_id: targetId,
        parent_id: targetParentId,
      })
      const parts = [`已移动 ${result.moved_nodes} 个文档`]
      if (result.moved_files > 0) parts.push(`${result.moved_files} 个文件`)
      if (result.missing_files.length > 0) parts.push(`${result.missing_files.length} 个文件缺失`)
      message.success(parts.join('、'))
      onMoved?.(result.target_workspace_id)
      onClose()
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      message.error(detail ? `移动失败：${detail}` : '移动失败')
    } finally {
      setSubmitting(false)
    }
  }

  const noTargets = !targetsQuery.isLoading && targets.length === 0

  return (
    <Modal
      title="移动到工作区"
      open={open}
      onCancel={onClose}
      onOk={() => void submit()}
      okText="移动"
      cancelText="取消"
      okButtonProps={{ disabled: noTargets || targetId === null }}
      confirmLoading={submitting}
      destroyOnHidden
      data-testid="move-document-modal"
    >
      <div data-testid="move-document-body" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--cn-space-sm)' }}>
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
          {summary ?? `将移动 ${documentIds.length} 项（文件夹会连同其中的文档一起移动）`}
        </Text>

        {targetsQuery.isLoading ? (
          <Spin size="small" />
        ) : targets.length === 0 ? (
          <Alert
            type="info"
            showIcon
            data-testid="move-document-empty"
            message="没有可移动的目标工作区"
            description="目标工作区需要「你是编辑者及以上」且已启用文档模块。"
          />
        ) : (
          <>
            <Select
              data-testid="move-document-target"
              placeholder="选择目标工作区"
              value={targetId ?? undefined}
              onChange={value => {
                setTargetId(value)
                setTargetParentId(null)
              }}
              optionFilterProp="label"
              showSearch
              options={targets.map(target => ({
                value: target.id,
                label: `${target.name}（剩余 ${formatBytes(target.remaining_bytes)}）`,
              }))}
            />
            <TreeSelect
              data-testid="move-document-parent"
              placeholder="目标位置：根目录（可选文件夹）"
              allowClear
              showSearch
              treeDefaultExpandAll
              value={targetParentId ?? undefined}
              onChange={value => setTargetParentId(value ?? null)}
              treeData={folderTree}
              disabled={targetId === null || treeQuery.isLoading}
            />
          </>
        )}

        <Alert
          type="warning"
          showIcon
          data-testid="move-document-impact"
          message="移动后的影响"
          description={(
            <ul style={{ margin: 0, paddingInlineStart: 'var(--cn-space-lg)', fontSize: 'var(--cn-text-xs)' }}>
              <li>源工作区成员将不再能访问这些文档（含目录树、检索、版本与导出）。</li>
              <li>版本历史、站内图片、文档问题讨论、待审修改申请一并迁移。</li>
              <li>访客分享链接<Text strong>继续有效</Text>，仍按文档的发布状态与可见性判定。</li>
              <li><code>[[双链]]</code> 与 <code>{'{{table:…}}'}</code> 引用属于工作区语义，移动后<Text strong>不会自动修复</Text>。</li>
            </ul>
          )}
        />

        {selected && (
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }} data-testid="move-document-quota">
            目标工作区配额 {formatBytes(selected.quota_bytes)}，已用 {formatBytes(selected.used_bytes)}，
            剩余 {formatBytes(selected.remaining_bytes)}
            {selected.remaining_bytes <= 0 && <Tag color="red" style={{ marginInlineStart: 8 }}>空间不足</Tag>}
          </Text>
        )}
      </div>
    </Modal>
  )
}

/** 供调用方做小型确认文案：`共 N 项`（含文件夹时额外说明） */
export function moveSummary(count: number, folders = 0): string {
  const items = [`共 ${count} 项`]
  if (folders > 0) items.push(`含 ${folders} 个文件夹（连同其中文档一起移动）`)
  return items.join('，')
}
