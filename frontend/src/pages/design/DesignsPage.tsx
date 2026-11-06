/** 「设计结构」页 —— 设计模块默认根页（ADR 0109 D1 / D2 / D3）
 *
 * 形态对齐质量检查 / 修改申请：`cn-page` 紧凑页头 + `cn-qc-split` 左右分栏。
 * 左栏 = 产品（设计文件）清单：扁平可选列表，行内 Tag 承载类型 / 目录 / 依赖陈旧 / 版本，
 * 行尾保留打开 / 编辑 / 删除（viewer 只读时收紧）；
 * 右栏 = 选中产品的装配结构树：按需加载 outline（IR 快照缓存优先），
 * 节点点击打开编辑器并带 `?line=` 定位源行（ADR 0083 D4 / D7）。
 * 模块侧栏的装配树收窄到编辑器页（ADR 0109 D4），根页不再渲染侧栏。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  App as AntApp, Button, Empty, Form, Input, Modal, Popconfirm, Segmented, Select, Space, Spin, Tag,
  Tree, Typography,
} from 'antd'
import type { TreeProps } from 'antd/es/tree'
import {
  ApartmentOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, ToolOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignIRResponse, DesignListItem, DesignOutlineNode } from '@/api'
import CnListMeta from '@/components/CnListMeta'
import SectionBox from '@/components/SectionBox'
import { formatDateTime } from '@/utils/datetime'
import { designEditorPath, outlineToTree } from './designOutline'
import { entryToTreeNode, type DesignTreeDataNode } from './designTree'
import { prefetchDesignEditorChunks } from './prefetchEditor'

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

/** 新建零件文件的起步模板：顶层 param 即公开参数，顶层实例即零件几何（ADR 0086 C1） */
export const DEFAULT_PART_CONTENT = `// 零件文件：顶层 param = 公开参数，顶层实例 = 零件几何
param width = 80
param depth = 40
param height = 12

// 顶层实例：零件几何（禁止 system 声明）
difference {
  box(size = [width, depth, height])
  translate([0, 0, -1]) cyl(d = 8, h = height + 2)
}
`

/** 新建装配文件的起步模板：use 引用 part 文件 + 组件级约束（ADR 0086 C5）
 *  注意：模板中的 "plate" 需替换为实际零件 file_key 才能编译通过 */
export const DEFAULT_ASSEMBLY_CONTENT = DEFAULT_DESIGN_CONTENT

interface DesignFormValues {
  title: string
  description?: string
  kind: 'part' | 'assembly'
  folder?: string
  file_key?: string
}

interface OutlineState {
  nodes: DesignOutlineNode[]
  source: 'compiled' | 'content'
}

/** 右栏：选中产品的装配结构树（ADR 0109 C4 / D5 / D6）
 *
 * 数据流唯一入口为 `GET /designs/{id}/outline`：IR 快照缓存优先（缓存键与编辑器 / 侧栏一致，
 * 三处共享同一份数据），无缓存再按需请求；节点点击与侧栏同口径 —— `use` 实例打开源文件，
 * 其余大纲节点打开当前设计并带 `?line=` 定位源行。 */
