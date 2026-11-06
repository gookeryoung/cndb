/** 认证页静态晶格背景：一次生成、整页常驻（ADR 0016）.
 *
 * 用尖顶六边形铺满画布，形成低透明度「晶格」纹理；每 3 行 / 3 列的交点放一颗
 * 青紫交替的结点。整张图只绘制一次，不启动 rAF、不随指针变化，因此登录页空闲时
 * 不再持续占用 CPU / GPU。颜色只来自 `--cn-auth-*` token（I3）。
 */

import { withAlpha } from './palette'
import type { LatticeFrame } from './types'

const CELL_DESKTOP = 46
const CELL_MOBILE = 34
const LINE_ALPHA = 0.085
const NODE_ALPHA = 0.34
const NODE_RADIUS = 1.7
const TAU = Math.PI * 2

/** 六边形外接圆半径（CSS px）；移动端更密一点以保持纹理存在感 */
export function latticeCell(isMobile: boolean): number {
  return isMobile ? CELL_MOBILE : CELL_DESKTOP
}

export function drawLattice(frame: LatticeFrame): void {
  const { ctx, width, height, dpr, palette, isMobile } = frame
  if (width <= 0 || height <= 0) return

  // 尖顶六边形：宽 √3·s、高 2s；行距 1.5s，奇数行横向错开半个步长
  const radius = latticeCell(isMobile) * dpr
  const stepX = Math.sqrt(3) * radius
  const stepY = 1.5 * radius
  const cols = Math.ceil(width / stepX) + 1
  const rows = Math.ceil(height / stepY) + 1
  const offsetOf = (row: number) => (row % 2 === 1 ? stepX / 2 : 0)

  ctx.lineWidth = Math.max(1, dpr * 0.75)
  ctx.strokeStyle = withAlpha(palette.ink, LINE_ALPHA)
  ctx.beginPath()
  for (let row = 0; row <= rows; row += 1) {
    const offsetX = offsetOf(row)
    for (let col = 0; col <= cols; col += 1) {
      const cx = col * stepX + offsetX
      const cy = row * stepY
      for (let corner = 0; corner < 6; corner += 1) {
        const angle = (Math.PI / 3) * corner - Math.PI / 6
        const x = cx + Math.cos(angle) * radius
        const y = cy + Math.sin(angle) * radius
        if (corner === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.closePath()
    }
  }
  ctx.stroke()

  // 稀疏结点：青 / 紫两组各批量一次 fillStyle，减少状态切换
  const nodeRadius = NODE_RADIUS * dpr
  const groups: Array<{ color: string; points: Array<[number, number]> }> = [
    { color: withAlpha(palette.accent, NODE_ALPHA), points: [] },
    { color: withAlpha(palette.accentAlt, NODE_ALPHA), points: [] },
  ]
  for (let row = 0; row <= rows; row += 3) {
    const offsetX = offsetOf(row)
    for (let col = 0; col <= cols; col += 3) {
      groups[(row + col) % 2].points.push([col * stepX + offsetX, row * stepY])
    }
  }

  for (const group of groups) {
    if (group.points.length === 0) continue
    ctx.fillStyle = group.color
    for (const [x, y] of group.points) {
      ctx.beginPath()
      ctx.arc(x, y, nodeRadius, 0, TAU)
      ctx.fill()
    }
  }
}
