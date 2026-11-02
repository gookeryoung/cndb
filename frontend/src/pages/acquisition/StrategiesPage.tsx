/** 采集策略页 — 工作区级「智能采集」（ADR 0085 §10）
 *
 * - 列表：名称 / 渠道数 / 落点 / 调度 / 最近状态 + 启停、运行、历史、编辑、删除
 * - 编辑抽屉：四段式规则 + 自然语言草案 + 预览（StrategyEditor）
 * - 运行抽屉：运行摘要 + 轮次时间线 + 诊断 / 续跑 / 取消（RunDetail）
 *
 * 权限：读 VIEWER、写 / 运行 EDITOR（后端校验）；本页不做前端权限分支，越权时按钮返回 403。
 */

import { useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Empty, Popconfirm, Space, Spin, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, HistoryOutlined, PauseCircleOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { tableApi } from '@/api'
import { documentsApi } from '@/api/documents'
import { acquisitionApi } from '@/api/acquisition'
import type { AcquisitionChannelOption, AcquisitionStrategy } from '@/api/acquisition'
import StrategyEditor from './StrategyEditor'
import RunDetail from './RunDetail'

const { Title, Text } = Typography

const STATUS_META: Record<string, { color: string; label: string }> = {
  running: { color: 'blue', label: '运行中' },
  awaiting_review: { color: 'gold', label: '待复核' },
  success: { color: 'green', label: '成功' },
  partial: { color: 'orange', label: '部分成功' },
  failed: { color: 'red', label: '失败' },
  cancelled: { color: 'default', label: '已取消' },
}

const REVIEW_LABEL: Record<string, string> = {
  auto: '确定性',
  llm: '模型判断',
  manual: '每轮确认',
}

function scheduleLabel(schedule: Record<string, unknown>): string {
  const mode = String(schedule.mode || 'manual')
  if (mode === 'daily') return `每天 ${String(schedule.at || '')}`
  if (mode === 'interval') return `每 ${Number(schedule.seconds || 0) / 60} 分钟`
  if (mode === 'cron') return `cron ${String(schedule.expr || '')}`
  return '手动'
}

function targetLabel(strategy: AcquisitionStrategy, tableName: (id?: number) => string): string {
  const parts = strategy.targets.map(target => (
    target.kind === 'table' ? `表：${tableName(target.table_id)}` : '文档'
  ))
  return parts.join(' / ') || '—'
}

export default function StrategiesPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<AcquisitionStrategy | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [runId, setRunId] = useState<number | null>(null)

  const strategiesQuery = useQuery({
    queryKey: ['acquisition', wid, 'strategies'],
    queryFn: () => acquisitionApi.listStrategies(wid),
    enabled: !!wid,
  })
  const channelsQuery = useQuery({
    queryKey: ['acquisition', wid, 'channels'],
    queryFn: () => acquisitionApi.channels(wid),
    enabled: !!wid,
  })
  const tablesQuery = useQuery({
    queryKey: ['tables', wid],
    queryFn: () => tableApi.list(wid),
    enabled: !!wid,
  })
  const treeQuery = useQuery({
    queryKey: ['documents', wid, 'tree'],
    queryFn: () => documentsApi.tree(wid),
    enabled: !!wid,
  })

  const strategies = strategiesQuery.data?.strategies ?? []
  const channels: AcquisitionChannelOption[] = channelsQuery.data?.channels ?? []
  const tables = useMemo(
    () => (tablesQuery.data ?? []).map(table => ({ id: Number(table.id), name: table.name })),
    [tablesQuery.data],
  )
  const folders = useMemo(
    () => (treeQuery.data ?? [])
      .filter(item => item.is_folder)
      .map(item => ({ id: Number(item.id), title: item.title })),
    [treeQuery.data],
  )
  const tableName = useMemo(() => {
    const map = new Map<number, string>(tables.map(table => [table.id, table.name]))
    return (id?: number) => (id ? map.get(id) ?? `#${id}` : '—')
  }, [tables])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['acquisition', wid] })

  const toggleMutation = useMutation({
    mutationFn: (strategy: AcquisitionStrategy) => (
      strategy.enabled
        ? acquisitionApi.disableStrategy(wid, strategy.id)
        : acquisitionApi.enableStrategy(wid, strategy.id)
    ),
    onSuccess: (data) => {
      message.success(data.enabled ? '已启用：定时触发生效' : '已停用')
      refresh()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const runMutation = useMutation({
    mutationFn: (strategy: AcquisitionStrategy) => acquisitionApi.run(wid, strategy.id),
    onSuccess: (run) => {
      message.success(
        run.status === 'awaiting_review' ? '本轮完成，等待你确认扩展词' : `运行完成：${run.inserted} 新增 / ${run.updated} 更新`,
      )
      setRunId(run.id)
      refresh()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (strategy: AcquisitionStrategy) => acquisitionApi.deleteStrategy(wid, strategy.id),
    onSuccess: () => {
      message.success('已删除')
      refresh()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const loading = strategiesQuery.isLoading || channelsQuery.isLoading

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }} align="center">
        <div>
          <Title level={5} style={{ marginBottom: 2 }}>智能采集</Title>
          <Text type="secondary">
            一条规则 = 渠道 + 检索式 + 筛选 + 落点 + 迭代；启用的策略会按调度自动跑，模型只做语义辅助。
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refresh()}>刷新</Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => { setEditing(null); setEditorOpen(true) }}
          >
            新建策略
          </Button>
        </Space>
      </Space>

      {strategiesQuery.isError && <Alert type="error" showIcon message="策略列表加载失败" style={{ marginBottom: 12 }} />}
      {channelsQuery.isError && (
        <Alert type="warning" showIcon message="渠道目录加载失败，新建策略时请稍后重试" style={{ marginBottom: 12 }} />
      )}

      {loading ? <Spin /> : strategies.length === 0 ? (
        <Empty description="还没有采集策略：点右上角「新建策略」开始，用「预览」确认能抓到想要的内容再启用" />
      ) : (
        <Table<AcquisitionStrategy>
          rowKey="id"
          size="middle"
          pagination={false}
          dataSource={strategies}
          columns={[
            {
              title: '策略',
              dataIndex: 'name',
              render: (_, strategy) => (
                <Space orientation="vertical" size={0}>
                  <Space size={6}>
                    <Text strong>{strategy.name}</Text>
                    <Tag color={strategy.enabled ? 'green' : 'default'}>{strategy.enabled ? '启用' : '停用'}</Tag>
                    <Tag>v{strategy.rule_version}</Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>{strategy.scope.query || '未设置检索式'}</Text>
                </Space>
              ),
            },
            {
              title: '渠道',
              dataIndex: 'scope',
              width: 220,
              render: (_, strategy) => (
                <Space size={4} wrap>
                  {(strategy.scope.channels ?? []).map(channel => (
                    <Tag key={channel}>{channel}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: '落点',
              width: 200,
              render: (_, strategy) => <Text>{targetLabel(strategy, tableName)}</Text>,
            },
            {
              title: '调度 / 复核',
              width: 180,
              render: (_, strategy) => (
                <Space orientation="vertical" size={0}>
                  <Text>{scheduleLabel(strategy.schedule)}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    复核：{REVIEW_LABEL[String(strategy.iteration.expand?.review ?? 'auto')] ?? '确定性'}
                  </Text>
                </Space>
              ),
            },
            {
              title: '最近运行',
              width: 170,
              render: (_, strategy) => {
                const meta = STATUS_META[strategy.last_status]
                return (
                  <Space orientation="vertical" size={0}>
                    {meta ? <Tag color={meta.color}>{meta.label}</Tag> : <Text type="secondary">未运行</Text>}
                    {strategy.last_run_at && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {new Date(strategy.last_run_at).toLocaleString()}
                      </Text>
                    )}
                  </Space>
                )
              },
            },
            {
              title: '操作',
              width: 240,
              render: (_, strategy) => (
                <Space size={4} wrap>
                  <Tooltip title="立即运行一次">
                    <Button size="small" icon={<PlayCircleOutlined />} loading={runMutation.isPending && runMutation.variables?.id === strategy.id} onClick={() => runMutation.mutate(strategy)}>
                      运行
                    </Button>
                  </Tooltip>
                  <Button size="small" icon={<HistoryOutlined />} onClick={() => {
                    const latest = strategy.last_run_at
                    if (!latest) { message.info('这条策略还没有运行记录'); return }
                    void acquisitionApi.runs(wid, strategy.id).then(data => {
                      if (!data.runs.length) { message.info('这条策略还没有运行记录'); return }
                      setRunId(data.runs[0].id)
                    })
                  }}>
                    历史
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => { setEditing(strategy); setEditorOpen(true) }}>
                    编辑
                  </Button>
                  <Button
                    size="small"
                    icon={strategy.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                    loading={toggleMutation.isPending && toggleMutation.variables?.id === strategy.id}
                    onClick={() => toggleMutation.mutate(strategy)}
                  >
                    {strategy.enabled ? '停用' : '启用'}
                  </Button>
                  <Popconfirm title="删除这条策略？" description="运行记录会一并删除，已采集的数据不受影响。" onConfirm={() => deleteMutation.mutate(strategy)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}

      <StrategyEditor
        open={editorOpen}
        wid={wid}
        strategy={editing}
        channels={channels}
        tables={tables}
        folders={folders}
        onClose={() => setEditorOpen(false)}
        onSaved={() => { setEditorOpen(false); refresh() }}
      />
      <RunDetail open={runId !== null} wid={wid} runId={runId} onClose={() => setRunId(null)} />
    </div>
  )
}
