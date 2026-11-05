/** 视口定向常量表（ADR 0103 D11 / C3）—— 机械制图术语 + Z-up 世界下的方向向量.
 *
 * 纯数据 + 纯函数，不引 three：单测直接断言方位与 up，不必进入 WebGL。
 * 方位定义（Z-up，观察者站在 dir 一侧看向原点）：主视 = 从 −Y 看 +Y，俯视 = 从 +Z 向下。
 */

export type ViewOrientation = 'front' | 'back' | 'top' | 'bottom' | 'left' | 'right' | 'iso'

export interface ViewPreset {
  key: ViewOrientation
  label: string
  /** 相机相对目标的方向单位向量（从目标指向相机） */
  dir: [number, number, number]
  /** 相机 up（俯视 / 仰视改 +Y，避免与视线共线导致 lookAt 退化） */
  up: [number, number, number]
}

export const VIEW_PRESETS: ViewPreset[] = [
  { key: 'front', label: '主视', dir: [0, -1, 0], up: [0, 0, 1] },
  { key: 'top', label: '俯视', dir: [0, 0, 1], up: [0, 1, 0] },
  { key: 'bottom', label: '仰视', dir: [0, 0, -1], up: [0, 1, 0] },
  { key: 'left', label: '左视', dir: [-1, 0, 0], up: [0, 0, 1] },
  { key: 'right', label: '右视', dir: [1, 0, 0], up: [0, 0, 1] },
  { key: 'back', label: '后视', dir: [0, 1, 0], up: [0, 0, 1] },
  { key: 'iso', label: '等轴测', dir: [1, -1, 0.65], up: [0, 0, 1] },
]

/** 按 key 取预设（未知 key 返回 undefined，调用方静默忽略） */
export function viewPreset(key: string): ViewPreset | undefined {
  return VIEW_PRESETS.find(preset => preset.key === key)
}
