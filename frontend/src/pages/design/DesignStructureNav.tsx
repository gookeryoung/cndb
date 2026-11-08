/** 设计侧栏导航（ADR 0109 D2 / D4 / D5 / D8）
 *
 * 单一侧栏承载两态，桌面 Sider 与移动抽屉共用：
 * - `list`：产品（设计文件）列表，顶部搜索 / 类型筛选 / 新建，行尾「更多」菜单（打开 / 编辑 / 删除）；
 * - `tree`：当前产品的装配结构树（产品根 → 系统 → 组件 → 分组 → 零件），
 *   头部「产品列表」返回键只切侧栏状态，不改 URL 与 Content。
 * 两态互斥：同一时刻只渲染一个面板；URL 变化（选产品 / 进入编辑器）自动回到树态。
 * 大纲按需加载既有 outline 端点（ADR 0083 D4），IR 快照缓存优先（ADR 0086 D10），
 * 节点点击带 `?line=` 定位（ADR 0083 D7）。侧栏只读：改名 / 删除走弹窗（D6）。
 */

import { useEffect, useMemo, useRef, useState, type ComponentRef } from 'react'
import {
  App as AntApp, Button, Checkbox, Dropdown, Empty, Form, Input, Modal, Segmented, Select, Space, Spin, Tag, Tree,
  Typography,
} from 'antd'
import type { TreeProps } from 'antd/es/tree'
import {
  ArrowLeftOutlined, BookOutlined, DeleteOutlined, EditOutlined, MoreOutlined, PlusOutlined, ReloadOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { designLibraryApi, designsApi, workspaceApi } from '@/api'
import type {
  DesignIRResponse, DesignListItem, DesignOutlineNode, LibraryModuleItem,
} from '@/api'
import SearchInput from '@/components/SearchInput'
import { formatDateTime } from '@/utils/datetime'
import { usePersistedState } from '@/utils/persistedState'
import {
  designEditorPath, latestDesignId, outlineKeyPath, outlineToTree, resolveOutlinePath,
} from './designOutline'
import { entryToTreeNode, type DesignTreeDataNode } from './designTree'
import {
  DEFAULT_ASSEMBLY_CONTENT, DEFAULT_PART_CONTENT,
} from './designDefaults'

const { Text } = Typography

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

interface DesignStructureNavProps {
  workspaceId: string
  /** 移动端抽屉：点击条目后收起 */
  mobile?: boolean
  /** 桌面端 Sider 折叠态：只保留标题 */
  collapsed?: boolean
  onNavigate?: () => void
}

/** 从 pathname 取当前编辑器中的设计 id（根页 / 静态段不匹配则为 undefined） */
function activeDesignIdFrom(pathname: string, workspaceId: string): number | undefined {
  const match = new RegExp(`^/w/${workspaceId}/design/(\\d+)$`).exec(pathname)
  return match ? Number(match[1]) : undefined
}

/** 模块库只读页 id（/w/:wid/design/library/:moduleId） */
function activeLibraryIdFrom(pathname: string, workspaceId: string): number | undefined {
  const match = new RegExp(`^/w/${workspaceId}/design/library/(\\d+)$`).exec(pathname)
  return match ? Number(match[1]) : undefined
}

type NavView = 'list' | 'tree' | 'library'

export default function DesignStructureNav({
  workspaceId, mobile = false, collapsed = false, onNavigate,
}: DesignStructureNavProps) {
  const navigate = useNavigate()
  const pathname = useLocation().pathname
  const queryClient = useQueryClient()
  const { message, modal } = AntApp.useApp()

  const activeDesignId = activeDesignIdFrom(pathname, workspaceId)
  const activeLibraryId = activeLibraryIdFrom(pathname, workspaceId)
  // 侧栏三态：路由带 designId = 树态；模块库页 = 库态；根页 = 列表态。「返回产品列表」只改本地状态（D4）
  const [view, setView] = useState<NavView>(() => {
    if (activeDesignId !== undefined) return 'tree'
    return activeLibraryId !== undefined ? 'library' : 'list'
  })

  /** 侧栏筛选：产品搜索 / 类型 + 模块库可见范围等，按工作区会话级记忆，刷新不丢 */
  const [filters, setFilters] = usePersistedState<{
    keyword: string
    kindFilter: 'all' | 'part' | 'assembly'
    libraryScope: 'all' | 'public' | 'workspace'
    libraryOwnedOnly: boolean
    libraryIncludeArchived: boolean
    libraryKeyword: string
  }>(
    `cndb_design_nav_filters_v1:${workspaceId}`,
    {
      keyword: '',
      kindFilter: 'all',
      libraryScope: 'all',
      libraryOwnedOnly: false,
      libraryIncludeArchived: false,
      libraryKeyword: '',
    },
    'session',
  )
  const { keyword, kindFilter, libraryScope, libraryOwnedOnly, libraryIncludeArchived, libraryKeyword } = filters
  const patchFilters = (patch: Partial<typeof filters>) =>
    setFilters(prev => ({ ...prev, ...patch }))
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm<DesignFormValues>()
  const [renaming, setRenaming] = useState<DesignListItem | null>(null)
  const [renameForm] = Form.useForm<DesignFormValues>()

  const { data: designs = [], isLoading } = useQuery({
    queryKey: ['designs', workspaceId],
    queryFn: () => designsApi.list(workspaceId),
    enabled: !!workspaceId,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId),
    enabled: !!workspaceId,
  })
  const isViewer = wsDetail?.current_user_role === 'viewer'
  const isOwner = wsDetail?.current_user_role === 'owner'

  // 模块库浏览（ADR 0118 P1）：公开 + 当前工作区发布；含归档仅 owner
  const { data: libraryModules = [], isLoading: libraryLoading } = useQuery({
    queryKey: [
      'design-library', workspaceId, libraryKeyword, libraryScope, libraryOwnedOnly, libraryIncludeArchived,
    ],
    queryFn: () => designLibraryApi.list(workspaceId, {
      q: libraryKeyword.trim() || undefined,
      visibility: libraryScope === 'all' ? undefined : libraryScope,
      owned_only: libraryOwnedOnly || undefined,
      include_archived: libraryIncludeArchived || undefined,
    }),
    enabled: !!workspaceId && view === 'library',
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['designs', workspaceId] })

  /** 进入某产品的编辑器并切到结构树态（列表点击 / 新建成功共用） */
  const openProduct = (designId: number) => {
    setView('tree')
    navigate(designEditorPath(workspaceId, designId))
    if (mobile) onNavigate?.()
  }

  const create = useMutation({
    mutationFn: (values: DesignFormValues) =>
      designsApi.create(workspaceId, {
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
      openProduct(created.id)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建失败'),
  })

  const rename = useMutation({
    mutationFn: (payload: { item: DesignListItem; values: DesignFormValues }) =>
      designsApi.update(workspaceId, payload.item.id, {
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
    mutationFn: (item: DesignListItem) => designsApi.remove(workspaceId, item.id),
    onSuccess: (_data, item) => {
      message.success('设计已删除')
      invalidate()
      if (item.id !== activeDesignId) return
      // 删除当前产品：回落到最近更新的其余产品；全部删除则回根页空态（边界 #3）
      const rest = designs.filter(candidate => candidate.id !== item.id)
      const next = latestDesignId(rest)
      navigate(next == null
        ? `/w/${workspaceId}/design`
        : designEditorPath(workspaceId, next), { replace: true })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  /** 路由进入编辑器（含从列表选择产品）自动切树态；模块库页切库态；回根页切列表态 */
  useEffect(() => {
    if (activeDesignId !== undefined) setView('tree')
    else if (activeLibraryId !== undefined) setView('library')
    else setView('list')
  }, [activeDesignId, activeLibraryId])

  /** 列表可见项：标题搜索 + 类型筛选 */
  const visibleDesigns = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return designs.filter(item => (
      (kindFilter === 'all' || item.kind === kindFilter)
      && (!query || item.title.toLowerCase().includes(query))
    ))
  }, [designs, kindFilter, keyword])

  const openRename = (item: DesignListItem) => {
    renameForm.setFieldsValue({ title: item.title, description: item.description })
    setRenaming(item)
  }

  const confirmDelete = (item: DesignListItem) => {
    modal.confirm({
      title: `删除设计「${item.title}」？`,
      content: '版本历史会一并隐藏，操作不可撤销。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => remove.mutateAsync(item),
    })
  }

  const renderRow = (item: DesignListItem) => {
    const active = item.id === activeDesignId
    return (
      <div
        key={item.id}
        role="option"
        aria-selected={active}
        data-testid={`design-row-${item.id}`}
        className={[
          'cn-design-nav-row',
          active ? 'cn-design-nav-row--active' : '',
        ].filter(Boolean).join(' ')}
        onClick={() => openProduct(item.id)}
      >
        <ToolOutlined className="cn-design-nav-row-icon" />
        <div className="cn-design-nav-row-main">
          <div className="cn-design-nav-row-title">
            <Text strong ellipsis={{ tooltip: item.title }}>{item.title}</Text>
            <span className="cn-design-nav-row-version">v{item.version_count}</span>
          </div>
          <div className="cn-design-nav-row-meta">
            <Tag variant="filled" color={item.kind === 'part' ? 'blue' : 'geekblue'}>
              {item.kind === 'part' ? '零件' : '装配'}
            </Tag>
            {item.folder && <Tag variant="filled">{item.folder}</Tag>}
            {item.dependencies_stale && (
              <Tag color="gold" variant="filled" data-testid={`design-list-stale-${item.id}`}>依赖陈旧</Tag>
            )}
            <span className="cn-design-nav-row-time">{formatDateTime(item.updated_at)}</span>
          </div>
        </div>
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              { key: 'open', label: '打开', icon: <ToolOutlined /> },
              ...(isViewer
                ? []
                : [
                    { key: 'rename', label: '编辑', icon: <EditOutlined /> },
                    { type: 'divider' as const },
                    { key: 'delete', label: '删除', icon: <DeleteOutlined />, danger: true },
                  ]),
            ],
            onClick: ({ key, domEvent }) => {
              domEvent.stopPropagation()
              if (key === 'open') openProduct(item.id)
              else if (key === 'rename') openRename(item)
              else if (key === 'delete') confirmDelete(item)
            },
          }}
        >
          <Button
            type="text"
            size="small"
            className="cn-design-nav-row-more"
            icon={<MoreOutlined />}
            aria-label={`${item.title} 操作`}
            onClick={event => event.stopPropagation()}
          />
        </Dropdown>
      </div>
    )
  }

  // ── 结构树态：当前产品的单一大纲（根 = 产品，下挂系统 → 组件 → 分组 → 零件） ──
  const [outline, setOutline] = useState<OutlineState | null>(null)
  const [outlineLoading, setOutlineLoading] = useState(false)
  const [outlineError, setOutlineError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])

  const [searchParams] = useSearchParams()
  const revealLine = Number(searchParams.get('line')) || undefined
  const treeRef = useRef<ComponentRef<typeof Tree> | null>(null)

  useEffect(() => {
    if (activeDesignId === undefined) {
      setOutline(null)
      setOutlineError(null)
      return
    }
    let cancelled = false
    // IR 快照缓存优先（键与编辑器 useQuery 一致，designId 为字符串）
    const cached = queryClient
      .getQueryData<DesignIRResponse>(['designs', workspaceId, String(activeDesignId), 'ir'])
      ?.ir?.outline?.children
    setExpandedKeys([`design-${activeDesignId}`])
    if (cached) {
      setOutline({ nodes: cached, source: 'compiled' })
      setOutlineLoading(false)
      setOutlineError(null)
      return () => { cancelled = true }
    }
    setOutlineLoading(true)
    setOutlineError(null)
    designsApi
      .outline(workspaceId, activeDesignId)
      .then((result) => {
        if (cancelled) return
        setOutline({ nodes: result.outline.children, source: result.source })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setOutline(null)
        setOutlineError(err instanceof Error ? err.message : '结构加载失败')
      })
      .finally(() => {
        if (!cancelled) setOutlineLoading(false)
      })
    return () => { cancelled = true }
  }, [workspaceId, activeDesignId, queryClient, reloadKey])

  const activeDesign = designs.find(item => item.id === activeDesignId) ?? null

  const treeData = useMemo<DesignTreeDataNode[]>(() => {
    if (!outline || activeDesignId === undefined) return []
    const entries = outlineToTree(outline.nodes, activeDesignId)
    const partCount = entries.reduce((total, entry) => total + entry.meta.partCount, 0)
    return [{
      key: `design-${activeDesignId}`,
      meta: { type: 'design' as const, designId: activeDesignId, partCount },
      isLeaf: outline.nodes.length === 0,
      icon: <ToolOutlined />,
      title: renderDesignTitle(activeDesignId, activeDesign, outline),
      children: entries.map(entryToTreeNode),
    }]
  }, [outline, activeDesignId, activeDesign])

  /** 反向定位：源行 → 大纲节点路径 → 树 key 路径（ADR 0103 C1② / D9） */
  const revealKeyPath = useMemo(() => {
    if (!outline || revealLine === undefined || activeDesignId === undefined) return []
    const path = resolveOutlinePath(outline.nodes, revealLine, activeDesignId)
    return outlineKeyPath(outline.nodes, path, activeDesignId)
  }, [outline, revealLine, activeDesignId])

  // 反向定位生效：展开祖先链 + 滚动到选中节点（virtual 滚动由 Tree.scrollTo 处理）
  useEffect(() => {
    if (revealKeyPath.length === 0 || activeDesignId === undefined) return
    const ancestors = revealKeyPath.slice(0, -1)
    setExpandedKeys(prev => Array.from(new Set([...prev, `design-${activeDesignId}`, ...ancestors])))
    const key = revealKeyPath[revealKeyPath.length - 1]!
    const timer = window.setTimeout(() => treeRef.current?.scrollTo({ key }), 0)
    return () => window.clearTimeout(timer)
  }, [revealKeyPath, activeDesignId])

  function renderDesignTitle(
    designId: number,
    item: DesignListItem | null,
    current: OutlineState,
  ) {
    return (
      <span className="cn-design-tree-title" data-testid={`design-node-${designId}`}>
        <Text strong>{item?.title ?? `设计 #${designId}`}</Text>
        {item?.kind === 'part' && <Tag variant="filled" className="cn-design-tree-tag">零件</Tag>}
        {item?.folder && <Tag variant="filled" className="cn-design-tree-tag">{item.folder}</Tag>}
        {item && <Text type="secondary" className="cn-design-tree-meta">v{item.version_count}</Text>}
        {item?.dependencies_stale && (
          <Tag color="gold" variant="filled" className="cn-design-tree-tag" data-testid={`design-stale-${designId}`}>
            依赖陈旧
          </Tag>
        )}
        {current.source === 'content' && (
          <Tag color="orange" variant="filled" className="cn-design-tree-tag">历史快照派生</Tag>
        )}
      </span>
    )
  }

  /** 点击节点：产品根 → 编辑器；系统 / 组件 / 分组 / 零件 → 编辑器并定位源行；
   * use 实例带源文件（IR v4）时打开该源文件（ADR 0086 C7） */
  const onSelectNode: TreeProps['onSelect'] = (_keys, info) => {
    const meta = (info.node as DesignTreeDataNode).meta
    if (!meta) return
    if (meta.type === 'design') {
      if (meta.designId) navigate(designEditorPath(workspaceId, meta.designId))
    } else if (meta.fileId) {
      navigate(designEditorPath(workspaceId, meta.fileId))
    } else {
      navigate(designEditorPath(workspaceId, meta.designId ?? 0, meta.line))
    }
    if (mobile) onNavigate?.()
  }

  if (collapsed) {
    return (
      <div data-testid="sider-designs" className="cn-table-nav">
        <div className="cn-design-nav-caption">设计</div>
      </div>
    )
  }

  const showTree = view === 'tree' && activeDesignId !== undefined

  /** 模块库行：只读打开模块详情 / 预览页（ADR 0118 P1） */
  const renderLibraryRow = (item: LibraryModuleItem) => {
    const active = item.id === activeLibraryId
    return (
      <div
        key={item.id}
        role="option"
        aria-selected={active}
        data-testid={`library-row-${item.id}`}
        className={[
          'cn-design-nav-row',
          active ? 'cn-design-nav-row--active' : '',
        ].filter(Boolean).join(' ')}
        onClick={() => {
          navigate(`/w/${workspaceId}/design/library/${item.id}`)
          if (mobile) onNavigate?.()
        }}
      >
        <BookOutlined className="cn-design-nav-row-icon" />
        <div className="cn-design-nav-row-main">
          <div className="cn-design-nav-row-title">
            <Text strong ellipsis={{ tooltip: item.name }}>{item.name}</Text>
            <span className="cn-design-nav-row-version">v{item.latest_version}</span>
          </div>
          <div className="cn-design-nav-row-meta">
            <Tag variant="filled" color={item.visibility === 'public' ? 'green' : 'default'}>
              {item.visibility === 'public' ? '公开' : '私有'}
            </Tag>
            {item.is_archived && <Tag color="red" variant="filled">已归档</Tag>}
            <span className="cn-design-nav-row-time">{item.module_key}</span>
          </div>
        </div>
      </div>
    )
  }

  const backToList = () => {
    setView('list')
    if (activeLibraryId !== undefined) navigate(`/w/${workspaceId}/design`)
  }

  return (
    <>
      <div data-testid="sider-designs" className="cn-table-nav cn-design-nav">
        {showTree ? (
          <div data-testid="design-outline-panel" className="cn-design-nav-panel">
            <div className="cn-design-nav-head">
              <Button
                size="small"
                type="text"
                icon={<ArrowLeftOutlined />}
                data-testid="design-nav-back"
                onClick={() => setView('list')}
              >
                产品列表
              </Button>
            </div>
            {outlineLoading ? (
              <div className="cn-state" data-testid="design-outline-loading"><Spin /></div>
            ) : outlineError ? (
              <div className="cn-state" data-testid="design-outline-error">
                <Space direction="vertical" size={8}>
                  <Text type="danger">结构加载失败：{outlineError}</Text>
                  <Button size="small" icon={<ReloadOutlined />} onClick={() => setReloadKey(key => key + 1)}>
                    重试
                  </Button>
                </Space>
              </div>
            ) : treeData.length === 0 ? (
              <div className="cn-state">
                <Empty description="该设计还没有结构节点，去编辑器补充" />
              </div>
            ) : (
              <div className="cn-design-nav-tree" data-testid="design-outline-tree">
                <Tree
                  ref={treeRef}
                  // 重试后按新数据重建（受控 expandedKeys 由设计切换重置）
                  key={reloadKey}
                  blockNode
                  showIcon
                  className="cn-doc-sider-tree"
                  treeData={treeData}
                  virtual
                  height={640}
                  expandedKeys={expandedKeys}
                  selectedKeys={revealKeyPath.length > 0
                    ? [revealKeyPath[revealKeyPath.length - 1]!]
                    : [`design-${activeDesignId}`]}
                  onExpand={keys => setExpandedKeys(keys as string[])}
                  onSelect={onSelectNode}
                />
              </div>
            )}
          </div>
        ) : view === 'library' ? (
          <div data-testid="design-library-panel" className="cn-design-nav-panel">
            <div className="cn-design-nav-head">
              <Button
                size="small"
                type="text"
                icon={<ArrowLeftOutlined />}
                data-testid="design-library-back"
                onClick={backToList}
              >
                产品列表
              </Button>
              <span className="cn-design-nav-count">共 {libraryModules.length} 个</span>
            </div>
            <div className="cn-design-nav-toolbar">
              <SearchInput
                placeholder="搜索模块名称 / key…"
                value={libraryKeyword}
                onChange={event => patchFilters({ libraryKeyword: event.target.value })}
                data-testid="design-library-filter"
                style={{ width: '100%' }}
              />
              <Segmented
                size="small"
                block
                value={libraryScope}
                onChange={value => patchFilters({ libraryScope: value as 'all' | 'public' | 'workspace' })}
                options={[
                  { value: 'all', label: '全部' },
                  { value: 'public', label: '公开' },
                  { value: 'workspace', label: '私有' },
                ]}
              />
              <Checkbox
                checked={libraryOwnedOnly}
                onChange={event => patchFilters({ libraryOwnedOnly: event.target.checked })}
              >
                仅本工作区发布
              </Checkbox>
              {isOwner && (
                <Checkbox
                  checked={libraryIncludeArchived}
                  onChange={event => patchFilters({ libraryIncludeArchived: event.target.checked })}
                >
                  含已归档
                </Checkbox>
              )}
            </div>
            <Spin spinning={libraryLoading}>
              {libraryModules.length === 0 && !libraryLoading ? (
                <div className="cn-state">
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无可见的复用模块"
                  />
                </div>
              ) : (
                <div
                  role="listbox"
                  aria-label="复用模块库"
                  data-testid="design-library-list"
                  className="cn-design-nav-list"
                >
                  {libraryModules.map(renderLibraryRow)}
                </div>
              )}
            </Spin>
          </div>
        ) : (
          <div data-testid="design-products-panel" className="cn-design-nav-panel">
            <div className="cn-design-nav-head">
              <span className="cn-design-nav-caption">设计</span>
              <span className="cn-design-nav-count">共 {visibleDesigns.length} 个</span>
            </div>
            <div className="cn-design-nav-toolbar">
              <SearchInput
                placeholder="搜索设计…"
                value={keyword}
                onChange={event => patchFilters({ keyword: event.target.value })}
                data-testid="design-nav-filter"
                style={{ width: '100%' }}
              />
              <Segmented
                size="small"
                block
                value={kindFilter}
                onChange={value => patchFilters({ kindFilter: value as 'all' | 'part' | 'assembly' })}
                data-testid="design-kind-filter"
                options={[
                  { value: 'all', label: '全部' },
                  { value: 'part', label: '零件' },
                  { value: 'assembly', label: '装配' },
                ]}
              />
              {!isViewer && (
                <Button
                  type="primary"
                  size="small"
                  block
                  icon={<PlusOutlined />}
                  onClick={() => setCreateOpen(true)}
                >
                  新建设计
                </Button>
              )}
              <Button
                size="small"
                block
                icon={<BookOutlined />}
                data-testid="design-library-open"
                onClick={() => setView('library')}
              >
                复用模块库
              </Button>
            </div>
            <Spin spinning={isLoading}>
              {designs.length === 0 && !isLoading ? (
                <div className="cn-state">
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={isViewer ? '当前工作区还没有结构设计' : '还没有结构设计'}
                  />
                </div>
              ) : visibleDesigns.length === 0 ? (
                <div className="cn-state">
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该类型下暂无设计" />
                </div>
              ) : (
                <div role="listbox" aria-label="产品列表" data-testid="design-list" className="cn-design-nav-list">
                  {visibleDesigns.map(renderRow)}
                </div>
              )}
            </Spin>
          </div>
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
    </>
  )
}
