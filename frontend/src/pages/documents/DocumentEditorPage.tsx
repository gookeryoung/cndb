/** 文档编辑页 — 分屏编辑/预览 + 版本历史 + 标签 + 乐观锁保存. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Breadcrumb,
  Button,
  Drawer,
  Dropdown,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Splitter,
  Tag,
  Typography,
  message,
} from 'antd'
import type { TextAreaRef } from 'antd/es/input/TextArea'
import {
  BranchesOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  HistoryOutlined,
  LinkOutlined,
  MenuOutlined,
  MoreOutlined,
  PictureOutlined,
  PullRequestOutlined,
  SaveOutlined,
  SearchOutlined,
  TableOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import FindReplaceBar from '@/components/Document/FindReplaceBar'
import { ancestorChain } from './DocumentTree'
import { pushRecentDoc } from './recentDocs'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import MarkdownToolbar, { type MarkdownAction } from '@/components/Document/MarkdownToolbar'
import { findMatches, nextMatchIndex, replaceAllMatches, replaceMatch } from '@/components/Document/documentSearch'
import { documentStats, formatStatsLabel } from '@/components/Document/documentStats'
import { buildImageSnippet, isImageFile } from '@/components/Document/imageRef'
import { insertLink, wrapSelection } from '@/components/Document/markdownEdit'
import { parseOutline } from '@/components/Document/outline'
import { documentsApi, isChangeRequestDispatch } from '@/api/documents'
import { fileApi, tableApi, workspaceApi } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
import type { WorkspaceRole } from '@/api'
import type {
  DocumentChangeRequestDispatch,
  DocumentDetail,
  DocumentExportFormat,
  DocumentItem,
  OutgoingLinkItem,
  VersionItem,
} from '@/api/documents'

const { Text, Title } = Typography
const { TextArea } = Input


import BacklinksDrawer from './BacklinksDrawer'
import DocumentChangeRequestsDrawer from './DocumentChangeRequestsDrawer'
import InsertTableModal from './InsertTableModal'
import LinksDrawer from './LinksDrawer'
import OutlineDrawer from './OutlineDrawer'
import VersionsDrawer from './VersionsDrawer'
import TagEditor from './TagEditor'

export default function DocumentEditorPage() {
  const { wid, docId } = useParams<{ wid: string; docId: string }>()
  const { isMobile } = useResponsive()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const id = Number(docId)

  const [content, setContent] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [tagsOpen, setTagsOpen] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(false)
  /** 窄屏（<768px）编辑/预览二选一：左右分栏在 390px 屏上每侧仅约 190px，正文换行严重 */
  const [mobilePane, setMobilePane] = useState<'edit' | 'preview'>('edit')
  const [backlinksOpen, setBacklinksOpen] = useState(false)
  const [linksOpen, setLinksOpen] = useState(false)
  // 断链修复：旧标题 → 选中的目标文档 ID
  const [repairTargets, setRepairTargets] = useState<Record<string, number>>({})
  const [diffPair, setDiffPair] = useState<{ base: number; head: number } | null>(null)
  const [crOpen, setCrOpen] = useState(false)
  /** 保存被转为修改申请时的提示（正文未落库，等待审核） */
  const [pendingNotice, setPendingNotice] = useState<string | null>(null)
  // 查找 / 替换（Ctrl+F / Ctrl+H 打开，Esc 关闭）
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [replaceText, setReplaceText] = useState('')
  const [findCaseSensitive, setFindCaseSensitive] = useState(false)
  /** 当前定位到的匹配下标（-1 = 尚未定位） */
  const [matchIndex, setMatchIndex] = useState(-1)
  const baseTsRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)
  const taRef = useRef<TextAreaRef>(null)

  // 插入数据表引用辅助
  const [insertOpen, setInsertOpen] = useState(false)
  const [insertTableId, setInsertTableId] = useState<number | null>(null)
  const [insertLimit, setInsertLimit] = useState<number | null>(null)

  // 当前用户在工作区的角色：决定修改申请抽屉里的审核入口
  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId),
    enabled: Number.isFinite(workspaceId),
  })
  const myRole = (wsDetail?.current_user_role ?? null) as WorkspaceRole | null

  // 该文档的修改申请（与抽屉共享缓存）：工具栏徽标显示待审核条数
  const { data: crList } = useQuery({
    queryKey: ['document-change-requests', workspaceId, id, 'all'],
    queryFn: () => documentsApi.changeRequests(workspaceId, { document_id: id, scope: 'all' }),
    enabled: Number.isFinite(workspaceId) && Number.isFinite(id),
  })
  const pendingCrCount = (crList?.items ?? []).filter(cr => cr.status === 'open').length

  const tablesQuery = useQuery({
    queryKey: ['tables', workspaceId, 'embed-options'],
    queryFn: () => tableApi.list(workspaceId),
    enabled: insertOpen,
  })

  const docQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'content'],
    queryFn: () => documentsApi.getContent(workspaceId, id),
    enabled: Number.isFinite(workspaceId) && Number.isFinite(id),
  })

  // 载入文档内容 + 版本戳
  useEffect(() => {
    const doc = docQuery.data
    if (doc) {
      setContent(doc.content)
      baseTsRef.current = doc.updated_at
      dirtyRef.current = false
    }
  }, [docQuery.data])

  const saveMut = useMutation({
    mutationFn: (text: string) =>
      documentsApi.updateContent(workspaceId, id, {
        content: text,
        base_updated_at: baseTsRef.current,
        base_version_number: docQuery.data?.version_number ?? null,
      }),
    onSuccess: (result: DocumentDetail | DocumentChangeRequestDispatch) => {
      // 双轨制：无直编资格时保存转为修改申请，正文未落库
      if (isChangeRequestDispatch(result)) {
        dirtyRef.current = false
        setSaveError(null)
        setPendingNotice(result.message)
        void qc.invalidateQueries({ queryKey: ['document-change-requests', workspaceId, id] })
        return
      }
      baseTsRef.current = result.updated_at
      dirtyRef.current = false
      setSaveError(null)
      setPendingNotice(null)
      message.success(`已保存 v${result.version_number ?? '?'}`)
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '保存失败'
      setSaveError(detail)
    },
  })

  // 导出文档：Markdown / Word / PDF（浏览器直接下载）
  const exportMut = useMutation({
    mutationFn: (format: DocumentExportFormat) => documentsApi.exportFile(workspaceId, id, format),
    onSuccess: (blob: Blob, format: DocumentExportFormat) => {
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${docQuery.data?.title || 'document'}_${ts}.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('已导出')
    },
    onError: () => message.error('导出失败'),
  })

  const tagsQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tags'],
    queryFn: () => documentsApi.tags(workspaceId),
    enabled: tagsOpen,
  })

  // 反向链接：谁在正文中引用了 [[本文档标题]]（打开抽屉时拉取）
  const backlinksQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'backlinks'],
    queryFn: () => documentsApi.backlinks(workspaceId, id),
    enabled: backlinksOpen && Number.isFinite(workspaceId) && Number.isFinite(id),
  })

  // 出链：正文 [[标题]] 的命中与断链（打开抽屉时拉取）
  const linksQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'links'],
    queryFn: () => documentsApi.links(workspaceId, id),
    enabled: linksOpen && Number.isFinite(workspaceId) && Number.isFinite(id),
  })

  // 断链修复目标候选：工作区文档树（与文档页共享同一缓存 key）
  const linkTargetsQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tree'],
    queryFn: () => documentsApi.tree(workspaceId),
    enabled: linksOpen && Number.isFinite(workspaceId),
  })

  const repairMut = useMutation({
    mutationFn: () => {
      const repairs = (linksQuery.data?.items ?? [])
        .filter((item: OutgoingLinkItem) => item.broken && repairTargets[item.title] != null)
        .map((item: OutgoingLinkItem) => ({
          title: item.title,
          target_document_id: repairTargets[item.title],
        }))
      return documentsApi.repairLinks(workspaceId, id, repairs)
    },
    onSuccess: result => {
      message.success(`已修复 ${result.replaced} 处链接，生成 v${result.version_number}`)
      setRepairTargets({})
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '链接修复失败'
      message.error(detail)
    },
  })

  const versionsQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'versions'],
    queryFn: () => documentsApi.versions(workspaceId, id),
    enabled: versionsOpen,
  })

  const diffQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'diff', diffPair?.base, diffPair?.head],
    queryFn: () => documentsApi.diff(workspaceId, id, diffPair!.base, diffPair!.head),
    enabled: diffPair !== null,
  })

  const rollbackMut = useMutation({
    mutationFn: (target: number) => documentsApi.rollback(workspaceId, id, target),
    onSuccess: (_doc, target) => {
      message.success(`已回滚到 v${target}`)
      setVersionsOpen(false)
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
    },
    onError: () => message.error('回滚失败'),
  })

  const setDocTagsMut = useMutation({
    mutationFn: (tagIds: number[]) => documentsApi.setDocTags(workspaceId, id, tagIds),
    onSuccess: () => {
      message.success('标签已更新')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
    },
  })

  const doc = docQuery.data

  const handleSave = useCallback(() => {
    saveMut.mutate(content)
  }, [content, saveMut])

  /** 当前文档所在路径（祖先链，去掉自身）：复用与文档树相同的 React Query 缓存 key */
  const treeQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tree'],
    queryFn: () => documentsApi.tree(workspaceId),
    enabled: Number.isFinite(workspaceId),
  })

  const pathItems = useMemo(() => {
    const chain = ancestorChain(treeQuery.data ?? [], id)
    const segments = chain.slice(0, -1)
    return [
      { key: 'root', title: <a onClick={() => navigate(`/w/${wid}/documents`)}>文档</a> },
      ...segments.map(node => ({
        key: String(node.id),
        title: <a onClick={() => navigate(`/w/${wid}/documents?parent=${node.id}`)}>{node.title}</a>,
      })),
    ]
  }, [treeQuery.data, id, navigate, wid])

  // 记录「最近打开」：文档加载完成后写入本地历史（个人浏览偏好，按工作区分键）
  useEffect(() => {
    if (!doc || doc.is_folder) return
    pushRecentDoc(workspaceId, { id: doc.id, title: doc.title })
  }, [doc, workspaceId])

  /** 正文统计（字数 / 行数 / 预计阅读时长） */
  const stats = useMemo(() => documentStats(content), [content])

  /** 全部匹配（随正文 / 查询 / 大小写开关实时重算） */
  const findMatchesList = useMemo(
    () => findMatches(content, findQuery, { caseSensitive: findCaseSensitive }),
    [content, findQuery, findCaseSensitive],
  )

  /** 选中并滚动到指定区间（textarea 聚焦后设置选区会自动将其卷入可视区） */
  const focusRange = useCallback((start: number, end: number) => {
    requestAnimationFrame(() => {
      const node = taRef.current?.resizableTextArea?.textArea
      if (!node) return
      node.focus()
      node.setSelectionRange(start, end)
    })
  }, [])

  /** 定位到第 index 个匹配 */
  const selectMatch = useCallback((index: number) => {
    const m = findMatchesList[index]
    if (!m) return
    setMatchIndex(index)
    focusRange(m.start, m.end)
  }, [findMatchesList, focusRange])

  /** 打开查找条；若编辑器中有选中文本（且不含换行）则作为查询词 */
  const openFind = useCallback(() => {
    const node = taRef.current?.resizableTextArea?.textArea
    const selected = node && node.selectionEnd > node.selectionStart
      ? content.slice(node.selectionStart, node.selectionEnd)
      : ''
    if (selected && !selected.includes('\n') && selected.length <= 200) setFindQuery(selected)
    setFindOpen(true)
  }, [content])

  const closeFind = useCallback(() => {
    setFindOpen(false)
    setMatchIndex(-1)
    requestAnimationFrame(() => taRef.current?.resizableTextArea?.textArea?.focus())
  }, [])

  /** 上一个 / 下一个匹配（从当前光标位置起算，越界环绕） */
  const stepMatch = useCallback((direction: 1 | -1) => {
    if (findMatchesList.length === 0) return
    const node = taRef.current?.resizableTextArea?.textArea
    const caret = node?.selectionEnd ?? 0
    const idx = nextMatchIndex(findMatchesList, caret, direction)
    if (idx >= 0) selectMatch(idx)
  }, [findMatchesList, selectMatch])

  /** 替换当前匹配，并自动跳到下一处（与常见编辑器行为一致） */
  const handleReplaceOne = useCallback(() => {
    const node = taRef.current?.resizableTextArea?.textArea
    const caret = node?.selectionEnd ?? 0
    const idx = matchIndex >= 0 && findMatchesList[matchIndex] ? matchIndex : nextMatchIndex(findMatchesList, caret, 1)
    const target = findMatchesList[idx]
    if (!target) return
    const replaced = replaceMatch(content, target, replaceText)
    setContent(replaced.value)
    dirtyRef.current = true
    const after = findMatches(content, findQuery, { caseSensitive: findCaseSensitive })
    const nextIdx = nextMatchIndex(after, replaced.caret, 1)
    const nextMatch = after[nextIdx]
    setMatchIndex(nextIdx)
    focusRange(nextMatch?.start ?? replaced.caret, nextMatch?.end ?? replaced.caret)
  }, [content, matchIndex, findMatchesList, replaceText, findQuery, findCaseSensitive, focusRange])

  /** 全部替换（字面量替换，空结果不做改动） */
  const handleReplaceAll = useCallback(() => {
    const result = replaceAllMatches(content, findQuery, replaceText, { caseSensitive: findCaseSensitive })
    if (result.count === 0) {
      message.info('没有可替换的内容')
      return
    }
    setContent(result.value)
    dirtyRef.current = true
    setMatchIndex(-1)
    message.success(`已替换 ${result.count} 处`)
  }, [content, findQuery, replaceText, findCaseSensitive])

  /** 应用一次 Markdown 语法操作：以 textarea 当前选区为准，写回后恢复焦点与光标 */
  const applyMarkdownAction = useCallback((action: MarkdownAction) => {
    const node = taRef.current?.resizableTextArea?.textArea
    const start = node?.selectionStart ?? content.length
    const end = node?.selectionEnd ?? start
    const result = action(content, start, end)
    if (result.value === content) return
    setContent(result.value)
    dirtyRef.current = true
    // 受控组件重渲染后再恢复选区（否则光标会跳到末尾）
    requestAnimationFrame(() => {
      const next = taRef.current?.resizableTextArea?.textArea
      if (!next) return
      next.focus()
      next.setSelectionRange(result.selectionStart, result.selectionEnd)
    })
  }, [content])

  /** 编辑区快捷键：Ctrl/Cmd+B 加粗、Ctrl/Cmd+I 斜体、Ctrl/Cmd+K 链接（Ctrl+S 由全局处理） */
  const handleEditorKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape' && findOpen) {
      e.preventDefault()
      closeFind()
      return
    }
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return
    const key = e.key.toLowerCase()
    if (key === 'f') {
      // 接管浏览器查找：打开文档内查找替换
      e.preventDefault()
      openFind()
    } else if (key === 'h') {
      e.preventDefault()
      openFind()
    } else if (key === 'b') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => wrapSelection(v, s, en, '**'))
    } else if (key === 'i') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => wrapSelection(v, s, en, '*'))
    } else if (key === 'k') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => insertLink(v, s, en))
    }
  }, [applyMarkdownAction, findOpen, closeFind, openFind])

  /** 在光标处插入独占段落的片段（前后自动补空行）；图片 / 数据表引用共用.
   *
   * 用函数式更新：连续插入（如一次粘贴多张图片）时各自基于最新正文计算，不会互相覆盖。
   */
  const insertSnippetAtCursor = useCallback((snippet: string) => {
    const el = taRef.current?.resizableTextArea?.textArea
    const pos = el?.selectionStart ?? null
    const end = el?.selectionEnd ?? pos
    setContent(prev => {
      const start = pos ?? prev.length
      const stop = end ?? start
      const before = prev.slice(0, start)
      const after = prev.slice(stop)
      const prefix = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''
      const suffix = after && !after.startsWith('\n\n') ? (after.startsWith('\n') ? '\n' : '\n\n') : ''
      return `${before}${prefix}${snippet}${suffix}${after}`
    })
    dirtyRef.current = true
  }, [])

  // 在光标位置插入数据表引用占位符（前后自动补空行保证独占段落）
  const insertTableRef = () => {
    if (insertTableId === null) return
    insertSnippetAtCursor(`{{table:${insertTableId}${insertLimit ? `|limit=${insertLimit}` : ''}}}`)
    setInsertOpen(false)
    setInsertTableId(null)
    setInsertLimit(null)
  }

  // ── 插入图片：上传到工作区文件存储，正文写入站内引用 `![alt](file:<key>)` ──
  const imageInputRef = useRef<HTMLInputElement>(null)

  const imageMut = useMutation({
    mutationFn: (file: File) => fileApi.upload(workspaceId, file),
    onSuccess: (res, file) => {
      insertSnippetAtCursor(buildImageSnippet(file.name, res.file_key))
      message.success('图片已插入（保存后生效）')
    },
    onError: () => message.error('图片上传失败'),
  })

  /** 串行上传队列：多次选择 / 一次粘贴多张时，按顺序插入正文且互不覆盖 */
  const uploadQueueRef = useRef<Promise<void>>(Promise.resolve())

  const enqueueImageUpload = useCallback((file: File) => {
    uploadQueueRef.current = uploadQueueRef.current
      .then(() => imageMut.mutateAsync(file).then(() => undefined))
      .catch(() => {
        // onError 已统一提示，这里只保证队列不中断
      })
  }, [imageMut])

  const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // 复位 input：允许连续选择同一文件
    e.target.value = ''
    if (!file) return
    if (!isImageFile(file)) {
      message.error('仅支持图片文件（png / jpg / gif / webp / svg 等）')
      return
    }
    enqueueImageUpload(file)
  }

  /** 编辑器内粘贴：剪贴板含图片时直接上传并插入引用，普通文本粘贴不受影响 */
  const handleEditorPaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files: File[] = []
    for (const item of Array.from(items)) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length === 0) return
    // 阻止默认：否则会把图片当文件粘贴，浏览器可能插入文件名文本
    e.preventDefault()
    for (const file of files) enqueueImageUpload(file)
  }, [enqueueImageUpload])

  // Ctrl/Cmd+S 保存
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleSave()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleSave])

  // 大纲：从当前内容实时解析（不依赖保存后的 toc_json），点击定位预览区锚点
  const outline = useMemo(() => parseOutline(content), [content])

  const scrollToAnchor = useCallback((anchor: string) => {
    // 窄屏预览在独立面板：先切过去，等面板渲染后再滚动定位
    setMobilePane('preview')
    requestAnimationFrame(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  // 双向链接跳转：按标题在工作区文档树中定位目标文档（无缓存时现场拉取树）
  const handleWikilink = useCallback(
    (title: string) => {
      const key = ['documents', workspaceId, 'tree'] as const
      const cached = qc.getQueryData<DocumentItem[]>([...key])
      const resolve = (tree: DocumentItem[]) => {
        const hit = tree.find(d => !d.is_folder && d.title === title)
        if (hit) {
          navigate(`/w/${workspaceId}/documents/${hit.id}`)
        } else {
          message.warning(`未找到文档「${title}」`)
        }
      }
      if (cached) {
        resolve(cached)
      } else {
        void qc
          .fetchQuery({
            queryKey: key,
            queryFn: () => documentsApi.tree(workspaceId),
          })
          .then(resolve)
          .catch(() => message.error('文档树加载失败'))
      }
    },
    [qc, workspaceId, navigate],
  )

  const versionTimeline = useMemo(() => {
    const items: VersionItem[] = versionsQuery.data?.items ?? []
    return items.map((v, idx) => ({
      color: idx === 0 ? 'green' : 'gray',
      children: (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <div>
            <Space size={8}>
              <Text strong>v{v.version_number}</Text>
              {v.change_type === 'rollback' && <Tag color="orange">回滚</Tag>}
              {v.change_type === 'auto_import' && <Tag color="blue">导入</Tag>}
            </Space>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {new Date(v.created_at).toLocaleString('zh-CN', { hour12: false })}
                {v.change_summary ? ` · ${v.change_summary}` : ''}
              </Text>
            </div>
          </div>
          <Space size={4}>
            {idx > 0 && (
              <Button
                size="small"
                onClick={() => setDiffPair({ base: items[idx].version_number, head: items[idx - 1].version_number })}
              >
                与上一版对比
              </Button>
            )}
            {idx > 0 && (
              <Popconfirm title={`回滚到 v${v.version_number}？将创建新版本。`} onConfirm={() => rollbackMut.mutate(v.version_number)}>
                <Button size="small">回滚到此版</Button>
              </Popconfirm>
            )}
          </Space>
        </div>
      ),
    }))
  }, [versionsQuery.data, rollbackMut])

  if (docQuery.isLoading) return <div style={{ padding: 24 }}>加载中…</div>
  if (docQuery.isError || !doc) {
    return <Alert type="error" message="文档不存在或加载失败" style={{ margin: 24 }} showIcon />
  }

  const editable = true // viewer 保存转修改申请（202），无需在前端隐藏编辑入口

  /** 窄屏：次级入口（反向链接 / 文档链接 / 插入表格引用 / 标签 / 修改申请 / 版本 / 导出）
   *  收进「更多」，只保留「大纲」（导航）与「保存」（主操作），
   *  避免 9 个按钮在 390px 屏上折成三行挤掉正文。 */
  const docMoreItems = [
    { key: 'find', icon: <SearchOutlined />, label: '查找替换', onClick: openFind },
    { key: 'backlinks', icon: <LinkOutlined />, label: '反向链接', onClick: () => setBacklinksOpen(true) },
    { key: 'links', icon: <BranchesOutlined />, label: '文档链接', onClick: () => setLinksOpen(true) },
    { key: 'insert-image', icon: <PictureOutlined />, label: '插入图片', onClick: () => imageInputRef.current?.click() },
    { key: 'insert-table', icon: <TableOutlined />, label: '插入表格引用', onClick: () => setInsertOpen(true) },
    { key: 'tags', icon: <TagsOutlined />, label: `标签${(doc.tag_ids?.length ?? 0) > 0 ? ` (${doc.tag_ids?.length})` : ''}`, onClick: () => setTagsOpen(true) },
    { key: 'change-requests', icon: <PullRequestOutlined />, label: `修改申请${pendingCrCount > 0 ? ` (${pendingCrCount})` : ''}`, onClick: () => setCrOpen(true) },
    { key: 'versions', icon: <HistoryOutlined />, label: `版本${(doc.version_count ?? 0) > 0 ? ` (${doc.version_count})` : ''}`, onClick: () => setVersionsOpen(true) },
    { type: 'divider' as const },
    {
      key: 'export',
      icon: <DownloadOutlined />,
      label: '导出',
      children: [
        { key: 'docx', icon: <FileWordOutlined />, label: '导出 Word (.docx)', onClick: () => exportMut.mutate('docx') },
        { key: 'pdf', icon: <FilePdfOutlined />, label: '导出 PDF (.pdf)', onClick: () => exportMut.mutate('pdf') },
        { key: 'md', icon: <FileMarkdownOutlined />, label: '导出 Markdown (.md)', onClick: () => exportMut.mutate('md') },
      ],
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 顶栏 */}
      <div
        style={{
          padding: '12px 24px',
          borderBottom: '1px solid var(--cn-border, #e8e8e8)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          {pathItems.length > 1 && (
            <Breadcrumb
              data-testid="doc-path-crumb"
              style={{ fontSize: 12, marginBottom: 2 }}
              items={pathItems}
            />
          )}
          <Space wrap>
          <Title level={4} style={{ margin: 0 }}>{doc.title}</Title>
          <Tag>{doc.status === 'published' ? '已发布' : doc.status === 'archived' ? '归档' : '草稿'}</Tag>
          {dirtyRef.current && <Text type="warning" style={{ fontSize: 12 }}>未保存</Text>}
          </Space>
        </div>
        {isMobile ? (
          <Space size={8}>
            <Button icon={<MenuOutlined />} onClick={() => setOutlineOpen(true)}>
              大纲{outline.length > 0 ? ` (${outline.length})` : ''}
            </Button>
            <Dropdown trigger={['click']} menu={{ items: docMoreItems }}>
              <Button icon={<MoreOutlined />} data-testid="doc-more-actions">更多</Button>
            </Dropdown>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saveMut.isPending}
              disabled={!editable}
              data-testid="doc-save-btn"
              onClick={handleSave}
            >
              保存
            </Button>
          </Space>
        ) : (
        <Space wrap>
          <Button icon={<MenuOutlined />} onClick={() => setOutlineOpen(true)}>
            大纲{outline.length > 0 ? ` (${outline.length})` : ''}
          </Button>
          <Button
            icon={<PictureOutlined />}
            loading={imageMut.isPending}
            data-testid="doc-image-insert"
            onClick={() => imageInputRef.current?.click()}
          >
            图片
          </Button>
          <Button icon={<SearchOutlined />} data-testid="doc-find-open" onClick={openFind}>
            查找
          </Button>
          <Button icon={<LinkOutlined />} onClick={() => setBacklinksOpen(true)}>
            反链
          </Button>
          <Button icon={<BranchesOutlined />} data-testid="doc-links-open" onClick={() => setLinksOpen(true)}>
            链接
          </Button>
          <Button icon={<TableOutlined />} onClick={() => setInsertOpen(true)}>
            插入表格引用
          </Button>
          <Button icon={<TagsOutlined />} onClick={() => setTagsOpen(true)}>
            标签{doc.tag_ids.length > 0 ? ` (${doc.tag_ids.length})` : ''}
          </Button>
          <Button
            icon={<PullRequestOutlined />}
            data-testid="doc-cr-open"
            onClick={() => setCrOpen(true)}
          >
            修改申请{pendingCrCount > 0 ? ` (${pendingCrCount})` : ''}
          </Button>
          <Button icon={<HistoryOutlined />} onClick={() => setVersionsOpen(true)}>
            版本{doc.version_count > 0 ? ` (${doc.version_count})` : ''}
          </Button>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'docx', icon: <FileWordOutlined />, label: '导出 Word (.docx)' },
                { key: 'pdf', icon: <FilePdfOutlined />, label: '导出 PDF (.pdf)' },
                { key: 'md', icon: <FileMarkdownOutlined />, label: '导出 Markdown (.md)' },
              ],
              onClick: ({ key }) => exportMut.mutate(key as DocumentExportFormat),
            }}
          >
            <Button icon={<DownloadOutlined />} loading={exportMut.isPending} data-testid="doc-export-btn">
              导出
            </Button>
          </Dropdown>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saveMut.isPending}
            disabled={!editable}
            onClick={handleSave}
          >
            保存 (Ctrl+S)
          </Button>
        </Space>
        )}
      </div>

      {saveError && (
        <Alert
          type="warning"
          showIcon
          message={saveError}
          description="文档可能已被他人修改。复制当前编辑内容后刷新页面，再粘贴保存。"
          closable
          onClose={() => setSaveError(null)}
          style={{ margin: '8px 24px 0' }}
        />
      )}

      {pendingNotice && (
        <Alert
          type="info"
          showIcon
          data-testid="doc-cr-notice"
          message={pendingNotice}
          description="正文尚未落库；可打开「修改申请」查看内容差异，由编辑者及以上角色通过后生效。"
          closable
          onClose={() => setPendingNotice(null)}
          style={{ margin: '8px 24px 0' }}
        />
      )}

      {doc.edit_lock && doc.edit_lock.user_id !== doc.updated_by_id && (
        <Alert
          type="info"
          showIcon
          message={`${doc.edit_lock.username} 正在编辑此文档（${doc.edit_lock.elapsed_seconds} 秒前开始）`}
          style={{ margin: '8px 24px 0' }}
        />
      )}

      {/* 分屏编辑/预览 —— 窄屏改为「编辑 / 预览」页签切换，桌面保持左右分屏 */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {isMobile ? (
          <>
            <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--cn-border)', flexShrink: 0 }}>
              <Segmented
                block
                value={mobilePane}
                data-testid="doc-mobile-pane-switch"
                onChange={v => setMobilePane(v as 'edit' | 'preview')}
                options={[
                  { label: '编辑', value: 'edit' },
                  { label: '预览', value: 'preview' },
                ]}
              />
            </div>
            {mobilePane === 'edit' ? (
              <>
                {findOpen && (
                  <FindReplaceBar
                    query={findQuery}
                    replacement={replaceText}
                    matches={findMatchesList}
                    currentIndex={matchIndex < findMatchesList.length ? matchIndex : -1}
                    caseSensitive={findCaseSensitive}
                    onQueryChange={q => { setFindQuery(q); setMatchIndex(-1) }}
                    onReplacementChange={setReplaceText}
                    onPrev={() => stepMatch(-1)}
                    onNext={() => stepMatch(1)}
                    onReplace={handleReplaceOne}
                    onReplaceAll={handleReplaceAll}
                    onToggleCase={() => { setFindCaseSensitive(v => !v); setMatchIndex(-1) }}
                    onClose={closeFind}
                  />
                )}
                <MarkdownToolbar onAction={applyMarkdownAction} />
                <TextArea
                  ref={taRef}
                  value={content}
                  onChange={e => {
                    setContent(e.target.value)
                    dirtyRef.current = true
                  }}
                  onKeyDown={handleEditorKeyDown}
                  onPaste={handleEditorPaste}
                  placeholder="输入 Markdown 内容…"
                  style={{
                    flex: 1,
                    minHeight: 0,
                    resize: 'none',
                    border: 'none',
                    boxShadow: 'none',
                    borderRadius: 0,
                    fontFamily: 'var(--cn-mono, monospace)',
                    fontSize: 14,
                    lineHeight: 1.7,
                    padding: 16,
                  }}
                />
                <div className="cn-doc-stats" data-testid="doc-stats">{formatStatsLabel(stats)}</div>
              </>
            ) : (
              <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '16px' }}>
                <MarkdownPreview content={content} workspaceId={workspaceId} onWikilink={handleWikilink} />
              </div>
            )}
          </>
        ) : (
          <Splitter style={{ height: '100%' }}>
            <Splitter.Panel defaultSize="50%" min="20%" max="80%">
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {findOpen && (
                <FindReplaceBar
                  query={findQuery}
                  replacement={replaceText}
                  matches={findMatchesList}
                  currentIndex={matchIndex < findMatchesList.length ? matchIndex : -1}
                  caseSensitive={findCaseSensitive}
                  onQueryChange={q => { setFindQuery(q); setMatchIndex(-1) }}
                  onReplacementChange={setReplaceText}
                  onPrev={() => stepMatch(-1)}
                  onNext={() => stepMatch(1)}
                  onReplace={handleReplaceOne}
                  onReplaceAll={handleReplaceAll}
                  onToggleCase={() => { setFindCaseSensitive(v => !v); setMatchIndex(-1) }}
                  onClose={closeFind}
                />
              )}
              <MarkdownToolbar onAction={applyMarkdownAction} />
              <TextArea
                ref={taRef}
                value={content}
                onChange={e => {
                  setContent(e.target.value)
                  dirtyRef.current = true
                }}
                onKeyDown={handleEditorKeyDown}
                onPaste={handleEditorPaste}
                placeholder="输入 Markdown 内容…"
                style={{
                  flex: 1,
                  minHeight: 0,
                  resize: 'none',
                  border: 'none',
                  boxShadow: 'none',
                  fontFamily: 'var(--cn-mono, monospace)',
                  fontSize: 14,
                  lineHeight: 1.7,
                  padding: 20,
                }}
              />
              <div className="cn-doc-stats" data-testid="doc-stats">{formatStatsLabel(stats)}</div>
              </div>
            </Splitter.Panel>
            <Splitter.Panel min="20%" max="80%">
              <div style={{ height: '100%', overflow: 'auto', padding: '20px 24px' }}>
                <MarkdownPreview content={content} workspaceId={workspaceId} onWikilink={handleWikilink} />
              </div>
            </Splitter.Panel>
          </Splitter>
        )}
      </div>

      {/* 插入图片用的隐藏文件选择器（工具栏按钮 / 窄屏更多菜单共用） */}
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        data-testid="doc-image-input"
        onChange={handleImagePick}
      />

      {/* 大纲抽屉：实时标题层级，点击滚动定位预览区锚点 */}
      <OutlineDrawer
        open={outlineOpen}
        onClose={() => setOutlineOpen(false)}
        outline={outline}
        onAnchorClick={scrollToAnchor}
      />

      {/* 反链抽屉：引用了 [[本文档标题]] 的文档列表，点击跳转 */}
      <BacklinksDrawer
        open={backlinksOpen}
        onClose={() => setBacklinksOpen(false)}
        items={backlinksQuery.data ?? []}
        loading={backlinksQuery.isLoading}
        docTitle={doc.title}
        onOpenDoc={docId => {
          setBacklinksOpen(false)
          navigate(`/w/${workspaceId}/documents/${docId}`)
        }}
      />

      {/* 出链抽屉：正文 [[标题]] 命中与断链，可为断链选择目标文档并修复 */}
      <LinksDrawer
        open={linksOpen}
        onClose={() => {
          setLinksOpen(false)
          setRepairTargets({})
        }}
        loading={linksQuery.isLoading}
        links={linksQuery.data?.items ?? []}
        brokenCount={linksQuery.data?.broken ?? 0}
        targets={linkTargetsQuery.data ?? []}
        repairTargets={repairTargets}
        onTargetChange={(title, targetId) => setRepairTargets(prev => ({ ...prev, [title]: targetId }))}
        onRepair={() => repairMut.mutate()}
        repairing={repairMut.isPending}
        onOpenDoc={docId => {
          setLinksOpen(false)
          navigate(`/w/${workspaceId}/documents/${docId}`)
        }}
      />

      {/* 版本抽屉 */}
      <VersionsDrawer
        open={versionsOpen}
        onClose={() => {
          setVersionsOpen(false)
          setDiffPair(null)
        }}
        loading={versionsQuery.isLoading}
        timeline={versionTimeline}
        diffPair={diffPair}
        diffLoading={diffQuery.isLoading}
        diff={diffQuery.data}
      />

      {/* 标签抽屉 */}
      <Drawer title="文档标签" width={420} open={tagsOpen} onClose={() => setTagsOpen(false)}>
        <TagEditor
          workspaceId={workspaceId}
          allTags={tagsQuery.data ?? []}
          selectedIds={doc.tag_ids}
          onChange={ids => setDocTagsMut.mutate(ids)}
        />
      </Drawer>

      {/* 修改申请抽屉：待审列表 + 内容 DIFF + 通过/驳回/删除草稿 */}
      <DocumentChangeRequestsDrawer
        open={crOpen}
        onClose={() => setCrOpen(false)}
        workspaceId={workspaceId}
        documentId={id}
        role={myRole}
      />

      {/* 插入数据表引用弹窗 */}
      <InsertTableModal
        open={insertOpen}
        onOk={insertTableRef}
        onCancel={() => setInsertOpen(false)}
        tableId={insertTableId}
        onTableIdChange={v => setInsertTableId(v)}
        limit={insertLimit}
        onLimitChange={v => setInsertLimit(v)}
        tables={tablesQuery.data ?? []}
        tablesLoading={tablesQuery.isLoading}
      />
    </div>
  )
}
