/** 采集运行详情抽屉：运行摘要 + 轮次时间线 + 失败诊断 / 复核续跑 / 取消（ADR 0085 §10）
 *
 * 轮次时间线回答四个问题：这轮用了什么检索式、新增多少、扩展词是什么、为什么停。
 * 诊断与续跑都是显式按钮动作，不做自动轮询（同步执行模型下没有后台任务）。
 */

import { useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, Empty, Input, Space, Spin, Tag, Timeline, Typography,
} from 'antd'
import { BulbOutlined, CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { acquisitionApi } from '@/api/acquisition'
import type { AcquisitionRound, AcquisitionRun } from '@/api/acquisition'

const { Text, Paragraph } = Typography

const STATUS_META: Record<string, { color: string; label: string }> = {
  running: { color: 'blue', label: '运行中' },
  awaiting_review: { color: 'gold', label: '待复核' },
  success: { color: 'green', label: '成功' },
  partial: { color: 'orange', label: '部分成功' },
  failed: { color: 'red', label: '失败' },
  cancelled: { color: 'default', label: '已取消' },
}

const STOP_LABEL: Record<string, string> = {
  empty_round: '空轮（没有新内容）',
  min_new: '未达最小新增',
  budget: '预算触顶',
  max_rounds: '达到最大轮数',
}

interface Props {
  open: boolean
  wid: string
  runId: number | null
  onClose: () => void
}

function RoundItem({ round }: { round: AcquisitionRound }) {
  const stats = (round.stats ?? {}) as Record<string, unknown>
  return (
    <Timeline.Item color={round.status === 'success' ? 'green' : round.status === 'failed' ? 'red' : 'orange'}>
      <Space orientation="vertical" size={2} style={{ width: '100%' }}>
        <Space size="small" wrap>
          <Text strong>第 {round.round_no} 轮</Text>
          <Tag>{round.new_items} 条新增</Tag>
          {round.stop_reason && <Tag color="purple">{STOP_LABEL[round.stop_reason] ?? round.stop_reason}</Tag>}
          {round.review_state === 'pending' && <Tag color="gold">等待复核</Tag>}
          <Text type="secondary">{round.duration_ms} ms</Text>
        </Space>
        <Text code style={{ fontSize: 12 }}>{round.query}</Text>
        <Text type="secondary">
          抓取 {String(stats.total_collected ?? 0)} → 去重 {String(stats.after_dedup ?? 0)} → 命中{' '}
          {String(stats.after_filter ?? 0)}
        </Text>
        {round.top_keywords.length > 0 && (
          <Space size={4} wrap>
            {round.top_keywords.map(item => (
              <Tag key={String(item.term)} color={item.source === 'llm' ? 'blue' : item.source === 'user' ? 'green' : 'default'}>
                {String(item.term)}
                {item.source === 'llm' ? ' · 模型' : item.source === 'user' ? ' · 我调的' : ''}
                {item.dropped ? '（已弃用）' : ''}
              </Tag>
            ))}
          </Space>
        )}
        {round.next_query && round.next_query !== round.query && (
          <Text type="secondary" style={{ fontSize: 12 }}>下一轮：{round.next_query}</Text>
        )}
        {round.error_message && <Text type="danger">{round.error_message}</Text>}
      </Space>
    </Timeline.Item>
  )
}

export default function RunDetail({ open, wid, runId, onClose }: Props) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [diagnosis, setDiagnosis] = useState('')
  const [keywords, setKeywords] = useState('')

  const detail = useQuery({
    queryKey: ['acquisition', wid, 'run', runId],
    queryFn: () => acquisitionApi.runDetail(wid, runId as number),
    enabled: open && runId !== null,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['acquisition', wid] })

  const diagnoseMutation = useMutation({
    mutationFn: () => acquisitionApi.diagnose(wid, runId as number),
    onSuccess: data => setDiagnosis(data.text),
    onError: (error: Error) => message.error(error.message),
  })

  const resumeMutation = useMutation({
    mutationFn: () => {
      const terms = keywords.split(/[\s,，]+/).map(item => item.trim()).filter(Boolean)
      return acquisitionApi.resume(wid, runId as number, terms.length ? { keywords: terms } : {})
    },
    onSuccess: () => {
      message.success('已继续下一轮')
      refresh()
      detail.refetch()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const cancelMutation = useMutation({
    mutationFn: () => acquisitionApi.cancel(wid, runId as number),
    onSuccess: () => {
      message.info('已请求取消：本轮结束后停止')
      refresh()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const run: AcquisitionRun | undefined = detail.data?.run
  const rounds = detail.data?.rounds ?? []
  const statusMeta = STATUS_META[run?.status ?? ''] ?? { color: 'default', label: run?.status ?? '-' }

  return (
    <Drawer open={open} size={640} onClose={onClose} title={run ? `运行 #${run.id}` : '运行详情'}>
      {detail.isLoading && <Spin />}
      {detail.isError && <Alert type="error" message="运行记录加载失败" />}
      {run && (
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
            <Tag>{run.trigger === 'scheduler' ? '定时触发' : run.trigger === 'cli' ? 'CLI' : '手动'}</Tag>
            <Text type="secondary">{run.round_count} 轮 · {run.duration_ms} ms</Text>
          </Space>
          <Text type="secondary">{run.progress_message}</Text>
          <Space wrap size="large">
            <Text>抓取 {run.fetched}</Text>
            <Text>新增 {run.inserted}</Text>
            <Text>更新 {run.updated}</Text>
            <Text>跳过 {run.skipped}</Text>
            <Text>文档 +{run.docs_created}/~{run.docs_updated}</Text>
            <Text type="secondary">预算 {run.budget_used?.requests ?? 0} 次请求</Text>
          </Space>
          {run.error_message && <Alert type="error" showIcon message={run.error_message} />}
          {(run.detail?.report as { text?: string } | undefined)?.text && (
            <Alert
              type="info"
              showIcon
              message="运行报告"
              description={(run.detail.report as { text: string }).text}
            />
          )}

          <Space wrap>
            <Button
              size="small"
              icon={<BulbOutlined />}
              loading={diagnoseMutation.isPending}
              onClick={() => diagnoseMutation.mutate()}
            >
              为什么这轮没结果
            </Button>
            {run.status === 'awaiting_review' && (
              <>
                <Input
                  size="small"
                  style={{ width: 220 }}
                  value={keywords}
                  onChange={event => setKeywords(event.target.value)}
                  placeholder="可选：调整扩展词（空格分隔）"
                />
                <Button size="small" type="primary" icon={<ReloadOutlined />} loading={resumeMutation.isPending} onClick={() => resumeMutation.mutate()}>
                  继续下一轮
                </Button>
              </>
            )}
            {run.status === 'running' && (
              <Button size="small" danger icon={<CloseCircleOutlined />} loading={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
                取消
              </Button>
            )}
          </Space>

          {diagnosis && (
            <Alert type="warning" showIcon closable message="诊断建议" description={<Paragraph style={{ marginBottom: 0 }}>{diagnosis}</Paragraph>} onClose={() => setDiagnosis('')} />
          )}

          <div>
            <Text strong>轮次时间线</Text>
            {rounds.length === 0
              ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有轮次记录" />
              : <Timeline style={{ marginTop: 12 }}>{rounds.map(round => <RoundItem key={round.id} round={round} />)}</Timeline>}
          </div>
        </Space>
      )}
    </Drawer>
  )
}
