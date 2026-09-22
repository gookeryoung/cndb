/** 创建 / 编辑视图表单（合并版，消除 GridPage 里 CreateViewForm 与 EditViewForm 的 90% 重复）.
 *
 * 通过 initialName / initialType / initialOptions 三个可选 prop 区分创建 vs 编辑场景.
 *
 * 布局为「两列网格 + 分区卡片 + 可折叠」，以压缩对话框高度：原单列 vertical 布局会把
 * 该视图的全部专属配置项（kanban 多达 14 项）顺次纵向堆叠，导致对话框过长。
 * 分区归属与列宽元数据均来自 viewOptionSchema（group / optionColSpan），组件本身不硬编码。
 */

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Form, Input, Select, Switch } from 'antd'
import { RightOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import {
  COLLAPSED_BY_DEFAULT_GROUPS,
  getOptionSchema,
  groupOptionSchema,
  optionColSpan,
  resolveFieldOptions,
} from './viewOptionSchema'
import type { ViewOptionSchema } from './viewOptionSchema'
import DoneFlagFields from '../views/DoneFlagFields'

// ── 类型 ──────────────────────────────────────────

interface CreateEditViewFormProps {
  fields: Field[]
  initialName?: string
  initialType?: string
  initialOptions?: Record<string, unknown> | null
  submitLabel?: string
  onSubmit: (name: string, viewType: string, viewOptions: Record<string, unknown>) => void
}

// ── 分区卡片 ──────────────────────────────────────

interface SectionCardProps {
  title: string
  collapsed?: boolean
  collapsible?: boolean
  onToggle?: () => void
  children: ReactNode
}

/** 分区卡片：标题 + 折叠开关；collapsible=false 时标题不可点、内容常显 */
function SectionCard({ title, collapsed = false, collapsible = true, onToggle, children }: SectionCardProps) {
  return (
    <section className={`cevf-section${collapsed ? ' collapsed' : ''}`}>
      {collapsible ? (
        <button
          type="button"
          className="cevf-section-head"
          aria-expanded={!collapsed}
          onClick={onToggle}
        >
          <RightOutlined className="cevf-section-chevron" />
          <span>{title}</span>
        </button>
      ) : (
        <div className="cevf-section-head"><span>{title}</span></div>
      )}
      {!collapsed && <div className="cevf-section-body">{children}</div>}
    </section>
  )
}

// ── 单项配置控件 ──────────────────────────────────

/** 渲染单个 ViewOptionSchema item 为 Form.Item 块 */
function ConfigItem({ opt, fields, opts, updateOpt }: {
  opt: ViewOptionSchema
  fields: Field[]
  opts: Record<string, unknown>
  updateOpt: (key: string, value: unknown) => void
}) {
  const currentValue = opts[opt.key]
  const fallbackValue = opt.defaultValue

  if (opt.kind === 'switch') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip} valuePropName="checked">
        <Switch
          checked={currentValue !== false && currentValue !== undefined}
          onChange={v => updateOpt(opt.key, v)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      </Form.Item>
    )
  }

  if (opt.kind === 'direction' || opt.kind === 'enum_select' || opt.kind === 'number_enum') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip}>
        <Select
          style={{ width: '100%' }}
          value={(currentValue ?? fallbackValue) as string | number}
          onChange={v => updateOpt(opt.key, v)}
          options={opt.enumOptions?.map(o => ({ value: o.value, label: o.label })) || []}
        />
      </Form.Item>
    )
  }

  // 完成标志：字段下拉 + 匹配值复合控件（存 done_field + done_value 两键）
  if (opt.kind === 'done_flag') {
    return (
      <Form.Item label={opt.label} tooltip={opt.tooltip}>
        <DoneFlagFields
          fields={fields}
          doneField={opts.done_field as string | undefined}
          doneValue={opts.done_value}
          onChange={(patch) => Object.entries(patch).forEach(([k, v]) => updateOpt(k, v))}
        />
      </Form.Item>
    )
  }

  // field_select / field_multi_select
  const fieldOptions = resolveFieldOptions(fields, opt)
  const isMultiple = opt.kind === 'field_multi_select'
  return (
    <Form.Item label={opt.label} tooltip={opt.tooltip} required={opt.required}>
      <Select
        mode={isMultiple ? 'multiple' : undefined}
        style={{ width: '100%' }}
        allowClear
        showSearch
        placeholder={isMultiple ? '选择多个字段' : '选择字段'}
        options={fieldOptions}
        value={isMultiple ? (currentValue as string[]) || [] : ((currentValue as string) || undefined)}
        onChange={v => {
          if (isMultiple) updateOpt(opt.key, v)
          else updateOpt(opt.key, v ?? '')
        }}
      />
    </Form.Item>
  )
}

