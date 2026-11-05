/** 顶栏统一搜索 —— GitHub 风格搜索框：范围切换 + 分组结果面板 + 命令模式.
 *
 * 口径：
 * - 默认范围是**整个工作区**（文档 FTS + 数据表行/表名），不再区分「文档页入口」；
 * - 左端范围选择器区分「全部 / 数据表 / 文档」，等价于 GitHub 搜索框里的 scope 限定词；
 * - 工作区范围覆盖全部可读表且不按视图收敛；只有「数据表」范围才收敛到当前表
 *   与激活视图（此时才下发 view_id），面板底部明示当前范围，避免「搜不到」被误读成数据丢失；
 * - 命令模式（0067）：输入以 `>` 开头时面板切换为命令列表，不发搜索请求，
 *   命令定义集中在 components/commands.ts；
 * - 主页模式（0081 C3）：不传 workspaceId 时检索范围为当前用户可访问的**全部工作区**
 *   （GET /api/v1/search），隐藏范围选择器，命中项带工作区名、点击进入对应工作区。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Dropdown, Input, Spin } from 'antd'
import type { InputRef } from 'antd'
import {
  DatabaseOutlined,
  DownOutlined,
  FileTextOutlined,
  SearchOutlined,
  TableOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { formatMeta } from '@/components/Document/docFormat'
import { searchApi } from '@/api'
import type {
  GlobalSearchResult, SearchDocumentHit, SearchRowHit, SearchScope, SearchTableHit,
  WorkspaceRef, WorkspaceSearchResult,
} from '@/api'
import { parseHitHighlight } from '@/components/Document/outline'
import { useTheme } from '@/theme/ThemeProvider'
import { useUiStore } from '@/store'
import { buildCommands } from '@/components/commands'
import type { Command } from '@/components/commands'
import { helpLink, subsectionAnchor } from '@/pages/help/helpNav'

const SCOPE_STORAGE_KEY = 'cndb:search-scope'
const MAX_ITEMS = 20
/** 主页模式（跨工作区检索）单次请求的各组命中上限（与服务端口径一致） */
const GLOBAL_LIMIT = 10

const SCOPES: { key: SearchScope; label: string; icon: React.ReactNode; hint: string }[] = [
  { key: 'all', label: '工作区', icon: <SearchOutlined />, hint: '文档与数据表一起搜' },
  { key: 'tables', label: '数据表', icon: <DatabaseOutlined />, hint: '只搜表名与表内数据' },
  { key: 'documents', label: '文档', icon: <FileTextOutlined />, hint: '只搜文档标题与正文' },
]

function readScope(): SearchScope {
  try {
    const v = localStorage.getItem(SCOPE_STORAGE_KEY)
    if (v === 'tables' || v === 'documents' || v === 'all') return v
  } catch { /* localStorage 不可用时按默认 */ }
  return 'all'
}

