import React, { Suspense, lazy, useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { Outlet, useNavigate, useParams, useSearchParams, useLocation, Navigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Button, App as AntApp, Tooltip, Tabs, Drawer, Tree } from 'antd'
import type { MenuProps, TabsProps } from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  LogoutOutlined, TableOutlined,
  UserOutlined, ExclamationCircleOutlined, SearchOutlined,
  SettingOutlined, SafetyOutlined, QuestionCircleOutlined,
  MenuOutlined, InfoCircleOutlined,
  DatabaseOutlined,
  FolderOutlined, FolderOpenOutlined,
  PullRequestOutlined, BarChartOutlined, CloudDownloadOutlined,
  SafetyCertificateOutlined, ToolOutlined,
  RobotOutlined, FolderFilled, FileTextOutlined, SortAscendingOutlined,
  MenuUnfoldOutlined, MenuFoldOutlined,
  LockOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { systemApi, tableApi, workspaceApi } from '@/api'
import { documentsApi } from '@/api/documents'
import { ancestorChain, buildDocTree, type DocTreeNode } from '@/pages/documents/DocumentTree'
import DesignStructureNav from '@/pages/design/DesignStructureNav'
import {
  describeSort, DOC_SORT_OPTIONS, setDocTitleFilter, sortDocTree, sortToValue, useDocSortPref,
  useDocTitleFilter, valueToSort,
} from '@/pages/documents/docTreeSort'
import GlobalSearch from '@/components/GlobalSearch'
import SearchInput from '@/components/SearchInput'
import { BrandMark } from '@/components/BrandMark'
import { useAuthStore, useUiStore } from '@/store'
import { useResponsive } from '@/hooks/useResponsive'
import { workspaceLandingSegment, workspaceModulesFeatures } from '@/utils/workspaceModules'
import { formatMeta } from '@/components/Document/docFormat'
import { scrollActiveTabIntoViewNextFrame } from './tabScroll'
import { WEIGHT } from '@/theme/tokens'

// Modal 组件 lazy import：点击打开时才加载
const SettingsModal = lazy(() => import('@/pages/settings/SettingsModal'))
// 关于系统弹窗 lazy import：点击打开时才加载
const AboutModal = lazy(() => import('@/components/AboutModal'))
// 新手引导：MainLayout 挂载一次，内部自行判定触发时机
const OnboardingTour = lazy(() => import('@/components/onboarding/OnboardingTour'))

function ModalFallback() {
  return null
}

/** 表级子页定义 —— 融合导航行面包屑的下拉菜单与当前位置展示共用；顺序即菜单顺序. */
const TABLE_SUBPAGES = [
  { key: 'change-requests', label: '修改申请', icon: <PullRequestOutlined /> },
  { key: 'issues', label: '问题清单', icon: <ExclamationCircleOutlined /> },
  { key: 'settings', label: '数据表设置', icon: <SettingOutlined /> },
] as const

/** 文档区二级页定义 —— 与表级子页同形，但作用域是工作区下的全部文档（无「文档设置」）.
 * 「文档结构」在前（0082 C4）：指向既有文档总览列表页（/documents），作为文档模块的根级页签入口；
 * 「质量检查」（ADR 0080 D4）指向文档上下文的质量检查页（/documents/pipelines），
 * 只呈现 document/* 检查动作与规则，不跳到数据表段；其余子页同样导航到 /documents/<key>。 */
const DOCUMENT_SUBPAGES = [
  { key: 'structure', label: '文档结构', icon: <FolderOpenOutlined />, to: '' },
  { key: 'pipelines', label: '质量检查', icon: <SafetyCertificateOutlined />, to: 'pipelines' },
  { key: 'change-requests', label: '修改申请', icon: <PullRequestOutlined />, to: 'change-requests' },
  { key: 'issues', label: '问题清单', icon: <ExclamationCircleOutlined />, to: 'issues' },
] as const

/** 设计区二级页定义 —— 与文档区同形（cn-table-crumb + cn-table-tab）。
 * 0083：仅「设计结构」一项，`to: ''` 即模块根页（/w/:wid/design）作为默认页；
 * 编辑器页（/w/:wid/design/:id）显示页签但无子页激活。设计区不引入双轨修改申请（ADR 0079 D6）。 */
const DESIGN_SUBPAGES = [
  { key: 'structure', label: '设计结构', icon: <ApartmentOutlined />, to: '' },
] as const

/** 文档树节点 → antd Tree 节点：文件夹/文档区分图标，原始节点挂在 docNode 供点击导航. */
function toTreeNode(node: DocTreeNode): DataNode {
  // 格式图标与文档页树同口径（docFormat 单点维护）：PDF / 图片等按格式区分形状与配色
  const fmt = formatMeta(node.content_type, node.is_folder)
  const FormatIcon = fmt.Icon
  return {
    key: String(node.id),
    icon: node.is_folder
      ? <FolderFilled style={{ color: 'var(--cn-primary, #1677ff)' }} />
      : <FormatIcon style={{ color: fmt.color }} />,
    // 可见性提示：未发布的文档同事看不到，明确告知以免误以为"文档丢了"（与旧文档树口径一致）
    // 单行省略：文本占满剩余宽度截断（完整标题放 title 悬停提示），私有锁等尾缀图标不参与截断
    title: (
      <span className="cn-doc-sider-title" title={node.title} data-testid={`doc-tree-doc-${node.id}`}>
        <span className="cn-doc-sider-title-text">{node.title}</span>
        {!node.is_folder && node.visibility === 'private' && (
          <Tooltip title="未发布：仅你与工作区所有者可见">
            <LockOutlined
              aria-label="仅自己可见"
              data-testid={`doc-visibility-${node.id}`}
              style={{ marginLeft: 6, fontSize: 11, color: 'var(--cn-text-secondary, #8c8c8c)' }}
            />
          </Tooltip>
        )}
      </span>
    ),
    docNode: node,
    children: node.children.map(toTreeNode),
  } as DataNode
}

/** 树标题过滤：保留命中节点及其祖先链（空关键词返回原树） */
function filterDocTree(nodes: DocTreeNode[], keyword: string): DocTreeNode[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return nodes
  const walk = (node: DocTreeNode): DocTreeNode | null => {
    const children = node.children.map(walk).filter((c): c is DocTreeNode => c !== null)
    if (node.title.toLowerCase().includes(kw) || children.length > 0) return { ...node, children }
    return null
  }
  return nodes.map(walk).filter((n): n is DocTreeNode => n !== null)
}

/** 内容区骨架 —— 懒加载页面在 Content 内挂起时的占位，避免整页高度跳动 */
function ContentFallback() {
  return (
    <div className="cn-page" aria-label="页面加载中">
      <div style={{ height: 28, width: 220, borderRadius: 'var(--cn-radius-base)', background: 'var(--cn-border)' }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--cn-space-lg)' }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{ height: 40, borderRadius: 'var(--cn-radius-lg)', background: 'var(--cn-border)', opacity: 0.5 }} />
        ))}
      </div>
    </div>
  )
}

