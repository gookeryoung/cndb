/**
 * 流水线规则版本历史抽屉（ADR 0114 C9）.
 *
 * 列表（版本号 / 类型 / 时间 / 备注）→ 单版原文 → 任选两版 DIFF → editor 可恢复。
 * 交互与视觉复用设计端版本抽屉的 `cn-dsl-version-*` 样式与 `DocumentDiffView`，
 * diff 由后端 `core.textdiff` 产出，前端不在本地复算。
 */

import { useEffect, useState } from 'react'
import { App as AntApp, Button, Drawer, Empty, Popconfirm, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { RollbackOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { pipelinesApi } from '@/api'
import type { PipelineVersionChangeType, PipelineWorkflow } from '@/api'
import DocumentDiffView from '@/components/DiffView/DocumentDiffView'
import { formatDateTime } from '@/utils/datetime'

const { Text } = Typography

/** 版本类型展示口径（本地定义，不跨页面 import 设计模块常量） */
const VERSION_TYPE_LABEL: Record<PipelineVersionChangeType, string> = {
  manual: '主动保存',
  rollback: '版本恢复',
}

const VERSION_TYPE_COLOR: Record<PipelineVersionChangeType, string> = {
  manual: 'blue',
  rollback: 'orange',
}

interface PipelineVersionsDrawerProps {
  wid: number | string
  /** 目标规则（null = 抽屉关闭） */
  workflow: PipelineWorkflow | null
  open: boolean
  /** editor 才显示恢复入口（viewer 只读） */
  canRestore: boolean
  onClose: () => void
}

export default function PipelineVersionsDrawer({
  wid, workflow, open, canRestore, onClose,
}: PipelineVersionsDrawerProps) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [viewing, setViewing] = useState<number | null>(null)
  const [diffBase, setDiffBase] = useState<number | null>(null)
  const [diffHead, setDiffHead] = useState<number | null>(null)

  // 关闭或切换规则时回到列表并清空对比选择
  useEffect(() => {
    if (!open || !workflow) {
      setViewing(null)
      setDiffBase(null)
      setDiffHead(null)
    }
  }, [open, workflow])

  const workflowId = workflow?.id

  const { data: versions = [], isLoading } = useQuery({
    queryKey: ['pipelines', wid, 'versions', workflowId],
    queryFn: () => pipelinesApi.listVersions(wid, workflowId as number),
    enabled: open && workflowId != null,
  })

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['pipelines', wid, 'versions', workflowId, viewing],
    queryFn: () => pipelinesApi.getVersion(wid, workflowId as number, viewing as number),
    enabled: open && workflowId != null && viewing != null,
  })

  const { data: versionDiff, isLoading: diffLoading } = useQuery({
    queryKey: ['pipelines', wid, 'versions', workflowId, 'diff', diffBase, diffHead],
    queryFn: () => pipelinesApi.getVersionDiff(wid, workflowId as number, {
      base: diffBase as number,
      head: diffHead as number,
    }),
    enabled: open && workflowId != null && diffBase != null && diffHead != null,
  })

  const versionOptions = versions.map(item => ({ value: item.version_number, label: `v${item.version_number}` }))

  /** 选中一版：目标 = 本版，基准默认上一版（不存在则本版） */
  const openVersion = (versionNumber: number) => {
    setViewing(versionNumber)
    setDiffHead(versionNumber)
    setDiffBase(versions.some(item => item.version_number === versionNumber - 1) ? versionNumber - 1 : versionNumber)
  }

  const restore = useMutation({
    mutationFn: (versionNumber: number) => pipelinesApi.restoreVersion(wid, workflowId as number, versionNumber),
    onSuccess: (_, versionNumber) => {
      message.success(`已恢复到 v${versionNumber}，并保存为新版本`)
      queryClient.invalidateQueries({ queryKey: ['pipelines', wid] })
      setViewing(null)
      setDiffBase(null)
      setDiffHead(null)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '恢复失败'),
  })

  const viewingItem = versions.find(item => item.version_number === viewing) ?? null

  return (
    <Drawer
      title={viewing != null
        ? `版本回看：v${viewing}`
        : `版本历史${workflow ? `：${workflow.name}` : ''}（${versions.length}）`}
      open={open}
      size={460}
      onClose={onClose}
      footer={viewing != null && canRestore ? (
        <Space>
          <Popconfirm
            title={`以 v${viewing} 原文重新编译并保存为新版本？`}
            onConfirm={() => restore.mutate(viewing)}
          >
            <Button
              type="primary"
              danger
              icon={<RollbackOutlined />}
              loading={restore.isPending}
              data-testid="pipeline-version-restore"
            >
              恢复此版本
            </Button>
          </Popconfirm>
          <Button onClick={() => setViewing(null)}>返回列表</Button>
        </Space>
      ) : null}
    >
      {viewing == null ? (
        isLoading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : versions.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本（每次保存后自动记录一版）" />
        ) : (
          <div className="cn-dsl-version-list" data-testid="pipeline-version-list">
            {versions.map(item => (
              <Button
                key={item.version_number}
                type="text"
                block
                className="cn-dsl-version-row"
                data-testid={`pipeline-version-row-${item.version_number}`}
                onClick={() => openVersion(item.version_number)}
              >
                <Tag color={VERSION_TYPE_COLOR[item.change_type] ?? 'default'}>
                  {VERSION_TYPE_LABEL[item.change_type] ?? item.change_type}
                </Tag>
                <span className="cn-dsl-version-text">
                  v{item.version_number}
                  {item.comment ? ` · ${item.comment}` : ''}
                </span>
                <Text type="secondary" className="cn-dsl-version-time">
                  {formatDateTime(item.created_at)}
                </Text>
              </Button>
            ))}
          </div>
        )
      ) : (
        <>
          <Space size={8} wrap style={{ marginBottom: 8 }}>
            <Tag>第 {viewing} 版</Tag>
            {viewingItem && (
              <Tag color={VERSION_TYPE_COLOR[viewingItem.change_type] ?? 'default'}>
                {VERSION_TYPE_LABEL[viewingItem.change_type] ?? viewingItem.change_type}
              </Tag>
            )}
            <Text type="secondary">
              {formatDateTime(detail?.created_at ?? viewingItem?.created_at)}
            </Text>
          </Space>
          {detail?.comment && <Text type="secondary">备注：{detail.comment}</Text>}
          <div className="cn-dsl-diff-controls">
            <Select
              size="small"
              value={diffBase ?? undefined}
              options={versionOptions}
              aria-label="对比基准版本"
              data-testid="pipeline-diff-base"
              onChange={setDiffBase}
            />
            <Text type="secondary">→</Text>
            <Select
              size="small"
              value={diffHead ?? undefined}
              options={versionOptions}
              aria-label="对比目标版本"
              data-testid="pipeline-diff-head"
              onChange={setDiffHead}
            />
          </div>
          {diffLoading ? (
            <Skeleton active paragraph={{ rows: 4 }} />
          ) : (
            <div data-testid="pipeline-version-diff">
              <DocumentDiffView
                diff={versionDiff?.diff ?? ''}
                baseLabel={diffBase != null ? `v${diffBase}` : undefined}
                headLabel={diffHead != null ? `v${diffHead}` : undefined}
              />
            </div>
          )}
          {detailLoading ? (
            <Skeleton active />
          ) : (
            <pre data-testid="pipeline-version-content" className="cn-dsl-version-pre">
              {detail?.content ?? ''}
            </pre>
          )}
        </>
      )}
    </Drawer>
  )
}
