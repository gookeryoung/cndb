/** 版本抽屉：单栏时间线 + 差异原地展开（从 DocumentEditorPage 抽出）.
 *
 * 交互口径（2026-10-18 增强）：
 * - 取消「时间线 / 差异对比」两个 Tab —— 差异改为在**当前版本卡片下方原地展开**，
 *   不切页面、不跳 Tab；再点一次收起。
 * - 同一时刻只展开一处：一个 diff 动辄上千行，多开会让抽屉卡顿。
 * - 抽屉不依赖 React Query：版本列表、diff 结果、loading 全部由页面解包后传入。
 *   差异渲染交给 DiffView（统一 / 并排 + 行内高亮）。
 */

import { Button, Drawer, Empty, Popconfirm, Skeleton, Tag, Tooltip } from 'antd'
import { DownOutlined, HistoryOutlined, RollbackOutlined, UpOutlined } from '@ant-design/icons'

import type { VersionItem } from '@/api/documents'
import { DocumentDiffView } from '@/components/DiffView'
import { useResponsive } from '@/hooks/useResponsive'
import { formatDateTime, formatRelativeTime } from '@/utils/datetime'
import { formatSize } from '@/utils/formatSize'

/** 对比对：base 是旧版（本卡片），head 是新版（上一张卡片） */
export interface VersionDiffPair {
  base: number
  head: number
}

/** 变更类型 → 徽标（手动保存不加徽标，避免每行都是标签） */
const CHANGE_TYPE_META: Record<VersionItem['change_type'], { label: string; color: string } | null> = {
  manual: null,
  auto_import: { label: '导入', color: 'blue' },
  rollback: { label: '回滚', color: 'orange' },
}

const SAVED_SIZE_HINT: Record<'add' | 'del' | 'same', string> = {
  add: '较上一版增加',
  del: '较上一版减少',
  same: '与上一版体积相同',
}

function VolumeDelta({ current, older }: { current: number; older?: number }) {
  if (older === undefined) return null
  const diff = current - older
  if (diff === 0) {
    return (
      <span className="cn-vh-delta cn-vh-delta--same" title={SAVED_SIZE_HINT.same}>
        体积不变
      </span>
    )
  }
  const kind = diff > 0 ? 'add' : 'del'
  return (
    <span
      className={`cn-vh-delta cn-vh-delta--${kind}`}
      title={`${SAVED_SIZE_HINT[kind]} ${formatSize(Math.abs(diff))}`}
    >
      {diff > 0 ? '+' : '−'}
      {formatSize(Math.abs(diff))}
    </span>
  )
}