// ── 主表单组件 ──────────────────────────────────────────

/** 合并后的创建/编辑视图表单（根据 initialName 是否存在自动区分模式） */
export default function CreateEditViewForm({
  fields,
  initialName = '',
  initialType = 'grid',
  initialOptions,
  submitLabel = '创建',
  onSubmit,
}: CreateEditViewFormProps) {
  const [name, setName] = useState(initialName)
  const [vt, setVt] = useState(initialType)
  const [opts, setOpts] = useState<Record<string, unknown>>(initialOptions ? { ...initialOptions } : {})
  // 折叠状态：键为分区名；初值按 initialType 的 schema 默认收起集合预置（避免首帧展开闪烁）
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(
    () => Object.fromEntries(
      groupOptionSchema(getOptionSchema(initialType))
        .map(s => [s.label, COLLAPSED_BY_DEFAULT_GROUPS.has(s.label)]),
    ),
  )

  const sections = useMemo(() => groupOptionSchema(getOptionSchema(vt)), [vt])

  // 视图类型切换 → sections 变化 → 按新 schema 的默认收起集合重置折叠状态
  useEffect(() => {
    setCollapsed(Object.fromEntries(
      sections.map(s => [s.label, COLLAPSED_BY_DEFAULT_GROUPS.has(s.label)]),
    ))
  }, [sections])

  const toggleSection = (label: string) => {
    setCollapsed(prev => ({ ...prev, [label]: !prev[label] }))
  }

  const updateOpt = (key: string, value: unknown) => {
    setOpts(prev => {
      const next = { ...prev }
      if (value === undefined || value === null || value === '') delete next[key]
      else next[key] = value
      return next
    })
  }

  const viewTypeOptions = [
    { value: 'grid', label: '表格（Grid）' },
    { value: 'kanban', label: '看板（Kanban）' },
    { value: 'gallery', label: '画廊（Gallery）' },
    { value: 'calendar', label: '日历（Calendar）' },
    { value: 'gantt', label: '甘特图（Gantt）' },
    { value: 'wbs', label: '工作分解（WBS）' },
  ]

  return (
    <Form layout="vertical" style={{ marginTop: 8 }}>
      {/* 基础信息：两列并排，不可折叠 */}
      <SectionCard title="基础信息" collapsible={false}>
        <div className="cevf-grid">
          <div className="cevf-col-1">
            <Form.Item label="视图名称" required>
              <Input placeholder="例如：只看进行中" value={name} onChange={e => setName(e.target.value)} autoFocus />
            </Form.Item>
          </div>
          <div className="cevf-col-1">
            <Form.Item label="视图类型">
              <Select value={vt} onChange={(v) => { setVt(v); setOpts({}) }} options={viewTypeOptions} />
            </Form.Item>
          </div>
        </div>
      </SectionCard>

      {/* 视图专属配置：按 schema 分区渲染（分区卡片 + 两列网格 + 折叠） */}
      {sections.map(sec => (
        <SectionCard
          key={sec.label}
          title={sec.label}
          collapsed={!!collapsed[sec.label]}
          onToggle={() => toggleSection(sec.label)}
        >
          <div className="cevf-grid">
            {sec.items.map(opt => (
              <div
                key={opt.key}
                className={optionColSpan(opt.kind) === 2 ? 'cevf-col-2' : 'cevf-col-1'}
              >
                <ConfigItem opt={opt} fields={fields} opts={opts} updateOpt={updateOpt} />
              </div>
            ))}
          </div>
        </SectionCard>
      ))}

      <div className="cevf-footer">
        <Button type="primary" disabled={!name.trim()}
          onClick={() => onSubmit(name.trim(), vt, opts)}>{submitLabel}</Button>
      </div>
    </Form>
  )
}