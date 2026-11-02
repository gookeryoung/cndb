/** 流水线运行详情页 —— job / step 结论树 + 发现物过滤分页 + 运行中自动轮询.
 *
 * 数据源 `pipelinesApi.getRun` / `listFindings`（ADR 0076 P1）。
 * 运行处于 pending / running 时每 1.5 秒刷新一次，终态自动停止。
 * 表目标的发现物可一键转成所属表的问题（P2 / D15）。
 * `domain` 决定「返回」回到哪个质量检查页（数据表 / 文档各自留在本模块上下文）。
 *
 * 视觉口径与质量检查规则页（PipelinesPage）共用一套原语：
 * 紧凑页头（cn-page-head）+ 概要计数条 + 左右双栏 SectionBox（左=执行结果，右=检查发现物）。
 * 两栏都走 flush 盒体，外框由盒子承担、行间分隔线满宽绘制，避免双层描边。
 * queryKey 约定：['pipeline-run', wid, rid] / ['pipeline-findings', wid, rid, severity, offset]。
 */

import { useEffect, useState } from 'react'
import {
  Alert, App as AntApp, Button, Collapse, Empty, Pagination, Segmented, Space, Spin, Tag, Typography,
} from 'antd'
import {
  AlertOutlined, ApartmentOutlined, ArrowLeftOutlined, FlagOutlined, HistoryOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import CnListMeta from '@/components/CnListMeta'
import SectionBox from '@/components/SectionBox'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { formatDateTime } from '@/utils/datetime'
import { pipelinesApi } from '@/api'
import type { PipelineCheckDomain, PipelineFinding, PipelineSeverity } from '@/api'
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

/** 概要条单元格：标签在上、数值在下（错误 / 告警命中有色，0 保持弱化） */
function Stat({
  label, value, tone,
}: {
  label: string
  value: ReactNode
  tone?: 'danger' | 'warning'
}) {
  return (
    <div className="cn-qc-run-stat">
      <span className="cn-qc-run-stat-label">{label}</span>
      <Text strong type={tone} className="cn-qc-run-stat-value">{value}</Text>
    </div>
  )
}

export default function PipelineRunDetail({ domain = 'table' }: { domain?: PipelineCheckDomain }) {
  const { wid = '', rid = '' } = useParams<{ wid: string; rid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  const [offset, setOffset] = useState(0)

  /** 返回按钮回到本域的质量检查页：文档运行详情不跳回数据表段 */
  const listPath = domain === 'document' ? `/w/${wid}/documents/pipelines` : `/w/${wid}/pipelines`

  const convertIssue = useMutation({
    mutationFn: (finding: PipelineFinding) => pipelinesApi.convertFindingToIssue(wid, rid, finding.id),
    onSuccess: (issue) => message.success(`已创建问题 #${issue.id}`),
    onError: (err) => message.error(err instanceof Error ? err.message : '转问题失败'),
  })

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
      <div className="cn-page cn-state">
        <Spin />
      </div>
    )
  }

  const counts = run.stats.findings ?? {}
  const statusMeta = PIPELINE_STATUS_META[run.status] ?? { label: run.status, color: 'default' }
  const jobs = run.stats.jobs ?? []
  const totalSteps = jobs.reduce((sum, job) => sum + job.steps.length, 0)

  return (
    <div className="cn-page cn-qc-run-page" data-testid="pipeline-run-detail">
      {/* ── 页头：工作流名 + 运行状态 / 元信息 + 返回（与规则页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><HistoryOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">{run.workflow_name || `运行 #${run.id}`}</h1>
            <div className="cn-page-head-sub">
              <Tag color={statusMeta.color} style={{ marginInlineEnd: 0 }}>{statusMeta.label}</Tag>
              <span className="cn-page-head-meta">
                #{run.id} · {PIPELINE_TRIGGER_LABEL[run.trigger] ?? run.trigger}触发 · {formatDateTime(run.created_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(listPath)}>
            返回质量检查
          </Button>
        </div>
      </header>

      {isActiveRun(run.status) && (
        <Alert type="info" showIcon title="运行中，页面会自动刷新" />
      )}
      {run.status === 'failed' && run.error_message && (
        <Alert type="error" showIcon title="运行失败" description={run.error_message} />
      )}
      {(run.stats.warnings ?? []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          title="运行告警"
          description={(
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {(run.stats.warnings ?? []).map(warning => <li key={warning}>{warning}</li>)}
            </ul>
          )}
        />
      )}

      {/* ── 概要计数条：Job / Step / 严重度 / 耗时，单元格分栏、内部分隔线 ── */}
      <section className="cn-qc-run-summary" aria-label="运行概要">
        <Stat label="Job" value={`${run.stats.jobs_done ?? 0}/${run.stats.jobs_total ?? jobs.length}`} />
        <Stat label="Step" value={run.stats.steps_total ?? totalSteps} />
        <Stat label="错误" value={counts.error ?? 0} tone={counts.error ? 'danger' : undefined} />
        <Stat label="告警" value={counts.warn ?? 0} tone={counts.warn ? 'warning' : undefined} />
        <Stat label="提示" value={counts.info ?? 0} />
        <Stat
          label="耗时"
          value={typeof run.stats.duration_ms === 'number' ? `${run.stats.duration_ms} ms` : '—'}
        />
      </section>

      {/* ── 双栏：左=执行结果（job / step），右=检查发现物（严重度过滤 + 分页） ── */}
      <div className="cn-qc-run-split">
        <SectionBox
          title="执行结果"
          icon={<ApartmentOutlined />}
          extra={<span>{jobs.length} 个 job</span>}
          flush
          testId="qc-jobs-box"
        >
          {jobs.length === 0 ? (
            <div className="cn-qc-empty">
              <Empty description="暂无 job 执行记录" />
            </div>
          ) : (
            <Collapse
              ghost
              size="small"
              className="cn-qc-run-jobs"
              items={jobs.map(job => ({
                key: job.id,
                label: (
                  <div className="cn-qc-run-job-head">
                    <Space size={8} wrap>
                      <Text strong>{job.id}</Text>
                      <ConclusionTag conclusion={job.conclusion} />
                    </Space>
                    <Text type="secondary" className="cn-qc-run-job-meta">{job.steps.length} 个 step</Text>
                  </div>
                ),
                children: (
                  <div className="cn-qc-run-steps">
                    {job.steps.map((step, index) => (
                      <div key={`${job.id}-${step.uses}-${index}`} className="cn-list-item cn-qc-run-step">
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
                    {job.steps.length === 0 && (
                      <Text type="secondary" className="cn-qc-run-step-empty">该 job 没有 step</Text>
                    )}
                  </div>
                ),
              }))}
            />
          )}
        </SectionBox>

        <SectionBox
          title="检查发现物"
          icon={<AlertOutlined />}
          extra={(
            <Space size={8}>
              <span>共 {findings?.total ?? 0} 项</span>
              <Segmented
                size="small"
                options={SEVERITY_OPTIONS}
                value={severity}
                onChange={(value) => setSeverity(value as SeverityFilter)}
              />
            </Space>
          )}
          flush
          className="cn-qc-run-findings"
          testId="qc-findings-box"
          footer={(findings?.total ?? 0) > PAGE_SIZE ? (
            <Pagination
              size="small"
              current={Math.floor(offset / PAGE_SIZE) + 1}
              pageSize={PAGE_SIZE}
              total={findings?.total ?? 0}
              onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
              showSizeChanger={false}
            />
          ) : undefined}
        >
          <Spin spinning={findingsLoading}>
            {(findings?.items.length ?? 0) === 0 ? (
              <div className="cn-qc-empty">
                <Empty description="没有匹配的发现物" />
              </div>
            ) : (
              (findings?.items ?? []).map((finding: PipelineFinding) => (
                <div key={finding.id} className="cn-list-item cn-qc-row cn-qc-run-finding">
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
                  {finding.target_type === 'table' && (
                    <div className="cn-list-item-actions">
                      <Button
                        type="link"
                        size="small"
                        icon={<FlagOutlined />}
                        loading={convertIssue.isPending && convertIssue.variables?.id === finding.id}
                        onClick={() => convertIssue.mutate(finding)}
                      >
                        转问题
                      </Button>
                    </div>
                  )}
                </div>
              ))
            )}
          </Spin>
        </SectionBox>
      </div>
    </div>
  )
}
