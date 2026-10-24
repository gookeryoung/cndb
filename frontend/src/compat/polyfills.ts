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
