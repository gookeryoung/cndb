/** 工作区链接面板（ADR 0154 P2）—— 消费方链接列表 + 发起申请 + 源侧审批.
 *
 * 用法：挂在数据表列表页顶部（`TablesList`）。三块内容：
 * 1. 我的外部链接（消费方）：状态 / 到期 / 可读 / 打开只读网格 / 撤回；
 * 2. 发起链接申请：选源工作区 → 选表（只能选你本来就有权访问的）→ 别名 / 有效期 / 备注；
 * 3. 待我批准（源工作区所有者，`MANAGE_LINKS`）：批准（可改有效期）/ 拒绝。
 *
 * 只读边界：面板不提供任何写数据的入口；写操作只有「申请 / 批准 / 拒绝 / 撤回」四类链接管理动作。
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  App as AntApp, Button, Card, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Select, Space,
  Table, Tag, Tooltip, Typography,
} from 'antd'
import { ApartmentOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'

import { linksApi, tableApi, teamApi, workspaceApi } from '@/api'
import type { TableSummary, Team, Workspace, WorkspaceLink } from '@/api'
import { useCapabilities } from '@/hooks/useCapabilities'
import { formatDateTime } from '@/utils/datetime'

const { Text } = Typography

const STATUS_META: Record<string, { color: string; text: string }> = {
  pending: { color: 'gold', text: '待源工作区批准' },
  active: { color: 'green', text: '生效中' },
  rejected: { color: 'red', text: '已拒绝' },
  expired: { color: 'default', text: '已到期' },
}

/** 源工作区下拉只列「我有权访问的工作区」（链接读取本就需要源工作区 READ，L1） */
function useSourceWorkspaces(currentWid: string) {
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  return useMemo(
    () => workspaces.filter(ws => String(ws.id) !== String(currentWid)),
    [workspaces, currentWid],
  )
}

