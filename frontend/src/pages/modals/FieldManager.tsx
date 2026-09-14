import { useEffect, useMemo, useState } from 'react'
import { Modal, Table, Button, Tag, Input, Select, Form, Row, Col, Popconfirm, Checkbox, InputNumber, Radio, ColorPicker, message } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, BgColorsOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fieldApi, tableApi } from '@/api'
import type { Field, FieldCreate, FieldType, TableSummary } from '@/api'
import { suggestColorForLabel } from '@/utils/tagColors'

interface Props {
  /** 非 embedded 模式下控制外层 Modal 显隐；embedded 模式下可传 true */
  open: boolean
  wid: string
  tid: string
  fields: Field[]
  onClose: () => void
  onChanged: () => void
  /** 嵌入模式：作为 Tab / 页面内容渲染，不包外层 Modal */
  embedded?: boolean
}

const FIELD_TYPES: { value: FieldType; label: string; category: string }[] = [
  { value: 'text', label: '单行文本', category: '基础' },
  { value: 'longtext', label: '多行文本', category: '基础' },
  { value: 'boolean', label: '是/否', category: '基础' },
  { value: 'number', label: '整数', category: '数字' },
  { value: 'float', label: '小数', category: '数字' },
  { value: 'percentage', label: '百分比', category: '数字' },
  { value: 'date', label: '日期', category: '日期' },
  { value: 'datetime', label: '日期时间', category: '日期' },
  { value: 'timestamp', label: '时间戳', category: '日期' },
  { value: 'select', label: '单选', category: '选择' },
  { value: 'multiselect', label: '多选', category: '选择' },
  { value: 'email', label: '邮箱', category: '高级' },
  { value: 'url', label: '链接', category: '高级' },
  { value: 'phone', label: '电话', category: '高级' },
  { value: 'link', label: '关联', category: '关联' },
  { value: 'attachment', label: '附件', category: '高级' },
]

/** 字段类型分类，决定需要渲染哪些 config 子表单 */
const TYPE_CATEGORIES = {
  basic: ['text', 'longtext', 'boolean', 'email', 'url', 'phone'],
  numeric: ['number', 'float', 'percentage'],
  date: ['date', 'datetime'],
  timestamp: ['timestamp'],
  select: ['select', 'multiselect'],
  link: ['link'],
  attachment: ['attachment'],
}

/** 把后端 SelectOption 格式归一化为前端编辑用的 { key, label, value, color } */
function normalizeOptionsFromConfig(raw: unknown): Array<{ key: string; label: string; value: string | number; color: string }> {
  if (!Array.isArray(raw)) return []
  return raw.map((item, idx) => {
    if (typeof item === 'string') {
      return { key: String(idx), label: item, value: item, color: '' }
    }
    if (typeof item === 'object' && item !== null) {
      const o = item as Record<string, unknown>
      const label = String(o.label ?? '')
      const val = o.value ?? label
      return { key: String(idx), label, value: val as string | number, color: String(o.color ?? '') }
    }
    return { key: String(idx), label: String(item), value: String(item), color: '' }
  })
}

