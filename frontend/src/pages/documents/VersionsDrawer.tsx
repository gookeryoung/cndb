/** 版本抽屉：时间线与差异对比两个 Tab（从 DocumentEditorPage 抽出）.
 *
 * 页面侧把 query 结果解包为 props（timeline / diff / loading 标记），
 * 抽屉不依赖 React Query。差异对比交给 DiffView 组件（统一 / 并排 + 行内高亮）。
 */

import { Drawer, Tabs, Timeline, Typography } from 'antd'
import type { TimelineProps } from 'antd'

import { DocumentDiffView } from '@/components/DiffView'

const { Text } = Typography

export default function VersionsDrawer({
  open,
  onClose,
  loading,
  timeline,
  diffPair,
  diffLoading,
  diff,
}: {
  open: boolean
  onClose: () => void
  loading: boolean
  timeline: NonNullable<TimelineProps['items']>
  /** 当前对比的版本对；null 表示还没在时间线里选 */
  diffPair: { base: number; head: number } | null
  diffLoading: boolean
  diff: { added: number; removed: number; diff: string } | undefined
}) {
  return (
    <Drawer title="版本历史" width={920} open={open} onClose={onClose}>
      <Tabs
        items={[
          {
            key: 'list',
            label: '时间线',
            children: loading ? (
              <div>加载中…</div>
            ) : timeline.length <= 1 ? (
              <Text type="secondary">暂无历史版本（首次保存后自动创建）</Text>
            ) : (
              <Timeline items={timeline} />
            ),
          },
          {
            key: 'diff',
            label: '差异对比',
            children: diffPair ? (
              diffLoading ? (
                <div>计算差异中…</div>
              ) : (
                <DocumentDiffView
                  diff={diff?.diff ?? ''}
                  baseLabel={`v${diffPair.base}`}
                  headLabel={`v${diffPair.head}`}
                />
              )
            ) : (
              <Text type="secondary">在时间线中点击「与上一版对比」查看差异</Text>
            ),
          },
        ]}
      />
    </Drawer>
  )
}
