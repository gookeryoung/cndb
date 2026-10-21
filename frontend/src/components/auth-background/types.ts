/** 认证页动态背景：变体 ID、元数据与绘制接口（ADR 0014）.
 *
 * 本模块保持「零依赖 + 极小体积」：AuthLayout 会静态引入元数据与偏好，
 * 真正的绘制实现只随 lazy chunk 加载。
 */

export const AUTH_BACKGROUND_VARIANTS = [
  'constellation',
  'nebula',
  'aurora',
  'rain',
  'orbs',
] as const

export type AuthBackgroundVariant = (typeof AUTH_BACKGROUND_VARIANTS)[number]

export interface AuthBackgroundMeta {
  id: AuthBackgroundVariant
  label: string
  description: string
}

export const AUTH_BACKGROUND_META: readonly AuthBackgroundMeta[] = [
  { id: 'constellation', label: '星座', description: '星点近邻连线，缓慢漂移' },
  { id: 'nebula', label: '星云', description: '螺旋星尘与核心辉光' },
  { id: 'aurora', label: '极光', description: '噪声驱动的带状光幕' },
  { id: 'rain', label: '数字雨', description: '字符列下落与拖尾' },
  { id: 'orbs', label: '光点', description: '柔光圆斑慢速游移' },
]

export function isAuthBackgroundVariant(value: string): value is AuthBackgroundVariant {
  return (AUTH_BACKGROUND_VARIANTS as readonly string[]).includes(value)
}

export interface Palette {
  brand: string
  text: string
  bg: string
}

export interface FrameContext {
  ctx: CanvasRenderingContext2D
  width: number
  height: number
  palette: Palette
  isDark: boolean
  isMobile: boolean
  /** 归一化指针位置，范围 -1..1；非桌面或 reduced-motion 时恒为 0 */
  pointer: { x: number; y: number }
}

/** 5 个变体统一实现的生命周期接口 */
export interface BackgroundVariant {
  /** 视口尺寸变化时重建粒子 / 列 / 光带状态 */
  resize(c: FrameContext): void
  /** 绘制一帧；引擎保证每帧只调用一次且已 clear */
  frame(c: FrameContext, timeMs: number): void
}
