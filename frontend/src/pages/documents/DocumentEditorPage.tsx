/** 文档页 — 查看/编辑双模式 + Obsidian 风格实时预览 + 个人草稿（保存与提交解耦） */

import '@/compat/polyfills'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Breadcrumb,
  Button,
  Divider,
  Drawer,
  Dropdown,
  Input,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  BarChartOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  CodeOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  HistoryOutlined,
  LinkOutlined,
  DeleteOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MenuOutlined,
  MoreOutlined,
  PictureOutlined,
  PullRequestOutlined,
  ReadOutlined,
  SaveOutlined,
  SearchOutlined,
  SendOutlined,
  ShareAltOutlined,
  TableOutlined,
  TagsOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import FindReplaceBar from '@/components/Document/FindReplaceBar'
import { ancestorChain } from './DocumentTree'
import { pushRecentDoc } from './recentDocs'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import MarkdownLiveEditor, {
  type MarkdownEditorHandle,
  type MarkdownEditorMode,
  type MarkdownEditorShortcut,
} from '@/components/Document/MarkdownLiveEditor'
import MarkdownToolbar, { type MarkdownAction } from '@/components/Document/MarkdownToolbar'
import { findMatches, nextMatchIndex, replaceAllMatches, replaceMatch } from '@/components/Document/documentSearch'
import { documentStats, formatStatsLabel } from '@/components/Document/documentStats'
import { buildImageSnippet, isImageFile } from '@/components/Document/imageRef'
import { buildTableSkeleton, insertLink, wrapSelection } from '@/components/Document/markdownEdit'
import { parseOutline } from '@/components/Document/outline'
import { DEFAULT_REF_WIDTH, rewriteRefWidth, type RefWidthChange } from '@/components/Document/refWidth'
import {
  chartBlockBytes,
  DEFAULT_CHART_WIDTH,
  MAX_BLOCK_BYTES,
  MAX_BLOCKS_PER_DOC,
  rewriteChartBlock,
  rewriteChartBlockWidth,
  serializeChartBlock,
  iterChartBlocks,
  type ChartBlockSpec,
} from '@/components/Document/chartBlock'
import { documentsApi } from '@/api/documents'
import { fileApi, tableApi, viewApi, workspaceApi } from '@/api'
import { useLlmAction } from '@/hooks/useLlmAction'
import { useResponsive } from '@/hooks/useResponsive'
import { useLlmConfigured } from '@/api'
import type { WorkspaceRole } from '@/api'
import type { AiResultSection } from '@/components/Ai/AiResultDrawer'
import type {
  DocumentAiInstruction,
  DocumentAiPolishPayload,
  DocumentDraftPayload,
  DocumentExportFormat,
  DocumentItem,
  DocumentSubmitResult,
  OutgoingLinkItem,
} from '@/api/documents'

const { Text, Title } = Typography


import { isAssetContentType } from '@/components/Document/docFormat'
import BacklinksDrawer from './BacklinksDrawer'
import DocumentAssetView, { assetSuffix } from './DocumentAssetView'
import DocumentChangeRequestsDrawer from './DocumentChangeRequestsDrawer'
import DocumentShareModal from './DocumentShareModal'
import ChartDesignerModal, { type ChartDesignResult, type ChartDesignTarget } from './ChartDesignerModal'
import InsertChartModal from './InsertChartModal'
import InsertTableModal from './InsertTableModal'
import LinksDrawer from './LinksDrawer'
import OutlineDrawer from './OutlineDrawer'
import OutlinePanel from './OutlinePanel'
import {
  clampOutlineWidth,
  loadOutlinePrefs,
  saveOutlinePrefs,
  type OutlinePrefs,
} from './outlinePrefs'
import VersionsDrawer from './VersionsDrawer'
import TagEditor from './TagEditor'

// 文档 AI 面全部懒加载：结果抽屉 / 顶栏入口只在点击后才进入加载队列（ADR 0020 C11）。
// 页面本身已是路由级 lazy chunk，这里再拆一层是为了不让 AI 弹层代码进文档页首帧。
const AiDocEntry = lazy(() => import('@/components/Ai/AiDocEntry'))
const AiResultDrawer = lazy(() => import('@/components/Ai/AiResultDrawer'))

/** 选区改写指令 → 中文标签（抽屉标题 / 结果分区用） */
const AI_INSTRUCTION_LABELS: Record<DocumentAiInstruction, string> = {
  polish: '润色',
  shorten: '精简',
  expand: '扩写',
  formal: '书面化',
  translate: '翻译',
}

/** 单次选区改写上限（与后端 documents/services/ai.py 的 MAX_SELECTION_CHARS 对齐，超限先提示分段） */
const MAX_AI_SELECTION_CHARS = 4000

/** 提交弹窗的默认提交信息（需求 0063）：变更说明为空时预填，可自由修改 */
const DEFAULT_CHANGE_SUMMARY = '更新文档'

/** 顶栏图标按钮：仅图标 + Tooltip 提示；aria-label 承载含数量后缀的完整名称（测试与无障碍共用） */
function IconBtn({
  icon,
  label,
  ...rest
}: ComponentProps<typeof Button> & { icon: ReactNode; label: string }) {
  return (
    <Tooltip title={label}>
      <Button icon={icon} aria-label={label} {...rest} />
    </Tooltip>
  )
}

