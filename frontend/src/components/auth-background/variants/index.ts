/** 变体工厂：把稳定的 UI 选择映射到绘制实现（ADR 0014 D2） */

import type { AuthBackgroundVariant, BackgroundVariant } from '../types'
import { createAurora } from './aurora'
import { createConstellation } from './constellation'
import { createNebula } from './nebula'
import { createOrbs } from './orbs'
import { createRain } from './rain'

type Factory = (isMobile: boolean) => BackgroundVariant

const FACTORIES: Record<AuthBackgroundVariant, Factory> = {
  constellation: createConstellation,
  nebula: createNebula,
  aurora: createAurora,
  rain: createRain,
  orbs: createOrbs,
}

export function createVariant(variant: AuthBackgroundVariant, isMobile: boolean): BackgroundVariant {
  return FACTORIES[variant](isMobile)
}
