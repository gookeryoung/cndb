/** 数据标准符合度面板（ADR 0188 C4 / C11）.
 *
 * 把「数据标准」从文档变成可度量的一组数字：六项覆盖率 + 缺口字段清单。
 * 缺口字段名可点击（跳到字段 Tab 并定位该字段），让「知道缺什么」直接连到「去补」。
 */
import { useQuery } from '@tanstack/react-query'
import { Progress, Tag, Tooltip, Empty, Skeleton, Button } from 'antd'
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { dictionaryApi } from '@/api'
import type { TableDictionaryScore } from '@/api'

/** 指标展示顺序（与后端 METRIC_LABELS 的键对齐） */
export const SCORE_METRIC_ORDER = [
  'business_meaning',
  'enum_controlled',
  'naming',
  'required',
  'sensitivity',
  'example_value',
] as const

/** 指标说明（给不熟悉治理口径的用户解释「这一项在量什么」） */
export const SCORE_METRIC_HINTS: Record<string, string> = {
  business_meaning: '写了业务口径的字段占比。口径缺失意味着「这个字段什么意思」只存在于某个人脑子里。',
  enum_controlled: '使用单选 / 多选（枚举）的字段占比。有限取值用自由文本是数据标准失效的首要原因。',
  naming: '字段名不含空格与标点、长度 ≤ 64 的占比。',
  required: '开启了必填（或条件必填）的字段占比。全部字段都可空通常说明约束还没梳理。',
  sensitivity: '显式设置了敏感级的字段占比。含隐私 / 机密的字段必须标注，否则字典不会脱敏。',
  example_value: '填了示例值的字段占比。示例值是可读性最强的一项元数据。',
}

export interface StandardScorePanelProps {
  wid: string
  tid: string
  /** 点击缺口字段时回调（父层切到字段 Tab 并定位） */
  onJumpToField?: (fieldName: string) => void
}

function ratioPercent(ratio: number): number {
  return Math.round(ratio * 100)
}

/** 单项指标行 */
function MetricRow({
  metricKey, label, hint, covered, total, ratio, missing, onJumpToField,
}: {
  metricKey: string
  label: string
  hint: string
  covered: number
  total: number
  ratio: number
  missing: string[]
  onJumpToField?: (fieldName: string) => void
}) {
  const percent = ratioPercent(ratio)
  const status = percent >= 80 ? 'success' : percent >= 50 ? 'normal' : 'exception'
  return (
    <div className="cn-score-row" data-testid={`score-metric-${metricKey}`} style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 'var(--cn-text-sm)' }}>
          <Tooltip title={hint}>
            <span style={{ borderBottom: '1px dashed var(--cn-border)', cursor: 'help' }}>{label}</span>
          </Tooltip>
        </span>
        <span style={{ color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-xs)' }}>
          {covered} / {total}（{percent}%）
        </span>
      </div>
      <Progress percent={percent} status={status} showInfo={false} size="small" />
      {missing.length > 0 && (
        <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {missing.slice(0, 12).map(name => (
            <Tag
              key={name}
              icon={<WarningOutlined />}
              color="warning"
              style={{ cursor: onJumpToField ? 'pointer' : 'default' }}
              onClick={() => onJumpToField?.(name)}
              data-testid={`score-missing-${metricKey}-${name}`}
            >
              {name}
            </Tag>
          ))}
          {missing.length > 12 && <Tag>+{missing.length - 12}</Tag>}
        </div>
      )}
    </div>
  )
}

export default function StandardScorePanel({ wid, tid, onJumpToField }: StandardScorePanelProps) {
  const { data, isLoading, refetch, isFetching } = useQuery<TableDictionaryScore>({
    queryKey: ['table-dictionary-score', wid, tid],
    queryFn: () => dictionaryApi.score(wid, tid),
    enabled: !!wid && !!tid,
  })

  if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />
  if (!data) return <Empty description="暂无符合度数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />

  const overallPercent = ratioPercent(data.overall.ratio)

  return (
    <div data-testid="standard-score-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <span style={{ fontSize: 'var(--cn-text-sm)', color: 'var(--cn-text-secondary)' }}>
            共 {data.field_count} 个字段 · 综合符合度 {overallPercent}%
          </span>
          <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-tertiary, var(--cn-text-secondary))' }}>
            六项指标的平均值，仅供参考，不构成门禁。
          </div>
        </div>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={isFetching}
          onClick={() => { void refetch() }}
          data-testid="score-refresh"
        >
          刷新
        </Button>
      </div>
      {SCORE_METRIC_ORDER.map(key => {
        const metric = data.metrics[key]
        if (!metric) return null
        return (
          <MetricRow
            key={key}
            metricKey={key}
            label={data.metric_labels[key] ?? key}
            hint={SCORE_METRIC_HINTS[key] ?? ''}
            covered={metric.covered}
            total={metric.total}
            ratio={metric.ratio}
            missing={metric.missing_fields}
            onJumpToField={onJumpToField}
          />
        )
      })}
      <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}>
        结构指纹：<code>{data.schema_hash}</code>
      </div>
    </div>
  )
}
