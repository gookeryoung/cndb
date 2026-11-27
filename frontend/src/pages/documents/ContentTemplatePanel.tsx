/** 内容模板面板（需求 0169 / ADR 0177 C3 / ADR 0185）.
 *
 * 内容模板是「从模板新建文档」用的工作区级 Markdown 正文骨架，与导出模板
 * （`ExportTemplatePanel` / ADR 0152）**模型独立**。两个面板由 `DocumentTemplatesPage` 按
 * `?kind=export|content` 切换，入口统一在文档区「内容模板 / 导出模板」页签（内容模板在前）。
 *
 * 左清单两组（ADR 0185 D5 / D6）：
 * - 「内置模板」按分类折叠分组，只读，带「内置」徽标；动作仅「另存为 / 导出 / 预览」；
 * - 「自定义模板」既有平铺 + 拖拽排序 + 副本 / 删除 / 保存，能力逐项不变（C6）。
 *
 * 选中态用 `selectedRef`（`builtin:<key>` / `custom:<id>`，D6），正文一律来自接口，
 * 前端不拼装内置正文（正文只维护一份，不进 bundle，H31）。
 *
 * 文件格式 `kind=cndb-content-template`，与排版模板文件互不兼容并明确报错。
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
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  DownOutlined,
  DownloadOutlined,
  FileTextOutlined,
  HolderOutlined,
  PlusOutlined,
  RightOutlined,
  SaveOutlined,
  SnippetsOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} from '@ant-design/icons'

import { contentTemplateApi, exportTemplateApi } from '@/api'
import type { BuiltinContentTemplate, ContentTemplateItem, ContentTemplateList } from '@/api'
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
import { hasHeadingNumbers, stripHeadingNumbers } from './contentTemplateNumbers'
import { readTextFile, suggestImportName } from './templateFile'
import { SPACE } from '@/theme/tokens'

const { Text } = Typography

interface Draft {
  name: string
  description: string
  icon: string
  sort_order: number
  export_template_ref: string | null
  content_markdown: string
}

const EMPTY_DRAFT: Draft = {
  name: '',
  description: '',
  icon: '',
  sort_order: 0,
  export_template_ref: null,
  content_markdown: '',
}

const BUILTIN_PREFIX = 'builtin:'
const CUSTOM_PREFIX = 'custom:'

const customRef = (id: number) => `${CUSTOM_PREFIX}${id}`

function toDraft(item: ContentTemplateItem): Draft {
  return {
    name: item.name,
    description: item.description ?? '',
    icon: item.icon ?? '',
    sort_order: item.sort_order ?? 0,
    export_template_ref: item.export_template_ref ?? null,
    content_markdown: item.content_markdown ?? '',
  }
}

function fromBuiltin(item: BuiltinContentTemplate): Draft {
  return {
    name: item.name,
    description: item.description ?? '',
    icon: item.icon ?? '',
    sort_order: item.sort_order ?? 0,
    export_template_ref: item.export_template_ref ?? null,
    content_markdown: item.content_markdown ?? '',
  }
}

/** 另存为的默认名（D5 / D8）：`原名（自定义）`，冲突时递增 */
function saveAsName(base: string, used: Set<string>): string {
  const stem = `${base}（自定义）`
  if (!used.has(stem)) return stem
  let seq = 2
  while (used.has(`${base}（自定义 ${seq}）`)) seq += 1
  return `${base}（自定义 ${seq}）`
}

