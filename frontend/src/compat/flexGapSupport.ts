/** flex gap 能力探测 —— Chrome 81 只支持 grid gap，不能用 @supports (gap: 1px) 判断。
 *
 * 单独成模块，让入口能在不下载 shim 的前提下完成探测（ADR 0026 D5）。
 */

export function isFlexGapSupported(doc?: Document): boolean {
  const target = doc ?? (typeof document !== 'undefined' ? document : null)
  if (!target || !target.body) return true

  const host = target.createElement('div')
  host.setAttribute('data-cn-flex-probe', 'host')
  host.style.cssText = 'position:absolute;top:-9999px;left:-9999px;display:flex;gap:10px;width:100px;height:10px;visibility:hidden;pointer-events:none'

  const first = target.createElement('span')
  first.setAttribute('data-cn-flex-probe', 'a')
  first.style.cssText = 'display:block;width:10px;height:10px;flex:0 0 auto'
  const second = target.createElement('span')
  second.setAttribute('data-cn-flex-probe', 'b')
  second.style.cssText = 'display:block;width:10px;height:10px;flex:0 0 auto'

  host.appendChild(first)
  host.appendChild(second)
  target.body.appendChild(host)

  const a = first.getBoundingClientRect()
  const b = second.getBoundingClientRect()
  host.parentNode?.removeChild(host)

  // 期望：首元素右沿到次元素左沿正好 10px；不支持 flex gap 时为 0
  return Math.abs(b.left - a.right - 10) < 0.5
}
