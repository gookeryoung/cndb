/** 表单管理页 — 工作区表单列表 + 新建/编辑 Drawer（字段编排 + 权限阈值）.
 *
 * 与「公开收集表单」（DataView.FORM / PublicFormPage）是两条产品线：
 * 本页管理的是认证态数据表单（表单定义 + 行增删查改 + 表单级权限）。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert, App as AntApp, Button, Drawer, Empty, Form, Input, Select, Space, Switch,
  Table, Tag, Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, AuditOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fieldApi, formApi, tableApi, workflowApi } from '@/api'
import type { FormFieldConfig, FormListItem, FormRoleThreshold, ID } from '@/api'

const { Title, Text } = Typography

/** 编辑 Drawer 表单值类型（table_id/name 为必填，其余可选或阈值可空） */
interface EditorValues {
  name: string
  description?: string
  table_id: ID
  use_role: FormRoleThreshold
  edit_role: FormRoleThreshold
  delete_role: FormRoleThreshold
  /** 绑定的审批流；null = 直接提交落库 */
  approval_workflow_id?: ID | null
}

const ROLE_OPTIONS: Array<{ value: FormRoleThreshold; label: string }> = [
  { value: '', label: '未配置（跟随表级权限）' },
  { value: 'viewer', label: 'viewer 及以上' },
  { value: 'editor', label: 'editor 及以上' },
  { value: 'admin', label: 'admin 及以上' },
]

function roleTag(role: FormRoleThreshold): string {
  return role || '表级'
}

