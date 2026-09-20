import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Modal, Button, Tag, Input, Select, Form, Row, Col, Popconfirm, Checkbox, InputNumber, Radio, ColorPicker, DatePicker, Switch, Tooltip, message, Alert, Empty, Spin, Divider } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, ImportOutlined, SwapOutlined, CloseCircleOutlined, CheckCircleOutlined, MinusOutlined, ThunderboltOutlined, BgColorsOutlined, FontSizeOutlined, AlignLeftOutlined, CheckSquareOutlined, FieldNumberOutlined, PercentageOutlined, CalendarOutlined, ClockCircleOutlined, FieldTimeOutlined, TagOutlined, TagsOutlined, MailOutlined, LinkOutlined, PhoneOutlined, ApartmentOutlined, PaperClipOutlined, SettingOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fieldApi, tableApi } from '@/api'
import type { Field, FieldCreate, FieldType, TableSummary, FieldImportResponse as FieldImportResponseType, FieldImportSuggestion } from '@/api'
import dayjs from 'dayjs'
import { resolveTagColor, suggestColorsForLabels } from '@/utils/tagColors'
import { FIELD_TYPE_OPTIONS, getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import HelpTip from '@/components/HelpTip'

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

/** 字段类型 → 图标（字段行卡片等场景共用；历史别名类型走 TagOutlined 兜底） */
const FIELD_TYPE_ICONS: Partial<Record<FieldType, ReactNode>> = {
  text: <FontSizeOutlined />,
  longtext: <AlignLeftOutlined />,
  boolean: <CheckSquareOutlined />,
  number: <FieldNumberOutlined />,
  float: <FieldNumberOutlined />,
  percentage: <PercentageOutlined />,
  date: <CalendarOutlined />,
  datetime: <ClockCircleOutlined />,
  timestamp: <FieldTimeOutlined />,
  select: <TagOutlined />,
  multiselect: <TagsOutlined />,
  email: <MailOutlined />,
  url: <LinkOutlined />,
  phone: <PhoneOutlined />,
  link: <ApartmentOutlined />,
  attachment: <PaperClipOutlined />,
}

/** 把后端 SelectOption 格式归一化为前端编辑用的 { key, label, value, color }.
 *
 * 归一化后对 color 为空的选项按 `resolveTagColor` 自动补色（与表格渲染完全同源），
 * 保证编辑字段打开即与数据表所见一致；保存时随 syncToForm 落库实现永久同步。
 */
function normalizeOptionsFromConfig(raw: unknown): Array<{ key: string; label: string; value: string | number; color: string }> {
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

/** 字段行的备注文字：必填/唯一状态 + 默认值/自动编号 + 自动填充规则（备注风格，无任何状态则返回空串不渲染） */
export function fieldNoteText(f: Field): string {
  const parts: string[] = []
  if (f.required) parts.push('必填')
  if (f.is_unique) parts.push('唯一')
  const defaultMode = (f.config?.default_mode as string) ?? ''
  if (f.field_type === 'text' && defaultMode === 'auto_increment') {
    parts.push(`自动编号：${formatIncrementExample(f.config)} 起`)
  } else if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
    parts.push(`默认值：${String(f.default_value)}`)
  }
  const autoFill = (f.config?.auto_fill as string) ?? ''
  if ((f.field_type === 'date' || f.field_type === 'datetime') && autoFill) {
    parts.push(autoFill === 'on_create' ? '创建时自动填充' : '更新时自动填充')
  }
  return parts.join(' · ')
}

/** 由自动编号 config 拼出示例编号（如 PRJ-0001），供备注与默认值编辑器共用 */
export function formatIncrementExample(config: Record<string, unknown> | undefined): string {
  const prefix = String(config?.increment_prefix ?? '')
  const paddingNum = Number(config?.increment_padding ?? 4)
  const padding = Number.isFinite(paddingNum) ? Math.max(0, Math.min(10, Math.trunc(paddingNum))) : 4
  const startNum = Number(config?.increment_start ?? 1)
  const start = Number.isFinite(startNum) ? Math.max(0, Math.trunc(startNum)) : 1
  return `${prefix}${String(start).padStart(padding, '0')}`
}

export default function FieldManager({ open, wid, tid, fields, onClose, onChanged, embedded }: Props) {
  const [innerOpen, setInnerOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Field | null>(null)
  const [form] = Form.useForm()
  const [fieldType, setFieldType] = useState<FieldType | undefined>()
  const sorted = useMemo(() => [...fields].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)), [fields])

  // ── 从其他表引入对话框状态 ──
  const [importOpen, setImportOpen] = useState(false)
  const [sourceTableId, setSourceTableId] = useState<number | string | null>(null)
  const [importSelectedIds, setImportSelectedIds] = useState<Array<number | string>>([])
  const [importSkipConflicts, setImportSkipConflicts] = useState(true)
  // 新增：预览返回的 suggestions + gap_analysis
  const [importPreview, setImportPreview] = useState<FieldImportResponseType | null>(null)
  const [importMapping, setImportMapping] = useState<Record<string, string | null>>({})
  const [importPreviewLoading, setImportPreviewLoading] = useState(false)

  // 拉取当前工作区表列表（link 字段用 + 引入来源选择）
  const { data: tables = [] } = useQuery<TableSummary[]>({
    queryKey: ['tables', wid],
    queryFn: () => tableApi.list(wid),
    enabled: open && (innerOpen || importOpen),
  })

  // 拉取选中源表的字段列表
  const { data: sourceFields = [], isFetching: sourceFieldsLoading } = useQuery<Field[]>({
    queryKey: ['fields', wid, sourceTableId],
    queryFn: () => fieldApi.list(wid, String(sourceTableId!)),
    enabled: importOpen && !!sourceTableId && String(sourceTableId) !== String(tid),
  })

  const create = useMutation({
    mutationFn: (data: FieldCreate) => fieldApi.create(wid, tid, data),
    onSuccess: () => { message.success('已添加字段'); closeDialog(); onChanged() },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建字段失败'),
  })
  const update = useMutation({
    mutationFn: (args: { fid: number | string; data: Partial<Field> }) => fieldApi.update(wid, tid, args.fid, args.data),
    onSuccess: () => { message.success('已更新'); closeDialog(); onChanged() },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新字段失败'),
  })
  const remove = useMutation({
    mutationFn: (fid: number | string) => fieldApi.remove(wid, tid, fid),
    onSuccess: () => { message.success('已删除'); onChanged() },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除字段失败'),
  })

  // ── 预览建议映射 ──
  const runPreview = async () => {
    if (!sourceTableId) return
    setImportPreviewLoading(true)
    try {
      const resp = await fieldApi.importFields(wid, tid, {
        source_table_id: Number(sourceTableId),
        field_ids: importSelectedIds.length > 0 ? importSelectedIds.map(Number) : undefined,
        import_all_fields: importSelectedIds.length === 0,
        skip_conflicts: importSkipConflicts,
        preview_only: true,
      })
      setImportPreview(resp)
      // 用 suggestions 初始化 importMapping
      const mapping: Record<string, string | null> = {}
      resp.suggestions?.forEach((s: FieldImportSuggestion) => {
        mapping[s.source] = s.will_map && s.target ? s.target : null
      })
      setImportMapping(mapping)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '预览失败'
      message.error(msg)
    } finally {
      setImportPreviewLoading(false)
    }
  }

  const importMutation = useMutation({
    mutationFn: () => {
      if (!sourceTableId) return Promise.reject(new Error('未选择源表'))
      return fieldApi.importFields(wid, tid, {
        source_table_id: Number(sourceTableId),
        field_ids: importSelectedIds.length > 0 ? importSelectedIds.map(Number) : undefined,
        import_all_fields: importSelectedIds.length === 0,
        skip_conflicts: importSkipConflicts,
        // 把用户调整后的 mapping 传过去（null 条目表示跳过）
        field_mapping: importMapping,
      })
    },
    onSuccess: (resp) => {
      const parts: string[] = [`成功引入 ${resp.created.length} 个字段`]
      if (resp.skipped.length > 0) parts.push(`已跳过 ${resp.skipped.length} 个字段`)
      message.success(parts.join('，'))
      closeImportDialog()
      onChanged()
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : '引入失败'
      message.error(msg)
    },
  })

  function closeDialog() {
    // 先 resetFields（此时内层 Modal 的 Form 还在 DOM 里），再关闭 Modal；
    // 若先 setInnerOpen(false) 则 Form 可能已被 Modal 卸载，form 实例找不到 Form 元素而报 warning.
    form.resetFields()
    setInnerOpen(false)
    setEditTarget(null)
    setFieldType(undefined)
  }

  function openImportDialog() {
    setSourceTableId(null)
    setImportSelectedIds([])
    setImportSkipConflicts(true)
    setImportOpen(true)
  }

  function closeImportDialog() {
    setImportOpen(false)
    setSourceTableId(null)
    setImportSelectedIds([])
    setImportPreview(null)
    setImportMapping({})
  }

  /** 打开新建/编辑对话框 */
  function openDialog(target: Field | null) {
    setEditTarget(target)
    setInnerOpen(true)
    if (target) {
      // 先设置 fieldType，让 ConfigEditor 也能拿到正确类型
      setFieldType(target.field_type)
      // 用 setTimeout 推入下一个事件循环，确保内层 Modal + Form 完成首次挂载
      // 同步调用 setFieldsValue 会因 Form.Item 尚未挂载而丢失值
      setTimeout(() => {
        form.setFieldsValue({
          name: target.name,
          field_type: target.field_type,
          required: target.required,
          hidden: target.hidden,
          is_unique: target.is_unique ?? false,
          default_value: target.default_value ?? '',
          // 类型默认值打底、已存值覆盖：存量/引入字段缺失的 config 键（如 auto_fill）
          // 补上默认值，保证编辑时对应控件（Radio 等）总有激活态
          config: { ...defaultConfigForType(target.field_type), ...(target.config ?? {}) },
        })
      }, 0)
    } else {
      // 同样延迟到下一个 tick —— setInnerOpen(true) 是异步批处理，
      // 在 React 提交更新前 Form 还未挂载，此时 form.resetFields() 会触发
      // "Instance created by useForm is not connected to any Form element" warning.
      setFieldType(undefined)
      setTimeout(() => { form.resetFields() }, 0)
    }
  }

  /** 提交：组装 config 后发送 */
  function handleSubmit() {
    const values = form.getFieldsValue()
    // config 已通过 <Form.Item name="config" hidden /> 注册，getFieldsValue() 包含它；
    // 读 store 作为 fallback 兼容极端边界（如 hidden Form.Item 未渲染）。
    const configFromStore = (form.getFieldValue('config') as Record<string, unknown> | undefined) ?? values.config as Record<string, unknown> | undefined ?? {}
    const payload: Record<string, unknown> = {
      name: values.name,
      field_type: values.field_type,
      required: !!values.required,
      is_unique: !!values.is_unique,
      hidden: !!values.hidden,
      config: configFromStore ?? values.config ?? {},
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
      <div className="fm-toolbar">
        <span style={{ color: 'var(--cn-text-secondary)', fontSize: 13 }}>共 {sorted.length} 个字段</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<ImportOutlined />} onClick={openImportDialog}>
            从其他表引入
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openDialog(null)}>
            新建字段
          </Button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <Empty description="暂无字段，点击右上角「新建字段」创建" style={{ padding: 32 }} />
      ) : (
        <div style={{ maxHeight: 480, overflowY: 'auto' }}>
          {sorted.map((r) => {
            return (
              <div key={String(r.id)} className="fm-row">
                <span className="fm-row-icon" title={getFieldTypeLabel(r.field_type)}>
                  {FIELD_TYPE_ICONS[r.field_type] ?? <TagOutlined />}
                </span>
                <span className="fm-row-name">{r.name}</span>
                {fieldNoteText(r) && (
                  <span className="fm-row-note" title={fieldNoteText(r)}>{fieldNoteText(r)}</span>
                )}
                <span className="fm-row-tags">
                  {r.is_primary && <Tag color="gold" style={{ marginInlineEnd: 0 }}>PK</Tag>}
                  <Tag color={getFieldTypeColor(r.field_type)} style={{ marginInlineEnd: 0 }} title={r.field_type}>
                    {getFieldTypeLabel(r.field_type)}
                  </Tag>
                  {r.hidden && <Tag style={{ marginInlineEnd: 0 }}>隐藏</Tag>}
                </span>
                <span className="fm-row-actions">
                  <Tooltip title="编辑字段类型与配置">
                    <Button size="small" type="text" icon={<EditOutlined />}
                      onClick={() => openDialog(r)} />
                  </Tooltip>
                  {!r.is_primary && (
                    <Popconfirm title="确认删除？" onConfirm={() => remove.mutate(r.id)}>
                      <Tooltip title="删除字段（列及其数据将从表中移除）">
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Tooltip>
                    </Popconfirm>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </>
  )

  /** 新建 / 编辑字段的内部 Modal（两种模式共用） */
  const editDialog = (
    <Modal
      title={editTarget ? '编辑字段' : '新建字段'}
      open={innerOpen}
      destroyOnHidden={false}
      onCancel={closeDialog}
      onOk={handleSubmit}
      confirmLoading={create.isPending || update.isPending}
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
                  setFieldType(v)
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

  // 计算哪些源字段会和当前表重名
  const existingNames = useMemo(() => new Set(fields.map(f => f.name)), [fields])
  const sourceFieldsWithConflict = useMemo(() => {
    return sourceFields.map(sf => ({
      ...sf,
      conflict: existingNames.has(sf.name),
    }))
  }, [sourceFields, existingNames])

  /** 引入对话框 */
  const importDialog = (
    <Modal
      title="从其他表引入字段"
      open={importOpen}
      onCancel={closeImportDialog}
      onOk={() => importMutation.mutate()}
      confirmLoading={importMutation.isPending}
      okText={importPreview ? `确认引入（${Object.values(importMapping).filter(v => v != null).length} 个字段）` : '确认引入'}
      cancelText="取消"
      width={780}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="字段将被复制为当前表的新字段（独立副本，不与源表保持同步）"
      />

      {/* 源表选择 */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontWeight: 500 }}>选择源表</div>
        <Select
          style={{ width: '100%' }}
          placeholder="请选择要引入字段的来源表"
          showSearch
          value={sourceTableId ?? undefined}
          onChange={(v) => { setSourceTableId(v); setImportSelectedIds([]); setImportPreview(null); setImportMapping({}) }}
          options={tables
            .filter(t => String(t.id) !== String(tid))
            .map(t => ({ label: t.name, value: t.id }))}
          filterOption={(input, option) => (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())}
        />
      </div>

      {/* 字段勾选区 */}
      {sourceTableId && String(sourceTableId) !== String(tid) && (
        <Spin spinning={sourceFieldsLoading}>
          {sourceFields.length === 0 ? (
            <Empty description="该表暂无字段" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <div>
              <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 500 }}>选择要引入的字段</span>
                <span style={{ color: '#999', fontSize: 12 }}>
                  已选 {importSelectedIds.length}/{sourceFields.length}（不选 = 全部引入）
                </span>
              </div>
              <Checkbox.Group
                value={importSelectedIds as Array<string | number>}
                onChange={(vals) => { setImportSelectedIds(vals as Array<string | number>); setImportPreview(null) }}
                style={{ width: '100%' }}
              >
                <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                  {sourceFieldsWithConflict.map((sf) => (
                    <div key={sf.id} style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Checkbox value={sf.id} disabled={sf.is_primary}>
                        <span style={{ fontWeight: sf.is_primary ? 500 : 400 }}>{sf.name}</span>
                        {sf.is_primary && <Tag color="gold" style={{ marginLeft: 4 }}>PK</Tag>}
                        <Tag color={getFieldTypeColor(sf.field_type)} style={{ marginLeft: 4 }}>{getFieldTypeLabel(sf.field_type)}</Tag>
                        {sf.conflict && (
                          <Tag color="orange" style={{ marginLeft: 4 }}>重名</Tag>
                        )}
                      </Checkbox>
                    </div>
                  ))}
                </div>
              </Checkbox.Group>

              {/* 预览按钮 */}
              <div style={{ marginTop: 12, textAlign: 'center' }}>
                <Button
                  type="primary"
                  icon={<SwapOutlined />}
                  loading={importPreviewLoading}
                  disabled={!sourceTableId}
                  onClick={runPreview}
                >
                  {importPreview ? '重新分析映射' : '分析字段映射'}
                </Button>
              </div>
            </div>
          )}
        </Spin>
      )}

      {/* 映射对比面板 */}
      {importPreview && importPreview.suggestions && importPreview.suggestions.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Divider style={{ margin: '8px 0' }}>字段映射对照</Divider>

          {/* gap_analysis 概要 */}
          {importPreview.gap_analysis && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, fontSize: 12 }}>
              <Tag color="green">已匹配 {importPreview.gap_analysis.matched.length}</Tag>
              {importPreview.gap_analysis.unmapped_source.length > 0 && (
                <Tag color="orange">待引入 {importPreview.gap_analysis.unmapped_source.length}</Tag>
              )}
              {importPreview.gap_analysis.target_missing.length > 0 && (
                <Tag color="blue">目标侧还缺 {importPreview.gap_analysis.target_missing.length} 个字段</Tag>
              )}
              {importPreview.gap_analysis.conflicts.length > 0 && (
                <Tag color="red">重名冲突 {importPreview.gap_analysis.conflicts.length}</Tag>
              )}
            </div>
          )}

          {/* 映射对比表 */}
          <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}>
            {importPreview.suggestions.map((s: FieldImportSuggestion) => {
              const isSkipped = importMapping[s.source] === null || importMapping[s.source] === undefined
              const scoreColor = s.score >= 0.9 ? '#16a34a' : s.score >= 0.75 ? '#d97706' : '#dc2626'
              // 候选目标字段：目标表已有字段 + 用户可以输入新名字
              const targetOptions = [
                ...fields.map(f => ({ label: `${f.name}（${getFieldTypeLabel(f.field_type)}）`, value: f.name })),
                { label: '新名字（在下方输入）', value: '__new__' },
                { label: '跳过（不引入）', value: '__skip__' },
              ]

              return (
                <div
                  key={s.source}
                  style={{
                    padding: '8px 12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    borderBottom: '1px solid #f5f5f5',
                    background: isSkipped ? '#fffbeb' : 'transparent',
                  }}
                >
                  {/* 源字段 */}
                  <div style={{ width: 160, flexShrink: 0 }}>
                    <div style={{ fontWeight: 500 }}>{s.source}</div>
                    <div style={{ fontSize: 11, color: '#999' }}>
                      {getFieldTypeLabel(sourceFields.find(f => f.name === s.source)?.field_type ?? 'unknown')}
                    </div>
                  </div>

                  {/* 箭头 */}
                  <div style={{ color: isSkipped ? '#999' : '#52c41a', fontSize: 18 }}>
                    {isSkipped ? <MinusOutlined /> : <SwapOutlined />}
                  </div>

                  {/* 目标字段选择 */}
                  <div style={{ flex: 1, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Select
                      size="small"
                      style={{ width: 220 }}
                      value={isSkipped ? '__skip__' : (importMapping[s.source] ?? '__skip__')}
                      options={targetOptions}
                      onChange={(val) => {
                        const next: Record<string, string | null> = { ...importMapping }
                        if (val === '__skip__') {
                          next[s.source] = null
                        } else if (val === '__new__') {
                          // 先设为源字段名本身，让用户在旁边的 Input 改
                          next[s.source] = s.source
                        } else {
                          next[s.source] = val
                        }
                        setImportMapping(next)
                      }}
                    />
                    {importMapping[s.source] !== null && importMapping[s.source] !== undefined &&
                      importMapping[s.source] !== s.source &&
                      !fields.find(f => f.name === importMapping[s.source]) && (
                        <Tooltip title="这是新输入的目标字段名">
                          <Input
                            size="small"
                            value={importMapping[s.source] ?? ''}
                            placeholder="输入新字段名"
                            onChange={(e) => {
                              const next = { ...importMapping, [s.source]: e.target.value }
                              setImportMapping(next)
                            }}
                            style={{ width: 140 }}
                          />
                        </Tooltip>
                      )}
                  </div>

                  {/* 推荐状态 + 置信度 */}
                  <Tooltip title={s.reason}>
                    <Tag
                      color={s.will_map ? 'green' : 'orange'}
                      style={{ margin: 0, fontSize: 11 }}
                      icon={s.will_map ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                    >
                      {s.will_map ? '推荐' : '低置信度'}
                    </Tag>
                  </Tooltip>
                  <span style={{ fontSize: 11, color: scoreColor, width: 42, textAlign: 'right' }}>
                    {s.score.toFixed(2)}
                  </span>
                </div>
              )
            })}
          </div>

          {/* 统计 */}
          <div style={{ marginTop: 10, fontSize: 12, color: '#64748b', textAlign: 'center' }}>
            共 {importPreview.suggestions.length} 个源字段 — 目标表当前 {fields.length} 个已有字段
          </div>
        </div>
      )}

      {/* 冲突策略 */}
      {sourceFields.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Checkbox checked={importSkipConflicts} onChange={(e) => { setImportSkipConflicts(e.target.checked); setImportPreview(null) }}>
            跳过重名字段（推荐）
          </Checkbox>
          <div style={{ color: '#999', fontSize: 12, marginTop: 2 }}>
            关闭则在重名时报错，不会执行任何引入
          </div>
        </div>
      )}
    </Modal>
  )

  // embedded 模式：直接返回内容（供 Tab / 页面嵌入）
  if (embedded) {
    return (
      <>
        {fieldListContent}
        {editDialog}
        {importDialog}
      </>
    )
  }

  // 独立模式：外层包 Modal
  return (
    <Modal title="字段管理" width={760} open={open} destroyOnHidden={false} onCancel={onClose} footer={null}>
      {fieldListContent}
      {editDialog}
      {importDialog}
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
function ConfigEditor({ fieldType, form, tables, isEdit = false, editTargetId = null }: ConfigEditorProps) {
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

  // 无配置项的字段类型直接返回 null，不显示空壳
  if (!HAS_CONFIG_TYPES.has(fieldType)) return null

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

function SelectOptionsEditor({ form }: { form: ReturnType<typeof Form.useForm>[0] }) {
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

// ─────────────── 动态默认值输入组件 ───────────────

interface DefaultValueInputProps {
  /** 当前字段类型，决定渲染哪种控件 */
  fieldType: FieldType | undefined
  /** Form 实例，用于 useWatch 订阅 default_value / config.options 及写入值 */
  form: ReturnType<typeof Form.useForm>[0]
}

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
function DefaultValueInput({ fieldType, form }: DefaultValueInputProps) {
  // 订阅 default_value 本身 + config.options（select/multiselect 用）+ config 自动编号配置（text 用）
  const value = Form.useWatch('default_value', form) as unknown
  const optionsRaw = Form.useWatch(['config', 'options'], form)
  const defaultMode = Form.useWatch(['config', 'default_mode'], form) as string | undefined
  const incrementPrefix = Form.useWatch(['config', 'increment_prefix'], form) as string | undefined
  const incrementPadding = Form.useWatch(['config', 'increment_padding'], form) as number | undefined
  const incrementStart = Form.useWatch(['config', 'increment_start'], form) as number | undefined
  const selectOptions = buildSelectOptions(optionsRaw)

  const setValue = (v: unknown) => form.setFieldValue('default_value', v)

  /** 把自动编号模式/参数写入 config（读取现有 config 合并，避免覆盖 options 等其他键） */
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
          {isAuto && (
            <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Input
                size="small"
                style={{ width: 140 }}
                placeholder="前缀，如 PRJ-"
                value={incrementPrefix ?? ''}
                onChange={(e) => setIncrementConfig({ increment_prefix: e.target.value })}
              />
              <InputNumber
                size="small"
                min={0}
                max={10}
                style={{ width: 110 }}
                addonBefore="补零"
                value={incrementPadding ?? 4}
                onChange={(v) => setIncrementConfig({ increment_padding: v ?? 0 })}
              />
              <InputNumber
                size="small"
                min={0}
                style={{ width: 110 }}
                addonBefore="起始"
                value={incrementStart ?? 1}
                onChange={(v) => setIncrementConfig({ increment_start: v ?? 0 })}
              />
              <span style={{ color: 'var(--cn-text-secondary)', fontSize: 12 }}>
                示例：{formatIncrementExample({ increment_prefix: incrementPrefix, increment_padding: incrementPadding, increment_start: incrementStart })}（新增行保存时自动生成，不预填）
              </span>
            </div>
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
