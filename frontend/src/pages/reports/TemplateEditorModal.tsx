/** 报表模板编辑器弹窗 —— 基本信息 / 模板内容两页签 + 关联表级联引用.
 *
 * 编辑器三组件（CodeMirror 相关）在本模块内懒加载，首屏不加载。
 */

import React, { Suspense, useEffect, useRef, useState } from 'react'
import { Button, Space, Modal, Form, Input, Typography, Select, Tooltip, Segmented, Tabs, Badge, Spin } from 'antd'
import type { FormInstance } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ReportTemplate, ReportTemplateCreate, ReportParameter, TableSummary, Field } from '@/api'
import type { TemplateEditorHandle } from '@/components/report-editor'
import { FORMAT_OPTIONS, PARAM_TYPES, THEME_OPTIONS } from './reportsConstants'
import { useTemplateEditorData } from './useTemplateEditorData'

// 编辑器三组件懒加载：共享同一动态 import 落同一 chunk，首屏不加载 CodeMirror
const ReportTemplateEditor = React.lazy(() =>
  import('@/components/report-editor').then(m => ({ default: m.ReportTemplateEditor })))
const PreviewPanel = React.lazy(() =>
  import('@/components/report-editor').then(m => ({ default: m.PreviewPanel })))
const SyntaxHelpPanel = React.lazy(() =>
  import('@/components/report-editor').then(m => ({ default: m.SyntaxHelpPanel })))


/** 编辑器 chunk 懒加载占位 — 与编辑器主体同高，避免布局跳动 */
function EditorLoadingFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 'min(56vh, 640px)' }}>
      <Spin />
    </div>
  )
}

// ─────────────── 模板编辑器 Modal ───────────────

interface EditorProps {
  open: boolean
  editing: ReportTemplate | null
  tables: TableSummary[]
  workspaceId: string
  form: FormInstance
  /** 编辑器初始模板内容（由所点行的详情显式传入） */
  initialContent: string
  onClose: () => void
  onSubmit: (data: ReportTemplateCreate) => void
  submitting: boolean
}

/** 编辑器弹窗页签 key（模板参数已整合进基本信息页签） */
type EditorTabKey = 'basic' | 'editor'

/** 表单字段 → 所属页签映射（保存校验失败时按此跳转；新增表单字段时必须同步维护此表） */
const FIELD_TAB_MAP: Record<string, EditorTabKey> = {
  name: 'basic',
  output_format: 'basic',
  theme: 'basic',
  table_id: 'basic',
  view_id: 'basic',
  extra_table_ids: 'basic',
  description: 'basic',
  parameters: 'basic',
  template_content: 'editor',
}

