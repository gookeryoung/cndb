/** dashboard 文本组件：口径说明 / 标题注释（ADR 0023 P0） */
import type { DashboardTextWidget } from '../dashboardModel'

export default function TextWidget({ widget }: { widget: DashboardTextWidget }) {
  return (
    <div
      data-testid={`dashboard-text-${widget.id}`}
      style={{
        flex: 1, minHeight: 0, overflow: 'auto', whiteSpace: 'pre-wrap',
        fontSize: 13, lineHeight: 1.7, color: 'var(--cn-text-primary)',
      }}
    >
      {widget.text.content}
    </div>
  )
}
