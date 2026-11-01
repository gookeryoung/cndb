/** 设计列表页 —— 新建 / 打开 / 改名 / 描述 / 删除（ADR 0079 §6）.
 *
 * 数据源 `designsApi`（queryKey 约定：['designs', wid]）。新建以法兰板示例
 * 模板起步（与 ADR 0079 §2 示例一致），保存前原文必经后端编译校验。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, Listy, Modal, Popconfirm, Skeleton, Space, Typography,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ToolOutlined } from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignListItem } from '@/api'
import { formatDateTime } from '@/utils/datetime'

const { Text } = Typography

/** 新建设计的起步模板（ADR 0079 §2 法兰板示例） */
export const DEFAULT_DESIGN_CONTENT = `// 参数：驱动参数面板，可被预览覆盖重编译
param width = 80          // 长度单位 mm
param height = 40
param hole_d = 8

// 模块：带默认值的可复用结构
module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w / 2, h / 2, -1]) {
      cyl(d = hole_d, h = t + 2)   // 减切通孔：两端各出 1mm
    }
  }
}

plate(width, height, 12)            // 顶层实例（产出几何）
`

interface CreateFormValues {
  title: string
  description?: string
}

interface RenameFormValues {
  title: string
  description?: string
}

export default function DesignsPage() {
  const { wid = '' } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const { data: designs = [], isLoading } = useQuery({
    queryKey: ['designs', wid],
    queryFn: () => designsApi.list(wid),
    enabled: !!wid,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const isViewer = wsDetail?.current_user_role === 'viewer'

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [renaming, setRenaming] = useState<DesignListItem | null>(null)
  const [renameForm] = Form.useForm<RenameFormValues>()

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['designs', wid] })

  const create = useMutation({
    mutationFn: (values: CreateFormValues) =>
      designsApi.create(wid, {
        title: values.title,
        description: values.description ?? '',
        content: DEFAULT_DESIGN_CONTENT,
      }),
    onSuccess: (created) => {
      message.success('设计已创建')
      setCreateOpen(false)
      createForm.resetFields()
      invalidate()
      navigate(`/w/${wid}/design/${created.id}`)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建失败'),
  })

  const rename = useMutation({
    mutationFn: (payload: { item: DesignListItem; values: RenameFormValues }) =>
      designsApi.update(wid, payload.item.id, {
        title: payload.values.title,
        description: payload.values.description ?? payload.item.description,
      }),
    onSuccess: () => {
      message.success('已更新')
      setRenaming(null)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '更新失败'),
  })

  const remove = useMutation({
    mutationFn: (item: DesignListItem) => designsApi.remove(wid, item.id),
    onSuccess: () => {
      message.success('设计已删除')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const openRename = (item: DesignListItem) => {
    renameForm.setFieldsValue({ title: item.title, description: item.description })
    setRenaming(item)
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 960, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <Space size={8}>
            <ToolOutlined />
            <Text strong style={{ fontSize: 18 }}>设计</Text>
          </Space>
          <div>
            <Text type="secondary">
              用结构 DSL（.cnmd）描述产品结构：参数化图元 + 模块复用 + 布尔组合，编辑时实时 3D 预览。
            </Text>
          </div>
        </div>
        {!isViewer && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建设计</Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton active />
      ) : designs.length === 0 ? (
        <Empty description="还没有结构设计" style={{ padding: 48 }} />
      ) : (
        <Listy
          className="cn-listy-plain"
          items={designs}
          rowKey={item => item.id}
          itemRender={(item: DesignListItem) => (
            <div className="cn-list-item" data-testid={`design-item-${item.id}`}>
              <div className="cn-list-item-main">
                <CnListMeta
                  title={<Text strong>{item.title}</Text>}
                  description={(
                    <Text type="secondary">
                      {item.description || '（无描述）'}
                      {' · '}v{item.version_count}
                      {' · 更新于 '}
                      {formatDateTime(item.updated_at)}
                    </Text>
                  )}
                />
              </div>
              <div className="cn-list-item-actions">
                <Space size={4}>
                  <Button type="link" size="small" onClick={() => navigate(`/w/${wid}/design/${item.id}`)}>
                    打开
                  </Button>
                  {!isViewer && (
                    <>
                      <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openRename(item)}>
                        编辑
                      </Button>
                      <Popconfirm
                        title={`删除设计「${item.title}」？`}
                        description="版本历史会一并隐藏，操作不可撤销。"
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        onConfirm={() => remove.mutate(item)}
                      >
                        <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                      </Popconfirm>
                    </>
                  )}
                </Space>
              </div>
            </div>
          )}
        />
      )}

      <Modal
        title="新建设计"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        okText="创建"
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" onFinish={values => create.mutate(values)}>
          <Form.Item
            name="title"
            label="名称"
            rules={[
              { required: true, message: '请输入设计名称' },
              { max: 200, message: '名称不超过 200 字' },
            ]}
          >
            <Input placeholder="如：法兰板" autoFocus />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} maxLength={500} placeholder="用途说明" />
          </Form.Item>
          <Text type="secondary">将以示例模板（参数化法兰板）创建，创建后可自由编辑。</Text>
        </Form>
      </Modal>

      <Modal
        title="编辑设计信息"
        open={renaming !== null}
        onCancel={() => setRenaming(null)}
        onOk={() => renameForm.submit()}
        okText="保存"
        confirmLoading={rename.isPending}
        destroyOnHidden
      >
        <Form form={renameForm} layout="vertical" onFinish={values => renaming && rename.mutate({ item: renaming, values })}>
          <Form.Item
            name="title"
            label="名称"
            rules={[
              { required: true, message: '请输入设计名称' },
              { max: 200, message: '名称不超过 200 字' },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
