/** 字段管理 —— 容器组件：字段列表 / 新建编辑对话框 / 从其他表引入字段对话框.
 *
 * 拆分说明（重构自 1300 行单体）:
 *   FieldList.tsx       — 字段列表 + 拖拽排序行卡片（含 fieldNoteText / formatIncrementExample）
 *   FieldEditor.tsx     — 新建 / 编辑字段 Modal（含类型感知默认值输入）
 *   typeConfigPanel.tsx — 类型专属 config 编辑区（数字/日期/选择/关联/附件）
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal, Button, Tag, Input, Select, Checkbox, Tooltip, App as AntApp, Alert, Empty, Spin, Divider, Form, Radio } from 'antd'
import { MinusOutlined, SwapOutlined, CloseCircleOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fieldApi, tableApi, workspaceApi } from '@/api'
import type { Field, FieldCreate, FieldType, TableSummary, Workspace, FieldImportResponse as FieldImportResponseType, FieldImportSuggestion } from '@/api'
import { getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'
import FieldList from './FieldList'
import FieldEditor from './FieldEditor'
import { defaultConfigForType } from './typeConfigPanel'
import { WEIGHT } from '@/theme/tokens'

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

  // 表详情默认只带前 500 项 options（ADR 0046 D6）。字段编辑必须基于全量配置，
  // 否则保存时会把后段选项当作用户删除而丢掉 —— 打开面板时按需拉一次全量（缓存复用）。
  // 只替换「被截断」的字段，其余字段仍以 props（父层最新回流）为准。
  const { data: fullFields } = useQuery<Field[]>({
    queryKey: ['fields-full', wid, tid],
    queryFn: () => fieldApi.list(wid, tid, false, true),
    enabled: open,
    staleTime: 60_000,
  })
  const editFields = useMemo(() => {
    if (!fullFields?.length) return fields
    return fields.map(f => {
      const truncated = (f.config as Record<string, unknown> | undefined)?.options_truncated === true
      if (!truncated) return f
      return fullFields.find(x => String(x.id) === String(f.id)) ?? f
    })
  }, [fields, fullFields])

  // ── 编辑对话框「最新数据」同步 ──
  // fields 常因保存后父层异步 refetch 才更新：若在该窗口内点开编辑，或对话框已打开时才回流，
  // 旧实现只在点击编辑那一刻回填一次（快照），会导致对话框停留在旧配置、需再点一次编辑才对。
  // 这里改为在对话框打开期间监听 fields 变化并重新回填。
  const seededSigRef = useRef<string>('')
  const dirtyRef = useRef(false)
  const programmaticRef = useRef(false)

  /** 编辑目标始终以 fields 里的最新版本为准（找不到时回退到点击时的快照） */
  const liveEditTarget = useMemo(
    () => (editTarget ? editFields.find(f => String(f.id) === String(editTarget.id)) ?? editTarget : null),
    [editTarget, editFields],
  )

  /** 组装编辑用 config。关联字段的 reference_fields 为空（缺失或空数组，种子/历史数据
   *  或后端归一化后为 []）时，从同表归属于它的 lookup 行按 order 反推，保证对话框
   *  「引用字段」与字段列表一致，也避免保存时以空列表覆盖、误删这些已存在的引用字段。
   *
   *  为什么用「空」而非「缺失」判定：后端 _validate_field_config 归一化时会写入
   *  reference_fields=[]，若仅判断键是否存在，真实返回的 [] 会被当成有效配置而跳过反推，
   *  导致编辑关联字段时「引用字段」区始终为空。 */
  const buildEditConfig = (f: Field): Record<string, unknown> => {
    const cfg: Record<string, unknown> = { ...defaultConfigForType(f.field_type), ...(f.config ?? {}) }
    const storedRefs = cfg.reference_fields
    const hasRefs = Array.isArray(storedRefs) && storedRefs.length > 0
    if (f.field_type === 'link' && !hasRefs) {
      const derived = editFields
        .filter(l => l.field_type === 'lookup' && String(l.config?.via_link_field_id) === String(f.id))
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map(l => l.config?.source_field_id)
        .filter((x): x is number => typeof x === 'number')
      cfg.reference_fields = derived
    }
    return cfg
  }

  /** 把字段值回填到表单；标记为程序化写入，避免被 onValuesChange 误判为用户改动 */
  const seedEditForm = (f: Field, config: Record<string, unknown>) => {
    programmaticRef.current = true
    setFieldType(f.field_type)
    form.setFieldsValue({
      name: f.name,
      field_type: f.field_type,
      required: f.required,
      hidden: f.hidden,
      is_unique: f.is_unique ?? false,
      default_value: f.default_value ?? '',
      config,
    })
    programmaticRef.current = false
    dirtyRef.current = false
  }

  // 对话框打开期间：fields 更新且用户尚未改动表单时，同步为最新配置。
  //
  // 同步指纹必须基于「回填用的完整 config」（buildEditConfig 的结果），而不是字段自身的
  // 原始 config —— 关联字段的「引用字段」是从同表归属它的 lookup 行反推而来的，当这些
  // lookup 兄弟字段在对话框打开后才异步到达（首次进入时 fields 尚未含它们的典型情形），
  // 字段自身的 config 不变但反推结果会变。若指纹只看自身 config，effect 会误判「无变化」
  // 而跳过回填，「引用字段」区就会停在打开时的空态，表现为「首次进入编辑页面无法同步」。
  useEffect(() => {
    if (!innerOpen || !liveEditTarget) return
    // options 被截断且全量还没到：先不回填，等 fullFields 到达后由本 effect 重新触发，
    // 避免用截断配置覆盖表单、保存时丢掉后段选项（ADR 0046 D6）
    const truncated = (liveEditTarget.config as Record<string, unknown> | undefined)?.options_truncated === true
    if (truncated && fullFields === undefined) return
    const config = buildEditConfig(liveEditTarget)
    const sig = JSON.stringify({
      n: liveEditTarget.name, t: liveEditTarget.field_type, r: liveEditTarget.required,
      h: liveEditTarget.hidden, u: liveEditTarget.is_unique, d: liveEditTarget.default_value,
      c: config,
    })
    if (sig === seededSigRef.current || dirtyRef.current) return
    seededSigRef.current = sig
    seedEditForm(liveEditTarget, config)
  }, [innerOpen, liveEditTarget, editFields, fullFields]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 从其他表引入对话框状态 ──
  const [importOpen, setImportOpen] = useState(false)
  const [sourceWid, setSourceWid] = useState<number | string | null>(null)
  const [sourceTableId, setSourceTableId] = useState<number | string | null>(null)
  const [importSelectedIds, setImportSelectedIds] = useState<Array<number | string>>([])
  const [importSkipConflicts, setImportSkipConflicts] = useState(true)
  // 引入模式：copy = 复制独立副本；link = 创建 link + lookup 字段实时引用源表
  const [importMode, setImportMode] = useState<'copy' | 'link'>('copy')
  const [fieldFilter, setFieldFilter] = useState('')
  // 新增：预览返回的 suggestions + gap_analysis
  const [importPreview, setImportPreview] = useState<FieldImportResponseType | null>(null)
  const [importMapping, setImportMapping] = useState<Record<string, string | null>>({})
  const [importPreviewLoading, setImportPreviewLoading] = useState(false)

  // 拉取当前工作区表列表（link 字段用）
  const { data: tables = [] } = useQuery<TableSummary[]>({
    queryKey: ['tables', wid],
    queryFn: () => tableApi.list(wid),
    enabled: open && (innerOpen || importOpen),
  })

  // 拉取可访问工作区列表（跨工作区引入的源工作区选择）
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
    enabled: open && importOpen,
  })

  // 拉取选中源工作区的表列表（跨工作区引入的源表选择）
  const { data: sourceTables = [] } = useQuery<TableSummary[]>({
    queryKey: ['tables', sourceWid],
    queryFn: () => tableApi.list(String(sourceWid)),
    enabled: importOpen && !!sourceWid,
  })

  // 拉取选中源表的字段列表（用源表所在工作区 wid）
  const { data: sourceFields = [], isFetching: sourceFieldsLoading } = useQuery<Field[]>({
    queryKey: ['fields', sourceWid, sourceTableId],
    queryFn: () => fieldApi.list(String(sourceWid!), String(sourceTableId!)),
    enabled: importOpen && !!sourceWid && !!sourceTableId,
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
        import_mode: importMode,
        preview_only: true,
      })
      setImportPreview(resp)
      // 用 suggestions 初始化 importMapping —— 所有有 target 的 suggestion 都预填充，
      // 包括低置信度项（让用户看到系统推荐了什么目标），后续「仅引入已匹配」会把
      // will_map=false 的置为 null（跳过）
      const mapping: Record<string, string | null> = {}
      resp.suggestions?.forEach((s: FieldImportSuggestion) => {
        mapping[s.source] = s.target ?? null
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
        import_mode: importMode,
        // 把用户调整后的 mapping 传过去（null 条目表示跳过；link 模式不走映射）
        field_mapping: importMode === 'copy' ? importMapping : undefined,
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
    programmaticRef.current = true
    form.resetFields()
    programmaticRef.current = false
    seededSigRef.current = ''
    dirtyRef.current = false
    setInnerOpen(false)
    setEditTarget(null)
    setFieldType(undefined)
  }

  function openImportDialog() {
    setSourceWid(null)
    setSourceTableId(null)
    setImportSelectedIds([])
    setImportSkipConflicts(true)
    setImportMode('copy')
    setFieldFilter('')
    setImportOpen(true)
  }

  function closeImportDialog() {
    setImportOpen(false)
    setSourceWid(null)
    setSourceTableId(null)
    setImportSelectedIds([])
    setImportPreview(null)
    setImportMapping({})
    setFieldFilter('')
  }

  /** 打开新建/编辑对话框 */
  function openDialog(target: Field | null) {
    setEditTarget(target)
    setInnerOpen(true)
    // 重置同步指纹：确保每次打开都重新回填（含重开同一字段的场景）
    seededSigRef.current = ''
    dirtyRef.current = false
    if (target) {
      // 先设置 fieldType，让 ConfigEditor 也能拿到正确类型；
      // 实际回填交由下方 effect（在 Modal + Form 挂载后执行，并随 fields 更新重新同步）
      setFieldType(target.field_type)
    } else {
      // 新建：延迟到下一个 tick reset —— setInnerOpen(true) 是异步批处理，
      // 在 React 提交更新前 Form 还未挂载，此时 form.resetFields() 会触发
      // "Instance created by useForm is not connected to any Form element" warning.
      setFieldType(undefined)
      setTimeout(() => {
        programmaticRef.current = true
        form.resetFields()
        programmaticRef.current = false
      }, 0)
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
      editTarget={liveEditTarget}
      fieldType={fieldType}
      form={form}
      wid={wid}
      tid={tid}
      tables={tables}
      submitPending={create.isPending || update.isPending}
      onSubmit={handleSubmit}
      onCancel={closeDialog}
      onFieldTypeChange={setFieldType}
      // 用户改动表单后置脏：此时 fields 的异步回流不再覆盖用户正在编辑的内容
      onValuesChange={() => { if (!programmaticRef.current) dirtyRef.current = true }}
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

  // 勾选区按名称过滤（不影响勾选状态）
  const filteredSourceFields = useMemo(() => {
    const kw = fieldFilter.trim().toLowerCase()
    if (!kw) return sourceFieldsWithConflict
    return sourceFieldsWithConflict.filter(sf => sf.name.toLowerCase().includes(kw))
  }, [sourceFieldsWithConflict, fieldFilter])

  /** 全选 / 反选当前过滤后的字段 */
  function toggleSelectAll(mode: 'all' | 'invert') {
    const selectable = filteredSourceFields.map(sf => sf.id)
    if (mode === 'all') {
      setImportSelectedIds(prev => Array.from(new Set([...prev, ...selectable])))
    } else {
      setImportSelectedIds(prev => {
        const base = new Set(prev)
        selectable.forEach(id => {
          if (base.has(id)) base.delete(id)
          else base.add(id)
        })
        return Array.from(base)
      })
    }
    setImportPreview(null)
  }

  /** 仅引入已匹配：把低置信度项的映射置为跳过 */
  function keepMatchedOnly() {
    if (!importPreview?.suggestions) return
    const next: Record<string, string | null> = { ...importMapping }
    importPreview.suggestions.forEach((s: FieldImportSuggestion) => {
      if (!s.will_map) next[s.source] = null
    })
    setImportMapping(next)
  }

  /** link 字段的关联目标提示（解析目标表所在工作区，跨工作区时提醒用户） */
  function linkTargetHint(sf: Field): string | null {
    if (sf.field_type !== 'link') return null
    const targetTid = Number(sf.config?.target_table_id)
    if (!Number.isFinite(targetTid)) return null
    const inSource = sourceTables.find(t => Number(t.id) === targetTid)
    if (inSource) return `关联目标：${inSource.name}（源工作区）`
    const inCurrent = tables.find(t => Number(t.id) === targetTid)
    if (inCurrent) return `关联目标：${inCurrent.name}（当前工作区）`
    return `关联目标：表 #${targetTid}（其他工作区）`
  }

  /** 映射面板单行渲染（推荐/低置信度两组共用） */
  const renderSuggestionRow = (s: FieldImportSuggestion) => {
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
          <div style={{ fontWeight: WEIGHT.medium }}>{s.source}</div>
          <div style={{ fontSize: 11, color: '#999' }}>
            {getFieldTypeLabel(sourceFields.find(f => f.name === s.source)?.field_type ?? 'unknown')}
          </div>
          {(() => {
            const sf = sourceFields.find(f => f.name === s.source)
            const hint = sf ? linkTargetHint(sf) : null
            return hint ? <div style={{ fontSize: 11, color: '#999' }}>{hint}</div> : null
          })()}
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
            {s.will_map ? '推荐' : '未能自动对应'}
          </Tag>
        </Tooltip>
        <span style={{ fontSize: 11, color: scoreColor, width: 42, textAlign: 'right' }}>
          {s.score.toFixed(2)}
        </span>
      </div>
    )
  }

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
        message={importMode === 'link'
          ? '将通过「关联引用」实时引用源表的数据：这里显示的值始终与源表保持一致，源表改动会自动同步（不复制数据）；若源表中的字段被删除或修改，引用会标记为已失效'
          : '字段会被复制成当前表的新字段，之后两边修改互不影响；若源字段是「关联」类型，复制后仍指向原来的目标表（支持跨工作区关联）'}
      />

      {/* 引入模式选择 */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontWeight: WEIGHT.medium }}>引入方式</div>
        <Radio.Group
          value={importMode}
          onChange={(e) => { setImportMode(e.target.value as 'copy' | 'link'); setImportPreview(null); setImportMapping({}) }}
        >
          <Radio value="copy">复制副本（独立数据）</Radio>
          <Radio value="link">关联引用（实时同步）</Radio>
        </Radio.Group>
      </div>

      {/* 源工作区 + 源表级联选择（支持跨工作区） */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontWeight: WEIGHT.medium }}>选择源工作区</div>
        <Select
          style={{ width: '100%' }}
          placeholder="请选择来源工作区"
          showSearch
          optionFilterProp="label"
          value={sourceWid ?? undefined}
          onChange={(v) => { setSourceWid(v); setSourceTableId(null); setImportSelectedIds([]); setImportPreview(null); setImportMapping({}) }}
          options={workspaces.map(w => ({
            label: String(w.id) === String(wid) ? `${w.name}（当前）` : w.name,
            value: w.id,
          }))}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontWeight: WEIGHT.medium }}>选择源表</div>
        <Select
          style={{ width: '100%' }}
          placeholder={sourceWid ? '请选择要引入字段的来源表' : '请先选择来源工作区'}
          disabled={!sourceWid}
          showSearch
          optionFilterProp="label"
          value={sourceTableId ?? undefined}
          onChange={(v) => { setSourceTableId(v); setImportSelectedIds([]); setImportPreview(null); setImportMapping({}) }}
          options={sourceTables
            .filter(t => !t.trashed && String(t.id) !== String(tid))
            .map(t => ({ label: t.name, value: t.id }))}
        />
      </div>

      {/* 字段勾选区 */}
      {sourceWid && sourceTableId && (
        <Spin spinning={sourceFieldsLoading}>
          {sourceFields.length === 0 ? (
            <Empty description="该表暂无字段" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <div>
              <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: WEIGHT.medium }}>选择要引入的字段</span>
                <span style={{ color: '#999', fontSize: 12 }}>
                  已选 {importSelectedIds.length}/{sourceFields.length}（不选 = 全部引入）
                </span>
              </div>
              {/* 过滤 + 全选/反选（AC-4） */}
              <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <Input
                  size="small"
                  allowClear
                  placeholder="按字段名过滤"
                  value={fieldFilter}
                  onChange={(e) => setFieldFilter(e.target.value)}
                  style={{ width: 200 }}
                />
                <Button size="small" onClick={() => toggleSelectAll('all')}>全选</Button>
                <Button size="small" onClick={() => toggleSelectAll('invert')}>反选</Button>
              </div>
              <Checkbox.Group
                value={importSelectedIds as Array<string | number>}
                onChange={(vals) => { setImportSelectedIds(vals as Array<string | number>); setImportPreview(null) }}
                style={{ width: '100%' }}
              >
                <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                  {filteredSourceFields.map((sf) => {
                    const hint = linkTargetHint(sf)
                    return (
                      <div key={sf.id} style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Checkbox value={sf.id}>
                          <span>{sf.name}</span>
                          <Tag color={getFieldTypeColor(sf.field_type)} style={{ marginLeft: 4 }}>{getFieldTypeLabel(sf.field_type)}</Tag>
                          {sf.conflict && (
                            <Tag color="orange" style={{ marginLeft: 4 }}>重名</Tag>
                          )}
                          {hint && (
                            <span style={{ fontSize: 11, color: '#999', marginLeft: 4 }}>{hint}</span>
                          )}
                        </Checkbox>
                      </div>
                    )
                  })}
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

      {/* link 模式预览：展示将创建的关联字段清单 */}
      {importMode === 'link' && importPreview && (
        <div style={{ marginTop: 16 }}>
          <Divider style={{ margin: '8px 0' }}>关联字段预览</Divider>
          <div style={{ color: '#64748b', fontSize: 12, marginBottom: 8 }}>将创建以下关联字段：</div>
          <div style={{ maxHeight: 240, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
            {(importPreview.gap_analysis?.planned_fields ?? []).map((p, i) => (
              <div key={i} style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                <CheckCircleOutlined style={{ color: 'var(--cn-success, #52c41a)' }} />
                <span style={{ fontWeight: WEIGHT.medium }}>{p.name}</span>
                <Tag color={getFieldTypeColor(p.field_type)} style={{ marginLeft: 4 }}>{getFieldTypeLabel(p.field_type)}</Tag>
              </div>
            ))}
            {(importPreview.gap_analysis?.planned_fields ?? []).length === 0 && (
              <div style={{ color: '#999', fontSize: 12 }}>所选表中没有可引入的字段（「关联」「引用」类型的字段暂不支持引入）</div>
            )}
          </div>
        </div>
      )}

      {/* 映射对比面板（copy 模式专用） */}
      {importMode === 'copy' && importPreview && importPreview.suggestions && importPreview.suggestions.length > 0 && (
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

          {/* 映射对比表 —— 按 will_map 分组（AC-5） */}
          {(() => {
            const all = importPreview.suggestions
            const matched = all.filter((s: FieldImportSuggestion) => s.will_map)
            const lowConfidence = all.filter((s: FieldImportSuggestion) => !s.will_map)
            const hasLowConfidence = lowConfidence.length > 0
            return (
              <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}>
                <div style={{ padding: '6px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f6ffed', borderBottom: '1px solid #f0f0f0' }}>
                  <Tag color="green" style={{ margin: 0 }}>已匹配推荐 {matched.length}</Tag>
                  {hasLowConfidence && (
                    <Button size="small" type="link" onClick={keepMatchedOnly}>
                      仅引入已匹配（跳过 {lowConfidence.length} 个未能自动对应的）
                    </Button>
                  )}
                </div>
                {matched.map(renderSuggestionRow)}
                {hasLowConfidence && (
                  <>
                    <div style={{ padding: '6px 12px', background: '#fffbeb', borderBottom: '1px solid #f0f0f0' }}>
                      <Tag color="orange" style={{ margin: 0 }}>未能自动对应 {lowConfidence.length} 个（默认将引入为新字段，可改名或跳过）</Tag>
                    </div>
                    {lowConfidence.map(renderSuggestionRow)}
                  </>
                )}
              </div>
            )
          })()}

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