export function TemplateEditor({ open, editing, tables, workspaceId, form, initialContent, onClose, onSubmit, submitting }: EditorProps) {

  // 编辑器 value（受控）
  const [templateValue, setTemplateValue] = useState('')
  // 当前选中的关联表 ID（从 Form 监听）
  const [selectedTableId, setSelectedTableId] = useState<number | null>(null)
  // 额外选择的表 ID 列表（本工作区 + 跨工作区）
  const [extraTableIds, setExtraTableIds] = useState<number[]>([])
  // 跨工作区级联选择状态
  const [importWsId, setImportWsId] = useState<string>('')
  const [importTableId, setImportTableId] = useState<number | null>(null)
  // CodeMirror 引用（供 SyntaxHelpPanel 插入代码使用）
  const editorRef = useRef<TemplateEditorHandle | null>(null)
  // 主区视图模式：编辑器保持挂载仅隐藏显示，避免切换后丢失内容与插入能力
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'help'>('edit')
  // 弹窗页签：新建态默认基本信息，编辑态默认模板编辑
  const [activeTab, setActiveTab] = useState<EditorTabKey>('basic')
  // 校验失败涉及的页签（页签标题显示错误标记）
  const [erroredTabs, setErroredTabs] = useState<Set<EditorTabKey>>(new Set())
  // 编辑器页签是否已被访问（CodeMirror 避免在隐藏容器中初始化，首次激活后才挂载，之后保持挂载）
  const [editorVisited, setEditorVisited] = useState(false)

  // 服务端派生数据与选项：跨工作区解析、字段/视图/预览取数（见 useTemplateEditorData）
  const {
    setCrossTableInfo,
    importWsTables,
    fields,
    previewRows,
    previewLoading,
    importWsOptions,
    importTableOptions,
    selectedTableName,
    tableSelectOptions,
    tableGroups,
    recordsByTable,
    extraTableOptions,
    viewSelectOptions,
  } = useTemplateEditorData({ open, workspaceId, tables, selectedTableId, extraTableIds, importWsId })


  // Modal 打开时统一初始化所有表单值（在 Form.Items mount 之后，避免 destroyOnHidden 时序错乱）
  useEffect(() => {
    if (!open) return
    // 编辑态：从 editing 详情对象取；新建态：默认值
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        description: editing.description,
        output_format: editing.output_format ?? 'docx',
        template_content: editing.template_content,
        table_id: editing.table_id,
        view_id: editing.view_id ?? null,
        parameters: (editing.parameters as ReportParameter[]).map(p => ({
          ...p,
          // options 数组转逗号分隔文本，供编辑器 Input 展示
          optionsText: (p.options ?? []).join(','),
        })) as ReportParameter[],
        theme: editing.theme ?? 'minimal',
        extra_table_ids: editing.extra_table_ids ?? [],
      })
      setExtraTableIds(editing.extra_table_ids ?? [])
    } else {
      form.setFieldsValue({
        name: '',
        description: '',
        output_format: 'docx',
        template_content: initialContent,
        table_id: null,
        view_id: null,
        parameters: [],
        theme: 'minimal',
        extra_table_ids: [],
      })
      setExtraTableIds([])
    }
    // 模板内容使用外部显式传入的 initialContent（与所点行绑定）
    setTemplateValue(initialContent)
    const tplId: number | null = form.getFieldValue('table_id') ?? null
    const extras: number[] = form.getFieldValue('extra_table_ids') || []
    setSelectedTableId(tplId)
    // 额外表多选框 value 同步 state（让 Form.List 的 select 有受控值）
    setExtraTableIds(extras)
    setImportWsId('')
    setImportTableId(null)
    // 每次打开弹窗回到编辑模式，避免上次停留在预览/帮助视图
    setViewMode('edit')
    // 新建态默认落在基本信息页签，编辑态默认落在模板编辑页签；清空错误标记
    setActiveTab(editing ? 'editor' : 'basic')
    setErroredTabs(new Set())
    setEditorVisited(Boolean(editing))
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // 全局 insert 事件监听（SyntaxHelpPanel → ReportTemplateEditor）
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ code?: string; fieldName?: string }>
      if (ce.detail?.code) {
        editorRef.current?.insertText(ce.detail.code)
      } else if (ce.detail?.fieldName) {
        editorRef.current?.insertText(`{{ ${ce.detail.fieldName} }}`)
      }
    }
    window.addEventListener('report-editor-insert', handler)
    return () => window.removeEventListener('report-editor-insert', handler)
  }, [])

  // 关联表变更时更新 selectedTableId（同时从 extra 表中排除它；视图归属主表，一并重置）
  const handleTableChange = (value: number | null) => {
    setSelectedTableId(value)
    form.setFieldValue('view_id', null)
    if (value !== null) {
      setExtraTableIds(prev => prev.filter(id => id !== value))
    }
  }

  // extra_table_ids 变更（排除主表本身）
  const handleExtraTablesChange = (values: number[]) => {
    const filtered = selectedTableId !== null
      ? values.filter(id => id !== selectedTableId)
      : values
    setExtraTableIds(filtered)
    form.setFieldValue('extra_table_ids', filtered)
  }

  // 模板内容变更（CodeMirror → Form 同步）
  const handleTemplateChange = (value: string) => {
    setTemplateValue(value)
    form.setFieldValue('template_content', value)
  }

  // 页签切换（首次进入模板编辑页签时挂载编辑器，之后保持挂载）
  const handleTabChange = (key: string) => {
    if (key === 'editor') setEditorVisited(true)
    setActiveTab(key as EditorTabKey)
  }

  // 保存校验：失败时按字段→页签映射跳转并显示错误标记，成功后提交并清空标记
  const handleSave = () => {
    form.validateFields().then((v) => {
      setErroredTabs(new Set())
      handleFormFinish(v as Parameters<typeof handleFormFinish>[0])
    }).catch((err: { errorFields?: Array<{ name?: Array<string | number> }> }) => {
      const tabs = new Set<EditorTabKey>()
      for (const f of err.errorFields ?? []) {
        const tab = FIELD_TAB_MAP[String(f.name?.[0])]
        if (tab) tabs.add(tab)
      }
      setErroredTabs(tabs)
      // 跳到第一个含错误的页签
      const order: EditorTabKey[] = ['basic', 'editor']
      const first = order.find(t => tabs.has(t))
      if (first) {
        if (first === 'editor') setEditorVisited(true)
        setActiveTab(first)
      }
    })
  }

  // 保存校验（extra_table_ids 随模板持久化，含跨工作区表；输出格式/主题兜底默认值）
  // 表单参数额外携带 optionsText（编辑用），提交前转换为 options 数组
  const handleFormFinish = (v: Omit<ReportTemplateCreate, 'parameters'> & { parameters?: Array<ReportParameter & { optionsText?: string }> }) => {
    onSubmit({
      ...v,
      output_format: v.output_format ?? 'docx',
      theme: v.theme ?? 'minimal',
      template_content: templateValue,
      extra_table_ids: extraTableIds,
      // 视图绑定随模板持久化；清空时落 null（取全表数据）
      view_id: v.view_id ?? null,
      // optionsText（逗号分隔字符串）→ options（字符串数组），与后端 ParameterDef 对齐
      parameters: (v.parameters ?? []).map(p => ({
        ...p,
        options: typeof p.optionsText === 'string' && p.optionsText.trim()
          ? p.optionsText.split(/[，,]/).map(s => s.trim()).filter(Boolean)
          : [],
      })),
    })
  }

  // 跨工作区引入：将级联选中的表加入额外引用表
  const handleImportCrossTable = () => {
    if (importTableId === null) return
    const t = importWsTables.find(x => x.id === importTableId)
    if (!t) return
    setCrossTableInfo(prev => ({ ...prev, [importTableId]: { name: t.name, wsId: importWsId } }))
    setExtraTableIds(prev => (prev.includes(importTableId) ? prev : [...prev, importTableId]))
    setImportTableId(null)
  }


  return (
    <Modal
      title={editing ? `编辑模板「${editing.name}」` : '新建模板'}
      open={open}
      onCancel={onClose}
      width="min(1280px, 92vw)"
      onOk={() => form.submit()}
      confirmLoading={submitting}
      okText={editing ? '保存' : '创建'}
      cancelText="取消"
      destroyOnHidden
      footer={null}
      styles={{ body: { padding: 0, maxHeight: 'calc(92vh - 110px)', overflowY: 'auto' } }}
    >
      {/* 单一 Form：所有 Form.Items 共享一个 form 实例 + onFinish；内容按 Tabs 分两页签（页签标题在校验失败时叠加错误红点） */}
      <Form
        form={form}
        layout="vertical"
        style={{ padding: '12px 24px 0' }}
        onFinish={handleFormFinish}
      >
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={[
            {
              key: 'basic',
              label: erroredTabs.has('basic') ? <Badge dot>基本信息</Badge> : '基本信息',
              forceRender: true,
              children: (
                <>
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入名称' }]} style={{ flex: '1 1 220px', marginBottom: 8 }}>
                      <Input placeholder="例如：月度销售汇总" />
                    </Form.Item>
                    <Form.Item name="output_format" label="输出格式" style={{ width: 150, marginBottom: 8 }}>
                      <Select options={FORMAT_OPTIONS} />
                    </Form.Item>
                    <Form.Item name="theme" label="主题风格" className="report-theme-row" style={{ width: 120, marginBottom: 8 }} tooltip="影响导出文档的标题/正文/表格样式">
                      {/* 选项仅 5 个，关闭虚拟滚动（jsdom 高度为 0 时虚拟列表渲染不全） */}
                      <Select options={THEME_OPTIONS} virtual={false} />
                    </Form.Item>
                    <Form.Item name="table_id" label="关联表" style={{ width: 220, marginBottom: 8 }}>
                      <Select
                        options={tableSelectOptions}
                        allowClear
                        placeholder="选填（建议关联）"
                        onChange={handleTableChange}
                      />
                    </Form.Item>
                    <Form.Item name="view_id" label="关联视图" style={{ width: 180, marginBottom: 8 }} tooltip="绑定后按该视图的过滤/排序取数，视图调整即报表调整；不绑定则取全部数据">
                      <Select
                        options={viewSelectOptions}
                        allowClear
                        virtual={false}
                        disabled={selectedTableId === null}
                        placeholder="全部数据（默认）"
                      />
                    </Form.Item>
                    <Form.Item name="extra_table_ids" label="额外引用表" style={{ flex: '1 1 220px', marginBottom: 8 }} tooltip="模板中可通过 records_by_table['表名'] 引用这些表的数据">
                      <Select
                        mode="multiple"
                        options={extraTableOptions}
                        placeholder="选择额外引用的数据表（可选）"
                        onChange={handleExtraTablesChange}
                        value={extraTableIds}
                        allowClear
                        maxTagCount={3}
                      />
                    </Form.Item>
                  </div>
                  {/* 跨工作区引入：先点源工作区按钮，再从源表下拉选择，点「引入」加入额外引用表 */}
                  {importWsOptions.length > 0 && (
                    <div className="report-crossws-row" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>跨工作区引入：</Typography.Text>
                      {importWsOptions.map(o => (
                        <Button
                          key={o.value}
                          size="small"
                          type={importWsId === o.value ? 'primary' : 'default'}
                          onClick={() => { setImportWsId(o.value); setImportTableId(null) }}
                        >
                          {o.label}
                        </Button>
                      ))}
                      <Select
                        size="small"
                        style={{ minWidth: 180 }}
                        placeholder="跨工作区源表"
                        value={importTableId}
                        options={importTableOptions}
                        onChange={setImportTableId}
                        allowClear
                      />
                      <Button size="small" type="primary" disabled={importTableId === null} onClick={handleImportCrossTable}>引入</Button>
                    </div>
                  )}
                  <Form.Item name="description" label="描述（可选）" style={{ marginBottom: 8 }}>
                    <Input.TextArea rows={1} placeholder="简单说明这个模板的用途" />
                  </Form.Item>

                  {/* 模板参数定义区（整合进基本信息页签） */}
                  <Form.Item label="模板参数" tooltip="运行时传入的动态参数（可选）" style={{ marginBottom: 0 }}>
                    <Form.List name="parameters">
                      {(paramFields, { add, remove }) => (
                        <>
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                            {paramFields.map(({ key, name, ...restField }) => (
                              /* 每行一个参数：默认值/显示名/选项用 flex 弹性宽度，长内容可完整展示 */
                              <div key={key} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', flexBasis: '100%' }}>
                                <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]} style={{ width: 140, marginBottom: 4 }}>
                                  <Input placeholder="参数名" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'type']} style={{ width: 90, marginBottom: 4 }}>
                                  <Select options={PARAM_TYPES} />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'default']} style={{ flex: '1 1 160px', minWidth: 160, marginBottom: 4 }}>
                                  <Input placeholder="默认值" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'label']} style={{ flex: '1 1 140px', minWidth: 140, marginBottom: 4 }}>
                                  <Input placeholder="显示名" />
                                </Form.Item>
                                <Form.Item {...restField} name={[name, 'optionsText']} tooltip="逗号分隔的可选值，非空时渲染时显示下拉菜单" style={{ flex: '2 1 220px', minWidth: 220, marginBottom: 4 }}>
                                  <Input placeholder="选项(逗号分隔)" />
                                </Form.Item>
                                {/* Select 用 value prop 而非 checked，移除 valuePropName="checked" */}
                                <Form.Item {...restField} name={[name, 'required']} style={{ width: 80, marginBottom: 4 }}>
                                  <Select options={[{ value: true, label: '必填' }, { value: false, label: '可选' }]} />
                                </Form.Item>
                                <Tooltip title="删除该参数">
                                  <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
                                </Tooltip>
                              </div>
                            ))}
                          </div>
                          <Button type="dashed" onClick={() => add({ name: '', type: 'string', default: null, label: '', required: false })} block icon={<PlusOutlined />}>
                            添加参数
                          </Button>
                        </>
                      )}
                    </Form.List>
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'editor',
              label: erroredTabs.has('editor') ? <Badge dot>模板编辑</Badge> : '模板编辑',
              children: editorVisited ? (
                <Suspense fallback={<EditorLoadingFallback />}>
                  {/* 编辑器主体：内部模式切换 + 字段面板/编辑器/预览单区切换 */}
                  <div className="report-editor-toolbar">
                    <Segmented
                      size="small"
                      value={viewMode}
                      onChange={(v) => setViewMode(v as 'edit' | 'preview' | 'help')}
                      options={[
                        { label: '编辑模板', value: 'edit' },
                        { label: '实时预览', value: 'preview' },
                        { label: '语法帮助', value: 'help' },
                      ]}
                    />
                  </div>
                  <div className="report-editor-body" style={{ height: 'min(56vh, 640px)' }}>
                    {/* 编辑视图：保持挂载，仅切换显示，保证内容与插入能力不丢失 */}
                    <div className="report-editor-editpane" style={{ display: viewMode === 'edit' ? undefined : 'none' }}>
                      <ReportTemplateEditor
                        fields={selectedTableId !== null ? (fields as Field[]) : undefined}
                        tableGroups={tableGroups.length > 0 ? tableGroups : undefined}
                        value={templateValue}
                        onChange={handleTemplateChange}
                        editorRef={editorRef}
                      />
                    </div>

                    {viewMode === 'preview' && (
                      <div className="report-editor-viewpane">
                        <PreviewPanel
                          template={templateValue}
                          records={previewRows as Array<Record<string, unknown>>}
                          tableName={selectedTableName}
                          loading={previewLoading}
                          recordsByTable={recordsByTable}
                        />
                      </div>
                    )}

                    {viewMode === 'help' && (
                      <div className="report-editor-viewpane">
                        <SyntaxHelpPanel
                          onInsert={(code) => {
                            window.dispatchEvent(new CustomEvent('report-editor-insert', { detail: { code } }))
                          }}
                        />
                      </div>
                    )}
                  </div>
                </Suspense>
              ) : null,
            },
          ]}
        />

        {/* 隐藏的 template_content 字段 — 实际值由 CodeMirror 控制 */}
        <Form.Item name="template_content" rules={[{ required: true, message: '请输入模板内容' }]} style={{ display: 'none' }}>
          <Input />
        </Form.Item>
      </Form>{/* 关闭单一 Form — Tabs 两页签（基本信息含模板参数 / 模板编辑） */}

      {/* 底部按钮区 */}
      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--cn-border-soft)', textAlign: 'right' }}>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSave}>
            {editing ? '保存' : '创建'}
          </Button>
        </Space>
      </div>
    </Modal >
  )
}
