/** 团队只读授权卡片（ADR 0154 P3.1 / B′）—— 工作区设置「权限管理」分区的最后一块.
 *
 * 口径（与后端一致）：
 * - 仅源工作区所有者（`MANAGE_ACCESS`）可见 / 可操作；
 * - 授权只产 `data_role=viewer`：被授团队的成员可**只读**该工作区，**不获得管理面**，
 *   行级规则与字段隐藏照旧（H57）；到期惰性失效，可随时撤销；
 * - 与「成员」独立：这条授权不会在工作区成员列表里新增任何人。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App as AntApp, Button, Card, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Space,
  Table, Tag, Typography,
} from 'antd'
import { ApartmentOutlined, PlusOutlined } from '@ant-design/icons'

import { linksApi, teamApi } from '@/api'
import type { Team, TeamAccess } from '@/api'
import { formatDateTime } from '@/utils/datetime'

const { Text } = Typography

export default function TeamAccessCard({
  wid,
  canManage,
}: {
  wid: string
  /** `MANAGE_ACCESS`（仅工作区所有者） */
  canManage: boolean
}) {
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const { data: grants = [], isLoading } = useQuery<TeamAccess[]>({
    queryKey: ['workspace-team-access', wid],
    queryFn: () => linksApi.listTeamAccess(wid),
    enabled: !!wid && canManage,
    retry: false,
  })

  const { data: teams = [] } = useQuery<Team[], Error>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
    enabled: !!wid && canManage,
    retry: false,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['workspace-team-access', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspace-capabilities', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const create = useMutation({
    mutationFn: (values: { team_id: number; ttl_days?: number; note?: string }) =>
      linksApi.createTeamAccess(wid, values),
    onSuccess: () => {
      message.success('已授予以团队只读（到期自动失效，可随时撤销）')
      setOpen(false)
      form.resetFields()
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '授权失败'),
  })

  const revoke = useMutation({
    mutationFn: (row: TeamAccess) => linksApi.removeTeamAccess(wid, row.id),
    onSuccess: () => {
      message.success('已撤销团队授权')
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '撤销失败'),
  })

  if (!canManage) return null

  return (
    <Card
      size="small"
      title={<Space><ApartmentOutlined /> 团队只读授权</Space>}
      style={{ marginTop: 12 }}
      extra={(
        <Button size="small" icon={<PlusOutlined />} onClick={() => setOpen(true)} data-testid="team-access-add-btn">
          授予团队
        </Button>
      )}
      data-testid="team-access-card"
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        被授团队的成员可以**只读**本工作区的数据（含行级规则与字段隐藏约束），不获得管理权；到期自动失效。
        这只是「授权」，不会把团队成员加进上方成员列表。
      </Text>

      {grants.length === 0 && !isLoading ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有团队授权" />
      ) : (
        <Table<TeamAccess>
          size="small"
          rowKey="id"
          loading={isLoading}
          dataSource={grants}
          pagination={false}
          data-testid="team-access-table"
          columns={[
            { title: '团队', dataIndex: 'team_name' },
            {
              title: '角色',
              dataIndex: 'role',
              width: 100,
              render: () => <Tag color="blue">只读</Tag>,
            },
            {
              title: '到期',
              dataIndex: 'expires_at',
              render: (value: string | null, row) => (
                <Space size={4}>
                  <span>{value ? formatDateTime(value) : '长期'}</span>
                  {!row.active && <Tag color="default">已失效</Tag>}
                </Space>
              ),
            },
            {
              title: '备注',
              dataIndex: 'note',
              render: (note: string) => note || <Text type="secondary">—</Text>,
            },
            {
              title: '操作',
              width: 90,
              render: (_, row) => (
                <Popconfirm
                  title="撤销该团队授权？"
                  description="撤销后该团队成员将不再能读取本工作区数据。"
                  onConfirm={() => revoke.mutate(row)}
                  okText="撤销"
                  cancelText="取消"
                >
                  <Button size="small" type="link" danger data-testid={`team-access-revoke-${row.id}`}>
                    撤销
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      )}

      <Modal
        open={open}
        title="授予以团队只读"
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="授予"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ ttl_days: 30 }} onFinish={(values) => create.mutate(values)}>
          <Form.Item
            name="team_id"
            label="团队"
            rules={[{ required: true, message: '请选择团队' }]}
            extra="被授团队的成员获得本工作区的只读权限（不含管理权）"
          >
            <Select
              placeholder="选择团队"
              data-testid="team-access-team-select"
              options={teams.map(team => ({ value: team.id, label: team.name }))}
            />
          </Form.Item>
          <Form.Item name="ttl_days" label="有效期（天）" extra="到期自动失效，可随时撤销">
            <InputNumber min={1} max={365} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="note" label="备注（可选）">
            <Input.TextArea rows={2} maxLength={200} placeholder="例如：季度数据汇总" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