export default function VersionsDrawer({
  open,
  onClose,
  loading,
  versions,
  total,
  diffPair,
  onToggleDiff,
  diffLoading,
  diff,
  diffError,
  onRollback,
  rollingBack,
}: {
  open: boolean
  onClose: () => void
  loading: boolean
  /** 版本列表（后端倒序：最新在前） */
  versions: VersionItem[]
  /** 版本总数（可能大于列表长度 —— 接口默认只给最近 50 个） */
  total?: number
  /** 当前展开的对比对；null 表示全部收起 */
  diffPair: VersionDiffPair | null
  /** 传 null 表示收起当前展开项 */
  onToggleDiff: (pair: VersionDiffPair | null) => void
  diffLoading: boolean
  diff: { added: number; removed: number; diff: string } | undefined
  diffError?: boolean
  onRollback: (versionNumber: number) => void
  /** 正在回滚的目标版本号，用于按钮 loading */
  rollingBack?: number | null
}) {
  const latest = versions[0]
  const hidden = total !== undefined ? total - versions.length : 0
  const { isMobile } = useResponsive()

  const body = () => {
    if (loading) {
      return (
        <div className="cn-vh-loading" data-testid="versions-loading">
          <Skeleton active title={false} paragraph={{ rows: 6 }} />
        </div>
      )
    }
    if (versions.length <= 1) {
      return (
        <div className="cn-vh-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史版本（首次保存后自动创建）" />
        </div>
      )
    }
    return (
      <>
        {hidden > 0 && (
          <div className="cn-vh-hint">
            仅显示最近 {versions.length} 个版本（共 {total} 个，更早的版本已归档）
          </div>
        )}
        <ol className="cn-vh-list">
          {versions.map((v, idx) => {
            const isCurrent = idx === 0
            // 时间线自上而下由新到旧：items[idx + 1] 才是更早的那一版
            const older = versions[idx + 1]
            // 「与上一版对比」= 本版（旧）→ 上方那一版（新）
            const pair: VersionDiffPair | null = idx > 0
              ? { base: v.version_number, head: versions[idx - 1].version_number }
              : null
            const expanded = pair !== null && diffPair?.base === pair.base && diffPair?.head === pair.head
            const meta = CHANGE_TYPE_META[v.change_type] ?? null

            return (
              <li
                key={v.id}
                className={`cn-vh-item${isCurrent ? ' is-current' : ''}${expanded ? ' is-expanded' : ''}`}
                data-testid={`version-item-${v.version_number}`}
              >
                <span className="cn-vh-rail" aria-hidden="true">
                  <span className="cn-vh-dot" />
                </span>

                <div className="cn-vh-body">
                  <div className="cn-vh-card">
                    <div className="cn-vh-card-head">
                      <span className="cn-vh-ver">v{v.version_number}</span>
                      {isCurrent && <Tag color="green" className="cn-vh-tag">当前</Tag>}
                      {meta && <Tag color={meta.color} className="cn-vh-tag">{meta.label}</Tag>}
                      <Tooltip title={formatDateTime(v.created_at)}>
                        <span className="cn-vh-time">{formatRelativeTime(v.created_at)}</span>
                      </Tooltip>
                      <VolumeDelta current={v.content_size} older={older?.content_size} />
                      <span className="cn-vh-size">{formatSize(v.content_size)}</span>
                    </div>

                    <div className={`cn-vh-summary${v.change_summary ? '' : ' is-empty'}`}>
                      {v.change_summary || '未填写变更说明'}
                    </div>

                    <div className="cn-vh-actions">
                      {pair && (
                        <Button
                          size="small"
                          type={expanded ? 'primary' : 'default'}
                          ghost={expanded}
                          icon={expanded ? <UpOutlined /> : <DownOutlined />}
                          aria-expanded={expanded}
                          data-testid={`version-diff-toggle-${v.version_number}`}
                          onClick={() => onToggleDiff(expanded ? null : pair)}
                        >
                          {expanded ? '收起对比' : '与上一版对比'}
                        </Button>
                      )}
                      {!isCurrent && (
                        <Popconfirm
                          title={`回滚到 v${v.version_number}？`}
                          description="将基于该版本内容创建一个新版本，当前内容不会被覆盖。"
                          okText="确认回滚"
                          cancelText="取消"
                          onConfirm={() => onRollback(v.version_number)}
                        >
                          <Button
                            size="small"
                            icon={<RollbackOutlined />}
                            loading={rollingBack === v.version_number}
                            data-testid={`version-rollback-${v.version_number}`}
                          >
                            回滚到此版
                          </Button>
                        </Popconfirm>
                      )}
                    </div>
                  </div>

                  {expanded && pair && (
                    <div className="cn-vh-diff" data-testid="version-diff-panel">
                      {diffLoading ? (
                        <div className="cn-vh-diff-loading">
                          <Skeleton active title={false} paragraph={{ rows: 5 }} />
                        </div>
                      ) : diffError ? (
                        <div className="cn-vh-diff-error">差异计算失败，请重试</div>
                      ) : (
                        <DocumentDiffView
                          diff={diff?.diff ?? ''}
                          baseLabel={`v${pair.base}`}
                          headLabel={`v${pair.head}`}
                        />
                      )}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </>
    )
  }

  return (
    <Drawer
      title={
        <span className="cn-vh-drawer-title">
          <HistoryOutlined />
          版本历史
        </span>
      }
      width={isMobile ? '100%' : 960}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: 0 } }}
      extra={
        latest ? (
          <span className="cn-vh-head-meta">
            共 {total ?? versions.length} 个版本 · 当前 v{latest.version_number}
          </span>
        ) : null
      }
    >
      <div className="cn-vh">{body()}</div>
    </Drawer>
  )
}
