/** 项目清单（ADR 0122）：一个工作区多个项目的阶段 / 门禁 / 文档摘要，点击进入项目上下文. */

import { App as AntApp, Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'
import { PlusOutlined, ProjectOutlined, SyncOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { workspaceProjectsApi, type ProjectListItem } from '@/api/workspaceProjects'

const { Text, Paragraph } = Typography

export default function ProjectsPage() {
  const { wid } = useParams<{ wid: string }>()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['workspace-projects', wid],
    queryFn: () => workspaceProjectsApi.list(wid!),
    enabled: !!wid,
    retry: false,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['workspace-projects', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspace-data-flow', wid] })
    queryClient.invalidateQueries({ queryKey: ['workspace-lifecycle', wid] })
  }

  const enable = useMutation({
    mutationFn: () => workspaceProjectsApi.enableProjectMode(wid!, true),
    onSuccess: (res) => {
      message.success(`项目级管理已启用：${res.projects} 个项目，补建 ${res.documents_created} 份文档`)
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '启用失败'),
  })

  const ensureDocs = useMutation({
    mutationFn: (projectRowId: number) => workspaceProjectsApi.ensureDocuments(wid!, projectRowId),
    onSuccess: (res) => {
      message.success(res.created ? `已补建 ${res.created} 份文档` : '项目文档已齐全')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '补建文档失败'),
  })

  const ensureAllDocs = useMutation({
    mutationFn: async () => {
      const pending = (data?.items ?? []).filter(item => item.missing_documents.length > 0)
      let created = 0
      for (const row of pending) {
        const res = await workspaceProjectsApi.ensureDocuments(wid!, row.project_row_id)
        created += res.created
      }
      return { projects: pending.length, created }
    },
    onSuccess: ({ projects, created }) => {
      message.success(projects ? `已为 ${projects} 个项目补建 ${created} 份文档` : '所有项目文档已齐全')
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '批量补建文档失败'),
  })

  const openProject = (row: ProjectListItem) => {
    navigate(`/w/${wid}/tables?project=${row.project_row_id}`)
  }

  if (isLoading) return <div className="cn-state">加载中…</div>

  if (error || !data) {
    return (
      <div style={{ padding: 16 }}>
        <Empty description="项目清单加载失败">
          <Text type="secondary">{error instanceof Error ? error.message : '请稍后重试'}</Text>
        </Empty>
      </div>
    )
  }

  if (data.project_mode !== 'project') {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <Empty
            image={<ProjectOutlined style={{ fontSize: 44, color: 'var(--cn-text-tertiary)' }} />}
            description="当前工作区按工作区级管理"
          >
            <Paragraph type="secondary">
              启用项目级管理后，同一工作区可承载多个项目：每个项目独立阶段、门禁与文档；
              单项目工作区会自动进入项目上下文，体验不变。
            </Paragraph>
            <Button type="primary" icon={<SyncOutlined />} loading={enable.isPending} onClick={() => enable.mutate()}>
              启用项目级管理
            </Button>
          </Empty>
        </Card>
      </div>
    )
  }

  const columns = [
    {
      title: '项目名称',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, row: ProjectListItem) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => openProject(row)}>{title}</Button>
      ),
    },
    {
      title: '当前阶段',
      dataIndex: 'stage_name',
      key: 'stage_name',
      render: (stage: string | null) => stage ?? '—',
    },
    {
      title: '阶段门禁',
      dataIndex: 'gate_satisfied',
      key: 'gate_satisfied',
      render: (ok: boolean) => <Tag color={ok ? 'green' : 'orange'}>{ok ? '已满足' : '待补齐'}</Tag>,
    },
    {
      title: '缺失项',
      key: 'missing',
      render: (_: unknown, row: ProjectListItem) => {
        const items = [...row.missing_forms, ...row.missing_documents]
        if (!items.length) return <Text type="secondary">—</Text>
        return <Space size={4} wrap>{items.map(item => <Tag key={item}>{item}</Tag>)}</Space>
      },
    },
    {
      title: '初始化',
      dataIndex: 'initialized',
      key: 'initialized',
      render: (ok: boolean) => (ok ? <Tag color="blue">已初始化</Tag> : <Tag>未初始化</Tag>),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, row: ProjectListItem) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => openProject(row)}>进入</Button>
          <Button
            size="small"
            type="link"
            icon={<PlusOutlined />}
            loading={ensureDocs.isPending}
            onClick={() => ensureDocs.mutate(row.project_row_id)}
          >
            补文档
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={`项目清单（${data.total}）`}
        extra={(
          <Space size={8}>
            <Text type="secondary">根表单：{data.root_form}</Text>
            <Button
              size="small"
              icon={<PlusOutlined />}
              loading={ensureAllDocs.isPending}
              onClick={() => ensureAllDocs.mutate()}
            >
              全部补文档
            </Button>
          </Space>
        )}
      >
        {data.items.length ? (
          <Table
            rowKey="project_row_id"
            dataSource={data.items}
            columns={columns}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
          />
        ) : (
          <Empty description="还没有项目">
            <Paragraph type="secondary">在根表单「{data.root_form}」中新建一条记录，即创建一个项目。</Paragraph>
            <Button type="primary" onClick={() => navigate(`/w/${wid}/tables`)}>去数据表创建项目</Button>
          </Empty>
        )}
      </Card>
    </div>
  )
}
