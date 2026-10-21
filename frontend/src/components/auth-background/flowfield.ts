/** 认证页唯一动效：Perlin 流场粒子（ADR 0016 D2）.
 *
 * 粒子沿 Perlin 噪声场的方向持续漂移，每个粒子维护一段环形尾迹（最近 N 个位置），
 * 每帧把尾迹连成一条青紫渐变的发光流线；不填充底色，固定深色舞台由 `.auth-shell` 提供。
 *
 * 噪声用固定种子的 LCG 生成置换表，保证每次加载得到同一张场（可复现、可测试）。
 * 首帧先把尾迹缓冲灌满（等价于已经跑了 N 帧），因此正常动画与 reduced-motion
 * 静帧都能立刻看到完整流线，不存在「只有首帧有轨迹」的问题。
 */

import { withAlpha } from './palette'
import type { BackgroundVariant, Palette } from './types'

const TAU = Math.PI * 2
const DESKTOP_PARTICLES = 800
const MOBILE_PARTICLES = 320
const DESKTOP_TRAIL = 40
const MOBILE_TRAIL = 26
const FIELD_SCALE = 0.0032
const SPEED_SCALE = 0.06
const MAX_STEP_MS = 48
const WARMUP_STEP_MS = 8
const RESPAWN_MARGIN = 32

// ── Perlin 噪声（固定种子） ────────────────────────────────────────────

function buildPermutation(seed: number): Uint8Array {
  const base = new Uint8Array(256)
  for (let index = 0; index < 256; index += 1) base[index] = index
  let state = seed >>> 0
  for (let index = 255; index > 0; index -= 1) {
    state = (state * 1664525 + 1013904223) >>> 0
    const target = state % (index + 1)
    const swap = base[index]
    base[index] = base[target]
    base[target] = swap
  }
  const perm = new Uint8Array(512)
  for (let index = 0; index < 512; index += 1) perm[index] = base[index & 255]
  return perm
}

const PERM = buildPermutation(0x6d2b79f5)

function fade(t: number): number {
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function grad(hash: number, x: number, y: number): number {
  switch (hash & 7) {
    case 0:
      return x + y
    case 1:
      return -x + y
    case 2:
      return x - y
    case 3:
      return -x - y
    case 4:
      return x
    case 5:
      return -x
    case 6:
      return y
    default:
      return -y
  }
}

/** 经典 improved Perlin 2D，返回 -1..1 */
export function noise2(x: number, y: number): number {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const xf = x - xi
  const yf = y - yi
  const X = xi & 255
  const Y = yi & 255
  const u = fade(xf)
  const v = fade(yf)
  const aa = PERM[PERM[X] + Y]
  const ab = PERM[PERM[X] + Y + 1]
  const ba = PERM[PERM[X + 1] + Y]
  const bb = PERM[PERM[X + 1] + Y + 1]
  const lower = lerp(grad(aa, xf, yf), grad(ba, xf - 1, yf), u)
  const upper = lerp(grad(ab, xf, yf - 1), grad(bb, xf - 1, yf - 1), u)
  return lerp(lower, upper, v)
}

// ── 粒子系统 ──────────────────────────────────────────────────────────

interface Particle {
  x: number
  y: number
  speed: number
  life: number
  /** 环形尾迹下一个写入位置（也是最旧的位置） */
  head: number
  trailX: Float32Array
  trailY: Float32Array
}

function createRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0x100000000
  }
}

