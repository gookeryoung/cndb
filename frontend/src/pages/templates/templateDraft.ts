/** 模板结构化编辑的草稿模型（ADR 0121）.
 *
 * 结构化视图与 JSON 高级页签共用这一份草稿；`draftToSpec` 是唯一序列化入口。
 * 本地校验只用于即时定位，最终以服务端 `normalize_spec` 为准。
 */

import type {
  TemplateSpec, TemplateSpecDocument, TemplateSpecField, TemplateSpecFlow,
  TemplateSpecForm, TemplateSpecFormFlow, TemplateSpecGroup, TemplateSpecStage, TemplateSpecFlowStep,
} from '@/api/types'
import { DEFAULT_WORKSPACE_MODULES, normalizeModules } from '@/utils/workspaceModules'
import { FIELD_TYPE_OPTIONS } from '@/utils/fieldTypeMeta'

export type DraftScope = 'meta' | 'spec' | 'forms' | 'documents' | 'stages' | 'flows'

export interface DraftIssue {
  path: string
  message: string
  scope: DraftScope
  uid?: string
  formUid?: string
  fieldUid?: string
}

export interface DraftMeta {
  name: string
  description: string
  category: string
  modules: string[]
}

export interface DraftField extends TemplateSpecField {
  uid: string
}

export interface DraftForm extends Omit<TemplateSpecForm, 'fields' | 'flow'> {
  uid: string
  fields: DraftField[]
  flow?: TemplateSpecFormFlow
}

export interface DraftDocument extends TemplateSpecDocument {
  uid: string
}

export interface DraftStage extends Omit<TemplateSpecStage, 'order'> {
  uid: string
}

export interface DraftStep extends TemplateSpecFlowStep {
  uid: string
}

export interface DraftFlow extends Omit<TemplateSpecFlow, 'steps'> {
  uid: string
  steps: DraftStep[]
}

export interface TemplateDraft extends DraftMeta {
  forms: DraftForm[]
  documents: DraftDocument[]
  stages: DraftStage[]
  flows: DraftFlow[]
}

const KEY_RE = /^[\w\-\u4e00-\u9fa5]+$/u
const TYPE_ALIAS: Record<string, string> = {
  long_text: 'longtext',
  decimal: 'float',
  multi_select: 'multiselect',
}
const TYPE_VALUES = new Set<string>([
  ...FIELD_TYPE_OPTIONS.map(o => o.value as string),
  'lookup',
])

let uidSeed = 0

function newUid(prefix: string): string {
  uidSeed += 1
  return `${prefix}-${Date.now().toString(36)}-${uidSeed}`
}

export function nextKey(prefix: string, existing: Iterable<string>): string {
  const used = new Set(existing)
  let index = used.size + 1
  let key = `${prefix}_${index}`
  while (used.has(key)) {
    index += 1
    key = `${prefix}_${index}`
  }
  return key
}

export function normalizeFieldType(type: string): string {
  return TYPE_ALIAS[type] ?? type
}

export function emptyField(existingNames: string[] = []): DraftField {
  let index = existingNames.length + 1
  let name = `字段${index}`
  while (existingNames.includes(name)) {
    index += 1
    name = `字段${index}`
  }
  return { uid: newUid('field'), name, type: 'text', required: false, is_unique: false, hidden: false, config: {} }
}

export function emptyForm(existingKeys: string[], existingNames: string[] = []): DraftForm {
  let index = existingNames.length + 1
  let name = `表单${index}`
  while (existingNames.includes(name)) {
    index += 1
    name = `表单${index}`
  }
  const field = emptyField()
  return {
    uid: newUid('form'),
    key: nextKey('form', existingKeys),
    name,
    description: '',
    fields: [field],
  }
}

