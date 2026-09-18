/** 表设置 Modal — 四个 Tab：基本信息 / 字段 / 视图 / 权限.
 *
 * 聚合 FieldManager（字段）、PermissionEditor（权限）、CreateEditViewForm（视图创建/编辑），
 * 形成统一的表级设置入口。
 *
 * 支持两种模式：
 *  - 普通 Modal 模式（open/onClose）
 *  - embedded 模式（embedded=true，用于独立设置页面）
 */

import { Suspense, lazy, useEffect, useState } from 'react'
import {
  Modal, Tabs, Form, Input, Button, Descriptions, Tag, Popconfirm, message, Space, Empty,
} from 'antd'
import {
  InfoCircleOutlined, UnorderedListOutlined, AppstoreOutlined, SafetyOutlined,
  SaveOutlined, EditOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tableApi, permissionApi, viewApi } from '@/api'
import type { TableDetail, TableUpdate, ViewCreate } from '@/api'
import PermissionEditor from '@/pages/grid/components/PermissionEditor'

const FieldManager = lazy(() => import('@/pages/modals/FieldManager'))
const CreateEditViewForm = lazy(() => import('@/pages/grid/components/CreateEditViewForm'))

interface Props {
  open?: boolean
  wid: string
  tid: string
  onClose?: () => void
  /** 保存成功或删除后通知 GridPage 刷新 */
  onUpdated?: () => void
  /** 指定打开时的 Tab */
  initialTab?: 'basic' | 'fields' | 'views' | 'permissions'
  /** embedded 模式：不包 Modal 外壳，用于独立设置页面 */
  embedded?: boolean
}

function hasAction(actions: string[] | undefined, action: string): boolean {
  return Array.isArray(actions) && actions.includes(action)
}

/** 表设置 Modal / Content.
 *  - embedded=false（默认）→ 外层 Modal 包裹，由 open 控制显隐
 *  - embedded=true → 直接返回 Tabs 主体（用于独立页面）
 */
