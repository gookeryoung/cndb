/** 贡献统计洞察 —— KPI 摘要、活动构成与成员排行（需求 0126 布局优化）.
 *
 * 全部基于贡献接口返回值在前端聚合，不新增接口：
 * - KPI：近 12 个月贡献、活跃成员 / 成员总数、日均贡献、连续贡献天数、最活跃成员；
 * - 活动构成：六类直接写活动累计值的横向堆叠条 + 图例；
 * - 成员排行：按累计贡献取 Top 5，条宽按榜首归一化。
 */

import type { ReactNode } from 'react'
import { Avatar, Empty } from 'antd'
import {
  CalendarOutlined, FireOutlined, LineChartOutlined, TeamOutlined, TrophyOutlined,
} from '@ant-design/icons'
import type { WorkspaceContributionItem, WorkspaceContributions } from '@/api'
import { workspaceModulesFeatures } from '@/utils/workspaceModules'

export function memberName(item: WorkspaceContributionItem): string {
  return item.nickname?.trim() || item.username?.trim() || `用户 ${item.user_id}`
}

function memberInitial(item: WorkspaceContributionItem): string {
  return memberName(item).slice(0, 1).toUpperCase()
}

/** 相对时间：一周内按分钟 / 小时 / 天，超过 30 天回落日期. */
export function formatRelative(value?: string | null): string {
  if (!value) return '-'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return '-'
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  const diff = Date.now() - time
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  return new Date(value).toLocaleDateString()
}

function parseIso(iso: string): Date {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day)
}

function isoDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

/** 近 12 个月窗口内的按天计数、总量与活跃成员集合 */
function windowTotals(data?: WorkspaceContributions) {
  const counts = new Map<string, number>()
  const active = new Set<string>()
  let total = 0
  for (const entry of data?.daily ?? []) {
    counts.set(entry.date, (counts.get(entry.date) ?? 0) + entry.count)
    total += entry.count
    if (entry.count > 0) active.add(String(entry.user_id))
  }
  return { counts, total, active }
}

/** 截至窗口结束日的连续贡献天数；当天无贡献时按 GitHub 口径从昨天起算 */
function currentStreak(counts: Map<string, number>, endIso?: string): number {
  if (!endIso) return 0
  const cursor = parseIso(endIso)
  if ((counts.get(isoDate(cursor)) ?? 0) <= 0) cursor.setDate(cursor.getDate() - 1)
  let streak = 0
  while ((counts.get(isoDate(cursor)) ?? 0) > 0) {
    streak += 1
    cursor.setDate(cursor.getDate() - 1)
  }
  return streak
}

function windowDays(startIso?: string, endIso?: string): number {
  if (!startIso || !endIso) return 0
  const diff = parseIso(endIso).getTime() - parseIso(startIso).getTime()
  return diff < 0 ? 0 : Math.round(diff / 86_400_000) + 1
}

interface KpiCard {
  label: string
  value: string
  hint: string
  icon: ReactNode
}

export function ContributionKpis({
  data,
  items,
  memberCount,
}: {
  data?: WorkspaceContributions
  items: WorkspaceContributionItem[]
  memberCount?: number
}) {
  const { counts, total, active } = windowTotals(data)
  const days = windowDays(data?.timeline_start, data?.timeline_end)
  const streak = currentStreak(counts, data?.timeline_end)
  const top = items.reduce<WorkspaceContributionItem | null>(
    (best, item) => (!best || item.total > best.total ? item : best),
    null,
  )
  const totalMembers = memberCount && memberCount > 0
    ? memberCount
    : items.filter(item => item.is_member).length
  const topName = top && top.total > 0 ? memberName(top) : '暂无'

  const cards: KpiCard[] = [
    {
      label: '近 12 个月贡献',
      value: total.toLocaleString(),
      hint: '按天汇总，不含更早累计',
      icon: <LineChartOutlined />,
    },
    {
      label: '活跃成员',
      value: String(active.size),
      hint: `共 ${totalMembers} 位成员`,
      icon: <TeamOutlined />,
    },
    {
      label: '日均贡献',
      value: days > 0 ? (total / days).toFixed(1) : '0',
      hint: days > 0 ? `统计窗口 ${days} 天` : '暂无统计窗口',
      icon: <CalendarOutlined />,
    },
    {
      label: '连续贡献',
      value: `${streak} 天`,
      hint: streak > 0 ? '截至最近一次贡献' : '最近无连续贡献',
      icon: <FireOutlined />,
    },
    {
      label: '最活跃成员',
      value: topName,
      hint: top && top.total > 0 ? `累计 ${top.total.toLocaleString()} 次` : '等待首次贡献',
      icon: <TrophyOutlined />,
    },
  ]

  return (
    <div className="cn-contrib-kpis" data-testid="ws-contribution-kpis">
      {cards.map(card => (
        <div key={card.label} className="cn-contrib-kpi">
          <div className="cn-contrib-kpi-label">{card.icon} {card.label}</div>
          <div className="cn-contrib-kpi-value" title={card.value}>{card.value}</div>
          <div className="cn-contrib-kpi-hint" title={card.hint}>{card.hint}</div>
        </div>
      ))}
    </div>
  )
}

