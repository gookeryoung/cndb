/** 流水线运行详情页 —— job / step 结论树 + 发现物过滤分页 + 运行中自动轮询.
 *
 * 数据源 `pipelinesApi.getRun` / `listFindings`（ADR 0076 P1）。
 * 运行处于 pending / running 时每 1.5 秒刷新一次，终态自动停止。
 * queryKey 约定：['pipeline-run', wid, rid] / ['pipeline-findings', wid, rid, severity, offset]。
 */

import { useEffect, useState } from 'react'
import {
  Alert, Button, Collapse, Empty, Listy, Pagination, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { pipelinesApi } from '@/api'
import type { PipelineFinding, PipelineSeverity } from '@/api'
import {
  PIPELINE_SEVERITY_META, PIPELINE_STATUS_META, PIPELINE_TRIGGER_LABEL, isActiveRun,
} from './checkCatalog'

const { Text } = Typography

const PAGE_SIZE = 50

/** job / step 结论 → 标签文案与颜色 */
const CONCLUSION_META: Record<string, { label: string; color: string }> = {
  success: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  skipped: { label: '跳过', color: 'default' },
}

type SeverityFilter = 'all' | PipelineSeverity

const SEVERITY_OPTIONS: Array<{ label: string; value: SeverityFilter }> = [
  { label: '全部', value: 'all' },
  { label: '错误', value: 'error' },
  { label: '告警', value: 'warn' },
  { label: '提示', value: 'info' },
]

function ConclusionTag({ conclusion }: { conclusion: string }) {
  const meta = CONCLUSION_META[conclusion] ?? { label: conclusion, color: 'default' }
  return <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
}

export default function PipelineRunDetail() {
  const { wid = '', rid = '' } = useParams<{ wid: string; rid: string }>()
  const navigate = useNavigate()
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  const [offset, setOffset] = useState(0)

  // 切换过滤条件时回到第一页，避免越界空白页
  useEffect(() => { setOffset(0) }, [severity])

  const { data: run, isLoading } = useQuery({
    queryKey: ['pipeline-run', wid, rid],
    queryFn: () => pipelinesApi.getRun(wid, rid),
    enabled: !!wid && !!rid,
    refetchInterval: (query) => (query.state.data && isActiveRun(query.state.data.status) ? 1500 : false),
  })

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ['pipeline-findings', wid, rid, severity, offset],
    queryFn: () => pipelinesApi.listFindings(wid, rid, {
      ...(severity === 'all' ? {} : { severity }),
      limit: PAGE_SIZE,
      offset,
    }),
    enabled: !!wid && !!rid,
  })

  if (isLoading || !run) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  const counts = run.stats.findings ?? {}
  const statusMeta = PIPELINE_STATUS_META[run.status] ?? { label: run.status, color: 'default' }
  const jobs = run.stats.jobs ?? []

  return (
    <div style={{ padding: '16px 24px', maxWidth: 960, margin: '0 auto' }}>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${wid}/pipelines`)} style={{ paddingInline: 0 }}>
        返回质量检查
      </Button>

      <Space size={8} wrap style={{ marginTop: 4 }}>
        <Text strong style={{ fontSize: 18 }}>{run.workflow_name || `运行 #${run.id}`}</Text>
        <Tag color={statusMeta.color} style={{ marginInlineEnd: 0 }}>{statusMeta.label}</Tag>
        <Text type="secondary">
          #{run.id} · {PIPELINE_TRIGGER_LABEL[run.trigger] ?? run.trigger}触发 · {formatDateTime(run.created_at)}
        </Text>
      </Space>

      {isActiveRun(run.status) && (
        <Alert style={{ marginTop: 12 }} type="info" showIcon message="运行中，页面会自动刷新" />
      )}
      {run.status === 'failed' && run.error_message && (
        <Alert style={{ marginTop: 12 }} type="error" showIcon message="运行失败" description={run.error_message} />
      )}

      <Space size={16} wrap style={{ marginTop: 12 }}>
        <Text>Job {run.stats.jobs_done ?? 0}/{run.stats.jobs_total ?? jobs.length}</Text>
        <Text>Step {run.stats.steps_total ?? 0}</Text>
        <Tag color="error" style={{ marginInlineEnd: 0 }}>错误 {counts.error ?? 0}</Tag>
        <Tag color="warning" style={{ marginInlineEnd: 0 }}>告警 {counts.warn ?? 0}</Tag>
        <Tag style={{ marginInlineEnd: 0 }}>提示 {counts.info ?? 0}</Tag>
        {typeof run.stats.duration_ms === 'number' && <Text type="secondary">耗时 {run.stats.duration_ms} ms</Text>}
      </Space>

      {(run.stats.warnings ?? []).length > 0 && (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message="运行告警"
          description={(
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {(run.stats.warnings ?? []).map(warning => <li key={warning}>{warning}</li>)}
            </ul>
          )}
        />
      )}

      <Collapse
        style={{ marginTop: 16 }}
        items={jobs.map(job => ({
          key: job.id,
          label: (
            <Space size={8}>
              <Text strong>{job.id}</Text>
              <ConclusionTag conclusion={job.conclusion} />
            </Space>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {job.steps.map((step, index) => (
                <div key={`${job.id}-${step.uses}-${index}`} className="cn-list-item" style={{ paddingInline: 8 }}>
                  <div className="cn-list-item-main">
                    <CnListMeta
                      title={(
                        <Space size={8} wrap>
                          <Text code>{step.uses}</Text>
                          <ConclusionTag conclusion={step.conclusion} />
                          <Tag color={PIPELINE_SEVERITY_META[step.severity as PipelineSeverity]?.color ?? 'default'} style={{ marginInlineEnd: 0 }}>
                            严重度 {PIPELINE_SEVERITY_META[step.severity as PipelineSeverity]?.label ?? step.severity}
                          </Tag>
                        </Space>
                      )}
                      description={(
                        <Text type={step.error ? 'danger' : 'secondary'}>
                          {step.error ? step.error : `发现 ${step.findings} 项`}
                        </Text>
                      )}
                    />
                  </div>
                </div>
              ))}
              {job.steps.length === 0 && <Text type="secondary">该 job 没有 step</Text>}
            </div>
          ),
        }))}
      />
      {jobs.length === 0 && <Empty description="暂无 job 执行记录" style={{ padding: 24 }} />}

      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Text strong>检查发现物</Text>
        <Segmented
          options={SEVERITY_OPTIONS}
          value={severity}
          onChange={(value) => setSeverity(value as SeverityFilter)}
        />
      </div>

      <Spin spinning={findingsLoading}>
        {(findings?.items.length ?? 0) === 0 ? (
          <Empty description="没有匹配的发现物" style={{ padding: 32 }} />
        ) : (
          <Listy
            className="cn-listy-plain"
            style={{ marginTop: 8 }}
            items={findings?.items ?? []}
            rowKey={(item: PipelineFinding) => item.id}
            itemRender={(finding: PipelineFinding) => (
              <div className="cn-list-item" style={{ paddingInline: 8 }}>
                <div className="cn-list-item-main">
                  <CnListMeta
                    title={(
                      <Space size={8} wrap>
                        <Tag color={PIPELINE_SEVERITY_META[finding.severity]?.color ?? 'default'} style={{ marginInlineEnd: 0 }}>
                          {PIPELINE_SEVERITY_META[finding.severity]?.label ?? finding.severity}
                        </Tag>
                        <Text>{finding.message}</Text>
                      </Space>
                    )}
                    description={(
                      <Text type="secondary">
                        {finding.check} · {finding.target_type}
                        {finding.target_id != null ? ` #${finding.target_id}` : ''}
                        {Object.keys(finding.locator ?? {}).length > 0
                          ? ` · ${JSON.stringify(finding.locator)}`
                          : ''}
                      </Text>
                    )}
                  />
                </div>
              </div>
            )}
          />
        )}
      </Spin>

      {(findings?.total ?? 0) > PAGE_SIZE && (
        <Pagination
          style={{ marginTop: 12, textAlign: 'right' }}
          size="small"
          current={Math.floor(offset / PAGE_SIZE) + 1}
          pageSize={PAGE_SIZE}
          total={findings?.total ?? 0}
          onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
          showSizeChanger={false}
        />
      )}
    </div>
  )
}
