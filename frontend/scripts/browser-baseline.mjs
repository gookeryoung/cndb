/**
 * 浏览器兼容基线 —— 构建目标、静态门禁、老内核冒烟共用同一份常量。
 *
 * 禁止在 vite.config / check-browser-compat / chrome81-smoke 里各写一份 target：
 * 三处漂移时门禁会失去判别力（构建降级了但冒烟仍用旧版本，或反之）。
 *
 * 基线与不承诺范围见 ADR 0026 与 README「浏览器基线」。
 */
export const BROWSER_BASELINE = 'chrome81'

/** 与 .browserslistrc 保持一致；browserslist 没有 chrome81 这种写法，故单独维护一份。 */
export const BROWSERLIST_ENTRIES = ['chrome >= 81', 'edge >= 81']

/** 老内核冒烟使用的 Chromium 快照 revision（≈ Chrome 81.0.4044）。
 *  与 BROWSER_BASELINE 绑在一起，避免冒烟脚本悄悄换版本而门禁失去判别力（ADR 0026 D9）。 */
export const CHROMIUM81_REVISION = '737027'

