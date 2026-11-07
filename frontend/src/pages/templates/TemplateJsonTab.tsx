/** JSON 高级页签（ADR 0121 D2/D10）：显式应用，失败不覆盖结构化草稿. */

import { useState } from 'react'
import { Alert, Button, Input, Space, Typography } from 'antd'
import { applyJsonToDraft, serializeDraftJson } from './templateDraft'
import type { TemplateDraft } from './templateDraft'

const { Text } = Typography

export default function TemplateJsonTab({
  draft, onApply,
}: {
  draft: TemplateDraft
  onApply: (next: TemplateDraft) => void
}) {
  const [text, setText] = useState(() => serializeDraftJson(draft))
  const [error, setError] = useState('')
  const [issues, setIssues] = useState<Array<{ path: string; message: string }>>([])

  const apply = () => {
    const result = applyJsonToDraft(text, {
      name: draft.name,
      description: draft.description,
      category: draft.category,
      modules: draft.modules,
    })
    if (result.parseError) {
      setError(result.parseError)
      setIssues([])
      return
    }
    if (result.issues.length) {
      setError('JSON 已解析，但规格仍有问题；请修正后再应用。')
      setIssues(result.issues.map(issue => ({ path: issue.path, message: issue.message })))
      return
    }
    if (result.draft) {
      setError('')
      setIssues([])
      onApply(result.draft)
    }
  }

  return (
    <div className="cn-tpl-section">
      <Alert
        type="info"
        showIcon
        message="高级模式"
        description="JSON 用于批量修改、跨版本迁移与排障。修改后必须点击「应用 JSON」才会写入结构化草稿；解析或校验失败不会覆盖当前内容。"
        style={{ marginBottom: 12 }}
      />
      <Input.TextArea
        value={text}
        onChange={e => { setText(e.target.value); setError(''); setIssues([]) }}
        autoSize={{ minRows: 18, maxRows: 30 }}
        className="cn-tpl-code cn-tpl-json-editor"
        data-testid="template-spec-text"
      />
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 8 }} />}
      {issues.length > 0 && (
        <div className="cn-tpl-json-issues">
          {issues.slice(0, 20).map((issue, index) => (
            <div key={`${issue.path}-${index}`}>
              <Text code>{issue.path}</Text> <Text type="danger">{issue.message}</Text>
            </div>
          ))}
          {issues.length > 20 && <Text type="secondary">还有 {issues.length - 20} 条问题…</Text>}
        </div>
      )}
      <Space style={{ marginTop: 12 }}>
        <Button type="primary" onClick={apply}>应用 JSON</Button>
        <Button onClick={() => { setText(serializeDraftJson(draft)); setError(''); setIssues([]) }}>恢复当前草稿</Button>
        <Button onClick={() => {
          try {
            setText(JSON.stringify(JSON.parse(text), null, 2))
            setError('')
          } catch {
            setError('JSON 解析失败，无法格式化')
          }
        }}>格式化</Button>
      </Space>
    </div>
  )
}
