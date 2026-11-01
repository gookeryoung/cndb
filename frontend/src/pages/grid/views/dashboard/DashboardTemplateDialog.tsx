/** dashboard 模板对话框（ADR 0023 P3：另存为模板 / 应用模板）.
 *
 * - 另存：把当前草稿剥离来源表后存进 per-user 偏好（`dashboard-templates`）；
 * - 应用：按「同名同类型」自动认领字段，认领不到的字段由用户逐项指定，
 *   全部认领完成后仍走 `normalizeDashboard` 校验，模板不是校验后门。
 */

import { useEffect, useMemo, useState } from 'react'
import { App as AntApp, Button, Empty, Input, Modal, Select, Spin, Tooltip } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { DashboardTemplate, Field } from '@/api'
import { fieldApi, preferencesApi } from '@/api'
import { serializeDashboard, type DashboardConfig } from './dashboardModel'
import {
  applyDashboardTemplate,
  buildDashboardTemplate,
  collectTemplateTableIds,
  matchingTargetFields,
  planTemplateFields,
} from './dashboardTemplate'

export type DashboardTemplateMode = 'save' | 'apply'

export interface DashboardTemplateDialogProps {
  open: boolean
  mode: DashboardTemplateMode
  config: DashboardConfig
  fields: Field[]
  /** 工作区 id：另存时按跨表 widget 的目标表拉字段类型快照（缺省时只快照基表字段） */
  workspaceId?: string | number
  /** 另存时的默认名称（通常取视图名） */
  defaultName?: string
  onClose: () => void
  onSaved?: (template: DashboardTemplate) => void
  onApply?: (config: DashboardConfig) => void
}

const TEMPLATES_QUERY_KEY = ['dashboard-templates'] as const

function errorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? (error instanceof Error ? error.message : '操作失败')
}

