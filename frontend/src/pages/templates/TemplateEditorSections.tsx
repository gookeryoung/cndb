/** 模板结构化编辑器的各分区（ADR 0121 P0/P1）.
 *
 * 所有分区只读写父级传入的 `TemplateDraft`，不直接请求服务端；
 * 引用完整性、级联删除与保存由 `TemplateEditorDrawer` 统一处理。
 */

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Button, Collapse, Divider, Empty, Input, InputNumber, Modal, Select, Space, Switch, Tag, Typography,
} from 'antd'
import {
  DeleteOutlined, DownOutlined, EditOutlined, HolderOutlined, PlusOutlined, UpOutlined,
} from '@ant-design/icons'
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import {
  SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import ModuleCheckCards from '@/components/ModuleCheckCards'
import type { TemplateSpecFormFlow, TemplateSpecGroup } from '@/api'
import type { WorkspaceModule } from '@/utils/workspaceModules'
import { FIELD_TYPE_META, FIELD_TYPE_OPTIONS, getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import type { DraftDocument, DraftField, DraftFlow, DraftForm, DraftStage, DraftStep, TemplateDraft } from './templateDraft'
import { emptyDocument, emptyField, emptyFlow, emptyStage, formFlow, nextKey } from './templateDraft'

const { Text, Paragraph } = Typography

const FIELD_TYPE_CHOICES = [
  ...FIELD_TYPE_OPTIONS.map(option => ({ value: option.value as string, label: option.label })),
  { value: 'lookup', label: '引用' },
]

// ── 通用 ────────────────────────────────────────────────

export function SortableList<T extends { uid: string }>({
  items, onChange, children,
}: {
  items: T[]
  onChange: (next: T[]) => void
  children: (item: T) => ReactNode
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const handleEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const from = items.findIndex(item => item.uid === active.id)
    const to = items.findIndex(item => item.uid === over.id)
    if (from < 0 || to < 0) return
    onChange(arrayMove(items, from, to))
  }
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleEnd}>
      <SortableContext items={items.map(item => item.uid)} strategy={verticalListSortingStrategy}>
        <div className="cn-tpl-sortable">
          {items.map(item => <SortableItem key={item.uid} id={item.uid}>{children(item)}</SortableItem>)}
        </div>
      </SortableContext>
    </DndContext>
  )
}

function SortableItem({ id, children }: { id: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 }}
      className="cn-tpl-sortable-item"
    >
      <button
        type="button"
        className="cn-tpl-drag-handle"
        aria-label="拖动排序"
        {...attributes}
        {...listeners}
      >
        <HolderOutlined />
      </button>
      <div className="cn-tpl-sortable-body">{children}</div>
    </div>
  )
}

function SectionTitle({ title, hint, extra }: { title: string; hint?: string; extra?: ReactNode }) {
  return (
    <div className="cn-tpl-section-head">
      <div>
        <Text strong>{title}</Text>
        {hint && <div className="cn-tpl-hint">{hint}</div>}
      </div>
      {extra}
    </div>
  )
}

function MoveButtons({ index, total, onMove }: { index: number; total: number; onMove: (from: number, to: number) => void }) {
  return (
    <Space size={2}>
      <Button size="small" type="text" icon={<UpOutlined />} disabled={index === 0} onClick={() => onMove(index, index - 1)} aria-label="上移" />
      <Button size="small" type="text" icon={<DownOutlined />} disabled={index === total - 1} onClick={() => onMove(index, index + 1)} aria-label="下移" />
    </Space>
  )
}

export type DraftUpdater = (fn: (draft: TemplateDraft) => TemplateDraft) => void

// ── 概览 ────────────────────────────────────────────────

export function MetaSection({
  draft, onDraft, changeSummary, onChangeSummary,
}: {
  draft: TemplateDraft
  onDraft: DraftUpdater
  changeSummary: string
  onChangeSummary: (value: string) => void
}) {
  const patch = (field: keyof TemplateDraft, value: unknown) => onDraft(d => ({ ...d, [field]: value }))
  return (
    <div className="cn-tpl-section">
      <SectionTitle title="模板概览" hint="名称、说明与模块决定模板在工作区创建时的默认能力" />
      <div className="cn-tpl-form-grid">
        <label className="cn-tpl-field">
          <span>模板名称 *</span>
          <Input
            value={draft.name}
            maxLength={120}
            placeholder="例如：设备巡检工作区"
            onChange={e => patch('name', e.target.value)}
            data-testid="template-name"
          />
        </label>
        <label className="cn-tpl-field">
          <span>分类</span>
          <Input
            value={draft.category}
            maxLength={64}
            placeholder="例如：设备管理"
            onChange={e => patch('category', e.target.value)}
          />
        </label>
      </div>
      <label className="cn-tpl-field">
        <span>说明</span>
        <Input.TextArea
          value={draft.description}
          rows={2}
          placeholder="模板适用场景、包含哪些表单与文档"
          onChange={e => patch('description', e.target.value)}
        />
      </label>
      <div className="cn-tpl-field">
        <span>功能模块</span>
        <ModuleCheckCards
          value={draft.modules as WorkspaceModule[]}
          onChange={value => patch('modules', value)}
        />
      </div>
      <label className="cn-tpl-field">
        <span>本次修改说明</span>
        <Input
          value={changeSummary}
          maxLength={500}
          placeholder="保存时写入版本历史，例如：新增验收表与验收阶段"
          onChange={e => onChangeSummary(e.target.value)}
        />
      </label>
      <Paragraph type="secondary" className="cn-tpl-muted">
        模板规格由阶段、表单、文档规则和端到端流程组成；保存前会先做结构与引用检查，再展示对已有工作区的影响。
      </Paragraph>
    </div>
  )
}

