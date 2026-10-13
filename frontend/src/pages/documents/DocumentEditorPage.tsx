/** 文档编辑页 — 分屏编辑/预览 + 版本历史 + 标签 + 乐观锁保存. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Drawer,
  Divider,
  Input,
  Popconfirm,
  Space,
  Splitter,
  Tabs,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckOutlined,
  HistoryOutlined,
  SaveOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import { documentsApi } from '@/api/documents'
import type { DocumentDetail, TagItem, VersionItem } from '@/api/documents'

const { Text, Title } = Typography
const { TextArea } = Input

/** 简易 unified diff 渲染（行级着色） */
function DiffView({ diff }: { diff: string }) {
  const lines = useMemo(() => diff.split('\n'), [diff])
  return (
    <pre
      style={{
        fontSize: 12,
        lineHeight: 1.6,
        fontFamily: 'var(--cn-mono, monospace)',
        overflow: 'auto',
        maxHeight: 480,
        padding: 12,
        background: 'var(--cn-bg-secondary, #f6f6f6)',
        borderRadius: 8,
      }}
    >
      {lines.map((line, i) => {
        const color = line.startsWith('+') && !line.startsWith('+++')
          ? '#2e7d32'
          : line.startsWith('-') && !line.startsWith('---')
            ? '#c62828'
            : undefined
        const bg = color ? (line.startsWith('+') ? '#e8f5e9' : '#ffebee') : undefined
        return (
          <div key={i} style={{ color, background: bg, whiteSpace: 'pre-wrap' }}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}

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
  const [diffPair, setDiffPair] = useState<{ base: number; head: number } | null>(null)
  const baseTsRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)

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
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/w/${workspaceId}/documents`)}>
            返回列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>{doc.title}</Title>
          <Tag>{doc.status === 'published' ? '已发布' : doc.status === 'archived' ? '归档' : '草稿'}</Tag>
          {dirtyRef.current && <Text type="warning" style={{ fontSize: 12 }}>未保存</Text>}
        </Space>
        <Space wrap>
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
              <MarkdownPreview content={content} />
            </div>
          </Splitter.Panel>
        </Splitter>
      </div>

      {/* 版本抽屉 */}
      <Drawer
        title="版本历史"
        width={520}
        open={versionsOpen}
        onClose={() => {
          setVersionsOpen(false)
          setDiffPair(null)
        }}
      >
        <Tabs
          items={[
            {
              key: 'list',
              label: '时间线',
              children:
                versionsQuery.isLoading ? (
                  <div>加载中…</div>
                ) : versionTimeline.length <= 1 ? (
                  <Text type="secondary">暂无历史版本（首次保存后自动创建）</Text>
                ) : (
                  <Timeline items={versionTimeline} />
                ),
            },
            {
              key: 'diff',
              label: '差异对比',
              children: diffPair ? (
                diffQuery.isLoading ? (
                  <div>计算差异中…</div>
                ) : (
                  <>
                    <Space style={{ marginBottom: 12 }}>
                      <Text strong>
                        v{diffPair.base} → v{diffPair.head}
                      </Text>
                      {diffQuery.data && (
                        <>
                          <Tag color="green">+{diffQuery.data.added}</Tag>
                          <Tag color="red">-{diffQuery.data.removed}</Tag>
                        </>
                      )}
                    </Space>
                    <DiffView diff={diffQuery.data?.diff ?? ''} />
                  </>
                )
              ) : (
                <Text type="secondary">在时间线中点击「与上一版对比」查看差异</Text>
              ),
            },
          ]}
        />
      </Drawer>

      {/* 标签抽屉 */}
      <Drawer title="文档标签" width={420} open={tagsOpen} onClose={() => setTagsOpen(false)}>
        <TagEditor
          workspaceId={workspaceId}
          allTags={tagsQuery.data ?? []}
          selectedIds={doc.tag_ids}
          onChange={ids => setDocTagsMut.mutate(ids)}
        />
      </Drawer>
    </div>
  )
}

/** 标签选择器 + 新建 */
function TagEditor({
  workspaceId,
  allTags,
  selectedIds,
  onChange,
}: {
  workspaceId: number
  allTags: TagItem[]
  selectedIds: number[]
  onChange: (ids: number[]) => void
}) {
  const qc = useQueryClient()
  const [newName, setNewName] = useState('')

  const createMut = useMutation({
    mutationFn: () => documentsApi.createTag(workspaceId, { name: newName.trim() }),
    onSuccess: tag => {
      setNewName('')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, 'tags'] })
      onChange([...selectedIds, tag.id])
    },
    onError: () => message.error('创建标签失败（可能重名）'),
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Input
          placeholder="新标签名称"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onPressEnter={() => newName.trim() && createMut.mutate()}
        />
        <Button type="primary" disabled={!newName.trim()} loading={createMut.isPending} onClick={() => createMut.mutate()}>
          添加
        </Button>
      </div>
      <Divider style={{ margin: '8px 0' }} />
      {allTags.length === 0 ? (
        <Text type="secondary">暂无标签，先创建一个</Text>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {allTags.map(tag => {
            const checked = selectedIds.includes(tag.id)
            return (
              <Tag.CheckableTag
                key={tag.id}
                checked={checked}
                onChange={checkedNow => {
                  onChange(
                    checkedNow ? [...selectedIds, tag.id] : selectedIds.filter(x => x !== tag.id),
                  )
                }}
                style={{ fontSize: 13, padding: '4px 12px', borderColor: tag.color }}
              >
                {tag.name} ({tag.doc_count})
              </Tag.CheckableTag>
            )
          })}
        </div>
      )}
      {selectedIds.length > 0 && (
        <>
          <Divider style={{ margin: '16px 0 8px' }} />
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={() => {
              onChange(selectedIds)
              message.success('标签已保存')
            }}
          >
            完成
          </Button>
        </>
      )}
    </div>
  )
}
