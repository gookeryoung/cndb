/** 引导步骤定义测试：结构完整性与锚点可达性. */

import { describe, expect, it } from 'vitest'
import { buildSteps, TOUR_SELECTORS } from './onboardingSteps'

describe('onboardingSteps', () => {
  it('至少包含欢迎步与收尾帮助步，首步无 element（居中弹窗）', () => {
    const steps = buildSteps()
    expect(steps.length).toBeGreaterThanOrEqual(7)
    expect(steps[0]!.element).toBeUndefined()
    expect(steps[steps.length - 1]!.element).toBe(TOUR_SELECTORS.helpBtn)
  })

  it('除首步外每步都有 element 锚点与 title/description', () => {
    const steps = buildSteps()
    for (const [i, step] of steps.entries()) {
      expect(step.popover.title, `step ${i} 缺 title`).toBeTruthy()
      expect(step.popover.description, `step ${i} 缺 description`).toBeTruthy()
      if (i > 0) {
        expect(step.element, `step ${i} 缺 element`).toMatch(/^\[data-testid=/)
      }
    }
  })

  it('TOUR_SELECTORS 与步骤中使用的锚点一致（无孤儿选择器）', () => {
    const steps = buildSteps()
    const used = new Set(steps.map(s => s.element).filter(Boolean))
    for (const sel of Object.values(TOUR_SELECTORS)) {
      expect(used.has(sel), `选择器 ${sel} 未被步骤使用`).toBe(true)
    }
  })

  it('关键锚点齐全：工作区切换/侧边表列表/新增行/视图切换/表设置/导入导出/帮助', () => {
    const values = Object.values(TOUR_SELECTORS)
    expect(values).toHaveLength(7)
    expect(values).toContain('[data-testid="ws-switch-btn"]')
    expect(values).toContain('[data-testid="add-row-btn"]')
    expect(values).toContain('[data-testid="table-settings-btn"]')
    expect(values).toContain('[data-testid="import-export-btn"]')
    expect(values).toContain('[data-testid="help-btn"]')
  })
})