export default function WorkspaceLinksPanel({ wid }: { wid: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message } = AntApp.useApp()
  const { can } = useCapabilities(wid)
  const canManageLinks = can('MANAGE_LINKS')
  const canApply = can('EDIT_SETTINGS')

  const [applyOpen, setApplyOpen] = useState(false)
  const [form] = Form.useForm()
  const [sourceWid, setSourceWid] = useState<string | null>(null)
  /** 受众：members（批量只读成员）/ team（团队数据授权，B′） */
  const [audience, setAudience] = useState<'members' | 'team'>('members')
  const [approveTarget, setApproveTarget] = useState<WorkspaceLink | null>(null)
  const [approveTtl, setApproveTtl] = useState<number>(30)

  const sources = useSourceWorkspaces(wid)

  const { data: links = [], isLoading } = useQuery<WorkspaceLink[]>({
    queryKey: ['workspace-links', wid],
    queryFn: () => linksApi.list(wid),
    enabled: !!wid,
    retry: false,
  })

  const { data: inbox = [] } = useQuery<WorkspaceLink[]>({
    queryKey: ['workspace-links-inbox', wid],
    queryFn: () => linksApi.inbox(wid),
    enabled: !!wid && canManageLinks,
    retry: false,
  })

  // 我所在的团队（audience=team 时可选；后端要求「只能授给你所在团队」）
  const { data: myTeams = [] } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
    enabled: applyOpen,
    retry: false,
  })

  const { data: sourceTables = [], isFetching: tablesLoading } = useQuery<TableSummary[]>({
    queryKey: ['workspace-link-source-tables', sourceWid],
    queryFn: () => tableApi.list(sourceWid as string),
    enabled: !!sourceWid,
    retry: false,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['workspace-links', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspace-links-inbox', wid] })
  }

  const create = useMutation({
    mutationFn: (values: {
      source_workspace_id: string
      target_table_id: number
      alias?: string
      ttl_days?: number
      note?: string
      audience?: 'members' | 'team'
      team_id?: number
    }) => linksApi.create(wid, {
      ...values,
      team_id: values.audience === 'team' ? values.team_id : null,
    }),
    onSuccess: () => {
      message.success('已提交链接申请，等待源工作区批准')
      setApplyOpen(false)
      form.resetFields()
      setSourceWid(null)
      setAudience('members')
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '提交申请失败'),
  })

  const approve = useMutation({
    mutationFn: ({ link, ttl }: { link: WorkspaceLink; ttl?: number }) =>
      linksApi.approve(wid, link.id, ttl),
    onSuccess: () => {
      message.success('已批准链接')
      setApproveTarget(null)
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '批准失败'),
  })

  const reject = useMutation({
    mutationFn: (link: WorkspaceLink) => linksApi.reject(wid, link.id),
    onSuccess: () => {
      message.success('已拒绝链接')
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '拒绝失败'),
  })

  const revoke = useMutation({
    mutationFn: (link: WorkspaceLink) => linksApi.remove(wid, link.id),
    onSuccess: () => {
      message.success('已撤回链接；由它创建的只读成员会被回收')
      refresh()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '撤回失败'),
  })

  const nothingToShow = links.length === 0 && inbox.length === 0

  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={<Space><LinkOutlined /> 外部链接（只读）</Space>}
      extra={canApply && (
        <Button size="small" icon={<PlusOutlined />} onClick={() => setApplyOpen(true)} data-testid="link-apply-btn">
          申请链接
        </Button>
      )}
      data-testid="workspace-links-panel"
    >
      {nothingToShow && !isLoading ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无外部链接：可申请只读引用其他工作区的表，用于跨工作区汇总"
        />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {links.length > 0 && (
            <Table<WorkspaceLink>
              size="small"
              rowKey="id"
              loading={isLoading}
              dataSource={links}
              pagination={false}
              data-testid="workspace-links-table"
              columns={[
                { title: '别名', dataIndex: 'alias' },
                { title: '来源工作区', dataIndex: 'source_workspace_name' },
                { title: '表', dataIndex: 'target_table_name' },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (status: string, link) => (
                    <Space size={4} wrap>
                      <Tag color={STATUS_META[status]?.color ?? 'default'}>
                        {STATUS_META[status]?.text ?? status}
                      </Tag>
                      {status === 'active' && !link.readable && (
                        <Tooltip title="你在源工作区没有读取权限，请联系源工作区拥有者">
                          <Tag color="orange">不可读</Tag>
                        </Tooltip>
                      )}
                    </Space>
                  ),
                },
                {
                  title: '到期',
                  dataIndex: 'expires_at',
                  render: (value: string | null) => (value ? formatDateTime(value) : '—'),
                },
                {
                  title: '操作',
                  width: 140,
                  render: (_, link) => (
                    <Space size={4}>
                      <Button
                        size="small"
                        type="link"
                        disabled={link.status !== 'active' || !link.readable}
                        onClick={() => navigate(`/w/${wid}/links/${link.id}`)}
                        data-testid={`link-open-${link.id}`}
                      >
                        打开
                      </Button>
                      {canApply && (
                        <Popconfirm
                          title="撤回该链接？"
                          description="由它创建的只读成员会被回收，原有成员不受影响。"
                          onConfirm={() => revoke.mutate(link)}
                          okText="撤回"
                          cancelText="取消"
                        >
                          <Button size="small" type="link" danger data-testid={`link-revoke-${link.id}`}>
                            撤回
                          </Button>
                        </Popconfirm>
                      )}
                    </Space>
                  ),
                },
              ]}
            />
          )}

          {canManageLinks && inbox.length > 0 && (
            <div data-testid="workspace-links-inbox">
              <Text strong>
                <ApartmentOutlined /> 待我批准（{inbox.length}）
              </Text>
              <Table<WorkspaceLink>
                size="small"
                rowKey="id"
                dataSource={inbox}
                pagination={false}
                style={{ marginTop: 8 }}
                columns={[
                  { title: '别名', dataIndex: 'alias' },
                  { title: '来自工作区', dataIndex: 'source_workspace_name' },
                  { title: '表', dataIndex: 'target_table_name' },
                  {
                    title: '备注',
                    dataIndex: 'note',
                    render: (note: string) => note || <Text type="secondary">—</Text>,
                  },
                  {
                    title: '操作',
                    width: 150,
                    render: (_, link) => (
                      <Space size={4}>
                        <Button
                          size="small"
                          type="link"
                          onClick={() => {
                            setApproveTarget(link)
                            setApproveTtl(link.ttl_days || 30)
                          }}
                          data-testid={`link-approve-${link.id}`}
                        >
                          批准
                        </Button>
                        <Button
                          size="small"
                          type="link"
                          danger
                          onClick={() => reject.mutate(link)}
                          data-testid={`link-reject-${link.id}`}
                        >
                          拒绝
                        </Button>
                      </Space>
                    ),
                  },
                ]}
              />
            </div>
          )}
        </Space>
      )}

      {/* 发起申请 */}
      <Modal
        open={applyOpen}
        title="申请外部链接（只读）"
        onCancel={() => setApplyOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        okText="提交申请"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ ttl_days: 30, audience: 'members' }}
          onFinish={(values) => create.mutate(values)}
        >
          <Form.Item
            name="source_workspace_id"
            label="源工作区"
            rules={[{ required: true, message: '请选择源工作区' }]}
            extra="只列出你本人有权访问的工作区；链接数据仍需你在源工作区具备读取权限"
          >
            <Select
              placeholder="选择要引用的工作区"
              data-testid="link-apply-source"
              options={sources.map(ws => ({ value: String(ws.id), label: ws.name }))}
              onChange={(value: string) => {
                setSourceWid(value)
                form.setFieldValue('target_table_id', undefined)
              }}
            />
          </Form.Item>
          <Form.Item
            name="target_table_id"
            label="数据表"
            rules={[{ required: true, message: '请选择数据表' }]}
          >
            <Select
              placeholder={sourceWid ? '选择数据表' : '请先选择源工作区'}
              loading={tablesLoading}
              disabled={!sourceWid}
              data-testid="link-apply-table"
              options={sourceTables.map(t => ({ value: t.id, label: t.name }))}
            />
          </Form.Item>
          <Form.Item
            name="audience"
            label="授权给"
            initialValue="members"
            extra="批量成员：把当前工作区成员逐个加为源工作区只读；团队授权：只写一条「团队 = 只读」，不新增成员"
          >
            <Radio.Group
              data-testid="link-apply-audience"
              onChange={(e) => setAudience(e.target.value as 'members' | 'team')}
            >
              <Radio value="members">批量只读成员（逐个加入）</Radio>
              <Radio value="team">团队只读授权（一条授权行）</Radio>
            </Radio.Group>
          </Form.Item>
          {audience === 'team' && (
            <Form.Item
              name="team_id"
              label="被授团队"
              rules={[{ required: true, message: '请选择被授团队' }]}
              extra="只能授给你所在的团队；批准后该团队成员可只读源工作区（不含管理权）"
            >
              <Select
                placeholder="选择团队"
                data-testid="link-apply-team"
                options={myTeams.map(team => ({ value: team.id, label: team.name }))}
              />
            </Form.Item>
          )}
          <Form.Item name="alias" label="显示别名（可选，默认用表名）">
            <Input maxLength={64} placeholder="例如：各部门销售汇总" />
          </Form.Item>
          <Form.Item
            name="ttl_days"
            label="有效期（天）"
            extra="批准时源工作区所有者可调整；到期后链接立即失效"
          >
            <InputNumber min={1} max={365} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="note" label="申请说明（可选）">
            <Input.TextArea rows={2} maxLength={200} placeholder="说明用途，便于对方判断" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批准（可改有效期） */}
      <Modal
        open={!!approveTarget}
        title={`批准链接「${approveTarget?.alias ?? ''}」`}
        onCancel={() => setApproveTarget(null)}
        onOk={() => approveTarget && approve.mutate({ link: approveTarget, ttl: approveTtl })}
        confirmLoading={approve.isPending}
        okText="批准"
        destroyOnHidden
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Text type="secondary">
            批准后会把当前消费方工作区的成员批量加为**本工作区只读成员**，到期或撤回时自动回收（原有成员不受影响）。
          </Text>
          <Space>
            <Text>有效期（天）</Text>
            <InputNumber
              min={1}
              max={365}
              value={approveTtl}
              onChange={(value) => setApproveTtl(Number(value) || 30)}
              data-testid="link-approve-ttl"
            />
          </Space>
        </Space>
      </Modal>
    </Card>
  )
}
