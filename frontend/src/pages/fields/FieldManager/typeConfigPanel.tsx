/** 类型专属 config 编辑区 — 数字 / 日期 / 选择 / 关联 / 附件 五类配置表单.
 *
 * 从 FieldManager 拆出：ConfigEditor 按字段类型渲染对应子表单，
 * SelectOptionsEditor 为 select / multiselect 共享的选项编辑器.
 */
import { useEffect, useState } from 'react'
import { Form, Row, Col, Input, InputNumber, Checkbox, Radio, Select, Tag, Tooltip, Button, App as AntApp, ColorPicker } from 'antd'
import { PlusOutlined, DeleteOutlined, TagOutlined, BgColorsOutlined, ThunderboltOutlined, SettingOutlined } from '@ant-design/icons'
import type { FieldType, TableSummary } from '@/api'
import { resolveTagColor, suggestColorsForLabels } from '@/utils/tagColors'

/** 字段类型分类，决定需要渲染哪些 config 子表单 */
export const TYPE_CATEGORIES = {
  basic: ['text', 'longtext', 'boolean', 'email', 'url', 'phone'],
  numeric: ['number', 'float', 'percentage'],
  date: ['date', 'datetime'],
  timestamp: ['timestamp'],
  select: ['select', 'multiselect'],
  link: ['link'],
  attachment: ['attachment'],
}

/** 把后端 SelectOption 格式归一化为前端编辑用的 { key, label, value, color }.
 *
 * 归一化后对 color 为空的选项按 `resolveTagColor` 自动补色（与表格渲染完全同源），
 * 保证编辑字段打开即与数据表所见一致；保存时随 syncToForm 落库实现永久同步。
 */
