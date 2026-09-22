/** Web Vitals 采集 —— FCP / LCP / CLS / INP / TTFB.
 *
 * 项目暂无监控后端，指标先落地到两处：
 * - window.__cndWebVitals：环形缓冲（最多 50 条），供浏览器控制台与 E2E 性能用例读取；
 * - 开发环境额外 console.debug 打印（含 good / needs-improvement / poor 评级）。
 *
 * 未来接入后端时，只需在页面注入 window.__cndVitalsEndpoint（接收 POST 的 URL），
 * 指标即通过 sendBeacon 自动上报，调用方无需改动。
 *
 * 本模块经由动态 import() 加载（见 main.tsx），web-vitals 不会进入主入口 chunk。
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals'

interface WebVitalsWindow extends Window {
  __cndWebVitals?: Metric[]
  __cndVitalsEndpoint?: string
}

const BUFFER_LIMIT = 50

function pushMetric(metric: Metric): void {
  const w = window as WebVitalsWindow
  const buffer = (w.__cndWebVitals ??= [])
  buffer.push(metric)
  // 环形缓冲：超出上限丢弃最旧一条，防止长会话无限增长
  if (buffer.length > BUFFER_LIMIT) buffer.shift()

  if (import.meta.env.DEV) {
    console.debug(`[web-vitals] ${metric.name} ${metric.value.toFixed(2)} (${metric.rating})`, metric)
  }

  // 配置了上报端点时静默尝试投递；埋点失败不得影响主流程
  const endpoint = w.__cndVitalsEndpoint
  if (endpoint) {
    const payload = JSON.stringify({ name: metric.name, value: metric.value, rating: metric.rating, path: window.location.pathname })
    navigator.sendBeacon?.(endpoint, new Blob([payload], { type: 'application/json' }))
  }
}

/** 注册全部核心指标监听；模块只动态加载一次，天然幂等。 */
export function reportWebVitals(): void {
  onCLS(pushMetric)
  onINP(pushMetric)
  onLCP(pushMetric)
  onFCP(pushMetric)
  onTTFB(pushMetric)
}