export default function DocumentEditorPage() {
  const { wid, docId } = useParams<{ wid: string; docId: string }>()
  const { isMobile, isDesktop } = useResponsive()
  const navigate = useNavigate()
  const qc = useQueryClient()
  // 未配置大模型时隐藏所有 AI 入口（需求 0069）：顶栏 AI、工具栏选区改写、更多菜单 AI 项
  const llmConfigured = useLlmConfigured()
  const workspaceId = Number(wid)
  const id = Number(docId)

  const [content, setContent] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [tagsOpen, setTagsOpen] = useState(false)
  const [outlineDrawerOpen, setOutlineDrawerOpen] = useState(false)
  /** 桌面端右侧大纲栏偏好（展开态 + 宽度，存 localStorage） */
  const [outlinePrefs, setOutlinePrefs] = useState<OutlinePrefs>(() => loadOutlinePrefs())
  /** 拖动中的同步写入靠 ref 取最新值，避免闭包读到旧状态 */
  const outlinePrefsRef = useRef(outlinePrefs)
  /** 顶层查看/编辑模式：已发布文档默认查看；有个人草稿或未发布文档默认编辑 */
  const [viewMode, setViewMode] = useState<'view' | 'edit'>('view')
  /** 编辑器的渲染模式：实时预览（Obsidian 风格）/ 源码 */
  const [editorMode, setEditorMode] = useState<MarkdownEditorMode>('live')
  const [backlinksOpen, setBacklinksOpen] = useState(false)
  const [linksOpen, setLinksOpen] = useState(false)
  // 断链修复：旧标题 → 选中的目标文档 ID
  const [repairTargets, setRepairTargets] = useState<Record<string, number>>({})
  const [diffPair, setDiffPair] = useState<{ base: number; head: number } | null>(null)
  const [crOpen, setCrOpen] = useState(false)
  /** 分享弹层（ADR 0017）：owner/editor 可创建匿名只读链接 */
  const [shareOpen, setShareOpen] = useState(false)

  /** 原件族文档下载（顶栏分享左侧图标按钮 / 窄屏溢出菜单）：经鉴权接口取原件存为本地文件 */
  const downloadAsset = async () => {
    if (!doc) return
    const blob = await documentsApi.assetBlob(workspaceId, doc.id)
    const suffix = assetSuffix(doc)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${doc.title || 'download'}${suffix ? `.${suffix}` : ''}`
    a.click()
    URL.revokeObjectURL(url)
  }
  /** 提交修改弹窗与变更说明 */
  const [submitOpen, setSubmitOpen] = useState(false)
  const [changeSummary, setChangeSummary] = useState('')
  /** 保存被转为修改申请时的提示（正文未落库，等待审核） */
  const [pendingNotice, setPendingNotice] = useState<string | null>(null)
  // 查找 / 替换（Ctrl+F / Ctrl+H 打开，Esc 关闭）
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [replaceText, setReplaceText] = useState('')
  const [findCaseSensitive, setFindCaseSensitive] = useState(false)
  /** 当前定位到的匹配下标（-1 = 尚未定位） */
  const [matchIndex, setMatchIndex] = useState(-1)
  /** 最新版本正文：与编辑器正文一致时禁用「保存草稿 / 提交修改」 */
  const [latestContent, setLatestContent] = useState('')
  /** 最近一次已保存（版本或草稿）的正文：用于「未保存」提示 */
  const [savedContent, setSavedContent] = useState('')
  /** 服务端已存在的个人草稿元数据（保存/提交后同步） */
  const [serverDraft, setServerDraft] = useState<DocumentDraftPayload | null>(null)
  /** 当前用户的写模式：direct 直编 / change_request 提交审核 */
  const [writeMode, setWriteMode] = useState<'direct' | 'change_request'>('direct')
  /** 草稿基准版本：首次编辑时锁定，提交时交给服务端做段落级三方合并 */
  const baseVersionRef = useRef(0)
  const editorRef = useRef<MarkdownEditorHandle>(null)
  /** 已按哪篇文档完成初始化（避免 query 重取时覆盖正在编辑的正文） */
  const initializedDocRef = useRef<number | null>(null)

  // 插入数据表引用辅助
  const [insertOpen, setInsertOpen] = useState(false)
  const [insertTableId, setInsertTableId] = useState<number | null>(null)
  /** 按视图过滤 / 排序取数；null = 整表 */
  const [insertViewId, setInsertViewId] = useState<number | null>(null)
  const [insertLimit, setInsertLimit] = useState<number | null>(null)
  /** 插入时预设的显示宽度（ADR 0051；默认 75，只有非默认才写入占位符） */
  const [insertWidth, setInsertWidth] = useState<number>(DEFAULT_REF_WIDTH)

  // 插入 / 设计图表（ADR 0048）：弹窗选模板或已有实例，设计器保存后回插引用
  const [chartInsertOpen, setChartInsertOpen] = useState(false)
  const [chartDesign, setChartDesign] = useState<ChartDesignTarget | null>(null)

  // ── 文档 AI（ADR 0020 P1）：结果只做「建议 → 预览 → 确认」，不自动保存 ──
  const [aiOpen, setAiOpen] = useState(false)
  /** 当前展示的动作：选区改写 / 整篇摘要 / 标签建议 */
  const [aiKind, setAiKind] = useState<'polish' | 'summarize' | 'suggest_tags'>('polish')
  const [aiInstruction, setAiInstruction] = useState<DocumentAiInstruction>('polish')
  /** 改写选区（字符偏移）：请求时的快照，应用时按它替换内存态正文 */
  const [aiRange, setAiRange] = useState<{ start: number; end: number } | null>(null)
  /** 改写请求对应的原文片段（抽屉左侧展示） */
  const [aiOriginal, setAiOriginal] = useState('')
  /** 标签建议选中项：仅作阅读辅助，P1 不写回文档元数据 */
  const [aiSelectedTags, setAiSelectedTags] = useState<string[]>([])

  const polishAi = useLlmAction(
    (payload: DocumentAiPolishPayload) => documentsApi.aiAction(workspaceId, id, 'polish', payload),
    { fallbackError: 'AI 润色失败，请稍后重试' },
  )
  const summarizeAi = useLlmAction(
    () => documentsApi.aiAction(workspaceId, id, 'summarize'),
    { fallbackError: 'AI 摘要失败，请稍后重试' },
  )
  const suggestTagsAi = useLlmAction(
    () => documentsApi.aiAction(workspaceId, id, 'suggest_tags'),
    { fallbackError: 'AI 标签建议失败，请稍后重试' },
  )

  // run / reset 在 hook 内是 useCallback 稳定引用：拆出来让事件回调的依赖数组保持干净
  const runPolish = polishAi.run
  const runSummarize = summarizeAi.run
  const runSuggestTags = suggestTagsAi.run
  const resetPolish = polishAi.reset
  const resetSummarize = summarizeAi.reset
  const resetSuggestTags = suggestTagsAi.reset

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

  // 插入弹窗的视图下拉：仅在已选表时加载（后端已按可见性收敛）
  const viewsQuery = useQuery({
    queryKey: ['views', workspaceId, insertTableId],
    queryFn: () => viewApi.list(workspaceId, insertTableId as number),
    enabled: insertOpen && insertTableId !== null,
  })

  const docQuery = useQuery({
    queryKey: ['documents', workspaceId, id, 'content'],
    queryFn: () => documentsApi.getContent(workspaceId, id),
    enabled: Number.isFinite(workspaceId) && Number.isFinite(id),
  })

  // 载入文档：有个人草稿则优先展示草稿，否则展示最新版本
  useEffect(() => {
    const doc = docQuery.data
    if (!doc) return
    if (initializedDocRef.current === doc.id) return
    initializedDocRef.current = doc.id
    const draft = doc.draft ?? null
    const initial = draft?.content ?? doc.content
    setContent(initial)
    setSavedContent(initial)
    setLatestContent(doc.content)
    setServerDraft(draft)
    setWriteMode(doc.write_mode === 'change_request' ? 'change_request' : 'direct')
    baseVersionRef.current = draft?.base_version_number ?? doc.version_number ?? 0
    // 默认模式：有草稿或未发布文档 → 编辑；已发布/归档且无草稿 → 查看
    const defaultEdit = !!draft || (!doc.is_folder && doc.status === 'draft')
    setViewMode(defaultEdit ? 'edit' : 'view')
  }, [docQuery.data])

  // 保存草稿：只写个人草稿，不创建版本、不触发审核
  const draftMut = useMutation({
    mutationFn: (text: string) =>
      documentsApi.saveDraft(workspaceId, id, {
        content: text,
        base_version_number: baseVersionRef.current,
      }),
    onSuccess: (result, text) => {
      setServerDraft(result.draft)
      setSavedContent(text)
      setSaveError(null)
      setPendingNotice(null)
      message.success(result.draft ? '草稿已保存（尚未提交）' : '内容与当前版本一致，草稿已清空')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '草稿保存失败'
      setSaveError(detail)
    },
  })

  // 提交修改：显式动作，直接落库为新版本或生成修改申请
  const submitMut = useMutation({
    mutationFn: (summary: string) =>
      documentsApi.submit(workspaceId, id, {
        content,
        change_summary: summary,
        base_version_number: baseVersionRef.current,
      }),
    onSuccess: (result: DocumentSubmitResult) => {
      setSubmitOpen(false)
      setChangeSummary('')
      setSaveError(null)
      setServerDraft(null)
      if (result.mode === 'direct') {
        const next = result.content ?? content
        setContent(next)
        setSavedContent(next)
        setLatestContent(next)
        baseVersionRef.current = result.version_number ?? baseVersionRef.current
        setPendingNotice(null)
        message.success(result.message)
      } else {
        // 修改申请待审：正文不落库，回到查看模式展示当前发布版
        setPendingNotice(result.message)
        setContent(latestContent)
        setSavedContent(latestContent)
        message.success(result.message)
      }
      setViewMode('view')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'versions'] })
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
      void qc.invalidateQueries({ queryKey: ['document-change-requests', workspaceId, id] })
    },
    onError: (err: unknown) => {
      const data = (err as { response?: { data?: { detail?: string; code?: string } } })?.response?.data
      setSaveError(data?.detail ?? '提交失败')
      setSubmitOpen(false)
      if (data?.code === 'no_changes') {
        void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
      }
    },
  })

  // 导出文档：Markdown / Word / PDF（浏览器直接下载）
  // 发布：可见性策略下「草稿仅创建者与工作区所有者可见」，
  // 因此必须提供显式发布入口，否则同事永远看不到这份文档。
  const publishMut = useMutation({
    mutationFn: () => documentsApi.updateMeta(workspaceId, id, { status: 'published' }),
    onSuccess: () => {
      message.success('已发布：工作区成员现在可以看到这份文档')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id] })
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
    },
    onError: (err: unknown) => {
      message.error(err instanceof Error ? err.message : '状态更新失败')
    },
  })

  const exportMut = useMutation({
    mutationFn: (format: DocumentExportFormat) => documentsApi.exportFile(workspaceId, id, format),
    onSuccess: (blob: Blob, format: DocumentExportFormat) => {
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // Markdown 正文含站内图片时后端返回 zip（<标题>.md + assets/），文件名随实际类型调整
      const ext = blob.type === 'application/zip' ? 'zip' : format
      a.download = `${docQuery.data?.title || 'document'}_${ts}.${ext}`
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
    // head=0 为草稿哨兵（需求 0062）：走「编辑基准版本 → 草稿」端点
    queryFn: () =>
      diffPair!.head === 0
        ? documentsApi.getDraftDiff(workspaceId, id)
        : documentsApi.diff(workspaceId, id, diffPair!.base, diffPair!.head),
    enabled: diffPair !== null,
  })

  // 丢弃草稿（ADR 0057 D4）：确认后删除服务端草稿，编辑态重置为最新版本并回到查看模式
  const discardMut = useMutation({
    mutationFn: () => documentsApi.discardDraft(workspaceId, id),
    onSuccess: () => {
      setServerDraft(null)
      setContent(latestContent)
      setSavedContent(latestContent)
      baseVersionRef.current = docQuery.data?.version_number ?? 0
      setDiffPair(null)
      setViewMode('view')
      message.success('已丢弃草稿，回到最新版本')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '草稿丢弃失败'
      message.error(detail)
    },
  })

  const rollbackMut = useMutation({
    mutationFn: (target: number) => documentsApi.rollback(workspaceId, id, target),
    onSuccess: (_doc, target) => {
      message.success(`已回滚到 v${target}`)
      setVersionsOpen(false)
      setDiffPair(null)
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'content'] })
      // 回滚会追加新版本，版本列表与差异缓存都失效
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'versions'] })
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, id, 'diff'] })
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

  /** 是否有未提交的修改：与最新版本正文一致时禁止保存草稿 / 提交 */
  const hasChanges = content !== latestContent
  /** 是否有尚未保存到草稿的修改：驱动「草稿未保存 / 已保存」标签与保存按钮禁用 */
  const hasUnsaved = content !== savedContent

  /** 保存：只写个人草稿，不产生版本、不触发审核；提交由「提交修改」显式触发 */
  const handleSave = useCallback(() => {
    if (!hasChanges) {
      message.info('内容与当前版本一致，无需保存')
      return
    }
    // 草稿已保存且无新改动时不重复落库（Ctrl+S 与按钮共用此守卫）
    if (!hasUnsaved) return
    draftMut.mutate(content)
  }, [content, draftMut, hasChanges, hasUnsaved])

  /** 打开提交确认弹窗：未修改时直接拦截，避免产生空版本 */
  const openSubmit = useCallback(() => {
    if (!hasChanges) {
      message.info('文档未发生修改，无需提交')
      return
    }
    // 变更说明为空时预填默认提交信息（需求 0063）；取消后重开保留已输入文本
    setChangeSummary(prev => (prev.trim() === '' ? DEFAULT_CHANGE_SUMMARY : prev))
    setSubmitOpen(true)
  }, [hasChanges])

  /** 切换查看 / 编辑：离开编辑且有未保存改动时先落草稿（草稿不提交、不影响版本） */
  const handleModeChange = useCallback(
    (next: 'view' | 'edit') => {
      if (next === viewMode) return
      if (next === 'view' && hasChanges && hasUnsaved && !draftMut.isPending) {
        draftMut.mutate(content)
      }
      setViewMode(next)
    },
    [viewMode, hasChanges, hasUnsaved, draftMut, content],
  )

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

  /** 选中并滚动到指定区间（编辑器负责聚焦与滚动） */
  const focusRange = useCallback((start: number, end: number) => {
    requestAnimationFrame(() => {
      editorRef.current?.setSelection(start, end)
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
    const selection = editorRef.current?.getSelection()
    const selected = selection && selection.end > selection.start
      ? content.slice(selection.start, selection.end)
      : ''
    if (selected && !selected.includes('\n') && selected.length <= 200) setFindQuery(selected)
    setFindOpen(true)
  }, [content])

  const closeFind = useCallback(() => {
    setFindOpen(false)
    setMatchIndex(-1)
    requestAnimationFrame(() => editorRef.current?.focus())
  }, [])

  /** 上一个 / 下一个匹配（从当前光标位置起算，越界环绕） */
  const stepMatch = useCallback((direction: 1 | -1) => {
    if (findMatchesList.length === 0) return
    const caret = editorRef.current?.getSelection().end ?? 0
    const idx = nextMatchIndex(findMatchesList, caret, direction)
    if (idx >= 0) selectMatch(idx)
  }, [findMatchesList, selectMatch])

  /** 替换当前匹配，并自动跳到下一处（与常见编辑器行为一致） */
  const handleReplaceOne = useCallback(() => {
    const caret = editorRef.current?.getSelection().end ?? 0
    const idx = matchIndex >= 0 && findMatchesList[matchIndex] ? matchIndex : nextMatchIndex(findMatchesList, caret, 1)
    const target = findMatchesList[idx]
    if (!target) return
    const replaced = replaceMatch(content, target, replaceText)
    setContent(replaced.value)
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
    setMatchIndex(-1)
    message.success(`已替换 ${result.count} 处`)
  }, [content, findQuery, replaceText, findCaseSensitive])

  /** 应用一次 Markdown 语法操作：以编辑器当前选区为准，写回后恢复焦点与选区 */
  const applyMarkdownAction = useCallback((action: MarkdownAction) => {
    const selection = editorRef.current?.getSelection()
    const start = selection?.start ?? content.length
    const end = selection?.end ?? start
    const result = action(content, start, end)
    if (result.value === content) return
    setContent(result.value)
    // 受控组件重渲染后再恢复选区（否则光标会跳到末尾）
    requestAnimationFrame(() => {
      editorRef.current?.setSelection(result.selectionStart, result.selectionEnd)
    })
  }, [content])

  // ── 文档 AI：入口 / 应用 / 重新生成（结果只改内存态，绝不自动保存） ──

  /** 打开选区改写：从编辑器读当前选区，空选区给中文提示且不发请求 */
  const openAiRewrite = useCallback((instruction: DocumentAiInstruction) => {
    const selection = editorRef.current?.getSelection()
    const start = selection?.start ?? 0
    const end = selection?.end ?? 0
    const selected = end > start ? content.slice(start, end) : ''
    if (!selected.trim()) {
      message.warning('请先选中文本')
      return
    }
    if (selected.length > MAX_AI_SELECTION_CHARS) {
      message.warning(`选中文本过长（${selected.length} 字，最多 ${MAX_AI_SELECTION_CHARS} 字），请分段改写`)
      return
    }
    setAiKind('polish')
    setAiInstruction(instruction)
    setAiRange({ start, end })
    setAiOriginal(selected)
    setAiSelectedTags([])
    setAiOpen(true)
    void runPolish({ selection: selected, instruction })
  }, [content, runPolish])

  /** 打开整篇摘要：后端读取文档最新版本正文，与编辑器未保存改动无关 */
  const openAiSummary = useCallback(() => {
    setAiKind('summarize')
    setAiRange(null)
    setAiOriginal('')
    setAiSelectedTags([])
    setAiOpen(true)
    void runSummarize({})
  }, [runSummarize])

  /** 打开标签建议：只展示建议，不自动改文档元数据 */
  const openAiSuggestTags = useCallback(() => {
    setAiKind('suggest_tags')
    setAiRange(null)
    setAiOriginal('')
    setAiSelectedTags([])
    setAiOpen(true)
    void runSuggestTags({})
  }, [runSuggestTags])

  /** 关闭抽屉：丢弃在途请求结果，避免关闭后延迟到达的状态再弹回来 */
  const closeAi = useCallback(() => {
    setAiOpen(false)
    setAiRange(null)
    setAiOriginal('')
    setAiSelectedTags([])
    resetPolish()
    resetSummarize()
    resetSuggestTags()
  }, [resetPolish, resetSummarize, resetSuggestTags])

  /** 重新生成：沿用同一动作与同一选区 */
  const regenerateAi = useCallback(() => {
    if (aiKind === 'polish') {
      if (!aiRange || !aiOriginal) return
      void runPolish({ selection: aiOriginal, instruction: aiInstruction })
      return
    }
    if (aiKind === 'summarize') void runSummarize({})
    else void runSuggestTags({})
  }, [aiKind, aiRange, aiOriginal, aiInstruction, runPolish, runSummarize, runSuggestTags])

  /** 应用改写：只替换编辑器内存态选区并恢复光标；保存仍走既有草稿 / 提交 */
  const applyAiRewrite = useCallback(() => {
    const text = polishAi.data?.result.text
    if (!text || !aiRange) return
    const { start, end } = aiRange
    setContent(prev => `${prev.slice(0, start)}${text}${prev.slice(end)}`)
    const caret = start + text.length
    setAiOpen(false)
    requestAnimationFrame(() => editorRef.current?.setSelection(caret, caret))
    message.success('已应用到编辑器（尚未保存，请记得保存草稿或提交修改）')
  }, [polishAi.data, aiRange])

  /** 在光标处插入独占段落的片段（前后自动补空行）；图片 / 数据表引用共用.
   *
   * 用函数式更新：连续插入（如一次粘贴多张图片）时各自基于最新正文计算，不会互相覆盖。
   */
  const insertSnippetAtCursor = useCallback((snippet: string) => {
    const selection = editorRef.current?.getSelection()
    const pos = selection?.start ?? null
    const end = selection?.end ?? pos
    let inserted: { start: number; end: number } | null = null
    setContent(prev => {
      const start = pos ?? prev.length
      const stop = end ?? start
      const before = prev.slice(0, start)
      const after = prev.slice(stop)
      const prefix = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''
      const suffix = after && !after.startsWith('\n\n') ? (after.startsWith('\n') ? '\n' : '\n\n') : ''
      const block = `${prefix}${snippet}${suffix}`
      inserted = { start: before.length + prefix.length, end: before.length + block.length }
      return `${before}${prefix}${snippet}${suffix}${after}`
    })
    // 光标随插入内容前移：一次粘贴多张图片走串行上传队列，逐条插入时读取的都是
    // 同一光标位置；React 19 受控 textarea 会恢复插入前光标，若不显式前移，
    // 第二条会插到第一条之前（顺序反转）。微任务时序在 React 提交后执行，
    // 真实浏览器与测试环境一致。
    if (inserted) {
      const caret: { start: number; end: number } = inserted
      queueMicrotask(() => editorRef.current?.setSelection(caret.start, caret.end))
    }
  }, [])

  /** 编辑器快捷键：查找 / 加粗 / 斜体 / 链接 / Esc 关闭查找条（Ctrl+S 由全局处理） */
  const applyEditorShortcut = useCallback((action: MarkdownEditorShortcut) => {
    if (action === 'escape') {
      if (findOpen) closeFind()
      return
    }
    if (action === 'find') {
      openFind()
    } else if (action === 'bold') {
      applyMarkdownAction((v, s, e) => wrapSelection(v, s, e, '**'))
    } else if (action === 'italic') {
      applyMarkdownAction((v, s, e) => wrapSelection(v, s, e, '*'))
    } else {
      applyMarkdownAction((v, s, e) => insertLink(v, s, e))
    }
  }, [findOpen, closeFind, openFind, applyMarkdownAction])

  // 在光标位置插入数据表引用占位符（前后自动补空行保证独占段落）
  const resetInsertState = () => {
    setInsertTableId(null)
    setInsertViewId(null)
    setInsertLimit(null)
    setInsertWidth(DEFAULT_REF_WIDTH)
  }

  const insertTableRef = () => {
    if (insertTableId === null) return
    const view = insertViewId ? `|view=${insertViewId}` : ''
    const limit = insertLimit ? `|limit=${insertLimit}` : ''
    const width = insertWidth !== DEFAULT_REF_WIDTH ? `|width=${insertWidth}` : ''
    insertSnippetAtCursor(`{{table:${insertTableId}${view}${limit}${width}}}`)
    // 0071：插入成功提示带可读名，避免落笔后只剩 ID 无从对应
    const tableName = tablesQuery.data?.find(t => t.id === insertTableId)?.name ?? `#${insertTableId}`
    const viewName = insertViewId
      ? viewsQuery.data?.find(v => v.id === insertViewId)?.name ?? `#${insertViewId}`
      : null
    message.success(`已插入数据表引用：${tableName}${viewName ? ` · ${viewName}` : ''}`)
    setInsertOpen(false)
    resetInsertState()
  }

  // ── 图表（ADR 0052）：插入定义块 / 从预览按块序号进入设计器编辑 ──
  const insertChartSpec = useCallback((spec: ChartBlockSpec) => {
    if (chartBlockBytes(spec) > MAX_BLOCK_BYTES) {
      message.error('图表定义超过 32KB，无法插入')
      return
    }
    if (iterChartBlocks(content).length >= MAX_BLOCKS_PER_DOC) {
      message.error(`单篇文档最多 ${MAX_BLOCKS_PER_DOC} 个图表，请先删除不再使用的图表`)
      return
    }
    insertSnippetAtCursor(serializeChartBlock(spec))
  }, [content, insertSnippetAtCursor])

  /** 图表编辑入口（ChartEmbed）：有写权限才传入预览，viewer 不出现按钮 */
  const canEditCharts = myRole === 'owner' || myRole === 'editor'

  /** 引用宽度调整（ADR 0051）：按出现序号改写正文占位符，仅编辑者及以上可用 */
  const changeRefWidth = useCallback((change: RefWidthChange) => {
    setContent(prev => rewriteRefWidth(prev, change))
  }, [])
  /** 图表宽度随块写入正文（ADR 0052 D8）：按出现序号定位 */
  const changeChartWidth = useCallback((occurrence: number, width: number) => {
    setContent(prev => rewriteChartBlockWidth(prev, occurrence, width))
  }, [])
  /** 编辑正文块：直接带定义打开设计器，不再按实例 ID 拉取 */
  const openChartDesignerForEdit = useCallback((spec: ChartBlockSpec, occurrence: number) => {
    setChartDesign({ kind: 'editBlock', spec, occurrence })
  }, [])

  // ── 插入图片：上传到工作区文件存储，正文写入站内引用 `![alt](file:<key>)` ──
  const imageInputRef = useRef<HTMLInputElement>(null)

  const imageMut = useMutation({
    mutationFn: (file: File) => fileApi.upload(workspaceId, file, { documentId: id }),
    onSuccess: (res, file) => {
      insertSnippetAtCursor(buildImageSnippet(file.name, res.file_key))
      message.success('图片已插入（提交后生效）')
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

  /** 编辑器内粘贴图片：按顺序上传并插入站内引用（普通文本粘贴不受影响） */
  const handlePasteImages = useCallback((files: File[]) => {
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
    // 锚点位于预览区：先切到查看模式，等渲染后再滚动定位
    setViewMode('view')
    requestAnimationFrame(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  /** 大纲栏偏好唯一写入口：先同步 ref，再更新状态，按需落本地 */
  const updateOutlinePrefs = useCallback((next: OutlinePrefs, persist = true) => {
    outlinePrefsRef.current = next
    setOutlinePrefs(next)
    if (persist) saveOutlinePrefs(next)
  }, [])

  const toggleOutline = useCallback(() => {
    const cur = outlinePrefsRef.current
    updateOutlinePrefs({ ...cur, open: !cur.open })
  }, [updateOutlinePrefs])

  /** 拖动过程 commit=false（只预览宽度），松手 / 键盘操作 commit=true（写入偏好） */
  const changeOutlineWidth = useCallback((width: number, commit = false) => {
    updateOutlinePrefs({ ...outlinePrefsRef.current, width: clampOutlineWidth(width) }, commit)
  }, [updateOutlinePrefs])

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

  /** 版本列表（后端倒序：最新在前）+ 总数；差异对比在抽屉内原地展开，不需要额外拼装时间线节点 */
  const versions = versionsQuery.data?.items ?? []

  if (docQuery.isLoading) return <div style={{ padding: 24 }}>加载中…</div>
  if (docQuery.isError || !doc) {
    return <Alert type="error" title="文档不存在或加载失败" style={{ margin: 24 }} showIcon />
  }

  const editable = true // viewer 保存转修改申请（202），无需在前端隐藏编辑入口
  // 原件族（PDF / Office / 图片，ADR 0025）：只读，正文区换成阅读器，编辑类入口全部隐藏
  const isAssetDoc = !doc.is_folder && isAssetContentType(doc.content_type)

  // ── AI 抽屉展示数据：按当前动作从对应 hook 取 loading / error / 结果 ──
  const aiLoading =
    aiKind === 'polish' ? polishAi.loading : aiKind === 'summarize' ? summarizeAi.loading : suggestTagsAi.loading
  const aiError =
    aiKind === 'polish' ? polishAi.error : aiKind === 'summarize' ? summarizeAi.error : suggestTagsAi.error
  const aiTitle =
    aiKind === 'summarize'
      ? 'AI 摘要'
      : aiKind === 'suggest_tags'
        ? 'AI 标签建议'
        : `AI ${AI_INSTRUCTION_LABELS[aiInstruction]}`
  const aiSummaryResult = summarizeAi.data?.result
  const aiTagResult = suggestTagsAi.data?.result
  const aiSections: AiResultSection[] =
    aiKind === 'summarize' && aiSummaryResult
      ? [
          { key: 'summary', title: '摘要', text: aiSummaryResult.summary || '模型未给出摘要', testId: 'ai-summary' },
          {
            key: 'points',
            title: '要点',
            items: aiSummaryResult.key_points,
            emptyText: '模型未给出要点',
            testId: 'ai-summary-points',
          },
          {
            key: 'tags',
            title: '建议标签',
            items: aiSummaryResult.suggested_tags,
            emptyText: '模型未给出标签建议',
            selectable: true,
            selected: aiSelectedTags,
            onSelect: setAiSelectedTags,
            hint: '建议标签不会自动写入文档；可在文档设置（顶栏「标签」抽屉）中手动添加。',
            testId: 'ai-summary-tags',
          },
        ]
      : aiKind === 'suggest_tags' && aiTagResult
        ? [
            {
              key: 'tags',
              title: '建议标签',
              items: aiTagResult.suggested_tags,
              emptyText: '模型未给出标签建议',
              selectable: true,
              selected: aiSelectedTags,
              onSelect: setAiSelectedTags,
              hint: '本期只展示建议，不会自动修改文档标签；可在文档设置（顶栏「标签」抽屉）中手动添加。',
              testId: 'ai-suggest-tags',
            },
          ]
        : []
  const aiMetaSource =
    aiKind === 'polish' ? polishAi.data : aiKind === 'summarize' ? summarizeAi.data : suggestTagsAi.data
  const aiTotalTokens = aiMetaSource?.usage.total_tokens
  const aiMeta = aiMetaSource
    ? [
        aiMetaSource.model ? `模型 ${aiMetaSource.model}` : '',
        typeof aiTotalTokens === 'number' ? `本次 ${aiTotalTokens} tokens` : '',
        `留痕 #${aiMetaSource.run_id}`,
      ]
        .filter(Boolean)
        .join(' · ')
    : undefined
  /** 摘要 / 标签建议基于截断后的正文生成（后端 truncated 标记） */
  const aiTruncated = aiKind !== 'polish' && Boolean(aiMetaSource?.truncated)
  const aiHint =
    aiKind === 'polish'
      ? '应用只修改编辑器内容，不会自动保存；请用「保存草稿」或「提交修改」落库。'
      : `${
          aiKind === 'summarize'
            ? '摘要与要点由模型根据文档最新版本生成，仅供参考。'
            : '标签建议不会自动修改文档元数据，可在文档设置（顶栏「标签」抽屉）中手动添加。'
        }${aiTruncated ? '（文档较长，本次仅基于正文前 12000 字生成）' : ''}`

  /** 窄屏：次级入口（反向链接 / 文档链接 / 插入图片 / 插入表格引用 / 标签 / 修改申请 / 版本 / 导出）
   *  收进「更多」，只保留「大纲」（导航）与「保存」（主操作），
   *  避免 9 个按钮在 390px 屏上折成三行挤掉正文。
   *  插入图片 / 插入表格引用仅编辑模式注入：查看模式只读，不出现写入口（ADR 0042）。 */
  const docMoreItems = [
    ...(isAssetDoc
      ? []
      : [
          { key: 'find', icon: <SearchOutlined />, label: '查找替换', onClick: openFind },
          ...(llmConfigured
            ? [
                { key: 'ai-summarize', icon: <ReadOutlined />, label: 'AI 摘要', onClick: openAiSummary },
                { key: 'ai-suggest-tags', icon: <TagsOutlined />, label: 'AI 标签建议', onClick: openAiSuggestTags },
              ]
            : []),
          { key: 'backlinks', icon: <LinkOutlined />, label: '反向链接', onClick: () => setBacklinksOpen(true) },
          { key: 'links', icon: <BranchesOutlined />, label: '文档链接', onClick: () => setLinksOpen(true) },
          ...(viewMode === 'edit'
            ? [
                { key: 'insert-image', icon: <PictureOutlined />, label: '插入图片', onClick: () => imageInputRef.current?.click() },
                { key: 'insert-table', icon: <TableOutlined />, label: '插入表格引用', onClick: () => setInsertOpen(true) },
                { key: 'insert-chart', icon: <BarChartOutlined />, label: '插入图表', onClick: () => setChartInsertOpen(true) },
              ]
            : []),
        ]),
    // 原件族文档：下载原件入口与分享并列（窄屏溢出菜单）
    ...(isAssetDoc
      ? [{ key: 'download-asset', icon: <DownloadOutlined />, label: '下载原件', onClick: () => void downloadAsset() }]
      : []),
    // 仅 owner / editor 且非文件夹可分享（viewer 由后端 require_editor 拒绝）
    ...((myRole === 'owner' || myRole === 'editor') && !doc.is_folder
      ? [{ key: 'share', icon: <ShareAltOutlined />, label: '分享', onClick: () => setShareOpen(true) }]
      : []),
    { key: 'tags', icon: <TagsOutlined />, label: `标签${(doc.tag_ids?.length ?? 0) > 0 ? ` (${doc.tag_ids?.length})` : ''}`, onClick: () => setTagsOpen(true) },
    ...(isAssetDoc
      ? []
      : [
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
        ]),
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 顶栏 */}
      <div
        style={{
          // 窄屏收窄留白：顶栏与正文左右对齐（12px），把横向空间还给标题与操作
          padding: isMobile ? '10px 12px' : '12px 24px',
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
            <Title level={4} style={{ margin: 0, fontSize: isMobile ? 18 : undefined }}>{doc.title}</Title>
            <Tag color={doc.status === 'published' ? 'green' : 'default'}>
              {/* 窄屏：长文案占宽过多，草稿态收敛为「草稿」 */}
              {doc.status === 'published' ? '已发布' : doc.status === 'archived' ? '归档' : (isMobile ? '草稿' : '草稿（仅自己可见）')}
            </Tag>
            {(hasUnsaved || serverDraft) &&
              (hasUnsaved ? (
                <Tag color="warning" icon={<WarningOutlined />} data-testid="doc-draft-tag">
                  草稿未保存
                </Tag>
              ) : (
                <Tag color="success" icon={<CheckCircleOutlined />} data-testid="doc-draft-tag">
                  草稿已保存
                </Tag>
              ))}
            {/* 已有服务端草稿未提交：追加「待提交」提示（与保存状态标签并存） */}
            {serverDraft && (
              <Tag color="orange" data-testid="doc-pending-tag">
                待提交
              </Tag>
            )}
            {/* 查看/编辑切换：按钮组连体样式，激活项高亮 */}
            {!doc.is_folder && !isAssetDoc && doc.status !== 'archived' && (
              <Space.Compact data-testid="doc-mode-switch">
                <Button
                  size="small"
                  type={viewMode === 'view' ? 'primary' : 'default'}
                  icon={<ReadOutlined />}
                  title="查看已发布的最新版本"
                  onClick={() => handleModeChange('view')}
                >
                  查看
                </Button>
                <Button
                  size="small"
                  type={viewMode === 'edit' ? 'primary' : 'default'}
                  icon={<EditOutlined />}
                  title="进入编辑，修改先保存为个人草稿"
                  onClick={() => handleModeChange('edit')}
                >
                  编辑
                </Button>
              </Space.Compact>
            )}
            {editable && doc.status === 'draft' && (
              <Button
                size="small"
                data-testid="doc-publish-toggle"
                loading={publishMut.isPending}
                onClick={() => publishMut.mutate()}
              >
                发布
              </Button>
            )}
          </Space>
        </div>
        {isMobile ? (
          <Space size={8}>
            {!isAssetDoc && (
            <Button icon={<MenuOutlined />} data-testid="doc-outline-toggle" onClick={() => setOutlineDrawerOpen(true)}>
              大纲{outline.length > 0 ? ` (${outline.length})` : ''}
            </Button>
            )}
            <Dropdown trigger={['click']} menu={{ items: docMoreItems }}>
              <Button icon={<MoreOutlined />} data-testid="doc-more-actions">更多</Button>
            </Dropdown>
            {!isAssetDoc && (
              <>
            {/* 草稿丢弃（ADR 0057，窄屏紧凑）；查看修改已并入版本历史（需求 0062） */}
            {serverDraft && (
              <Popconfirm
                  title="丢弃草稿？"
                  description="未提交的草稿修改将丢失，正文回到最新版本。"
                  okText="丢弃"
                  okButtonProps={{ danger: true }}
                  cancelText="取消"
                  onConfirm={() => discardMut.mutate()}
                >
                  <Button danger size="small" loading={discardMut.isPending} data-testid="doc-draft-discard-btn">
                    丢弃
                  </Button>
                </Popconfirm>
            )}
            <Space.Compact>
              <Button
                icon={<SaveOutlined />}
                loading={draftMut.isPending}
                disabled={!hasChanges || !hasUnsaved}
                data-testid="doc-save-btn"
                onClick={handleSave}
              >
                草稿
              </Button>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={submitMut.isPending}
                disabled={!hasChanges}
                data-testid="doc-submit-btn"
                onClick={openSubmit}
              >
                提交
              </Button>
            </Space.Compact>
              </>
            )}
          </Space>
        ) : (
        // 桌面顶栏：按任务语义分组（导航关联 → 标注 → 协作 → 历史输出 → 提交动作），大纲为最右视图锚点
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
          {/* 组 1：导航与关联（反链 / 链接，按钮组连体）；大纲开关固定最右端收尾 */}
          {!isAssetDoc && (
            <Space.Compact>
              <IconBtn icon={<LinkOutlined />} label="反链" onClick={() => setBacklinksOpen(true)} />
              <IconBtn
                icon={<BranchesOutlined />}
                label="链接"
                data-testid="doc-links-open"
                onClick={() => setLinksOpen(true)}
              />
            </Space.Compact>
          )}
          {/* 组 2：内容标注（AI / 标签）；插入图片 / 表格引用已移入编辑模式 Markdown 工具栏（ADR 0042）；
              未配置大模型时 AI 入口整体隐藏（需求 0069） */}
          {!isAssetDoc && llmConfigured && (
            <Suspense fallback={null}>
              <AiDocEntry onSummarize={openAiSummary} onSuggestTags={openAiSuggestTags} />
            </Suspense>
          )}
          <IconBtn
            icon={<TagsOutlined />}
            label={`标签${doc.tag_ids.length > 0 ? ` (${doc.tag_ids.length})` : ''}`}
            onClick={() => setTagsOpen(true)}
          />
          <Divider orientation="vertical" style={{ margin: '0 2px' }} />
          {/* 组 3：协作（下载 / 修改申请 / 分享）；原件族文档在分享左侧提供下载原件图标按钮 */}
          {isAssetDoc && (
            <IconBtn
              icon={<DownloadOutlined />}
              label="下载原件"
              data-testid="doc-asset-download-btn"
              onClick={() => void downloadAsset()}
            />
          )}
          {!isAssetDoc && (
            <IconBtn
              icon={<PullRequestOutlined />}
              label={`修改申请${pendingCrCount > 0 ? ` (${pendingCrCount})` : ''}`}
              data-testid="doc-cr-open"
              onClick={() => setCrOpen(true)}
            />
          )}
          {(myRole === 'owner' || myRole === 'editor') && !doc.is_folder && (
            <IconBtn
              icon={<ShareAltOutlined />}
              label="分享"
              data-testid="doc-share-open"
              onClick={() => setShareOpen(true)}
            />
          )}
          <Divider orientation="vertical" style={{ margin: '0 2px' }} />
          {/* 组 4：版本与导出 */}
          {!isAssetDoc && (
            <IconBtn
              icon={<HistoryOutlined />}
              label={`版本${doc.version_count > 0 ? ` (${doc.version_count})` : ''}`}
              onClick={() => setVersionsOpen(true)}
            />
          )}
          {!isAssetDoc && (
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
            <IconBtn icon={<DownloadOutlined />} label="导出" loading={exportMut.isPending} data-testid="doc-export-btn" />
          </Dropdown>
          )}
          {!isAssetDoc && (
            <>
          {/* 组 5：提交动作：保存 / 提交为按钮组连体；破坏性的丢弃草稿独立组外弱化为纯图标（ADR 0057 口径恢复） */}
          <Space.Compact>
            <Button
              icon={<SaveOutlined />}
              loading={draftMut.isPending}
              disabled={!hasChanges || !hasUnsaved}
              data-testid="doc-save-btn"
              onClick={handleSave}
              title={
                !hasChanges
                  ? '内容与当前版本一致，无需保存'
                  : !hasUnsaved
                    ? '草稿已保存，再次修改后可继续保存'
                    : '保存为个人草稿，不生成版本'
              }
            >
              保存
            </Button>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={submitMut.isPending}
              disabled={!hasChanges}
              data-testid="doc-submit-btn"
              onClick={openSubmit}
              title={
                !hasChanges
                  ? '文档未发生修改，无需提交'
                  : writeMode === 'change_request'
                    ? '提交后生成修改申请，审核通过后生效'
                    : '提交后生成新版本'
              }
            >
              提交
            </Button>
          </Space.Compact>
          {serverDraft && (
            <Popconfirm
              title="丢弃草稿？"
              description="未提交的草稿修改将丢失，正文回到最新版本。"
              okText="丢弃"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => discardMut.mutate()}
            >
              <IconBtn
                danger
                icon={<DeleteOutlined />}
                label="丢弃草稿"
                loading={discardMut.isPending}
                data-testid="doc-draft-discard-btn"
                style={{ marginLeft: 8 }}
              />
            </Popconfirm>
          )}
            </>
          )}
          {/* 组 1 收尾：大纲视图开关，展开 / 收起用不同图标，不做高亮以与普通入口保持一致 */}
          {!isAssetDoc && (
            <IconBtn
              icon={outlinePrefs.open ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
              label={`大纲${outline.length > 0 ? ` (${outline.length})` : ''}`}
              data-testid="doc-outline-toggle"
              aria-expanded={isDesktop ? outlinePrefs.open : undefined}
              onClick={() => (isDesktop ? toggleOutline() : setOutlineDrawerOpen(true))}
            />
          )}
        </div>
        )}
      </div>

      {saveError && (
        <Alert
          type="warning"
          showIcon
          title={saveError}
          description="你的编辑内容仍在页面上；个人草稿不会丢失，可重试或刷新后继续编辑。"
          closable
          onClose={() => setSaveError(null)}
          style={{ margin: isMobile ? '8px 12px 0' : '8px 24px 0' }}
        />
      )}

      {pendingNotice && (
        <Alert
          type="info"
          showIcon
          data-testid="doc-cr-notice"
          title={pendingNotice}
          description="正文尚未落库；可打开「修改申请」查看内容差异，由编辑者及以上角色通过后生效。"
          closable
          onClose={() => setPendingNotice(null)}
          style={{ margin: isMobile ? '8px 12px 0' : '8px 24px 0' }}
        />
      )}

      {/* 分屏编辑/预览 —— 窄屏改为「编辑 / 预览」页签切换，桌面保持左右分屏 */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* 正文列：查看 / 编辑内容，桌面端右侧并排大纲栏 */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {isAssetDoc ? (
          <DocumentAssetView workspaceId={workspaceId} doc={doc} />
        ) : viewMode === 'view' ? (
          <div
            style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: isMobile ? 16 : '20px 24px' }}
            data-testid="doc-view-mode"
          >
            <MarkdownPreview
              content={content}
              workspaceId={workspaceId}
              onWikilink={handleWikilink}
              onEditChart={canEditCharts ? openChartDesignerForEdit : undefined}
              onRefWidthChange={canEditCharts ? changeRefWidth : undefined}
              onChartWidthChange={canEditCharts ? changeChartWidth : undefined}
            />
          </div>
        ) : (
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
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 8,
                padding: '4px 12px',
                borderBottom: '1px solid var(--cn-border)',
                flexShrink: 0,
              }}
            >
              <MarkdownToolbar
                onAction={applyMarkdownAction}
                onInsertTable={(cols, rows) => insertSnippetAtCursor(buildTableSkeleton(cols, rows))}
                // 未配置大模型时不传回调：工具栏 AI 选区改写入口整体不渲染（需求 0069）
                onAiAction={llmConfigured ? openAiRewrite : undefined}
                aiDisabled={polishAi.loading}
                // 插入图片 / 插入表格引用 / 插入图表：桌面编辑模式走工具栏；窄屏收进「更多」菜单（ADR 0042 D4）
                onInsertImage={isMobile ? undefined : () => imageInputRef.current?.click()}
                imageInsertLoading={imageMut.isPending}
                onInsertTableRef={isMobile ? undefined : () => setInsertOpen(true)}
                onInsertChart={isMobile ? undefined : () => setChartInsertOpen(true)}
              />
              {/* 实时预览/源码切换：与顶栏「保存草稿/提交修改」同款图标+文字按钮风格，激活项高亮 */}
              <Space size={4} data-testid="doc-editor-mode-switch">
                <Button
                  size="small"
                  type={editorMode === 'live' ? 'primary' : 'default'}
                  icon={<EyeOutlined />}
                  title="Obsidian 风格实时预览，输入即渲染"
                  onClick={() => setEditorMode('live')}
                >
                  实时预览
                </Button>
                <Button
                  size="small"
                  type={editorMode === 'source' ? 'primary' : 'default'}
                  icon={<CodeOutlined />}
                  title="纯 Markdown 源码编辑"
                  onClick={() => setEditorMode('source')}
                >
                  源码
                </Button>
              </Space>
            </div>
            <MarkdownLiveEditor
              ref={editorRef}
              value={content}
              mode={editorMode}
              workspaceId={workspaceId}
              placeholder="输入 Markdown 内容…"
              onChange={setContent}
              onPasteImages={handlePasteImages}
              onShortcut={applyEditorShortcut}
            />
            <div className="cn-doc-stats" data-testid="doc-stats">{formatStatsLabel(stats)}</div>
          </>
        )}
        </div>
        {!isAssetDoc && isDesktop && outlinePrefs.open && (
          <OutlinePanel
            width={outlinePrefs.width}
            outline={outline}
            onWidthChange={changeOutlineWidth}
            onAnchorClick={scrollToAnchor}
          />
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

      {/* 大纲抽屉：窄屏（移动 / 平板）入口；桌面端走右侧常驻栏 */}
      <OutlineDrawer
        open={outlineDrawerOpen}
        onClose={() => setOutlineDrawerOpen(false)}
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
        versions={versions}
        total={versionsQuery.data?.total}
        diffPair={diffPair}
        onToggleDiff={setDiffPair}
        draft={serverDraft ? { baseVersion: serverDraft.base_version_number } : null}
        diffLoading={diffQuery.isLoading}
        diff={diffQuery.data}
        diffError={diffQuery.isError}
        onRollback={(target) => rollbackMut.mutate(target)}
        rollingBack={rollbackMut.isPending ? rollbackMut.variables ?? null : null}
      />

      {/* 标签抽屉 */}
      <Drawer title="文档标签" size={420} open={tagsOpen} onClose={() => setTagsOpen(false)}>
        <TagEditor
          workspaceId={workspaceId}
          allTags={tagsQuery.data ?? []}
          selectedIds={doc.tag_ids}
          onChange={ids => setDocTagsMut.mutate(ids)}
        />
      </Drawer>

      {/* AI 结果抽屉：懒加载；结果只作预览，应用只改编辑器内存态（不自动保存） */}
      {aiOpen && (
        <Suspense fallback={null}>
          <AiResultDrawer
            open
            title={aiTitle}
            onClose={closeAi}
            loading={aiLoading}
            error={aiError}
            originalText={aiKind === 'polish' ? aiOriginal : undefined}
            resultText={aiKind === 'polish' ? polishAi.data?.result.text : undefined}
            resultLabel={aiKind === 'polish' ? `AI ${AI_INSTRUCTION_LABELS[aiInstruction]}结果` : 'AI 结果'}
            sections={aiSections}
            meta={aiMeta}
            hint={aiHint}
            applyText="应用到编辑器"
            onApply={aiKind === 'polish' ? applyAiRewrite : undefined}
            onRegenerate={regenerateAi}
          />
        </Suspense>
      )}

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
        onCancel={() => {
          setInsertOpen(false)
          resetInsertState()
        }}
        tableId={insertTableId}
        onTableIdChange={v => {
          setInsertTableId(v)
          // 换表后旧视图失效，清空已选视图
          setInsertViewId(null)
        }}
        viewId={insertViewId}
        onViewIdChange={setInsertViewId}
        limit={insertLimit}
        onLimitChange={v => setInsertLimit(v)}
        width={insertWidth}
        onWidthChange={setInsertWidth}
        tables={tablesQuery.data ?? []}
        tablesLoading={tablesQuery.isLoading}
        views={viewsQuery.data ?? []}
        viewsLoading={viewsQuery.isLoading}
      />

      {/* 插入图表弹窗（ADR 0052）：模板两级浏览 + 素材库复制定义 */}
      <InsertChartModal
        open={chartInsertOpen}
        workspaceId={workspaceId}
        onCancel={() => setChartInsertOpen(false)}
        onPickExisting={chart => {
          setChartInsertOpen(false)
          insertChartSpec({ version: 1, templateKey: chart.template_key, title: chart.title, width: DEFAULT_CHART_WIDTH, config: chart.config })
        }}
        onPickTemplate={templateKey => {
          setChartInsertOpen(false)
          setChartDesign({ kind: 'create', templateKey })
        }}
      />

      {/* 图表设计器（ADR 0052）：新建保存后插入定义副本；编辑按块序号替换 */}
      <ChartDesignerModal
        open={chartDesign !== null}
        workspaceId={workspaceId}
        target={chartDesign}
        onCancel={() => setChartDesign(null)}
        onSaved={(result: ChartDesignResult) => {
          const design = chartDesign
          setChartDesign(null)
          if (result.kind === 'chart') {
            void qc.invalidateQueries({ queryKey: ['charts', workspaceId] })
            insertChartSpec({
              version: 1,
              templateKey: result.chart.template_key,
              title: result.chart.title,
              width: DEFAULT_CHART_WIDTH,
              config: result.chart.config,
            })
            message.success('图表已创建并插入（提交后生效）')
            return
          }
          if (design?.kind === 'editBlock') {
            setContent(prev => rewriteChartBlock(prev, design.occurrence, result.spec))
            message.success('图表已更新')
          }
        }}
      />

      {/* 分享弹层：匿名只读链接的创建 / 复制 / 访问次数 / 撤销（ADR 0017） */}
      <DocumentShareModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        workspaceId={workspaceId}
        docId={id}
        docStatus={doc.status}
      />

      {/* 提交修改弹窗：保存只写草稿，这里显式确认后才生成版本 / 修改申请 */}
      <Modal
        open={submitOpen}
        title={writeMode === 'change_request' ? '提交修改申请' : '提交修改'}
        okText={writeMode === 'change_request' ? '提交审核' : '确认提交'}
        cancelText="取消"
        confirmLoading={submitMut.isPending}
        onOk={() => submitMut.mutate(changeSummary.trim())}
        onCancel={() => setSubmitOpen(false)}
      >
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Text type="secondary">
            {writeMode === 'change_request'
              ? '你的角色没有直接编辑权限，提交后将生成修改申请，需编辑者及以上角色审核通过后才会更新正文。'
              : `提交后将生成新版本 v${(doc.version_number ?? 0) + 1}；保存草稿不会影响当前版本。`}
          </Text>
          <Input.TextArea
            value={changeSummary}
            onChange={e => setChangeSummary(e.target.value)}
            placeholder="变更说明（可选）"
            maxLength={200}
            autoSize={{ minRows: 3, maxRows: 6 }}
            data-testid="doc-submit-summary"
          />
        </Space>
      </Modal>
    </div>
  )
}
