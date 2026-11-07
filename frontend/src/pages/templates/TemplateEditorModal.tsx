/** 模板规格编辑器：JSON 编辑 + 变更预览 + 破坏性变更确认. */

import { useEffect, useMemo, useState } from 'react'
import { Alert, App as AntApp, Checkbox, Input, Modal, Space, Spin, Typography } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceTemplateApi } from '@/api'
import type { TemplatePreview, WorkspaceTemplate } from '@/api'
import TemplatePreviewPanel from './TemplatePreviewPanel'
import { formatSpecJson, parseSpecJson } from './templateSpec'

const { Text } = Typography

interface Props {
  open: boolean
  /** 正在编辑的模板；null 表示新建 */
  template: WorkspaceTemplate | null
  /** 新建时用来预填内容的模板（复制内置模板为自定义模板） */
  seed?: WorkspaceTemplate | null
  onClose: () => void
  onSaved?: (template: WorkspaceTemplate) => void
}

export default function TemplateEditorModal({ open, template, seed, onClose, onSaved }: Props) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [summary, setSummary] = useState('')
  const [text, setText] = useState(formatSpecJson(null))
  const [specError, setSpecError] = useState<string | null>(null)
  const [preview, setPreview] = useState<TemplatePreview | null>(null)
  const [force, setForce] = useState(false)

  useEffect(() => {
    if (!open) return
    const source = template ?? seed ?? null
    setName(template?.name ?? (seed ? `${seed.name}（副本）` : ''))
    setDescription(source?.description ?? '')
    setCategory(source?.category ?? '')
    setSummary('')
    setText(formatSpecJson(source?.spec))
    setSpecError(null)
    setPreview(null)
    setForce(false)
  }, [open, template, seed])

  const parsed = useMemo(() => parseSpecJson(text), [text])

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!template) throw new Error('新建模板暂无历史版本，可直接保存')
      if (parsed.error || !parsed.spec) throw new Error(parsed.error ?? '规格无效')
      return workspaceTemplateApi.preview(template.id, parsed.spec)
    },
    onSuccess: (data) => {
      setPreview(data)
      setSpecError(null)
      if (data.requires_force) {
        message.warning('检测到破坏性变更：确认后勾选「我已知晓影响」再保存')
      } else {
        message.success('预览完成：变更非破坏')
      }
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : '预览失败'
      setSpecError(msg)
      message.error(msg)
    },
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (parsed.error || !parsed.spec) throw new Error(parsed.error ?? '规格无效')
      if (!name.trim()) throw new Error('请填写模板名称')
      if (!template) {
        return workspaceTemplateApi.create({
          name: name.trim(),
          description,
          category,
          spec: parsed.spec,
          change_summary: summary || '初始版本',
        })
      }
      return workspaceTemplateApi.update(template.id, {
        name: name.trim(),
        description,
        category,
        spec: parsed.spec,
        change_summary: summary || undefined,
        force,
      })
    },
    onSuccess: (result) => {
      const saved = 'template' in result ? result.template : result
      const sync = 'sync' in result ? result.sync : undefined
      message.success(
        sync
          ? `模板已保存；已同步 ${sync.created_tables} 张表 / ${sync.added_fields} 个字段 / ${sync.created_documents} 份文档`
          : '模板已创建',
      )
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
      onSaved?.(saved)
      onClose()
    },
    onError: (err: unknown) => {
      // 409 的 detail 里带 diff / impact，直接转成预览，避免用户盲确认
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      if (detail && typeof detail === 'object' && 'diff' in detail && 'impact' in detail) {
        const d = detail as { diff: TemplatePreview['diff']; impact: TemplatePreview['impact']; requires_force: boolean }
        setPreview({ diff: d.diff, impact: d.impact, requires_force: d.requires_force, spec: parsed.spec! })
        message.warning('模板变更包含破坏性影响，请查看预览后勾选确认')
        return
      }
      const msg = err instanceof Error ? err.message : '保存失败'
      setSpecError(msg)
      message.error(msg)
    },
  })

  const submitting = saveMutation.isPending || previewMutation.isPending

  const onOk = async () => {
    if (parsed.error || !parsed.spec) {
      setSpecError(parsed.error ?? '规格无效')
      return
    }
    if (template && !preview) {
      // 第一次保存先强制预览：用户必须看到「已有数据会怎样」
      try {
        const data = await workspaceTemplateApi.preview(template.id, parsed.spec)
        setPreview(data)
        if (data.requires_force) {
          message.warning('检测到破坏性变更，请查看预览并勾选确认')
          return
        }
        saveMutation.mutate()
      } catch (err) {
        const msg = err instanceof Error ? err.message : '预览失败'
        setSpecError(msg)
        message.error(msg)
      }
      return
    }
    if (preview?.requires_force && !force) {
      message.warning('请先勾选「我已知晓影响」再保存')
      return
    }
    saveMutation.mutate()
  }

  return (
    <Modal
      title={template ? `编辑模板：${template.name}（v${template.version}）` : '新建工作区模板'}
      open={open}
      onCancel={onClose}
      onOk={onOk}
      okText={template ? '保存并同步' : '创建模板'}
      cancelText="取消"
      confirmLoading={submitting}
      width={860}
      destroyOnHidden
      data-testid="template-editor-modal"
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            addonBefore="名称"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="例如：科研项目全生命周期管理"
            data-testid="template-name"
          />
          <Input addonBefore="分类" value={category} onChange={e => setCategory(e.target.value)} placeholder="例如：科研管理" />
        </Space.Compact>
        <Input value={description} onChange={e => setDescription(e.target.value)} placeholder="模板说明（可选）" />
        {template && (
          <Input value={summary} onChange={e => setSummary(e.target.value)} placeholder="本次变更说明（写入版本历史）" />
        )}
        <div>
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
            规格 JSON：forms（表单 / 字段）、documents（文档规则）、stages（生命周期阶段与门禁）。
            阶段必须引用已定义的表单 / 文档 key，且所有表单 / 文档都要被某个阶段引用。
          </Text>
        </div>
        <Input.TextArea
          value={text}
          onChange={e => { setText(e.target.value); setPreview(null); setForce(false) }}
          autoSize={{ minRows: 12, maxRows: 24 }}
          style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 'var(--cn-text-xs)' }}
          data-testid="template-spec-text"
          aria-label="模板规格 JSON"
        />
        {specError && <Alert type="error" showIcon message={specError} />}
        {preview && <TemplatePreviewPanel preview={preview} />}
        {preview?.requires_force && (
          <Checkbox checked={force} onChange={e => setForce(e.target.checked)} data-testid="template-force-check">
            我已知晓影响，确认保存（存量表 / 字段 / 文档不会被删除，仅增量补齐）
          </Checkbox>
        )}
        {template && (
          <Space>
            <a onClick={() => previewMutation.mutate()} data-testid="template-preview-btn">预览变更与已有数据影响</a>
            {previewMutation.isPending && <Spin size="small" />}
          </Space>
        )}
      </Space>
    </Modal>
  )
}
