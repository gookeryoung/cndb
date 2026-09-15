/** 生成微信 tabBar 图标 —— 4 个 81x81 RGBA PNG.
 *  workspace / me 各有普通（灰）和选中（蓝）两版.
 */
const fs = require('fs')
const path = require('path')
const { PNG } = require('pngjs')

const SIZE = 81
const COLOR_GRAY = [0x6b, 0x72, 0x80, 255]   // #6b7280
const COLOR_BLUE = [0x16, 0x77, 0xff, 255]   // #1677ff
const OUT_DIR = path.resolve(__dirname, '..', 'src', 'assets', 'tab')

function newPng() {
  const png = new PNG({ width: SIZE, height: SIZE })
  // 全透明背景
  for (let i = 0; i < SIZE * SIZE * 4; i += 4) {
    png.data[i] = 0; png.data[i + 1] = 0; png.data[i + 2] = 0; png.data[i + 3] = 0
  }
  return png
}

function setPixel(png, x, y, color) {
  if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return
  const i = (y * SIZE + x) * 4
  png.data[i] = color[0]; png.data[i + 1] = color[1]; png.data[i + 2] = color[2]; png.data[i + 3] = color[3]
}

function drawRect(png, x0, y0, x1, y1, color) {
  for (let y = y0; y <= y1; y++)
    for (let x = x0; x <= x1; x++)
      setPixel(png, x, y, color)
}

function drawCircle(png, cx, cy, r, color) {
  const r2 = r * r
  for (let y = cy - r; y <= cy + r; y++)
    for (let x = cx - r; x <= cx + r; x++) {
      const dx = x - cx, dy = y - cy
      if (dx * dx + dy * dy <= r2) setPixel(png, x, y, color)
    }
}

function drawTriangle(png, x0, y0, x1, y1, x2, y2, color) {
  // 简单扫描三角形
  const minY = Math.min(y0, y1, y2), maxY = Math.max(y0, y1, y2)
  const minX = Math.min(x0, x1, x2), maxX = Math.max(x0, x1, x2)
  for (let y = minY; y <= maxY; y++)
    for (let x = minX; x <= maxX; x++)
      if (pointInTri(x, y, x0, y0, x1, y1, x2, y2))
        setPixel(png, x, y, color)
}
function pointInTri(px, py, x0, y0, x1, y1, x2, y2) {
  const s1 = sign(px, py, x0, y0, x1, y1)
  const s2 = sign(px, py, x1, y1, x2, y2)
  const s3 = sign(px, py, x2, y2, x0, y0)
  const hasNeg = (s1 < 0) || (s2 < 0) || (s3 < 0)
  const hasPos = (s1 > 0) || (s2 > 0) || (s3 > 0)
  return !(hasNeg && hasPos)
}
function sign(px, py, ax, ay, bx, by) {
  return (px - bx) * (ay - by) - (ax - bx) * (py - by)
}

/** workspace 图标：梯形屋顶 + 矩形墙 + 门洞. */
function drawWorkspace(color) {
  const png = newPng()
  // 屋顶（三角形）
  drawTriangle(png, 10, 40, 40, 10, 70, 40, color)
  // 墙体
  drawRect(png, 15, 40, 65, 70, color)
  // 挖掉门洞（透明）
  drawRect(png, 33, 50, 47, 70, [0, 0, 0, 0])
  return png
}

/** me 图标：圆形脑袋 + 梯形肩膀. */
function drawMe(color) {
  const png = newPng()
  // 脑袋
  drawCircle(png, 40, 26, 14, color)
  // 肩膀（倒梯形）
  drawTriangle(png, 12, 75, 68, 75, 40, 42, color)
  return png
}

function writeIcon(name, png) {
  const out = path.join(OUT_DIR, name)
  const buf = PNG.sync.write(png)
  fs.writeFileSync(out, buf)
  console.log(`wrote ${name} (${buf.length} bytes)`)
}

writeIcon('workspace.png', drawWorkspace(COLOR_GRAY))
writeIcon('workspace-active.png', drawWorkspace(COLOR_BLUE))
writeIcon('me.png', drawMe(COLOR_GRAY))
writeIcon('me-active.png', drawMe(COLOR_BLUE))

console.log('done')
