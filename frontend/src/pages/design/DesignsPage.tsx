/** 设计结构页（设计模块默认页，ADR 0083 D6）.
 *
 * 主体为装配大纲树：设计（根）→ 组件（module 实例，可嵌套）→ 结构分组 →
 * 零件（图元）。大纲由后端编译链路与 IR 同源产出（D2），前端零解析（ADR 0079 I1）；
 * 按设计展开懒加载单设计大纲端点（D4），节点带 1 基源行并可点击定位编辑器（D7）。
 * 既有能力（新建 / 打开 / 改名 / 描述 / 删除）全部保留在树节点与工具栏上。
 */

import { useMemo, useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, Modal, Popconfirm, Skeleton, Space, Tag, Tree, Typography,
} from 'antd'
import type { DataNode, TreeProps } from 'antd/es/tree'
import {
  ApartmentOutlined, AppstoreOutlined, ClusterOutlined, DeleteOutlined, EditOutlined,
  NodeIndexOutlined, PlusOutlined, ToolOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignListItem, DesignOutlineNode } from '@/api'
import { formatDateTime } from '@/utils/datetime'
import {
  countParts, designEditorPath, type DesignTreeEntry, type DesignTreeMeta, outlineToTree,
} from './designOutline'

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

/** 大纲节点图标：组件 / 分组 / 零件各一类（设计根用工具图标） */
const ENTRY_ICONS = {
  assembly: ClusterOutlined,
  group: NodeIndexOutlined,
  part: AppstoreOutlined,
} as const

/** Tree 节点（额外携带 meta，供点击跳转定位） */
interface DesignTreeDataNode extends DataNode {
  meta?: DesignTreeMeta
  children?: DesignTreeDataNode[]
}

/** 大纲条 → antd Tree 节点（标题 + 类型 / 行号 / 零件数描述） */
function entryToTreeNode(entry: DesignTreeEntry): DesignTreeDataNode {
  const Icon = ENTRY_ICONS[entry.meta.type as keyof typeof ENTRY_ICONS]
  return {
    key: entry.key,
    meta: entry.meta,
    isLeaf: entry.isLeaf,
    icon: <Icon />,
    title: (
      <span className="cn-design-outline-title" data-testid={`design-outline-node-${entry.key}`}>
        <span>{entry.title}</span>
        <Text type="secondary" className="cn-design-outline-detail">{entry.detail}</Text>
      </span>
    ),
    children: entry.children?.map(entryToTreeNode),
  }
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

  // 已加载大纲（按设计 id）：展开设计时懒加载（D4）；source=content 表示历史快照派生（D5）
  const [outlines, setOutlines] = useState<Record<number, { nodes: DesignOutlineNode[]; source: 'compiled' | 'content' }>>({})

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
      navigate(designEditorPath(wid, created.id))
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

  /** 设计节点标题：名称 + 版本 / 更新时间 + 历史快照标记 + 打开 / 编辑 / 删除入口 */
  const renderDesignTitle = (item: DesignListItem) => {
    const outline = outlines[item.id]
    return (
      <span className="cn-design-tree-title" data-testid={`design-node-${item.id}`}>
        <Text strong>{item.title}</Text>
        <Text type="secondary" className="cn-design-tree-meta">
          {item.description || '（无描述）'}
          {' · '}v{item.version_count}
          {' · '}更新于 {formatDateTime(item.updated_at)}
        </Text>
        {outline?.source === 'content' && (
          <Tag color="orange" bordered={false} className="cn-design-tree-tag">历史快照派生</Tag>
        )}
        {/* 树节点内联操作：阻止冒泡，避免同时触发行定位跳转 */}
        <span className="cn-design-tree-actions" onClick={(event) => event.stopPropagation()}>
          <Button size="small" type="link" onClick={() => navigate(designEditorPath(wid, item.id))}>
            打开
          </Button>
          {!isViewer && (
            <>
              <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openRename(item)}>
                编辑
              </Button>
              <Popconfirm
                title={`删除设计「${item.title}」？`}
                description="版本历史会一并隐藏，操作不可撤销。"
                okText="删除"
                okButtonProps={{ danger: true }}
                onConfirm={() => remove.mutate(item)}
              >
                <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
              </Popconfirm>
            </>
          )}
        </span>
      </span>
    )
  }

  const treeData = useMemo<DesignTreeDataNode[]>(
    () => designs.map((item) => {
      const outline = outlines[item.id]
      return {
        key: `design-${item.id}`,
        meta: { type: 'design', designId: item.id, partCount: outline ? outline.nodes.reduce((total, node) => total + countParts(node), 0) : 0 },
        isLeaf: outline ? outline.nodes.length === 0 : false,
        icon: <ToolOutlined />,
        title: renderDesignTitle(item),
        children: outline ? outlineToTree(outline.nodes, item.id).map(entryToTreeNode) : undefined,
      }
    }),
    // renderDesignTitle 依赖 isViewer / outlines / designs，均在本依赖内
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [designs, outlines, isViewer, wid],
  )

  /** 展开设计时懒加载该设计大纲（D4）；历史快照派生只读，保存一次后自然落库（D5） */
  const loadOutline = (node: DesignTreeDataNode): Promise<void> => {
    const designId = node.meta?.designId
    if (!designId || node.meta?.type !== 'design' || outlines[designId]) return Promise.resolve()
    return designsApi.outline(wid, designId)
      .then((result) => {
        setOutlines((prev) => ({ ...prev, [designId]: { nodes: result.outline.children, source: result.source } }))
      })
      .catch((err) => {
        message.error(err instanceof Error ? err.message : '装配大纲加载失败')
      })
  }

  /** 点击节点：设计 → 编辑器；组件 / 分组 / 零件 → 编辑器并定位源行（D7） */
  const onSelectNode: TreeProps['onSelect'] = (_keys, info) => {
    const meta = (info.node as DesignTreeDataNode).meta
    if (!meta || meta.type === 'design') {
      if (meta?.designId) navigate(designEditorPath(wid, meta.designId))
      return
    }
    navigate(designEditorPath(wid, meta.designId ?? 0, meta.line))
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
              按装配层级查看设计的组件与零件；展开设计加载大纲，点击节点定位到结构 DSL 源行。
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
        <div className="cn-design-structure" data-testid="design-structure-tree">
          <Tree
            blockNode
            showIcon
            treeData={treeData}
            // antd 懒加载契约：展开无 children 的节点时调用，子节点由 treeData 状态回填
            loadData={(node) => loadOutline(node as DesignTreeDataNode)}
            onSelect={onSelectNode}
          />
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

