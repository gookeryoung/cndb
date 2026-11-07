/** 工作区模板结构化编辑器（ADR 0121）：目录 / 编辑 / 检查预览三栏. */

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { App as AntApp, Button, Drawer, Input, Modal, Space, Tag, Typography } from 'antd'
import {
  ApartmentOutlined, AppstoreOutlined, CodeOutlined, DownOutlined, FileTextOutlined, PlusOutlined,
  SaveOutlined, SearchOutlined, TableOutlined,
} from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceTemplateApi } from '@/api'
import type { TemplatePreview, WorkspaceTemplate } from '@/api'
import {
  draftFromSpec, draftToSpec, emptyDocument, emptyFlow, emptyForm, emptyStage, emptyDraft,
  issueTarget, validateDraft,
} from './templateDraft'
import type { DraftDocument, DraftFlow, DraftForm, TemplateDraft } from './templateDraft'
import {
  DocumentSection, FlowSection, FormSection, MetaSection, StageSection,
  deleteDraftDocument, deleteDraftFlow, deleteDraftForm,
} from './TemplateEditorSections'
import TemplateCheckPanel from './TemplateCheckPanel'
import TemplateJsonTab from './TemplateJsonTab'

const { Text } = Typography

interface Props {
  open: boolean
  /** 正在编辑的模板；null 表示新建 */
  template: WorkspaceTemplate | null
  /** 新建时用来预填内容的模板（复制内置模板为自定义模板） */
  seed?: WorkspaceTemplate | null
  onClose: () => void
  onSaved?: (template: WorkspaceTemplate) => void
}

function initialDraft(template: WorkspaceTemplate | null, seed?: WorkspaceTemplate | null): TemplateDraft {
  const source = template ?? seed ?? null
  if (!source) return emptyDraft()
  return draftFromSpec(source.spec, {
    name: template?.name ?? `${seed?.name ?? ''}（副本）`,
    description: source.description,
    category: source.category,
    modules: source.modules,
  })
}

function baselineOf(draft: TemplateDraft): string {
  return JSON.stringify({
    name: draft.name,
    description: draft.description,
    category: draft.category,
    modules: draft.modules,
    spec: draftToSpec(draft),
  })
}

const DRAFT_STORAGE_PREFIX = 'cndb_template_draft_v1'

interface StoredDraft {
  draft: TemplateDraft
  summary: string
  savedAt: string
}

function draftStorageKey(template: WorkspaceTemplate | null): string {
  return `${DRAFT_STORAGE_PREFIX}:${template?.id ?? 'new'}:${template?.version ?? 0}`
}

function readStoredDraft(key: string): StoredDraft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredDraft
    if (!parsed || typeof parsed !== 'object' || !parsed.draft) return null
    if (!Array.isArray(parsed.draft.forms) || !Array.isArray(parsed.draft.stages)) return null
    return parsed
  } catch {
    return null
  }
}

