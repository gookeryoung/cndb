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

  it('顶栏按钮分级：默认无描边，只有显式 cn-header-btn-outlined 才描边（0190 C5）', () => {
    // 默认不再无差别加描边：GitHub 顶栏的 icon-only 按钮本来就没有边框，
    // 原先每个按钮都被套上 1px 描边，一排下来像一排小方块且主次不分。
    const base = ruleBody('.cn-app-header .ant-btn')
    expect(base).toContain('box-shadow: none')
    expect(base).not.toContain('border:')

    // 管理类（管理台 / 头像）显式声明后才有 1px 中性线
    const outlined = ruleBody('.cn-app-header .cn-header-btn-outlined')
    expect(outlined).toContain('border: 1px solid var(--cn-border)')
    // 圆角 / 文字色由 outlined 与 ghost 的共享规则承担
    expect(
      ruleBody('.cn-app-header .cn-header-btn-outlined, .cn-app-header .cn-header-btn-ghost'),
    ).toContain('border-radius: var(--cn-radius-base)')

    // 工具类（大模型 / 帮助）静态完全平面：与 outlined 共享圆角 / 文字色，
    // 自己的规则只声明 border + background，故取该选择器的全部声明块。
    const ghostBodies = allRuleBodies('.cn-app-header .cn-header-btn-ghost')
    expect(ghostBodies.length).toBeGreaterThan(0)
    const ghost = ghostBodies.join(' ')
    expect(ghost).toContain('border: 1px solid transparent')
    expect(ghost).toContain('background: transparent')

    // 圆形按钮保持正圆
    expect(ruleBody('.cn-app-header .ant-btn-circle')).toContain('border-radius: var(--cn-radius-pill)')
  })

  it('侧栏选中态与表导航同语言：3px 品牌色左指示条（0190 C8）', () => {
    // 同一位置（左栏）的两条侧栏原先两种选中语言：表导航有左条，文档树只有一层底色。
    const nav = ruleBody('.cn-table-nav .ant-menu-item-selected::before')
    const tree = ruleBody(
      '.cn-doc-sider-tree .ant-tree-node-content-wrapper.ant-tree-node-selected::before',
    )
    for (const body of [nav, tree]) {
      expect(body).toContain('width: 3px')
      expect(body).toContain('background: var(--cn-brand-color)')
    }
  })

  it('侧栏与内容区分层：底色降一档 + 1px 右边框，把手常态可见（0190 C9）', () => {
    const sider = ruleBody('.cn-app-sider')
    expect(sider).toContain('background: var(--cn-bg-subtle)')
    expect(sider).toContain('border-right: 1px solid var(--cn-border)')

    // 拖拽把手常态就有 1px 中性线（原先透明，用户不知道可拖），hover 才转品牌色
    expect(ruleBody('.cn-sider-resizer::after')).toContain('background: var(--cn-border)')
    const hover = ruleBody('.cn-sider-resizer:hover::after, .cn-sider-resizer:focus::after')
    expect(hover).toContain('background: var(--cn-brand-color)')
  })

  it('一级导航激活态是胶囊底而非底部墨条（0190 C3）', () => {
    const active = ruleBody('.cn-header-nav-item-active')
    // 三层导航不再靠「线宽 2px vs 3px」区分层级
    expect(active).not.toContain('box-shadow')
    expect(active).toContain('background: var(--cn-mix-brand-color-12-bg-container)')
    // 胶囊形状由基类提供（与 .cn-table-tab-active 同一套视觉语言）
    expect(ruleBody('.cn-header-nav-item')).toContain('border-radius: var(--cn-radius-base)')
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
