/** 编辑器右侧检查面板：本地问题清单 + 服务端预览 + 结构预览（ADR 0121）.
 */

import { useMemo } from 'react'
import { Alert, Button, Checkbox, Collapse, Empty, Space, Tag, Typography } from 'antd'
import type { TemplatePreview, WorkspaceTemplate } from '@/api'
import type { DraftIssue, TemplateDraft } from './templateDraft'
import { draftToSpec } from './templateDraft'
import TemplateDetail from './TemplateDetail'
import TemplatePreviewPanel from './TemplatePreviewPanel'

const { Text } = Typography

export default function TemplateCheckPanel({
  draft, issues, onJump, isEditing, preview, previewing, force, onForceChange, onPreview,
}: {
  draft: TemplateDraft
  issues: DraftIssue[]
  onJump: (issue: DraftIssue) => void
  isEditing: boolean
  preview: TemplatePreview | null
  previewing: boolean
  force: boolean
  onForceChange: (value: boolean) => void
  onPreview: () => void
}) {
  const pseudoTemplate = useMemo<WorkspaceTemplate>(() => ({
    id: 0,
    name: draft.name,
    description: draft.description,
    category: draft.category,
    modules: draft.modules as WorkspaceTemplate['modules'],
    spec: draftToSpec(draft),
    version: 0,
    is_builtin: false,
    created_by_id: null,
    updated_at: '',
    counts: { stage_count: 0, form_count: 0, field_count: 0, document_rule_count: 0, flow_count: 0, step_count: 0 },
    workspace_count: 0,
  }), [draft])

  return (
    <div className="cn-tpl-check-panel" data-testid="template-check-panel">
      <div className="cn-tpl-check-head">
        <Text strong>检查与预览</Text>
        <Tag color={issues.length ? 'red' : 'green'}>{issues.length ? `${issues.length} 个问题` : '结构通过'}</Tag>
      </div>
      {issues.length === 0 ? (
        <Alert type="success" showIcon message="本地结构检查通过" description="保存时仍会由服务端做最终校验。" />
      ) : (
        <div className="cn-tpl-issue-list">
          {issues.map((issue, index) => (
            <button
              type="button"
              className="cn-tpl-issue"
              key={`${issue.path}-${index}`}
              onClick={() => onJump(issue)}
            >
              <Text code>{issue.path}</Text>
              <span>{issue.message}</span>
            </button>
          ))}
        </div>
      )}

      {isEditing && (
        <>
          <Button
            block
            style={{ marginTop: 12 }}
            loading={previewing}
            onClick={onPreview}
            disabled={issues.length > 0}
          >
            检查已有工作区影响
          </Button>
          {preview && (
            <div style={{ marginTop: 12 }}>
              <TemplatePreviewPanel preview={preview} />
              {preview.requires_force && (
                <Checkbox
                  checked={force}
                  onChange={e => onForceChange(e.target.checked)}
                  style={{ marginTop: 8 }}
                  data-testid="template-force-check"
                >
                  我确认包含破坏性变更，仍需保存
                </Checkbox>
              )}
            </div>
          )}
        </>
      )}

      <Collapse
        size="small"
        style={{ marginTop: 16 }}
        items={[{
          key: 'structure',
          label: '结构预览（只读）',
          children: <>
            {draft.forms.length || draft.documents.length
              ? <TemplateDetail template={pseudoTemplate} />
              : <Empty description="暂无结构" />}
          </>,
        }]}
      />
      <Space size={4} wrap style={{ marginTop: 12 }}>
        <Text type="secondary">表单 {draft.forms.length}</Text>
        <Text type="secondary">·</Text>
        <Text type="secondary">文档 {draft.documents.length}</Text>
        <Text type="secondary">·</Text>
        <Text type="secondary">阶段 {draft.stages.length}</Text>
        <Text type="secondary">·</Text>
        <Text type="secondary">流程 {draft.flows.length}</Text>
      </Space>
    </div>
  )
}