export function emptyDocument(existingKeys: string[], existingTitles: string[] = []): DraftDocument {
  let index = existingTitles.length + 1
  let title = `文档${index}`
  while (existingTitles.includes(title)) {
    index += 1
    title = `文档${index}`
  }
  return {
    uid: newUid('doc'),
    key: nextKey('doc', existingKeys),
    title,
    required: true,
    naming: '',
    content: '',
  }
}

export function emptyStage(existingKeys: string[], existingNames: string[] = []): DraftStage {
  let index = existingNames.length + 1
  let name = `阶段${index}`
  while (existingNames.includes(name)) {
    index += 1
    name = `阶段${index}`
  }
  return {
    uid: newUid('stage'),
    key: nextKey('stage', existingKeys),
    name,
    description: '',
    forms: [],
    documents: [],
  }
}

export function emptyFlow(existingKeys: string[], existingNames: string[] = []): DraftFlow {
  let index = existingNames.length + 1
  let name = `流程${index}`
  while (existingNames.includes(name)) {
    index += 1
    name = `流程${index}`
  }
  const step: DraftStep = {
    uid: newUid('step'),
    key: 'step_1',
    name: '步骤1',
    description: '',
    form: null,
    documents: [],
  }
  return {
    uid: newUid('flow'),
    key: nextKey('flow', existingKeys),
    name,
    description: '',
    stage: null,
    steps: [step],
  }
}

export function emptyDraft(): TemplateDraft {
  const form = emptyForm([], [])
  const stage = emptyStage([], [])
  stage.forms = [form.key]
  return {
    name: '',
    description: '',
    category: '',
    modules: [...DEFAULT_WORKSPACE_MODULES],
    forms: [form],
    documents: [],
    stages: [stage],
    flows: [],
  }
}

export function draftFromSpec(
  spec: TemplateSpec | null | undefined,
  meta: { name?: string; description?: string; category?: string; modules?: string[] } = {},
): TemplateDraft {
  const forms: DraftForm[] = (spec?.forms ?? []).map((form, index) => ({
    uid: newUid('form'),
    key: form.key || `form_${index + 1}`,
    name: form.name || `表单${index + 1}`,
    description: form.description ?? '',
    fields: (form.fields ?? []).map((field, fIndex) => ({
      ...field,
      uid: newUid('field'),
      name: field.name || `字段${fIndex + 1}`,
      type: normalizeFieldType(field.type || 'text'),
      config: { ...(field.config ?? {}) },
    })),
    flow: form.flow ? cloneFlowConfig(form.flow) : undefined,
  }))
  const documents: DraftDocument[] = (spec?.documents ?? []).map((doc, index) => ({
    uid: newUid('doc'),
    ...doc,
    key: doc.key || `doc_${index + 1}`,
    title: doc.title || `文档${index + 1}`,
  }))
  const stages: DraftStage[] = (spec?.stages ?? []).map((stage, index) => ({
    uid: newUid('stage'),
    key: stage.key || `stage_${index + 1}`,
    name: stage.name || `阶段${index + 1}`,
    description: stage.description ?? '',
    forms: [...(stage.forms ?? [])],
    documents: [...(stage.documents ?? [])],
  }))
  const flows: DraftFlow[] = (spec?.flows ?? []).map((flow, index) => ({
    uid: newUid('flow'),
    key: flow.key || `flow_${index + 1}`,
    name: flow.name || `流程${index + 1}`,
    description: flow.description ?? '',
    stage: flow.stage ?? null,
    steps: (flow.steps ?? []).map((step, sIndex) => ({
      uid: newUid('step'),
      key: step.key || `step_${sIndex + 1}`,
      name: step.name || `步骤${sIndex + 1}`,
      description: step.description ?? '',
      form: step.form ?? null,
      documents: [...(step.documents ?? [])],
    })),
  }))
  return {
    name: meta.name ?? '',
    description: meta.description ?? '',
    category: meta.category ?? '',
    modules: normalizeModules(meta.modules),
    forms,
    documents,
    stages,
    flows,
  }
}