// ── 阶段 ────────────────────────────────────────────────

export function StageSection({
  draft, onDraft, activeUid,
}: {
  draft: TemplateDraft
  onDraft: DraftUpdater
  activeUid?: string
}) {
  const forms = draft.forms.map(f => ({ value: f.key, label: f.name }))
  const docs = draft.documents.map(d => ({ value: d.key, label: d.title }))

  const update = (uid: string, patch: Partial<DraftStage>) => onDraft(d => ({
    ...d,
    stages: d.stages.map(stage => (stage.uid === uid ? { ...stage, ...patch } : stage)),
  }))

  const add = () => onDraft(d => ({
    ...d,
    stages: [...d.stages, emptyStage(d.stages.map(s => s.key), d.stages.map(s => s.name))],
  }))

  const remove = (stage: DraftStage) => {
    Modal.confirm({
      title: `删除阶段「${stage.name}」？`,
      content: '关联流程的阶段引用会被清空；表单与文档规则本身不会被删除。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => onDraft(d => ({
        ...d,
        stages: d.stages.filter(item => item.uid !== stage.uid),
        flows: d.flows.map(flow => (flow.stage === stage.key ? { ...flow, stage: null } : flow)),
      })),
    })
  }

  return (
    <div className="cn-tpl-section">
      <SectionTitle
        title={`生命周期阶段（${draft.stages.length}）`}
        hint="阶段顺序决定门禁顺序；表单 / 文档可被多个阶段复用"
        extra={<Button size="small" icon={<PlusOutlined />} onClick={add}>新增阶段</Button>}
      />
      {!draft.stages.length && <Empty description="还没有阶段，先新增一个" />}
      <SortableList
        items={draft.stages}
        onChange={next => onDraft(d => ({ ...d, stages: next }))}
      >
        {stage => (
          <div className={`cn-tpl-card ${activeUid === stage.uid ? 'is-active' : ''}`} data-testid={`template-stage-editor-${stage.key}`}>
            <div className="cn-tpl-card-head">
              <Space size={8}>
                <Tag color="blue">阶段</Tag>
                <Text strong>{stage.name || '未命名阶段'}</Text>
                <Text type="secondary" className="cn-tpl-code">{stage.key}</Text>
              </Space>
              <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={() => remove(stage)}>删除</Button>
            </div>
            <div className="cn-tpl-form-grid">
              <label className="cn-tpl-field">
                <span>阶段名称 *</span>
                <Input value={stage.name} maxLength={120} onChange={e => update(stage.uid, { name: e.target.value })} />
              </label>
              <label className="cn-tpl-field">
                <span>阶段 key（只读）</span>
                <Input value={stage.key} disabled />
              </label>
            </div>
            <label className="cn-tpl-field">
              <span>阶段说明</span>
              <Input.TextArea value={stage.description ?? ''} rows={2} onChange={e => update(stage.uid, { description: e.target.value })} />
            </label>
            <div className="cn-tpl-form-grid">
              <label className="cn-tpl-field">
                <span>包含表单</span>
                <Select
                  mode="multiple"
                  value={stage.forms}
                  options={forms}
                  placeholder="选择该阶段需要完成的表单"
                  onChange={value => update(stage.uid, { forms: value })}
                />
              </label>
              <label className="cn-tpl-field">
                <span>包含文档规则</span>
                <Select
                  mode="multiple"
                  value={stage.documents}
                  options={docs}
                  placeholder="选择该阶段需要提交的文档"
                  onChange={value => update(stage.uid, { documents: value })}
                />
              </label>
            </div>
          </div>
        )}
      </SortableList>
    </div>
  )
}

// ── 表单与字段 ──────────────────────────────────────────

