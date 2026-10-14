/** 渲染参数弹窗 —— 自定义参数 + 额外引用表 + 临时覆盖取数视图. */

import { useEffect, useMemo, useState } from 'react'
import { Modal, Form, Input, Typography, Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { viewApi } from '@/api'
import type { ReportTemplateSummary, TableSummary, View } from '@/api'

// ════════════════════════════════════════════════ 渲染参数 Modal ════════════════════════════════════════════════

interface RenderParamsModalProps {
  open: boolean
  target: ReportTemplateSummary | null
  tables: TableSummary[]
  /** 当前工作区 ID，用于加载主表的视图列表（临时覆盖渲染取数视图） */
  wid: string | undefined
  onClose: () => void
  onSubmit: (params: Record<string, unknown>, extraTableIds?: number[], viewId?: number | null) => void
  submitting: boolean
}

export function RenderParamsModal({ open, target, tables, wid, onClose, onSubmit, submitting }: RenderParamsModalProps) {
  const [form] = Form.useForm<Record<string, unknown>>()
  const [extraTableIds, setExtraTableIds] = useState<number[]>([])
  // 渲染视图覆盖：初始为模板绑定视图，清除/未改即回退模板默认，改选其他视图则临时覆盖
  const [viewId, setViewId] = useState<number | null>(null)

  useEffect(() => {
    if (open && target) {
      const initial: Record<string, unknown> = {}
      target.parameters.forEach(p => { if (p.default !== undefined) initial[p.name] = p.default })
      form.setFieldsValue(initial as any)
      // 默认带入模板已保存的额外引用表（含跨工作区表）
      setExtraTableIds(target.extra_table_ids ?? [])
      setViewId(target.view_id ?? null)
    }
  }, [open, target, form])

  // 主表视图列表（临时覆盖渲染取数视图用）
  const { data: tableViews = [] } = useQuery<View[]>({
    queryKey: ['workspaces', wid, 'tables', target?.table_id, 'views'],
    queryFn: () => viewApi.list(wid!, target!.table_id!),
    enabled: open && !!wid && !!target?.table_id,
  })

  const tableNameMap = useMemo(() => new Map(tables.map(t => [t.id, t.name])), [tables])

  // 额外表选项（排除模板关联的主表；跨工作区表不在本区 tables，补占位选项避免选中值显示裸数字）
  const extraTableOptions = useMemo(() => {
    const base = target?.table_id ? tables.filter(t => t.id !== target.table_id) : tables
    const opts = base.map(t => ({ value: t.id, label: t.name }))
    for (const eid of target?.extra_table_ids ?? []) {
      if (!opts.some(o => o.value === eid)) opts.push({ value: eid, label: `跨工作区表 #${eid}` })
    }
    return opts
  }, [tables, target?.table_id, target?.extra_table_ids])

  return (
    <Modal
      title={target ? `渲染模板：${target.name}` : '渲染参数'}
      open={open}
      onCancel={() => { form.resetFields(); setExtraTableIds([]); setViewId(null); onClose() }}
      confirmLoading={submitting}
      okText="生成报告"
      cancelText="取消"
      onOk={async () => {
        try {
          const values = await form.validateFields()
          onSubmit(values as Record<string, unknown>, extraTableIds.length > 0 ? extraTableIds : undefined, viewId)
        } catch { /* 用户取消校验 */ }
      }}
    >
      {target?.table_id ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          数据源表：{tableNameMap.get(target.table_id) || `#${target.table_id}`}
        </Typography.Text>
      ) : (
        <Typography.Text type="danger" style={{ display: 'block', marginBottom: 16 }}>
          模板未关联数据表，无法渲染
        </Typography.Text>
      )}

      {/* 渲染视图覆盖：初始为模板绑定视图，清除即回退模板默认，改选则临时覆盖本次取数 */}
      {target?.table_id && (
        <Form.Item label="取数视图" tooltip="本次渲染按所选视图的过滤/排序取数；清除则使用模板绑定的视图（未绑定时取全部数据）" style={{ marginBottom: 12 }}>
          <Select<number | null>
            options={tableViews.map(v => ({ value: v.id as number, label: v.name }))}
            placeholder="使用模板绑定的视图"
            value={viewId}
            onChange={val => setViewId(val ?? null)}
            allowClear
          />
        </Form.Item>
      )}

      {/* 额外引用表选择 */}
      {target?.table_id && (
        <Form.Item label="额外引用表" tooltip="模板中可通过 records_by_table['表名'] 引用" style={{ marginBottom: 12 }}>
          <Select
            mode="multiple"
            options={extraTableOptions}
            placeholder="选择额外引用的数据表（可选）"
            value={extraTableIds}
            onChange={setExtraTableIds}
            allowClear
            maxTagCount={3}
          />
        </Form.Item>
      )}

      <Form form={form} layout="vertical" disabled={!target?.table_id}>
        {target?.parameters.map(p => (
          <Form.Item
            key={p.name}
            label={p.label || p.name}
            name={p.name}
            rules={p.required ? [{ required: true, message: `参数 ${p.name} 必填` }] : []}
          >
            {p.type === 'boolean' ? (
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            ) : p.options && p.options.length > 0 ? (
              <Select options={p.options.map(o => ({ value: o, label: o }))} virtual={false} placeholder={`请选择 ${p.label || p.name}`} />
            ) : p.type === 'number' ? (
              <Input type="number" placeholder={`请输入 ${p.name}`} />
            ) : p.type === 'date' ? (
              <Input type="date" />
            ) : (
              <Input placeholder={`请输入 ${p.name}`} />
            )}
          </Form.Item>
        ))}
        {(!target?.parameters || target.parameters.length === 0) && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            该模板无自定义参数，选择额外引用表后直接点击「生成报告」
          </Typography.Text>
        )}
      </Form>
    </Modal>
  )
}
