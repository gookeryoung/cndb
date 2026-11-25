/** 团队页各分区内容（需求 0157 C3）—— 概览 / 工作区 / 成员 / 策略 / 搜索.
 *
 * 只负责展示与调用页面传入的回调；数据查询与变更集中在 `TeamPage`（单一数据源、单一失效入口）。
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Button, Card, Col, Empty, Form, Input, InputNumber, Popconfirm, Row, Select, Space,
  Statistic, Switch, Table, Tag, Typography, type FormInstance,
} from 'antd'
import {
  ArrowRightOutlined, DeleteOutlined, FileSearchOutlined, FileTextOutlined, PlusOutlined,
  TableOutlined, UserAddOutlined,
} from '@ant-design/icons'

import { teamApi } from '@/api'
import type { Team, TeamMember, TeamPolicy, TeamRole, TeamWorkspace, WorkspaceModule } from '@/api'
import HelpTip from '@/components/HelpTip'
import { TEAM_ROLE_COLOR, TEAM_ROLE_LABEL, teamRoleLabel } from '@/utils/roleLabels'
import type { TeamSectionKey } from './teamSectionMeta'

const { Text, Title } = Typography

const MODULE_LABEL: Record<string, string> = {
  tables: '数据表',
  documents: '文档',
  design: '设计',
}

export interface TeamPageSectionProps {
  team: Team
  isOwner: boolean
  canManageMembers: boolean
  onNavigateSection: (section: TeamSectionKey) => void
}

// ─────────────── 概览 ───────────────

export function TeamOverviewSection({
  team, isOwner, canManageMembers, onNavigateSection, members, membersLoading,
  workspaces, workspacesLoading, onCreateWorkspace,
}: TeamPageSectionProps & {
  members: TeamMember[]
  membersLoading: boolean
  workspaces: TeamWorkspace[]
  workspacesLoading: boolean
  onCreateWorkspace: () => void
}) {
  const recent = [...workspaces]
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
    .slice(0, 5)
  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="工作区" value={team.workspace_count} suffix="个" loading={workspacesLoading} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="团队成员" value={team.member_count} suffix="人" loading={membersLoading} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic
              title="你的团队角色"
              value={teamRoleLabel(team.current_user_role)}
              valueStyle={{ fontSize: 'var(--cn-text-lg)' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic
              title="默认工作区角色"
              value={team.policy.default_workspace_role === 'none' ? '不可见' : team.policy.default_workspace_role === 'viewer' ? '可查看' : '可编辑'}
              valueStyle={{ fontSize: 'var(--cn-text-lg)' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="最近更新的工作区"
        style={{ marginTop: 16 }}
        extra={(
          <Button type="link" size="small" onClick={() => onNavigateSection('workspaces')} data-testid="team-overview-more-workspaces">
            全部工作区 <ArrowRightOutlined />
          </Button>
        )}
      >
        {workspaces.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该团队还没有工作区">
            <Button type="primary" icon={<PlusOutlined />} onClick={onCreateWorkspace} data-testid="team-overview-create-workspace">
              新建工作区
            </Button>
          </Empty>
        ) : (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {recent.map(ws => (
              <div key={ws.id} className="cn-team-recent-row">
                <Link to={`/w/${ws.id}`} className="cn-team-recent-name">{ws.name}</Link>
                <Space size={4} wrap>
                  {ws.modules.map(m => <Tag key={m}>{MODULE_LABEL[m] ?? m}</Tag>)}
                </Space>
                <Text type="secondary" className="cn-team-recent-time">{ws.updated_at?.slice(0, 10)}</Text>
              </div>
            ))}
          </Space>
        )}
      </Card>

      <Card
        size="small"
        title={(
          <Space>
            管理面与数据面
            <HelpTip title="团队角色只决定管理面：所有者可改团队设置与策略，管理员可管成员；两者默认都读不到工作区数据（数据权限仍由工作区成员角色决定）。" />
          </Space>
        )}
        style={{ marginTop: 16 }}
      >
        <Space direction="vertical" size={6}>
          <Text type="secondary">团队管理员默认看不到工作区数据；数据读取仍由各工作区的成员角色决定。</Text>
          <Space wrap>
            <Button size="small" onClick={() => onNavigateSection('members')} disabled={!canManageMembers && !isOwner}>
              管理成员
            </Button>
            <Button size="small" onClick={() => onNavigateSection('policy')} disabled={!isOwner}>
              团队策略
            </Button>
            <Button size="small" onClick={() => onNavigateSection('search')}>团队内搜索</Button>
          </Space>
        </Space>
      </Card>

      <Card size="small" title="成员摘要" style={{ marginTop: 16 }}>
        {members.length === 0 ? (
          <Text type="secondary">还没有成员</Text>
        ) : (
          <Space size={4} wrap>
            {members.slice(0, 12).map(m => (
              <Tag key={m.id} color={TEAM_ROLE_COLOR[m.role]}>
                {m.user?.nickname || m.user?.username} · {TEAM_ROLE_LABEL[m.role]}
              </Tag>
            ))}
            {members.length > 12 && (
              <Button type="link" size="small" onClick={() => onNavigateSection('members')}>
                查看全部 {members.length} 人
              </Button>
            )}
          </Space>
        )}
      </Card>
    </div>
  )
}

// ─────────────── 工作区 ───────────────

export function TeamWorkspacesSection({
  team, workspaces, loading, onJoin, joining, onCreateWorkspace,
}: TeamPageSectionProps & {
  workspaces: TeamWorkspace[]
  loading: boolean
  onJoin: (wid: number | string) => void
  joining: boolean
  onCreateWorkspace: () => void
}) {
  return (
    <Card
      size="small"
      title="工作区（平铺列表）"
      extra={(
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreateWorkspace} data-testid="team-create-workspace">
          新建工作区
        </Button>
      )}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        团队内工作区以平铺列表呈现（无树）；数据权限仍由各工作区的成员角色决定。
      </Text>
      {workspaces.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该团队还没有工作区" />
      ) : (
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          dataSource={workspaces}
          pagination={false}
          columns={[
            {
              title: '工作区',
              dataIndex: 'name',
              render: (name: string, ws: TeamWorkspace) => <Link to={`/w/${ws.id}`}>{name}</Link>,
            },
            {
              title: '模块',
              dataIndex: 'modules',
              render: (modules: WorkspaceModule[]) => (
                <Space size={4} wrap>
                  {modules.map(m => <Tag key={m}>{MODULE_LABEL[m] ?? m}</Tag>)}
                </Space>
              ),
            },
            { title: '成员', dataIndex: 'member_count', width: 80 },
            {
              title: '操作',
              width: 120,
              render: (_: unknown, ws: TeamWorkspace) =>
                ws.is_member ? (
                  <Text type="secondary">已加入</Text>
                ) : team.policy.allow_member_invite ? (
                  <Button
                    size="small"
                    type="link"
                    loading={joining}
                    onClick={() => onJoin(ws.id)}
                    data-testid={`join-workspace-${ws.id}`}
                  >
                    加入
                  </Button>
                ) : (
                  <Text type="secondary">未加入</Text>
                ),
            },
          ]}
        />
      )}
    </Card>
  )
}

// ─────────────── 成员 ───────────────

export function TeamMembersSection({
  members, loading, isOwner, canManageMembers,
  addName, setAddName, addRole, setAddRole, onAdd, adding,
  onChangeRole, onRemove,
}: TeamPageSectionProps & {
  members: TeamMember[]
  loading: boolean
  addName: string
  setAddName: (value: string) => void
  addRole: 'admin' | 'member'
  setAddRole: (value: 'admin' | 'member') => void
  onAdd: () => void
  adding: boolean
  onChangeRole: (memberId: number | string, role: string) => void
  onRemove: (memberId: number | string) => void
}) {
  return (
    <Card size="small" title="团队成员">
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        团队角色只决定管理面；移除团队身份不影响其在各工作区里的成员角色。
      </Text>
      {canManageMembers && (
        <Space style={{ marginBottom: 12 }} wrap>
          <Input
            placeholder="按用户名添加成员"
            value={addName}
            onChange={e => setAddName(e.target.value)}
            style={{ width: 200 }}
            data-testid="team-add-member-input"
          />
          <Select
            value={addRole}
            onChange={setAddRole}
            style={{ width: 120 }}
            options={[
              { value: 'member', label: '团队成员' },
              { value: 'admin', label: '团队管理员' },
            ]}
          />
          <Button
            icon={<UserAddOutlined />}
            disabled={!addName.trim()}
            loading={adding}
            onClick={onAdd}
            data-testid="team-add-member-btn"
          >
            添加
          </Button>
        </Space>
      )}
      <Table<TeamMember>
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={members}
        pagination={false}
        columns={[
          {
            title: '成员',
            dataIndex: ['user', 'username'],
            render: (_: unknown, m) => m.user?.nickname || m.user?.username,
          },
          {
            title: '团队角色',
            dataIndex: 'role',
            width: 180,
            render: (role: TeamRole, m) =>
              isOwner ? (
                <Select
                  size="small"
                  value={role}
                  style={{ width: 140 }}
                  onChange={(next) => onChangeRole(m.id, next)}
                  options={[
                    { value: 'owner', label: '团队所有者' },
                    { value: 'admin', label: '团队管理员' },
                    { value: 'member', label: '团队成员' },
                  ]}
                />
              ) : (
                <Tag color={TEAM_ROLE_COLOR[role]}>{TEAM_ROLE_LABEL[role]}</Tag>
              ),
          },
          {
            title: '操作',
            width: 90,
            render: (_: unknown, m) =>
              canManageMembers ? (
                <Popconfirm
                  title="移出团队？"
                  description="只移除团队身份，不影响其在各工作区里的成员角色。"
                  onConfirm={() => onRemove(m.id)}
                  okText="移出"
                  cancelText="取消"
                >
                  <Button size="small" type="text" danger>移出</Button>
                </Popconfirm>
              ) : null,
          },
        ]}
      />
    </Card>
  )
}

// ─────────────── 策略 ───────────────

export function TeamPolicySection({
  team, form, isOwner, saving, onSave, onDelete, deleting,
}: TeamPageSectionProps & {
  form: FormInstance
  saving: boolean
  onSave: (policy: TeamPolicy) => void
  onDelete: () => void
  deleting: boolean
}) {
  return (
    <div>
      <Card
        size="small"
        title="团队策略"
        extra={!isOwner && <Text type="secondary">仅团队所有者可修改</Text>}
      >
        <Form
          form={form}
          layout="vertical"
          disabled={!isOwner}
          initialValues={{
            default_workspace_role: team.policy.default_workspace_role,
            allow_member_invite: team.policy.allow_member_invite,
            default_storage_quota_mb: team.policy.default_storage_quota_bytes
              ? Math.round(team.policy.default_storage_quota_bytes / (1024 * 1024))
              : null,
          }}
          onFinish={(values) => {
            onSave({
              default_workspace_role: values.default_workspace_role,
              allow_member_invite: values.allow_member_invite,
              allowed_modules: team.policy.allowed_modules,
              default_storage_quota_bytes: values.default_storage_quota_mb
                ? Number(values.default_storage_quota_mb) * 1024 * 1024
                : null,
            })
          }}
        >
          <Form.Item
            label="团队成员默认角色"
            name="default_workspace_role"
            extra="只对「未被加为该工作区成员」的团队成员生效；显式成员角色永远优先"
          >
            <Select
              options={[
                { value: 'none', label: '看不到（默认，推荐）' },
                { value: 'viewer', label: '可查看' },
                { value: 'editor', label: '可编辑' },
              ]}
            />
          </Form.Item>
          <Form.Item label="允许团队成员自助加入团队工作区" name="allow_member_invite" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="新工作区默认配额（MB）" name="default_storage_quota_mb" extra="留空表示沿用系统默认 100MB">
            <InputNumber min={1} style={{ width: 180 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} data-testid="save-team-policy">
            保存策略
          </Button>
        </Form>
      </Card>

      {isOwner && (
        <Card size="small" title="危险区" style={{ marginTop: 16, borderColor: 'var(--cn-border)' }}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Text type="secondary">删除团队后，其工作区会转为独立工作区，成员与数据都不会被删除。</Text>
            <Popconfirm
              title="删除团队？"
              description="工作区会转为独立工作区，成员与数据都不会被删除。"
              onConfirm={onDelete}
              okText="删除团队"
              cancelText="取消"
            >
              <Button danger icon={<DeleteOutlined />} loading={deleting} data-testid="delete-team-btn">
                删除团队
              </Button>
            </Popconfirm>
          </Space>
        </Card>
      )}
    </div>
  )
}

// ─────────────── 搜索 ───────────────

export function TeamSearchSection({ team }: TeamPageSectionProps) {
  const [searchText, setSearchText] = useState('')
  const [keyword, setKeyword] = useState('')
  const { data: result, isFetching } = useQuery({
    queryKey: ['team-search', team.id, keyword],
    queryFn: () => teamApi.search(team.id, keyword),
    enabled: !!keyword.trim(),
    staleTime: 15_000,
  })

  return (
    <Card size="small" title="团队内搜索">
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          placeholder="在团队内所有我能访问的工作区里搜索文档 / 数据表"
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          onPressEnter={() => setKeyword(searchText.trim())}
          data-testid="team-search-input"
        />
        <Button
          onClick={() => setKeyword(searchText.trim())}
          loading={isFetching}
          data-testid="team-search-btn"
        >
          搜索
        </Button>
      </Space.Compact>
      {keyword ? (
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {(result?.documents ?? []).map(doc => (
            <Link key={`doc-${doc.id}`} to={`/w/${doc.workspace_id}/documents/${doc.id}`}>
              <FileTextOutlined /> {doc.title}
              <Text type="secondary"> · {doc.workspace_name}</Text>
            </Link>
          ))}
          {(result?.tables ?? []).map(table => (
            <Link key={`table-${table.workspace_id}-${table.id}`} to={`/w/${table.workspace_id}/tables/${table.id}`}>
              <TableOutlined /> {table.name}
              <Text type="secondary"> · {table.workspace_name}</Text>
            </Link>
          ))}
          {(result?.rows ?? []).map(row => (
            <Link key={`row-${row.workspace_id}-${row.row_id}`} to={`/w/${row.workspace_id}/tables`}>
              <FileSearchOutlined /> {row.title}
              <Text type="secondary"> · {row.workspace_name} / {row.table_name}</Text>
            </Link>
          ))}
          {!isFetching
            && (result?.documents?.length ?? 0) + (result?.tables?.length ?? 0) + (result?.rows?.length ?? 0) === 0 && (
            <Text type="secondary">没有匹配结果（只检索你有权访问的工作区）</Text>
          )}
        </Space>
      ) : (
        <Text type="secondary">团队管理员默认看不到数据，搜索只覆盖你本人可读的工作区</Text>
      )}
    </Card>
  )
}

/** 团队页头部（标题 + 角色 + 指标 + 主操作）—— 由 TeamPage 组合，导出便于单测 */
export function TeamHeader({
  team, isOwner, onCreateWorkspace, onManagePolicy,
}: {
  team: Team
  isOwner: boolean
  onCreateWorkspace: () => void
  onManagePolicy: () => void
}) {
  return (
    <div className="cn-team-header" data-testid="team-header">
      <div className="cn-team-header-main">
        <Space size={8} wrap>
          <Title level={3} style={{ margin: 0 }}>{team.name}</Title>
          <Tag color={TEAM_ROLE_COLOR[team.current_user_role ?? 'member']}>
            {TEAM_ROLE_LABEL[team.current_user_role ?? 'member']}
          </Tag>
        </Space>
        <Text type="secondary">
          {team.workspace_count} 个工作区 · {team.member_count} 名成员 · 标识 {team.slug}
        </Text>
        {team.description && <Text type="secondary">{team.description}</Text>}
      </div>
      <Space wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreateWorkspace} data-testid="team-header-create-workspace">
          新建工作区
        </Button>
        <Button onClick={onManagePolicy} disabled={!isOwner} data-testid="team-header-policy">
          团队设置
        </Button>
      </Space>
    </div>
  )
}
