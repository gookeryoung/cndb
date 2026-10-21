/** 认证页宇宙星系动效（ADR 0016 D2 / P2）.
 *
 * 固定种子生成 2~3 座大小、倾角、色相各异的旋臂星系：每座星系由中心核球 +
 * 两条对数螺线星臂 + 弥散星尘组成。星点只保存盘面极坐标，每帧按「内快外慢」
 * 的差分角速度自转，再经各自的三轴倾斜矩阵投影到屏幕；倾斜角同时以不同相位、
 * 不同方向做缓慢进动，几座星系因此始终朝不同方向相互翻滚。
 * 每座星系有外晕 + 核球两层缓存的径向渐变，亮星再垫一圈柔光，叠加成朦胧的雾状盘面。
 * 首帧即完整可见，reduced-motion 的静帧与正常动画共用同一套采样。
 */

import { withAlpha } from './palette'
import type { BackgroundVariant, Palette } from './types'

const TAU = Math.PI * 2
const SPIN_SCALE = 0.00005
const TWINKLE_SCALE = 0.0016
const BLOOM_THRESHOLD = 0.55
const PITCH_SWAY = 0.1
const YAW_SWAY = 0.18

interface GalaxySpec {
  /** 归一化中心，相对视口宽高 */
  cx: number
  cy: number
  /** 盘半径相对 max(width, height) */
  scale: number
  stars: number
  /** 基础三轴倾角（rad） */
  pitch: number
  yaw: number
  roll: number
  /** 自转方向与倍率；负值 = 反向旋转 */
  spin: number
  /** 指针视差强度（px），移动端不生效 */
  parallax: number
  /** 多轴进动速度（rad/ms），保持极慢 */
  pitchSpeed: number
  yawSpeed: number
  rollSpeed: number
  phase: number
  /** 色相权重：0 = 青为主，1 = 紫为主 */
  hue: number
}

const DESKTOP_GALAXIES: readonly GalaxySpec[] = [
  {
    cx: 0.72,
    cy: 0.3,
    scale: 0.54,
    stars: 1000,
    pitch: 0.62,
    yaw: 0.26,
    roll: -0.32,
    spin: 1,
    parallax: 22,
    pitchSpeed: 0.00005,
    yawSpeed: 0.00007,
    rollSpeed: 0.000022,
    phase: 0,
    hue: 0,
  },
  {
    cx: 0.2,
    cy: 0.78,
    scale: 0.34,
    stars: 380,
    pitch: 1.02,
    yaw: -0.5,
    roll: 0.78,
    spin: -0.72,
    parallax: 12,
    pitchSpeed: 0.00004,
    yawSpeed: 0.00006,
    rollSpeed: -0.000018,
    phase: 2.1,
    hue: 1,
  },
  {
    cx: 0.94,
    cy: 0.84,
    scale: 0.21,
    stars: 220,
    pitch: 0.38,
    yaw: 0.86,
    roll: 0.18,
    spin: 1.35,
    parallax: 8,
    pitchSpeed: 0.00006,
    yawSpeed: 0.00005,
    rollSpeed: 0.00003,
    phase: 4.2,
    hue: 0.45,
  },
]

const MOBILE_GALAXIES: readonly GalaxySpec[] = [
  {
    cx: 0.5,
    cy: 0.22,
    scale: 0.62,
    stars: 470,
    pitch: 0.58,
    yaw: 0.2,
    roll: -0.3,
    spin: 1,
    parallax: 0,
    pitchSpeed: 0.00005,
    yawSpeed: 0.00007,
    rollSpeed: 0.000022,
    phase: 0,
    hue: 0,
  },
  {
    cx: 0.16,
    cy: 0.84,
    scale: 0.34,
    stars: 230,
    pitch: 1.02,
    yaw: -0.45,
    roll: 0.8,
    spin: -0.72,
    parallax: 0,
    pitchSpeed: 0.00004,
    yawSpeed: 0.00006,
    rollSpeed: -0.000018,
    phase: 2.1,
    hue: 1,
  },
]

function createRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0x100000000
  }
}

/** 近正态抖动：三均匀求和，够用且比 Box-Muller 少一半代码 */
function gaussian(random: () => number): number {
  return (random() + random() + random() - 1.5) * 1.7
}

