/**
 * 设计标尺一致性测试.
 *
 * 样式表（全局 index.css 与随页面 lazy 加载的页面级 *.css）与 src/theme/tokens.ts
 * 是同一把尺子的两个落点（CSS 变量 / TS 常量），双写必然漂移，这里用测试把两边钉死：
 *   1. tokens.ts 声明的每个变量都必须在 :root 里存在且数值一致
 *   2. 样式表里不允许再出现游离的离散步长（字号 9/15px、圆角 3/10px、间距 3/5/7/10/14px）
 *   3. max-width 断点只允许登记过的几个口径
 *
 * 违反第 2/3 条说明有人绕过了标尺就地写字面量——请把新档位加进 tokens.ts 再引用变量。
 *
 * 需求 0183 起，src 下除 index.css 外还有页面级样式（如
 * pages/documents/DocumentGraphPage.css）；扫描面是整个 src，搬出 index.css 不会漏检。
 */

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  BREAKPOINT,
  CSS_VARS,
  FONT,
  RADIUS,
  SPACE,
  TEXT,
  TRACKING,
  WEIGHT,
  radiusFamily,
} from './tokens'

// 直接读磁盘：vitest 会拦截 .css 的模块加载（?raw 也可能被 CSS 插件接管），
// 这里要的是「写进文件的字面文本」，不经过任何转换。
// jsdom 环境下 import.meta.url 不是 file:// 协议，只能从 cwd 推断。
const SRC_DIR = [
  path.resolve(process.cwd(), 'src'),
  path.resolve(process.cwd(), 'frontend/src'),
].find(p => existsSync(p)) ?? ''

const INDEX_CSS = path.join(SRC_DIR, 'index.css')

/** 递归收集 src 下的全部样式表（全局 + 页面级），排序保证扫描结果稳定 */
function collectStylesheets(dir: string): string[] {
  if (!dir || !existsSync(dir)) return []
  const found: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules') continue
      found.push(...collectStylesheets(full))
      continue
    }
    if (entry.name.endsWith('.css')) found.push(full)
  }
  return found.sort()
}

/** 去掉注释，避免注释里的示例值被当成声明 */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 取出标尺块：:root { ... } 的第一处（排在主题变量之前） */
function scaleBlock(css: string): string {
  const start = css.indexOf(':root {')
  expect(start).toBeGreaterThan(-1)
  const end = css.indexOf('}', start)
  return css.slice(start, end)
}

const STYLESHEETS = collectStylesheets(SRC_DIR)

/** 全部样式表去注释后拼接：字面量与断点断言按合并文本跑，单个文件不必重复实现 */
const css = STYLESHEETS.map(f => stripComments(readFileSync(f, 'utf8'))).join('\n')

describe('tokens ↔ index.css 同步', () => {
  const block = scaleBlock(stripComments(readFileSync(INDEX_CSS, 'utf8')))
  it('每个标尺变量都在 :root 中声明且数值一致', () => {
    for (const [name, value] of Object.entries(CSS_VARS)) {
      expect(block, `:root 缺少 ${name}`).toContain(`${name}: ${value};`)
    }
  })

  it('圆角档位按 base 派生：sm = base-2、lg = base+2', () => {
    const { sm, lg } = radiusFamily(RADIUS.base)
    expect(sm).toBe(RADIUS.base - 2)
    expect(lg).toBe(RADIUS.base + 2)
    // 极简主题 base=2 时不能让 sm 掉到 0/负数
    expect(radiusFamily(RADIUS.xs).sm).toBe(RADIUS.xs)
  })

  it('间距主体为 4px 网格，半步仅 hairline(2) 与 sm(6)', () => {
    const grid = [SPACE.xs, SPACE.md, SPACE.lg, SPACE.xl, SPACE['2xl'], SPACE['3xl'], SPACE['4xl']]
    for (const v of grid) expect(v % 4).toBe(0)
    expect(SPACE.hairline).toBe(2)
    expect(SPACE.sm).toBe(6)
  })

  it('字号档位单调递增且下限 ≥ 10px', () => {
    const sizes = [TEXT['3xs'], TEXT['2xs'], TEXT.xs, TEXT.sm, TEXT.md, TEXT.lg, TEXT.xl]
    for (let i = 1; i < sizes.length; i++) expect(sizes[i]).toBeGreaterThan(sizes[i - 1])
    expect(sizes[0]).toBeGreaterThanOrEqual(10)
  })

  it('字重四档递增，字体栈覆盖正文 / 展示 / 等宽', () => {
    expect([WEIGHT.regular, WEIGHT.medium, WEIGHT.semibold, WEIGHT.bold]).toEqual([400, 500, 600, 700])
    expect(FONT.sans).toContain('Inter')
    expect(FONT.display).toContain('Outfit')
    expect(FONT.mono).toContain('JetBrains Mono')
    expect(TRACKING.display).toBe('-0.02em')
  })
})

