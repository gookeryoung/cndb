/** 设计侧栏导航（ADR 0084 D4 / D5）
 *
 * 形态对齐文档段侧栏（需求 0065）：标题 + 标题过滤 + 装配树；桌面 Sider 与移动抽屉共用。
 * 树层级 = 设计根 → 系统（复杂系统级）→ 组件（module 实例，可嵌套）→ 结构分组 → 零件，
 * 大纲按设计懒加载既有 outline 端点（ADR 0083 D4），节点带 1 基源行并可点击定位编辑器（D7）。
 * 侧栏只读（D6）：改名 / 删除在设计管理页完成。
 */

import { useEffect, useMemo, useRef, useState, type ComponentRef } from 'react'
import { Tag, Tree, Typography } from 'antd'
import type { DataNode, TreeProps } from 'antd/es/tree'
import {
  ApartmentOutlined, AppstoreOutlined, ClusterOutlined, NodeIndexOutlined, ToolOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { designsApi } from '@/api'
import type { DesignIRResponse, DesignListItem, DesignOutlineNode } from '@/api'
import SearchInput from '@/components/SearchInput'
import {
  designEditorPath, type DesignTreeEntry, type DesignTreeMeta, outlineKeyPath, outlineToTree,
  resolveOutlinePath,
} from './designOutline'

const { Text } = Typography

/** 大纲节点图标：系统 / 组件 / 分组 / 零件各一类（设计根用工具图标） */
const ENTRY_ICONS = {
  system: ApartmentOutlined,
  assembly: ClusterOutlined,
  group: NodeIndexOutlined,
  part: AppstoreOutlined,
} as const

interface DesignTreeDataNode extends DataNode {
  meta?: DesignTreeMeta
  children?: DesignTreeDataNode[]
}

interface OutlineState {
  nodes: DesignOutlineNode[]
  source: 'compiled' | 'content'
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

interface DesignStructureNavProps {
  workspaceId: string
  /** 移动端抽屉：点击条目后收起 */
  mobile?: boolean
  /** 桌面端 Sider 折叠态：只保留标题 */
  collapsed?: boolean
  onNavigate?: () => void
}

/** 从 pathname 取当前编辑器中的设计 id（管理页与静态段不匹配则为 undefined） */
function activeDesignIdFrom(pathname: string, workspaceId: string): number | undefined {
  const match = new RegExp(`^/w/${workspaceId}/design/(\\d+)$`).exec(pathname)
  return match ? Number(match[1]) : undefined
}

export default function DesignStructureNav({
  workspaceId, mobile = false, collapsed = false, onNavigate,
}: DesignStructureNavProps) {
  const navigate = useNavigate()
  const pathname = useLocation().pathname
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  // 已加载大纲（按设计 id）：展开设计时懒加载（ADR 0083 D4）；source=content = 历史快照派生
  const [outlines, setOutlines] = useState<Record<number, OutlineState>>({})
  const [loadingIds, setLoadingIds] = useState<Record<number, boolean>>({})

  const activeDesignId = activeDesignIdFrom(pathname, workspaceId)
  // 编辑器 ?line= 反向通知侧栏（ADR 0103 C1② / D9）：按大纲归属选中节点并滚动到可视区
  const [searchParams] = useSearchParams()
  const revealLine = Number(searchParams.get('line')) || undefined
  const treeRef = useRef<ComponentRef<typeof Tree> | null>(null)

  const { data: designs = [], isLoading } = useQuery({
    queryKey: ['designs', workspaceId],
    queryFn: () => designsApi.list(workspaceId),
    enabled: !!workspaceId,
  })

  const filteredDesigns = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    if (!q) return designs
    return designs.filter(item => item.title.toLowerCase().includes(q))
  }, [designs, keyword])

  /** 展开设计时懒加载该设计大纲（ADR 0083 D4）；历史快照派生只读，保存一次后自然落库（D5）。
   * 打开性能（ADR 0086 D10）：编辑器已拉取 /ir 时直接复用其大纲建树，不重复请求 /outline */
  const loadOutline = (designId: number): Promise<void> => {
    if (outlines[designId] || loadingIds[designId]) return Promise.resolve()
    // IR 快照缓存优先（键与编辑器 useQuery 一致，designId 为字符串）
    const irResp = queryClient.getQueryData<DesignIRResponse>([
      'designs', workspaceId, String(designId), 'ir',
    ])
    const cachedChildren = irResp?.ir?.outline?.children
    if (cachedChildren) {
      setOutlines(prev => ({ ...prev, [designId]: { nodes: cachedChildren, source: 'compiled' } }))
      return Promise.resolve()
    }
    setLoadingIds(prev => ({ ...prev, [designId]: true }))
    return designsApi
      .outline(workspaceId, designId)
      .then(result => {
        setOutlines(prev => ({ ...prev, [designId]: { nodes: result.outline.children, source: result.source } }))
      })
      .catch(() => undefined)
      .finally(() => setLoadingIds(prev => ({ ...prev, [designId]: false })))
  }

  // 进入编辑器时自动展开当前设计并加载大纲：进入模块即见装配结构（C1）
  useEffect(() => {
    if (activeDesignId === undefined) return
    const key = `design-${activeDesignId}`
    setExpandedKeys(prev => (prev.includes(key) ? prev : [...prev, key]))
    void loadOutline(activeDesignId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDesignId])

  // 过滤命中时展开命中设计（未展开则同时拉大纲）；设计清单异步到达后也要重跑一次
  useEffect(() => {
    if (!keyword.trim()) return
    const keys = filteredDesigns.map(item => `design-${item.id}`)
    if (keys.length === 0) return
    setExpandedKeys(prev => Array.from(new Set([...prev, ...keys])))
    filteredDesigns.forEach(item => void loadOutline(item.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, designs])

  const activeOutline = activeDesignId === undefined ? undefined : outlines[activeDesignId]?.nodes
  /** 反向定位：源行 → 大纲节点路径 → 树 key 路径（无大纲 / 无命中为空数组） */
  const revealKeyPath = useMemo(() => {
    if (!activeOutline || revealLine === undefined || activeDesignId === undefined) return []
    const path = resolveOutlinePath(activeOutline, revealLine, activeDesignId)
    return outlineKeyPath(activeOutline, path, activeDesignId)
  }, [activeOutline, revealLine, activeDesignId])

  // 反向定位生效：展开祖先链 + 滚动到选中节点（virtual 滚动由 Tree.scrollTo 处理）
  useEffect(() => {
    if (revealKeyPath.length === 0) return
    const ancestors = revealKeyPath.slice(0, -1)
    setExpandedKeys(prev => Array.from(new Set([...prev, `design-${activeDesignId}`, ...ancestors])))
    const key = revealKeyPath[revealKeyPath.length - 1]!
    const timer = window.setTimeout(() => treeRef.current?.scrollTo({ key }), 0)
    return () => window.clearTimeout(timer)
  }, [revealKeyPath, activeDesignId])

  const treeData = useMemo<DesignTreeDataNode[]>(
    () => filteredDesigns.map(item => {
      const outline = outlines[item.id]
      const entries = outline ? outlineToTree(outline.nodes, item.id) : []
      // 一次后序计数在 outlineToTree 内完成（ADR 0086 C7），这里只求根层和
      const partCount = entries.reduce((total, entry) => total + entry.meta.partCount, 0)
      return {
        key: `design-${item.id}`,
        meta: { type: 'design' as const, designId: item.id, partCount },
        isLeaf: outline ? outline.nodes.length === 0 : false,
        icon: <ToolOutlined />,
        title: renderDesignTitle(item, outline),
        children: entries.map(entryToTreeNode),
      }
    }),
    // renderDesignTitle 依赖 outlines / designs，均在本依赖内
    [filteredDesigns, outlines],
  )

  function renderDesignTitle(item: DesignListItem, outline?: OutlineState) {
    return (
      <span className="cn-design-tree-title" data-testid={`design-node-${item.id}`}>
        <Text strong>{item.title}</Text>
        {item.kind === 'part' && <Tag bordered={false} className="cn-design-tree-tag">零件</Tag>}
        <Text type="secondary" className="cn-design-tree-meta">v{item.version_count}</Text>
        {item.dependencies_stale && (
          <Tag color="gold" bordered={false} className="cn-design-tree-tag" data-testid={`design-stale-${item.id}`}>
            依赖陈旧
          </Tag>
        )}
        {outline?.source === 'content' && (
          <Tag color="orange" bordered={false} className="cn-design-tree-tag">历史快照派生</Tag>
        )}
      </span>
    )
  }

  /** 点击节点：设计 → 编辑器；系统 / 组件 / 分组 / 零件 → 编辑器并定位源行（ADR 0083 D7）；
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
        <div style={{
          padding: 'var(--cn-space-sm) var(--cn-space-lg)', fontWeight: 600,
          color: 'var(--cn-text-secondary)', fontSize: 12,
        }}>
          设计
        </div>
      </div>
    )
  }

  return (
    <div data-testid="sider-designs" className="cn-table-nav">
      <div style={{
        padding: 'var(--cn-space-sm) var(--cn-space-lg)', fontWeight: 600,
        color: 'var(--cn-text-secondary)', fontSize: 12,
      }}>
        设计
      </div>
      <div style={{ padding: '0 var(--cn-space-lg) var(--cn-space-sm)' }}>
        <SearchInput
          placeholder="过滤设计…"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          data-testid="design-nav-filter"
          style={{ width: '100%' }}
        />
      </div>
      {isLoading ? (
        <div className="cn-state">加载中…</div>
      ) : treeData.length === 0 ? (
        <div className="cn-state">
          <p>{keyword.trim() ? '没有匹配的设计' : '还没有结构设计，去设计页创建吧'}</p>
        </div>
      ) : (
        <div style={{ padding: '0 var(--cn-space-sm) var(--cn-space-sm) var(--cn-space-xs)' }}>
          <Tree
            ref={treeRef}
            blockNode
            showIcon
            className="cn-doc-sider-tree"
            treeData={treeData}
            // 虚拟滚动：大装配只渲染可见节点（ADR 0086 C7）
            virtual
            height={640}
            expandedKeys={expandedKeys}
            selectedKeys={activeDesignId === undefined
              ? []
              : revealKeyPath.length > 0
                ? [revealKeyPath[revealKeyPath.length - 1]!]
                : [`design-${activeDesignId}`]}
            onExpand={keys => setExpandedKeys(keys as string[])}
            loadData={(node) => {
              const meta = (node as DesignTreeDataNode).meta
              return meta?.type === 'design' && meta.designId ? loadOutline(meta.designId) : Promise.resolve()
            }}
            onSelect={onSelectNode}
          />
        </div>
      )}
    </div>
  )
}
