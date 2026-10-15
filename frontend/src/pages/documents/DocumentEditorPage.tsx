/** 文档编辑页 — 分屏编辑/预览 + 版本历史 + 标签 + 乐观锁保存. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
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
  PullRequestOutlined,
  SaveOutlined,
  TableOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import MarkdownToolbar, { type MarkdownAction } from '@/components/Document/MarkdownToolbar'
import { insertLink, wrapSelection } from '@/components/Document/markdownEdit'
import { parseOutline } from '@/components/Document/outline'
import { documentsApi, isChangeRequestDispatch } from '@/api/documents'
import { tableApi, workspaceApi } from '@/api'
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
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return
    const key = e.key.toLowerCase()
    if (key === 'b') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => wrapSelection(v, s, en, '**'))
    } else if (key === 'i') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => wrapSelection(v, s, en, '*'))
    } else if (key === 'k') {
      e.preventDefault()
      applyMarkdownAction((v, s, en) => insertLink(v, s, en))
    }
  }, [applyMarkdownAction])

  // 在光标位置插入数据表引用占位符（前后自动补空行保证独占段落）
  const insertTableRef = () => {
    if (insertTableId === null) return
    const snippet = `{{table:${insertTableId}${insertLimit ? `|limit=${insertLimit}` : ''}}}`
    const el = taRef.current?.resizableTextArea?.textArea
    const pos = el?.selectionStart ?? content.length
    const end = el?.selectionEnd ?? pos
    const before = content.slice(0, pos)
    const after = content.slice(end)
    const prefix = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''
    const suffix = after && !after.startsWith('\n\n') ? (after.startsWith('\n') ? '\n' : '\n\n') : ''
    setContent(`${before}${prefix}${snippet}${suffix}${after}`)
    dirtyRef.current = true
    setInsertOpen(false)
    setInsertTableId(null)
    setInsertLimit(null)
  }

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
    { key: 'backlinks', icon: <LinkOutlined />, label: '反向链接', onClick: () => setBacklinksOpen(true) },
    { key: 'links', icon: <BranchesOutlined />, label: '文档链接', onClick: () => setLinksOpen(true) },
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
        <Space wrap>
          <Title level={4} style={{ margin: 0 }}>{doc.title}</Title>
          <Tag>{doc.status === 'published' ? '已发布' : doc.status === 'archived' ? '归档' : '草稿'}</Tag>
          {dirtyRef.current && <Text type="warning" style={{ fontSize: 12 }}>未保存</Text>}
        </Space>
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
                <MarkdownToolbar onAction={applyMarkdownAction} />
                <TextArea
                  ref={taRef}
                  value={content}
                  onChange={e => {
                    setContent(e.target.value)
                    dirtyRef.current = true
                  }}
                  onKeyDown={handleEditorKeyDown}
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
              <MarkdownToolbar onAction={applyMarkdownAction} />
              <TextArea
                ref={taRef}
                value={content}
                onChange={e => {
                  setContent(e.target.value)
                  dirtyRef.current = true
                }}
                onKeyDown={handleEditorKeyDown}
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
