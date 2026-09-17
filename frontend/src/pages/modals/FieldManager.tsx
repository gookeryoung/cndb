import { useEffect, useMemo, useState } from 'react'
import { Modal, Table, Button, Tag, Input, Select, Form, Row, Col, Popconfirm, Checkbox, InputNumber, Radio, ColorPicker, message, Alert, Empty, Spin, Tooltip, Divider } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, BgColorsOutlined, ImportOutlined, SwapOutlined, CloseCircleOutlined, CheckCircleOutlined, MinusOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fieldApi, tableApi } from '@/api'
import type { Field, FieldCreate, FieldType, TableSummary, FieldImportResponse as FieldImportResponseType, FieldImportSuggestion } from '@/api'
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
  })
  const update = useMutation({
    mutationFn: (args: { fid: number | string; data: Partial<Field> }) => fieldApi.update(wid, tid, args.fid, args.data),
    onSuccess: () => { message.success('已更新'); closeDialog(); onChanged() },
  })
  const remove = useMutation({
    mutationFn: (fid: number | string) => fieldApi.remove(wid, tid, fid),
    onSuccess: () => { message.success('已删除'); onChanged() },
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
    setInnerOpen(false)
    setEditTarget(null)
    setFieldType(undefined)
    form.resetFields()
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
    // config 由 ConfigEditor/SelectOptionsEditor 通过 setFieldValue 写入 store，
    // 未注册对应 Form.Item，getFieldsValue()（仅注册字段）不包含 config —— 必须直接读 store。
    const configFromStore = form.getFieldValue('config') as Record<string, unknown> | undefined
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
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button icon={<ImportOutlined />} onClick={openImportDialog}>
          从其他表引入
        </Button>
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
        {fieldType && <ConfigEditor fieldType={fieldType} form={form} wid={wid} tid={tid} tables={tables} isEdit={!!editTarget} />}
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
                        <Tag style={{ marginLeft: 4 }}>{sf.field_type}</Tag>
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
                ...fields.map(f => ({ label: `${f.name}（${f.field_type}）`, value: f.name })),
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
                      {sourceFields.find(f => f.name === s.source)?.field_type ?? 'unknown'}
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
    <Modal title="字段管理" width={760} open={open} onCancel={onClose} footer={null}>
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
function ConfigEditor({ fieldType, form, tables, isEdit = false }: ConfigEditorProps) {
  // 监听 config 变化，保证表单 re-render。
  // 注意：Form.useWatch 走 getFieldsValue()（仅含已注册 Form.Item 的字段），
  // select 的 options 编辑器没有注册 config.* 表单项，因此 select 字段的 watch
  // 值永远是 undefined —— 必须回退直接读 form store（getFieldValue），否则
  // 编辑时 options 永远显示为空（并可能被默认值覆盖）。
  const currentConfig = Form.useWatch('config', form) as Record<string, unknown> | undefined
  const effectiveConfig = currentConfig ?? (form.getFieldValue('config') as Record<string, unknown> | undefined) ?? {}

  // 初始填充：仅新建字段时（编辑时不覆盖既有 config）给默认值。
  // 注意 Form.useWatch 首帧返回 undefined，若不加 isEdit 守卫会把已存 options 等配置误清空。
  useEffect(() => {
    if (isEdit) return
    if (!currentConfig || Object.keys(currentConfig).length === 0) {
      const defaults = defaultConfigForType(fieldType)
      if (Object.keys(defaults).length > 0) {
        form.setFieldValue('config', defaults)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldType, isEdit])

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
