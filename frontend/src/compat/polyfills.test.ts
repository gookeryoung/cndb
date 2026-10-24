/**
 * 定向 polyfill 的覆盖面与装载边界（ADR 0026 P0/P1）。
 *
 * polyfill 不作为入口常驻：入口无条件加载会吃掉关键 chunk 预算，而实际用到
 * 这些 API 的模块都是懒加载的。这里锁定「使用方必须自行静态导入」这一约束，
 * 防止后续重构把某条导入删掉后旧内核再次抛 TypeError。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const read = (relative: string) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

describe('Chromium 81 定向 polyfill', () => {
  it('只引入实际缺失且未被守卫的 API', () => {
    const source = read('./polyfills.ts')
    expect(source).toContain("'core-js/actual/array/at'")
    expect(source).toContain("'core-js/actual/object/has-own'")
    // @formatjs/intl-segmenter 内部依赖 String.prototype.replaceAll（Chrome 85+），
    // 缺它会让 PDF 导出在 html2canvas 渲染完成后静默失败（真机 Chromium 81 已复现）
    expect(source).toContain("'core-js/actual/string/replace-all'")
    // 唯一调用点自带 typeof 守卫与 JSON 回退，补它会把 Map/Set internals 拖进包体
    expect(source).not.toContain("'core-js/web/structured-clone'")
    // Segmenter 只在导出路径按需加载，不得进这里
    expect(source).not.toMatch(/import\s+['"]@formatjs/)
  })

  it('所有使用方都静态导入 polyfill', () => {
    const consumers = [
      '../utils/webVitals.ts',
      '../pages/import-export/ImportExportDialog/exportPdf.ts',
      '../components/Document/MarkdownPreview.tsx',
      '../pages/documents/DocumentEditorPage.tsx',
    ]
    for (const consumer of consumers) {
      expect(read(consumer), `${consumer} 缺少 polyfill 导入`).toContain("import '@/compat/polyfills'")
    }
  })

  it('入口不常驻 polyfill（由懒加载消费方各自导入）', () => {
    expect(read('../main.tsx')).not.toContain("'./compat/polyfills'")
  })
})
