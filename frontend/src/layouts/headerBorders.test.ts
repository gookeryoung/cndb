/** 顶栏线条一致性（极简 / GitHub 式）—— 搜索框、图标按钮、分界线的边框契约.
 *
 * 顶栏控件与分界线统一走「1px + GitHub 中性线（--cn-border）」：线宽与形状在各主题
 * 一致，颜色由 ThemeProvider 统一为浅色 #6e7781 / 深色 #8b949e。这里直接读 index.css
 * 文本，防止后续改样式时把顶栏搜索框 / 图标按钮 / 底边线改回 1.5px 或主题色相描边。
 */

import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const INDEX_CSS = [
  path.resolve(process.cwd(), 'src/index.css'),
  path.resolve(process.cwd(), 'frontend/src/index.css'),
].find(p => existsSync(p)) ?? ''

/** 去掉注释，避免注释里的示例值被当成声明 */
const css = readFileSync(INDEX_CSS, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

/** 取某条选择器规则的声明块（支持逗号分组跨行、选择器与花括号之间换行 / 空白） */
function ruleBody(selector: string): string {
  const pattern = selector
    .split(',')
    .map(part => part.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('\\s*,\\s*')
  const match = css.match(new RegExp(`(?:^|\\n)\\s*${pattern}\\s*\\{([^}]*)\\}`))
  if (!match) throw new Error(`index.css 未找到规则：${selector}`)
  return match[1]!.replace(/\s+/g, ' ').trim()
}

/** 取同一选择器在文件内出现的全部声明块（后置规则可能重新叠加被收掉的样式） */
function allRuleBodies(selector: string): string[] {
  const pattern = selector
    .split(',')
    .map(part => part.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('\\s*,\\s*')
  const re = new RegExp(`(?:^|\\n)\\s*${pattern}\\s*\\{([^}]*)\\}`, 'g')
  return [...css.matchAll(re)].map(m => m[1]!.replace(/\s+/g, ' ').trim())
}

describe('顶栏线条契约（搜索框 / 图标按钮 / 分界线）', () => {
  it('顶栏底边为 1px 统一中性线，平面底色、无渐变与投影', () => {
    const body = ruleBody('.ant-layout-header.cn-app-header')
    expect(body).toContain('border-bottom: 1px solid var(--cn-border)')
    expect(body).toContain('background: var(--cn-bg-container)')
    expect(body).toContain('box-shadow: none')
  })

  it('顶栏图标按钮统一 1px 描边 + 基准圆角，圆形按钮保持正圆', () => {
    const body = ruleBody('.cn-app-header .ant-btn')
    expect(body).toContain('border: 1px solid var(--cn-border)')
    expect(body).toContain('border-radius: var(--cn-radius-base)')
    expect(ruleBody('.cn-app-header .ant-btn-circle')).toContain('border-radius: var(--cn-radius-pill)')
  })

  it('顶栏搜索框及内部线条同为 1px 统一中性线', () => {
    expect(ruleBody('.cn-gs-box')).toContain('border: 1px solid var(--cn-border)')
    expect(ruleBody('.cn-gs-scope')).toContain('border-right: 1px solid var(--cn-border)')
    expect(ruleBody('.cn-gs-kbd')).toContain('border: 1px solid var(--cn-border)')
    expect(ruleBody('.cn-gs-panel')).toContain('border: 1px solid var(--cn-border)')
  })

  it('聚焦态只保留一条品牌色边框，不叠加光晕与内层 outline', () => {
    const focused = ruleBody('.cn-gs-box-open, .cn-gs-box:focus-within')
    expect(focused).toContain('border-color: var(--cn-brand-color)')
    expect(focused).not.toContain('box-shadow')

    const inner = ruleBody(
      '.cn-gs-box .cn-gs-input, .cn-gs-box .cn-gs-input:focus, .cn-gs-box .cn-gs-input:focus-within',
    )
    expect(inner).toContain('outline: none')
    expect(inner).toContain('box-shadow: none')
  })

  it('文件内任何搜索框聚焦规则都不得再叠加 shadow ring', () => {
    const focusSelectors = [
      '.cn-gs-box, .cn-gs-box-open, .cn-gs-box:focus-within',
      '.cn-gs-box-open, .cn-gs-box:focus-within',
      '.cn-gs-box:focus-within',
    ]
    for (const selector of focusSelectors) {
      const bodies = allRuleBodies(selector)
      expect(bodies.length).toBeGreaterThan(0)
      for (const body of bodies) {
        const shadows = [...body.matchAll(/box-shadow:\s*([^;]+);/g)].map(m => m[1]!.trim())
        expect(shadows).toEqual(shadows.map(() => 'none'))
      }
    }
  })

  it('内层 Input 收线声明带 !important，压过文末 antd 聚焦 ring', () => {
    const bodies = allRuleBodies(
      '.cn-gs-box .cn-gs-input, .cn-gs-box .cn-gs-input:focus, .cn-gs-box .cn-gs-input:focus-within',
    )
    expect(bodies.length).toBeGreaterThan(0)
    const body = bodies[0]!
    expect(body).toContain('outline: none !important')
    expect(body).toContain('box-shadow: none !important')
  })
})