function cloneFlowConfig(flow: TemplateSpecFormFlow): TemplateSpecFormFlow {
  return {
    ...flow,
    list_fields: [...(flow.list_fields ?? [])],
    search_fields: [...(flow.search_fields ?? [])],
    form_groups: (flow.form_groups ?? []).map(g => ({ title: g.title, fields: [...g.fields] })),
    detail_groups: (flow.detail_groups ?? []).map(g => ({ title: g.title, fields: [...g.fields] })),
    hints: { ...(flow.hints ?? {}) },
    default_values: { ...(flow.default_values ?? {}) },
    default_sort: flow.default_sort ? { ...flow.default_sort } : null,
  }
}

export function defaultFormFlow(fields: DraftField[]): TemplateSpecFormFlow {
  const names = fields.filter(f => !f.hidden).map(f => f.name)
  const allNames = fields.map(f => f.name)
  const searchable = fields
    .filter(f => !f.hidden && ['text', 'longtext', 'email', 'url', 'phone', 'select', 'multiselect'].includes(f.type))
    .map(f => f.name)
  const group: TemplateSpecGroup = { title: '基本信息', fields: names.length ? names : allNames }
  return {
    enabled: true,
    list_fields: (names.slice(0, 6).length ? names.slice(0, 6) : allNames.slice(0, 6)),
    search_fields: (searchable.slice(0, 3).length ? searchable.slice(0, 3) : names.slice(0, 3)),
    form_groups: [{ ...group, fields: [...group.fields] }],
    detail_groups: [{ title: group.title, fields: [...group.fields] }],
    hints: {},
    default_values: {},
    allow_create: true,
    allow_edit: true,
    allow_delete: true,
    default_sort: null,
    empty_text: '',
  }
}

export function formFlow(form: DraftForm): TemplateSpecFormFlow {
  return form.flow ?? defaultFormFlow(form.fields)
}

export function draftToSpec(draft: TemplateDraft): TemplateSpec {
  return {
    forms: draft.forms.map(form => ({
      key: form.key,
      name: form.name,
      description: form.description ?? '',
      fields: form.fields.map(({ uid: _uid, ...field }) => ({
        ...field,
        config: { ...(field.config ?? {}) },
      })),
      ...(form.flow ? { flow: cloneFlowConfig(form.flow) } : {}),
    })),
    documents: draft.documents.map(({ uid: _uid, ...doc }) => ({
      ...doc,
      required: doc.required ?? true,
      naming: doc.naming ?? '',
      content: doc.content ?? '',
    })),
    stages: draft.stages.map(({ uid: _uid, ...stage }, index) => ({
      ...stage,
      order: index + 1,
      forms: [...stage.forms],
      documents: [...stage.documents],
    })),
    flows: draft.flows.map(({ uid: _uid, steps, ...flow }) => ({
      ...flow,
      steps: steps.map(({ uid: _stepUid, ...step }) => ({
        ...step,
        documents: [...(step.documents ?? [])],
      })),
    })),
  }
}

export function serializeDraftJson(draft: TemplateDraft): string {
  return JSON.stringify(draftToSpec(draft), null, 2)
}

function keyIssue(key: string): string | null {
  if (!key) return 'key 不能为空'
  if (!KEY_RE.test(key)) return '只能包含字母 / 数字 / 下划线 / 连字符 / 中文，且不超过 64 字符'
  if (key.length > 64) return 'key 不能超过 64 字符'
  return null
}

