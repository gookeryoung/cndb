/** 工作区生命周期（需求 0094）：阶段时间线、门禁检查、推进与模板应用. */

import { useState } from 'react'
import {
  Alert, App as AntApp, Button, Empty, List, Modal, Select, Space, Tag, Timeline, Typography,
} from 'antd'
import { CheckCircleFilled, ClockCircleOutlined, MinusCircleOutlined, RocketOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceLifecycleApi, workspaceTemplateApi } from '@/api'
import type { LifecycleStage, WorkspaceLifecycle } from '@/api'
import { formatDateTime } from '@/utils/datetime'

const { Text, Paragraph } = Typography

interface Props {
  wid: string
  /** 编辑者及以上可推进阶段 */
  canAdvance: boolean
  /** 所有者可应用 / 切换模板 */
  canManageTemplate: boolean
}

function StageChecks({ stage }: { stage: LifecycleStage }) {
  return (
    <div style={{ fontSize: 'var(--cn-text-sm)' }}>
      {stage.forms.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <Text strong>表单门禁</Text>
          <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
            {stage.forms.map(f => (
              <li key={f.key}>
                {f.satisfied
                  ? <CheckCircleFilled style={{ color: '#52c41a', marginRight: 4 }} />
                  : <MinusCircleOutlined style={{ color: '#faad14', marginRight: 4 }} />}
                {f.name}：{f.table_exists ? `${f.row_count} 条记录` : '表不存在'}
                {f.required && !f.satisfied ? <Text type="secondary">（需至少 1 条）</Text> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {stage.documents.length > 0 && (
        <div>
          <Text strong>文档门禁</Text>
          <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
            {stage.documents.map(d => (
              <li key={d.key}>
                {d.satisfied
                  ? <CheckCircleFilled style={{ color: '#52c41a', marginRight: 4 }} />
                  : <MinusCircleOutlined style={{ color: '#faad14', marginRight: 4 }} />}
                {d.title}：{d.exists ? '已创建' : '缺失'}
                {!d.required ? <Text type="secondary">（可选）</Text> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {stage.forms.length === 0 && stage.documents.length === 0 && <Text type="secondary">该阶段无门禁要求</Text>}
    </div>
  )
}

export default function WorkspaceLifecyclePanel({ wid, canAdvance, canManageTemplate }: Props) {
  const { message, modal } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [applyOpen, setApplyOpen] = useState(false)
  const [applyTemplateId, setApplyTemplateId] = useState<number | null>(null)

  const { data: lifecycle, isLoading, error } = useQuery<WorkspaceLifecycle>({
    queryKey: ['workspace-lifecycle', wid],
    queryFn: () => workspaceLifecycleApi.get(wid),
    enabled: !!wid,
    retry: false,
  })

  const { data: templates = [] } = useQuery({
    queryKey: ['workspace-templates'],
    queryFn: () => workspaceTemplateApi.list(),
    enabled: applyOpen,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['workspace-lifecycle', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspace-detail', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const advance = useMutation({
    mutationFn: (force: boolean) => workspaceLifecycleApi.advance(wid, { force, reason: force ? '门禁未通过，人工强制推进' : '' }),
    onSuccess: (state) => {
      message.success(`已推进到「${state.stages[state.current_stage_index]?.name ?? state.current_stage}」`)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '推进失败'),
  })

  const apply = useMutation({
    mutationFn: () => {
      if (!applyTemplateId) throw new Error('请选择模板')
      return workspaceLifecycleApi.apply(wid, { template_id: applyTemplateId, force: true })
    },
    onSuccess: (res) => {
      message.success(`模板已应用：新建 ${res.sync.created_tables ?? 0} 张表 / ${res.sync.created_documents ?? 0} 份文档`)
      setApplyOpen(false)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '应用模板失败'),
  })

  const onAdvance = () => {
    if (!lifecycle) return
    if (lifecycle.can_advance) {
      advance.mutate(false)
      return
    }
    modal.confirm({
      title: '门禁未通过，仍要推进？',
      content: '当前阶段的表单或必需文档尚未补齐。强制推进会把该动作写入阶段履历，建议先补齐后推进。',
      okText: '强制推进',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => advance.mutate(true),
    })
  }

  if (isLoading) return <div className="cn-state">加载中…</div>

  if (error || !lifecycle) {
    return (
      <div data-testid="workspace-lifecycle-empty">
        <Empty description="该工作区还没有使用模板">
          {canManageTemplate ? (
            <Space direction="vertical" align="center">
              <Text type="secondary">应用模板后会按模板建立表单与文档占位，已有数据不受影响。</Text>
              <Button type="primary" icon={<RocketOutlined />} onClick={() => setApplyOpen(true)}>
                选择模板
              </Button>
            </Space>
          ) : (
            <Text type="secondary">请让工作区所有者选择模板后查看流程进度。</Text>
          )}
        </Empty>
        <Modal
          title="应用工作区模板"
          open={applyOpen}
          onCancel={() => setApplyOpen(false)}
          onOk={() => apply.mutate()}
          okText="应用模板"
          confirmLoading={apply.isPending}
          okButtonProps={{ disabled: !applyTemplateId }}
        >
          <Select
            style={{ width: '100%' }}
            placeholder="选择模板"
            value={applyTemplateId ?? undefined}
            onChange={setApplyTemplateId}
            options={templates.map(t => ({ value: Number(t.id), label: `${t.name}（v${t.version}）` }))}
          />
          <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 'var(--cn-text-xs)' }}>
            增量同步：只补齐缺失的表 / 字段 / 文档占位，不删除任何已有数据。
          </Paragraph>
        </Modal>
      </div>
    )
  }

  const timelineItems = lifecycle.stages.map(stage => ({
    color: stage.is_current ? 'blue' : stage.is_completed ? 'green' : 'gray',
    dot: stage.is_completed
      ? <CheckCircleFilled />
      : stage.is_current ? <ClockCircleOutlined /> : undefined,
    children: (
      <div data-testid={`lifecycle-stage-${stage.key}`}>
        <Space wrap>
          <Text strong>阶段 {stage.order} · {stage.name}</Text>
          {stage.is_current && <Tag color="blue">当前阶段</Tag>}
          {stage.is_completed && <Tag color="green">已完成</Tag>}
          <Tag color={stage.gate_satisfied ? 'green' : 'orange'}>
            {stage.gate_satisfied ? '门禁已通过' : '门禁未通过'}
          </Tag>
        </Space>
        <div style={{ color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-sm)', margin: '2px 0 6px' }}>{stage.description || '—'}</div>
        <StageChecks stage={stage} />
      </div>
    ),
  }))

  return (
    <div data-testid="workspace-lifecycle-panel">
      <Alert
        type={lifecycle.version_mismatch ? 'warning' : 'info'}
        showIcon
        style={{ marginBottom: 12 }}
        message={`模板：${lifecycle.template_name}（v${lifecycle.template_version}${lifecycle.version_mismatch ? ` → 最新 v${lifecycle.current_version}` : ''}）`}
        description={
          lifecycle.version_mismatch
            ? '该工作区尚未同步到最新模板版本。同步只增量补齐，不删除已有数据。'
            : `共 ${lifecycle.stage_count} 个阶段，当前第 ${lifecycle.current_stage_index + 1} 阶段。`
        }
        action={canManageTemplate ? (
          <Button size="small" onClick={() => { setApplyTemplateId(Number(lifecycle.template_id)); setApplyOpen(true) }}>
            同步模板
          </Button>
        ) : undefined}
      />

      <Timeline items={timelineItems} style={{ marginTop: 18 }} />

      <Space wrap style={{ marginBottom: 14 }}>
        <Button
          type="primary"
          onClick={onAdvance}
          disabled={!canAdvance || !lifecycle.next_stage}
          loading={advance.isPending}
          data-testid="lifecycle-advance-btn"
        >
          {lifecycle.next_stage ? `推进到「${lifecycle.next_stage.name}」` : '已是最后阶段'}
        </Button>
        {!canAdvance && <Text type="secondary">仅编辑者及以上可推进阶段</Text>}
      </Space>

      <div style={{ marginTop: 8 }}>
        <Text strong>阶段履历</Text>
        {lifecycle.history.length === 0 ? (
          <div><Text type="secondary">暂无</Text></div>
        ) : (
          <List
            size="small"
            dataSource={[...lifecycle.history].reverse()}
            renderItem={item => (
              <List.Item>
                <Space wrap>
                  <Tag>{item.from ?? '—'} → {item.to}</Tag>
                  <Text type="secondary">{formatDateTime(item.at)}</Text>
                  {item.forced && <Tag color="red">强制推进</Tag>}
                  {item.reason && <Text>{item.reason}</Text>}
                </Space>
              </List.Item>
            )}
          />
        )}
      </div>

      <Modal
        title="应用 / 同步工作区模板"
        open={applyOpen}
        onCancel={() => setApplyOpen(false)}
        onOk={() => apply.mutate()}
        okText="应用模板"
        confirmLoading={apply.isPending}
        okButtonProps={{ disabled: !applyTemplateId }}
      >
        <Select
          style={{ width: '100%' }}
          placeholder="选择模板"
          value={applyTemplateId ?? undefined}
          onChange={setApplyTemplateId}
          options={templates.map(t => ({ value: Number(t.id), label: `${t.name}（v${t.version}）` }))}
        />
        <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 'var(--cn-text-xs)' }}>
          增量同步：只补齐缺失的表 / 字段 / 文档占位，不删除任何已有数据；切换模板会保留阶段履历。
        </Paragraph>
      </Modal>
    </div>
  )
}
