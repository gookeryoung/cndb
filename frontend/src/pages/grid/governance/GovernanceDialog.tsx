/** 数据治理向导 — 重复检测 → 确认合并 → 数据清洗.
 *
 * 三步向导（AntD Steps）：
 *  1. 检测配置：选择判重字段 + 归一化选项，提交 detect 任务并轮询
 *  2. 确认合并：逐组选择保留行与融合策略，提交 merge 任务
 *  3. 数据清洗：配置 4 动作（复用导入侧动作），先预览再执行
 *
 * 所有任务异步提交后通过 useQuery refetchInterval 轮询进度。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Modal, Steps, Select, Checkbox, Button, Table, Tag, Space, Alert, App as AntApp,
  Input, Empty, Typography, Popconfirm, Spin,
} from 'antd'
import { SearchOutlined, MergeCellsOutlined, ClearOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { governanceApi } from '@/api'
import type {
  Field, GovernanceTask, Survivorship,
  DetectReport, MergeReport, CleanReport,
} from '@/api'

const { Text } = Typography

/** survivorship 融合策略选项 */
const SURVIVORSHIP_OPTIONS = [
  { value: 'non_empty_first', label: '非空优先（按行序）' },
  { value: 'latest', label: '保留最新（行 ID 大）' },
  { value: 'oldest', label: '保留最旧（行 ID 小）' },
]

const CLEAN_ACTION_OPTIONS = [
  { value: 'trim_whitespace', label: '去除首尾空白' },
  { value: 'fill_null', label: '填充空值' },
  { value: 'coerce_type', label: '类型转换' },
  { value: 'drop_outliers', label: '剔除异常值' },
]

const COERCE_STRATEGIES = [
  { value: 'number', label: '转数字' },
  { value: 'date', label: '转日期' },
  { value: 'text', label: '转文本' },
  { value: 'boolean', label: '转布尔' },
]

interface Props {
  open: boolean
  wid: string
  tid: string
  fields: Field[]
  onClose: () => void
  /** 合并/清洗执行成功后通知父组件刷新行数据 */
  onDataChanged?: () => void
}

/** 轮询治理任务直到终态 */
function useGovernanceTask(wid: string, tid: string, taskId: number | null) {
  return useQuery({
    queryKey: ['governance-task', wid, tid, taskId],
    queryFn: () => governanceApi.task(wid, tid, taskId!),
    enabled: taskId != null,
    refetchInterval: (q) => {
      const st = q.state.data?.status
      return st === 'pending' || st === 'running' ? 800 : false
    },
  })
}

/** 任务终态为 done 时拉取解析后的报告 */
function useGovernanceReport(wid: string, tid: string, task: GovernanceTask | undefined) {
  const done = task?.status === 'done'
  return useQuery({
    queryKey: ['governance-report', wid, tid, task?.id],
    queryFn: () => governanceApi.report(wid, tid, task!.id),
    enabled: done,
  })
}