export function createFlowField(isMobile: boolean): BackgroundVariant {
  const particleCount = isMobile ? MOBILE_PARTICLES : DESKTOP_PARTICLES
  const trailLength = isMobile ? MOBILE_TRAIL : DESKTOP_TRAIL
  let width = 0
  let height = 0
  let particles: Particle[] = []
  let palette: Palette | null = null
  let gradient: CanvasGradient | null = null
  let lastFrameMs: number | null = null
  let warmedUp = false
  let random = createRandom(0x2f6e2b1)

  function respawn(particle: Particle) {
    particle.x = random() * width
    particle.y = random() * height
    particle.speed = SPEED_SCALE * (0.55 + random() * 0.9)
    particle.life = 2400 + random() * 5200
    particle.head = 0
    // 重生先把尾迹压在当前位置，几帧后自然展开，避免跨屏拉出长线
    particle.trailX.fill(particle.x)
    particle.trailY.fill(particle.y)
  }

  function rebuild(w: number, h: number, nextPalette: Palette) {
    width = w
    height = h
    palette = nextPalette
    gradient = null
    lastFrameMs = null
    warmedUp = false
    random = createRandom(0x2f6e2b1)
    particles = Array.from({ length: particleCount }, () => {
      const particle: Particle = {
        x: 0,
        y: 0,
        speed: 0,
        life: 0,
        head: 0,
        trailX: new Float32Array(trailLength),
        trailY: new Float32Array(trailLength),
      }
      respawn(particle)
      return particle
    })
  }

  function update(particle: Particle, ms: number, drift: number, pointerBias: number) {
    particle.life -= ms
    if (
      particle.life <= 0 ||
      particle.x < -RESPAWN_MARGIN ||
      particle.x > width + RESPAWN_MARGIN ||
      particle.y < -RESPAWN_MARGIN ||
      particle.y > height + RESPAWN_MARGIN
    ) {
      respawn(particle)
    }
    const angle =
      noise2(particle.x * FIELD_SCALE + drift, particle.y * FIELD_SCALE - drift) * TAU +
      pointerBias
    particle.x += Math.cos(angle) * particle.speed * ms
    particle.y += Math.sin(angle) * particle.speed * ms
    particle.trailX[particle.head] = particle.x
    particle.trailY[particle.head] = particle.y
    particle.head = (particle.head + 1) % trailLength
  }

  /** 尾迹缓冲已由 warmup 灌满；每帧把所有粒子轨迹一次性描边 */
  function draw(ctx: CanvasRenderingContext2D) {
    ctx.beginPath()
    for (const particle of particles) {
      const oldest = particle.head
      ctx.moveTo(particle.trailX[oldest], particle.trailY[oldest])
      for (let index = 1; index < trailLength; index += 1) {
        const cursor = (oldest + index) % trailLength
        ctx.lineTo(particle.trailX[cursor], particle.trailY[cursor])
      }
    }
    ctx.stroke()
  }

  /** 预热：只推进粒子、填满尾迹缓冲，不描边 */
  function warmup(drift: number, pointerBias: number) {
    const steps = trailLength + 8
    for (let step = 0; step < steps; step += 1) {
      for (const particle of particles) {
        update(particle, WARMUP_STEP_MS, drift, pointerBias)
      }
    }
  }

  function ensureGradient(ctx: CanvasRenderingContext2D, colors: Palette): CanvasGradient {
    if (gradient) return gradient
    const next = ctx.createLinearGradient(0, height * 0.1, width, height * 0.9)
    const accent = withAlpha(colors.accent, 0.55)
    const accentAlt = withAlpha(colors.accentAlt, 0.6)
    next.addColorStop(0, accent)
    next.addColorStop(0.5, accentAlt)
    next.addColorStop(1, accent)
    gradient = next
    return next
  }

  return {
    resize(c) {
      if (c.width > 0 && c.height > 0) rebuild(c.width, c.height, c.palette)
    },

    frame(c, timeMs) {
      if (!width || !height || !palette || particles.length === 0) return
      const { ctx } = c
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.clearRect(0, 0, width, height)
      ctx.lineWidth = 1
      ctx.strokeStyle = ensureGradient(ctx, palette)

      const drift = timeMs * 0.00004
      const pointerBias = isMobile ? 0 : c.pointer.x * 0.24 + c.pointer.y * 0.12

      if (!warmedUp) {
        warmedUp = true
        warmup(drift, pointerBias)
      } else {
        const dt =
          lastFrameMs === null ? 16 : Math.min(MAX_STEP_MS, Math.max(1, timeMs - lastFrameMs))
        for (const particle of particles) {
          update(particle, dt, drift, pointerBias)
        }
      }
      lastFrameMs = timeMs

      ctx.globalCompositeOperation = 'lighter'
      draw(ctx)
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
    },
  }
}