function DesignOutlineTree({ workspaceId, design }: { workspaceId: string; design: DesignListItem }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [outline, setOutline] = useState<OutlineState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 重试计数：失败后点「重试」重跑加载副作用
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    // IR 快照缓存优先（键与编辑器 useQuery 一致，designId 为字符串）
    const cached = queryClient
      .getQueryData<DesignIRResponse>(['designs', workspaceId, String(design.id), 'ir'])
      ?.ir?.outline?.children
    if (cached) {
      setOutline({ nodes: cached, source: 'compiled' })
      setLoading(false)
      setError(null)
      return () => { cancelled = true }
    }
    setLoading(true)
    setError(null)
    designsApi
      .outline(workspaceId, design.id)
      .then((result) => {
        if (cancelled) return
        setOutline({ nodes: result.outline.children, source: result.source })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setOutline(null)
        setError(err instanceof Error ? err.message : '结构加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workspaceId, design.id, queryClient, reloadKey])

  const treeData = useMemo(
    () => (outline ? outlineToTree(outline.nodes, design.id).map(entryToTreeNode) : []),
    [outline, design.id],
  )

  const onSelectNode: TreeProps['onSelect'] = (_keys, info) => {
    const meta = (info.node as DesignTreeDataNode).meta
    if (!meta) return
    if (meta.fileId) navigate(designEditorPath(workspaceId, meta.fileId))
    else navigate(designEditorPath(workspaceId, meta.designId ?? design.id, meta.line))
  }

  return (
    <SectionBox
      title={`结构树：${design.title}`}
      icon={<ApartmentOutlined />}
      extra={outline?.source === 'content'
        ? <Tag color="orange" bordered={false}>历史快照派生</Tag>
        : undefined}
      flush
      testId="design-outline-box"
    >
      {loading ? (
        <div className="cn-qc-empty" data-testid="design-outline-loading"><Spin /></div>
      ) : error ? (
        <div className="cn-qc-empty" data-testid="design-outline-error">
          <Space direction="vertical" size={8}>
            <Text type="danger">结构加载失败：{error}</Text>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => setReloadKey(key => key + 1)}>
              重试
            </Button>
          </Space>
        </div>
      ) : treeData.length === 0 ? (
        <div className="cn-qc-empty">
          <Empty description="该设计还没有结构节点，点「打开」进入编辑器补充" />
        </div>
      ) : (
        <div className="cn-ds-outline-tree" data-testid="design-outline-tree">
          <Tree
            // 重试后按新数据重建（defaultExpandAll 只在初始化生效）
            key={reloadKey}
            blockNode
            showIcon
            defaultExpandAll
            className="cn-doc-sider-tree"
            treeData={treeData as DesignTreeDataNode[]}
            onSelect={onSelectNode}
          />
        </div>
      )}
    </SectionBox>
  )
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

  // 类型筛选（ADR 0103 C8 / D12）：全部 / 零件 / 装配（kind 为 0086 既有字段，零后端）
  const [kindFilter, setKindFilter] = useState<'all' | 'part' | 'assembly'>('all')
  /** 左栏选中态（ADR 0109 D2 / D3）：
   *  undefined = 跟随默认（最近更新的设计）、null = 用户主动取消、number = 显式选中 */
  const [pickedId, setPickedId] = useState<number | null | undefined>(undefined)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm<DesignFormValues>()
  const [renaming, setRenaming] = useState<DesignListItem | null>(null)
  const [renameForm] = Form.useForm<DesignFormValues>()

  // 打开性能（ADR 0086 C9）：列表页空闲时预取编辑器 route chunk 与 3D 预览 chunk，
  // 首次点击「打开」不再为下载解析付费（requestIdleCallback Chrome 47+，兜底 setTimeout）
  useEffect(() => {
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(() => prefetchDesignEditorChunks(), { timeout: 2000 })
      return () => window.cancelIdleCallback(id)
    }
    const timer = window.setTimeout(() => prefetchDesignEditorChunks(), 300)
    return () => window.clearTimeout(timer)
  }, [])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['designs', wid] })

  const create = useMutation({
    mutationFn: (values: DesignFormValues) =>
      designsApi.create(wid, {
        title: values.title,
        description: values.description ?? '',
        content: values.kind === 'part' ? DEFAULT_PART_CONTENT : DEFAULT_ASSEMBLY_CONTENT,
        kind: values.kind,
        folder: values.folder ?? '',
        file_key: values.file_key || undefined,
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

  /** 左栏可见清单（类型筛选后），目录信息降级为行内 Tag（ADR 0109 D2） */
  const visibleDesigns = useMemo(
    () => designs.filter(item => kindFilter === 'all' || item.kind === kindFilter),
    [designs, kindFilter],
  )

  // 默认选中：最近更新的设计（ADR 0109 D3，对齐需求 0107「默认选中」口径）
  const latestId = useMemo(() => {
    let best: DesignListItem | undefined
    for (const item of visibleDesigns) {
      if (!best || String(item.updated_at) > String(best.updated_at)) best = item
    }
    return best?.id ?? null
  }, [visibleDesigns])

  /** 实际激活项：显式选中失效（被删 / 被筛掉）回落到列表首个；主动取消则为空 */
  const activeId = useMemo(() => {
    if (pickedId === null) return null
    if (pickedId !== undefined) {
      return visibleDesigns.some(item => item.id === pickedId)
        ? pickedId
        : (visibleDesigns[0]?.id ?? null)
    }
    return latestId
  }, [pickedId, visibleDesigns, latestId])
  const activeDesign = visibleDesigns.find(item => item.id === activeId) ?? null

  /** 单击选中 / 再点取消（ADR 0109 C3） */
  const togglePick = (item: DesignListItem) => {
    setPickedId(prev => (prev === item.id ? null : item.id))
  }

  const renderRow = (item: DesignListItem) => {
    const active = item.id === activeId
    return (
      <div
        key={item.id}
        role="option"
        aria-selected={active}
        data-testid={`design-row-${item.id}`}
        className={[
          'cn-list-item',
          'cn-qc-row',
          'cn-qc-row--selectable',
          active ? 'cn-qc-row--active' : '',
        ].filter(Boolean).join(' ')}
        onClick={() => togglePick(item)}
      >
        <div className="cn-list-item-main">
          <CnListMeta
            avatar={<ToolOutlined style={{ color: 'var(--cn-text-muted)' }} />}
            title={(
              <Space size={6} wrap>
                <Text strong>{item.title}</Text>
                <Tag bordered={false} color={item.kind === 'part' ? 'blue' : 'geekblue'}>
                  {item.kind === 'part' ? '零件' : '装配'}
                </Tag>
                {item.folder && <Tag bordered={false}>{item.folder}</Tag>}
                {item.dependencies_stale && (
                  <Tag color="gold" bordered={false} data-testid={`design-list-stale-${item.id}`}>依赖陈旧</Tag>
                )}
              </Space>
            )}
            description={(
              <span className="cn-design-tree-meta">
                {item.file_key && <Text code style={{ fontSize: 12 }}>{item.file_key}</Text>}
                {' '}
                {item.description || '（无描述）'}
                {' · '}v{item.version_count}
                {' · '}更新于 {formatDateTime(item.updated_at)}
              </span>
            )}
          />
        </div>
        <div className="cn-list-item-actions" onClick={event => event.stopPropagation()}>
          <Button size="small" type="link" onClick={() => navigate(designEditorPath(wid, item.id))}>
            打开
          </Button>
          {!isViewer && (
            <>
              <Button
                size="small"
                type="link"
                icon={<EditOutlined />}
                onClick={() => openRename(item)}
              >
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
        </div>
      </div>
    )
  }

  return (
    <div className="cn-page cn-qc-page" data-testid="designs-page">
      {/* ── 页头：标题 + 口径说明 + 类型筛选 / 新建入口（与质量检查页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><ApartmentOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">设计结构</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">左侧产品列表、右侧选中产品的结构树</span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Segmented
            size="small"
            value={kindFilter}
            onChange={value => setKindFilter(value as 'all' | 'part' | 'assembly')}
            data-testid="design-kind-filter"
            options={[
              { value: 'all', label: '全部' },
              { value: 'part', label: '零件' },
              { value: 'assembly', label: '装配' },
            ]}
          />
          {!isViewer && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建设计</Button>
          )}
        </div>
      </header>

      {/* GitHub 风格双栏：左=产品清单，右=选中产品的装配结构树；窄屏由 cn-qc-split 收为纵向堆叠 */}
      <div className="cn-qc-split" data-testid="designs-split">
        <SectionBox
          title="产品列表"
          icon={<UnorderedListOutlined />}
          extra={<span>共 {visibleDesigns.length} 个</span>}
          flush
          testId="design-products-box"
        >
          <Spin spinning={isLoading}>
            {designs.length === 0 && !isLoading ? (
              <div className="cn-qc-empty">
                <Empty description="还没有结构设计" />
              </div>
            ) : visibleDesigns.length === 0 ? (
              <div className="cn-qc-empty">
                <Empty description="该类型下暂无设计" />
              </div>
            ) : (
              <div role="listbox" aria-label="产品列表" data-testid="design-list">
                {visibleDesigns.map(renderRow)}
              </div>
            )}
          </Spin>
        </SectionBox>

        {activeDesign ? (
          <DesignOutlineTree key={activeDesign.id} workspaceId={wid} design={activeDesign} />
        ) : (
          <SectionBox title="结构树" icon={<ApartmentOutlined />} flush testId="design-outline-box">
            <div className="cn-qc-empty">
              <Empty description={designs.length === 0 ? '还没有结构设计' : '选择左侧产品查看结构树'} />
            </div>
          </SectionBox>
        )}
      </div>

      <Modal
        title="新建设计"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        okText="创建"
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{ kind: 'assembly' }}
          onFinish={values => create.mutate(values)}
        >
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
          <Form.Item name="kind" label="文件类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'assembly', label: '装配（系统 / 组件装配声明）' },
                { value: 'part', label: '零件（顶层参数 + 零件几何）' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="folder"
            label="目录（可选）"
            rules={[{ pattern: /^(?!\/)[^\\]*$/, message: '目录为相对路径（a/b），不允许反斜杠' }]}
          >
            <Input placeholder="如：parts/rover" />
          </Form.Item>
          <Form.Item
            name="file_key"
            label="文件标识（可选，创建后不可改）"
            rules={[{ pattern: /^[A-Za-z0-9_\-\u4e00-\u9fff]{1,64}$/, message: '1-64 位字母 / 数字 / 下划线 / 连字符 / 中文' }]}
          >
            <Input placeholder="缺省由名称生成" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} maxLength={500} placeholder="用途说明" />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.kind !== next.kind}>
            {({ getFieldValue }) => (
              <Text type="secondary">
                {getFieldValue('kind') === 'part'
                  ? '将以零件模板（顶层参数 + 零件几何）创建，创建后可自由编辑。'
                  : '将以示例模板（四轮小车：系统 / 组件 / 零件三级装配）创建，创建后可自由编辑。'}
              </Text>
            )}
          </Form.Item>
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