const { Header, Sider, Content } = Layout

export default function MainLayout() {
  const navigate = useNavigate()
  const { modal } = AntApp.useApp()
  const { wid, tid, docId } = useParams<{ wid: string; tid?: string; docId?: string }>()
  const location = useLocation().pathname
  const user = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)
  const { isMobile } = useResponsive()
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const settingsOpen = useUiStore(s => s.settingsOpen)
  const settingsTab = useUiStore(s => s.settingsTab)
  const openSettings = useUiStore(s => s.openSettings)
  const closeSettings = useUiStore(s => s.closeSettings)
  // 关于系统弹窗开关 —— 所有登录用户可见
  const [aboutOpen, setAboutOpen] = useState(false)
  /** 顶部导航横滑容器（工作区页签 + 二级页签）—— 窄屏下把激活项滚入可视区 */
  const wsTabsRef = useRef<HTMLDivElement>(null)
  const [searchParams] = useSearchParams()
  // 移动端抽屉导航开关（仅 isMobile 时渲染汉堡入口）
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  /** 跨表导航时保留当前 URL 的 query params（如 ?mode=calendar、?view=123）. */
  const navigateToTable = useCallback((targetWid: string | number, targetTid: string | number) => {
    const params = new URLSearchParams()
    // 复制需要保留的 params
    for (const key of ['mode', 'view']) {
      const v = searchParams.get(key)
      if (v) params.set(key, v)
    }
    const qs = params.toString()
    navigate(`/w/${targetWid}/tables/${targetTid}${qs ? `?${qs}` : ''}`)
  }, [searchParams, navigate])

  /** hover 预取表详情 —— 点击进表时 useTable 命中缓存，减少冷启动白屏（queryKey 与 useTable 一致）. */
  const prefetchTable = useCallback((targetWid: string, targetTid: string | number) => {
    void queryClient.prefetchQuery({
      queryKey: ['table', `${targetWid}/${targetTid}`],
      queryFn: () => tableApi.get(targetWid, String(targetTid)),
      staleTime: 60_000,
    })
  }, [queryClient])

  const { data: workspaces = [], isLoading: wsLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 顶栏版本小字 —— 与「关于系统」弹窗共用缓存；版本是非关键信息，失败静默不重试
  const { data: systemAbout } = useQuery({
    queryKey: ['system-about'],
    queryFn: systemApi.about,
    staleTime: 60_000,
    retry: false,
  })

  const currentWs = workspaces.find(w => String(w.id) === wid)
  /** 当前工作区按勾选模块开放的功能（模块缺失/非法时按默认全三模块兜底） */
  const wsFeatures = workspaceModulesFeatures(currentWs?.modules)

  const { data: tables = [], isSuccess: tablesReady } = useQuery({
    queryKey: ['workspaces', wid, 'tables'],
    queryFn: () => (wid ? tableApi.list(wid) : Promise.resolve([])),
    enabled: !!wid && wsFeatures.tables,
  })

  // 文档数徽标：limit=1 仅取 total 计数，避免拉全量
  const { data: docCount, isSuccess: docsReady } = useQuery({
    queryKey: ['documents', Number(wid), 'count'],
    queryFn: () => documentsApi.list(Number(wid), { limit: 1 }),
    enabled: !!wid && wsFeatures.documents,
    staleTime: 60_000,
  })

  // 文档侧栏的文档树：与文档管理页同源 tree 端点（共享 react-query 缓存），全量文档+文件夹
  const inDocumentsContext = !!wid && location.startsWith(`/w/${wid}/documents`)
  // 设计模块上下文：页签行不再渲染工作区级质量检查（2026-11-02 用户口径）
  const inDesignContext = !!wid && location.startsWith(`/w/${wid}/design`)
  const { data: docsTreeData, isSuccess: docsTreeReady } = useQuery({
    // 注意 key 用数字 wid：文档页 invalidateQueries 按 ['documents', <number>] 前缀失效，
    // 字符串 wid 与数字 workspaceId 严格不等会导致前缀匹配不上、侧边栏不随页面变更刷新
    queryKey: ['documents', Number(wid), 'tree'],
    queryFn: () => documentsApi.tree(Number(wid)),
    enabled: !!wid && wsFeatures.documents && inDocumentsContext,
  })
  const docTree = useMemo(() => buildDocTree(docsTreeData ?? []), [docsTreeData])
  // 树排序偏好（沿用原页面内左树的 docTreeSort 口径）：与文档内容区排序控件共享同一偏好，实时同步
  const [docSort, setDocSort] = useDocSortPref()
  // 标题过滤（与文档内容区过滤框联动，共享同一关键词；命中节点及其祖先链保留）
  const [docTreeKeyword] = useDocTitleFilter()
  // 编辑器路由参数：仅纯数字为真实文档 id（静态子页段不会落入 docId，此处双保险）
  const activeDocId = docId && /^\d+$/.test(docId) ? docId : undefined
  // 树展开态：用户展开/收起前按「当前文档祖先链 + 一级文件夹」自动展开；交互后以手动状态为准
  const [manualExpanded, setManualExpanded] = useState<string[] | null>(null)
  const setDocTreeExpanded = (keys: string[]) => setManualExpanded(keys)
  const autoExpanded = useMemo(() => {
    const rootFolders = docTree.filter(n => n.is_folder).map(n => String(n.id))
    if (!activeDocId) return rootFolders
    return [...ancestorChain(docsTreeData ?? [], Number(activeDocId)).map(d => String(d.id)), ...rootFolders]
  }, [docTree, docsTreeData, activeDocId])
  const docTreeExpanded = manualExpanded ?? autoExpanded
  // 展开全部 / 收起全部：图标随切换变化（收起态下一键展开全部节点，展开态下一键收起）
  const [treeCollapsed, setTreeCollapsed] = useState(false)
  const toggleTreeExpanded = () => {
    setManualExpanded(treeCollapsed ? docTree.map(n => String(n.id)) : [])
    setTreeCollapsed(!treeCollapsed)
  }

  // 后端已按 DataTable.order（用户拖拽顺序）返回，这里直接使用即可。
  /** 侧栏表搜索关键词：按表名过滤（需求 0068，接入 SearchInput 统一组件） */
  const [tableKeyword, setTableKeyword] = useState('')
  const orderedTables = useMemo(
    () => tables.filter(t => t.name.toLowerCase().includes(tableKeyword.trim().toLowerCase())),
    [tables, tableKeyword],
  )

  // ── 表级页签（融合导航行，紧随工作区分页之后）──
  // 当 URL 处于某张表的上下文（网格页 /w/:wid/tables/:tid 及其子页）时，
  // 在工作区 Tabs 右侧以竖线分割后渲染：表名（点击返回网格）+ 子页页签（GitHub 风格页签切换）。
  const inTableContext = !!wid && !!tid && location.startsWith(`/w/${wid}/tables/${tid}`)

  // 激活态由 pathname 驱动：表详情页及表级子页一律落在「数据表」（子页高亮由表级导航负责），
  // 避免表设置页（/tables/:tid/settings）被误判为「工作区设置」
  const activeWsTab = inTableContext
    ? 'tables'
    : location.includes('/documents')
      ? 'documents'
      : location.includes('/design')
        ? 'design'
        : location.includes('/analytics')
          ? 'analytics'
          : location.includes('/datasource')
            ? 'datasource'
            : location.includes('/pipelines')
              ? 'pipelines'
              : location.includes('/settings')
                ? 'settings'
              : 'tables'

  /** 数据表派生二级功能（数据分析 / 数据同步）的显示窗口：仅在数据表模块上下文
   * （表列表、表级页、分析段、同步段、质量检查段）显示；切到文档 / 设计 / 工作区设置一级模块时隐藏，
   * 避免与当前模块无关的入口干扰导航。工作区级质量检查页（/pipelines）属数据表域：
   * 落在该页时窗口保持开启（与数据分析行为一致），页签行不消失。 */
  const tablesDerivedActive =
    activeWsTab === 'tables' || activeWsTab === 'analytics' || activeWsTab === 'datasource'
    || activeWsTab === 'pipelines'

  /** 顶栏一级模块导航（需求 0081 C4）：数据表 → 文档 → 设计 → 工作区设置.
   *
   * 前三项按勾选模块门控（ADR 0080 口径），「工作区设置」恒显；
   * 数据表 / 文档带数量徽标（仅数据就绪后渲染，0 也显示）；
   * key 即路由段（/w/:wid/{key}），激活态由 activeWsTab 驱动。
   * 仅桌面端渲染：移动端顶栏放不下，一级模块维持页签行承载（C5）。
   */
  const headerNavItems = [
    ...(wsFeatures.tables ? [{
      key: 'tables',
      icon: <DatabaseOutlined />,
      label: '数据表',
      count: tablesReady ? tables.length : undefined,
    }] : []),
    ...(wsFeatures.documents ? [{
      key: 'documents',
      icon: <FileTextOutlined />,
      label: '文档',
      count: docsReady && docCount ? docCount.total : undefined,
    }] : []),
    ...(wsFeatures.design ? [{
      key: 'design',
      icon: <ToolOutlined />,
      label: '设计',
      count: undefined,
    }] : []),
    { key: 'settings', icon: <SettingOutlined />, label: '工作区设置', count: undefined },
  ] as const

  /** 工作区级分页导航（需求 0081 C5）：仅承载二级功能模块，维持原位置.
   *
   * 顺序：数据列表 → 质量检查 → 数据分析 → 数据同步（质量检查紧随数据列表，2026-11-02 用户口径）。
   * 数据分析 / 数据同步随数据表开放，且仅在数据表模块上下文显示
   * （切到文档 / 设计 / 工作区设置时隐藏，tablesDerivedActive 收敛）；
   * 工作区级质量检查（/pipelines）为数据表域入口，恒显（ADR 0080），
   * 但文档 / 设计模块上下文除外：文档区胶囊页签已承载文档质量检查（/documents/pipelines），
   * 页签行再渲染一份属冗余；设计模块按 2026-11-02 用户口径不承载质量检查入口（设置段仍显示）。
   * 一级模块已上移顶栏（C4），
   * 仅移动端仍在页签行全量渲染（顶栏空间不足，移动端形态维持现状）。
   */
  const secondaryTabItems: TabsProps['items'] = [
    // 「数据列表」为数据表一级导航的第一个二级页签：进入数据表模块默认落在 /tables（数据列表视图），
    // 从数据分析 / 质量检查等二级功能点击可回到列表。仅桌面端渲染：
    // 移动端页签行一级模块已有「数据表」入口（key 同为 tables），避免重复。
    ...(wsFeatures.tables && !isMobile && tablesDerivedActive ? [{
      key: 'tables',
      label: (
        <span>
          <TableOutlined /> 数据列表
        </span>
      ),
    }] : []),
    // 质量检查紧随数据列表（第二项）：文档 / 设计上下文不显示——文档区胶囊页签已有入口，
    // 设计模块不承载质量检查入口，避免同名页签混入其他模块
    ...(wsFeatures.quality && !inDocumentsContext && !inDesignContext ? [{
      key: 'pipelines',
      label: (
        <span>
          <SafetyCertificateOutlined /> 质量检查
        </span>
      ),
    }] : []),
    ...(wsFeatures.analytics && tablesDerivedActive ? [{
      key: 'analytics',
      label: (
        <span>
          <BarChartOutlined /> 数据分析
        </span>
      ),
    }] : []),
    ...(wsFeatures.datasource && tablesDerivedActive ? [{
      key: 'datasource',
      label: (
        <span>
          <CloudDownloadOutlined /> 数据同步
        </span>
      ),
    }] : []),
  ]
  const wsTabItems: TabsProps['items'] = isMobile
    ? [
      ...headerNavItems.map(item => ({
        key: item.key,
        label: (
          <span>
            {item.icon} {item.label}
            {item.count !== undefined && <span className="cn-ws-tab-count">{item.count}</span>}
          </span>
        ),
      })),
      ...secondaryTabItems,
    ]
    : secondaryTabItems
  const currentTable = orderedTables.find(t => String(t.id) === String(tid))
  const activeTableTab = location.includes('/change-requests')
    ? 'change-requests'
    : location.includes('/issues')
      ? 'issues'
      : location.includes('/settings')
        ? 'settings'
        : ''
  const activeSubpage = TABLE_SUBPAGES.find(p => p.key === activeTableTab)

  // ── 文档区二级页签（与表级同形：竖线分割 + 胶囊页签）──
  // 进入 /w/:wid/documents 及其子页时，在工作区 Tabs 右侧渲染子页页签（无根入口，「文档结构」即根）。
  // 注意：/w/:wid/documents/:docId 也在该前缀下（编辑器页），此时无子页激活。
  // inDocumentsContext 已在上方文档侧栏查询处定义
  // 「文档结构」页签即文档总览列表页本体（/documents 无子段时激活）；
  // 其余子页由 pathname 中的静态段驱动；「质量检查」指向文档上下文页 /documents/pipelines。
  const activeDocumentTab = location === `/w/${wid}/documents`
    ? 'structure'
    : location.startsWith(`/w/${wid}/documents/pipelines`)
      ? 'pipelines'
      : location.includes('/change-requests')
        ? 'change-requests'
        : location.includes('/issues')
          ? 'issues'
          : ''
  const activeDocumentSubpage = DOCUMENT_SUBPAGES.find(p => p.key === activeDocumentTab)

  // 设计区二级页激活态（0083 C1）：仅模块根页 /w/:wid/design 激活「设计结构」，
  // 编辑器 /w/:wid/design/:id 显示页签但无子页激活。
  const activeDesignSubpage = location === `/w/${wid}/design`
    ? DESIGN_SUBPAGES.find(p => p.key === 'structure')
    : undefined

  // ── 侧边栏形态：按当前功能段切换（需求 0065；工作区设置段折叠过渡）──
  // documents → 文档侧栏（文档树）；design → 设计侧栏（装配结构树，ADR 0084 D4）；
  // analytics / datasource / pipelines → 数据表侧栏始终展开（不再自动折叠）；
  // workspace settings → Sider 不卸载，自动折叠为图标条，
  //   减少切换时布局骨架消失的视觉冲击，返回数据表段时恢复用户原有折叠偏好；
  // 其余（数据表段）→ 维持数据表导航。未勾选数据表模块的工作区仍隐藏侧栏。
  // 表级子页 /tables/:tid/settings 不含 /settings 段前缀，不受影响。
  const inWsSettingsContext = !!wid && location.startsWith(`/w/${wid}/settings`)
  const inFocusContext = inWsSettingsContext
  type SiderMode = 'documents' | 'design' | 'tables' | 'hidden'
  const siderMode: SiderMode =
    inDocumentsContext && wsFeatures.documents
      ? 'documents'
      : inDesignContext && wsFeatures.design
        ? 'design'
        : wsFeatures.tables
          ? 'tables'
          : 'hidden'

  // 进入分析/同步/设置段时自动折叠侧栏（记住进入前的折叠偏好，离开时恢复）
  const collapsedBeforeFocusRef = useRef(false)
  // 初始化为 false：直接落在分析/同步/设置段的首屏也要走一次折叠（含首帧挂载）
  const prevInFocusRef = useRef(false)
  useEffect(() => {
    if (inFocusContext && !prevInFocusRef.current) {
      collapsedBeforeFocusRef.current = collapsed
      setCollapsed(true)
    } else if (!inFocusContext && prevInFocusRef.current) {
      setCollapsed(collapsedBeforeFocusRef.current)
    }
    prevInFocusRef.current = inFocusContext
  }, [inFocusContext, collapsed])

  // 路由变化后（含进入表/文档二级页）把激活页签滚入可视区：窄屏横滑时激活项可能在视口外。
  // 依赖页签计数徽标：徽标异步到达会改变页签宽度与整行可滚动范围，需再校准一次，
  // 否则首帧按较窄内容滚动会被 clamp 在中间位置，激活项仍露出一截。
  useEffect(
    () => scrollActiveTabIntoViewNextFrame(wsTabsRef.current),
    [location, wid, isMobile, tablesReady, tables.length, docsReady, docCount?.total],
  )

  // 模块门控：当前 URL 落在该工作区未开放的功能区（如仅勾「文档」访问 /tables）时，
  // 重定向到该工作区的落地段，避免出现空页签/空白内容（ADR 0080；质量检查恒开放）。
  useEffect(() => {
    if (!wid || !currentWs) return
    const feat = workspaceModulesFeatures(currentWs.modules)
    const inTables = location.startsWith(`/w/${wid}/tables`)
    const inDocuments = location.startsWith(`/w/${wid}/documents`)
    const inAnalytics = location.startsWith(`/w/${wid}/analytics`)
    const inDatasource = location.startsWith(`/w/${wid}/datasource`)
    const inDesign = location.startsWith(`/w/${wid}/design`)
    if (
      (!feat.tables && inTables) ||
      (!feat.documents && inDocuments) ||
      (!feat.analytics && inAnalytics) ||
      (!feat.datasource && inDatasource) ||
      (!feat.design && inDesign)
    ) {
      navigate(`/w/${wid}/${workspaceLandingSegment(currentWs.modules)}`, { replace: true })
    }
  }, [location, wid, currentWs, navigate])

  const isAdmin = !!user && (user.is_superuser || user.role === 'system_admin')

  // ── 顶栏工作区搜索 ──
  // 数据表侧的检索范围随当前激活视图收敛：表上下文 + ?view= 时把 table_id / view_id 带下去，
  // 后端仅在「数据表」范围应用视图收敛；「工作区」范围覆盖全部可读表（ADR 0015）。
  const [searchMobileOpen, setSearchMobileOpen] = useState(false)
  const viewParam = Number(searchParams.get('view'))
  const searchContext = inTableContext && tid
    ? {
      tableId: Number(tid),
      viewId: Number.isFinite(viewParam) && viewParam > 0 ? viewParam : undefined,
    }
    : { tableId: undefined, viewId: undefined }
  // 顶栏搜索三态（需求 0081 C3）：工作区上下文 = 工作区范围；无工作区上下文
  // （/w 主页、/admin、/help）= 主页模式，跨工作区检索（进入工作区前也可搜索）。
  // 移动端一律收为图标入口 + 顶部抽屉，避免挤压顶栏横向空间。
  const searchNode = isMobile ? (
    <Button
      type="text"
      icon={<SearchOutlined />}
      aria-label="搜索"
      data-testid="global-search-mobile-open"
      onClick={() => setSearchMobileOpen(true)}
    />
  ) : (
    <GlobalSearch
      workspaceId={wid ? Number(wid) : undefined}
      workspaceName={currentWs?.name}
      tableId={wid ? searchContext.tableId : undefined}
      viewId={wid ? searchContext.viewId : undefined}
    />
  )

  const onLogout = useCallback(() => {
    modal.confirm({
      title: '退出登录？',
      icon: React.createElement(ExclamationCircleOutlined),
      onOk: () => {
        logout()
        queryClient.clear()
        navigate('/login', { replace: true })
      },
    })
  }, [logout, navigate, queryClient, modal])

  const workspaceMenuItems: MenuProps['items'] = [
    { type: 'group', label: '工作区' },
    ...workspaces.map(w => ({
      key: `ws-${w.id}`,
      icon: <FolderOutlined />,
      label: (w.pinned ? '📌 ' : '') + w.name,
      onClick: () => navigate(`/w/${w.id}/${workspaceLandingSegment(w.modules)}`),
    })),
  ]

  const userMenuItems: MenuProps['items'] = [
    { key: 'user', icon: <UserOutlined />, label: user?.username || '用户', disabled: true },
    { type: 'divider' },
    { key: 'settings', icon: <SettingOutlined />, label: '个人设置', onClick: () => openSettings() },
    // 大模型设置：桌面端顶栏有常驻图标入口，移动端顶栏放不下，收进用户菜单直达页签
    ...(isMobile
      ? [
        { key: 'llm', icon: <RobotOutlined />, label: '大模型设置', onClick: () => openSettings('llm') },
        { key: 'help', icon: <QuestionCircleOutlined />, label: '帮助文档', onClick: () => navigate('/help') },
      ]
      : []),
    // 关于系统：普通用户与管理员均可见，查看版本等基本信息
    { key: 'about', icon: <InfoCircleOutlined />, label: '关于系统', onClick: () => setAboutOpen(true) },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
  ]

  /**
   * 管理台上下文（/admin）：该路径没有工作区语义，侧边栏的数据表导航在这里
   * 只剩「请先选择工作区」的空占位。此时不渲染 Sider，改由管理台页内的分区
   * 导航栏承担导航，内容区拿到整幅宽度（页头/分区栏/内容列三者的左边界因此对齐）。
   */
  const inAdminConsole = location.startsWith('/admin')
  /** 帮助文档页（/help）：无工作区语义，侧栏由帮助页自带的两级导航承担 */
  const inHelpDocs = location.startsWith('/help')

  if (!wid) {
    if (wsLoading) {
      return <div className="cn-state">加载中…</div>
    }
    // 访问 / 时，让 index route 的 <Navigate to="/w" /> 生效；访问 /w 时让 Outlet 渲染 WorkspaceList.
    // 两种情况都必须返回 <Outlet /> 所在的布局，否则子路由（包括 Navigate）根本不会挂载。
    // 无 wid 的合法路径（/、/w、/admin 等）正常渲染布局；仅对需要 wid 的 /w/... 路径重定向
    if (!location.startsWith('/w/')) {
      // 正常落到下方 return 的布局 —— Outlet 渲染子路由
    } else if (workspaces.length > 0) {
      // 访问了需要 wid 的 URL 但没带 wid → 跳到第一个工作区
      const first = workspaces[0]
      return <Navigate to={`/w/${first.id}/${workspaceLandingSegment(first.modules)}`} replace />
    } else {
      // 空工作区 + 需要 wid 的 URL（不是 / 也不是 /w）→ 跳到 /w 让用户创建
      return <Navigate to="/w" replace />
    }
  }

  /** 表导航内容 —— 桌面端 Sider 与移动端抽屉共用；mobile=true 时点击表项后自动收起抽屉.
   * collapsed 仅桌面端 Sider 折叠态使用，与既有折叠隐藏逻辑保持一致。 */
  const renderTableNav = (mobile: boolean, collapsed = false) => {
    if (!wid) {
      // 未进入工作区：不渲染"数据表"导航，提示用户从顶部选择
      return (
        <div data-testid="sider-no-workspace" className="cn-state" style={{ display: collapsed ? 'none' : 'block' }}>
          <p>请先从顶部选择一个工作区</p>
        </div>
      )
    }
    return (
      <div data-testid="sider-tables" className="cn-table-nav">
        <div style={{
          padding: 'var(--cn-space-md) var(--cn-space-lg)', borderBottom: '1px solid var(--cn-border)',
          display: collapsed ? 'none' : 'flex', alignItems: 'center', gap: 8,
        }}>
          <SearchInput placeholder="搜索表…" value={tableKeyword} onChange={e => setTableKeyword(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div style={{ padding: 'var(--cn-space-sm) var(--cn-space-lg)', fontWeight: WEIGHT.semibold, color: 'var(--cn-text-secondary)', fontSize: 12, display: collapsed ? 'none' : 'block' }}>
          数据表 ({orderedTables.length})
        </div>
        {tables.length === 0 ? (
          collapsed ? (
            <div className="cn-state">无表</div>
          ) : (
            <div className="cn-state">
              <p>还没有数据表，先创建或导入一张吧</p>
            </div>
          )
        ) : (
          <Menu
            mode="inline"
            selectedKeys={tid ? [String(tid)] : []}
            items={orderedTables.map(t => ({
              key: String(t.id),
              icon: <TableOutlined />,
              label: <span onMouseEnter={() => prefetchTable(wid!, t.id)}>{t.name}</span>,
              onClick: () => {
                navigateToTable(wid!, t.id)
                if (mobile) setMobileNavOpen(false)
              },
            }))}
          />
        )}
      </div>
    )
  }

  /** 文档导航内容 —— 文档段下 Sider 与移动端抽屉共用（需求 0065）.
   * 文档/文件夹树（与文档管理页同源 tree 端点）：点文档进编辑器，点文件夹进对应层级管理页。
   * 编辑器视图下同样显示该树并高亮当前文档（大纲仍由编辑器右侧大纲栏承担，侧栏不再显示大纲）。 */
  const renderDocumentNav = (mobile: boolean, collapsed = false) => {
    if (!wid) return null
    // 树排序（文件夹恒在前，参考 Obsidian）+ 标题过滤后转 antd 节点
    const sortedTree = sortDocTree(docTree, docSort)
    const treeData: DataNode[] = filterDocTree(sortedTree, docTreeKeyword).map(toTreeNode)
    return (
      <div data-testid="sider-documents" className="cn-table-nav">
        <div style={{
          padding: 'var(--cn-space-sm) var(--cn-space-lg)', fontWeight: WEIGHT.semibold,
          color: 'var(--cn-text-secondary)', fontSize: 12, display: 'flex',
          alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>文档</span>
        </div>
        {collapsed ? null : (
          <>
            {/* 第一行：展开/收起 + 排序 + 标题过滤（左内边距与上方「文档」标题、下方树行首同一基线） */}
            <div style={{ padding: '0 var(--cn-space-lg) var(--cn-space-sm)', display: 'flex', alignItems: 'center', gap: 6 }}>
              {/* 展开/收起全部：图标随切换变化，置于排序按钮前面 */}
              <Tooltip title={treeCollapsed ? '展开全部' : '收起全部'}>
                <Button
                  size="small"
                  icon={treeCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                  aria-label={treeCollapsed ? '展开全部文档节点' : '收起全部文档节点'}
                  data-testid="doc-tree-expand-toggle"
                  onClick={toggleTreeExpanded}
                  style={{ flexShrink: 0 }}
                />
              </Tooltip>
              <Dropdown
                menu={{
                  items: DOC_SORT_OPTIONS.map(o => ({ key: o.value, label: o.label })),
                  selectable: true,
                  selectedKeys: [sortToValue(docSort)],
                  onClick: ({ key }) => setDocSort(valueToSort(key)),
                }}
                trigger={['click']}
              >
                <Tooltip title={`排序：${describeSort(docSort)}`}>
                  <Button
                    size="small"
                    icon={<SortAscendingOutlined />}
                    aria-label={`排序方式：${describeSort(docSort)}`}
                    data-testid="doc-tree-sort"
                    style={{ flexShrink: 0 }}
                  />
                </Tooltip>
              </Dropdown>
              <SearchInput
                placeholder="过滤标题…"
                value={docTreeKeyword}
                onChange={e => setDocTitleFilter(e.target.value)}
                data-testid="doc-tree-filter"
                style={{ flex: 1, minWidth: 0 }}
              />
            </div>
            {docsTreeReady && treeData.length === 0 ? (
              <div className="cn-state">
                <p>还没有文档，去文档页创建吧</p>
              </div>
            ) : (
              // 树容器左内边距 4px：行首箭头中心线落在 12px，与「文档」标题/工具栏按钮左基线对齐
              <div style={{ padding: '0 var(--cn-space-sm) var(--cn-space-sm) var(--cn-space-xs)' }}>
                <Tree
                  blockNode
                  showIcon
                  className="cn-doc-sider-tree"
                  treeData={treeData}
                  selectedKeys={activeDocId ? [activeDocId] : []}
                  expandedKeys={docTreeExpanded}
                  onExpand={keys => setDocTreeExpanded(keys as string[])}
                  onClick={(_, node) => {
                    const raw = node as unknown as { docNode?: DocTreeNode }
                    if (!raw.docNode) return
                    if (raw.docNode.is_folder) {
                      // 进入层级时保留已选筛选（?tag=&status=）
                      const kept = new URLSearchParams()
                      for (const k of ['tag', 'status']) {
                        const v = searchParams.get(k)
                        if (v) kept.set(k, v)
                      }
                      const qs = kept.toString()
                      navigate(`/w/${wid}/documents?parent=${raw.docNode.id}${qs ? `&${qs}` : ''}`)
                    } else {
                      navigate(`/w/${wid}/documents/${raw.docNode.id}`)
                    }
                    if (mobile) setMobileNavOpen(false)
                  }}
                />
              </div>
            )}
          </>
        )}
      </div>
    )
  }

  /** 设计导航内容 —— 设计段下 Sider 与移动端抽屉共用（ADR 0084 D4）.
   * 装配树（设计 → 系统 → 组件 → 分组 → 零件），按设计懒加载 outline 端点；
   * 点设计进编辑器、点大纲节点带 ?line= 定位（ADR 0083 D7）；侧栏只读（0084 D6）。 */
  const renderDesignNav = (mobile: boolean, collapsed = false) => {
    if (!wid) return null
    return (
      <DesignStructureNav
        workspaceId={wid}
        mobile={mobile}
        collapsed={collapsed}
        onNavigate={() => setMobileNavOpen(false)}
      />
    )
  }

  return (
    <Layout style={{ height: '100vh', minHeight: 0 }}>
      <Header className="cn-app-header" style={{
        // 移动端收窄左右留白与控件间距，给搜索/导航留出横向空间
        padding: isMobile ? '0 var(--cn-space-md)' : '0 var(--cn-space-lg)',
        height: 44, lineHeight: '44px', flexShrink: 0,
        display: 'flex', alignItems: 'center', gap: isMobile ? 4 : 8,
      }}>
        {/* ── 左区（需求 0081 C1）：品牌 + 工作区切换 + 一级模块导航 ── */}
        <div className="cn-header-left">
          {/* 移动端汉堡入口：替代常驻 Sider，点击打开抽屉导航 */}
          {isMobile && (
            <Button
              type="text"
              icon={<MenuOutlined />}
              aria-label="打开导航菜单"
              data-testid="mobile-nav-btn"
              onClick={() => setMobileNavOpen(true)}
            />
          )}
          <Tooltip title="主页">
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginRight: 4, cursor: 'pointer' }}
              data-testid="home-logo"
              onClick={() => navigate('/w')}>
              <BrandMark size={24} />
              {!isMobile && (
                <>
                  <span className="cn-brand-word">晶格协同</span>
                  {systemAbout?.app_version && (
                    <span
                      className="cn-brand-version"
                      data-testid="app-version"
                      title={`应用版本 v${systemAbout.app_version}`}
                    >
                      v{systemAbout.app_version}
                    </span>
                  )}
                </>
              )}
            </div>
          </Tooltip>

          {/* 工作区下拉 —— 移动端仅显示图标，节省横向空间 */}
          <Dropdown menu={{ items: workspaceMenuItems }} trigger={['click']}>
            <Button type="text" icon={<FolderOpenOutlined />} data-testid="ws-switch-btn">
              {!isMobile && (currentWs?.name || '工作区')}
            </Button>
          </Dropdown>

          {/* 一级模块导航（需求 0081 C4）—— 数据表 / 文档 / 设计 / 工作区设置上移顶栏；
              仅桌面端渲染（移动端一级模块维持在下方页签行，C5）。
              激活态由路由段驱动：表级子页（/tables/:tid/settings 等）一律落在「数据表」，
              避免表设置页被误判为「工作区设置」；点击导航到对应段。 */}
          {!isMobile && wid && (
            <nav className="cn-header-nav" data-testid="ws-module-nav" aria-label="工作区一级功能导航">
              {headerNavItems.map(item => {
                const active = activeWsTab === item.key
                return (
                  <button
                    key={item.key}
                    type="button"
                    aria-current={active ? 'page' : undefined}
                    data-testid={`ws-nav-${item.key}`}
                    className={active ? 'cn-header-nav-item cn-header-nav-item-active' : 'cn-header-nav-item'}
                    onClick={() => navigate(`/w/${wid}/${item.key}`)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                    {item.count !== undefined && <span className="cn-ws-tab-count">{item.count}</span>}
                  </button>
                )
              })}
            </nav>
          )}
        </div>

        {/* ── 中区（需求 0081 C1/C3）：搜索框，接管剩余横向空间相对居中 ──
            GitHub 风格顶栏搜索框：工作区上下文默认范围=整个工作区，处于某张表时把
            数据表侧收敛到当前激活视图（table_id + view_id）；主页（/w）等无工作区
            上下文 = 跨工作区检索，进入工作区前也可搜索（0081 C3）。
            移动端收为图标入口并展开抽屉，避免挤压顶栏横向空间。 */}
        {isMobile ? searchNode : <div className="cn-header-search">{searchNode}</div>}

        {/* ── 右区（需求 0081 C2）：操作区维持现状 —— GitHub 风格带边框图标按钮
            （antd 默认尺寸 32px），文字说明收进 Tooltip，降低顶栏视觉密度 ── */}
        <div className="cn-header-right">
          {/* 大模型设置入口 —— 个人级连接与调用记录；桌面端常驻图标（帮助左侧），
              移动端顶栏空间紧张，入口收进用户菜单（见 userMenuItems） */}
          {!isMobile && (
            <Tooltip title="大模型设置：连接配置与调用记录">
              <Button
                icon={<RobotOutlined />}
                aria-label="大模型设置"
                data-testid="llm-settings-btn"
                onClick={() => openSettings('llm')}
              />
            </Tooltip>
          )}
          {/* 帮助文档入口（ADR 0029）—— 桌面端常驻图标，整页路由；移动端收进用户菜单 */}
          {!isMobile && (
            <Tooltip title="帮助文档与新手引导">
              <Button
                icon={<QuestionCircleOutlined />}
                aria-label="帮助文档"
                data-testid="help-btn"
                onClick={() => navigate('/help')}
              />
            </Tooltip>
          )}
          {/* 系统管理台入口 —— 仅管理员可见，置于用户头像左侧以区别于常规导航；
              /admin 上下文时以品牌色描边高亮（cn-header-icon-btn-active） */}
          {isAdmin && (
            <Tooltip title="系统管理台">
              <Button
                icon={<SafetyOutlined />}
                aria-label="管理台"
                className={location.includes('/admin') ? 'cn-header-icon-btn-active' : undefined}
                onClick={() => navigate('/admin')}
              />
            </Tooltip>
          )}
          {/* 用户下拉 —— GitHub 风格：仅头像（带边框圆形按钮），昵称收进 Tooltip */}
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <Tooltip title={user?.nickname || user?.username || ''}>
              <Button
                shape="circle"
                aria-label="用户菜单"
                data-testid="user-menu-trigger"
                style={{ padding: 0 }}
                icon={<Avatar size={22} icon={<UserOutlined />} />}
              />
            </Tooltip>
          </Dropdown>
        </div>
      </Header>

      <Layout style={{ flex: 1, minHeight: 0 }}>
        {/* 移动端不渲染常驻 Sider，改用下方抽屉导航；桌面端行为不变。
            管理台（/admin）同样不渲染：无工作区上下文，导航由管理台页内分区栏承担。
            帮助文档（/help）不渲染：导航由帮助页自带的两级侧栏承担，内容区拿整幅宽度。
            侧栏形态随功能段切换（需求 0065 / ADR 0084）：文档段=文档导航，设计段=装配结构树，
            analytics / datasource / 工作区设置段=表导航自动折叠为图标条（骨架不消失），
            无 tables 能力的类型不渲染侧栏 */}
        {!isMobile && !inAdminConsole && !inHelpDocs && siderMode !== 'hidden' && (
          <Sider
            collapsible collapsed={collapsed} onCollapse={setCollapsed}
            width={240} collapsedWidth={60}
            style={{ background: 'var(--cn-bg-container)', borderRight: '1px solid var(--cn-border)', flexShrink: 0, overflow: 'auto' }}
          >
            {siderMode === 'documents'
              ? renderDocumentNav(false, collapsed)
              : siderMode === 'design'
                ? renderDesignNav(false, collapsed)
                : renderTableNav(false, collapsed)}
          </Sider>
        )}

        <Layout style={{ flex: 1, minHeight: 0 }}>
          {/* 工作区级分页导航 —— 位于 Content 之外，跨页切换不重挂载；无工作区上下文时不渲染。
              表上下文时紧随其后以竖线分割出表级页签段：表名（品牌色表图标标识）回网格 +
              子页胶囊页签切换；激活形状分层（工作区=墨条 / 表级=胶囊）以区分导航层级 */}
          {wid && (
            <div className="cn-ws-tabs" ref={wsTabsRef} style={{
              background: 'var(--cn-bg-container)', borderBottom: '1px solid var(--cn-border)', flexShrink: 0,
              display: 'flex', alignItems: 'stretch', overflowX: 'auto',
            }}>
              {/* 文档上下文（桌面端）二级页签为空：文档区胶囊页签已承载全部入口，
                  空 Tabs 仍会渲染带内边距的空页签栏，在胶囊页签左侧留出空白，故不渲染 */}
              {wsTabItems.length > 0 && (
                <Tabs
                  activeKey={activeWsTab}
                  items={wsTabItems}
                  // 窄屏：工作区页签保持内容宽度，由整行横滑承载（否则二级页签 448px 会把
                  // 工作区页签挤成 0 宽而被裁掉，手机上看不到也切不了数据表/文档/设置）
                  style={{ flex: isMobile ? '0 0 auto' : '0 1 auto', minWidth: 0 }}
                  tabBarStyle={{ margin: 0, padding: '0 12px' }}
                  onChange={(key) => navigate(`/w/${wid}/${key}`)}
                />
              )}
              {inTableContext && (
                <div className="cn-table-crumb" data-testid="table-crumb">
                  <span className="cn-table-crumb-divider" aria-hidden />
                  <Button
                    type="text"
                    size="small"
                    data-testid="table-crumb-table"
                    style={{ paddingInline: 8 }}
                    onClick={() => navigate(`/w/${wid}/tables/${tid}`)}
                  >
                    {/* 品牌色表图标：与工作区段区分的「数据表级」视觉标识（样式见 cn-table-crumb-table） */}
                    <TableOutlined />
                    <span className="cn-table-crumb-name">{currentTable?.name || '数据表'}</span>
                  </Button>
                  {/* 表级子页页签 —— 激活态与选中项由 pathname 驱动，替代旧的 ▾ 下拉切换 */}
                  <nav className="cn-table-tabs" aria-label="表级页面切换">
                    {TABLE_SUBPAGES.map(p => {
                      const active = activeSubpage?.key === p.key
                      return (
                        <button
                          key={p.key}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          data-testid={`table-tab-${p.key}`}
                          className={active ? 'cn-table-tab cn-table-tab-active' : 'cn-table-tab'}
                          onClick={() => navigate(`/w/${wid}/tables/${tid}/${p.key}`)}
                        >
                          {p.icon}
                          {p.label}
                        </button>
                      )
                    })}
                  </nav>
                </div>
              )}
              {inDocumentsContext && (
                <div className="cn-table-crumb" data-testid="documents-crumb">
                  {/* 文档区子页页签 —— 形式与表级页签一致，作用域为工作区下全部文档 */}
                  <nav className="cn-table-tabs" aria-label="文档页面切换">
                    {DOCUMENT_SUBPAGES.map(p => {
                      const active = activeDocumentSubpage?.key === p.key
                      return (
                        <button
                          key={p.key}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          data-testid={`document-tab-${p.key}`}
                          className={active ? 'cn-table-tab cn-table-tab-active' : 'cn-table-tab'}
                          onClick={() => navigate(`/w/${wid}/documents${p.to ? `/${p.to}` : ''}`)}
                        >
                          {p.icon}
                          {p.label}
                        </button>
                      )
                    })}
                  </nav>
                </div>
              )}
              {inDesignContext && (
                <div className="cn-table-crumb" data-testid="design-crumb">
                  {/* 设计区子页页签 —— 形式与文档区一致，作用域为工作区下全部设计（0083 C1） */}
                  <nav className="cn-table-tabs" aria-label="设计页面切换">
                    {DESIGN_SUBPAGES.map(p => {
                      const active = activeDesignSubpage?.key === p.key
                      return (
                        <button
                          key={p.key}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          data-testid={`design-tab-${p.key}`}
                          className={active ? 'cn-table-tab cn-table-tab-active' : 'cn-table-tab'}
                          onClick={() => navigate(`/w/${wid}/design${p.to ? `/${p.to}` : ''}`)}
                        >
                          {p.icon}
                          {p.label}
                        </button>
                      )
                    })}
                  </nav>
                </div>
              )}
            </div>
          )}
          <Content
            key={location}
            className="cn-page-enter"
            style={{ background: 'var(--cn-bg-page)', flex: 1, minHeight: 0, overflow: 'auto' }}
          >
            {/* 懒加载页面在 Content 内挂起 —— MainLayout 保持挂载，仅内容区显示骨架，整页不再跳动 */}
            <Suspense fallback={<ContentFallback />}>
              <Outlet />
            </Suspense>
          </Content>
        </Layout>
      </Layout>

      {/* 移动端抽屉导航：替代常驻 Sider，点击条目后自动收起；内容随功能段切换（需求 0065） */}
      <Drawer
        title="导航"
        placement="left"
        open={isMobile && mobileNavOpen && siderMode !== 'hidden'}
        onClose={() => setMobileNavOpen(false)}
        size={280}
        styles={{ body: { padding: 0 } }}
      >
        {siderMode === 'documents'
          ? renderDocumentNav(true)
          : siderMode === 'design'
            ? renderDesignNav(true)
            : siderMode === 'tables' && renderTableNav(true)}
      </Drawer>

      {/* 移动端搜索：顶部抽屉承载与桌面同款搜索面板（主页模式 = 跨工作区，0081 C3） */}
      <Drawer
        title={wid ? '搜索工作区' : '搜索全部工作区'}
        placement="top"
        open={isMobile && searchMobileOpen}
        onClose={() => setSearchMobileOpen(false)}
        size="auto"
        styles={{ body: { padding: 12 } }}
        data-testid="global-search-drawer"
      >
        <div className="cn-search-in-drawer">
          <GlobalSearch
            workspaceId={wid ? Number(wid) : undefined}
            workspaceName={currentWs?.name}
            tableId={wid ? searchContext.tableId : undefined}
            viewId={wid ? searchContext.viewId : undefined}
          />
        </div>
      </Drawer>

      <Suspense fallback={<ModalFallback />}>
        <SettingsModal open={settingsOpen} initialTab={settingsTab} onClose={closeSettings} />
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />
      </Suspense>

      <Suspense fallback={<ModalFallback />}>
        <OnboardingTour />
      </Suspense>
    </Layout>
  )
}
