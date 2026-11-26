/** 文档内容模板页（需求 0169）.
 *
 * 内容模板是「从模板新建文档」用的工作区级 Markdown 正文骨架，与导出排版模板
 * （`DocumentTemplatesPage` / ADR 0152）完全独立：本页不参与导出、无内置预设、
 * 无默认锚点，空态引导用户自建首个模板。
 *
 * 布局沿用文档区双栏原语：左 `SectionBox flush` 清单（选中左边条 + 主题选中底色），
 * 右 `SectionBox` 编辑（元数据 + MarkdownLiveEditor 正文）。颜色 / 间距全走 --cn-* token。
 */

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Typography,
  message,
} from 'antd'
import {
  DeleteOutlined,
  FileTextOutlined,
  PlusOutlined,
  SaveOutlined,
  SnippetsOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'

import { contentTemplateApi } from '@/api'
import type { ContentTemplateItem } from '@/api'
import CnListMeta from '@/components/CnListMeta'
import MarkdownLiveEditor, { type MarkdownEditorMode } from '@/components/Document/MarkdownLiveEditor'
import SectionBox from '@/components/SectionBox'
import { SPACE } from '@/theme/tokens'

const { Text } = Typography

interface Draft {
  name: string
  description: string
  icon: string
  sort_order: number
  content_markdown: string
}

const EMPTY_DRAFT: Draft = {
  name: '',
  description: '',
  icon: '',
  sort_order: 0,
  content_markdown: '',
}

function toDraft(item: ContentTemplateItem): Draft {
  return {
    name: item.name,
    description: item.description ?? '',
    icon: item.icon ?? '',
    sort_order: item.sort_order ?? 0,
    content_markdown: item.content_markdown ?? '',
  }
}

export default function DocumentContentTemplatesPage() {
  const { wid } = useParams<{ wid: string }>()
  const workspaceId = wid ?? ''
  const qc = useQueryClient()

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [editorMode, setEditorMode] = useState<MarkdownEditorMode>('live')

  const templatesQuery = useQuery({
    queryKey: ['content-templates', workspaceId],
    queryFn: () => contentTemplateApi.list(workspaceId),
  })
  const items = useMemo(() => templatesQuery.data?.items ?? [], [templatesQuery.data])

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['content-templates', workspaceId] })

  useEffect(() => {
    if (items.length === 0) {
      setSelectedId(null)
      setDraft(EMPTY_DRAFT)
      return
    }
    if (selectedId == null || !items.some(it => it.id === selectedId)) {
      setSelectedId(items[0].id)
      setDraft(toDraft(items[0]))
    }
  }, [items, selectedId])

  const select = (item: ContentTemplateItem) => {
    setSelectedId(item.id)
    setDraft(toDraft(item))
  }

  /** 新建时生成工作区内唯一默认名：未命名模板 / 未命名模板 2 …（避免第二个必 400） */
  const nextTemplateName = () => {
    const used = new Set(items.map(item => item.name))
    if (!used.has('未命名模板')) return '未命名模板'
    let seq = 2
    while (used.has(`未命名模板 ${seq}`)) seq += 1
    return `未命名模板 ${seq}`
  }

  const createMut = useMutation({
    mutationFn: () =>
      contentTemplateApi.create(workspaceId, {
        name: nextTemplateName(),
        content_markdown: '# 标题\n\n正文',
      }),
    onSuccess: item => {
      invalidate()
      setSelectedId(item.id)
      setDraft(toDraft(item))
      message.success(`已创建「${item.name}」`)
    },
    onError: () => message.error('创建失败'),
  })

  const saveMut = useMutation({
    mutationFn: () => {
      if (selectedId == null) throw new Error('未选中模板')
      return contentTemplateApi.update(workspaceId, selectedId, draft)
    },
    onSuccess: () => {
      invalidate()
      message.success('已保存')
    },
    onError: () => message.error('保存失败'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => contentTemplateApi.remove(workspaceId, id),
    onSuccess: () => {
      setSelectedId(null)
      setDraft(EMPTY_DRAFT)
      invalidate()
      message.success('已删除')
    },
    onError: () => message.error('删除失败'),
  })

  const dirty = selectedId != null && items.some(it => {
    if (it.id !== selectedId) return false
    return (
      it.name !== draft.name ||
      it.description !== draft.description ||
      it.icon !== draft.icon ||
      it.sort_order !== draft.sort_order ||
      it.content_markdown !== draft.content_markdown
    )
  })

  return (
    <div className="cn-page" data-testid="document-content-templates-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><SnippetsOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">内容模板</h1>
            <div className="cn-page-head-sub">新建文档时套用的 Markdown 正文骨架；与导出排版模板互不影响</div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            data-testid="content-template-create"
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            新建模板
          </Button>
        </div>
      </header>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: SPACE.md, alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 260px', minWidth: 0 }}>
          <SectionBox
            title="模板清单"
            icon={<UnorderedListOutlined />}
            extra={<span>{items.length} 个</span>}
            flush
            testId="content-template-list"
          >
            {items.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="还没有内容模板"
                style={{ padding: SPACE.lg }}
              >
                <Button
                  type="primary"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => createMut.mutate()}
                >
                  创建首个模板
                </Button>
              </Empty>
            ) : (
              items.map(item => (
                <div
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  data-testid={`content-template-row-${item.id}`}
                  className={`cn-qc-row cn-qc-row--selectable${selectedId === item.id ? ' cn-qc-row--active' : ''}`}
                  onClick={() => select(item)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') select(item)
                  }}
                >
                  <CnListMeta
                    avatar={<FileTextOutlined />}
                    title={item.name}
                    description={item.description || `${item.content_markdown.length} 字符`}
                  />
                </div>
              ))
            )}
          </SectionBox>
        </div>

        <div style={{ flex: '2 1 480px', minWidth: 0 }}>
          <SectionBox
            title={selectedId == null ? '模板内容' : draft.name || '未命名模板'}
            icon={<FileTextOutlined />}
            extra={
              selectedId == null ? null : (
                <Space size={SPACE.sm}>
                  <Button
                    size="small"
                    icon={<SaveOutlined />}
                    data-testid="content-template-save"
                    disabled={!dirty}
                    loading={saveMut.isPending}
                    onClick={() => saveMut.mutate()}
                  >
                    保存
                  </Button>
                  <Popconfirm
                    title={`删除「${draft.name || '未命名模板'}」？`}
                    description="已用该模板创建的文档不受影响"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => deleteMut.mutate(selectedId)}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      data-testid="content-template-delete"
                      loading={deleteMut.isPending}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              )
            }
            testId="content-template-editor"
          >
            {selectedId == null ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧模板，或新建首个模板" />
            ) : (
              <Space orientation="vertical" size={SPACE.md} style={{ width: '100%' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: SPACE.sm }}>
                  <Input
                    style={{ flex: '2 1 200px' }}
                    placeholder="模板名称"
                    value={draft.name}
                    data-testid="content-template-name"
                    onChange={e => setDraft({ ...draft, name: e.target.value })}
                  />
                  <Input
                    style={{ flex: '1 1 120px' }}
                    placeholder="图标（可选）"
                    value={draft.icon}
                    onChange={e => setDraft({ ...draft, icon: e.target.value })}
                  />
                  <Input
                    style={{ flex: '2 1 200px' }}
                    placeholder="说明（可选）"
                    value={draft.description}
                    onChange={e => setDraft({ ...draft, description: e.target.value })}
                  />
                  <Input
                    type="number"
                    style={{ flex: '0 1 90px' }}
                    placeholder="排序"
                    value={draft.sort_order}
                    onChange={e => setDraft({ ...draft, sort_order: Number(e.target.value) || 0 })}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                    正文在「从模板新建文档」时作为初始 Markdown 写入
                  </Text>
                  <Segmented
                    size="small"
                    value={editorMode}
                    options={[
                      { label: '实时', value: 'live' },
                      { label: '源码', value: 'source' },
                    ]}
                    onChange={value => setEditorMode(value as MarkdownEditorMode)}
                  />
                </div>
                <div style={{ border: '1px solid var(--cn-border)', borderRadius: 'var(--cn-radius-base)' }}>
                  <MarkdownLiveEditor
                    value={draft.content_markdown}
                    mode={editorMode}
                    workspaceId={workspaceId}
                    placeholder="用 Markdown 写模板正文，例如会议纪要 / 周报骨架"
                    onChange={value => setDraft(prev => ({ ...prev, content_markdown: value }))}
                    style={{ minHeight: 320 }}
                  />
                </div>
              </Space>
            )}
          </SectionBox>
        </div>
      </div>
    </div>
  )
}
