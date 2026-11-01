import { describe, expect, it } from 'vitest'
import {
  DEFAULT_WORKSPACE_MODULES, WORKSPACE_MODULE_LABEL, WORKSPACE_MODULES,
  normalizeModules, workspaceLandingSegment, workspaceModulesFeatures,
} from './workspaceModules'
import type { WorkspaceModule } from './workspaceModules'

describe('workspaceModules 工作区功能模块元数据', () => {
  it('三模块清单与中文标签符合产品定义（顺序即勾选顺序）', () => {
    expect(WORKSPACE_MODULES).toEqual(['tables', 'documents', 'design'])
    expect(WORKSPACE_MODULE_LABEL).toEqual({
      tables: '数据表', documents: '文档', design: '设计',
    })
  })

  it('新建默认三模块全选（ADR 0080 D8）', () => {
    expect(DEFAULT_WORKSPACE_MODULES).toEqual(['tables', 'documents', 'design'])
  })

  // 7 种非空组合矩阵 —— 与后端 tests/test_workspace_modules.py 逐项对齐（I3）
  it('7 种非空组合的功能开放矩阵与后端一致', () => {
    const cases: Array<[WorkspaceModule[], Record<string, boolean>]> = [
      [['tables'], { tables: true, documents: false, design: false, analytics: true, datasource: true }],
      [['documents'], { tables: false, documents: true, design: false, analytics: false, datasource: false }],
      [['design'], { tables: false, documents: false, design: true, analytics: false, datasource: false }],
      [['tables', 'documents'], { tables: true, documents: true, design: false, analytics: true, datasource: true }],
      [['tables', 'design'], { tables: true, documents: false, design: true, analytics: true, datasource: true }],
      [['documents', 'design'], { tables: false, documents: true, design: true, analytics: false, datasource: false }],
      [['tables', 'documents', 'design'], { tables: true, documents: true, design: true, analytics: true, datasource: true }],
    ]
    for (const [modules, expectPartial] of cases) {
      const feat = workspaceModulesFeatures(modules)
      expect(feat.tables).toBe(expectPartial.tables)
      expect(feat.documents).toBe(expectPartial.documents)
      expect(feat.design).toBe(expectPartial.design)
      expect(feat.analytics).toBe(expectPartial.analytics)
      expect(feat.datasource).toBe(expectPartial.datasource)
      // 质量检查恒开放（D4）
      expect(feat.quality).toBe(true)
    }
  })

  it('归一化：去重并按固定顺序输出', () => {
    expect(normalizeModules(['design', 'tables', 'design'])).toEqual(['tables', 'design'])
    expect(normalizeModules(['documents'])).toEqual(['documents'])
  })

  it('归一化：非法输入（空 / 非数组 / 全未知）回退默认全三模块', () => {
    expect(normalizeModules(undefined)).toEqual(DEFAULT_WORKSPACE_MODULES)
    expect(normalizeModules(null)).toEqual(DEFAULT_WORKSPACE_MODULES)
    expect(normalizeModules([])).toEqual(DEFAULT_WORKSPACE_MODULES)
    expect(normalizeModules('tables')).toEqual(DEFAULT_WORKSPACE_MODULES)
    expect(normalizeModules(['nope'])).toEqual(DEFAULT_WORKSPACE_MODULES)
  })

  it('落地页路由段：tables → documents → design 取第一个可用段（D9）', () => {
    expect(workspaceLandingSegment(['tables', 'documents'])).toBe('tables')
    expect(workspaceLandingSegment(['documents', 'design'])).toBe('documents')
    expect(workspaceLandingSegment(['design'])).toBe('design')
    // 缺失/非法 → 默认全三 → 落地 tables
    expect(workspaceLandingSegment(undefined)).toBe('tables')
    expect(workspaceLandingSegment([])).toBe('tables')
  })
})
