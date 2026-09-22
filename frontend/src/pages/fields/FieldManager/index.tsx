/** 字段管理 —— 容器组件：字段列表 / 新建编辑对话框 / 从其他表引入字段对话框.
 *
 * 拆分说明（重构自 1300 行单体）:
 *   FieldList.tsx       — 字段列表 + 拖拽排序行卡片（含 fieldNoteText / formatIncrementExample）
 *   FieldEditor.tsx     — 新建 / 编辑字段 Modal（含类型感知默认值输入）
 *   typeConfigPanel.tsx — 类型专属 config 编辑区（数字/日期/选择/关联/附件）
 */
import { useMemo, useState } from 'react'
import { Modal, Button, Tag, Input, Select, Checkbox, Tooltip, App as AntApp, Alert, Empty, Spin, Divider, Form } from 'antd'
import { MinusOutlined, SwapOutlined, CloseCircleOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fieldApi, tableApi } from '@/api'
import type { Field, FieldCreate, FieldType, TableSummary, FieldImportResponse as FieldImportResponseType, FieldImportSuggestion } from '@/api'
import { getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import FieldList from './FieldList'
import FieldEditor from './FieldEditor'
import { defaultConfigForType } from './typeConfigPanel'

// 保持既有公开 API：测试与外部调用方仍从本入口导入这两个工具函数
export { fieldNoteText, formatIncrementExample } from './FieldList'

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

export default function FieldManager({ open, wid, tid, fields, onClose, onChanged, embedded }: Props) {
  const { message } = AntApp.useApp()
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

  const reorderFields = useMutation({
    mutationFn: (ids: Array<number | string>) => fieldApi.reorder(wid, tid, ids),
    onSuccess: () => onChanged(),
    onError: (err) => message.error(err instanceof Error ? err.message : '字段排序失败'),
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

  /** 编辑对话框（FieldEditor 组件） */
  const editDialog = (
    <FieldEditor
      open={innerOpen}
      editTarget={editTarget}
      fieldType={fieldType}
      form={form}
      wid={wid}
      tid={tid}
      tables={tables}
      submitPending={create.isPending || update.isPending}
      onSubmit={handleSubmit}
      onCancel={closeDialog}
      onFieldTypeChange={setFieldType}
    />
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
        <FieldList
          fields={sorted}
          isReordering={reorderFields.isPending}
          onEdit={openDialog}
          onRemove={(f) => remove.mutate(f.id)}
          onReorder={(ids) => reorderFields.mutate(ids)}
          onOpenImport={openImportDialog}
          onCreate={() => openDialog(null)}
        />
        {editDialog}
        {importDialog}
      </>
    )
  }

  // 独立模式：外层包 Modal
  return (
    <Modal title="字段管理" width={760} open={open} destroyOnHidden={false} onCancel={onClose} footer={null}>
      <FieldList
        fields={sorted}
        isReordering={reorderFields.isPending}
        onEdit={openDialog}
        onRemove={(f) => remove.mutate(f.id)}
        onReorder={(ids) => reorderFields.mutate(ids)}
        onOpenImport={openImportDialog}
        onCreate={() => openDialog(null)}
      />
      {editDialog}
      {importDialog}
    </Modal>
  )
}