export default function FormsPage() {
  const { message, modal } = AntApp.useApp()
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<FormListItem | null>(null)
  const [form] = Form.useForm<EditorValues>()

  const { data: forms = [], isLoading } = useQuery<FormListItem[]>({
    queryKey: ['forms', wid],
    queryFn: () => formApi.list(wid!),
    enabled: !!wid,
  })

  const remove = useMutation({
    mutationFn: (id: number | string) => formApi.remove(wid!, id),
    onSuccess: () => {
      message.success('表单已删除')
      void queryClient.invalidateQueries({ queryKey: ['forms', wid] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除表单失败'),
  })

  /** 类别数量：绑定审批流 vs 直接落库（蓝/金两色区分，与列表「审批」列同色系） */
  const approvalCount = forms.filter(f => f.approval_workflow_id != null).length

  const confirmDelete = (f: FormListItem) => {
    modal.confirm({
      title: `删除表单「${f.name}」？`,
      content: '删除后表单入口不可用，数据行本身不受影响。',
      okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: () => remove.mutate(f.id),
    })
  }

  const columns = [
    {
      title: '表单名称',
      dataIndex: 'name',
      key: 'name',
      render: (n: string, r: FormListItem) => (
        <a onClick={() => navigate(`/w/${wid}/forms/${r.id}`)}>{n}</a>
      ),
    },
    { title: '所属表', dataIndex: 'table_name', key: 'table_name', width: 160 },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (d: string) => d || <Text type="secondary" italic>—</Text>,
    },
    {
      title: '审批',
      dataIndex: 'approval_workflow_id',
      key: 'approval',
      width: 90,
      render: (wid: ID | null) =>
        wid ? <Tag color="gold" icon={<AuditOutlined />}>审批</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '权限阈值',
      key: 'roles',
      width: 260,
      render: (_: unknown, r: FormListItem) => (
        <Space size={[4, 4]} wrap>
          <Tag color="blue">使用:{roleTag(r.use_role)}</Tag>
          <Tag color="cyan">编辑:{roleTag(r.edit_role)}</Tag>
          <Tag color="geekblue">删除:{roleTag(r.delete_role)}</Tag>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, r: FormListItem) => (
        <Space size="small">
          <Button size="small" type="link" onClick={() => navigate(`/w/${wid}/forms/${r.id}`)}>打开</Button>
          <Button
            size="small" type="link" icon={<EditOutlined />}
            onClick={() => { setEditing(r); setDrawerOpen(true) }}
          >编辑</Button>
          <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => confirmDelete(r)} />
        </Space>
      ),
    },
  ]

  const openCreate = () => {
    setEditing(null)
    setDrawerOpen(true)
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space align="center" size={12}>
          <Title level={3} style={{ margin: 0 }}>表单</Title>
          {!isLoading && (
            <>
              <Tag color="blue" data-testid="form-count-direct">直接落库 {forms.length - approvalCount}</Tag>
              <Tag color="gold" data-testid="form-count-approval">走审批 {approvalCount}</Tag>
            </>
          )}
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建表单</Button>
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        为数据表配置定制化表单（认证态数据录入/编辑），支持字段子集、必填/只读与表单级权限阈值；
        需要匿名公开收集请使用数据表的「公开表单」视图。
      </Text>
      <Table
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={forms}
        pagination={false}
        locale={{
          emptyText: (
            <div style={{ padding: '24px 0' }}>
              <Empty description="还没有表单，先新建一个吧" />
              <Button type="primary" size="small" icon={<PlusOutlined />} style={{ marginTop: 12 }} onClick={openCreate}>新建表单</Button>
            </div>
          ),
        }}
      />
      <FormEditorDrawer
        open={drawerOpen}
        editing={editing}
        wid={wid!}
        form={form}
        onClose={() => { setDrawerOpen(false); setEditing(null); form.resetFields() }}
      />
    </div>
  )
}

// ─────────────── 表单编辑 Drawer ───────────────

interface DrawerProps {
  open: boolean
  editing: FormListItem | null
  wid: string
  form: FormInstance<EditorValues>
  onClose: () => void
}

function FormEditorDrawer({ open, editing, wid, form, onClose }: DrawerProps) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const { data: tables = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => tableApi.list(wid),
    enabled: open,
  })

  const selectedTableId = Form.useWatch('table_id', form)
  // 字段编排状态：field_name -> {included, required, editable}
  const [fieldStates, setFieldStates] = useState<Record<string, FormFieldConfig>>({})
  // 编排顺序（field_name 列表，支持上移/下移）
  const [fieldOrder, setFieldOrder] = useState<string[]>([])

  const { data: fields = [] } = useQuery({
    queryKey: ['workspaces', wid, 'tables', selectedTableId, 'fields'],
    queryFn: () => fieldApi.list(wid, selectedTableId!),
    enabled: open && !!selectedTableId,
  })

  // 工作区审批流（表单绑定后提交进入审批而非直接落库）
  const { data: workflows = [] } = useQuery({
    queryKey: ['workspaces', wid, 'workflows'],
    queryFn: () => workflowApi.list(wid),
    enabled: open,
  })

  const create = useMutation({
    mutationFn: (data: Parameters<typeof formApi.create>[1]) => formApi.create(wid, data),
    onSuccess: () => { message.success('表单已创建'); finish() },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建表单失败'),
  })
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number | string; data: Parameters<typeof formApi.update>[2] }) =>
      formApi.update(wid, id, data),
    onSuccess: () => { message.success('表单已保存'); finish() },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存表单失败'),
  })

  const finish = () => {
    onClose()
    void queryClient.invalidateQueries({ queryKey: ['forms', wid] })
  }

  // 打开时初始化：编辑态先拉详情再回显；新建态重置
  useEffect(() => {
    if (!open) return
    if (editing) {
      formApi.get(wid, editing.id).then(detail => {
        form.setFieldsValue({
          name: detail.name,
          description: detail.description,
          table_id: detail.table_id,
          use_role: detail.use_role,
          edit_role: detail.edit_role,
          delete_role: detail.delete_role,
          approval_workflow_id: detail.approval_workflow_id ?? null,
        })
        setFieldStates(Object.fromEntries(detail.field_config.map(fc => [fc.field_name, fc])))
        setFieldOrder(detail.field_config.map(fc => fc.field_name))
      }).catch(() => message.error('加载表单详情失败'))
    } else {
      form.resetFields()
      setFieldStates({})
      setFieldOrder([])
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // 切换表：清空编排（编辑态首次加载时 selectedTableId 与已有配置一致，不清）
  const tableChangedByUser = useRef(false)
  useEffect(() => {
    if (tableChangedByUser.current) {
      setFieldStates({})
      setFieldOrder([])
      tableChangedByUser.current = false
    }
  }, [selectedTableId])

  // 字段列表就绪后，补齐编排顺序（新出现的字段追加在尾部）
  useEffect(() => {
    if (!open || fields.length === 0) return
    setFieldOrder(prev => {
      const known = new Set(prev)
      const appended = [...prev, ...fields.map(f => f.name).filter(n => !known.has(n))]
      // 编辑态首次加载：若尚无任何编排（新建或字段漂移），默认全包含、按字段顺序
      return appended.length === 0 ? fields.map(f => f.name) : appended
    })
  }, [fields, open])

  const orderedFields = useMemo(() => {
    const byName = new Map(fields.map(f => [f.name, f]))
    const ordered: typeof fields = []
    for (const n of fieldOrder) {
      const f = byName.get(n)
      if (f) ordered.push(f)
    }
    // 兜底：fields 中存在但未入序的字段
    for (const f of fields) if (!fieldOrder.includes(f.name)) ordered.push(f)
    return ordered
  }, [fields, fieldOrder])

  const move = (name: string, dir: -1 | 1) => {
    setFieldOrder(prev => {
      const idx = prev.indexOf(name)
      const next = idx + dir
      if (idx < 0 || next < 0 || next >= prev.length) return prev
      const copy = [...prev]
      ;[copy[idx], copy[next]] = [copy[next], copy[idx]]
      return copy
    })
  }

  const updateState = (name: string, patch: Partial<FormFieldConfig>) => {
    setFieldStates(prev => {
      const base: FormFieldConfig = prev[name] ?? { field_name: name, editable: true, visible: true }
      return { ...prev, [name]: { ...base, ...patch } }
    })
  }

  const handleSubmit = (v: EditorValues) => {
    const field_config = fieldOrder
      .filter(n => fieldStates[n])
      .map(n => fieldStates[n])
    if (editing) update.mutate({ id: editing.id, data: { ...v, field_config } })
    else create.mutate({ ...v, field_config })
  }

  return (
    <Drawer
      title={editing ? `编辑表单「${editing.name}」` : '新建表单'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnHidden
      footer={
        <div style={{ textAlign: 'right' }}>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={create.isPending || update.isPending} onClick={() => form.submit()}>
              {editing ? '保存' : '创建'}
            </Button>
          </Space>
        </div>
      }
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item name="table_id" label="所属数据表" rules={[{ required: true, message: '请选择数据表' }]}>
          <Select
            options={tables.map(t => ({ value: t.id, label: t.name }))}
            placeholder="选择要挂载表单的数据表"
            onChange={() => { tableChangedByUser.current = true }}
            disabled={!!editing}
          />
        </Form.Item>
        <Form.Item name="name" label="表单名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="例如：客户信息录入" />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={1} placeholder="简单说明表单用途" />
        </Form.Item>

        <Form.Item label="字段编排" tooltip="勾选加入表单的字段、设置必填/只读，并用箭头调整顺序；不勾选任何字段时表单镜像整表">
          <div style={{ border: '1px solid var(--cn-border, #eee)', borderRadius: 8, padding: 8 }}>
            {orderedFields.length === 0 && (
              <Text type="secondary" data-testid="field-orchestration-empty">
                {selectedTableId ? '该表暂无字段' : '请先选择数据表'}
              </Text>
            )}
            {orderedFields.map((f, idx) => {
              const st = fieldStates[f.name]
              const included = !!st
              return (
                <div
                  key={f.name}
                  data-testid={`field-row-${f.name}`}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '6px 4px', borderBottom: idx < orderedFields.length - 1 ? '1px solid var(--cn-border-soft, #f0f0f0)' : undefined,
                    opacity: included ? 1 : 0.55,
                  }}
                >
                  <Switch
                    size="small"
                    checked={included}
                    aria-label={`包含字段 ${f.name}`}
                    onChange={checked => {
                      if (checked) updateState(f.name, {})
                      else setFieldStates(prev => {
                        const copy = { ...prev }
                        delete copy[f.name]
                        return copy
                      })
                    }}
                  />
                  <span style={{ minWidth: 80 }}>{f.name}</span>
                  <Tag style={{ marginLeft: 'auto' }}>{f.field_type}</Tag>
                  <Switch
                    size="small"
                    checkedChildren="必填" unCheckedChildren="选填"
                    disabled={!included}
                    checked={st?.required === true}
                    onChange={checked => updateState(f.name, { required: checked })}
                  />
                  <Switch
                    size="small"
                    checkedChildren="可编辑" unCheckedChildren="只读"
                    disabled={!included}
                    checked={st?.editable !== false}
                    onChange={checked => updateState(f.name, { editable: checked })}
                  />
                  <Space size={0}>
                    <Button type="text" size="small" icon={<ArrowUpOutlined />} disabled={idx === 0} aria-label={`上移 ${f.name}`} onClick={() => move(f.name, -1)} />
                    <Button type="text" size="small" icon={<ArrowDownOutlined />} disabled={idx === orderedFields.length - 1} aria-label={`下移 ${f.name}`} onClick={() => move(f.name, 1)} />
                  </Space>
                </div>
              )
            })}
          </div>
        </Form.Item>

        <Form.Item name="use_role" label="使用权限" tooltip="打开表单/查看行/提交新行的最低工作区角色；未配置时跟随表级权限">
          <Select options={ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item name="edit_role" label="编辑权限" tooltip="表单内编辑已有行的最低工作区角色">
          <Select options={ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item name="delete_role" label="删除权限" tooltip="表单内删除行的最低工作区角色">
          <Select options={ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="approval_workflow_id"
          label="提交审批流（可选）"
          tooltip="绑定后经表单提交的数据进入审批流逐级审批，链尾通过才落库；未绑定时提交直接落库"
        >
          <Select
            allowClear
            placeholder="不绑定（提交直接落库）"
            options={workflows.map(wf => ({ value: wf.id, label: wf.name }))}
            notFoundContent={<Text type="secondary">尚无审批流，可在「审批流」页创建</Text>}
          />
        </Form.Item>
        <Alert
          type="info" showIcon
          message="表单权限只能收紧、不能放宽表级限制；未配置阈值时按数据表权限判定。"
        />
      </Form>
    </Drawer>
  )
}