export function validateDraft(draft: TemplateDraft): DraftIssue[] {
  const issues: DraftIssue[] = []
  if (!draft.name.trim()) {
    issues.push({ path: 'name', message: '模板名称不能为空', scope: 'meta' })
  }
  if (!draft.forms.length && !draft.documents.length) {
    issues.push({ path: 'spec', message: '至少定义一个表单或文档规则', scope: 'spec' })
  }
  if (!draft.stages.length) {
    issues.push({ path: 'stages', message: '至少定义一个生命周期阶段', scope: 'stages' })
  }

  const formKeys = new Set<string>()
  const formNames = new Set<string>()
  draft.forms.forEach((form, index) => {
    const path = `forms[${index}]`
    const keyError = keyIssue(form.key)
    if (keyError) issues.push({ path: `${path}.key`, message: keyError, scope: 'forms', uid: form.uid })
    else if (formKeys.has(form.key)) {
      issues.push({ path: `${path}.key`, message: `表单 key 重复：${form.key}`, scope: 'forms', uid: form.uid })
    }
    formKeys.add(form.key)
    if (!form.name.trim()) {
      issues.push({ path: `${path}.name`, message: '表单名称不能为空', scope: 'forms', uid: form.uid })
    } else if (formNames.has(form.name.trim())) {
      issues.push({ path: `${path}.name`, message: `表单名重复：${form.name}`, scope: 'forms', uid: form.uid })
    }
    formNames.add(form.name.trim())

    if (!form.fields.length) {
      issues.push({ path: `${path}.fields`, message: '至少定义一个字段', scope: 'forms', uid: form.uid })
    }
    const fieldNames = new Set<string>()
    form.fields.forEach((field, fIndex) => {
      const fieldPath = `${path}.fields[${fIndex}]`
      if (!field.name.trim()) {
        issues.push({
          path: `${fieldPath}.name`, message: '字段名不能为空', scope: 'forms',
          uid: form.uid, formUid: form.uid, fieldUid: field.uid,
        })
      } else if (fieldNames.has(field.name.trim())) {
        issues.push({
          path: `${fieldPath}.name`, message: `字段名重复：${field.name}`, scope: 'forms',
          uid: form.uid, formUid: form.uid, fieldUid: field.uid,
        })
      }
      fieldNames.add(field.name.trim())
      if (!TYPE_VALUES.has(normalizeFieldType(field.type))) {
        issues.push({
          path: `${fieldPath}.type`, message: `未知字段类型：${field.type}`, scope: 'forms',
          uid: form.uid, formUid: form.uid, fieldUid: field.uid,
        })
      }
      if (field.config != null && typeof field.config !== 'object') {
        issues.push({
          path: `${fieldPath}.config`, message: '字段配置必须是对象', scope: 'forms',
          uid: form.uid, formUid: form.uid, fieldUid: field.uid,
        })
      }
    })

    const flow = form.flow
    if (flow) {
      validateFlowRefs(flow, form, `${path}.flow`, issues)
    }
  })

  const docKeys = new Set<string>()
  const docTitles = new Set<string>()
  draft.documents.forEach((doc, index) => {
    const path = `documents[${index}]`
    const keyError = keyIssue(doc.key)
    if (keyError) issues.push({ path: `${path}.key`, message: keyError, scope: 'documents', uid: doc.uid })
    else if (docKeys.has(doc.key)) {
      issues.push({ path: `${path}.key`, message: `文档 key 重复：${doc.key}`, scope: 'documents', uid: doc.uid })
    }
    docKeys.add(doc.key)
    if (!doc.title.trim()) {
      issues.push({ path: `${path}.title`, message: '文档标题不能为空', scope: 'documents', uid: doc.uid })
    } else if (docTitles.has(doc.title.trim())) {
      issues.push({ path: `${path}.title`, message: `文档标题重复：${doc.title}`, scope: 'documents', uid: doc.uid })
    }
    docTitles.add(doc.title.trim())
  })

  const stageKeys = new Set<string>()
  const usedForms = new Set<string>()
  const usedDocs = new Set<string>()
  draft.stages.forEach((stage, index) => {
    const path = `stages[${index}]`
    const keyError = keyIssue(stage.key)
    if (keyError) issues.push({ path: `${path}.key`, message: keyError, scope: 'stages', uid: stage.uid })
    else if (stageKeys.has(stage.key)) {
      issues.push({ path: `${path}.key`, message: `阶段 key 重复：${stage.key}`, scope: 'stages', uid: stage.uid })
    }
    stageKeys.add(stage.key)
    if (!stage.name.trim()) {
      issues.push({ path: `${path}.name`, message: '阶段名称不能为空', scope: 'stages', uid: stage.uid })
    }
    const seenForms = new Set<string>()
    stage.forms.forEach(ref => {
      if (!formKeys.has(ref)) {
        issues.push({ path: `${path}.forms`, message: `引用了不存在的表单：${ref}`, scope: 'stages', uid: stage.uid })
      } else if (seenForms.has(ref)) {
        issues.push({ path: `${path}.forms`, message: `表单重复引用：${ref}`, scope: 'stages', uid: stage.uid })
      }
      seenForms.add(ref)
      usedForms.add(ref)
    })
    const seenDocs = new Set<string>()
    stage.documents.forEach(ref => {
      if (!docKeys.has(ref)) {
        issues.push({ path: `${path}.documents`, message: `引用了不存在的文档规则：${ref}`, scope: 'stages', uid: stage.uid })
      } else if (seenDocs.has(ref)) {
        issues.push({ path: `${path}.documents`, message: `文档规则重复引用：${ref}`, scope: 'stages', uid: stage.uid })
      }
      seenDocs.add(ref)
      usedDocs.add(ref)
    })
  })

  const flowKeys = new Set<string>()
  draft.flows.forEach((flow, index) => {
    const path = `flows[${index}]`
    const keyError = keyIssue(flow.key)
    if (keyError) issues.push({ path: `${path}.key`, message: keyError, scope: 'flows', uid: flow.uid })
    else if (flowKeys.has(flow.key)) {
      issues.push({ path: `${path}.key`, message: `流程 key 重复：${flow.key}`, scope: 'flows', uid: flow.uid })
    }
    flowKeys.add(flow.key)
    if (!flow.name.trim()) {
      issues.push({ path: `${path}.name`, message: '流程名称不能为空', scope: 'flows', uid: flow.uid })
    }
    if (flow.stage && !stageKeys.has(flow.stage)) {
      issues.push({ path: `${path}.stage`, message: `引用了不存在的阶段：${flow.stage}`, scope: 'flows', uid: flow.uid })
    }
    if (!flow.steps.length) {
      issues.push({ path: `${path}.steps`, message: '至少定义一个流程步骤', scope: 'flows', uid: flow.uid })
    }
    const stepKeys = new Set<string>()
    flow.steps.forEach((step, sIndex) => {
      const stepPath = `${path}.steps[${sIndex}]`
      const stepKeyError = keyIssue(step.key)
      if (stepKeyError) {
        issues.push({ path: `${stepPath}.key`, message: stepKeyError, scope: 'flows', uid: flow.uid })
      } else if (stepKeys.has(step.key)) {
        issues.push({ path: `${stepPath}.key`, message: `步骤 key 重复：${step.key}`, scope: 'flows', uid: flow.uid })
      }
      stepKeys.add(step.key)
      if (!step.name.trim()) {
        issues.push({ path: `${stepPath}.name`, message: '步骤名称不能为空', scope: 'flows', uid: flow.uid })
      }
      if (step.form) {
        if (!formKeys.has(step.form)) {
          issues.push({ path: `${stepPath}.form`, message: `引用了不存在的表单：${step.form}`, scope: 'flows', uid: flow.uid })
        } else {
          usedForms.add(step.form)
        }
      }
      const seenDocs = new Set<string>()
      ;(step.documents ?? []).forEach(ref => {
        if (!docKeys.has(ref)) {
          issues.push({ path: `${stepPath}.documents`, message: `引用了不存在的文档规则：${ref}`, scope: 'flows', uid: flow.uid })
        } else if (seenDocs.has(ref)) {
          issues.push({ path: `${stepPath}.documents`, message: `文档规则重复引用：${ref}`, scope: 'flows', uid: flow.uid })
        }
        seenDocs.add(ref)
        usedDocs.add(ref)
      })
    })
  })

  const orphanForms = [...formKeys].filter(key => !usedForms.has(key))
  if (orphanForms.length) {
    issues.push({
      path: 'forms', message: `表单未被任何阶段 / 流程引用：${orphanForms.join(', ')}`, scope: 'forms',
    })
  }
  const orphanDocs = [...docKeys].filter(key => !usedDocs.has(key))
  if (orphanDocs.length) {
    issues.push({
      path: 'documents', message: `文档规则未被任何阶段 / 流程引用：${orphanDocs.join(', ')}`, scope: 'documents',
    })
  }
  return issues
}