/** 关键词高亮：后端给 <mark> 包裹的片段，前端转成 mark 节点 */
function Highlight({ text }: { text: string }) {
  const parts = parseHitHighlight(text ?? '')
  if (parts.every(p => !p.marked)) return <>{text}</>
  return (
    <>
      {parts.map((p, i) => (p.marked ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
    </>
  )
}

interface GlobalSearchProps {
  /** 工作区 id；不传 = 主页模式（跨工作区检索，需求 0081 C3） */
  workspaceId?: number
  workspaceName?: string
  /** 当前激活表 / 视图（不在表上下文中则不传；主页模式无此概念） */
  tableId?: number
  viewId?: number
}

/** 两种模式的命中都带可选工作区归属：工作区模式下由 props 兜底填充 */
type DocHit = import('@/api').SearchDocumentHit & Partial<WorkspaceRef>
type TableHit = import('@/api').SearchTableHit & Partial<WorkspaceRef>
type RowHit = import('@/api').SearchRowHit & Partial<WorkspaceRef>

type PanelItem =
  | { kind: 'doc'; key: string; id: number; wsId: number }
  | { kind: 'table'; key: string; id: number; wsId: number }
  | { kind: 'row'; key: string; tableId: number; rowId: number | null; wsId: number }

export default function GlobalSearch({ workspaceId, workspaceName, tableId, viewId }: GlobalSearchProps) {
  const navigate = useNavigate()
  // 主页模式：无工作区上下文（/w、/admin、/help 等），检索范围为全部可访问工作区
  const isGlobal = workspaceId === undefined
  const [scope, setScope] = useState<SearchScope>(readScope)
  const [input, setInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<InputRef>(null)
  // 命令模式依赖（0067）：主题与设置弹窗 setter 经 commands.ts 注册表执行
  const { setMode: setThemeMode } = useTheme()
  const openSettings = useUiStore(s => s.openSettings)

  // ── 命令模式（输入以 `>` 开头）：本地过滤，不发搜索请求（C1/C7）──
  const isCommandMode = input.startsWith('>')
  const commandCtx = useMemo(
    () => ({ navigate, workspaceId, openSettings, setThemeMode }),
    [navigate, workspaceId, openSettings, setThemeMode],
  )
  const commandKeyword = isCommandMode ? input.slice(1).trim().toLowerCase() : ''
  const commands = useMemo(() => {
    const all = buildCommands(commandCtx)
    return all
      // 无工作区上下文（/admin、/help 等）剔除需 wid 的命令（0067 C3）
      .filter(c => !c.needsWorkspace || Number.isFinite(workspaceId))
      .filter(c => !commandKeyword
        || c.title.toLowerCase().includes(commandKeyword)
        || (c.keywords ?? '').toLowerCase().includes(commandKeyword))
  }, [commandCtx, commandKeyword, workspaceId])

  // 输入去抖：每敲一个字就打后端代价过高（表行检索会扫动态表）；
  // 命令模式输入以 `>` 开头，不落 keyword（也就不会触发搜索 query，C1）
  useEffect(() => {
    const timer = window.setTimeout(() => setKeyword(isCommandMode ? '' : input.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [input, isCommandMode])

  useEffect(() => {
    try { localStorage.setItem(SCOPE_STORAGE_KEY, scope) } catch { /* ignore */ }
  }, [scope])

  const query = useQuery<WorkspaceSearchResult | GlobalSearchResult>({
    // 主页模式走跨工作区端点；工作区模式沿用既有键结构（视图收敛只属于「数据表」范围）
    queryKey: isGlobal
      ? ['global-search', keyword]
      : [
        'workspace-search',
        workspaceId,
        keyword,
        scope,
        tableId ?? null,
        scope === 'tables' ? (viewId ?? null) : null,
      ],
    queryFn: (): Promise<WorkspaceSearchResult | GlobalSearchResult> => isGlobal
      ? searchApi.global({ q: keyword, limit: GLOBAL_LIMIT })
      : searchApi.workspace(workspaceId!, {
        q: keyword,
        scope,
        table_id: tableId,
        view_id: scope === 'tables' ? viewId : undefined,
        limit: 10,
      }),
    enabled: keyword.length > 0 && (isGlobal || Number.isFinite(workspaceId!)),
    staleTime: 10_000,
    placeholderData: (prev: WorkspaceSearchResult | GlobalSearchResult | undefined) => prev,
  })

  const data: WorkspaceSearchResult | GlobalSearchResult | undefined = keyword ? query.data : undefined

  // ── 键盘：Ctrl/⌘+K 聚焦，/ 聚焦，Esc 收起，↑↓ 选择，回车打开 ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing = !!target && (
        target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
      )
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        return
      }
      if (!typing && e.key === '/') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 三个分组各自 memo：否则 ?? [] 每次渲染产生新数组，令下方 items 的 useMemo 失效。
  // 工作区模式的命中不带工作区字段，用 props 兜底填充，两种模式共用同一渲染路径
  const docHits = useMemo<DocHit[]>(
    () => ((data?.documents ?? []) as Array<SearchDocumentHit & Partial<WorkspaceRef>>).map(d => ({
      ...d,
      workspace_id: d.workspace_id ?? workspaceId!,
      workspace_name: d.workspace_name ?? workspaceName ?? '',
    })),
    [data, workspaceId, workspaceName],
  )
  const tableHits = useMemo<TableHit[]>(
    () => ((data?.tables ?? []) as Array<SearchTableHit & Partial<WorkspaceRef>>).map(t => ({
      ...t,
      workspace_id: t.workspace_id ?? workspaceId!,
      workspace_name: t.workspace_name ?? workspaceName ?? '',
    })),
    [data, workspaceId, workspaceName],
  )
  const rowHits = useMemo<RowHit[]>(
    () => ((data?.rows ?? []) as Array<SearchRowHit & Partial<WorkspaceRef>>).map(r => ({
      ...r,
      workspace_id: r.workspace_id ?? workspaceId!,
      workspace_name: r.workspace_name ?? workspaceName ?? '',
    })),
    [data, workspaceId, workspaceName],
  )

  const items: PanelItem[] = useMemo(() => [
    ...tableHits.map(t => ({ kind: 'table' as const, key: `table-${t.id}`, id: t.id, wsId: t.workspace_id! })),
    ...rowHits.map(r => ({
      kind: 'row' as const,
      key: `row-${r.table_id}-${r.row_id}`,
      tableId: r.table_id,
      rowId: r.row_id,
      wsId: r.workspace_id!,
    })),
    ...docHits.map(d => ({ kind: 'doc' as const, key: `doc-${d.id}`, id: d.id, wsId: d.workspace_id! })),
  ].slice(0, MAX_ITEMS), [tableHits, rowHits, docHits])

  // 键盘导航统一行数：命令模式走 commands，搜索模式走 items（0067 C4）
  const navCount = isCommandMode ? commands.length : items.length
  useEffect(() => { setActiveIndex(navCount > 0 ? 0 : -1) }, [navCount])

  const close = useCallback(() => {
    setOpen(false)
    setActiveIndex(-1)
  }, [])

  const openItem = useCallback((item: PanelItem) => {
    close()
    setInput('')
    setKeyword('')
    // 主页模式从命中项取归属工作区；工作区模式下即当前工作区
    const wid = item.wsId
    if (item.kind === 'doc') navigate(`/w/${wid}/documents/${item.id}`)
    else if (item.kind === 'table') navigate(`/w/${wid}/tables/${item.id}`)
    else if (item.rowId != null) navigate(`/w/${wid}/tables/${item.tableId}?row=${item.rowId}`)
    else navigate(`/w/${wid}/tables/${item.tableId}`)
    inputRef.current?.blur()
  }, [close, navigate])

  const runCommand = useCallback((cmd: Command) => {
    close()
    setInput('')
    setKeyword('')
    cmd.run(commandCtx)
    inputRef.current?.blur()
  }, [close, commandCtx])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { close(); inputRef.current?.blur(); return }
    if (navCount === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex(i => (i + 1) % navCount)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex(i => (i - 1 + navCount) % navCount)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const i = activeIndex >= 0 ? activeIndex : 0
      if (isCommandMode) {
        const cmd = commands[i]
        if (cmd) runCommand(cmd)
      } else {
        const item = items[i]
        if (item) openItem(item)
      }
    }
  }

  /** 点面板外部收起（面板是绝对定位的自绘层，不依赖 Dropdown 的受控逻辑） */
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, close])

  const scopeMeta = SCOPES.find(s => s.key === scope) ?? SCOPES[0]
  // 数据表侧的实际检索范围：表上下文 + 激活视图时只搜该视图（主页模式无视图收敛）
  const viewScope = !isGlobal && data && 'view' in data ? data.view : null
  const scopeNote = viewScope
    ? viewScope.name
      ? `${viewScope.table_name} · 视图「${viewScope.name}」`
      : `${viewScope.table_name} · 整表`
    : null

  const hasResult = items.length > 0
  // 命令模式即时显示（本地过滤不等去抖）；搜索模式保持 keyword 有值才出面板
  const showPanel = open && (isCommandMode || keyword.length > 0)

  let idx = -1
  const nextIndex = () => { idx += 1; return idx }
  const isActive = (key: string) => !isCommandMode && items[activeIndex]?.key === key
  // 主页模式命中项的副行带工作区名前缀（工作区模式下冗余，不显示）
  const wsPrefix = (name?: string) => (isGlobal && name ? `${name} · ` : '')

  return (
    <div className="cn-global-search" ref={wrapRef} data-testid="global-search">
      <div className={showPanel ? 'cn-gs-box cn-gs-box-open' : 'cn-gs-box'}>
        {/* 范围选择器只属于工作区模式：主页跨工作区检索恒为「文档 + 数据表」全部（0081 C3） */}
        {!isGlobal && (
          <Dropdown
            trigger={['click']}
            placement="bottomLeft"
            menu={{
              selectable: true,
              selectedKeys: [scope],
              items: SCOPES.map(s => ({
                key: s.key,
                icon: s.icon,
                label: (
                  <span className="cn-gs-scope-item">
                    <span>{s.label}</span>
                    <span className="cn-gs-scope-hint">{s.hint}</span>
                  </span>
                ),
              })),
              onClick: ({ key }) => setScope(key as SearchScope),
            }}
          >
            <button
              type="button"
              className="cn-gs-scope"
              data-testid="global-search-scope"
              aria-label={`搜索范围：${scopeMeta.label}`}
            >
              {scopeMeta.icon}
              <span className="cn-gs-scope-label">{scopeMeta.label}</span>
              <DownOutlined className="cn-gs-scope-arrow" />
            </button>
          </Dropdown>
        )}

        <Input
          ref={inputRef}
          variant="borderless"
          className="cn-gs-input"
          data-testid="global-search-input"
          placeholder={isGlobal
            ? '搜索全部工作区，输入 > 执行命令…'
            : workspaceName
              ? `搜索「${workspaceName}」，输入 > 执行命令…`
              : '搜索工作区，输入 > 执行命令…'}
          value={input}
          onChange={e => { setInput(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          prefix={<SearchOutlined className="cn-gs-icon" />}
          suffix={input ? null : <kbd className="cn-gs-kbd">Ctrl K</kbd>}
          aria-label={isGlobal ? '搜索全部工作区' : '搜索工作区'}
        />
      </div>

      {showPanel && (
        <div className="cn-gs-panel" data-testid="global-search-panel" role="listbox">
          {/* 命令模式（0067 C1）：`>` 前缀 → 命令列表，替代搜索分组 */}
          {isCommandMode && (
            <>
              <div className="cn-gs-group">
                <div className="cn-gs-group-title">
                  <ThunderboltOutlined /> 命令
                  <span className="cn-gs-count">{commands.length}</span>
                </div>
                {commands.length === 0 && (
                  <div className="cn-gs-state" data-testid="global-search-command-empty">
                    无匹配命令
                  </div>
                )}
                {commands.map((cmd, i) => (
                  <button
                    key={cmd.key}
                    type="button"
                    role="option"
                    aria-selected={i === activeIndex}
                    data-testid={`global-search-command-${cmd.key}`}
                    className={i === activeIndex ? 'cn-gs-item cn-gs-item-active' : 'cn-gs-item'}
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => runCommand(cmd)}
                  >
                    <ThunderboltOutlined className="cn-gs-item-icon" />
                    <span className="cn-gs-item-main">
                      <span className="cn-gs-item-title">{cmd.title}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="cn-gs-footer">
                <span>命令模式</span>
                <span className="cn-gs-footer-keys">↑↓ 选择 · Enter 执行 · Esc 关闭</span>
              </div>
            </>
          )}

          {!isCommandMode && query.isFetching && !data && (
            <div className="cn-gs-state"><Spin size="small" /> 搜索中…</div>
          )}

          {!isCommandMode && !hasResult && !query.isFetching && (
            <div className="cn-gs-state cn-gs-state-empty" data-testid="global-search-empty">
              <span>没有找到与「{keyword}」相关的内容</span>
              <span className="cn-gs-state-hint">
                换个关键词，或在左侧范围里切到「数据表 / 文档」再试一次。
              </span>
              <Link
                className="cn-gs-state-link"
                to={helpLink('tutorials', 'search', subsectionAnchor('global'))}
                data-testid="global-search-help-link"
                onClick={close}
              >
                查看「搜索范围」怎么选
              </Link>
            </div>
          )}

          {!isCommandMode && tableHits.length > 0 && (
            <div className="cn-gs-group">
              <div className="cn-gs-group-title">
                <TableOutlined /> 数据表
                <span className="cn-gs-count">{tableHits.length}</span>
              </div>
              {tableHits.map(t => {
                const i = nextIndex()
                return (
                  <button
                    key={`table-${t.id}`}
                    type="button"
                    role="option"
                    aria-selected={isActive(`table-${t.id}`)}
                    data-testid={`global-search-table-${t.id}`}
                    className={i === activeIndex ? 'cn-gs-item cn-gs-item-active' : 'cn-gs-item'}
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => openItem({ kind: 'table', key: `table-${t.id}`, id: t.id, wsId: t.workspace_id! })}
                  >
                    <TableOutlined className="cn-gs-item-icon" />
                    <span className="cn-gs-item-main">
                      <span className="cn-gs-item-title">{t.name}</span>
                      {(isGlobal || t.description) && (
                        <span className="cn-gs-item-sub">{wsPrefix(t.workspace_name)}{t.description}</span>
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {!isCommandMode && rowHits.length > 0 && (
            <div className="cn-gs-group">
              <div className="cn-gs-group-title">
                <DatabaseOutlined /> 表内数据
                <span className="cn-gs-count">{rowHits.length}</span>
              </div>
              {rowHits.map(r => {
                const key = `row-${r.table_id}-${r.row_id}`
                const i = nextIndex()
                return (
                  <button
                    key={key}
                    type="button"
                    role="option"
                    aria-selected={isActive(key)}
                    data-testid={`global-search-row-${r.table_id}-${r.row_id}`}
                    className={i === activeIndex ? 'cn-gs-item cn-gs-item-active' : 'cn-gs-item'}
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => openItem({ kind: 'row', key, tableId: r.table_id, rowId: r.row_id, wsId: r.workspace_id! })}
                  >
                    <DatabaseOutlined className="cn-gs-item-icon" />
                    <span className="cn-gs-item-main">
                      <span className="cn-gs-item-title"><Highlight text={r.title} /></span>
                      <span className="cn-gs-item-sub">{wsPrefix(r.workspace_name)}{r.table_name} · {r.snippet}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {!isCommandMode && docHits.length > 0 && (
            <div className="cn-gs-group">
              <div className="cn-gs-group-title">
                <FileTextOutlined /> 文档
                <span className="cn-gs-count">{docHits.length}</span>
              </div>
              {docHits.map(d => {
                const i = nextIndex()
                return (
                  <button
                    key={`doc-${d.id}`}
                    type="button"
                    role="option"
                    aria-selected={isActive(`doc-${d.id}`)}
                    data-testid={`global-search-doc-${d.id}`}
                    className={i === activeIndex ? 'cn-gs-item cn-gs-item-active' : 'cn-gs-item'}
                    onMouseEnter={() => setActiveIndex(i)}
                    onClick={() => openItem({ kind: 'doc', key: `doc-${d.id}`, id: d.id, wsId: d.workspace_id! })}
                  >
                    {(() => {
                      const fmt = formatMeta(d.content_type)
                      const FormatIcon = fmt.Icon
                      return (
                        <FormatIcon
                          className="cn-gs-item-icon"
                          aria-label={`格式：${fmt.label}`}
                          style={{ color: fmt.color }}
                        />
                      )
                    })()}
                    <span className="cn-gs-item-main">
                      <span className="cn-gs-item-title"><Highlight text={d.title_hit || d.title} /></span>
                      <span className="cn-gs-item-sub">{wsPrefix(d.workspace_name)}<Highlight text={d.summary_hit || ''} /></span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {!isCommandMode && (
            <div className="cn-gs-footer">
              <span>范围：{isGlobal ? '全部工作区' : `${scopeMeta.label}${scopeNote ? ` · ${scopeNote}` : ''}`}</span>
              <span className="cn-gs-footer-keys">↑↓ 选择 · Enter 打开 · Esc 关闭</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
