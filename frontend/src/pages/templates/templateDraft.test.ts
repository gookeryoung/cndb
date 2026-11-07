import { describe, expect, it } from 'vitest'
import type { TemplateSpec } from '@/api'
import {
  applyJsonToDraft, draftFromSpec, draftToSpec, emptyDraft, nextKey, validateDraft,
} from './templateDraft'
import { deleteDraftDocument, deleteDraftForm, deleteDraftStage } from './TemplateEditorSections'

const SPEC: TemplateSpec = {
  forms: [{
    key: 'apply',
    name: '申报表',
    description: '',
    fields: [
      { name: '项目名称', type: 'text', required: true, is_unique: false, hidden: false, config: { placeholder: '请输入' } },
      { name: '负责人', type: 'link', required: false, is_unique: false, hidden: false, config: { target_form: 'member', extra: 'keep-me' } },
    ],
    flow: {
      enabled: true,
      list_fields: ['项目名称'],
      search_fields: [],
      form_groups: [{ title: '基本信息', fields: ['项目名称', '负责人'] }],
      detail_groups: [{ title: '基本信息', fields: ['项目名称', '负责人'] }],
      hints: { 项目名称: '必填' },
      default_values: {},
      allow_create: true,
      allow_edit: true,
      allow_delete: true,
      default_sort: null,
      empty_text: '',
    },
  }],
  documents: [{ key: 'proposal', title: '立项书', required: true, naming: '项目-立项书', content: '# 正文' }],
  stages: [{
    key: 'proposal_stage', name: '立项', description: '', order: 1, forms: ['apply'], documents: ['proposal'],
  }],
  flows: [{
    key: 'main', name: '主流程', description: '', stage: 'proposal_stage',
    steps: [{ key: 'step_1', name: '填报', description: '', form: 'apply', documents: ['proposal'] }],
  }],
}

describe('templateDraft', () => {
  it('round-trips flow, stage and unknown field config without loss', () => {
    const draft = draftFromSpec(SPEC, { name: '科研模板', modules: ['tables', 'documents'] })
    const spec = draftToSpec(draft)
    expect(spec.forms[0].flow?.list_fields).toEqual(['项目名称'])
    expect(spec.forms[0].fields[1].config).toMatchObject({ target_form: 'member', extra: 'keep-me' })
    expect(spec.flows?.[0].stage).toBe('proposal_stage')
    expect(spec.stages[0].order).toBe(1)
    expect(draft.name).toBe('科研模板')
  })

  it('regenerates stage order from array position', () => {
    const draft = draftFromSpec(SPEC)
    draft.stages = [
      { ...draft.stages[0], uid: 'b', key: 'b', name: 'B' },
      { ...draft.stages[0], uid: 'a', key: 'a', name: 'A' },
    ]
    expect(draftToSpec(draft).stages.map(stage => [stage.key, stage.order])).toEqual([['b', 1], ['a', 2]])
  })

  it('cascades references when deleting form, document or stage', () => {
    const draft = draftFromSpec(SPEC)
    const withoutForm = deleteDraftForm(draft, draft.forms[0])
    expect(withoutForm.stages[0].forms).toEqual([])
    expect(withoutForm.flows[0].steps[0].form).toBeNull()

    const withoutDoc = deleteDraftDocument(draft, draft.documents[0])
    expect(withoutDoc.stages[0].documents).toEqual([])
    expect(withoutDoc.flows[0].steps[0].documents).toEqual([])

    const withoutStage = deleteDraftStage(draft, draft.stages[0])
    expect(withoutStage.flows[0].stage).toBeNull()
  })

  it('reports duplicate / unknown type / orphan issues with paths', () => {
    const draft = draftFromSpec(SPEC)
    draft.forms[0].fields[1].type = 'unknown'
    draft.documents.push({ ...draft.documents[0], uid: 'doc-2', key: 'other', title: '另一份' })
    const issues = validateDraft(draft)
    expect(issues.some(issue => issue.path === 'forms[0].fields[1].type')).toBe(true)
    expect(issues.some(issue => issue.path === 'documents' && issue.message.includes('未被任何阶段'))).toBe(true)
  })

  it('keeps draft unchanged when JSON is invalid', () => {
    const result = applyJsonToDraft('{bad json', { name: 'x', description: '', category: '', modules: [] })
    expect(result.draft).toBeUndefined()
    expect(result.parseError).toBeTruthy()
  })

  it('applies valid JSON into a fresh draft', () => {
    const result = applyJsonToDraft(JSON.stringify(SPEC), { name: 'x', description: '', category: '', modules: [] })
    expect(result.parseError).toBeUndefined()
    expect(result.issues).toEqual([])
    expect(result.draft?.forms[0].key).toBe('apply')
  })

  it('creates a saveable starter draft and stable keys', () => {
    const draft = emptyDraft()
    expect(validateDraft(draft).map(issue => issue.path)).toEqual(['name'])
    draft.name = '新模板'
    expect(validateDraft(draft)).toEqual([])
    expect(nextKey('form', ['form_1', 'form_2'])).toBe('form_3')
  })
})
