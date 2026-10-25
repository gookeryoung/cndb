/** color-mix 兼容层 —— Chrome 81 不支持 color-mix()（111+），
 * 注册表在构建期由作者颜色生成 `--cn-mix-*` 兜底变量，运行时按当前主题求值。
 *
 * 单一真相源（ADR 0026）：
 * - 静态颜色：`var(--cn-mix-<name>)`，index.css / TSX 直接引用；
 * - 运行时颜色：`mixColor(a, pct, b)`，现代浏览器原样返回 color-mix()，旧内核返回字面量；
 * - 主题切换：`applyThemeMixVars()` 在 ThemeProvider 的 layout effect 里重算全部变量。
 *
 * 求值遵循 CSS Color 5 的预乘 alpha 插值，避免「透明色混出灰边」。
 */

export interface MixSpec {
  a: string
  aPct: number
  b: string
  bPct?: number
}

/** 全部 author color-mix 表达式的注册表；名字即 `--cn-mix-<name>` 的后缀 */
export const MIX_REGISTRY: Readonly<Record<string, MixSpec>> = {
  'amber-12-transparent': { a: '#f59e0b', aPct: 12, b: 'transparent', bPct: 88 },
  'amber-16-bg-container': { a: '#f59e0b', aPct: 16, b: 'var(--cn-bg-container)', bPct: 84 },
  'amber-42-transparent': { a: '#f59e0b', aPct: 42, b: 'transparent', bPct: 58 },
  'amber-45-transparent': { a: '#f59e0b', aPct: 45, b: 'transparent', bPct: 55 },
  'amber-70-text-primary': { a: '#f59e0b', aPct: 70, b: 'var(--cn-text-primary)', bPct: 30 },
  'auth-accent-16-transparent': { a: 'var(--cn-auth-accent)', aPct: 16, b: 'transparent', bPct: 84 },
  'auth-accent-55-transparent': { a: 'var(--cn-auth-accent)', aPct: 55, b: 'transparent', bPct: 45 },
  'auth-accent-70-transparent': { a: 'var(--cn-auth-accent)', aPct: 70, b: 'transparent', bPct: 30 },
  'auth-accent-alt-15-transparent': { a: 'var(--cn-auth-accent-alt)', aPct: 15, b: 'transparent', bPct: 85 },
  'auth-accent-alt-65-transparent': { a: 'var(--cn-auth-accent-alt)', aPct: 65, b: 'transparent', bPct: 35 },
  'auth-bg-42-transparent': { a: 'var(--cn-auth-bg)', aPct: 42, b: 'transparent', bPct: 58 },
  'auth-bg-58-transparent': { a: 'var(--cn-auth-bg)', aPct: 58, b: 'transparent', bPct: 42 },
  'auth-bg-82-transparent': { a: 'var(--cn-auth-bg)', aPct: 82, b: 'transparent', bPct: 18 },
  'auth-ink-14-transparent': { a: 'var(--cn-auth-ink)', aPct: 14, b: 'transparent', bPct: 86 },
  'auth-ink-18-transparent': { a: 'var(--cn-auth-ink)', aPct: 18, b: 'transparent', bPct: 82 },
  'auth-ink-5-transparent': { a: 'var(--cn-auth-ink)', aPct: 5, b: 'transparent', bPct: 95 },
  'auth-ink-78-transparent': { a: 'var(--cn-auth-ink)', aPct: 78, b: 'transparent', bPct: 22 },
  'bg-container-55-code-block-bg': { a: 'var(--cn-bg-container)', aPct: 55, b: 'var(--cn-code-block-bg)', bPct: 45 },
  'bg-container-92-brand-color-8': { a: 'var(--cn-bg-container)', aPct: 92, b: 'var(--cn-brand-color)', bPct: 8 },
  'bg-container-94-brand-color-6': { a: 'var(--cn-bg-container)', aPct: 94, b: 'var(--cn-brand-color)', bPct: 6 },
  'bg-container-97-brand-color-3': { a: 'var(--cn-bg-container)', aPct: 97, b: 'var(--cn-brand-color)', bPct: 3 },
  'bg-danger-subtle-88-transparent': { a: 'var(--cn-bg-danger-subtle)', aPct: 88, b: 'transparent', bPct: 12 },
  'blue-10-bg-container': { a: '#3b82f6', aPct: 10, b: 'var(--cn-bg-container)', bPct: 90 },
  'blue-18-bg-container': { a: '#3b82f6', aPct: 18, b: 'var(--cn-bg-container)', bPct: 82 },
  'blue-45-transparent': { a: '#3b82f6', aPct: 45, b: 'transparent', bPct: 55 },
  'blue-8-bg-container': { a: '#3b82f6', aPct: 8, b: 'var(--cn-bg-container)', bPct: 92 },
  'border-80-transparent': { a: 'var(--cn-border)', aPct: 80, b: 'transparent', bPct: 20 },
  'brand-color-10-transparent': { a: 'var(--cn-brand-color)', aPct: 10, b: 'transparent', bPct: 90 },
  'brand-color-12-bg-container': { a: 'var(--cn-brand-color)', aPct: 12, b: 'var(--cn-bg-container)', bPct: 88 },
  'brand-color-12-transparent': { a: 'var(--cn-brand-color)', aPct: 12, b: 'transparent', bPct: 88 },
  'brand-color-14-transparent': { a: 'var(--cn-brand-color)', aPct: 14, b: 'transparent', bPct: 86 },
  'brand-color-18-transparent': { a: 'var(--cn-brand-color)', aPct: 18, b: 'transparent', bPct: 82 },
  'brand-color-22-transparent': { a: 'var(--cn-brand-color)', aPct: 22, b: 'transparent', bPct: 78 },
  'brand-color-24-border': { a: 'var(--cn-brand-color)', aPct: 24, b: 'var(--cn-border)', bPct: 76 },
  'brand-color-24-transparent': { a: 'var(--cn-brand-color)', aPct: 24, b: 'transparent', bPct: 76 },
  'brand-color-26-border': { a: 'var(--cn-brand-color)', aPct: 26, b: 'var(--cn-border)', bPct: 74 },
  'brand-color-26-transparent': { a: 'var(--cn-brand-color)', aPct: 26, b: 'transparent', bPct: 74 },
  'brand-color-30-border': { a: 'var(--cn-brand-color)', aPct: 30, b: 'var(--cn-border)', bPct: 70 },
  'brand-color-30-transparent': { a: 'var(--cn-brand-color)', aPct: 30, b: 'transparent', bPct: 70 },
  'brand-color-32-text-disabled': { a: 'var(--cn-brand-color)', aPct: 32, b: 'var(--cn-text-disabled)', bPct: 68 },
  'brand-color-32-transparent': { a: 'var(--cn-brand-color)', aPct: 32, b: 'transparent', bPct: 68 },
  'brand-color-35-border': { a: 'var(--cn-brand-color)', aPct: 35, b: 'var(--cn-border)', bPct: 65 },
  'brand-color-35-transparent': { a: 'var(--cn-brand-color)', aPct: 35, b: 'transparent', bPct: 65 },
  'brand-color-4-bg-container': { a: 'var(--cn-brand-color)', aPct: 4, b: 'var(--cn-bg-container)', bPct: 96 },
  'brand-color-40-border': { a: 'var(--cn-brand-color)', aPct: 40, b: 'var(--cn-border)', bPct: 60 },
  'brand-color-45-border': { a: 'var(--cn-brand-color)', aPct: 45, b: 'var(--cn-border)', bPct: 55 },
  'brand-color-46-border': { a: 'var(--cn-brand-color)', aPct: 46, b: 'var(--cn-border)', bPct: 54 },
  'brand-color-55-border': { a: 'var(--cn-brand-color)', aPct: 55, b: 'var(--cn-border)', bPct: 45 },
  'brand-color-55-transparent': { a: 'var(--cn-brand-color)', aPct: 55, b: 'transparent', bPct: 45 },
  'brand-color-6-bg-container': { a: 'var(--cn-brand-color)', aPct: 6, b: 'var(--cn-bg-container)', bPct: 94 },
  'brand-color-6-transparent': { a: 'var(--cn-brand-color)', aPct: 6, b: 'transparent', bPct: 94 },
  'brand-color-7-bg-container': { a: 'var(--cn-brand-color)', aPct: 7, b: 'var(--cn-bg-container)', bPct: 93 },
  'brand-color-72-black': { a: 'var(--cn-brand-color)', aPct: 72, b: '#000000', bPct: 28 },
  'brand-color-78-text-primary': { a: 'var(--cn-brand-color)', aPct: 78, b: 'var(--cn-text-primary)', bPct: 22 },
  'brand-color-8-bg-container': { a: 'var(--cn-brand-color)', aPct: 8, b: 'var(--cn-bg-container)', bPct: 92 },
  'brand-color-8-transparent': { a: 'var(--cn-brand-color)', aPct: 8, b: 'transparent', bPct: 92 },
  'brand-color-82-text-primary': { a: 'var(--cn-brand-color)', aPct: 82, b: 'var(--cn-text-primary)', bPct: 18 },
  'brand-color-85-transparent': { a: 'var(--cn-brand-color)', aPct: 85, b: 'transparent', bPct: 15 },
  'brand-color-88-white': { a: 'var(--cn-brand-color)', aPct: 88, b: '#ffffff', bPct: 12 },
  'green-10-bg-container': { a: '#22c55e', aPct: 10, b: 'var(--cn-bg-container)', bPct: 90 },
  'green-12-bg-container': { a: '#22c55e', aPct: 12, b: 'var(--cn-bg-container)', bPct: 88 },
  'green-14-bg-container': { a: '#22c55e', aPct: 14, b: 'var(--cn-bg-container)', bPct: 86 },
  'green-18-bg-container': { a: '#22c55e', aPct: 18, b: 'var(--cn-bg-container)', bPct: 82 },
  'green-40-transparent': { a: '#22c55e', aPct: 40, b: 'transparent', bPct: 60 },
  'green-8-bg-container': { a: '#22c55e', aPct: 8, b: 'var(--cn-bg-container)', bPct: 92 },
  'lime-35-transparent': { a: '#52c41a', aPct: 35, b: 'transparent', bPct: 65 },
  'primary-10-transparent': { a: 'var(--cn-primary, #1677ff)', aPct: 10, b: 'transparent', bPct: 90 },
  'primary-45-transparent': { a: 'var(--cn-primary, #1677ff)', aPct: 45, b: 'transparent', bPct: 55 },
  'red-10-bg-container': { a: '#ef4444', aPct: 10, b: 'var(--cn-bg-container)', bPct: 90 },
  'red-12-bg-container': { a: '#ef4444', aPct: 12, b: 'var(--cn-bg-container)', bPct: 88 },
  'red-14-bg-container': { a: '#ef4444', aPct: 14, b: 'var(--cn-bg-container)', bPct: 86 },
  'red-40-transparent': { a: '#ef4444', aPct: 40, b: 'transparent', bPct: 60 },
  'red-8-bg-container': { a: '#ef4444', aPct: 8, b: 'var(--cn-bg-container)', bPct: 92 },
  'shadow-color-10-transparent': { a: 'var(--cn-shadow-color)', aPct: 10, b: 'transparent', bPct: 90 },
  'shadow-color-12-transparent': { a: 'var(--cn-shadow-color)', aPct: 12, b: 'transparent', bPct: 88 },
}

