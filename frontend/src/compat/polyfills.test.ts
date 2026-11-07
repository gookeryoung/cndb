/**
 * 定向 polyfill 的覆盖面与装载边界（ADR 0026 P0/P1）。
 *
 * polyfill 不作为入口常驻：入口无条件加载会吃掉关键 chunk 预算，而实际用到
 * 这些 API 的模块都是懒加载的。这里锁定「使用方必须自行静态导入」这一约束，
 * 防止后续重构把某条导入删掉后旧内核再次抛 TypeError。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'

const read = (relative: string) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

/** 装载 polyfills 模块并锁定其性能条目守卫的能力探测结果。 */
async function loadWithEntryTypes(types: string[] | undefined): Promise<void> {
  if (types) {
    class FakePerformanceObserver {
      static supportedEntryTypes = types
    }
    vi.stubGlobal('PerformanceObserver', FakePerformanceObserver)
  } else {
    vi.stubGlobal('PerformanceObserver', undefined)
  }
  vi.resetModules()
  await import('./polyfills')
}

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

describe('performance.getEntriesByType 噪音守卫', () => {
  /** 用可断言的替身接管原型方法，返回原方法以便还原。 */
  function stubGetEntriesByType(): { native: ReturnType<typeof vi.fn>; restore: () => void } {
    const proto = Object.getPrototypeOf(performance) as Performance
    const original = proto.getEntriesByType
    const native = vi.fn(() => [{ name: 'mark' } as PerformanceEntry])
    proto.getEntriesByType = native
    return { native, restore: () => { proto.getEntriesByType = original } }
  }

  it('旧内核缺少 visibility-state 条目时短路为空数组', async () => {
    const { native, restore } = stubGetEntriesByType()
    try {
      await loadWithEntryTypes(['paint'])
      expect(performance.getEntriesByType('visibility-state')).toEqual([])
      expect(native).not.toHaveBeenCalled()
      expect(performance.getEntriesByType('paint')).toEqual([{ name: 'mark' }])
      expect(native).toHaveBeenCalledWith('paint')
    } finally {
      restore()
    }
  })

  it('现代内核保留原生实现', async () => {
    const { native, restore } = stubGetEntriesByType()
    try {
      await loadWithEntryTypes(['visibility-state', 'paint'])
      expect(performance.getEntriesByType('visibility-state')).toEqual([{ name: 'mark' }])
      expect(native).toHaveBeenCalledWith('visibility-state')
    } finally {
      restore()
    }
  })

  it('无 PerformanceObserver 时不做原型改写', async () => {
    const { native, restore } = stubGetEntriesByType()
    try {
      await loadWithEntryTypes(undefined)
      expect(performance.getEntriesByType('visibility-state')).toEqual([{ name: 'mark' }])
      expect(native).toHaveBeenCalledWith('visibility-state')
    } finally {
      restore()
    }
  })
})