export default function GovernanceDialog({ open, wid, tid, fields, onClose, onDataChanged }: Props) {
  const { message } = AntApp.useApp()
  const [step, setStep] = useState(0)

  // ── 步骤 1：检测配置 ──
  const [matchFields, setMatchFields] = useState<string[]>([])
  const [ignoreCase, setIgnoreCase] = useState(false)
  const [ignoreWhitespace, setIgnoreWhitespace] = useState(false)
  const [detectTaskId, setDetectTaskId] = useState<number | null>(null)

  // ── 步骤 2：合并确认 ──
  const [survivors, setSurvivors] = useState<Record<number, number>>({})
  const [survivorship, setSurvivorship] = useState<Survivorship>('non_empty_first')
  const [mergeTaskId, setMergeTaskId] = useState<number | null>(null)

  // ── 步骤 3：清洗配置 ──
  const [cleanActions, setCleanActions] = useState<Array<{
    action: 'trim_whitespace' | 'fill_null' | 'coerce_type' | 'drop_outliers'
    column: string
    strategy?: string | null
    fill_value?: string | null
  }>>([])
  const [cleanTaskId, setCleanTaskId] = useState<number | null>(null)
  const [previewDone, setPreviewDone] = useState(false)

  const detectTask = useGovernanceTask(wid, tid, detectTaskId)
  const mergeTask = useGovernanceTask(wid, tid, mergeTaskId)
  const cleanTask = useGovernanceTask(wid, tid, cleanTaskId)
  const detectReport = useGovernanceReport(wid, tid, detectTask.data) as { data?: DetectReport | null }
  const mergeReport = useGovernanceReport(wid, tid, mergeTask.data) as { data?: MergeReport | null }
  const cleanReport = useGovernanceReport(wid, tid, cleanTask.data) as { data?: CleanReport | null }
  // 打开时重置向导
  useEffect(() => {
    if (open) {
      setStep(0)
      setMatchFields([])
      setDetectTaskId(null)
      setMergeTaskId(null)
      setCleanTaskId(null)
      setCleanActions([])
      setPreviewDone(false)
      setSurvivors({})
    }
  }, [open])

  const columnOptions = useMemo(
    () => fields.map(f => ({ value: f.name, label: f.name })),
    [fields],
  )

  const startDetect = () => {
    governanceApi.detect(wid, tid, {
      match_fields: matchFields,
      ignore_case: ignoreCase,
      ignore_whitespace: ignoreWhitespace,
    }).then(t => setDetectTaskId(t.id))
      .catch(err => message.error(err instanceof Error ? err.message : '创建检测任务失败'))
  }

  const submitMerge = () => {
    const report = detectReport.data
    if (!report) return
    const groups = report.groups.map((g, i) => ({
      member_row_ids: g.member_row_ids,
      survivor_row_id: survivors[i] ?? g.member_row_ids[0],
      survivorship,
    }))
    governanceApi.merge(wid, tid, {
      match_fields: matchFields,
      ignore_case: ignoreCase,
      ignore_whitespace: ignoreWhitespace,
      groups,
    }).then(t => setMergeTaskId(t.id))
      .catch(err => message.error(err instanceof Error ? err.message : '创建合并任务失败'))
  }

  const runClean = (preview: boolean) => {
    const actions = cleanActions.map(a => ({
      action: a.action,
      column: a.column,
      strategy: a.strategy ?? null,
      on_fail: 'nullify' as const,
      ...(a.action === 'fill_null' && a.fill_value != null && a.fill_value !== ''
        ? { fill_value: a.fill_value }
        : {}),
    }))
    if (actions.length === 0) {
      message.warning('请先添加清洗动作')
      return
    }
    governanceApi.clean(wid, tid, { actions, preview })
      .then(t => {
        setCleanTaskId(t.id)
        if (preview) setPreviewDone(false)
      })
      .catch(err => message.error(err instanceof Error ? err.message : '创建清洗任务失败'))
  }

  // 任务完成时的提示与刷新
  useEffect(() => {
    if (mergeTask.data?.status === 'done') {
      message.success('合并完成')
      onDataChanged?.()
    }
  }, [mergeTask.data?.status])
  useEffect(() => {
    if (cleanTask.data?.status === 'done') {
      if (cleanTask.data.kind === 'clean' && (cleanTask.data.config as { preview?: boolean })?.preview) {
        setPreviewDone(true)
      } else {
        message.success('清洗完成')
        onDataChanged?.()
      }
    }
  }, [cleanTask.data?.status])

  const taskFailed = (t: GovernanceTask | undefined) => t?.status === 'failed' ? t.error_message : null

  // ── 步骤 1 内容 ──
  const detectStep = (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">选择用于判重的字段（值完全相同的行归为一组）：</Text>
      </div>
      <Select
        mode="multiple"
        style={{ width: '100%' }}
        placeholder="选择判重字段"
        value={matchFields}
        onChange={setMatchFields}
        options={columnOptions}
        data-testid="governance-match-fields"
      />
      <Space style={{ marginTop: 12 }}>
        <Checkbox checked={ignoreCase} onChange={e => setIgnoreCase(e.target.checked)}>忽略大小写</Checkbox>
        <Checkbox checked={ignoreWhitespace} onChange={e => setIgnoreWhitespace(e.target.checked)}>忽略首尾空白</Checkbox>
      </Space>
      <div style={{ marginTop: 16 }}>
        {detectTaskId == null ? (
          <Button
            type="primary"
            icon={<SearchOutlined />}
            disabled={matchFields.length === 0}
            loading={detectTask.isFetching && !detectTask.data}
            onClick={startDetect}
          >
            开始检测
          </Button>
        ) : detectTask.data?.status === 'done' ? (
          <Alert
            type="success"
            showIcon
            message={`检测完成：共 ${detectReport.data?.group_count ?? 0} 组重复（${detectReport.data?.duplicate_row_count ?? 0} 行）`}
          />
        ) : detectTask.data?.status === 'failed' ? (
          <Alert type="error" showIcon message="检测失败" description={taskFailed(detectTask.data)} />
        ) : (
          <Space><Spin size="small" /><Text type="secondary">正在检测...</Text></Space>
        )}
      </div>
      {detectTask.data?.status === 'done' && (
        <div style={{ marginTop: 16 }}>
          <Button type="primary" disabled={(detectReport.data?.group_count ?? 0) === 0} onClick={() => setStep(1)}>
            下一步：确认合并
          </Button>
          {(detectReport.data?.group_count ?? 0) === 0 && (
            <Text type="secondary" style={{ marginLeft: 8 }}>未发现重复行，无需合并</Text>
          )}
        </div>
      )}
    </div>
  )

  // ── 步骤 2 内容 ──
  const mergeStep = (() => {
    const report = detectReport.data
    if (!report) return <Empty description="暂无检测报告" />
    return (
      <div>
        <div style={{ marginBottom: 8 }}>
          <Text type="secondary">每组选择要保留的行；其余行合并进保留行后移入回收站（可恢复）。link 引用会自动迁移到保留行。</Text>
        </div>
        <Select
          style={{ width: 240, marginBottom: 12 }}
          value={survivorship}
          onChange={v => setSurvivorship(v)}
          options={SURVIVORSHIP_OPTIONS}
        />
        <Table
          size="small"
          rowKey={(_, i) => String(i)}
          dataSource={report.groups}
          pagination={false}
          columns={[
            {
              title: '判重键值',
              dataIndex: 'match_key_values',
              render: (v: Record<string, unknown>) => (
                <Space size={4} wrap>
                  {Object.entries(v).map(([k, val]) => (
                    <Tag key={k}>{k}: {String(val ?? '')}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: '成员行',
              dataIndex: 'member_row_ids',
              width: 120,
              render: (ids: number[]) => <Text code>{ids.join(', ')}</Text>,
            },
            {
              title: '保留行',
              dataIndex: 'survivor',
              width: 140,
              render: (_: unknown, g: { member_row_ids: number[] }, i: number) => (
                <Select
                  size="small"
                  style={{ width: 120 }}
                  value={survivors[i] ?? g.member_row_ids[0]}
                  onChange={v => setSurvivors(s => ({ ...s, [i]: v }))}
                  options={g.member_row_ids.map(id => ({ value: id, label: `行 ${id}` }))}
                />
              ),
            },
          ]}
        />
        <div style={{ marginTop: 16 }}>
          {mergeTaskId == null ? (
            <Popconfirm
              title="确认合并所选分组？"
              description="合并操作会改写保留行字段并把其余行移入回收站，操作将记入审计日志。"
              okText="确认合并"
              cancelText="取消"
              onConfirm={submitMerge}
            >
              <Button type="primary" icon={<MergeCellsOutlined />}>提交合并</Button>
            </Popconfirm>
          ) : mergeTask.data?.status === 'done' ? (
            <Alert
              type="success"
              showIcon
              message={`合并完成：${mergeReport.data?.merged_count ?? 0} 组已合并`}
            />
          ) : mergeTask.data?.status === 'failed' ? (
            <Alert type="error" showIcon message="合并失败" description={taskFailed(mergeTask.data)} />
          ) : (
            <Space><Spin size="small" /><Text type="secondary">正在合并...</Text></Space>
          )}
        </div>
        {mergeTask.data?.status === 'done' && (
          <div style={{ marginTop: 16 }}>
            <Button type="primary" onClick={() => setStep(2)}>下一步：数据清洗</Button>
          </div>
        )}
      </div>
    )
  })()

  // ── 步骤 3 内容 ──
  const cleanStep = (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">配置清洗动作（复用导入侧动作），先预览受影响行数，确认后执行。</Text>
      </div>
      {cleanActions.map((a, i) => (
        <Space key={i} style={{ display: 'flex', marginBottom: 8 }} wrap>
          <Select
            style={{ width: 150 }}
            value={a.action}
            onChange={v => setCleanActions(arr => arr.map((x, j) => j === i ? { ...x, action: v, strategy: null } : x))}
            options={CLEAN_ACTION_OPTIONS}
          />
          <Select
            style={{ width: 140 }}
            placeholder="目标列"
            value={a.column}
            onChange={v => setCleanActions(arr => arr.map((x, j) => j === i ? { ...x, column: v } : x))}
            options={columnOptions}
          />
          {a.action === 'fill_null' && (
            <Input
              style={{ width: 140 }}
              placeholder="填充值（可选）"
              value={a.fill_value ?? ''}
              onChange={e => setCleanActions(arr => arr.map((x, j) => j === i ? { ...x, fill_value: e.target.value } : x))}
            />
          )}
          {a.action === 'coerce_type' && (
            <Select
              style={{ width: 120 }}
              placeholder="目标类型"
              value={a.strategy ?? undefined}
              onChange={v => setCleanActions(arr => arr.map((x, j) => j === i ? { ...x, strategy: v } : x))}
              options={COERCE_STRATEGIES}
              allowClear
            />
          )}
          {a.action === 'drop_outliers' && (
            <Tag>iqr（四分位距）</Tag>
          )}
          <Button
            size="small"
            type="text"
            danger
            onClick={() => setCleanActions(arr => arr.filter((_, j) => j !== i))}
          >
            移除
          </Button>
        </Space>
      ))}
      <Button
        style={{ marginBottom: 12 }}
        icon={<ClearOutlined />}
        onClick={() => setCleanActions(arr => [...arr, { action: 'trim_whitespace', column: fields[0]?.name ?? '' }])}
      >
        添加动作
      </Button>

      <div>
        <Space>
          <Button
            loading={cleanTask.isFetching && !cleanTask.data && cleanTaskId != null}
            disabled={cleanActions.length === 0}
            onClick={() => runClean(true)}
          >
            预览
          </Button>
          {previewDone && (
            <Popconfirm
              title="确认执行清洗？"
              description="将按预览结果就地改写行数据，操作记入审计日志。"
              okText="执行"
              cancelText="取消"
              onConfirm={() => runClean(false)}
            >
              <Button type="primary" danger>执行清洗</Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      {cleanTask.data?.status === 'failed' && (
        <Alert style={{ marginTop: 12 }} type="error" showIcon message="清洗失败" description={taskFailed(cleanTask.data)} />
      )}

      {cleanReport.data && (
        <div style={{ marginTop: 16 }}>
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            dataSource={cleanReport.data.affected}
            pagination={false}
            columns={[
              { title: '动作', dataIndex: 'action', width: 140 },
              { title: '列', dataIndex: 'column', width: 120 },
              { title: '策略', dataIndex: 'strategy', width: 100, render: (v: string | null) => v ?? '—' },
              { title: '受影响行数', dataIndex: 'affected_rows', width: 100 },
            ]}
            locale={{ emptyText: '无受影响行' }}
          />
          {cleanReport.data.mode === 'preview' && (
            <Alert style={{ marginTop: 8 }} type="info" showIcon message="预览模式：以上为将受影响的行数，未写入任何数据" />
          )}
        </div>
      )}
    </div>
  )

  return (
    <Modal
      title="数据治理"
      open={open}
      onCancel={onClose}
      width={760}
      className="governance-modal"
      destroyOnHidden
      footer={null}
    >
      <Steps
        size="small"
        current={step}
        items={[{ title: '重复检测' }, { title: '确认合并' }, { title: '数据清洗' }]}
        style={{ marginBottom: 20 }}
      />
      {step === 0 && detectStep}
      {step === 1 && mergeStep}
      {step === 2 && cleanStep}
      <div style={{ marginTop: 16 }}>
        {step > 0 && <Button onClick={() => setStep(s => s - 1)}>上一步</Button>}
      </div>
    </Modal>
  )
}
