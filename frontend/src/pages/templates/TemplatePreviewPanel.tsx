/** 模板变更预览：diff（改了什么）+ impact（已有数据会怎样）. */

import { Alert, Space, Table, Tag, Typography } from 'antd'
import type { TemplateDiffChange, TemplatePreview } from '@/api'
import { SEVERITY_COLOR, impactSummaryLines } from './templateSpec'

const { Text } = Typography

const CHANGE_COLUMNS = [
  {
    title: '变更',
    dataIndex: 'kind',
    width: 88,
    render: (kind: string, change: TemplateDiffChange) => (
      <Tag color={SEVERITY_COLOR[change.severity]}>{kind}</Tag>
    ),
  },
  {
    title: '说明',
    dataIndex: 'message',
    render: (message: string) => <span className="cn-tpl-preview-msg">{message}</span>,
  },
]

export default function TemplatePreviewPanel({ preview }: { preview: TemplatePreview }) {
  const { diff, impact } = preview
  const lines = impactSummaryLines(impact)
  return (
    <div className="cn-tpl-preview" data-testid="template-preview-panel">
      <Alert
        className="cn-tpl-preview-alert"
        type={preview.requires_force ? 'warning' : 'info'}
        showIcon
        message={preview.requires_force ? '包含破坏性变更，保存需显式确认' : '变更非破坏：只增量补齐，不删除已有数据'}
        description={
          <div className="cn-tpl-preview-impact-lines">
            {lines.map(line => <div key={line}>{line}</div>)}
            {impact.truncated && <div>（工作区明细过多，已截断）</div>}
          </div>
        }
      />

      <div className="cn-tpl-preview-head">
        <Text strong>模板变更</Text>
        <Space size={4} wrap className="cn-tpl-preview-counts">
          <Tag>{diff.counts.total} 项</Tag>
          <Tag color="green">新增 {diff.counts.added}</Tag>
          <Tag color="blue">修改 {diff.counts.modified}</Tag>
          <Tag color="red">移除 {diff.counts.removed}</Tag>
        </Space>
      </div>
      {diff.changes.length === 0 ? (
        <Text type="secondary">规格没有变化</Text>
      ) : (
        <Table<TemplateDiffChange>
          className="cn-tpl-preview-table"
          size="small"
          rowKey={(_record, index) => String(index)}
          pagination={false}
          dataSource={diff.changes}
          columns={CHANGE_COLUMNS}
          scroll={{ y: 240 }}
        />
      )}

      {impact.workspaces.length > 0 && (
        <>
          <div className="cn-tpl-preview-head">
            <Text strong>受影响工作区</Text>
            <Tag>{impact.workspaces.length}</Tag>
          </div>
          <div className="cn-tpl-impact-list">
            {impact.workspaces.map(ws => (
              <div key={ws.workspace_id} className="cn-tpl-impact-card">
                <div className="cn-tpl-impact-title">
                  <Text strong>{ws.workspace_name}</Text>
                  <Text type="secondary">当前阶段 {ws.current_stage ?? '—'}</Text>
                  {ws.requires_force && <Tag color="red">需确认</Tag>}
                </div>
                <ul className="cn-tpl-impact-changes">
                  {ws.changes.map((c, idx) => (
                    <li key={`${ws.workspace_id}-${idx}`}>{c.message}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