export default function TemplateEditorDrawer({ open, template, seed, onClose, onSaved }: Props) {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<TemplateDraft>(() => initialDraft(template, seed))
  const [baseline, setBaseline] = useState(() => baselineOf(initialDraft(template, seed)))
  const [active, setActive] = useState('overview')
  const [summary, setSummary] = useState('')
  const [preview, setPreview] = useState<TemplatePreview | null>(null)
  const [force, setForce] = useState(false)
  const [serverError, setServerError] = useState('')
  const [keyword, setKeyword] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const next = initialDraft(template, seed)
    const stored = readStoredDraft(draftStorageKey(template))
    setDraft(stored?.draft ?? next)
    setBaseline(baselineOf(next))
    setActive('overview')
    setSummary(stored?.summary ?? '')
    setDraftSavedAt(stored?.savedAt ?? null)
    setPreview(null)
    setForce(false)
    setServerError('')
    setKeyword('')
    setCollapsed({})
    if (stored) message.info('已恢复上次未保存的本地草稿')
  }, [open, template, seed, message])

  const issues = useMemo(() => validateDraft(draft), [draft])
  const dirty = useMemo(() => baselineOf(draft) !== baseline || summary.trim() !== '', [draft, baseline, summary])

  /** 立即把当前草稿写入本机：不依赖校验结果，允许保存未完成 / 有问题的复杂模板。 */
  const persistDraft = (notify: boolean) => {
    const savedAt = new Date().toISOString()
    try {
      const payload: StoredDraft = { draft, summary, savedAt }
      localStorage.setItem(draftStorageKey(template), JSON.stringify(payload))
      setDraftSavedAt(savedAt)
      if (notify) message.success('草稿已保存到本机，下次打开可继续编辑')
      return true
    } catch {
      if (notify) message.error('本机存储不可用（隐私模式或空间不足），草稿未能保存')
      return false
    }
  }

  // 编辑中的草稿按「模板 id + 版本」暂存到本地，防误关丢失；保存成功或回到初始态时清除。
  useEffect(() => {
    if (!open) return
    const key = draftStorageKey(template)
    if (!dirty) {
      localStorage.removeItem(key)
      setDraftSavedAt(null)
      return
    }
    const timer = window.setTimeout(() => persistDraft(false), 800)
    return () => window.clearTimeout(timer)
    // persistDraft 只读当前 draft / summary，依赖已由下面列出
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, template, draft, summary, dirty])

  const updateDraft = (fn: (current: TemplateDraft) => TemplateDraft) => {
    setDraft(fn)
    setPreview(null)
    setForce(false)
    setServerError('')
  }

  const addForm = () => {
    const form = emptyForm(draft.forms.map(item => item.key), draft.forms.map(item => item.name))
    updateDraft(current => ({ ...current, forms: [...current.forms, form] }))
    setActive(`form:${form.uid}`)
  }
  const addDocument = () => {
    const doc = emptyDocument(draft.documents.map(item => item.key), draft.documents.map(item => item.title))
    updateDraft(current => ({ ...current, documents: [...current.documents, doc] }))
    setActive(`doc:${doc.uid}`)
  }
  const addStage = () => {
    const stage = emptyStage(draft.stages.map(item => item.key), draft.stages.map(item => item.name))
    updateDraft(current => ({ ...current, stages: [...current.stages, stage] }))
    setActive(`stage:${stage.uid}`)
  }
  const addFlow = () => {
    const flow = emptyFlow(draft.flows.map(item => item.key), draft.flows.map(item => item.name))
    updateDraft(current => ({ ...current, flows: [...current.flows, flow] }))
    setActive(`flow:${flow.uid}`)
  }

  const confirmDeleteForm = (form: DraftForm) => Modal.confirm({
    title: `删除表单「${form.name}」？`,
    content: '阶段与流程中的引用会被清除；已有工作区的旧表与数据不会删除。',
    okText: '删除',
    okButtonProps: { danger: true },
    cancelText: '取消',
    onOk: () => {
      updateDraft(current => deleteDraftForm(current, form))
      setActive('overview')
    },
  })
  const confirmDeleteDocument = (doc: DraftDocument) => Modal.confirm({
    title: `删除文档规则「${doc.title}」？`,
    content: '阶段与流程中的引用会被清除；已有文档不会被删除。',
    okText: '删除',
    okButtonProps: { danger: true },
    cancelText: '取消',
    onOk: () => {
      updateDraft(current => deleteDraftDocument(current, doc))
      setActive('overview')
    },
  })
  const confirmDeleteFlow = (flow: DraftFlow) => Modal.confirm({
    title: `删除流程「${flow.name}」？`,
    content: '只会删除流程展示，不影响表单、文档与阶段。',
    okText: '删除',
    okButtonProps: { danger: true },
    cancelText: '取消',
    onOk: () => {
      updateDraft(current => deleteDraftFlow(current, flow))
      setActive('overview')
    },
  })

  const spec = useMemo(() => draftToSpec(draft), [draft])

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!template) throw new Error('新建模板暂无历史版本，可直接保存')
      return workspaceTemplateApi.preview(template.id, spec)
    },
    onSuccess: (data) => {
      setPreview(data)
      setServerError('')
      if (data.requires_force) message.warning('检测到破坏性变更：确认后勾选「我已知晓影响」再保存')
      else message.success('预览完成：变更非破坏')
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : '预览失败'
      setServerError(msg)
      message.error(msg)
    },
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!draft.name.trim()) throw new Error('请填写模板名称')
      if (!template) {
        await workspaceTemplateApi.validate(spec)
        return workspaceTemplateApi.create({
          name: draft.name.trim(),
          description: draft.description,
          category: draft.category,
          spec,
          change_summary: summary.trim() || '初始版本',
        })
      }
      return workspaceTemplateApi.update(template.id, {
        name: draft.name.trim(),
        description: draft.description,
        category: draft.category,
        spec,
        change_summary: summary.trim() || undefined,
        force,
      })
    },
    onSuccess: (result) => {
      const saved = 'template' in result ? result.template : result
      const sync = 'sync' in result ? result.sync : undefined
      message.success(
        sync
          ? `模板已保存；已同步 ${sync.created_tables} 张表 / ${sync.added_fields} 个字段 / ${sync.created_documents} 份文档`
          : '模板已创建',
      )
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
      localStorage.removeItem(draftStorageKey(template))
      setBaseline(baselineOf(draft))
      setSummary('')
      onSaved?.(saved)
      onClose()
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      if (detail && typeof detail === 'object' && 'diff' in detail && 'impact' in detail) {
        const d = detail as { diff: TemplatePreview['diff']; impact: TemplatePreview['impact']; requires_force: boolean }
        setPreview({ diff: d.diff, impact: d.impact, requires_force: d.requires_force, spec })
        message.warning('模板变更包含破坏性影响，请查看预览后勾选确认')
        return
      }
      const msg = err instanceof Error ? err.message : '保存失败'
      setServerError(msg)
      message.error(msg)
    },
  })

  const submitting = saveMutation.isPending || previewMutation.isPending

  const save = async () => {
    if (issues.length) {
      setActive(issueTarget(issues[0]))
      message.error(`还有 ${issues.length} 个结构问题，请先修正`)
      return
    }
    if (!draft.name.trim()) {
      setActive('overview')
      message.error('请填写模板名称')
      return
    }
    if (template && !preview) {
      try {
        const data = await workspaceTemplateApi.preview(template.id, spec)
        setPreview(data)
        if (data.requires_force) {
          message.warning('检测到破坏性变更，请查看预览并勾选确认')
          return
        }
        saveMutation.mutate()
      } catch (err) {
        const msg = err instanceof Error ? err.message : '预览失败'
        setServerError(msg)
        message.error(msg)
      }
      return
    }
    if (preview?.requires_force && !force) {
      message.warning('请先勾选「我已知晓影响」再保存')
      return
    }
    saveMutation.mutate()
  }

  const close = () => {
    if (!dirty) {
      onClose()
      return
    }
    Modal.confirm({
      title: '关闭编辑？',
      content: '当前修改还未生成新版本。如需下次继续编辑，请先点「保存草稿」；选择「放弃修改」会清除本机草稿。',
      okText: '放弃修改',
      okButtonProps: { danger: true },
      cancelText: '继续编辑',
      onOk: () => {
        localStorage.removeItem(draftStorageKey(template))
        onClose()
      },
    })
  }

  const issueCount = (scope: string, uid?: string) => issues.filter(issue => (
    issue.scope === scope && (!uid || issue.uid === uid)
  )).length

  const normalizedKeyword = keyword.trim().toLowerCase()
  const matchText = (text: string) => !normalizedKeyword || text.toLowerCase().includes(normalizedKeyword)
  const visibleStages = draft.stages.filter(stage => matchText(`${stage.name} ${stage.key}`))
  const visibleForms = draft.forms.filter(form => matchText(`${form.name} ${form.key}`))
  const visibleDocuments = draft.documents.filter(doc => matchText(`${doc.title} ${doc.key}`))
  const visibleFlows = draft.flows.filter(flow => matchText(`${flow.name} ${flow.key}`))
  const groupOpen = (group: string) => !!normalizedKeyword || !collapsed[group]
  const toggleGroup = (group: string) => setCollapsed(current => ({ ...current, [group]: !current[group] }))
  const noMatch = !!normalizedKeyword
    && !visibleStages.length && !visibleForms.length && !visibleDocuments.length && !visibleFlows.length

  const renderMain = () => {
    if (active === 'json') {
      return (
        <TemplateJsonTab
          draft={draft}
          onApply={next => {
            setDraft(next)
            setPreview(null)
            setForce(false)
            setServerError('')
            setActive('overview')
            message.success('JSON 已应用到结构化草稿')
          }}
        />
      )
    }
    if (active.startsWith('stage')) {
      return <StageSection draft={draft} onDraft={updateDraft} activeUid={active.startsWith('stage:') ? active.slice(6) : undefined} />
    }
    if (active.startsWith('form') || active === 'forms') {
      const uid = active.startsWith('form:') ? active.slice(5) : draft.forms[0]?.uid
      return (
        <FormSection
          draft={draft}
          onDraft={updateDraft}
          formUid={uid}
          onAddForm={addForm}
          onDeleteForm={confirmDeleteForm}
        />
      )
    }
    if (active.startsWith('doc')) {
      return (
        <DocumentSection
          draft={draft}
          onDraft={updateDraft}
          activeUid={active.startsWith('doc:') ? active.slice(4) : undefined}
          onDeleteDocument={confirmDeleteDocument}
        />
      )
    }
    if (active.startsWith('flow')) {
      return (
        <FlowSection
          draft={draft}
          onDraft={updateDraft}
          activeUid={active.startsWith('flow:') ? active.slice(5) : undefined}
          onDeleteFlow={confirmDeleteFlow}
        />
      )
    }
    return (
      <MetaSection
        draft={draft}
        onDraft={updateDraft}
        changeSummary={summary}
        onChangeSummary={setSummary}
      />
    )
  }

  return (
    <Drawer
      open={open}
      onClose={close}
      width="96vw"
      rootClassName="cn-tpl-editor-drawer"
      destroyOnHidden
      title={template ? `编辑模板：${template.name}（v${template.version}）` : '新建工作区模板'}
      extra={(
        <Space>
          {draftSavedAt && (
            <Text type="secondary" className="cn-tpl-draft-saved" title={new Date(draftSavedAt).toLocaleString()}>
              草稿已存本机
            </Text>
          )}
          <Button
            icon={<SaveOutlined />}
            onClick={() => persistDraft(true)}
            disabled={!dirty}
            data-testid="template-save-draft-btn"
          >
            保存草稿
          </Button>
          <Button onClick={close}>取消</Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={save}
            disabled={issues.length > 0}
            data-testid="template-save-btn"
          >
            {template ? '保存并同步' : '创建模板'}
          </Button>
        </Space>
      )}
    >
      <div className="cn-tpl-editor" data-testid="template-editor-drawer">
        <aside className="cn-tpl-outline" aria-label="模板目录">
          <Input
            allowClear
            size="small"
            prefix={<SearchOutlined />}
            placeholder="搜索阶段 / 表单 / 文档 / 流程"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            aria-label="搜索模板结构"
            data-testid="template-outline-search"
          />
          <button type="button" className={`cn-tpl-outline-item ${active === 'overview' ? 'is-active' : ''}`} onClick={() => setActive('overview')}>
            <AppstoreOutlined /> 概览
          </button>

          <OutlineGroup
            title="阶段"
            icon={<ApartmentOutlined />}
            count={issueCount('stages')}
            onAdd={addStage}
            active={active === 'stages'}
            onSelect={() => setActive('stages')}
            open={groupOpen('stages')}
            onToggle={() => toggleGroup('stages')}
          />
          {groupOpen('stages') && visibleStages.map(stage => (
            <button
              key={stage.uid}
              type="button"
              className={`cn-tpl-outline-sub ${active === `stage:${stage.uid}` ? 'is-active' : ''}`}
              onClick={() => setActive(`stage:${stage.uid}`)}
            >
              <span>{stage.name || '未命名阶段'}</span>
              {issueCount('stages', stage.uid) > 0 && <Tag color="red">{issueCount('stages', stage.uid)}</Tag>}
            </button>
          ))}

          <OutlineGroup
            title="表单"
            icon={<TableOutlined />}
            count={issueCount('forms')}
            onAdd={addForm}
            active={active === 'forms'}
            onSelect={() => setActive(draft.forms[0] ? `form:${draft.forms[0].uid}` : 'forms')}
            open={groupOpen('forms')}
            onToggle={() => toggleGroup('forms')}
          />
          {groupOpen('forms') && visibleForms.map(form => (
            <button
              key={form.uid}
              type="button"
              data-testid={`outline-form-${form.key}`}
              className={`cn-tpl-outline-sub ${active === `form:${form.uid}` ? 'is-active' : ''}`}
              onClick={() => setActive(`form:${form.uid}`)}
            >
              <span>{form.name || '未命名表单'}</span>
              {issueCount('forms', form.uid) > 0 && <Tag color="red">{issueCount('forms', form.uid)}</Tag>}
            </button>
          ))}

          <OutlineGroup
            title="文档"
            icon={<FileTextOutlined />}
            count={issueCount('documents')}
            onAdd={addDocument}
            active={active === 'documents'}
            onSelect={() => setActive('documents')}
            open={groupOpen('documents')}
            onToggle={() => toggleGroup('documents')}
          />
          {groupOpen('documents') && visibleDocuments.map(doc => (
            <button
              key={doc.uid}
              type="button"
              className={`cn-tpl-outline-sub ${active === `doc:${doc.uid}` ? 'is-active' : ''}`}
              onClick={() => setActive(`doc:${doc.uid}`)}
            >
              <span>{doc.title || '未命名文档'}</span>
              {issueCount('documents', doc.uid) > 0 && <Tag color="red">{issueCount('documents', doc.uid)}</Tag>}
            </button>
          ))}

          <OutlineGroup
            title="流程"
            icon={<ApartmentOutlined />}
            count={issueCount('flows')}
            onAdd={addFlow}
            active={active === 'flows'}
            onSelect={() => setActive('flows')}
            open={groupOpen('flows')}
            onToggle={() => toggleGroup('flows')}
          />
          {groupOpen('flows') && visibleFlows.map(flow => (
            <button
              key={flow.uid}
              type="button"
              className={`cn-tpl-outline-sub ${active === `flow:${flow.uid}` ? 'is-active' : ''}`}
              onClick={() => setActive(`flow:${flow.uid}`)}
            >
              <span>{flow.name || '未命名流程'}</span>
              {issueCount('flows', flow.uid) > 0 && <Tag color="red">{issueCount('flows', flow.uid)}</Tag>}
            </button>
          ))}

          {noMatch && <Text type="secondary" className="cn-tpl-outline-empty">没有匹配「{keyword.trim()}」的结构</Text>}

          <button type="button" className={`cn-tpl-outline-item ${active === 'json' ? 'is-active' : ''}`} onClick={() => setActive('json')}>
            <CodeOutlined /> JSON（高级）
          </button>
          {serverError && <Text type="danger" className="cn-tpl-outline-error">{serverError}</Text>}
        </aside>

        <main className="cn-tpl-editor-main">{renderMain()}</main>

        <aside className="cn-tpl-editor-side">
          <TemplateCheckPanel
            draft={draft}
            issues={issues}
            onJump={issue => setActive(issueTarget(issue))}
            isEditing={!!template}
            preview={preview}
            previewing={previewMutation.isPending}
            force={force}
            onForceChange={setForce}
            onPreview={() => previewMutation.mutate()}
          />
        </aside>
      </div>
    </Drawer>
  )
}

function OutlineGroup({
  title, icon, count, onAdd, active, onSelect, open, onToggle,
}: {
  title: string
  icon: ReactNode
  count: number
  onAdd: () => void
  active: boolean
  onSelect: () => void
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="cn-tpl-outline-group">
      <Button
        size="small"
        type="text"
        className="cn-tpl-outline-toggle"
        icon={<DownOutlined rotate={open ? 0 : -90} />}
        aria-label={`${open ? '收起' : '展开'}${title}`}
        aria-expanded={open}
        onClick={onToggle}
      />
      <button type="button" className={`cn-tpl-outline-item ${active ? 'is-active' : ''}`} onClick={onSelect}>
        {icon} {title} {count > 0 && <Tag color="red">{count}</Tag>}
      </button>
      <Button
        size="small"
        type="text"
        icon={<PlusOutlined />}
        aria-label={`新增${title}`}
        onClick={onAdd}
      />
    </div>
  )
}
