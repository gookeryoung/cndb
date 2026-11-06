/** 认证页静态晶格背景：色板与一次绘制所需的上下文（ADR 0016）.
 *
 * 本模块保持「零依赖 + 极小体积」：真正的绘制实现只随 lazy chunk 加载。
 */

export interface Palette {
  /** 青紫渐变起点 / 终点：青色 */
  accent: string
  /** 青紫渐变中段：紫色 */
  accentAlt: string
  /** 固定浅色中性色：晶格线与卡片描边 */
  ink: string
}

/** 一次静态绘制所需的上下文；尺寸与线宽均按设备像素计算 */
export interface LatticeFrame {
  ctx: CanvasRenderingContext2D
  /** 画布位图宽度（设备像素） */
  width: number
  /** 画布位图高度（设备像素） */
  height: number
  /** 位图与 CSS 像素的比值（已按设备档位封顶） */
  dpr: number
  palette: Palette
  isMobile: boolean
}
