/**
 * 字体资产一致性测试.
 *
 * 正文字体（Inter）、展示字体（Outfit）与等宽字体（JetBrains Mono）全部走 npm 运行时依赖：
 *   1. package.json 必须声明三个 @fontsource 依赖（离线部署随依赖安装，不引 CDN）
 *   2. 实际安装的 latin 子集字重文件必须存在且非空（400/500/600/700）
 *   3. 入口 main.tsx 必须按字重导入对应 CSS，否则字体不会被构建进产物
 *   4. public/fonts 不再保留本地字体文件（中文由系统字体回退）
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

const WEIGHTS = [400, 500, 600, 700] as const

const pkg = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as {
  dependencies?: Record<string, string>
}

describe('字体依赖与资产', () => {
  it.each(Object.values(FONT_PACKAGES))('$pkg 已声明为运行时依赖', ({ pkg: name }) => {
    expect(pkg.dependencies?.[name]).toBeTruthy()
  })

  it.each(Object.values(FONT_PACKAGES))('$pkg 的 latin 四档 woff2 均已安装', ({ pkg: name }) => {
    const dir = path.join(ROOT, 'node_modules', name, 'files')
    for (const weight of WEIGHTS) {
      const file = path.join(dir, `${name.split('/')[1]}-latin-${weight}-normal.woff2`)
      expect(existsSync(file), `缺少 ${file}`).toBe(true)
      expect(statSync(file).size).toBeGreaterThan(1000)
    }
  })

  it('入口按字重导入三套字体的 latin 子集 CSS', () => {
    const main = readFileSync(path.join(ROOT, 'src/main.tsx'), 'utf8')
    for (const weight of WEIGHTS) {
      expect(main).toContain(`@fontsource/inter/latin-${weight}.css`)
      expect(main).toContain(`@fontsource/outfit/latin-${weight}.css`)
      expect(main).toContain(`@fontsource/jetbrains-mono/latin-${weight}.css`)
    }
  })

  it('public/fonts 不再保留本地字体文件', () => {
    expect(existsSync(path.join(ROOT, 'public/fonts'))).toBe(false)
  })
})
