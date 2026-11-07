/**
 * Chromium 81 缺失的运行时 API —— 由消费模块静态导入（ADR 0026 D3）。
 *
 * 只补实际出现在产物里的 API，且只在真正使用它的懒加载模块里导入：
 * ESM 保证依赖先于模块体执行，因此不必塞进首屏入口；入口常驻会无条件吃掉
 * 关键 chunk 预算（structured-clone 还会连带拉入整套 Map/Set internals）。
 *
 * - Array.prototype.at：web-vitals、jspdf（导出路径）
 * - Object.hasOwn：react-markdown（文档预览）、DocumentEditorPage 的依赖
 * - String.prototype.replaceAll：@formatjs/intl-segmenter 内部使用（Chrome 85+），
 *   导出 PDF 时缺它会让 html2canvas 的文本切分直接抛错
 * - structuredClone：唯一调用点已用 typeof 守卫并自带 JSON 回退，不补
 * - Intl.Segmenter：只在导出路径按需加载，见 exportPdf.ts
 */
import 'core-js/actual/array/at'
import 'core-js/actual/object/has-own'
import 'core-js/actual/string/replace-all'

/**
 * performance.getEntriesByType 噪音守卫（ADR 0026）。
 *
 * web-vitals v6 的 FCP / CLS / INP / LCP 都会经 getVisibilityWatcher 查询
 * `visibility-state` 性能条目；Chrome 81 不认识该条目类型，调用时会在控制台
 * 打印「Deprecated API for given entry type」。缺失该条目类型时直接返回空数组，
 * 与浏览器实际返回值一致，仅消除噪音。现代内核不受影响。
 */
let perfEntryTypesGuarded = false

export function guardUnsupportedPerfEntryTypes(): void {
  if (perfEntryTypesGuarded) return
  const supported =
    typeof PerformanceObserver === 'undefined' ? undefined : PerformanceObserver.supportedEntryTypes
  if (!Array.isArray(supported) || supported.includes('visibility-state')) return
  const perf = globalThis.performance
  const proto = perf ? (Object.getPrototypeOf(perf) as Performance) : undefined
  // lib.dom 的重载只接受 keyof PerformanceEntryMap，这里按字符串统一签名
  const getEntriesByType = proto?.getEntriesByType as unknown as
    | ((this: Performance, type: string) => PerformanceEntry[])
    | undefined
  if (!proto || typeof getEntriesByType !== 'function') return
  perfEntryTypesGuarded = true
  proto.getEntriesByType = function (this: Performance, type: string) {
    return type === 'visibility-state' ? [] : getEntriesByType.call(this, type)
  } as Performance['getEntriesByType']
}

guardUnsupportedPerfEntryTypes()