export function FormSection({
  draft, onDraft, formUid, onDeleteForm, onAddForm,
}: {
  draft: TemplateDraft
  onDraft: DraftUpdater
  formUid?: string
  onDeleteForm: (form: DraftForm) => void
  onAddForm: () => void
}) {
  const form = draft.forms.find(f => f.uid === formUid)
  const [editing, setEditing] = useState<DraftField | null>(null)

  if (!form) {
    return (
      <div className="cn-tpl-section">
        <Empty description="从左侧选择一个表单，或新增表单" />
        <div style={{ textAlign: 'center' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={onAddForm}>新增表单</Button>
        </div>
      </div>
    )
  }

  const patchForm = (patch: Partial<DraftForm>) => onDraft(d => ({
    ...d,
    forms: d.forms.map(item => (item.uid === form.uid ? { ...item, ...patch } : item)),
  }))
  const setFields = (fields: DraftField[]) => patchForm({ fields })
  const addField = () => setEditing(emptyField(form.fields.map(f => f.name)))
  const removeField = (field: DraftField) => setFields(form.fields.filter(f => f.uid !== field.uid))
  const moveField = (from: number, to: number) => setFields(arrayMove(form.fields, from, to))
  const saveField = (next: DraftField) => {
    setFields(form.fields.some(f => f.uid === next.uid)
      ? form.fields.map(f => (f.uid === next.uid ? next : f))
      : [...form.fields, next])
    setEditing(null)
  }

  return (
    <div className="cn-tpl-section">
      <SectionTitle
        title={`表单：${form.name}`}
        hint="字段改名等于移除旧字段 + 新增字段；旧列与数据保留，新列无历史值"
        extra={<Button size="small" danger icon={<DeleteOutlined />} onClick={() => onDeleteForm(form)}>删除表单</Button>}
      />
      <div className="cn-tpl-form-grid">
        <label className="cn-tpl-field">
          <span>表单名称 *</span>
          <Input value={form.name} maxLength={255} onChange={e => patchForm({ name: e.target.value })} />
        </label>
        <label className="cn-tpl-field">
          <span>表单 key（只读）</span>
          <Input value={form.key} disabled />
        </label>
      </div>
      <label className="cn-tpl-field">
        <span>表单说明</span>
        <Input.TextArea value={form.description ?? ''} rows={2} onChange={e => patchForm({ description: e.target.value })} />
      </label>

      <Divider plain>字段（{form.fields.length}）</Divider>
      <div style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={addField}>新增字段</Button>
      </div>
      {!form.fields.length && <Empty description="至少需要一个字段" />}
      <SortableList items={form.fields} onChange={setFields}>
        {field => {
          const index = form.fields.findIndex(f => f.uid === field.uid)
          return (
            <div className="cn-tpl-field-row">
              <Space size={8} wrap>
                <Text strong>{field.name || '未命名字段'}</Text>
                <Tag color={FIELD_TYPE_META[field.type]?.color ?? 'default'}>{getFieldTypeLabel(field.type)}</Tag>
                {field.required && <Tag color="red">必填</Tag>}
                {field.is_unique && <Tag color="gold">唯一</Tag>}
                {field.hidden && <Tag>隐藏</Tag>}
              </Space>
              <Space size={2}>
                <MoveButtons index={index} total={form.fields.length} onMove={moveField} />
                <Button size="small" type="text" icon={<EditOutlined />} onClick={() => setEditing(field)}>编辑</Button>
                <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeField(field)}>删除</Button>
              </Space>
            </div>
          )
        }}
      </SortableList>

      <Divider plain>表单数据流程配置</Divider>
      <FormFlowEditor
        form={form}
        onChange={flow => patchForm({ flow })}
      />

      <FieldEditorModal
        open={editing != null}
        field={editing}
        forms={draft.forms}
        onCancel={() => setEditing(null)}
        onSave={saveField}
      />
    </div>
  )
}

function FieldEditorModal({
  open, field, forms, onSave, onCancel,
}: {
  open: boolean
  field: DraftField | null
  forms: DraftForm[]
  onSave: (field: DraftField) => void
  onCancel: () => void
}) {
  const [draft, setDraft] = useState<DraftField | null>(field)
  const [rawConfig, setRawConfig] = useState('')
  const [rawTouched, setRawTouched] = useState(false)
  const [rawError, setRawError] = useState('')

  useEffect(() => {
    setDraft(field ? { ...field, config: { ...(field.config ?? {}) } } : null)
    setRawConfig(field ? JSON.stringify(field.config ?? {}, null, 2) : '')
    setRawTouched(false)
    setRawError('')
  }, [field])

  if (!draft) return null
  const config = draft.config ?? {}
  const setConfig = (patch: Record<string, unknown>) => {
    const next = { ...config, ...patch }
    Object.keys(next).forEach(key => {
      if (next[key] === '' || next[key] == null) delete next[key]
    })
    setDraft({ ...draft, config: next })
    if (!rawTouched) setRawConfig(JSON.stringify(next, null, 2))
  }
  const configText = (key: string) => {
    const value = config[key]
    return typeof value === 'string' ? value : ''
  }
  const configNumber = (key: string) => {
    const value = config[key]
    return typeof value === 'number' ? value : null
  }

  const save = () => {
    if (!draft.name.trim()) {
      setRawError('字段名不能为空')
      return
    }
    let nextConfig = draft.config ?? {}
    if (rawTouched) {
      try {
        const parsed = JSON.parse(rawConfig)
        if (parsed == null || typeof parsed !== 'object' || Array.isArray(parsed)) {
          setRawError('高级配置必须是 JSON 对象')
          return
        }
        nextConfig = parsed as Record<string, unknown>
      } catch (error) {
        setRawError(error instanceof Error ? error.message : 'JSON 解析失败')
        return
      }
    }
    onSave({ ...draft, name: draft.name.trim(), config: nextConfig })
  }

  return (
    <Modal open={open} title="编辑字段" width={640} onCancel={onCancel} onOk={save} okText="保存字段" cancelText="取消">
      <div className="cn-tpl-form-grid">
        <label className="cn-tpl-field">
          <span>字段名 *</span>
          <Input value={draft.name} maxLength={255} onChange={e => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label className="cn-tpl-field">
          <span>类型</span>
          <Select
            value={draft.type}
            options={FIELD_TYPE_CHOICES}
            onChange={value => setDraft({ ...draft, type: value })}
          />
        </label>
      </div>
      <Space size={16} wrap style={{ marginBottom: 12 }}>
        <Space size={6}><Switch size="small" checked={draft.required} onChange={v => setDraft({ ...draft, required: v })} /><Text>必填</Text></Space>
        <Space size={6}><Switch size="small" checked={draft.is_unique} onChange={v => setDraft({ ...draft, is_unique: v })} /><Text>唯一</Text></Space>
        <Space size={6}><Switch size="small" checked={draft.hidden} onChange={v => setDraft({ ...draft, hidden: v })} /><Text>隐藏</Text></Space>
      </Space>

      <Divider plain>类型配置</Divider>
      <div className="cn-tpl-form-grid">
        <label className="cn-tpl-field">
          <span>说明</span>
          <Input value={configText('description')} onChange={e => setConfig({ description: e.target.value })} />
        </label>
        <label className="cn-tpl-field">
          <span>占位提示</span>
          <Input value={configText('placeholder')} onChange={e => setConfig({ placeholder: e.target.value })} />
        </label>
      </div>

      {(draft.type === 'select' || draft.type === 'multiselect') && (
        <label className="cn-tpl-field">
          <span>选项（每行一个，格式：显示名=值）</span>
          <Input.TextArea
            rows={4}
            value={optionsToText(config.options)}
            placeholder={'进行中=doing\n已完成=done'}
            onChange={e => setConfig({ options: textToOptions(e.target.value, config.options) })}
          />
        </label>
      )}

      {(draft.type === 'number' || draft.type === 'float' || draft.type === 'percentage') && (
        <div className="cn-tpl-form-grid">
          <label className="cn-tpl-field">
            <span>最小值</span>
            <InputNumber value={configNumber('min')} onChange={v => setConfig({ min: v })} style={{ width: '100%' }} />
          </label>
          <label className="cn-tpl-field">
            <span>最大值</span>
            <InputNumber value={configNumber('max')} onChange={v => setConfig({ max: v })} style={{ width: '100%' }} />
          </label>
          <label className="cn-tpl-field">
            <span>小数位</span>
            <InputNumber min={0} max={6} value={configNumber('decimals')} onChange={v => setConfig({ decimals: v })} style={{ width: '100%' }} />
          </label>
        </div>
      )}

      {(draft.type === 'link' || draft.type === 'lookup') && (
        <div className="cn-tpl-form-grid">
          <label className="cn-tpl-field">
            <span>关联表单</span>
            <Select
              allowClear
              value={configText('target_form') || undefined}
              options={forms.map(f => ({ value: f.key, label: f.name }))}
              onChange={value => setConfig({ target_form: value })}
              placeholder="选择要关联的模板表单"
            />
          </label>
          <label className="cn-tpl-field">
            <span>是否多选</span>
            <Select
              value={config.multiple === true ? 'multiple' : 'single'}
              options={[{ value: 'single', label: '单条' }, { value: 'multiple', label: '多条' }]}
              onChange={value => setConfig({ multiple: value === 'multiple' })}
            />
          </label>
        </div>
      )}

      {draft.type === 'formula' && (
        <label className="cn-tpl-field">
          <span>计算公式</span>
          <Input.TextArea
            rows={3}
            value={configText('formula')}
            placeholder="例如：数量 * 单价"
            onChange={e => setConfig({ formula: e.target.value })}
          />
        </label>
      )}

      {(draft.type === 'attachment' || draft.type === 'image') && (
        <div className="cn-tpl-form-grid">
          <label className="cn-tpl-field">
            <span>单文件上限（MB）</span>
            <InputNumber min={1} value={configNumber('max_size_mb')} onChange={v => setConfig({ max_size_mb: v })} style={{ width: '100%' }} />
          </label>
          <label className="cn-tpl-field">
            <span>最多数量</span>
            <InputNumber min={1} value={configNumber('max_count')} onChange={v => setConfig({ max_count: v })} style={{ width: '100%' }} />
          </label>
        </div>
      )}

      <Collapse
        size="small"
        items={[{
          key: 'raw',
          label: '高级配置（JSON）',
          children: (
            <div>
              <Text type="secondary" className="cn-tpl-muted">
                用于编辑本页未覆盖的字段配置；修改后会覆盖上面的类型配置。
              </Text>
              <Input.TextArea
                rows={6}
                value={rawConfig}
                className="cn-tpl-code"
                onChange={e => { setRawTouched(true); setRawConfig(e.target.value); setRawError('') }}
              />
              {rawError && <Text type="danger">{rawError}</Text>}
            </div>
          ),
        }]}
      />
    </Modal>
  )
}

function optionsToText(value: unknown): string {
  if (!Array.isArray(value)) return ''
  return value.map(item => {
    if (typeof item === 'string') return item
    if (item && typeof item === 'object') {
      const label = String((item as { label?: unknown }).label ?? (item as { value?: unknown }).value ?? '')
      const val = String((item as { value?: unknown }).value ?? label)
      return label === val ? label : `${label}=${val}`
    }
    return String(item)
  }).join('\n')
}

function textToOptions(text: string, previous: unknown): Array<Record<string, unknown>> {
  const previousList = Array.isArray(previous) ? previous : []
  return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => {
    const [label, value] = line.includes('=') ? line.split('=').map(part => part.trim()) : [line, line]
    const old = previousList.find(item => item && typeof item === 'object' && String((item as { value?: unknown }).value) === value)
    return old ? { ...(old as Record<string, unknown>), label, value } : { label, value }
  })
}

function FormFlowEditor({ form, onChange }: { form: DraftForm; onChange: (flow: TemplateSpecFormFlow) => void }) {
  const flow = formFlow(form)
  const fieldOptions = form.fields.map(f => ({ value: f.name, label: f.name }))
  const fieldNames = form.fields.map(f => f.name)

  const patch = (next: Partial<TemplateSpecFormFlow>) => onChange({ ...flow, ...next })
  const groups = flow.form_groups ?? []
  const detailGroups = flow.detail_groups ?? groups

  return (
    <Collapse
      size="small"
      defaultActiveKey={['flow']}
      items={[{
        key: 'flow',
        label: <Space><Text>列表 / 搜索 / 分组 / 提示</Text><Tag>{flow.enabled === false ? '已停用' : '已启用'}</Tag></Space>,
        children: (
          <div className="cn-tpl-flow-config">
            <Space size={8} wrap style={{ marginBottom: 10 }}>
              <Switch size="small" checked={flow.enabled !== false} onChange={v => patch({ enabled: v })} />
              <Text>启用数据流程</Text>
              <Switch size="small" checked={flow.allow_create !== false} onChange={v => patch({ allow_create: v })} />
              <Text>允许新增</Text>
              <Switch size="small" checked={flow.allow_edit !== false} onChange={v => patch({ allow_edit: v })} />
              <Text>允许编辑</Text>
              <Switch size="small" checked={flow.allow_delete !== false} onChange={v => patch({ allow_delete: v })} />
              <Text>允许删除</Text>
            </Space>
            <div className="cn-tpl-form-grid">
              <label className="cn-tpl-field">
                <span>列表显示字段</span>
                <Select mode="multiple" value={flow.list_fields ?? []} options={fieldOptions} onChange={value => patch({ list_fields: value })} />
              </label>
              <label className="cn-tpl-field">
                <span>可搜索字段</span>
                <Select mode="multiple" value={flow.search_fields ?? []} options={fieldOptions} onChange={value => patch({ search_fields: value })} />
              </label>
            </div>
            <GroupEditor
              title="表单分组"
              groups={groups}
              fieldOptions={fieldOptions}
              onChange={value => patch({ form_groups: value })}
            />
            <GroupEditor
              title="详情分组"
              groups={detailGroups}
              fieldOptions={fieldOptions}
              onChange={value => patch({ detail_groups: value })}
            />
            <KeyValueEditor
              title="字段提示"
              entries={flow.hints ?? {}}
              fieldOptions={fieldOptions}
              onChange={value => patch({ hints: value })}
            />
            <KeyValueEditor
              title="默认值"
              entries={flow.default_values ?? {}}
              fieldOptions={fieldOptions}
              onChange={value => patch({ default_values: value })}
            />
            <div className="cn-tpl-form-grid">
              <label className="cn-tpl-field">
                <span>默认排序字段</span>
                <Select
                  allowClear
                  value={flow.default_sort?.field}
                  options={fieldOptions}
                  onChange={value => patch({
                    default_sort: value
                      ? { field: value, order: flow.default_sort?.order ?? 'asc' }
                      : null,
                  })}
                />
              </label>
              <label className="cn-tpl-field">
                <span>排序方向</span>
                <Select
                  value={flow.default_sort?.order ?? 'asc'}
                  options={[{ value: 'asc', label: '升序' }, { value: 'desc', label: '降序' }]}
                  onChange={value => {
                    const field = flow.default_sort?.field ?? fieldNames[0]
                    if (field) patch({ default_sort: { field, order: value } })
                  }}
                />
              </label>
            </div>
            <label className="cn-tpl-field">
              <span>空状态文案</span>
              <Input value={flow.empty_text ?? ''} maxLength={200} onChange={e => patch({ empty_text: e.target.value })} />
            </label>
            <Text type="secondary" className="cn-tpl-muted">
              未纳入任何分组的可见字段会由服务端自动归入「其他信息」。
            </Text>
          </div>
        ),
      }]}
    />
  )
}

function GroupEditor({
  title, groups, fieldOptions, onChange,
}: {
  title: string
  groups: TemplateSpecGroup[]
  fieldOptions: Array<{ value: string; label: string }>
  onChange: (groups: TemplateSpecGroup[]) => void
}) {
  const update = (index: number, patch: Partial<TemplateSpecGroup>) =>
    onChange(groups.map((group, i) => (i === index ? { ...group, ...patch } : group)))
  const move = (from: number, to: number) => onChange(arrayMove(groups, from, to))
  return (
    <div className="cn-tpl-subsection">
      <SectionTitle
        title={title}
        extra={<Button size="small" icon={<PlusOutlined />} onClick={() => onChange([...groups, { title: `分组${groups.length + 1}`, fields: [] }])}>新增分组</Button>}
      />
      {!groups.length && <Text type="secondary">未配置时由服务端按默认规则生成</Text>}
      {groups.map((group, index) => (
        <div className="cn-tpl-inline-row" key={`${title}-${index}`}>
          <Input
            value={group.title}
            placeholder="分组标题"
            style={{ width: 160 }}
            onChange={e => update(index, { title: e.target.value })}
          />
          <Select
            mode="multiple"
            value={group.fields}
            options={fieldOptions}
            placeholder="选择字段"
            style={{ flex: 1 }}
            onChange={value => update(index, { fields: value })}
          />
          <MoveButtons index={index} total={groups.length} onMove={move} />
          <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => onChange(groups.filter((_, i) => i !== index))} />
        </div>
      ))}
    </div>
  )
}

