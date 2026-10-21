/** 认证页动态背景：色板、帧上下文与绘制接口（ADR 0016）.
 *
 * 本模块保持「零依赖 + 极小体积」：真正的绘制实现只随 lazy chunk 加载。
 */

export interface Palette {
  /** 青紫渐变起点 / 终点：青色 */
  accent: string
  /** 青紫渐变中段：紫色 */
  accentAlt: string
  /** 固定浅色中性色：网格与卡片描边 */
  ink: string
}

export interface FrameContext {
  ctx: CanvasRenderingContext2D
  width: number
  height: number
  palette: Palette
  isMobile: boolean
  /** 归一化指针位置，范围 -1..1；非桌面或 reduced-motion 时恒为 0 */
  pointer: { x: number; y: number }
}

/** 背景动效统一实现的绘制接口 */
export interface BackgroundVariant {
  /** 视口尺寸变化时重建粒子和渐变 */
  resize(c: FrameContext): void
  /** 绘制一帧；引擎保证每帧只调用一次且已 clear */
  frame(c: FrameContext, timeMs: number): void
}
