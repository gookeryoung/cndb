import { useState, useMemo } from 'react'
import {
  Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { TablePaginationConfig } from 'antd/es/table'
import dayjs from 'dayjs'
import { crudApi, type User, type UserCreatePayload, type UserUpdatePayload } from '@/api'

const { Title, Text } = Typography
const DEFAULT_PAGE_SIZE = 10

const ROLE_COLOR: Record<string, string> = { admin: 'red', user: 'blue', guest: 'default' }

export default function UserList() {
  const queryClient = useQueryClient()
  const [pagination, setPagination] = useState({ current: 1, pageSize: DEFAULT_PAGE_SIZE })
  const [modalOpen, setModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [form] = Form.useForm<UserCreatePayload | UserUpdatePayload>()

  const { data, isFetching } = useQuery({
    queryKey: ['users', pagination.current, pagination.pageSize],
    queryFn: () => crudApi
      .listUsers({ offset: (pagination.current - 1) * pagination.pageSize, limit: pagination.pageSize })
      .then((r) => r.data),
  })
  const users = useMemo(() => data?.items ?? [], [data])
  const total = data?.total ?? 0

  const createMutation = useMutation({
    mutationFn: (payload: UserCreatePayload) => crudApi.createUser(payload).then((r) => r.data),
    onSuccess: () => { message.success('用户创建成功'); queryClient.invalidateQueries({ queryKey: ['users'] }) },
    onError: () => message.error('创建失败'),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UserUpdatePayload }) =>
      crudApi.updateUser(id, payload).then((r) => r.data),
    onSuccess: () => { message.success('用户更新成功'); queryClient.invalidateQueries({ queryKey: ['users'] }) },
    onError: () => message.error('更新失败'),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => crudApi.deleteUser(id),
    onSuccess: () => {
      message.success('用户已删除')
      if (users.length === 1 && pagination.current > 1) {
        setPagination((p) => ({ ...p, current: p.current - 1 }))
      }
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: () => message.error('删除失败'),
  })

  const openCreate = () => {
    setEditingUser(null)
    form.resetFields()
    form.setFieldsValue({ role: 'user' })
    setModalOpen(true)
  }
  const openEdit = (user: User) => {
    setEditingUser(user)
    form.setFieldsValue({ username: user.username, email: user.email, role: user.role })
    setModalOpen(true)
  }
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingUser) {
        updateMutation.mutate({ id: editingUser.id, payload: values as UserUpdatePayload })
      } else {
        createMutation.mutate(values as UserCreatePayload)
      }
      setModalOpen(false)
    } catch { /* 校验失败 antd 自动提示 */ }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', key: 'username', render: (n: string) => <Text strong>{n}</Text> },
    { title: '邮箱', dataIndex: 'email', key: 'email', render: (e: string) => <Text code>{e}</Text> },
    { title: '角色', dataIndex: 'role', key: 'role', width: 100,
      render: (r: string) => <Tag color={ROLE_COLOR[r] || 'default'}>{r}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
    { title: '操作', key: 'actions', width: 140, fixed: 'right' as const,
      render: (_: unknown, record: User) => (
        <Space size="small">
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title={`确定删除用户 "${record.username}" 吗？`} okText="删除" okButtonProps={{ danger: true }} cancelText="取消"
            onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const handleTableChange = (pag: TablePaginationConfig) => {
    if (pag.current && pag.pageSize) setPagination({ current: pag.current, pageSize: pag.pageSize })
  }

  const modalTitle = editingUser ? `编辑用户 #${editingUser.id}` : '新建用户'
  const roleOptions = [
    { value: 'admin', label: '管理员' },
    { value: 'user', label: '普通用户' },
    { value: 'guest', label: '访客' },
  ]

  return (
    <div style={{ padding: 8 }}>
      <Title level={3} style={{ marginTop: 0 }}>用户管理</Title>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
        <Button icon={<ReloadOutlined />} onClick={() => queryClient.invalidateQueries({ queryKey: ['users'] })} loading={isFetching}>刷新</Button>
        <Text type="secondary">共 {total} 条记录</Text>
      </Space>

      <Table<User>
        rowKey="id" columns={columns} dataSource={users} loading={isFetching} scroll={{ x: 900 }}
        pagination={{ current: pagination.current, pageSize: pagination.pageSize, total,
          showSizeChanger: true, showQuickJumper: true, pageSizeOptions: ['10', '20', '50'],
          showTotal: (t) => `共 ${t} 条` }}
        onChange={handleTableChange}
      />

      <Modal title={modalTitle} open={modalOpen} onCancel={() => setModalOpen(false)}
        onOk={handleSubmit} confirmLoading={createMutation.isPending || updateMutation.isPending} destroyOnClose>
        <Form form={form} layout="vertical" preserve={false} initialValues={{ role: 'user' }}>
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }, { min: 2, max: 32, message: '长度 2~32 字符' }]}>
            <Input placeholder="例如：newuser" disabled={!!editingUser} />
          </Form.Item>
          <Form.Item label="邮箱" name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '邮箱格式不正确' }]}>
            <Input placeholder="name@example.com" />
          </Form.Item>
          <Form.Item label="角色" name="role"><Select options={roleOptions} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}