export default function ContentTemplatePanel() {
  const { wid } = useParams<{ wid: string }>()
  const workspaceId = wid ?? ''
  const qc = useQueryClient()

  // 选中态（ADR 0185 D6）：`builtin:<key>` / `custom:<id>`
  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [editorMode, setEditorMode] = useState<MarkdownEditorMode>('live')
  // 编辑 / 预览（ADR 0177 C5）：预览只读渲染当前草稿正文，便于确认骨架效果
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit')
  // 切换模板时若有未保存修改，先挂起目标条目并弹确认（受控 Modal，便于测试）
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null)
  // 左栏分组折叠：内置分类各自独立 + 自定义一组，默认展开
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  // 导出模板候选（ADR 0177 C6）：内容模板可绑定一份排版模板，
  // 「从模板新建」时写入新文档，可作为文档级默认导出排版
  const exportTemplatesQuery = useQuery({
    queryKey: ['export-templates', Number(workspaceId)],
    queryFn: () => exportTemplateApi.list(workspaceId),
    staleTime: 0,
  })
  const exportTemplateOptions = exportTemplatesQuery.data?.items ?? []
  const exportTemplateLabel = (ref: string | null) => {
    if (!ref) return '跟随工作区默认'
    const found = exportTemplateOptions.find(option => option.ref === ref)
    return found ? `${found.source === 'builtin' ? '内置' : '自定义'} · ${found.name}` : ref
  }

  const templatesQuery = useQuery({
    queryKey: ['content-templates', workspaceId],
    queryFn: () => contentTemplateApi.list(workspaceId),
  })
  const items = useMemo(() => templatesQuery.data?.items ?? [], [templatesQuery.data])

  // 内置库（ADR 0185 D4）：独立只读端点，一次拿到全部分类 + 正文
  const builtinQuery = useQuery({
    queryKey: ['content-templates-builtin', workspaceId],
    queryFn: () => contentTemplateApi.listBuiltin(workspaceId),
    staleTime: Infinity,
  })
  const builtinCategories = useMemo(
    () => builtinQuery.data?.categories ?? [],
    [builtinQuery.data],
  )
  const builtinTemplates = useMemo(
    () => builtinCategories.flatMap(category => category.templates),
    [builtinCategories],
  )

  const selectedBuiltin = useMemo(
    () =>
      selectedRef?.startsWith(BUILTIN_PREFIX)
        ? builtinTemplates.find(template => template.ref === selectedRef) ?? null
        : null,
    [builtinTemplates, selectedRef],
  )
  const selectedCustom = useMemo(
    () =>
      selectedRef?.startsWith(CUSTOM_PREFIX)
        ? items.find(item => customRef(item.id) === selectedRef) ?? null
        : null,
    [items, selectedRef],
  )
  const isBuiltin = selectedBuiltin != null

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['content-templates', workspaceId] })

  /** 写成功后先把新行塞进缓存：否则 `items` 还没回读，选中态会被兜底 effect 改回旧条目 */
  const cacheItem = (item: ContentTemplateItem) => {
    qc.setQueryData<ContentTemplateList>(['content-templates', workspaceId], prev => {
      const list = prev?.items ?? []
      const next = list.some(it => it.id === item.id)
        ? list.map(it => (it.id === item.id ? item : it))
        : [...list, item]
      return { items: next, total: next.length }
    })
  }

  const dropCachedItem = (id: number) => {
    qc.setQueryData<ContentTemplateList>(['content-templates', workspaceId], prev => {
      const next = (prev?.items ?? []).filter(it => it.id !== id)
      return { items: next, total: next.length }
    })
  }

  const toSelection = (ref: string): Draft | null => {
    if (ref.startsWith(BUILTIN_PREFIX)) {
      const template = builtinTemplates.find(it => it.ref === ref)
      return template ? fromBuiltin(template) : null
    }
    const id = Number(ref.slice(CUSTOM_PREFIX.length))
    const item = items.find(it => it.id === id)
    return item ? toDraft(item) : null
  }

  // 首次加载 / 列表变化：默认选中首个自定义模板（与改造前一致），没有则选首个内置。
  // 两个查询都完成后再选，避免「谁先返回就选谁」造成选中态抖动。
  const listsReady = templatesQuery.isSuccess && builtinQuery.isSuccess
  useEffect(() => {
    if (!listsReady) return
    if (selectedRef != null && toSelection(selectedRef) != null) return
    const next = items.length > 0 ? customRef(items[0].id) : builtinTemplates[0]?.ref ?? null
    if (next === selectedRef) return
    setSelectedRef(next)
    const nextDraft = next == null ? null : toSelection(next)
    setDraft(nextDraft ?? EMPTY_DRAFT)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listsReady, items, builtinTemplates, selectedRef])

  const dirty = selectedCustom != null && (
    selectedCustom.name !== draft.name ||
    selectedCustom.description !== draft.description ||
    selectedCustom.icon !== draft.icon ||
    selectedCustom.sort_order !== draft.sort_order ||
    selectedCustom.export_template_ref !== draft.export_template_ref ||
    selectedCustom.content_markdown !== draft.content_markdown
  )

  const applySwitch = (ref: string) => {
    setSelectedRef(ref)
    setDraft(toSelection(ref) ?? EMPTY_DRAFT)
    setPendingSwitch(null)
  }

  /** 切换模板：有未保存修改时先确认，避免静默丢弃（内置只读，无需确认） */
  const select = (ref: string) => {
    if (ref === selectedRef) return
    if (dirty) {
      setPendingSwitch(ref)
      return
    }
    applySwitch(ref)
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
      cacheItem(item)
      invalidate()
      setSelectedRef(customRef(item.id))
      setDraft(toDraft(item))
      message.success(`已创建「${item.name}」`)
    },
    onError: () => message.error('创建失败'),
  })

  /** 另存为自定义（ADR 0185 D5）：以内置正文 + 元数据创建，名称默认 `原名（自定义）` 并递增 */
  const saveAsMut = useMutation({
    mutationFn: () => {
      if (!selectedBuiltin) throw new Error('未选中内置模板')
      const name = saveAsName(selectedBuiltin.name, new Set(items.map(item => item.name)))
      return contentTemplateApi.create(workspaceId, {
        name,
        description: selectedBuiltin.description ?? '',
        icon: selectedBuiltin.icon ?? '',
        content_markdown: selectedBuiltin.content_markdown,
        export_template_ref: selectedBuiltin.export_template_ref,
      })
    },
    onSuccess: item => {
      cacheItem(item)
      invalidate()
      setSelectedRef(customRef(item.id))
      setDraft(toDraft(item))
      message.success(`已另存为「${item.name}」`)
    },
    onError: () => message.error('另存为失败（名称可能重复或绑定非法）'),
  })

  const saveMut = useMutation({
    mutationFn: () => {
      if (selectedCustom == null) throw new Error('未选中模板')
      return contentTemplateApi.update(workspaceId, selectedCustom.id, draft)
    },
    onSuccess: () => {
      invalidate()
      message.success('已保存')
    },
    onError: () => message.error('保存失败'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => contentTemplateApi.remove(workspaceId, id),
    onSuccess: (_data, id) => {
      dropCachedItem(id)
      setSelectedRef(null)
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
      cacheItem(item)
      invalidate()
      setSelectedRef(customRef(item.id))
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
    const entry = selectedCustom
      ? {
          name: selectedCustom.name,
          description: selectedCustom.description,
          icon: selectedCustom.icon,
          content_markdown: selectedCustom.content_markdown,
        }
      : selectedBuiltin
        ? {
            name: selectedBuiltin.name,
            description: selectedBuiltin.description,
            icon: selectedBuiltin.icon,
            content_markdown: selectedBuiltin.content_markdown,
          }
        : null
    if (!entry) return
    downloadFile(contentTemplateFileText([entry]), contentTemplateFileName(entry.name))
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

  const toggleGroup = (key: string) =>
    setCollapsed(groups => ({ ...groups, [key]: !groups[key] }))

  const groupHeader = (key: string, label: string, count: number, testId: string) => (
    <button
      type="button"
      className="cn-doc-tpl-group"
      aria-expanded={!collapsed[key]}
      data-testid={testId}
      onClick={() => toggleGroup(key)}
    >
      <span className="cn-doc-tpl-group-title">
        {collapsed[key] ? <RightOutlined /> : <DownOutlined />}
        {label}
      </span>
      <span>{count}</span>
    </button>
  )

  const builtinRowNode = (template: BuiltinContentTemplate) => {
    const active = template.ref === selectedRef
    return (
      <div
        key={template.ref}
        role="button"
        tabIndex={0}
        data-testid={`content-template-builtin-${template.key}`}
        className={['cn-qc-row', 'cn-qc-row--selectable', active ? 'cn-qc-row--active' : '']
          .filter(Boolean)
          .join(' ')}
        onClick={() => select(template.ref)}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') select(template.ref)
        }}
      >
        <CnListMeta
          avatar={template.icon || <FileTextOutlined />}
          title={
            <span className="cn-doc-tpl-row-title">
              <Text strong={active}>{template.name}</Text>
              <Tag>内置</Tag>
            </span>
          }
          description={template.description || `${template.content_markdown.length} 字符`}
        />
      </div>
    )
  }

  const customRowNode = (item: ContentTemplateItem, index: number) => {
    const active = customRef(item.id) === selectedRef
    return (
      <div
        key={item.id}
        role="button"
        tabIndex={0}
        draggable
        data-testid={`content-template-row-${item.id}`}
        data-drag-over={dropIndex === index ? 'true' : undefined}
        className={[
          'cn-qc-row cn-qc-row--selectable cn-qc-row--draggable',
          active ? 'cn-qc-row--active' : '',
          dropIndex === index && dragIndex !== index ? 'cn-qc-row--drop' : '',
        ].filter(Boolean).join(' ')}
        onClick={() => select(customRef(item.id))}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') select(customRef(item.id))
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
    )
  }

  const totalCount = items.length + builtinTemplates.length

  /** 内置条目只读详情：元数据 + 绑定说明 + 正文预览，动作仅「另存为 / 导出」（D5） */
  const builtinDetail = selectedBuiltin && (
    <>
      <Space size={SPACE.sm} wrap>
        <Tag>内置 · 只读</Tag>
        <Tag>{selectedBuiltin.export_template_ref ?? '跟随工作区默认'}</Tag>
        <Tooltip title="以当前正文另建一份可编辑的自定义模板（名称自动加「（自定义）」）">
          <Button
            size="small"
            type="primary"
            icon={<CopyOutlined />}
            data-testid="content-template-save-as"
            loading={saveAsMut.isPending}
            onClick={() => saveAsMut.mutate()}
          >
            另存为自定义
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
      </Space>
      <div className="cn-doc-tpl-meta">
        <div>
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-2xs)' }}>说明</Text>
          <div>{selectedBuiltin.description || '—'}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-2xs)' }}>绑定排版模板</Text>
          <div data-testid="content-template-builtin-binding">
            {exportTemplateLabel(selectedBuiltin.export_template_ref)}
          </div>
        </div>
      </div>
      <div style={{ border: '1px solid var(--cn-border)', borderRadius: 'var(--cn-radius-base)' }}>
        <div
          data-testid="content-template-preview"
          style={{ padding: `${SPACE.md}px ${SPACE.lg}px`, minHeight: 320 }}
        >
          <MarkdownPreview
            content={selectedBuiltin.content_markdown}
            workspaceId={Number(workspaceId)}
          />
        </div>
      </div>
    </>
  )

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
          <Tooltip title="把本工作区全部自定义内容模板导出为一个 JSON 文件">
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
            count={totalCount}
            testId="content-template-list"
            empty={
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="内置库与自定义模板都为空"
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
            {groupHeader('builtin', '内置模板', builtinTemplates.length, 'content-template-group-builtin')}
            {!collapsed.builtin &&
              builtinCategories.map(category => (
                <div key={category.key} data-testid={`content-template-category-${category.key}`}>
                  <button
                    type="button"
                    className="cn-doc-tpl-group"
                    aria-expanded={!collapsed[category.key]}
                    data-testid={`content-template-category-toggle-${category.key}`}
                    onClick={() => toggleGroup(category.key)}
                  >
                    <span className="cn-doc-tpl-group-title">
                      {collapsed[category.key] ? <RightOutlined /> : <DownOutlined />}
                      {category.name}
                    </span>
                    <span>{category.templates.length}</span>
                  </button>
                  {!collapsed[category.key] && category.templates.map(builtinRowNode)}
                </div>
              ))}
            {groupHeader('custom', '自定义模板', items.length, 'content-template-group-custom')}
            {!collapsed.custom &&
              (items.length === 0 ? (
                <div className="cn-doc-tpl-empty">
                  <Text type="secondary">还没有自定义模板：选一个内置模板后点「另存为自定义」，或直接「新建模板」。</Text>
                </div>
              ) : (
                items.map(customRowNode)
              ))}
          </TemplateListBox>
        </div>

        <div style={{ flex: '2 1 480px', minWidth: 0 }}>
          <SectionBox
            title={
              selectedCustom != null
                ? draft.name || '未命名模板'
                : selectedBuiltin != null
                  ? selectedBuiltin.name
                  : '模板内容'
            }
            icon={<FileTextOutlined />}
            extra={
              selectedCustom == null ? null : (
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
                      onClick={() => duplicateMut.mutate(selectedCustom.id)}
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
                    onConfirm={() => deleteMut.mutate(selectedCustom.id)}
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
            {selectedRef == null ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧模板，或新建首个模板" />
            ) : isBuiltin ? (
              <Space orientation="vertical" size={SPACE.md} style={{ width: '100%' }}>
                {builtinDetail}
              </Space>
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
                    <Select
                      allowClear
                      style={{ flex: '2 1 220px' }}
                      placeholder="排版模板（可选，决定导出 Word / PDF 的版式）"
                      data-testid="content-template-export-template"
                      value={draft.export_template_ref ?? undefined}
                      options={exportTemplateOptions.map(item => ({
                        value: item.ref,
                        label: item.source === 'builtin' ? `内置 · ${item.name}` : `自定义 · ${item.name}`,
                      }))}
                      onChange={value => setDraft({ ...draft, export_template_ref: value ?? null })}
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
                    <Space size={SPACE.sm}>
                      <Tooltip title="把标题行开头的手写序号（一、/ 3.1 / 第一章）去掉：编号交给导出模板，避免导出时重复">
                        <Button
                          size="small"
                          data-testid="content-template-strip-numbers"
                          disabled={!hasHeadingNumbers(draft.content_markdown)}
                          onClick={() => {
                            const result = stripHeadingNumbers(draft.content_markdown)
                            if (result.changed === 0) return
                            setDraft(prev => ({ ...prev, content_markdown: result.text }))
                            message.success(`已去除 ${result.changed} 个标题序号，保存后生效`)
                          }}
                        >
                          去除标题序号
                        </Button>
                      </Tooltip>
                      <Segmented
                        size="small"
                        value={editorMode}
                        options={[
                          { label: '实时', value: 'live' },
                          { label: '源码', value: 'source' },
                        ]}
                        onChange={value => setEditorMode(value as MarkdownEditorMode)}
                      />
                    </Space>
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