export function normalizeOptionsFromConfig(raw: unknown): Array<{ key: string; label: string; value: string | number; color: string }> {
  if (!Array.isArray(raw)) return []
  const list = raw.map((item, idx) => {
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
  // 空 color 自动补色：传入原始 raw 让 resolveTagColor 按选项自身位置走同一 fallback
  return list.map((o, idx) => (o.color ? o : { ...o, color: resolveTagColor(o.label, raw, idx) }))
}

/** 根据字段类型给出初始默认 config */
export function defaultConfigForType(fieldType: FieldType): Record<string, unknown> {
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

interface ConfigEditorProps {
  fieldType: FieldType
  form: ReturnType<typeof Form.useForm>[0]
  wid: string
  tid: string
  tables: TableSummary[]
  /** 是否为编辑已有字段（编辑时不覆盖既有 config，避免 options 等配置被默认值清空） */
  isEdit?: boolean
  /** 正在编辑的字段 id（null 表示新建），用于强制 SelectOptionsEditor 在不同字段间切换时重挂载 */
  editTargetId?: number | string | null
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
export function ConfigEditor({ fieldType, form, tables, isEdit = false, editTargetId = null }: ConfigEditorProps) {
  // 关键：<Form.Item name="config" hidden /> 注册后，Form.useWatch('config', form)
  // 才能真正订阅 config 变化。此前未注册 Form.Item 导致 useWatch 永远返回 undefined，
  // ConfigEditor 不会因 form.setFieldValue 触发重渲染，SelectOptionsEditor 收到的 config
  // prop 长期停留在首帧快照。
  const currentConfig = Form.useWatch('config', form) as Record<string, unknown> | undefined

  // 初始化默认 config：仅在新建场景下、且 config 为空时填充默认值。
  // 编辑场景绝不覆盖已存 config。
  useEffect(() => {
    if (isEdit) return
    if (!HAS_CONFIG_TYPES.has(fieldType)) return
    const hasConfig = currentConfig != null && Object.keys(currentConfig).length > 0
    if (!hasConfig) {
      const defaults = defaultConfigForType(fieldType)
      if (Object.keys(defaults).length > 0) {
        form.setFieldValue('config', defaults)
      }
    }
  }, [fieldType, isEdit, currentConfig, form])

  // 无配置项的字段类型（text 等）不渲染编辑器，但仍要注册 config 根字段：
  // 缺少注册槽时 useWatch('config') 订阅不到更新、setFieldValue 写入也不生效，
  // 编辑回填的「自动编号」模式 Radio 无法激活（用户报告的"无法点开"）。
  if (!HAS_CONFIG_TYPES.has(fieldType)) {
    return <Form.Item name="config" hidden><Input /></Form.Item>
  }

  // 把 config 的子字段映射到独立表单项（antd Form.Item name 支持对象路径）
  const configField = (name: string) => ({ name: ['config', ...name.split('.')] as [string, string] })

  return (
    <div className="fm-config-section">
      {/* 注册 config 根字段，让 useWatch / getFieldsValue 能追踪它 */}
      <Form.Item name="config" hidden>
        <Input />
      </Form.Item>
      <div className="fm-config-title"><SettingOutlined />字段配置</div>

      {/* ── 数字类（number / decimal / percentage） ── */}
      {TYPE_CATEGORIES.numeric.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item {...configField('min')} label="最小值" style={{ marginBottom: 8 }}>
              <InputNumber style={{ width: '100%' }} placeholder="不限" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item {...configField('max')} label="最大值" style={{ marginBottom: 8 }}>
              <InputNumber style={{ width: '100%' }} placeholder="不限" />
            </Form.Item>
          </Col>
          {fieldType !== 'percentage' && (
            <Col span={8}>
              <Form.Item {...configField('decimals')} label="小数位数" extra="整数固定 0" style={{ marginBottom: 8 }}>
                <InputNumber min={0} max={10} style={{ width: '100%' }} placeholder="0" />
              </Form.Item>
            </Col>
          )}
        </Row>
      )}

      {/* ── 日期类（date / datetime） ── */}
      {TYPE_CATEGORIES.date.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={16}>
            <Form.Item {...configField('auto_fill')} label="自动填充" extra="创建时填入当前时间；更新时覆盖为最新时间" style={{ marginBottom: 8 }}>
              <Radio.Group size="small">
                <Radio.Button value="">不自动</Radio.Button>
                <Radio.Button value="on_create">创建时</Radio.Button>
                <Radio.Button value="on_update">更新时</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </Col>
          {fieldType === 'datetime' && (
            <Col span={8}>
              <Form.Item {...configField('include_time')} valuePropName="checked" label="包含时间" style={{ marginBottom: 8 }}>
                <Checkbox>显示时间部分</Checkbox>
              </Form.Item>
            </Col>
          )}
        </Row>
      )}

      {/* ── 选择类（select / multi_select） ── */}
      {/* key 绑定 fieldType + editTargetId：同类型不同字段切换时也强制重挂载，
          避免 SelectOptionsEditor 的 useState 停留在上一个字段的 options. */}
      {TYPE_CATEGORIES.select.includes(fieldType) && (
        <SelectOptionsEditor key={`${fieldType}-${editTargetId ?? 'new'}`} form={form} />
      )}

      {/* ── 关联 link ── */}
      {TYPE_CATEGORIES.link.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item {...configField('target_table_id')} label="关联目标表" rules={[{ required: true, message: '请选择目标表' }]} style={{ marginBottom: 8 }}>
              <Select
                showSearch
                placeholder="选择要关联的表"
                options={tables.map(t => ({ label: t.name, value: t.id }))}
                filterOption={(input, option) => (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item {...configField('multiple')} valuePropName="checked" label="允许多选" extra="勾选后一个单元格可关联多行目标数据" style={{ marginBottom: 8 }}>
              <Checkbox />
            </Form.Item>
          </Col>
        </Row>
      )}

      {/* ── 附件 attachment ── */}
      {TYPE_CATEGORIES.attachment.includes(fieldType) && (
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item {...configField('max_size_mb')} label="单文件最大 (MB)" style={{ marginBottom: 8 }}>
              <InputNumber min={0} max={1024} style={{ width: '100%' }} placeholder="10" />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item {...configField('allowed_mime_types')} label="允许的 MIME 类型（逗号分隔，空=不限）" style={{ marginBottom: 8 }}>
              <Input placeholder="例如 image/png,image/jpeg" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item {...configField('multiple')} valuePropName="checked" label="允许多文件" style={{ marginBottom: 8 }}>
              <Checkbox />
            </Form.Item>
          </Col>
        </Row>
      )}
    </div>
  )
}

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

function SelectOptionsEditor({ form }: { form: ReturnType<typeof Form.useForm>[0] }) {
  const { message } = AntApp.useApp()
  // options 的唯一真相源：首次挂载时从 form store 读一次，之后完全由本地 state 驱动。
  // 关键边界：openDialog 用 setTimeout(0) 延迟 setFieldsValue({ config })，
  // ConfigEditor/SelectOptionsEditor 先挂载 → useState lazy init 先跑（此时 Form store
  // 还没写入真实 config）→ 初始化空数组。后续 setTimeout 写入触发 useWatch 更新，
  // SelectOptionsEditor 重渲染但 useState **不会重新初始化**——这会导致"编辑已有
  // select 字段时 options 永远显示为空"。
  //
  // 因此加一个 guarded effect：仅在「外部 Form store 有值」且「内部 state 还空着」
  // 时同步一次。既修复初始化时序竞态，又不覆盖用户正在编辑的非空 state。
  const watchedOptions = Form.useWatch(['config', 'options'], form)
  const [options, setOptions] = useState(() => normalizeOptionsFromConfig(watchedOptions))

  useEffect(() => {
    const incoming = normalizeOptionsFromConfig(watchedOptions)
    if (incoming.length > 0 && options.length === 0) {
      setOptions(incoming)
      // 把自动补色后的选项同步回 form store：用户不改选项直接点保存也能把颜色落库
      syncToForm(incoming)
    }
  }, [watchedOptions])  // eslint-disable-line react-hooks/exhaustive-deps

  /** 把当前编辑中的 options 同步到 form 的 config.options.
   *
   * 后端兼容格式统一为 { label, value, color }，其中 value 恒等于 label
   * （用户不再编辑存储值，二者重复）。
   */
  function syncToForm(next: typeof options) {
    const cleaned = next.filter(o => o.label.trim())
    const backend = cleaned.map(o => {
      const label = o.label.trim()
      return {
        label,
        value: label,
        ...(o.color ? { color: o.color } : {}),
      }
    })
    form.setFieldValue(['config', 'options'], backend)
  }

  function addOption() {
    // 新增选项时按索引从调色板预分配一个颜色，label 输入后 updateOption 会再按语义调整
    const palette = ['blue', 'green', 'orange', 'purple', 'red', 'cyan', 'gold', 'magenta', 'yellow', 'volcano', 'geekblue', 'lime', 'pink']
    const preColor = palette[options.length % palette.length]!
    const next = [...options, { key: String(Date.now()), label: '', value: '', color: preColor }]
    setOptions(next)
    syncToForm(next)
  }

  function removeOption(key: string) {
    const next = options.filter(o => o.key !== key)
    setOptions(next)
    syncToForm(next)
  }

  /** 列表感知推荐：对当前选项列表全部 label 计算建议色，取指定下标的槽位.
   *
   * 语义优先；无语义 label 走分级调色板并避开其他选项已占用颜色，
   * 与后端 suggest_colors 同规则，修复"第 4 项推荐与第 1 项重复"的撞色问题。
   */
  function suggestColorAt(labels: string[], idx: number): string {
    return suggestColorsForLabels(labels)[idx] ?? 'blue'
  }

  function updateOption(key: string, patch: Partial<(typeof options)[number]>, opts?: { skipAutoColor?: boolean }) {
    const next = options.map(o => o.key === key ? { ...o, ...patch } : o)
    if (patch.label !== undefined) {
      const idx = next.findIndex(o => o.key === key)
      if (idx >= 0) {
        const newLabel = patch.label.trim()
        // label 编辑后 value 恒同步为 label，颜色也始终跟随刷新。
        // 颜色不再区分「预设色名 / HEX 自定义色」 — 只要 label 变了，语义就变了，
        // 色块必须立即匹配新语义，避免出现 label="低优先级" 但色块还是红色的陈旧态。
        if (!opts?.skipAutoColor) {
          next[idx] = { ...next[idx], value: newLabel, color: suggestColorAt(next.map(o => o.label.trim()), idx) }
        } else {
          next[idx] = { ...next[idx], value: newLabel }
        }
      }
    }
    setOptions(next)
    syncToForm(next)
  }

  /** 手动触发单个选项的智能推荐颜色（列表感知，无视当前颜色强制刷新） */
  function handleSmartSuggest(key: string) {
    const idx = options.findIndex(o => o.key === key)
    if (idx < 0) return
    const label = options[idx]!.label.trim()
    if (!label) {
      message.info('请先输入显示标签')
      return
    }
    const color = suggestColorAt(options.map(o => o.label.trim()), idx)
    updateOption(key, { color }, { skipAutoColor: true })
  }

  /** 一键对全部选项应用智能推荐颜色（覆盖式，与后端 apply_smart_colors(overwrite=True) 语义一致） */
  function handleSmartSuggestAll() {
    if (!options.some(o => o.label.trim())) {
      message.info('请先输入显示标签')
      return
    }
    const colors = suggestColorsForLabels(options.map(o => o.label.trim()))
    const next = options.map((o, i) => (o.label.trim() ? { ...o, color: colors[i] ?? o.color } : o))
    setOptions(next)
    syncToForm(next)
  }

  return (
    <div>
      <div className="fm-config-title" style={{ justifyContent: 'space-between' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><TagOutlined />选项列表</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* 全部智能推荐：一键按语义 + 避重规则为所有选项重新配色 */}
          <Tooltip title="按语义规则为所有选项一键推荐颜色">
            <Button size="small" type="dashed" icon={<BgColorsOutlined />} onClick={handleSmartSuggestAll}>
              全部智能推荐
            </Button>
          </Tooltip>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addOption}>
            添加选项
          </Button>
        </div>
      </div>
      {options.length === 0 ? (
        <div className="fm-option-empty">
          暂无选项，点击上方按钮添加
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {options.map((opt, idx) => (
            <div key={opt.key} className="fm-option-row">
              <span style={{ color: 'var(--cn-text-muted)', width: 20, textAlign: 'center', flexShrink: 0 }}>{idx + 1}</span>
              <Input
                value={opt.label}
                placeholder="显示标签"
                style={{ flex: 1 }}
                onChange={(e) => updateOption(opt.key, { label: e.target.value })}
              />
              {/* 智能推荐按钮：点击按语义规则 + hash 强制刷新颜色 */}
              <Tooltip title="智能推荐颜色">
                <Button
                  size="small"
                  type="text"
                  icon={<ThunderboltOutlined />}
                  onClick={() => handleSmartSuggest(opt.key)}
                />
              </Tooltip>
              {/* 颜色预览：antd 预设色名用 Tag 展示；HEX 自定义色显示色块 */}
              {opt.color ? (
                isPresetColor(opt.color) ? (
                  <Tag color={opt.color} style={{ margin: 0 }}>
                    {opt.color}
                  </Tag>
                ) : (
                  <span
                    style={{
                      display: 'inline-block', width: 18, height: 18, borderRadius: 4, flexShrink: 0,
                      background: opt.color, border: '1px solid var(--cn-border)',
                    }}
                    title={`自定义颜色 ${opt.color}`}
                  />
                )
              ) : null}
              <ColorPicker
                value={opt.color || undefined}
                size="small"
                onChange={(color) => updateOption(opt.key, { color: color.toHexString() }, { skipAutoColor: true })}
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