interface Star {
  /** 归一化盘半径，1 = 星系边缘 */
  radius: number
  angle: number
  /** rad/ms，内圈快、外圈慢 */
  spin: number
  size: number
  alpha: number
  twinkle: number
  phase: number
  /** 0 = accent 青，1 = accent-alt 紫，2 = ink 亮白 */
  group: number
}

interface Galaxy {
  spec: GalaxySpec
  stars: Star[]
  halo: CanvasGradient | null
  core: CanvasGradient | null
  cx: number
  cy: number
  radius: number
  coreRadius: number
}

function createStars(count: number, random: () => number): Star[] {
  const stars: Star[] = []

  for (let index = 0; index < count; index += 1) {
    const roll = random()
    let radius: number
    let angle: number
    let group: number
    let size: number
    let alpha: number

    if (roll < 0.18) {
      // 核球：半径小、亮度高，形成中心光团
      radius = Math.abs(gaussian(random)) * 0.12
      angle = random() * TAU
      group = random() < 0.62 ? 2 : 1
      size = 1.4 + random() * 1.8
      alpha = 0.5 + random() * 0.42
    } else if (roll < 0.54) {
      // 星臂：沿两条对数螺线撒点，切向抖动形成臂厚
      const arm = Math.floor(random() * 2) * (TAU / 2)
      const t = Math.pow(random(), 0.85)
      radius = 0.08 + t * 0.94
      angle = arm + t * TAU * 1.12 + gaussian(random) * (0.1 + 0.08 / radius)
      group = random() < 0.5 ? 0 : 1
      size = 0.9 + random() * 1.3
      alpha = 0.26 + random() * 0.44
    } else {
      // 弥散星尘：量大、亮度低，叠加成雾状盘面
      radius = Math.sqrt(random()) * 1.08
      angle = random() * TAU
      group = random() < 0.55 ? 1 : 0
      size = 0.7 + random() * 1.0
      alpha = 0.12 + random() * 0.24
    }

    stars.push({
      radius,
      angle,
      spin: SPIN_SCALE / (0.35 + radius),
      size,
      alpha,
      twinkle: TWINKLE_SCALE * (0.5 + random()),
      phase: random() * TAU,
      group,
    })
  }

  // 按颜色分组排序：每座星系逐帧只需切换 3 次 fillStyle
  return stars.sort((a, b) => a.group - b.group)
}

