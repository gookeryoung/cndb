/** 模板导入（需求 0120）：上传 JSON → 服务端校验预览 → 确认创建. */

import { useEffect, useState } from 'react'
import {
  Alert, App as AntApp, Descriptions, Modal, Space, Tag, Typography, Upload,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceTemplateApi } from '@/api'
import type { TemplateImportPayload, TemplateImportPreview, WorkspaceTemplate } from '@/api'

const { Text } = Typography

/** 导入文件大小上限（与卡片 C2 一致） */
const MAX_SIZE = 1024 * 1024

interface Props {
  open: boolean
  onClose: () => void
  onImported?: (template: WorkspaceTemplate) => void
}

export default function TemplateImportModal({ open, onClose, onImported }: Props) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [fileName, setFileName] = useState('')
  const [fileSize, setFileSize] = useState(0)
  const [payload, setPayload] = useState<TemplateImportPayload | null>(null)
  const [preview, setPreview] = useState<TemplateImportPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setFileName('')
    setFileSize(0)
    setPayload(null)
    setPreview(null)
    setError(null)
  }, [open])

  const previewMutation = useMutation({
    mutationFn: (data: TemplateImportPayload) => workspaceTemplateApi.importPreview(data),
    onSuccess: (data, variables) => {
      setPreview(data)
      setPayload(variables)
      setError(null)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '模板校验失败'
      setPreview(null)
      setPayload(null)
      setError(msg)
    },
  })

  const importMutation = useMutation({
    mutationFn: () => {
      if (!payload) throw new Error('请先选择模板文件')
      return workspaceTemplateApi.importFile(payload)
    },
    onSuccess: (template) => {
      message.success(`模板已导入：${template.name}`)
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
      onImported?.(template)
      onClose()
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '导入失败'
      setError(msg)
      message.error(msg)
    },
  })

  const handleFile = async (file: File) => {
    setFileName(file.name)
    setFileSize(file.size)
    setPreview(null)
    setPayload(null)
    setError(null)
    if (!file.name.toLowerCase().endsWith('.json')) {
      setError('仅支持 .json 模板文件')
      return
    }
    if (file.size > MAX_SIZE) {
      setError('文件不能超过 1MB')
      return
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(await file.text())
    } catch {
      setError('JSON 解析失败，请检查文件内容')
      return
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setError('文件内容必须是 JSON 对象')
      return
    }
    previewMutation.mutate(parsed as TemplateImportPayload)
  }

  const busy = previewMutation.isPending || importMutation.isPending

  return (
    <Modal
      title="导入工作区模板"
      open={open}
      onCancel={onClose}
      onOk={() => importMutation.mutate()}
      okText="确认导入"
      cancelText="取消"
      okButtonProps={{ disabled: !preview, loading: importMutation.isPending }}
      confirmLoading={false}
      width={640}
      destroyOnHidden
      data-testid="template-import-modal"
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Upload.Dragger
          maxCount={1}
          showUploadList={false}
          disabled={busy}
          beforeUpload={(file) => {
            void handleFile(file as unknown as File)
            return false
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 .workspace-template.json 到此处</p>
          <p className="ant-upload-hint">文件 ≤ 1MB；导入前先校验并预览，确认后创建为新模板</p>
        </Upload.Dragger>

        {fileName && (
          <Text type="secondary" data-testid="template-import-file">
            {fileName} · {(fileSize / 1024).toFixed(1)} KB
          </Text>
        )}
        {previewMutation.isPending && <Text type="secondary">正在校验模板…</Text>}
        {error && <Alert type="error" showIcon message={error} />}

        {preview && (
          <div data-testid="template-import-preview">
            {preview.renamed && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 8 }}
                message={`已有同名模板，将导入为「${preview.name}」`}
              />
            )}
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="模板名称">{preview.name}</Descriptions.Item>
              <Descriptions.Item label="分类">{preview.category || '—'}</Descriptions.Item>
              <Descriptions.Item label="模块">
                {preview.modules.length
                  ? preview.modules.map(m => <Tag key={m}>{m}</Tag>)
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="规模">
                {preview.counts.stage_count} 阶段 / {preview.counts.form_count} 表单 /{' '}
                {preview.counts.field_count} 字段 / {preview.counts.document_rule_count} 文档规则
                {preview.counts.flow_count ? ` / ${preview.counts.flow_count} 流程` : ''}
              </Descriptions.Item>
              {preview.source_version != null && (
                <Descriptions.Item label="源版本">v{preview.source_version}</Descriptions.Item>
              )}
            </Descriptions>
          </div>
        )}
      </Space>
    </Modal>
  )
}