export default function TableSettingsModal({
  open, wid, tid, onClose, onUpdated, initialTab = 'basic', embedded = false,
}: Props) {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(initialTab)
  const [form] = Form.useForm<TableUpdate>()
  const [viewEditorOpen, setViewEditorOpen] = useState(false)
  const [viewEditorInitial, setViewEditorInitial] = useState<{
    vid?: number | string
    name?: string
    viewType?: string
    options?: Record<string, unknown>
  }>({})

  const isActive = embedded || !!open

  // 表详情（含统计 + current_user_actions + 视图摘要）
  const { data: table, isLoading } = useQuery<TableDetail>({
    queryKey: ['table-settings', wid, tid],
    queryFn: () => tableApi.get(wid, tid),
    enabled: isActive,
  })

  // 视图列表（完整列表用于 Tab3 内联展示/编辑）
  const { data: views = [] } = useQuery({
    queryKey: ['table-views', wid, tid],
    queryFn: () => viewApi.list(wid, tid),
    enabled: isActive,
  })

  // 权限数据（切到 permissions Tab 时 refetch）
  const { data: permData, refetch: refetchPerm } = useQuery({
    queryKey: ['table-perm', wid, tid],
    queryFn: () => permissionApi.get(wid, tid),
    enabled: false,
  })

  // 基本信息更新
  const updateTable = useMutation({
    mutationFn: (data: TableUpdate) => tableApi.update(wid, tid, data),
    onSuccess: () => {
      message.success('已保存')
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table', `${wid}/${tid}`] })
      onUpdated?.()
    },
  })

  const removeTable = useMutation({
    mutationFn: () => tableApi.remove(wid, tid),
    onSuccess: () => {
      message.success('表已删除')
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
      queryClient.invalidateQueries({ queryKey: ['workspaces', wid] })
      onUpdated?.()
      onClose?.()
    },
  })

  const savePerm = useMutation({
    mutationFn: (data: Parameters<typeof permissionApi.patch>[2]) => permissionApi.patch(wid, tid, data),
    onSuccess: () => {
      message.success('权限已更新')
      queryClient.invalidateQueries({ queryKey: ['table-perm', wid, tid] })
    },
  })

  const createView = useMutation({
    mutationFn: (data: ViewCreate) => viewApi.create(wid, tid, data),
    onSuccess: () => {
      message.success('视图已创建')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
    },
  })
  const updateView = useMutation({
    mutationFn: (args: { vid: number | string; data: Partial<ViewCreate> }) =>
      viewApi.update(wid, tid, args.vid, args.data),
    onSuccess: () => {
      message.success('视图已更新')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
    },
  })
  const removeView = useMutation({
    mutationFn: (vid: number | string) => viewApi.remove(wid, tid, vid),
    onSuccess: () => {
      message.success('视图已删除')
      queryClient.invalidateQueries({ queryKey: ['table-views', wid, tid] })
      queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
    },
  })

  const handleTabChange = (key: string) => {
    setActiveTab(key as typeof initialTab)
    if (key === 'permissions') refetchPerm()
  }

  // 打开 / embedded 模式 / 表切换时，初始化基本信息表单
  useEffect(() => {
    if (isActive && table) {
      form.setFieldsValue({ name: table.name, description: table.description })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, table?.id])

  const actions = table?.current_user_actions ?? []
  const canEditSchema = hasAction(actions, 'edit_schema')
  const canEditViews = hasAction(actions, 'edit_views')
  const canEditRecords = hasAction(actions, 'edit_records')
  const canEditBasic = canEditSchema
  const canDeleteTable = !table?.trashed && canEditSchema

  const tabs = (
    <Tabs
      activeKey={activeTab}
      onChange={handleTabChange}
      items={[
        // ────────────── Tab 1: 基本信息 ──────────────
        {
          key: 'basic',
          label: <span><InfoCircleOutlined /> 基本信息</span>,
          children: table ? (
            <div style={{ paddingTop: 8 }}>
              <Descriptions column={3} bordered size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="字段数">
                  <Tag>{table.field_count ?? table.fields.length}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="记录数">
                  <strong>{table.record_count ?? 0}</strong>
                </Descriptions.Item>
                <Descriptions.Item label="视图数">
                  <Tag color="purple">{table.view_count ?? (table.views?.length ?? 0)}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="表 ID">{table.id}</Descriptions.Item>
                <Descriptions.Item label="工作区">{table.workspace_id}</Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {table.created_at ? new Date(table.created_at).toLocaleString() : '—'}
                </Descriptions.Item>
              </Descriptions>

              <Form
                key={`basic-${table?.id ?? 'loading'}`}
                form={form}
                layout="vertical"
                initialValues={{ name: table?.name ?? '', description: table?.description ?? '' }}
                onFinish={(v) => updateTable.mutate(v)}
              >
                <Form.Item
                  name="name"
                  label="表名"
                  rules={[{ required: true, message: '请输入表名' }, { max: 64 }]}
                >
                  <Input maxLength={64} showCount disabled={!canEditBasic} />
                </Form.Item>
                <Form.Item name="description" label="描述（可选）">
                  <Input.TextArea rows={3} maxLength={500} showCount disabled={!canEditBasic} />
                </Form.Item>

                <Space>
                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    htmlType="submit"
                    loading={updateTable.isPending}
                    disabled={!canEditBasic}
                  >
                    保存
                  </Button>
                  <Popconfirm
                    title={`删除表 "${table.name}" ？`}
                    description="表内所有记录和字段将被永久移除。此操作不可恢复。"
                    okText="删除"
                    okType="danger"
                    cancelText="取消"
                    onConfirm={() => removeTable.mutate()}
                    disabled={!canDeleteTable}
                  >
                    <Button danger icon={<DeleteOutlined />} disabled={!canDeleteTable}>
                      删除表
                    </Button>
                  </Popconfirm>
                  {!canDeleteTable && table && (
                    <Tag color="warning" style={{ marginLeft: 8 }}>
                      需要 edit_schema 权限才能删除此表
                    </Tag>
                  )}
                </Space>
              </Form>
            </div>
          ) : <Empty description="加载中..." />,
        },

        // ────────────── Tab 2: 字段 ──────────────
        {
          key: 'fields',
          label: <span><UnorderedListOutlined /> 字段</span>,
          children: (
            <Suspense fallback={<div style={{ padding: 48, textAlign: 'center' }}>加载字段管理器...</div>}>
              <FieldManager
                embedded
                open={true}
                wid={wid}
                tid={tid}
                fields={table?.fields ?? []}
                onClose={onClose ?? (() => {})}
                onChanged={() => {
                  queryClient.invalidateQueries({ queryKey: ['table-settings', wid, tid] })
                  queryClient.invalidateQueries({ queryKey: ['table', `${wid}/${tid}`] })
                  queryClient.invalidateQueries({ queryKey: ['table-records', `${wid}/${tid}`] })
                }}
              />
            </Suspense>
          ),
        },

        // ────────────── Tab 3: 视图 ──────────────
        {
          key: 'views',
          label: <span><AppstoreOutlined /> 视图</span>,
          children: (
            <div style={{ paddingTop: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ color: 'var(--cn-text-secondary)' }}>共 {views.length} 个视图</span>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  disabled={!canEditViews}
                  onClick={() => {
                    setViewEditorInitial({})
                    setViewEditorOpen(true)
                  }}
                >
                  新建视图
                </Button>
              </div>

              {views.length === 0 && (
                <Empty description="暂无视图，点击右上角「新建视图」创建" style={{ padding: 32 }} />
              )}

              {views.map((v: any) => (
                <div
                  key={String(v.id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 12px', marginBottom: 6,
                    border: '1px solid var(--cn-border)', borderRadius: 6,
                    background: 'var(--cn-bg-subtle)',
                  }}
                >
                  <strong style={{ flex: 1 }}>{v.name}</strong>
                  <Tag>{v.view_type}</Tag>
                  {v.is_default && <Tag color="blue">默认</Tag>}
                  <Space size={4}>
                    <Button
                      size="small" type="text" icon={<EditOutlined />} disabled={!canEditViews}
                      onClick={() => {
                        setViewEditorInitial({
                          vid: v.id,
                          name: v.name,
                          viewType: v.view_type,
                          options: v.view_options,
                        })
                        setViewEditorOpen(true)
                      }}
                    />
                    <Popconfirm
                      title={`删除视图 "${v.name}" ？`}
                      okText="删除"
                      okType="danger"
                      cancelText="取消"
                      onConfirm={() => removeView.mutate(v.id)}
                      disabled={!canEditViews}
                    >
                      <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!canEditViews} />
                    </Popconfirm>
                  </Space>
                </div>
              ))}
            </div>
          ),
        },

        // ────────────── Tab 4: 权限 ──────────────
        {
          key: 'permissions',
          label: <span><SafetyOutlined /> 权限</span>,
          children: table ? (
            <div style={{ paddingTop: 8 }}>
              <div style={{ marginBottom: 12 }}>
                <span style={{ fontSize: 13, color: 'var(--cn-text-primary)', marginRight: 8 }}>您当前在本表的权限：</span>
                <Space size={[4, 4]} wrap>
                  {canEditRecords && <Tag color="blue">编辑记录</Tag>}
                  {canEditViews && <Tag color="purple">编辑视图</Tag>}
                  {canEditSchema && <Tag color="gold">编辑结构</Tag>}
                  {!canEditRecords && !canEditViews && !canEditSchema && <Tag color="default">仅查看</Tag>}
                </Space>
              </div>

              <PermissionEditor fields={table.fields ?? []} data={permData as any} wid={wid} tid={tid} owner={table.owner ?? null} />

              <div style={{ marginTop: 16, textAlign: 'right' }}>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={savePerm.isPending}
                  disabled={!canEditSchema}
                  onClick={() => {
                    const hiddenInputs = document.querySelectorAll<HTMLInputElement>('input[data-perm-hidden]:checked')
                    const hiddenFields = Array.from(hiddenInputs).map(i => i.value)
                    const el = document.querySelector<HTMLInputElement>('input[data-perm-comment]')
                    const payloadHidden: Record<string, string[]> = hiddenFields.length > 0
                      ? { admin: hiddenFields }
                      : {}
                    savePerm.mutate({
                      hidden_fields: payloadHidden,
                      row_filters: null,
                      comment_role: el?.value ?? undefined,
                    })
                  }}
                >
                  保存权限
                </Button>
              </div>
            </div>
          ) : <Empty description="加载中..." />,
        },
      ]}
    />
  )

  // 视图表单弹层 — 创建 / 编辑共用
  const viewEditor = viewEditorOpen && (
    <Modal
      title={viewEditorInitial.vid ? '编辑视图' : '新建视图'}
      open={true}
      onCancel={() => setViewEditorOpen(false)}
      footer={null}
      destroyOnHidden
    >
      <Suspense fallback={<div style={{ padding: 48, textAlign: 'center' }}>加载表单...</div>}>
        <CreateEditViewForm
          fields={table?.fields ?? []}
          initialName={viewEditorInitial.name}
          initialType={viewEditorInitial.viewType}
          initialOptions={viewEditorInitial.options}
          submitLabel={viewEditorInitial.vid ? '保存' : '创建'}
          onSubmit={(name, vt, opts) => {
            if (viewEditorInitial.vid != null) {
              updateView.mutate({
                vid: viewEditorInitial.vid,
                data: { name, view_type: vt, ...(opts && Object.keys(opts).length ? { view_options: opts } : {}) },
              })
            } else {
              createView.mutate({
                name, view_type: vt,
                ...(opts && Object.keys(opts).length ? { view_options: opts } : {}),
              })
            }
            setViewEditorOpen(false)
          }}
        />
      </Suspense>
    </Modal>
  )

  if (embedded) {
    return (
      <>
        {tabs}
        {viewEditor}
      </>
    )
  }

  return (
    <Modal
      title={
        <Space>
          <span>表设置</span>
          {table?.name && <Tag color="blue">{table.name}</Tag>}
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={780}
      destroyOnHidden
      footer={null}
      loading={isLoading}
    >
      {tabs}
      {viewEditor}
    </Modal>
  )
}