export function createGalaxy(isMobile: boolean): BackgroundVariant {
  const specs = isMobile ? MOBILE_GALAXIES : DESKTOP_GALAXIES
  let width = 0
  let height = 0
  let palette: Palette | null = null
  let galaxies: Galaxy[] = []
  let colors: string[] = []

  function rebuild(w: number, h: number, next: Palette) {
    width = w
    height = h
    palette = next
    const span = Math.max(w, h)
    galaxies = specs.map((spec, index) => ({
      spec,
      stars: createStars(spec.stars, createRandom(0x9e3779b9 + index * 0x85ebca6b)),
      halo: null,
      core: null,
      cx: w * spec.cx,
      cy: h * spec.cy,
      radius: span * spec.scale,
      coreRadius: span * spec.scale * 0.34,
    }))
    colors = [
      withAlpha(next.accent, 0.72),
      withAlpha(next.accentAlt, 0.66),
      withAlpha(next.ink, 0.78),
    ]
  }

  /** 外晕：从亮核到盘面青紫再到大范围淡色，多层色标形成朦胧光雾 */
  function ensureHalo(ctx: CanvasRenderingContext2D, galaxy: Galaxy, next: Palette) {
    if (galaxy.halo) return galaxy.halo
    const main = galaxy.spec.hue > 0.5 ? next.accentAlt : next.accent
    const secondary = galaxy.spec.hue > 0.5 ? next.accent : next.accentAlt
    const gradient = ctx.createRadialGradient(
      galaxy.cx,
      galaxy.cy,
      0,
      galaxy.cx,
      galaxy.cy,
      galaxy.radius * 1.15,
    )
    gradient.addColorStop(0, withAlpha(next.ink, 0.12))
    gradient.addColorStop(0.16, withAlpha(main, 0.24))
    gradient.addColorStop(0.42, withAlpha(secondary, 0.12))
    gradient.addColorStop(0.74, withAlpha(main, 0.06))
    gradient.addColorStop(1, 'transparent')
    galaxy.halo = gradient
    return gradient
  }

  /** 核球辉光：小半径高亮，让中心像一团发光雾气而不是点阵 */
  function ensureCore(ctx: CanvasRenderingContext2D, galaxy: Galaxy, next: Palette) {
    if (galaxy.core) return galaxy.core
    const main = galaxy.spec.hue > 0.5 ? next.accentAlt : next.accent
    const gradient = ctx.createRadialGradient(
      galaxy.cx,
      galaxy.cy,
      0,
      galaxy.cx,
      galaxy.cy,
      galaxy.coreRadius,
    )
    gradient.addColorStop(0, withAlpha(next.ink, 0.3))
    gradient.addColorStop(0.45, withAlpha(main, 0.18))
    gradient.addColorStop(1, 'transparent')
    galaxy.core = gradient
    return gradient
  }

  /** 裁到画布内的填充区域：渐变坐标不变，只减少实际填充像素 */
  function fillNear(
    ctx: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    reach: number,
  ): void {
    const left = Math.max(0, cx - reach)
    const top = Math.max(0, cy - reach)
    const right = Math.min(width, cx + reach)
    const bottom = Math.min(height, cy + reach)
    if (right <= left || bottom <= top) return
    ctx.fillRect(left, top, right - left, bottom - top)
  }

  function drawGalaxy(
    ctx: CanvasRenderingContext2D,
    galaxy: Galaxy,
    timeMs: number,
    pointer: { x: number; y: number },
    next: Palette,
  ) {
    const { spec } = galaxy
    const pitch = spec.pitch + Math.sin(timeMs * spec.pitchSpeed + spec.phase) * PITCH_SWAY
    const yaw = spec.yaw + Math.sin(timeMs * spec.yawSpeed + spec.phase * 1.7) * YAW_SWAY
    const roll = spec.roll + timeMs * spec.rollSpeed
    const cp = Math.cos(pitch)
    const sp = Math.sin(pitch)
    const cy = Math.cos(yaw)
    const sy = Math.sin(yaw)
    const cr = Math.cos(roll)
    const sr = Math.sin(roll)

    // R = Rz(roll) · Rx(pitch) · Ry(yaw) 的前两行；z 轴用于前后景明暗
    const m00 = cr * cy - sr * sp * sy
    const m01 = -sr * cp
    const m10 = sr * cy + cr * sp * sy
    const m11 = cr * cp
    const m20 = -cp * sy
    const m21 = sp

    const originX = galaxy.cx + pointer.x * spec.parallax
    const originY = galaxy.cy + pointer.y * spec.parallax

    ctx.globalCompositeOperation = 'source-over'
    ctx.fillStyle = ensureHalo(ctx, galaxy, next)
    fillNear(ctx, galaxy.cx, galaxy.cy, galaxy.radius * 1.15)
    ctx.fillStyle = ensureCore(ctx, galaxy, next)
    fillNear(ctx, galaxy.cx, galaxy.cy, galaxy.coreRadius)

    let currentGroup = -1
    ctx.globalCompositeOperation = 'lighter'
    for (const star of galaxy.stars) {
      if (star.group !== currentGroup) {
        currentGroup = star.group
        ctx.fillStyle = colors[currentGroup]
      }
      const angle = star.angle + timeMs * star.spin * spec.spin
      const distance = star.radius * galaxy.radius
      const x3 = Math.cos(angle) * distance
      const y3 = Math.sin(angle) * distance
      const x = originX + x3 * m00 + y3 * m01
      const y = originY + x3 * m10 + y3 * m11
      // 盘面前侧更亮、后侧更暗，补足倾斜后的立体感
      const depth = (x3 * m20 + y3 * m21) / galaxy.radius
      const shade = 0.88 + (depth + 1) * 0.06
      const twinkle = 0.72 + 0.28 * Math.sin(star.phase + timeMs * star.twinkle)

      // 亮星先垫一圈低透明度大点，模拟镜头上的柔光晕
      if (star.alpha > BLOOM_THRESHOLD) {
        ctx.globalAlpha = star.alpha * twinkle * shade * 0.16
        ctx.fillRect(x - star.size, y - star.size, star.size * 3, star.size * 3)
      }
      ctx.globalAlpha = star.alpha * twinkle * shade
      ctx.fillRect(x, y, star.size, star.size)
    }
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height, c.palette)
    },

    frame(c, timeMs) {
      if (!width || !height || !palette || galaxies.length === 0) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)

      for (const galaxy of galaxies) {
        drawGalaxy(ctx, galaxy, timeMs, c.pointer, palette)
      }

      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
    },
  }
}
