/** 运行时兼容垫片的唯一装载入口（ADR 0026）。
 *
 * 入口只做能力探测：现代内核到此为止，flex-gap shim 永不下载；
 * 旧内核打上 cn-no-flex-gap 标记后再动态加载垫片。
 */
import { isFlexGapSupported } from './flexGapSupport'

let started = false

export function initCompat(): void {
  if (started || typeof document === 'undefined') return
  started = true
  if (isFlexGapSupported()) return
  document.documentElement.classList.add('cn-no-flex-gap')
  void import('./flexGap').then(mod => mod.initFlexGapShim())
}
