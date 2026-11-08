/** 移动端适配口径契约（ADR 0123 D6/D7/C6）.
 *
 * 直接读 index.css 文本（同 headerBorders.test.ts 范式，jsdom 不加载样式表，
 * 只能钉「写进文件的字面文本」）：
 *   1. D7：Modal / 左右 Drawer 移动宽度统一 calc(100vw - 32px) 上限，挂在移动断点内
 *   2. D6：行内「名称 + 徽标」的名称必须 min-width: 0（否则徽标不可收缩、名称被挤为 0）
 *   3. C6：CSS 断点 767.98px 与 useResponsive BREAKPOINTS.mobile(768) 对齐
 *
 * 防止后续改样式时把口径改回各页自发写法（92vw / calc(100vw - 16px / 24px) 等）。
 */

import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { BREAKPOINTS } from './hooks/useResponsive'

const INDEX_CSS = [
  path.resolve(process.cwd(), 'src/index.css'),
  path.resolve(process.cwd(), 'frontend/src/index.css'),
].find(p => existsSync(p)) ?? ''

/** 去注释后压平空白：选择器跨行 / 逗号分组统一成单空格，便于字面匹配 */
const css = readFileSync(INDEX_CSS, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ')

const MOBILE_BREAKPOINT = `${(BREAKPOINTS.mobile - 0.02).toFixed(2)}px`

/** 收集 @media (max-width: <w>) { ... } 的全部块（花括号计数，容忍嵌套规则） */
function mediaBlocks(maxWidth: string): string[] {
  const re = /@media\s*\(max-width:\s*([^)]+)\)\s*\{/g
  const blocks: string[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(css))) {
    if (m[1]!.trim() !== maxWidth) continue
    const start = m.index + m[0].length
    let depth = 1
    let i = start
    while (i < css.length && depth > 0) {
      if (css[i] === '{') depth++
      else if (css[i] === '}') depth--
      i++
    }
    blocks.push(css.slice(start, i - 1))
  }
  return blocks
}

/** 在给定源文本内取声明块（选择器 → { 声明 }） */
function ruleBody(source: string, selector: string): string {
  const pattern = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = source.match(new RegExp(`${pattern}\\s*\\{([^}]*)\\}`))
  if (!match) throw new Error(`未找到规则：${selector}`)
  return match[1]!.replace(/\s+/g, ' ').trim()
}

describe('移动端适配口径（ADR 0123）', () => {
  const mobileBlocks = mediaBlocks(MOBILE_BREAKPOINT)
  const globalBlock = mobileBlocks.find(b => b.includes('.ant-modal')) ?? ''

  it('C6：CSS 断点 767.98px 与 useResponsive mobile 断点（768）对齐', () => {
    expect(MOBILE_BREAKPOINT).toBe('767.98px')
    expect(mobileBlocks.length, 'index.css 缺少 767.98px 移动断点分节').toBeGreaterThan(0)
  })

  it('D7：Modal 移动宽度统一 calc(100vw - 32px) 上限，挂在移动断点内', () => {
    expect(globalBlock, 'index.css 缺少「移动端全局适配」分节').not.toBe('')
    expect(ruleBody(globalBlock, '.ant-modal')).toContain('max-width: calc(100vw - 32px)')
  })

  it('D7：左右抽屉移动宽度统一 calc(100vw - 32px)，顶部/底部抽屉不受限', () => {
    const drawerSelector = '.ant-drawer-left .ant-drawer-content-wrapper, .ant-drawer-right .ant-drawer-content-wrapper'
    expect(ruleBody(globalBlock, drawerSelector)).toContain('max-width: calc(100vw - 32px)')
    // 顶部抽屉（移动搜索）铺满视口宽是预期形态，不得被套上限（此前 92vw 全局口径的缺陷）；
    // 只拦截「裸 .ant-drawer-content-wrapper 选择器」写上限，左右复合选择器除外
    expect(globalBlock).not.toMatch(/(?<!\.ant-drawer-(?:left|right) )\.ant-drawer-content-wrapper\s*\{[^}]*max-width/)
  })

  it('D6：工作区列表行内名称占满剩余宽度（P0 资产）', () => {
    const block = mobileBlocks.find(b => b.includes('.cn-ws-row-name')) ?? ''
    expect(block, '缺少 .cn-ws-row-name 移动端规则').not.toBe('')
    expect(ruleBody(block, '.cn-ws-row-title .cn-ws-row-name')).toContain('min-width: 0')
    expect(ruleBody(block, '.cn-ws-row-title .cn-ws-row-name')).toContain('flex: 1 1 auto')
  })

  it('D6：工作区展开区表胶囊名称可收缩（长表名省略而非溢出胶囊）', () => {
    expect(ruleBody(css, '.cn-ws-detail-table-name')).toContain('min-width: 0')
  })

  it('C7：顶栏留白/间距已收敛到 CSS（桌面基准 + 移动收窄），不再 JS 分叉', () => {
    expect(ruleBody(css, '.ant-layout-header.cn-app-header')).toContain('gap: var(--cn-space-md)')
    expect(ruleBody(css, '.ant-layout-header.cn-app-header')).toContain('padding: 0 var(--cn-space-lg)')
    expect(ruleBody(globalBlock, '.ant-layout-header.cn-app-header')).toContain('gap: var(--cn-space-xs)')
    expect(ruleBody(globalBlock, '.ant-layout-header.cn-app-header')).toContain('padding: 0 var(--cn-space-md) !important')
  })
})