function toStringEntries(entries: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(Object.entries(entries).map(([key, value]) => [key, String(value ?? '')]))
}

function KeyValueEditor({
  title, entries, fieldOptions, onChange,
}: {
  title: string
  entries: Record<string, unknown>
  fieldOptions: Array<{ value: string; label: string }>
  onChange: (entries: Record<string, string>) => void
}) {
  const rows = Object.entries(entries)
  return (
    <div className="cn-tpl-subsection">
      <SectionTitle
        title={title}
        extra={<Button size="small" icon={<PlusOutlined />} onClick={() => {
          const used = new Set(Object.keys(entries))
          const field = fieldOptions.find(option => !used.has(option.value))?.value
          if (field) onChange({ ...toStringEntries(entries), [field]: '' })
        }}>新增</Button>}
      />
      {rows.map(([name, value]) => (
        <div className="cn-tpl-inline-row" key={`${title}-${name}`}>
          <Select
            value={name}
            options={fieldOptions}
            style={{ width: 180 }}
            onChange={next => {
              const updated: Record<string, string> = {}
              Object.entries(entries).forEach(([key, val]) => {
                if (key !== name) updated[key] = String(val ?? '')
              })
              updated[next] = String(value ?? '')
              onChange(updated)
            }}
          />
          <Input
            value={String(value ?? '')}
            style={{ flex: 1 }}
            onChange={e => onChange({ ...toStringEntries(entries), [name]: e.target.value })}
          />
          <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => {
            const next = toStringEntries(entries)
            delete next[name]
            onChange(next)
          }} />
        </div>
      ))}
    </div>
  )
}

