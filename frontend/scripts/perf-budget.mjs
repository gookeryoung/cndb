/**
 * 旧内核（Chromium 81 / Edge 81）性能阈值唯一来源（ADR 0117 C6 / D5 / D7）。
 *
 * 冒烟脚本与断言只引用本文件，禁止在别处散落数字；阈值按首次同机实测标定，
 * 之后只允许收紧，放宽须在 ADR 0117 的「决策记录」追加理由。
 *
 * 采集口径：`PerformanceObserver('longtask')` 的最长任务 + 「点击→下一帧」时延
 * （Chromium 81 无 Event Timing / INP，只能手工计时）。视图 / 主题测量前先预热一轮，
 * 首次懒加载 chunk 属于一次性加载成本，不计入「切换（不含网络）」口径。
 */
export const PERF_BUDGET = Object.freeze({
  /** 主题切换：点击主题卡片 → 下一帧（含 React 提交与全页主题变量重算） */
  themeSwitchMs: 200,
  /** 视图切换：点击视图按钮 → 下一帧（含同步渲染，不含网络请求） */
  viewSwitchMs: 800,
  /** 首屏可交互：导航开始 → 应用头部与内容可交互 */
  firstInteractiveMs: 3000,
  /** 主题切换期间单次长任务上限 */
  themeLongTaskMs: 250,
  /** 视图切换期间单次长任务上限（未单独列出的视图） */
  viewLongTaskMs: 250,
  /** 按视图覆盖的长任务上限（ADR 0117 D7：看板卡片挂载是 Chromium 81 已知热点） */
  viewLongTaskByModeMs: Object.freeze({
    kanban: 1000,
  }),
})
