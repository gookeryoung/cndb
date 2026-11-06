/**
 * 字体资产一致性测试.
 *
 * 正文字体（Inter）、展示字体（Outfit）与等宽字体（JetBrains Mono）全部走 npm 运行时依赖：
 *   1. package.json 必须声明三个 @fontsource 依赖（离线部署随依赖安装，不引 CDN）
 *   2. 实际安装的 latin 子集字重文件必须存在且非空（按实际使用字重裁剪，见 ENTRY_WEIGHTS）
 *   3. 入口 main.tsx 必须按字重导入对应 CSS，否则字体不会被构建进产物
 *   4. 入口字体传输总量 ≤150 KB（ADR 0116 C4）
 *   5. public/fonts 不再保留本地字体文件（中文由系统字体回退）
 */

import { existsSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const ROOT = [
  path.resolve(process.cwd(), '.'),
  path.resolve(process.cwd(), 'frontend'),
].find(p => existsSync(path.join(p, 'package.json'))) ?? ''

const FONT_PACKAGES = {
  inter: { pkg: '@fontsource/inter', family: 'inter' },
  outfit: { pkg: '@fontsource/outfit', family: 'outfit' },
  'jetbrains-mono': { pkg: '@fontsource/jetbrains-mono', family: 'jetbrains-mono' },
} as const

/** 入口实际引入的字重 —— 与 main.tsx 的 import 必须逐项一致（ADR 0116 C4 裁剪口径） */
const ENTRY_WEIGHTS: Record<keyof typeof FONT_PACKAGES, readonly number[]> = {
  inter: [400, 500, 600, 700],
  outfit: [600, 700],
  'jetbrains-mono': [400],
}

const FONT_BUDGET_BYTES = 150 * 1024

const pkg = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as {
  dependencies?: Record<string, string>
}

describe('字体依赖与资产', () => {
  it.each(Object.values(FONT_PACKAGES))('$pkg 已声明为运行时依赖', ({ pkg: name }) => {
    expect(pkg.dependencies?.[name]).toBeTruthy()
  })

  it.each(Object.values(FONT_PACKAGES))('$pkg 的 latin 字重文件均已安装', ({ pkg: name, family }) => {
    const dir = path.join(ROOT, 'node_modules', name, 'files')
    for (const weight of ENTRY_WEIGHTS[family]) {
      const file = path.join(dir, `${family}-latin-${weight}-normal.woff2`)
      expect(existsSync(file), `缺少 ${file}`).toBe(true)
      expect(statSync(file).size).toBeGreaterThan(1000)
    }
  })

  it('入口按实际使用字重导入三套字体的 latin 子集 CSS', () => {
    const main = readFileSync(path.join(ROOT, 'src/main.tsx'), 'utf8')
    for (const [family, weights] of Object.entries(ENTRY_WEIGHTS)) {
      for (const weight of weights) {
        expect(main).toContain(`@fontsource/${family}/latin-${weight}.css`)
      }
    }
    // 未使用的字重不得重新引入（防止体积无声反弹）
    expect(main).not.toContain('@fontsource/outfit/latin-400.css')
    expect(main).not.toContain('@fontsource/outfit/latin-500.css')
    expect(main).not.toContain('@fontsource/jetbrains-mono/latin-500.css')
    expect(main).not.toContain('@fontsource/jetbrains-mono/latin-600.css')
    expect(main).not.toContain('@fontsource/jetbrains-mono/latin-700.css')
  })

  it('入口字体 woff2 传输总量 ≤150 KB', () => {
    let total = 0
    for (const [family, config] of Object.entries(FONT_PACKAGES)) {
      const dir = path.join(ROOT, 'node_modules', config.pkg, 'files')
      for (const weight of ENTRY_WEIGHTS[family as keyof typeof ENTRY_WEIGHTS]) {
        total += statSync(path.join(dir, `${config.family}-latin-${weight}-normal.woff2`)).size
      }
    }
    expect(total).toBeLessThanOrEqual(FONT_BUDGET_BYTES)
  })

  it('public/fonts 不再保留本地字体文件', () => {
    expect(existsSync(path.join(ROOT, 'public/fonts'))).toBe(false)
  })
})