// ── 文档 ────────────────────────────────────────────────

export function DocumentSection({
  draft, onDraft, activeUid, onDeleteDocument,
}: {
  draft: TemplateDraft
  onDraft: DraftUpdater
  activeUid?: string
  onDeleteDocument: (doc: DraftDocument) => void
}) {
  const update = (uid: string, patch: Partial<DraftDocument>) => onDraft(d => ({
    ...d,
    documents: d.documents.map(doc => (doc.uid === uid ? { ...doc, ...patch } : doc)),
  }))
  return (
    <div className="cn-tpl-section">
      <SectionTitle
        title={`文档规则（${draft.documents.length}）`}
        hint="文档规则定义工作区需要维护哪些文档、是否必需与命名约定"
        extra={<Button size="small" icon={<PlusOutlined />} onClick={() => onDraft(d => ({
          ...d,
          documents: [...d.documents, emptyDocument(d.documents.map(doc => doc.key), d.documents.map(doc => doc.title))],
        }))}>新增文档</Button>}
      />
      {!draft.documents.length && <Empty description="还没有文档规则" />}
      {draft.documents.map(doc => (
        <div key={doc.uid} className={`cn-tpl-card ${activeUid === doc.uid ? 'is-active' : ''}`}>
          <div className="cn-tpl-card-head">
            <Space size={8}>
              <Tag color="orange">文档</Tag>
              <Text strong>{doc.title || '未命名文档'}</Text>
              <Text type="secondary" className="cn-tpl-code">{doc.key}</Text>
            </Space>
            <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={() => onDeleteDocument(doc)}>删除</Button>
          </div>
          <div className="cn-tpl-form-grid">
            <label className="cn-tpl-field">
              <span>文档标题 *</span>
              <Input value={doc.title} maxLength={500} onChange={e => update(doc.uid, { title: e.target.value })} />
            </label>
            <label className="cn-tpl-field">
              <span>是否必需</span>
              <div style={{ height: 32, display: 'flex', alignItems: 'center' }}>
                <Switch checked={doc.required !== false} onChange={v => update(doc.uid, { required: v })} />
              </div>
            </label>
          </div>
          <label className="cn-tpl-field">
            <span>命名规则</span>
            <Input value={doc.naming ?? ''} maxLength={500} placeholder="例如：设备编号-巡检日期" onChange={e => update(doc.uid, { naming: e.target.value })} />
          </label>
          <label className="cn-tpl-field">
            <span>初始正文</span>
            <Input.TextArea value={doc.content ?? ''} rows={5} onChange={e => update(doc.uid, { content: e.target.value })} />
          </label>
        </div>
      ))}
    </div>
  )
}

