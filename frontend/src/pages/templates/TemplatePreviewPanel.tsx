/** 模板变更预览：diff（改了什么）+ impact（已有数据会怎样）. */

import { Alert, Tag, Typography } from 'antd'
import type { TemplatePreview } from '@/api'
import { SEVERITY_COLOR, impactSummaryLines } from './templateSpec'

const { Text } = Typography

export default function TemplatePreviewPanel({ preview }: { preview: TemplatePreview }) {
  const { diff, impact } = preview
  const lines = impactSummaryLines(impact)
  return (
    <div data-testid="template-preview-panel">
      <Alert
        type={preview.requires_force ? 'warning' : 'info'}
        showIcon
        style={{ marginBottom: 12 }}
        message={preview.requires_force ? '包含破坏性变更，保存需显式确认' : '变更非破坏：只增量补齐，不删除已有数据'}
        description={
          <div style={{ fontSize: 'var(--cn-text-sm)' }}>
            {lines.map(line => <div key={line}>{line}</div>)}
            {impact.truncated && <div>（工作区明细过多，已截断）</div>}
          </div>
        }
      />

      <div style={{ marginBottom: 8, fontWeight: 600 }}>
        模板变更（{diff.counts.total} 项：新增 {diff.counts.added} / 修改 {diff.counts.modified} / 移除 {diff.counts.removed}）
      </div>
      {diff.changes.length === 0 ? (
        <Text type="secondary">规格没有变化</Text>
      ) : (
        <ul style={{ paddingLeft: 18, margin: 0, maxHeight: 220, overflow: 'auto' }}>
          {diff.changes.map((change, idx) => (
            <li key={`${change.kind}-${change.target}-${idx}`} style={{ marginBottom: 4 }}>
              <Tag color={SEVERITY_COLOR[change.severity]}>{change.kind}</Tag>
              <span style={{ fontSize: 'var(--cn-text-sm)' }}>{change.message}</span>
            </li>
          ))}
        </ul>
      )}

      {impact.workspaces.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ marginBottom: 6, fontWeight: 600 }}>受影响工作区</div>
          <div style={{ maxHeight: 220, overflow: 'auto' }}>
            {impact.workspaces.map(ws => (
              <div key={ws.workspace_id} style={{ marginBottom: 10, fontSize: 'var(--cn-text-sm)' }}>
                <Text strong>{ws.workspace_name}</Text>
                <Text type="secondary"> · 当前阶段 {ws.current_stage ?? '—'}</Text>
                {ws.requires_force && <Tag color="red" style={{ marginLeft: 8 }}>需确认</Tag>}
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {ws.changes.map((c, idx) => (
                    <li key={`${ws.workspace_id}-${idx}`}>{c.message}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
