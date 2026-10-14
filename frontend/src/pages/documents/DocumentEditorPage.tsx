/** 文档编辑页 — 分屏编辑/预览 + 版本历史 + 标签 + 乐观锁保存. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Drawer,
  Input,
  Popconfirm,
  Space,
  Splitter,
  Tag,
  Typography,
  message,
} from 'antd'
import type { TextAreaRef } from 'antd/es/input/TextArea'
import {
  BranchesOutlined,
  HistoryOutlined,
  LinkOutlined,
  MenuOutlined,
  SaveOutlined,
  TableOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import { parseOutline } from '@/components/Document/outline'
import { documentsApi } from '@/api/documents'
import { tableApi } from '@/api'
import type {
  DocumentDetail,
  DocumentItem,
  OutgoingLinkItem,
  VersionItem,
} from '@/api/documents'

const { Text, Title } = Typography
const { TextArea } = Input


import BacklinksDrawer from './BacklinksDrawer'
import InsertTableModal from './InsertTableModal'
import LinksDrawer from './LinksDrawer'
import OutlineDrawer from './OutlineDrawer'
import VersionsDrawer from './VersionsDrawer'
import TagEditor from './TagEditor'

export default function DocumentEditorPage() {
  const { wid, docId } = useParams<{ wid: string; docId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const id = Number(docId)

  const [content, setContent] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [tagsOpen, setTagsOpen] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [backlinksOpen, setBacklinksOpen] = useState(false)
  const [linksOpen, setLinksOpen] = useState(false)
  // 断链修复：旧标题 → 选中的目标文档 ID
  const [repairTargets, setRepairTargets] = useState<Record<string, number>>({})
  const [diffPair, setDiffPair] = useState<{ base: number; head: number } | null>(null)
  const baseTsRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)
  const taRef = useRef<TextAreaRef>(null)

  // 插入数据表引用辅助
  const [insertOpen, setInsertOpen] = useState(false)
  const [insertTableId, setInsertTableId] = useState<number | null>(null)
  const [insertLimit, setInsertLimit] = useState<number | null>(null)

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
      }),
    onSuccess: (doc: DocumentDetail) => {
      baseTsRef.current = doc.updated_at
      dirtyRef.current = false
      setSaveError(null)
      message.success(`已保存 v${doc.version_number ?? '?'}`)
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '保存失败'
      setSaveError(detail)
    },
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
    document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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

  const editable = true // viewer 的写请求会被后端 403，前端保持入口简洁

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
          <Button icon={<HistoryOutlined />} onClick={() => setVersionsOpen(true)}>
            版本{doc.version_count > 0 ? ` (${doc.version_count})` : ''}
          </Button>
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

      {doc.edit_lock && doc.edit_lock.user_id !== doc.updated_by_id && (
        <Alert
          type="info"
          showIcon
          message={`${doc.edit_lock.username} 正在编辑此文档（${doc.edit_lock.elapsed_seconds} 秒前开始）`}
          style={{ margin: '8px 24px 0' }}
        />
      )}

      {/* 分屏编辑/预览 */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <Splitter style={{ height: '100%' }}>
          <Splitter.Panel defaultSize="50%" min="20%" max="80%">
            <TextArea
              ref={taRef}
              value={content}
              onChange={e => {
                setContent(e.target.value)
                dirtyRef.current = true
              }}
              placeholder="输入 Markdown 内容…"
              style={{
                height: '100%',
                resize: 'none',
                border: 'none',
                boxShadow: 'none',
                fontFamily: 'var(--cn-mono, monospace)',
                fontSize: 14,
                lineHeight: 1.7,
                padding: 20,
              }}
            />
          </Splitter.Panel>
          <Splitter.Panel min="20%" max="80%">
            <div style={{ height: '100%', overflow: 'auto', padding: '20px 24px' }}>
              <MarkdownPreview content={content} workspaceId={workspaceId} onWikilink={handleWikilink} />
            </div>
          </Splitter.Panel>
        </Splitter>
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
