/** 设计管理页（设计模块默认页，ADR 0084 D5）
 *
 * 形态对齐文档模块分工：侧栏 = 装配结构树（导航），主区 = 设计管理列表
 * （新建 / 打开 / 改名 / 描述 / 删除 + 版本与更新时间摘要）。
 * 装配结构树已迁至侧栏（`DesignStructureNav`），本页不再渲染大纲树。
 */

import { useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, List, Modal, Popconfirm, Skeleton, Space, Tag, Typography,
} from 'antd'
import { ApartmentOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignListItem } from '@/api'
import { formatDateTime } from '@/utils/datetime'
import { designEditorPath } from './designOutline'

const { Text } = Typography

/** 新建设计的起步模板：复杂系统（system）→ 组件（module）→ 零件（图元）三级装配示例
 *  （ADR 0084 §9；后端编译通过才落 v1 版本） */
export const DEFAULT_DESIGN_CONTENT = `// 四轮小车（rover）：复杂系统 → 组件 → 零件三级装配示例
param body_len = 120
param body_w = 60
param body_t = 8
param wheel_d = 40
param wheel_w = 16
param axle_d = 10

// 组件级：module 可复用 / 可实例化 / 可嵌套（子装配）
module wheel(d, w) {
  rotate([90, 0, 0])
    difference {
      cyl(d = d, h = w)
      translate([0, 0, -1]) cyl(d = d * 0.35, h = w + 2)
    }
}

module axle(d, len) {
  rotate([90, 0, 0]) tube(od = d, id = d * 0.6, h = len)
}

module chassis(len, w, t) {
  difference {
    box(size = [len, w, t])
    translate([0, 0, -1]) cyl(d = 14, h = t + 2)
  }
}

// 系统级：复杂系统装配声明（顶层根，不可实例化）
system rover {
  chassis(body_len, body_w, body_t)

  translate([body_len / 2 - 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)
  translate([body_len / 2 - 18, body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)
  translate([body_len / 2 - 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([-body_len / 2 + 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)
  translate([-body_len / 2 + 18, body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)
  translate([-body_len / 2 + 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([0, 0, body_t + 42]) sphere(r = 14)   // 零件级细节：传感器球头
}
`

interface DesignFormValues {
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
  const [createForm] = Form.useForm<DesignFormValues>()
  const [renaming, setRenaming] = useState<DesignListItem | null>(null)
  const [renameForm] = Form.useForm<DesignFormValues>()

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['designs', wid] })

  const create = useMutation({
    mutationFn: (values: DesignFormValues) =>
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
      navigate(designEditorPath(wid, created.id))
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建失败'),
  })

  const rename = useMutation({
    mutationFn: (payload: { item: DesignListItem; values: DesignFormValues }) =>
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
            <ApartmentOutlined />
            <Text strong style={{ fontSize: 18 }}>设计结构</Text>
          </Space>
          <div>
            <Text type="secondary">
              侧栏按装配层级（系统 → 组件 → 零件）浏览设计；本页管理设计，点击进入结构 DSL 编辑器。
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
        <div className="cn-design-structure" data-testid="design-list">
          <List
            dataSource={designs}
            renderItem={(item) => (
              <List.Item
                data-testid={`design-row-${item.id}`}
                actions={[
                  <Button key="open" size="small" type="link" onClick={() => navigate(designEditorPath(wid, item.id))}>
                    打开
                  </Button>,
                  ...(isViewer
                    ? []
                    : [
                        <Button
                          key="edit"
                          size="small"
                          type="link"
                          icon={<EditOutlined />}
                          onClick={() => openRename(item)}
                        >
                          编辑
                        </Button>,
                        <Popconfirm
                          key="delete"
                          title={`删除设计「${item.title}」？`}
                          description="版本历史会一并隐藏，操作不可撤销。"
                          okText="删除"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => remove.mutate(item)}
                        >
                          <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
                        </Popconfirm>,
                      ]),
                ]}
              >
                <List.Item.Meta
                  title={<Text strong>{item.title}</Text>}
                  description={(
                    <span className="cn-design-tree-meta">
                      {item.description || '（无描述）'}
                      {' · '}v{item.version_count}
                      {' · '}更新于 {formatDateTime(item.updated_at)}
                    </span>
                  )}
                />
              </List.Item>
            )}
          />
          <div style={{ padding: '0 var(--cn-space-lg) var(--cn-space-sm)' }}>
            <Text type="secondary">
              <Tag bordered={false}>提示</Tag>
              展开侧栏中的设计可查看系统 / 组件 / 零件层级，点击节点定位到源行。
            </Text>
          </div>
        </div>
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
          <Text type="secondary">将以示例模板（四轮小车：系统 / 组件 / 零件三级装配）创建，创建后可自由编辑。</Text>
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