interface RGBA {
  r: number
  g: number
  b: number
  a: number
}

const HEX_RE = /^#([0-9a-f]{3,8})$/i
const RGB_RE = /^rgba?\(([^)]*)\)$/i
const TRIPLE_RE = /^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$/

/** 原生支持 color-mix 时直接交给浏览器（保留主题变量联动与渐变得以按规范插值） */
function supportsColorMix(): boolean {
  return typeof CSS !== 'undefined' && typeof CSS.supports === 'function'
    && CSS.supports('background-color', 'color-mix(in srgb, red 10%, blue)')
}

type VarReader = (name: string) => string

function cssVarReader(): VarReader {
  if (typeof window === 'undefined' || typeof document === 'undefined') return () => ''
  const host = document.body ?? document.documentElement
  return name => {
    if (!host) return ''
    return window.getComputedStyle(host).getPropertyValue(name).trim()
  }
}

/** 递归展开 var(--x, fallback)，最多 4 层防环 */
function resolveValue(value: string, readVar: VarReader, depth = 0): string {
  const trimmed = value.trim()
  if (depth > 4 || !/^var\(/i.test(trimmed)) return trimmed
  const open = trimmed.indexOf('(')
  const close = trimmed.lastIndexOf(')')
  if (close < open) return trimmed
  const inner = trimmed.slice(open + 1, close)
  const comma = inner.indexOf(',')
  const name = (comma < 0 ? inner : inner.slice(0, comma)).trim()
  const fallback = comma < 0 ? '' : inner.slice(comma + 1)
  const resolved = readVar(name)
  if (resolved) return resolveValue(resolved, readVar, depth + 1)
  return fallback ? resolveValue(fallback, readVar, depth + 1) : ''
}

function parseHex(hex: string): RGBA | null {
  const digits = hex.slice(1)
  if (![3, 4, 6, 8].includes(digits.length)) return null
  const expand = (s: string) => (s.length === 1 ? s + s : s)
  const pairs = digits.length <= 4
    ? digits.split('').map(expand)
    : digits.match(/.{2}/g) ?? []
  if (pairs.length < 3) return null
  const [r, g, b] = pairs.slice(0, 3).map(p => parseInt(p, 16))
  const a = pairs[3] ? parseInt(pairs[3], 16) / 255 : 1
  return { r, g, b, a }
}

function parseAlpha(token: string | undefined): number {
  if (token == null) return 1
  const t = token.trim()
  if (!t) return 1
  if (t.endsWith('%')) return Number.parseFloat(t) / 100
  return Number.parseFloat(t)
}

function parseRgb(body: string): RGBA | null {
  // 同时兼容 `rgb(1, 2, 3)` / `rgb(1 2 3)` / `rgb(1 2 3 / .5)`
  const slash = body.split('/')
  const channels = slash[0].trim().split(/[\s,]+/).filter(Boolean)
  if (channels.length < 3) return null
  const toChannel = (c: string) => c.endsWith('%')
    ? Number.parseFloat(c) * 2.55
    : Number.parseFloat(c)
  const [r, g, b] = channels.slice(0, 3).map(toChannel)
  const alphaToken = slash.length > 1 ? slash[1] : channels[3]
  const a = parseAlpha(alphaToken)
  if ([r, g, b, a].some(n => !Number.isFinite(n))) return null
  return { r, g, b, a: Math.min(1, Math.max(0, a)) }
}

/** 解析作者颜色；`--cn-shadow-color` 是 RGB 三元组，按 rgb() 处理 */
export function parseColor(value: string, readVar: VarReader = cssVarReader()): RGBA | null {
  const resolved = resolveValue(value, readVar)
  if (!resolved) return null
  const lower = resolved.toLowerCase()
  if (lower === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
  if (lower === 'black') return { r: 0, g: 0, b: 0, a: 1 }
  if (lower === 'white') return { r: 255, g: 255, b: 255, a: 1 }
  const hex = HEX_RE.exec(resolved)
  if (hex) return parseHex(resolved)
  const rgb = RGB_RE.exec(resolved)
  if (rgb) return parseRgb(rgb[1])
  const triple = TRIPLE_RE.exec(resolved)
  if (triple) {
    return {
      r: Number.parseFloat(triple[1]),
      g: Number.parseFloat(triple[2]),
      b: Number.parseFloat(triple[3]),
      a: 1,
    }
  }
  return null
}

function normalizeWeights(aPct: number, bPct?: number): [number, number] {
  const a = Math.max(0, aPct)
  const b = bPct == null ? Math.max(0, 100 - aPct) : Math.max(0, bPct)
  const sum = a + b
  return sum > 0 ? [a / sum, b / sum] : [0.5, 0.5]
}

function clampChannel(n: number): number {
  return Math.min(255, Math.max(0, Math.round(n)))
}

/** 按 CSS Color 5 预乘 alpha 插值求字面量；任一颜色解析失败返回 null */
function mixToLiteral(spec: MixSpec, readVar: VarReader = cssVarReader()): string | null {
  const a = parseColor(spec.a, readVar)
  const b = parseColor(spec.b, readVar)
  if (!a || !b) return null
  const [wa, wb] = normalizeWeights(spec.aPct, spec.bPct)
  const alpha = a.a * wa + b.a * wb
  if (alpha <= 0) return 'transparent'
  const channel = (ca: number, cb: number) => (ca * a.a * wa + cb * b.a * wb) / alpha
  const r = clampChannel(channel(a.r, b.r))
  const g = clampChannel(channel(a.g, b.g))
  const blue = clampChannel(channel(a.b, b.b))
  if (alpha >= 1 - 1e-6) return `rgb(${r}, ${g}, ${blue})`
  return `rgba(${r}, ${g}, ${blue}, ${Math.round(alpha * 1000) / 1000})`
}

/** 运行时混色：现代内核返回原生 color-mix，Chrome 81 返回等价字面量 */
export function mixColor(colorA: string, pct: number, colorB: string): string {
  if (supportsColorMix() || typeof document === 'undefined') {
    return `color-mix(in srgb, ${colorA} ${pct}%, ${colorB})`
  }
  return mixToLiteral({
    a: colorA,
    aPct: pct,
    b: colorB,
    bPct: Math.max(0, 100 - pct),
  }) ?? `color-mix(in srgb, ${colorA} ${pct}%, ${colorB})`
}

/** 按当前主题重算全部 `--cn-mix-*` 变量（旧内核 CSS 兜底依赖它） */
export function applyThemeMixVars(root?: HTMLElement): void {
  if (typeof document === 'undefined') return
  if (supportsColorMix()) return
  const target = root ?? document.documentElement
  const readVar = cssVarReader()
  for (const [name, spec] of Object.entries(MIX_REGISTRY)) {
    const value = mixToLiteral(spec, readVar)
    if (value) target.style.setProperty(`--cn-mix-${name}`, value)
  }
}
