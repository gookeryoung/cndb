/**
 * 旧内核（Chromium 81 / Edge 81）性能阈值唯一来源（ADR 0117 C6 / D5）。
 *
 * 冒烟脚本与断言只引用本文件，禁止在别处散落数字；阈值初值经 P0 实测后只允许收紧，
 * 放宽须在 ADR 0117 的「决策记录」追加理由。
 *
 * 采集口径：`PerformanceObserver('longtask')` 的最长任务 + 「点击→下一帧」时延
 * （Chromium 81 无 Event Timing / INP，只能手工计时）。
 */
export const PERF_BUDGET = Object.freeze({
  /** 主题切换：点击主题卡片 → 下一帧（含 React 提交与全页主题变量重算） */
  themeSwitchMs: 200,
  /** 视图切换：点击视图按钮 → 下一帧（含同步渲染，不含网络请求） */
  viewSwitchMs: 800,
  /** 首屏可交互：导航开始 → 应用头部与内容可交互 */
  firstInteractiveMs: 3000,
  /** 单次长任务上限（主题切换、视图切换期间） */
  maxLongTaskMs: 250,
})
