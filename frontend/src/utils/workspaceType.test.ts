import { describe, expect, it } from 'vitest'
import {
  WORKSPACE_TYPE_HINT, WORKSPACE_TYPE_LABEL, WORKSPACE_TYPE_OPTIONS,
  workspaceLandingSegment, workspaceTypeFeatures,
} from './workspaceType'

describe('workspaceType 工作区类型元数据', () => {
  it('三种类型的展示名与顺序符合产品定义', () => {
    expect(WORKSPACE_TYPE_LABEL).toEqual({
      data_doc: '数据 + 文档', data: '数据', doc: '文档',
    })
    expect(WORKSPACE_TYPE_OPTIONS.map(o => o.value)).toEqual(['data_doc', 'data', 'doc'])
    expect(WORKSPACE_TYPE_OPTIONS.map(o => o.label)).toEqual(['数据 + 文档', '数据', '文档'])
  })

  it('每种类型均有说明文案', () => {
    for (const t of ['data_doc', 'data', 'doc'] as const) {
      expect(WORKSPACE_TYPE_HINT[t]).toBeTruthy()
    }
  })

  it('data_doc 默认开放全部功能', () => {
    expect(workspaceTypeFeatures('data_doc')).toEqual({
      tables: true, documents: true, analytics: true, datasource: true, quality: true,
    })
  })

  it('data 类仅开放数据表与数据分析，不含文档', () => {
    expect(workspaceTypeFeatures('data')).toEqual({
      tables: true, documents: false, analytics: true, datasource: true, quality: true,
    })
  })

  it('doc 类仅开放文档，不含数据表与数据分析', () => {
    expect(workspaceTypeFeatures('doc')).toEqual({
      tables: false, documents: true, analytics: false, datasource: false, quality: false,
    })
  })

  it('类型缺失/为空时按默认 data_doc 全开', () => {
    expect(workspaceTypeFeatures(undefined)).toEqual({
      tables: true, documents: true, analytics: true, datasource: true, quality: true,
    })
    expect(workspaceTypeFeatures(null)).toEqual({
      tables: true, documents: true, analytics: true, datasource: true, quality: true,
    })
  })

  it('落地页路由段：有数据表功能 → tables，否则 → documents', () => {
    expect(workspaceLandingSegment('data_doc')).toBe('tables')
    expect(workspaceLandingSegment('data')).toBe('tables')
    expect(workspaceLandingSegment('doc')).toBe('documents')
    expect(workspaceLandingSegment(undefined)).toBe('tables')
  })
})