export default function DashboardTemplateDialog({
  open,
  mode,
  config,
  fields,
  workspaceId,
  defaultName,
  onClose,
  onSaved,
  onApply,
}: DashboardTemplateDialogProps) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [name, setName] = useState(defaultName ?? '未命名模板')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  /** 缺失字段映射：模板字段名 -> 用户指定的目标字段名 */
  const [issueMapping, setIssueMapping] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const { data: templates = [], isLoading } = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    queryFn: preferencesApi.listDashboardTemplates,
    enabled: open && mode === 'apply',
  })

  // 每次打开 / 切换模式都重置交互状态，避免残留上一次的选择
  useEffect(() => {
    if (!open) return
    setName(defaultName ?? '未命名模板')
    setSelectedId(null)
    setIssueMapping({})
    setBusy(false)
  }, [open, mode, defaultName])

  const selected = useMemo(
    () => templates.find((t) => t.id === selectedId) ?? null,
    [templates, selectedId],
  )

  const plan = useMemo(
    () => (selected ? planTemplateFields(selected.fields, fields) : null),
    [selected, fields],
  )

  const unresolved = plan ? plan.issues.filter((issue) => !issueMapping[issue.field]) : []

  const pickTemplate = (template: DashboardTemplate) => {
    setSelectedId(template.id)
    setIssueMapping({})
  }

  /** 拉取跨表 widget 目标表的字段（失败的表跳过，只影响类型快照的完整度） */
  const fetchExtraFields = async (): Promise<Record<string, Field[]>> => {
    if (workspaceId == null) return {}
    const tableIds = collectTemplateTableIds(serializeDashboard(config))
    if (!tableIds.length) return {}
    const extra: Record<string, Field[]> = {}
    let failed = 0
    await Promise.all(tableIds.map(async (id) => {
      try {
        extra[id] = await fieldApi.list(workspaceId, id)
      } catch {
        failed += 1
      }
    }))
    if (failed) message.warning('部分跨表字段类型读取失败，模板仅保留可读字段')
    return extra
  }

  const saveTemplate = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      message.warning('请填写模板名称')
      return
    }
    if (trimmed.length > 60) {
      message.warning('模板名称最多 60 个字符')
      return
    }
    setBusy(true)
    try {
      const extraFields = await fetchExtraFields()
      const built = buildDashboardTemplate(config, fields, extraFields)
      const saved = await preferencesApi.saveDashboardTemplate({
        name: trimmed,
        config: built.config,
        fields: built.fields,
      })
      await queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY })
      message.success('已保存为模板')
      onSaved?.(saved)
      onClose()
    } catch (error) {
      message.error(`保存模板失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const deleteTemplate = async (template: DashboardTemplate) => {
    setBusy(true)
    try {
      await preferencesApi.deleteDashboardTemplate(template.id)
      await queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY })
      if (template.id === selectedId) {
        setSelectedId(null)
        setIssueMapping({})
      }
      message.success('模板已删除')
    } catch (error) {
      message.error(`删除模板失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const applyTemplate = () => {
    if (!selected || !plan) return
    if (unresolved.length) {
      message.warning('请先为缺失字段选择目标字段')
      return
    }
    try {
      const applied = applyDashboardTemplate(
        selected.config,
        { ...plan.mapping, ...issueMapping },
        fields,
      )
      onApply?.(applied)
      message.success('已应用模板')
      onClose()
    } catch (error) {
      message.error(errorText(error))
    }
  }

  const footer = mode === 'save'
    ? [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="save" type="primary" loading={busy} onClick={saveTemplate} data-testid="dashboard-template-save">
          保存模板
        </Button>,
      ]
    : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="apply"
          type="primary"
          disabled={!selected || unresolved.length > 0}
          onClick={applyTemplate}
          data-testid="dashboard-template-apply"
        >
          应用模板
        </Button>,
      ]

  return (
    <Modal
      open={open}
      title={mode === 'save' ? '另存为模板' : '从模板创建'}
      onCancel={onClose}
      footer={footer}
      width={560}
      destroyOnHidden
    >
      <div data-testid="dashboard-template-dialog" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {mode === 'save' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Input
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="模板名称（同名模板会被覆盖）"
            data-testid="dashboard-template-name"
          />
          <span style={{ fontSize: 12, color: 'var(--cn-text-secondary)' }}>
            模板只保存「结构 + 字段名/类型快照」，不绑定来源表；应用到其他表时按同名同类型认领字段。
          </span>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {isLoading ? (
            <Spin size="small" />
          ) : templates.length === 0 ? (
            <Empty description="还没有保存过模板" data-testid="dashboard-template-empty" />
          ) : (
            <div data-testid="dashboard-template-list" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {templates.map((template) => {
                const active = template.id === selectedId
                const count = Array.isArray(template.config.widgets) ? template.config.widgets.length : 0
                return (
                  <div
                    key={template.id}
                    role="button"
                    tabIndex={0}
                    data-testid={`dashboard-template-item-${template.id}`}
                    onClick={() => pickTemplate(template)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') pickTemplate(template)
                    }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', cursor: 'pointer',
                      borderRadius: 6,
                      border: `1px solid ${active ? 'var(--cn-primary)' : 'var(--cn-border)'}`,
                      background: active ? 'var(--cn-bg-selected)' : 'transparent',
                    }}
                  >
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {template.name}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--cn-text-secondary)' }}>{count} 个组件</span>
                    <Tooltip title="删除模板">
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        data-testid={`dashboard-template-delete-${template.id}`}
                        onClick={(e) => {
                          e.stopPropagation()
                          void deleteTemplate(template)
                        }}
                      />
                    </Tooltip>
                  </div>
                )
              })}
            </div>
          )}

          {selected && plan && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {plan.issues.length === 0 ? (
                <span style={{ fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                  模板中的字段都已按同名同类型自动认领。
                </span>
              ) : (
                <>
                  <span style={{ fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                    以下字段在目标表中未找到同名同类型字段，请指定映射（共 {plan.issues.length} 个）：
                  </span>
                  {plan.issues.map((issue) => (
                    <div key={issue.field} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {issue.field}
                        <span style={{ marginLeft: 4, fontSize: 12, color: 'var(--cn-text-secondary)' }}>
                          {issue.type || '未知类型'}
                        </span>
                      </span>
                      <Select
                        style={{ flex: 1 }}
                        placeholder="选择目标字段"
                        value={issueMapping[issue.field]}
                        onChange={(value) => setIssueMapping((prev) => ({ ...prev, [issue.field]: value }))}
                        options={matchingTargetFields(fields, issue.type).map((field) => ({
                          value: field.name,
                          label: `${field.name}（${field.field_type}）`,
                        }))}
                        data-testid={`dashboard-template-map-${issue.field}`}
                      />
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}
      </div>
    </Modal>
  )
}
