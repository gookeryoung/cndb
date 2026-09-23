/** 新建 / 编辑字段 Modal + 类型感知默认值输入 DefaultValueInput.
 *
 * 从 FieldManager 拆出：外层 Modal / 通用属性表单在此，
 * 类型专属 config 编辑区在 typeConfigPanel.tsx 的 ConfigEditor.
 */
import { useEffect } from 'react'
import { Modal, Row, Col, Form, Input, Select, Checkbox, InputNumber, Radio, DatePicker, Switch, Tooltip } from 'antd'
import type { Field, FieldType, TableSummary } from '@/api'
import dayjs from 'dayjs'
import { FIELD_TYPE_OPTIONS, getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import HelpTip from '@/components/HelpTip'
import { ConfigEditor, defaultConfigForType } from './typeConfigPanel'
import { formatIncrementExample } from './FieldList'

interface FieldEditorProps {
  open: boolean
  /** null 表示新建，非 null 为正在编辑的字段 */
  editTarget: Field | null
  /** 当前选中的字段类型（决定 config 编辑区与默认值控件） */
  fieldType: FieldType | undefined
  form: ReturnType<typeof Form.useForm>[0]
  wid: string
  tid: string
  tables: TableSummary[]
  submitPending: boolean
  onSubmit: () => void
  onCancel: () => void
  /** 切换字段类型时回调（父层更新 fieldType 状态） */
  onFieldTypeChange: (type: FieldType) => void
}

/** 新建 / 编辑字段的内部 Modal（Modal 与嵌入模式共用） */
export default function FieldEditor({ open, editTarget, fieldType, form, wid, tid, tables, submitPending, onSubmit, onCancel, onFieldTypeChange }: FieldEditorProps) {
  return (
    <Modal
      title={editTarget ? '编辑字段' : '新建字段'}
      open={open}
      destroyOnHidden={false}
      onCancel={onCancel}
      onOk={onSubmit}
      confirmLoading={submitPending}
      width={640}
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
            <Form.Item
              name="field_type"
              label={<>类型<HelpTip title="类型决定数据的存储格式与编辑控件，选择后可在下方配置专属选项" /></>}
              rules={[{ required: true, message: '请选择类型' }]}
            >
              <Select
                showSearch
                options={FIELD_TYPE_OPTIONS.map(t => ({ label: `${t.label}（${t.category}）`, value: t.value }))}
                filterOption={(input, option) => {
                  const label = (option?.label as string) ?? ''
                  return label.toLowerCase().includes(input.toLowerCase())
                }}
                onChange={(v) => {
                  onFieldTypeChange(v)
                  // 编辑时切换类型：重置 config 为新类型的默认值（避免旧类型 config 残留）
                  if (editTarget && v !== editTarget.field_type) {
                    const defaults = defaultConfigForType(v)
                    form.setFieldValue('config', defaults)
                  }
                }}
              />
            </Form.Item>
          </Col>
        </Row>

        {/* 通用属性：内联 Checkbox 紧凑一行，默认值占右侧宽位 */}
        <Row gutter={12} align="middle">
          <Col span={4}>
            <Form.Item name="required" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Checkbox>必填</Checkbox>
            </Form.Item>
          </Col>
          <Col span={4} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Form.Item name="is_unique" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Checkbox>唯一</Checkbox>
            </Form.Item>
            <HelpTip title="唯一：该列不允许出现重复值，适合工号、邮箱等标识字段" />
          </Col>
          <Col span={6} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Form.Item name="hidden" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Checkbox>视图中隐藏</Checkbox>
            </Form.Item>
            <HelpTip title="隐藏：默认不在表格中显示该列，可在显示模式中重新打开" />
          </Col>
          <Col span={13}>
            {/* 注册 default_value 到 Form store，让 DefaultValueInput 内的 useWatch / setFieldValue
                能正常工作（与 ConfigEditor 里注册 config 同模式） */}
            <Form.Item name="default_value" hidden>
              <Input />
            </Form.Item>
            <Form.Item label="默认值（可选）" style={{ marginBottom: 0 }}>
              <DefaultValueInput fieldType={fieldType} form={form} />
            </Form.Item>
          </Col>
        </Row>

        {/* 类型专属 config 编辑区 */}
        {fieldType && <ConfigEditor fieldType={fieldType} form={form} wid={wid} tid={tid} tables={tables} isEdit={!!editTarget} editTargetId={editTarget?.id ?? null} />}
      </Form>
    </Modal>
  )
}

// ─────────────── 动态默认值输入组件 ───────────────

/** 哪些字段类型不支持默认值（link 需指定具体关联行，attachment 是二进制） */
const NO_DEFAULT_VALUE_TYPES = new Set<FieldType>(['link', 'attachment', 'timestamp'])

/** 把 config.options（后端格式：[{label,value,color}] 或字符串数组）转成 antd Select options */
function buildSelectOptions(raw: unknown): Array<{ label: string; value: string }> {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') return { label: item, value: item }
      if (item && typeof item === 'object') {
        const o = item as Record<string, unknown>
        const label = String(o.label ?? '')
        const val = String(o.value ?? label)
        return { label: label || val, value: val || label }
      }
      return null
    })
    .filter((o): o is { label: string; value: string } => !!o && o.label !== '')
}

