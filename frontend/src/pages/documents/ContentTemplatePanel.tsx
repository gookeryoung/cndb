/** 内容模板面板（需求 0169 / ADR 0177 C3）.
 *
 * 内容模板是「从模板新建文档」用的工作区级 Markdown 正文骨架，与导出模板
 * （`ExportTemplatePanel` / ADR 0152）**模型独立**：本面板不参与导出、无内置预设、
 * 无默认锚点，空态引导用户自建首个模板。两个面板由 `DocumentTemplatesPage` 按
 * `?kind=export|content` 切换，入口统一在文档区「导出模板 / 内容模板」页签。
 *
 * 布局沿用文档区双栏原语：左 `SectionBox flush` 清单（选中左边条 + 主题选中底色 + 拖拽排序），
 * 右 `SectionBox` 编辑（元数据 + MarkdownLiveEditor 正文 / 只读预览）。颜色 / 间距全走 --cn-* token。
 *
 * 能力对齐（ADR 0177 C5）：与导出模板一致提供 JSON 导入 / 导出、创建副本、Markdown 预览、
 * 拖拽排序；文件格式 `kind=cndb-content-template`，与排版模板文件互不兼容并明确报错。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FileTextOutlined,
  HolderOutlined,
  PlusOutlined,
  SaveOutlined,
  SnippetsOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} from '@ant-design/icons'

import { contentTemplateApi } from '@/api'
import type { ContentTemplateItem } from '@/api'
import CnListMeta from '@/components/CnListMeta'
import MarkdownLiveEditor, { type MarkdownEditorMode } from '@/components/Document/MarkdownLiveEditor'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import SectionBox from '@/components/SectionBox'
import TemplateListBox from '@/components/Template/TemplateListBox'
import {
  contentTemplateFileName,
  contentTemplateFileText,
  parseContentTemplateFile,
} from './contentTemplateFile'
import { readTextFile, suggestImportName } from './templateFile'
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

export default function ContentTemplatePanel() {
  const { wid } = useParams<{ wid: string }>()
  const workspaceId = wid ?? ''
  const qc = useQueryClient()

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [editorMode, setEditorMode] = useState<MarkdownEditorMode>('live')
  // 编辑 / 预览（ADR 0177 C5）：预览只读渲染当前草稿正文，便于确认骨架效果
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit')
  // 切换模板时若有未保存修改，先挂起目标条目并弹确认（受控 Modal，便于测试）
  const [pendingSwitch, setPendingSwitch] = useState<ContentTemplateItem | null>(null)

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

  const applySwitch = (item: ContentTemplateItem) => {
    setSelectedId(item.id)
    setDraft(toDraft(item))
    setPendingSwitch(null)
  }

  /** 切换模板：有未保存修改时先确认，避免静默丢弃 */
  const select = (item: ContentTemplateItem) => {
    if (item.id === selectedId) return
    if (dirty) {
      setPendingSwitch(item)
      return
    }
    applySwitch(item)
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

  /** 创建副本（ADR 0177 C5）：服务端生成「原名 副本」并递增，建完直接选中副本 */
  const duplicateMut = useMutation({
    mutationFn: (id: number) => contentTemplateApi.duplicate(workspaceId, id),
    onSuccess: item => {
      invalidate()
      setSelectedId(item.id)
      setDraft(toDraft(item))
      message.success(`已创建副本「${item.name}」`)
    },
    onError: () => message.error('创建副本失败'),
  })

  /** 拖拽排序：按落点重排后把顺序写成 10 的倍数，只 PATCH 真正变了的条目 */
  const reorderMut = useMutation({
    mutationFn: async (ordered: ContentTemplateItem[]) => {
      const changed = ordered
        .map((item, index) => ({ item, sortOrder: index * 10 }))
        .filter(({ item, sortOrder }) => item.sort_order !== sortOrder)
      for (const { item, sortOrder } of changed) {
        await contentTemplateApi.update(workspaceId, item.id, { sort_order: sortOrder })
      }
      return changed.length
    },
    onSuccess: () => invalidate(),
    onError: () => {
      // 排序失败时回读服务端顺序，避免界面停在「看起来已排序」的假状态
      invalidate()
      message.error('保存排序失败')
    },
  })

  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)

  const onDropRow = (targetIndex: number) => {
    const from = dragIndex
    setDragIndex(null)
    setDropIndex(null)
    if (from == null || from === targetIndex) return
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(targetIndex, 0, moved)
    reorderMut.mutate(next)
  }

  // 导入 / 导出（ADR 0177 C5）：导出当前模板或全部；导入逐条创建，同名自动加「（导入）」
  const importInputRef = useRef<HTMLInputElement | null>(null)
  const [importing, setImporting] = useState(false)

  const downloadFile = (text: string, filename: string) => {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const exportCurrent = () => {
    const entry = selectedId == null ? null : items.find(it => it.id === selectedId)
    if (!entry) return
    downloadFile(
      contentTemplateFileText([
        {
          name: entry.name,
          description: entry.description,
          icon: entry.icon,
          content_markdown: entry.content_markdown,
        },
      ]),
      contentTemplateFileName(entry.name),
    )
    message.success('模板文件已导出')
  }

  const exportAll = () => {
    if (items.length === 0) return
    downloadFile(
      contentTemplateFileText(
        items.map(it => ({
          name: it.name,
          description: it.description,
          icon: it.icon,
          content_markdown: it.content_markdown,
        })),
      ),
      contentTemplateFileName('', true),
    )
    message.success(`已导出 ${items.length} 个模板`)
  }

  const importFromFile = async (file: File) => {
    setImporting(true)
    try {
      const entries = parseContentTemplateFile(await readTextFile(file))
      const used = new Set(items.map(it => it.name))
      const created: string[] = []
      const failed: string[] = []
      for (const entry of entries) {
        const name = suggestImportName(entry.name, used)
        used.add(name)
        try {
          await contentTemplateApi.create(workspaceId, {
            name,
            description: entry.description ?? '',
            icon: entry.icon ?? '',
            content_markdown: entry.content_markdown,
          })
          created.push(name)
        } catch {
          failed.push(entry.name)
        }
      }
      invalidate()
      if (failed.length === 0) {
        message.success(`已导入 ${created.length} 个模板`)
      } else {
        message.warning(`已导入 ${created.length} 个模板，${failed.length} 个失败（名称或内容不合法）`)
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '模板文件导入失败')
    } finally {
      setImporting(false)
      if (importInputRef.current) importInputRef.current.value = ''
    }
  }

  return (
    <div className="cn-page" data-testid="document-content-templates-page">
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><SnippetsOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">内容模板</h1>
            <div className="cn-page-head-sub">「从模板新建」套用的 Markdown 正文骨架；与「导出模板」（Word / PDF 排版）互不影响</div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <input
            ref={importInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: 'none' }}
            data-testid="content-template-import-input"
            onChange={e => {
              const file = e.target.files?.[0]
              if (file) void importFromFile(file)
            }}
          />
          <Button
            icon={<UploadOutlined />}
            data-testid="content-template-import"
            loading={importing}
            onClick={() => importInputRef.current?.click()}
          >
            导入
          </Button>
          <Tooltip title="把本工作区全部内容模板导出为一个 JSON 文件">
            <Button
              icon={<DownloadOutlined />}
              data-testid="content-template-export-all"
              disabled={items.length === 0}
              onClick={exportAll}
            >
              导出全部
            </Button>
          </Tooltip>
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
          <TemplateListBox
            icon={<UnorderedListOutlined />}
            count={items.length}
            testId="content-template-list"
            empty={
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
            }
          >
            {items.map((item, index) => (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                draggable
                data-testid={`content-template-row-${item.id}`}
                data-drag-over={dropIndex === index ? 'true' : undefined}
                className={[
                  'cn-qc-row cn-qc-row--selectable cn-qc-row--draggable',
                  selectedId === item.id ? 'cn-qc-row--active' : '',
                  dropIndex === index && dragIndex !== index ? 'cn-qc-row--drop' : '',
                ].filter(Boolean).join(' ')}
                onClick={() => select(item)}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') select(item)
                }}
                onDragStart={() => setDragIndex(index)}
                onDragEnd={() => {
                  setDragIndex(null)
                  setDropIndex(null)
                }}
                onDragOver={e => {
                  // 不 preventDefault 浏览器就禁止 drop（HTML5 DnD 约定）
                  e.preventDefault()
                  setDropIndex(index)
                }}
                onDrop={e => {
                  e.preventDefault()
                  onDropRow(index)
                }}
              >
                <span className="cn-qc-row-handle" aria-hidden data-testid={`content-template-handle-${item.id}`}>
                  <HolderOutlined />
                </span>
                <CnListMeta
                  avatar={<FileTextOutlined />}
                  title={item.name}
                  description={item.description || `${item.content_markdown.length} 字符`}
                />
              </div>
            ))}
          </TemplateListBox>
        </div>

        <div style={{ flex: '2 1 480px', minWidth: 0 }}>
          <SectionBox
            title={selectedId == null ? '模板内容' : draft.name || '未命名模板'}
            icon={<FileTextOutlined />}
            extra={
              selectedId == null ? null : (
                <Space size={SPACE.sm}>
                  <Segmented
                    size="small"
                    value={viewMode}
                    data-testid="content-template-view"
                    options={[
                      { label: '编辑', value: 'edit' },
                      { label: '预览', value: 'preview' },
                    ]}
                    onChange={value => setViewMode(value as 'edit' | 'preview')}
                  />
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
                  <Tooltip title="以「原名 副本」创建一份新模板">
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      data-testid="content-template-duplicate"
                      loading={duplicateMut.isPending}
                      onClick={() => duplicateMut.mutate(selectedId)}
                    >
                      副本
                    </Button>
                  </Tooltip>
                  <Tooltip title="导出为模板文件（JSON，可分享 / 带到别的工作区）">
                    <Button
                      size="small"
                      icon={<DownloadOutlined />}
                      data-testid="content-template-export"
                      onClick={exportCurrent}
                    >
                      导出
                    </Button>
                  </Tooltip>
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
                {viewMode === 'edit' && (
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
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                    {viewMode === 'preview'
                      ? '预览：新建文档时将写入的正文骨架（只读）'
                      : '正文在「从模板新建文档」时作为初始 Markdown 写入；左侧清单可拖拽排序'}
                  </Text>
                  {viewMode === 'edit' && (
                    <Segmented
                      size="small"
                      value={editorMode}
                      options={[
                        { label: '实时', value: 'live' },
                        { label: '源码', value: 'source' },
                      ]}
                      onChange={value => setEditorMode(value as MarkdownEditorMode)}
                    />
                  )}
                </div>
                <div style={{ border: '1px solid var(--cn-border)', borderRadius: 'var(--cn-radius-base)' }}>
                  {viewMode === 'preview' ? (
                    <div
                      data-testid="content-template-preview"
                      style={{ padding: `${SPACE.md}px ${SPACE.lg}px`, minHeight: 320 }}
                    >
                      {draft.content_markdown.trim() ? (
                        <MarkdownPreview content={draft.content_markdown} workspaceId={Number(workspaceId)} />
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="正文为空，没有可预览的内容" />
                      )}
                    </div>
                  ) : (
                    <MarkdownLiveEditor
                      value={draft.content_markdown}
                      mode={editorMode}
                      workspaceId={workspaceId}
                      placeholder="用 Markdown 写模板正文，例如会议纪要 / 周报骨架"
                      onChange={value => setDraft(prev => ({ ...prev, content_markdown: value }))}
                      style={{ minHeight: 320 }}
                    />
                  )}
                </div>
              </Space>
            )}
          </SectionBox>
        </div>
      </div>

      <Modal
        open={pendingSwitch != null}
        title="放弃未保存的修改？"
        okText="放弃并切换"
        cancelText="继续编辑"
        onOk={() => pendingSwitch && applySwitch(pendingSwitch)}
        onCancel={() => setPendingSwitch(null)}
        destroyOnHidden
      >
        切换模板后，当前未保存的名称与正文不会保留。
      </Modal>
    </div>
  )
}