// ── 端到端流程 ──────────────────────────────────────────

export function FlowSection({
  draft, onDraft, activeUid, onDeleteFlow,
}: {
  draft: TemplateDraft
  onDraft: DraftUpdater
  activeUid?: string
  onDeleteFlow: (flow: DraftFlow) => void
}) {
  const updateFlow = (uid: string, patch: Partial<DraftFlow>) => onDraft(d => ({
    ...d,
    flows: d.flows.map(flow => (flow.uid === uid ? { ...flow, ...patch } : flow)),
  }))
  const updateStep = (flow: DraftFlow, uid: string, patch: Partial<DraftStep>) =>
    updateFlow(flow.uid, { steps: flow.steps.map(step => (step.uid === uid ? { ...step, ...patch } : step)) })
  const addStep = (flow: DraftFlow) => {
    const step: DraftStep = {
      uid: `step-${Date.now()}-${flow.steps.length + 1}`,
      key: nextKey('step', flow.steps.map(item => item.key)),
      name: `步骤${flow.steps.length + 1}`,
      description: '',
      form: null,
      documents: [],
    }
    updateFlow(flow.uid, { steps: [...flow.steps, step] })
  }

  return (
    <div className="cn-tpl-section">
      <SectionTitle
        title={`端到端流程（${draft.flows.length}）`}
        hint="流程用于业务过程展示；步骤可绑定表单与文档，也可只作为审批 / 确认节点"
        extra={<Button size="small" icon={<PlusOutlined />} onClick={() => onDraft(d => ({
          ...d,
          flows: [...d.flows, emptyFlow(d.flows.map(flow => flow.key), d.flows.map(flow => flow.name))],
        }))}>新增流程</Button>}
      />
      {!draft.flows.length && <Empty description="未配置端到端流程（旧模板由阶段自动派生）" />}
      {draft.flows.map(flow => (
        <div key={flow.uid} className={`cn-tpl-card ${activeUid === flow.uid ? 'is-active' : ''}`} data-testid={`template-flow-editor-${flow.key}`}>
          <div className="cn-tpl-card-head">
            <Space size={8}>
              <Tag color="purple">流程</Tag>
              <Text strong>{flow.name || '未命名流程'}</Text>
              <Text type="secondary" className="cn-tpl-code">{flow.key}</Text>
            </Space>
            <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={() => onDeleteFlow(flow)}>删除流程</Button>
          </div>
          <div className="cn-tpl-form-grid">
            <label className="cn-tpl-field">
              <span>流程名称 *</span>
              <Input value={flow.name} maxLength={120} onChange={e => updateFlow(flow.uid, { name: e.target.value })} />
            </label>
            <label className="cn-tpl-field">
              <span>关联阶段</span>
              <Select
                allowClear
                value={flow.stage ?? undefined}
                options={draft.stages.map(stage => ({ value: stage.key, label: stage.name }))}
                placeholder="不限定阶段"
                onChange={value => updateFlow(flow.uid, { stage: value ?? null })}
              />
            </label>
          </div>
          <label className="cn-tpl-field">
            <span>流程说明</span>
            <Input.TextArea value={flow.description ?? ''} rows={2} onChange={e => updateFlow(flow.uid, { description: e.target.value })} />
          </label>
          <Divider plain>步骤（{flow.steps.length}）</Divider>
          <div style={{ marginBottom: 8 }}>
            <Button size="small" icon={<PlusOutlined />} onClick={() => addStep(flow)}>新增步骤</Button>
          </div>
          <SortableList items={flow.steps} onChange={steps => updateFlow(flow.uid, { steps })}>
            {step => {
              const index = flow.steps.findIndex(item => item.uid === step.uid)
              return (
                <div className="cn-tpl-card cn-tpl-card--nested">
                  <div className="cn-tpl-card-head">
                    <Text strong>步骤 {index + 1} · {step.name || '未命名步骤'}</Text>
                    <Space size={2}>
                      <MoveButtons index={index} total={flow.steps.length} onMove={(from, to) => updateFlow(flow.uid, { steps: arrayMove(flow.steps, from, to) })} />
                      <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => updateFlow(flow.uid, { steps: flow.steps.filter(item => item.uid !== step.uid) })}>删除</Button>
                    </Space>
                  </div>
                  <div className="cn-tpl-form-grid">
                    <label className="cn-tpl-field">
                      <span>步骤名称 *</span>
                      <Input value={step.name} maxLength={120} onChange={e => updateStep(flow, step.uid, { name: e.target.value })} />
                    </label>
                    <label className="cn-tpl-field">
                      <span>绑定表单</span>
                      <Select
                        allowClear
                        value={step.form ?? undefined}
                        options={draft.forms.map(form => ({ value: form.key, label: form.name }))}
                        placeholder="不绑定（审批 / 确认节点）"
                        onChange={value => updateStep(flow, step.uid, { form: value ?? null })}
                      />
                    </label>
                  </div>
                  <label className="cn-tpl-field">
                    <span>关联文档规则</span>
                    <Select
                      mode="multiple"
                      value={step.documents ?? []}
                      options={draft.documents.map(doc => ({ value: doc.key, label: doc.title }))}
                      onChange={value => updateStep(flow, step.uid, { documents: value })}
                    />
                  </label>
                  <label className="cn-tpl-field">
                    <span>步骤说明</span>
                    <Input value={step.description ?? ''} maxLength={2000} onChange={e => updateStep(flow, step.uid, { description: e.target.value })} />
                  </label>
                </div>
              )
            }}
          </SortableList>
        </div>
      ))}
    </div>
  )
}