function validateFlowRefs(
  flow: TemplateSpecFormFlow,
  form: DraftForm,
  path: string,
  issues: DraftIssue[],
): void {
  const names = new Set(form.fields.map(f => f.name))
  const checkNames = (refs: string[] | undefined, label: string) => {
    ;(refs ?? []).forEach(ref => {
      if (!names.has(ref)) {
        issues.push({ path, message: `${label}引用了不存在的字段：${ref}`, scope: 'forms', uid: form.uid })
      }
    })
  }
  checkNames(flow.list_fields, '列表字段')
  checkNames(flow.search_fields, '搜索字段')
  ;([['form_groups', '表单分组'], ['detail_groups', '详情分组']] as const).forEach(([key, label]) => {
    ;(flow[key] ?? []).forEach(group => {
      if (!group.fields?.length) {
        issues.push({ path, message: `${label}「${group.title}」至少包含一个字段`, scope: 'forms', uid: form.uid })
      }
      ;(group.fields ?? []).forEach(name => {
        if (!names.has(name)) {
          issues.push({ path, message: `${label}引用了不存在的字段：${name}`, scope: 'forms', uid: form.uid })
        }
      })
    })
  })
  Object.keys(flow.hints ?? {}).forEach(name => {
    if (!names.has(name)) {
      issues.push({ path, message: `提示引用了不存在的字段：${name}`, scope: 'forms', uid: form.uid })
    }
  })
  Object.keys(flow.default_values ?? {}).forEach(name => {
    if (!names.has(name)) {
      issues.push({ path, message: `默认值引用了不存在的字段：${name}`, scope: 'forms', uid: form.uid })
    }
  })
  if (flow.default_sort && !names.has(flow.default_sort.field)) {
    issues.push({ path, message: `默认排序引用了不存在的字段：${flow.default_sort.field}`, scope: 'forms', uid: form.uid })
  }
}

export interface ApplyJsonResult {
  draft?: TemplateDraft
  issues: DraftIssue[]
  parseError?: string
}

export function applyJsonToDraft(
  text: string,
  meta: DraftMeta,
): ApplyJsonResult {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    return { issues: [], parseError: error instanceof Error ? error.message : 'JSON 解析失败' }
  }
  if (parsed == null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { issues: [], parseError: '模板规格必须是 JSON 对象' }
  }
  const draft = draftFromSpec(parsed as TemplateSpec, meta)
  const issues = validateDraft(draft)
  if (issues.length) return { issues }
  return { draft, issues: [] }
}

export function issueTarget(issue: DraftIssue): string {
  if (issue.scope === 'meta') return 'overview'
  if (issue.scope === 'forms' && issue.formUid) return `form:${issue.formUid}`
  if (issue.scope === 'documents' && issue.uid) return `doc:${issue.uid}`
  if (issue.scope === 'stages' && issue.uid) return `stage:${issue.uid}`
  if (issue.scope === 'flows' && issue.uid) return `flow:${issue.uid}`
  if (issue.scope === 'forms') return 'overview'
  if (issue.scope === 'stages') return 'overview'
  if (issue.scope === 'documents') return 'overview'
  return 'overview'
}