describe('样式表不出现游离字面量', () => {
  it('扫描面覆盖 src 下全部样式表', () => {
    expect(STYLESHEETS.length, 'src 下应至少有一个样式表').toBeGreaterThan(0)
    expect(STYLESHEETS.some(f => f.endsWith('index.css'))).toBe(true)
  })

  it('字号只走 --cn-text-*（9/15/17px 等离散步长已废弃）', () => {
    const offenders = [...css.matchAll(/font-size:\s*([0-9.]+px)/g)].map(m => m[1])
    expect(offenders).toEqual([])
  })

  it('字重只走 --cn-weight-*（@font-face 的字面量例外）', () => {
    const withoutFontFaces = css.replace(/@font-face\s*\{[^}]*\}/g, '')
    const offenders = [...withoutFontFaces.matchAll(/font-weight:\s*([^;]+);/g)]
      .map(m => m[1].trim())
      .filter(v => !v.includes('var(--cn-weight'))
    expect(offenders).toEqual([])
  })

  it('圆角只走 --cn-radius-*（0 / 1px / 50% / inherit 例外）', () => {
    const offenders = [...css.matchAll(/border-radius:\s*([^;]+);/g)]
      .map(m => m[1].trim())
      .filter(v => !v.includes('var(--cn-radius') && !/^(0|1px|50%|inherit)$/.test(v))
    expect(offenders).toEqual([])
  })

  it('间距只走 --cn-space-*（0 / auto / 1px 光学微调为例外）', () => {
    const prop = /(padding|margin|gap|row-gap|column-gap)(-[a-z]+)?:\s*([^;]+);/g
    const offenders: string[] = []
    for (const m of css.matchAll(prop)) {
      const leftover = m[3]
        .replace(/var\(--cn-space-[a-z0-9-]+\)/g, '')
        .replace(/\b1px\b/g, '')
        .replace(/\b(?:0|auto)\b/g, '')
        .replace(/!important/g, '')
        .trim()
      if (leftover) offenders.push(`${m[1]}${m[2] ?? ''}: ${m[3].trim()}`)
    }
    expect(offenders).toEqual([])
  })
})

describe('断点口径', () => {
  it('max-width 断点只允许 mobile / tablet 口径 - 0.02', () => {
    expect(BREAKPOINT.mobile).toBe(768)
    expect(BREAKPOINT.tablet).toBe(992)
    const widths = [...css.matchAll(/@media[^{]*max-width:\s*([0-9.]+)px/g)].map(m => Number(m[1]))
    expect(widths.length).toBeGreaterThan(0)
    // 991.98 = tablet(992) - 0.02，对应「窄屏单列堆叠」；575.98 为 antd xs 例外；
    // 1023.98 = 数据分析带状工作台的双列下限（<1024 堆叠，与 useResponsive BREAKPOINTS.tablet 对齐）；
    // 1199.98 = xl(1200) - 0.02，对应跨端布局收为双栏的下限
    // 1599.98 = wide(1600) - 0.02，对应主页「导航 rail + 主区 + 我的视图」三栏收为两栏的下限
    const allowed = [
      BREAKPOINT.mobile - 0.02, BREAKPOINT.tablet - 0.02, 575.98, 1023.98,
      BREAKPOINT.xl - 0.02, BREAKPOINT.wide - 0.02,
    ]
    for (const w of widths) {
      expect(allowed, `出现未登记断点 ${w}px`).toContain(w)
    }
  })
})