export default function FieldManager({ open, wid, tid, fields, onClose, onChanged, embedded }: Props) {
  const [innerOpen, setInnerOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Field | null>(null)
  const [form] = Form.useForm()
  const [fieldType, setFieldType] = useState<FieldType | undefined>()
  const sorted = useMemo(() => [...fields].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)), [fields])

  // 拉取当前工作区表列表（link 字段用）
  const { data: tables = [] } = useQuery<TableSummary[]>({
    queryKey: ['tables', wid],
    queryFn: () => tableApi.list(wid),
    enabled: open && innerOpen,
  })

  const create = useMutation({
    mutationFn: (data: FieldCreate) => fieldApi.create(wid, tid, data),
    onSuccess: () => { message.success('已添加字段'); closeDialog(); onChanged() },
  })
  const update = useMutation({
    mutationFn: (args: { fid: number | string; data: Partial<Field> }) => fieldApi.update(wid, tid, args.fid, args.data),
    onSuccess: () => { message.success('已更新'); closeDialog(); onChanged() },
  })
  const remove = useMutation({
    mutationFn: (fid: number | string) => fieldApi.remove(wid, tid, fid),
    onSuccess: () => { message.success('已删除'); onChanged() },
  })

  function closeDialog() {
    setInnerOpen(false)
    setEditTarget(null)
    setFieldType(undefined)
    form.resetFields()
  }

  /** 打开新建/编辑对话框 */
  function openDialog(target: Field | null) {
    setEditTarget(target)
    setInnerOpen(true)
    if (target) {
      // 回填数据，config 直接以 Record<string, unknown> 存入表单
      form.setFieldsValue({
        name: target.name,
        field_type: target.field_type,
        required: target.required,
        hidden: target.hidden,
        is_unique: target.is_unique ?? false,
        default_value: target.default_value ?? '',
        config: target.config ?? {},
      })
      setFieldType(target.field_type)
    } else {
      form.resetFields()
      setFieldType(undefined)
    }
  }

  /** 提交：组装 config 后发送 */
  function handleSubmit() {
    const values = form.getFieldsValue()
    const payload: Record<string, unknown> = {
      name: values.name,
      field_type: values.field_type,
      required: !!values.required,
      is_unique: !!values.is_unique,
      hidden: !!values.hidden,
      config: values.config ?? {},
    }
    // 处理 default_value
    if (values.default_value !== undefined && values.default_value !== null && values.default_value !== '') {
      payload.default_value = values.default_value
    }

    if (editTarget) {
      update.mutate({ fid: editTarget.id, data: payload as Partial<Field> })
    } else {
      create.mutate(payload as unknown as FieldCreate)
    }
  }

  /** 字段列表 + 工具栏（两种模式共用的内容） */
  const fieldListContent = (
    <>
      <div style={{ marginBottom: 12, textAlign: 'right' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openDialog(null)}>
          新建字段
        </Button>
      </div>

      <Table size="small" rowKey="id" pagination={false} dataSource={sorted}
        columns={[
          { title: '名称', dataIndex: 'name', render: (v, r) => r.is_primary ? <span><Tag color="gold">PK</Tag> {v}</span> : v },
          { title: '类型', dataIndex: 'field_type', render: (v) => <Tag>{String(v)}</Tag> },
          { title: '必填', dataIndex: 'required', render: v => v ? '是' : '否', width: 70 },
          { title: '隐藏', dataIndex: 'hidden', render: v => v ? '是' : '否', width: 70 },
          {
            title: '操作', key: 'op', width: 160,
            render: (_, r) => (
              <span>
                <Button size="small" icon={<EditOutlined />} style={{ marginRight: 4 }}
                  onClick={() => openDialog(r)}>编辑</Button>
                {!r.is_primary && (
                  <Popconfirm title="确认删除？" onConfirm={() => remove.mutate(r.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </span>
            ),
          },
        ]} />
    </>
  )

  /** 新建 / 编辑字段的内部 Modal（两种模式共用） */
  const editDialog = (
    <Modal
      title={editTarget ? '编辑字段' : '新建字段'}
      open={innerOpen}
      onCancel={closeDialog}
      onOk={handleSubmit}
      confirmLoading={create.isPending || update.isPending}
      width={720}
      okText={editTarget ? '保存' : '创建'}
      cancelText="取消"
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="name" label="字段名" rules={[{ required: true, message: '请输入字段名' }]}>
              <Input placeholder="例如：姓名" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="field_type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
              <Select
                options={FIELD_TYPES.map(t => ({ label: `${t.label}（${t.category}）`, value: t.value }))}
                onChange={(v) => setFieldType(v)}
                disabled={!!editTarget}
              />
            </Form.Item>
          </Col>
        </Row>

        {/* 通用属性 */}
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item name="required" valuePropName="checked" label="必填">
              <Checkbox />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="is_unique" valuePropName="checked" label="唯一">
              <Checkbox />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="hidden" valuePropName="checked" label="在视图中隐藏">
              <Checkbox />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="default_value" label="默认值（可选）">
              <Input placeholder="例如：默认文本" allowClear />
            </Form.Item>
          </Col>
        </Row>

        {/* 类型专属 config 编辑区 */}
        {fieldType && <ConfigEditor fieldType={fieldType} form={form} wid={wid} tid={tid} tables={tables} />}
      </Form>
    </Modal>
  )

  // embedded 模式：直接返回内容（供 Tab / 页面嵌入）
  if (embedded) {
    return (
      <>
        {fieldListContent}
        {editDialog}
      </>
    )
  }

  // 独立模式：外层包 Modal
  return (
    <Modal title="字段管理" width={760} open={open} onCancel={onClose} footer={null}>
      {fieldListContent}
      {editDialog}
    </Modal>
  )
}

// ─────────────── 动态 Config 编辑器 ───────────────

interface ConfigEditorProps {
  fieldType: FieldType
  form: ReturnType<typeof Form.useForm>[0]
  wid: string
  tid: string
  tables: TableSummary[]
}

/** 哪些字段类型有可配置项 */
const HAS_CONFIG_TYPES = new Set<string>([
  ...TYPE_CATEGORIES.numeric,
  ...TYPE_CATEGORIES.date,
  ...TYPE_CATEGORIES.select,
  ...TYPE_CATEGORIES.link,
  ...TYPE_CATEGORIES.attachment,
])

/** 字段类型对应的 config 编辑器 */
function ConfigEditor({ fieldType, form, tables }: ConfigEditorProps) {
  // 监听 config 变化，保证表单 re-render
  const currentConfig = Form.useWatch('config', form) as Record<string, unknown> | undefined
  const effectiveConfig = currentConfig ?? {}

  // 初始填充：如果 config 为空则给默认值
  useEffect(() => {
    if (!currentConfig || Object.keys(currentConfig).length === 0) {
      const defaults = defaultConfigForType(fieldType)
      if (Object.keys(defaults).length > 0) {
        form.setFieldValue('config', defaults)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldType])

  // 无配置项的字段类型直接返回 null，不显示空壳
  if (!HAS_CONFIG_TYPES.has(fieldType)) return null

  // 把 config 的子字段映射到独立表单项（antd Form.Item name 支持对象路径）
  const configField = (name: string) => ({ name: ['config', ...name.split('.')] as [string, string] })

  return (
    <div style={{ marginTop: 8, borderTop: '1px dashed #d9d9d9', paddingTop: 12 }}>
      <div style={{ fontWeight: 500, marginBottom: 12 }}>字段配置</div>

      {/* ── 数字类（number / decimal / percentage） ── */}
      {TYPE_CATEGORIES.numeric.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item {...configField('min')} label="最小值">
              <InputNumber style={{ width: '100%' }} placeholder="不限" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item {...configField('max')} label="最大值">
              <InputNumber style={{ width: '100%' }} placeholder="不限" />
            </Form.Item>
          </Col>
          {fieldType !== 'percentage' && (
            <Col span={8}>
              <Form.Item {...configField('decimals')} label="小数位数" extra="整数固定 0">
                <InputNumber min={0} max={10} style={{ width: '100%' }} placeholder="0" />
              </Form.Item>
            </Col>
          )}
        </Row>
      )}

      {/* ── 日期类（date / datetime） ── */}
      {TYPE_CATEGORIES.date.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item {...configField('auto_fill')} label="自动填充" extra="创建时间/更新时间戳推荐使用">
              <Radio.Group>
                <Radio.Button value="">不自动填充</Radio.Button>
                <Radio.Button value="on_create">创建时填入当前时间</Radio.Button>
                <Radio.Button value="on_update">每次更新时覆盖</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </Col>
          {fieldType === 'datetime' && (
            <Col span={12}>
              <Form.Item {...configField('include_time')} valuePropName="checked" label="包含时间">
                <Checkbox />
              </Form.Item>
            </Col>
          )}
        </Row>
      )}

      {/* ── 选择类（select / multi_select） ── */}
      {TYPE_CATEGORIES.select.includes(fieldType) && <SelectOptionsEditor form={form} config={effectiveConfig} />}

      {/* ── 关联 link ── */}
      {TYPE_CATEGORIES.link.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item {...configField('target_table_id')} label="关联目标表" rules={[{ required: true, message: '请选择目标表' }]}>
              <Select
                showSearch
                placeholder="选择要关联的表"
                options={tables.map(t => ({ label: t.name, value: t.id }))}
                filterOption={(input, option) => (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item {...configField('multiple')} valuePropName="checked" label="允许多选" extra="勾选后一个单元格可关联多行目标数据">
              <Checkbox />
            </Form.Item>
          </Col>
        </Row>
      )}

      {/* ── 附件 attachment ── */}
      {TYPE_CATEGORIES.attachment.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item {...configField('max_size_mb')} label="单文件最大 (MB)">
              <InputNumber min={0} max={1024} style={{ width: '100%' }} placeholder="10" />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item {...configField('allowed_mime_types')} label="允许的 MIME 类型（逗号分隔，空=不限）">
              <Input placeholder="例如 image/png,image/jpeg" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item {...configField('multiple')} valuePropName="checked" label="允许多文件">
              <Checkbox />
            </Form.Item>
          </Col>
        </Row>
      )}
    </div>
  )
}

/** 根据字段类型给出初始默认 config */
function defaultConfigForType(fieldType: FieldType): Record<string, unknown> {
  switch (fieldType) {
    case 'number':
    case 'float':
      return { min: undefined, max: undefined, decimals: fieldType === 'float' ? 2 : 0 }
    case 'percentage':
      return { decimals: 0 }
    case 'date':
      return { include_time: false, auto_fill: '' }
    case 'datetime':
      return { include_time: true, auto_fill: '' }
    case 'select':
    case 'multiselect':
      return { options: [] }
    case 'link':
      return { target_table_id: undefined, multiple: true }
    case 'attachment':
      return { max_size_mb: 10, allowed_mime_types: [], multiple: true }
    default:
      return {}
  }
}

// ─────────────── 选项编辑器（select / multi_select 共享） ───────────────

/** 判断颜色值是否为 antd 预设色名（而非 HEX/CSS 自定义色） */
function isPresetColor(color: string): boolean {
  if (!color) return false
  const PRESET_NAMES = new Set([
    'blue', 'purple', 'cyan', 'green', 'magenta', 'pink', 'red',
    'orange', 'yellow', 'volcano', 'geekblue', 'lime', 'gold',
    'blue-inverse', 'purple-inverse', 'cyan-inverse', 'green-inverse',
    'magenta-inverse', 'pink-inverse', 'red-inverse',
    'orange-inverse', 'yellow-inverse', 'volcano-inverse',
    'geekblue-inverse', 'lime-inverse', 'gold-inverse',
    'success', 'processing', 'error', 'default', 'warning',
  ])
  return PRESET_NAMES.has(color)
}

function SelectOptionsEditor({ form, config }: { form: ReturnType<typeof Form.useForm>[0]; config: Record<string, unknown> }) {
  // 从 config.options 初始化（兼容旧 list[str] 格式）
  const initialOptions = useMemo(() => normalizeOptionsFromConfig(config.options), [config.options])
  const [options, setOptions] = useState(initialOptions)

  // 当外部 config.options 变化（比如切换字段类型）时同步
  useEffect(() => {
    setOptions(normalizeOptionsFromConfig(config.options))
     
  }, [config.options])

  /** 把当前编辑中的 options 同步到 form 的 config.options */
  function syncToForm(next: typeof options) {
    // 过滤空 label 后才提交
    const cleaned = next.filter(o => o.label.trim())
    // 构建后端兼容格式：如果 value == label 则存简洁格式，否则带 value
    const backend = cleaned.map(o => ({
      label: o.label.trim(),
      value: o.value,
      ...(o.color ? { color: o.color } : {}),
    }))
    form.setFieldValue(['config', 'options'], backend)
  }

  function addOption() {
    const next = [...options, { key: String(Date.now()), label: '', value: '', color: '' }]
    setOptions(next)
    syncToForm(next)
  }

  function removeOption(key: string) {
    const next = options.filter(o => o.key !== key)
    setOptions(next)
    syncToForm(next)
  }

  function updateOption(key: string, patch: Partial<(typeof options)[number]>) {
    const next = options.map(o => o.key === key ? { ...o, ...patch } : o)
    // 如果 label 变化：同步 value + 智能推荐颜色
    if (patch.label !== undefined) {
      const old = options.find(o => o.key === key)
      const idx = next.findIndex(o => o.key === key)
      if (idx >= 0) {
        const newLabel = patch.label.trim()
        // 如果 value 仍等于旧 label，同步 value
        if (old && (old.value === old.label || old.value === old.label.trim())) {
          next[idx] = { ...next[idx], value: newLabel }
        }
        // 智能推荐颜色：仅当当前 color 是预设色名（自动填充的）或为空时自动更新
        const curColor = next[idx].color
        if (!curColor || isPresetColor(curColor)) {
          const suggested = suggestColorForLabel(newLabel)
          if (suggested) {
            next[idx] = { ...next[idx], color: suggested }
          }
        }
      }
    }
    setOptions(next)
    syncToForm(next)
  }

  /** 一键智能配色：为所有选项（不管之前有没有 color）重新推荐颜色 */
  function autoColorAll() {
    const next = options.map((opt) => {
      const suggested = suggestColorForLabel(opt.label.trim())
      return { ...opt, color: suggested || '' }
    })
    setOptions(next)
    syncToForm(next)
    message.success('已为所有选项智能配色')
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span>选项列表（显示标签 + 存储值）</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <Button size="small" icon={<BgColorsOutlined />} onClick={autoColorAll}>
            一键智能配色
          </Button>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addOption}>
            添加选项
          </Button>
        </div>
      </div>
      {options.length === 0 ? (
        <div style={{ color: '#999', padding: 16, textAlign: 'center', border: '1px dashed #d9d9d9', borderRadius: 4 }}>
          暂无选项，点击上方按钮添加
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {options.map((opt, idx) => (
            <div key={opt.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#999', width: 24, textAlign: 'center' }}>{idx + 1}</span>
              <Input
                value={opt.label}
                placeholder="显示标签"
                style={{ flex: 1 }}
                onChange={(e) => updateOption(opt.key, { label: e.target.value })}
              />
              <span style={{ color: '#999' }}>=</span>
              <Input
                value={String(opt.value)}
                placeholder="存储值（数字或文本）"
                style={{ flex: 1 }}
                onChange={(e) => {
                  const v = e.target.value
                  updateOption(opt.key, { value: v })
                }}
              />
              {/* 颜色预览 + ColorPicker：antd 预设色名用 Tag 展示，支持 ColorPicker 覆盖 */}
              {opt.color ? (
                <Tag
                  color={opt.color}
                  style={{ cursor: 'pointer', margin: 0 }}
                  title={`点击选择自定义颜色（当前: ${opt.color}）`}
                  onClick={() => {
                    // 如果是预设色名，清空让 ColorPicker 打开；如果是 HEX，打开 ColorPicker
                    const picker = document.querySelector(`.ant-color-picker-trigger`) as HTMLElement | null
                    picker?.click()
                  }}
                >
                  {isPresetColor(opt.color) ? `智能:${opt.color}` : opt.color}
                </Tag>
              ) : (
                <span style={{ color: '#bbb', fontSize: 12, width: 80, textAlign: 'center' }}>
                  自动推荐
                </span>
              )}
              <ColorPicker
                value={opt.color && !isPresetColor(opt.color) ? opt.color : undefined}
                size="small"
                onChange={(color) => updateOption(opt.key, { color: color.toHexString() })}
              />
              <Button
                danger
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                onClick={() => removeOption(opt.key)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