export function deleteDraftForm(draft: TemplateDraft, form: DraftForm): TemplateDraft {
  return {
    ...draft,
    forms: draft.forms.filter(item => item.uid !== form.uid),
    stages: draft.stages.map(stage => ({ ...stage, forms: stage.forms.filter(key => key !== form.key) })),
    flows: draft.flows.map(flow => ({
      ...flow,
      steps: flow.steps.map(step => (step.form === form.key ? { ...step, form: null } : step)),
    })),
  }
}

export function deleteDraftDocument(draft: TemplateDraft, doc: DraftDocument): TemplateDraft {
  return {
    ...draft,
    documents: draft.documents.filter(item => item.uid !== doc.uid),
    stages: draft.stages.map(stage => ({ ...stage, documents: stage.documents.filter(key => key !== doc.key) })),
    flows: draft.flows.map(flow => ({
      ...flow,
      steps: flow.steps.map(step => ({
        ...step,
        documents: (step.documents ?? []).filter(key => key !== doc.key),
      })),
    })),
  }
}

export function deleteDraftStage(draft: TemplateDraft, stage: DraftStage): TemplateDraft {
  return {
    ...draft,
    stages: draft.stages.filter(item => item.uid !== stage.uid),
    flows: draft.flows.map(flow => (flow.stage === stage.key ? { ...flow, stage: null } : flow)),
  }
}

export function deleteDraftFlow(draft: TemplateDraft, flow: DraftFlow): TemplateDraft {
  return { ...draft, flows: draft.flows.filter(item => item.uid !== flow.uid) }
}

