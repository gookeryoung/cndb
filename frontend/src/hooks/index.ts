/**
 * 通用 hooks 统一出口（barrel）.
 *
 * 收纳约定：
 * - 仅收领域无关的通用 hooks；调用点 ≥2 个、或与既有 hook 成对且可预期复用（如
 *   useDebouncedValue 与 useDebouncedCallback）；
 * - 领域 hooks 就近共置：api 层 React Query hooks 留在 src/api/hooks.ts，
 *   页面专用 hooks（如 useNewRowAutoScroll）留在页面目录，主题留 src/theme；
 * - 支持直接路径引用（@/hooks/useXxx）与 barrel（@/hooks）两种导入方式.
 */
export { useResponsive } from './useResponsive'
export type { ResponsiveState, DeviceType } from './useResponsive'
export { BREAKPOINTS } from './useResponsive'
export { useDebouncedValue } from './useDebouncedValue'
export { useDebouncedCallback } from './useDebouncedCallback'
export { useElementSize } from './useElementSize'
export type { ElementSize } from './useElementSize'