interface ActivityCategory {
  key: string
  label: string
  color: string
  value: number
}

export function ContributionBreakdown({
  items,
  features,
}: {
  items: WorkspaceContributionItem[]
  features: ReturnType<typeof workspaceModulesFeatures>
}) {
  const sum = (pick: (item: WorkspaceContributionItem) => number) =>
    items.reduce((total, item) => total + pick(item), 0)

  const categories: Array<ActivityCategory & { enabled: boolean }> = [
    { key: 'rows_created', label: '数据行新建', color: '#2da44e', enabled: features.tables, value: sum(item => item.rows_created) },
    { key: 'rows_updated', label: '数据行更新', color: '#57ab5a', enabled: features.tables, value: sum(item => item.rows_updated) },
    { key: 'documents_created', label: '文档新建', color: '#3b82f6', enabled: features.documents, value: sum(item => item.documents_created) },
    { key: 'documents_edited', label: '文档保存', color: '#79b8ff', enabled: features.documents, value: sum(item => item.documents_edited) },
    { key: 'designs_created', label: '设计新建', color: '#a371f7', enabled: features.design, value: sum(item => item.designs_created) },
    { key: 'designs_edited', label: '设计保存', color: '#d2a8ff', enabled: features.design, value: sum(item => item.designs_edited) },
  ]
  const visible = categories.filter(category => category.enabled)
  const grandTotal = visible.reduce((total, category) => total + category.value, 0)

  return (
    <section className="cn-contrib-card" data-testid="ws-contribution-breakdown">
      <div className="cn-contrib-card-head">
        <div className="cn-ws-stats-section-title">活动构成</div>
        <span className="cn-contrib-card-hint">全部时间 · 共 {grandTotal.toLocaleString()} 次</span>
      </div>
      {grandTotal > 0 ? (
        <>
          <div className="cn-contrib-stack" role="img" aria-label="活动构成分布">
            {visible.map(category => category.value > 0 && (
              <span
                key={category.key}
                className="cn-contrib-stack-seg"
                style={{ width: `${(category.value / grandTotal) * 100}%`, background: category.color }}
                title={`${category.label}：${category.value.toLocaleString()} 次`}
              />
            ))}
          </div>
          <div className="cn-contrib-breakdown-legend">
            {visible.map(category => (
              <div key={category.key} className="cn-contrib-breakdown-item">
                <i style={{ background: category.color }} />
                <span className="cn-contrib-breakdown-label">{category.label}</span>
                <span className="cn-contrib-breakdown-value">{category.value.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无活动构成" />
      )}
    </section>
  )
}

export function ContributionRanking({ items }: { items: WorkspaceContributionItem[] }) {
  const grandTotal = items.reduce((total, item) => total + item.total, 0)
  const ranked = [...items]
    .filter(item => item.total > 0)
    .sort((left, right) => right.total - left.total)
    .slice(0, 5)
  const max = ranked[0]?.total ?? 0

  return (
    <section className="cn-contrib-card" data-testid="ws-contribution-ranking">
      <div className="cn-contrib-card-head">
        <div className="cn-ws-stats-section-title">成员贡献排行</div>
        <span className="cn-contrib-card-hint">{ranked.length > 0 ? `Top ${ranked.length}` : '暂无数据'}</span>
      </div>
      {ranked.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无贡献记录" />
      ) : (
        <ol className="cn-contrib-rank-list">
          {ranked.map((item, index) => {
            const share = grandTotal > 0 ? (item.total / grandTotal) * 100 : 0
            return (
              <li key={item.user_id} className="cn-contrib-rank-row">
                <span className={`cn-contrib-rank-no${index < 3 ? ` is-top-${index + 1}` : ''}`}>
                  {index + 1}
                </span>
                <Avatar size={28}>{memberInitial(item)}</Avatar>
                <div className="cn-contrib-rank-main">
                  <div className="cn-contrib-rank-name" title={memberName(item)}>{memberName(item)}</div>
                  <div className="cn-contrib-rank-bar">
                    <i style={{ width: `${max > 0 ? (item.total / max) * 100 : 0}%` }} />
                  </div>
                </div>
                <div className="cn-contrib-rank-meta">
                  <strong>{item.total.toLocaleString()}</strong>
                  <span>{share.toFixed(0)}%</span>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