/** 动态默认值输入 —— 按字段类型渲染最合适的控件，保证编辑体验与字段类型语义一致.
 *
 * 组件自己通过 Form.useWatch / form.setFieldValue 管理 default_value 的读写，
 * Form.Item 仅负责 label 展示（不再直接注入 value/onChange）。
 *
 * 核心联动：
 *  - select / multiselect 从 config.options 读选项，选项变化时自动清空已不在列表中的默认值
 *  - date / datetime 用 DatePicker，值与 form store 之间做 dayjs ↔ 字符串互转
 *  - multiselect antd 返回 string[]，提交前会被后端自动 join 为逗号分隔字符串
 *  - text 支持「静态值 / 自动编号」两种默认值模式（自动编号参数写入 config，建行时由后端生成）
 *  - link / attachment / timestamp 不支持默认值，统一显示禁用态
 */
function DefaultValueInput({ fieldType, form }: { fieldType: FieldType | undefined; form: ReturnType<typeof Form.useForm>[0] }) {
  // 订阅 default_value 本身 + config.options（select/multiselect 用）+ config 自动编号配置（text 用）
  const value = Form.useWatch('default_value', form) as unknown
  const optionsRaw = Form.useWatch(['config', 'options'], form)
  const defaultMode = Form.useWatch(['config', 'default_mode'], form) as string | undefined
  const incrementPrefix = Form.useWatch(['config', 'increment_prefix'], form) as string | undefined
  const incrementPadding = Form.useWatch(['config', 'increment_padding'], form) as number | undefined
  const incrementStart = Form.useWatch(['config', 'increment_start'], form) as number | undefined
  const selectOptions = buildSelectOptions(optionsRaw)

  const setValue = (v: unknown) => form.setFieldValue('default_value', v)

  /** 把自动编号模式/参数写入 config（读取现有 config 合并，避免覆盖 options 等其他键）.
   *
   * 每次写入生成全新对象引用，保证 useWatch 订阅方能稳定感知变更。
   */
  const setIncrementConfig = (patch: Record<string, unknown>) => {
    const cfg = (form.getFieldValue('config') as Record<string, unknown> | undefined) ?? {}
    form.setFieldValue('config', { ...cfg, ...patch })
  }

  // select / multiselect 选项变化后，若当前默认值已不在选项中，自动清空
  useEffect(() => {
    if (!fieldType) return
    if (fieldType === 'select') {
      if (value != null && value !== '' && !selectOptions.some(o => o.value === String(value))) {
        form.setFieldValue('default_value', undefined)
      }
    } else if (fieldType === 'multiselect') {
      if (Array.isArray(value)) {
        const allowed = new Set(selectOptions.map(o => o.value))
        const filtered = value.filter(v => allowed.has(String(v)))
        if (filtered.length !== value.length) {
          form.setFieldValue('default_value', filtered.length > 0 ? filtered : undefined)
        }
      }
    }
  }, [selectOptions, fieldType, value, form])

  if (!fieldType) {
    return <Input placeholder="先选择字段类型" disabled />
  }

  if (NO_DEFAULT_VALUE_TYPES.has(fieldType)) {
    return (
      <Tooltip title={`${getFieldTypeLabel(fieldType)} 类型暂不支持默认值`}>
        <Input disabled placeholder="不支持" />
      </Tooltip>
    )
  }

  switch (fieldType) {
    // ── 单选：从选项列表取值 ──
    case 'select': {
      return (
        <Select
          style={{ width: '100%' }}
          placeholder={selectOptions.length === 0 ? '请先在下方添加选项' : '请选择默认值'}
          options={selectOptions}
          value={value !== undefined && value !== null && value !== '' ? String(value) : null}
          onChange={v => setValue(v)}
          allowClear
          disabled={selectOptions.length === 0}
        />
      )
    }

    // ── 多选：返回 string[]，后端自动 join ──
    case 'multiselect': {
      const arr = Array.isArray(value) ? value : (typeof value === 'string' && value ? value.split(',').map(s => s.trim()).filter(Boolean) : [])
      return (
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder={selectOptions.length === 0 ? '请先在下方添加选项' : '请选择默认值'}
          options={selectOptions}
          value={arr}
          onChange={v => setValue(v.length > 0 ? v : undefined)}
          allowClear
          disabled={selectOptions.length === 0}
        />
      )
    }

    // ── 布尔：Switch 直接切换 ──
    case 'boolean': {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 32 }}>
          <Switch
            checked={!!value}
            onChange={checked => setValue(checked)}
          />
          <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>
            {value === undefined || value === null ? '未设置（= false）' : value ? '是' : '否'}
          </span>
        </div>
      )
    }

    // ── 日期 / 日期时间：DatePicker ──
    case 'date':
    case 'datetime': {
      const showTime = fieldType === 'datetime'
      return (
        <DatePicker
          style={{ width: '100%' }}
          showTime={showTime ? { format: 'HH:mm:ss' } : undefined}
          format={showTime ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD'}
          placeholder={showTime ? '选择日期时间' : '选择日期'}
          value={value !== undefined && value !== null && value !== '' ? dayjs(String(value)) : null}
          onChange={(_d, dateStr) => setValue(dateStr || undefined)}
        />
      )
    }

    // ── 数字类：InputNumber ──
    case 'number':
    case 'float':
    case 'percentage': {
      const suffix = fieldType === 'percentage' ? '%' : undefined
      return (
        <InputNumber
          style={{ width: '100%' }}
          placeholder={`例如：${fieldType === 'percentage' ? '80' : '0'}`}
          value={value === undefined || value === null || value === '' ? undefined : Number(value)}
          onChange={v => setValue(v === null || v === undefined ? undefined : v)}
          suffix={suffix}
        />
      )
    }

    // ── 单行文本：静态默认值 / 自动编号 两种模式切换 ──
    case 'text': {
      const isAuto = defaultMode === 'auto_increment'
      return (
        <div>
          <Radio.Group
            size="small"
            value={isAuto ? 'auto_increment' : 'static'}
            onChange={(e) => {
              if (e.target.value === 'auto_increment') {
                // 自动编号模式：清掉静态默认值，补齐编号参数（已存值优先）
                setValue(undefined)
                setIncrementConfig({
                  default_mode: 'auto_increment',
                  increment_prefix: incrementPrefix ?? '',
                  increment_padding: incrementPadding ?? 4,
                  increment_start: incrementStart ?? 1,
                })
              } else {
                setIncrementConfig({ default_mode: '' })
              }
            }}
          >
            <Radio.Button value="static">静态值</Radio.Button>
            <Radio.Button value="auto_increment">自动编号</Radio.Button>
          </Radio.Group>
          {isAuto ? (
            <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Input
                size="small"
                style={{ width: 140 }}
                placeholder="前缀，如 PRJ-"
                value={incrementPrefix ?? ''}
                onChange={(e) => setIncrementConfig({ increment_prefix: e.target.value })}
              />
              {/* InputNumber 的 addonBefore 已被 antd v5 废弃（触发弃用警告），改用 span 标签 */}
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                补零
                <InputNumber
                  size="small"
                  min={0}
                  max={10}
                  style={{ width: 72 }}
                  value={incrementPadding ?? 4}
                  onChange={(v) => setIncrementConfig({ increment_padding: v ?? 0 })}
                />
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                起始
                <InputNumber
                  size="small"
                  min={0}
                  style={{ width: 72 }}
                  value={incrementStart ?? 1}
                  onChange={(v) => setIncrementConfig({ increment_start: v ?? 0 })}
                />
              </span>
              <span style={{ color: 'var(--cn-text-secondary)', fontSize: 12 }}>
                示例：{formatIncrementExample({ increment_prefix: incrementPrefix, increment_padding: incrementPadding, increment_start: incrementStart })}（新增行保存时自动生成，不预填）
              </span>
            </div>
          ) : (
            <Input
              size="small"
              style={{ marginTop: 8 }}
              placeholder="可留空；填写后新建行将自动填入该文本"
              allowClear
              value={value === undefined || value === null ? '' : String(value)}
              onChange={(e) => setValue(e.target.value || undefined)}
            />
          )}
        </div>
      )
    }

    // ── 其他文本类：保留 Input ──
    default: {
      return (
        <Input
          placeholder={`例如：默认${getFieldTypeLabel(fieldType)}`}
          allowClear
          value={value === undefined || value === null ? '' : String(value)}
          onChange={e => setValue(e.target.value || undefined)}
        />
      )
    }
  }
}
