/**
 * Vitest 全局测试 setup：
 * - 注册 jest-dom 匹配器
 * - antd 5 在 jsdom 下的所需 polyfill（matchMedia / ResizeObserver / getBoundingClientRect / scrollTo）
 * - RTL 自动 cleanup（globals 模式下 @testing-library/react 依赖 afterEach）
 * - 每个用例后清空 localStorage / sessionStorage，保证用例间隔离
 */
import '@testing-library/jest-dom/vitest'
import { act, cleanup } from '@testing-library/react'
import { message } from 'antd'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { server } from './msw'

// ── polyfill：matchMedia（antd 响应式断点依赖）────────────────────────
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(), // 已废弃但仍被部分 antd 代码使用
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}

// ── polyfill：ResizeObserver（antd 布局测量依赖）──────────────────────
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  class ResizeObserverPolyfill {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
  }
  window.ResizeObserver = ResizeObserverPolyfill as unknown as typeof ResizeObserver
}

// ── polyfill：元素尺寸与滚动（antd 弹层定位依赖）──────────────────────
if (typeof window !== 'undefined') {
  if (!window.scrollTo) {
    window.scrollTo = vi.fn()
  }
  if (!Element.prototype.scrollTo) {
    Element.prototype.scrollTo = vi.fn()
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn()
  }
  if (!Element.prototype.getBoundingClientRect) {
    Element.prototype.getBoundingClientRect = () => ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      toJSON: () => ({}),
    }) as DOMRect
  }
  // jsdom 未实现 IntersectionObserver（antd 虚拟滚动 + KanbanColumn 懒挂载用到）
  // polyfill：observe 后立即触发 isIntersecting=true 的回调（测试环境所有元素"都可见"）
  if (!window.IntersectionObserver) {
    class IntersectionObserverPolyfill {
      root = null
      rootMargin = ''
      thresholds: number[] = []
      private callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
        this.callback = callback
        // IntersectionObserverInit.threshold 可能是 number 或 number[]
        this.thresholds = options?.threshold !== undefined
          ? (Array.isArray(options.threshold) ? options.threshold : [options.threshold])
          : []
      }
      observe = (target: Element) => {
        // 同步触发 isIntersecting=true，让懒挂载组件直接渲染完整内容
        // KanbanColumn 的 useEffect 在 commit 后 observe，这里同步调 callback
        // → setVisible(true) 在同一个 microtask 里被 React 批量 flush
        this.callback([{ target, isIntersecting: true } as IntersectionObserverEntry], this)
      }
      unobserve = vi.fn()
      disconnect = vi.fn()
      takeRecords = () => []
    }
    window.IntersectionObserver =
      IntersectionObserverPolyfill as unknown as typeof IntersectionObserver
  }
}

// ── polyfill：Blob.stream()（Node 22 undici 的 Response 构造依赖）─────
// jsdom 的 Blob 实现缺失 stream()。axios responseType:'blob' 的请求经
// MSW XHR 拦截器会用全局（jsdom）Blob 构造 undici Response，而 Node 22
// 的 undici extractBody 会对 Blob 调用 object.stream()，缺失即抛
// "TypeError: object.stream is not a function"，导致下载类请求中断。
// （Node 25 的 undici 不走该分支，因此本地不会暴露此问题。）
if (typeof Blob !== 'undefined' && !Blob.prototype.stream) {
  Blob.prototype.stream = function (this: Blob) {
    const arrayBufferPromise = this.arrayBuffer()
    return new ReadableStream({
      async start(controller) {
        controller.enqueue(new Uint8Array(await arrayBufferPromise))
        controller.close()
      },
    })
  }
}

// ── 抑制已知的无害 console.error 噪音（antd act 警告）──────────────────
// antd ThemeProvider 渲染的 <AntApp> 挂载 rc-notification holder 及 rc-motion，
// 会在 requestAnimationFrame 中更新状态，发生在 RTL act 作用域之外，产生
// "not wrapped in act(...)" 警告。该更新仅涉弹层动画时序，不影响任何断言；
// 仅过滤栈内命中 node_modules 下 antd / rc-* 的此类警告，业务组件自身
// 的 act 警告仍正常抛出。
const originalConsoleError = console.error.bind(console)
console.error = (...args: unknown[]) => {
  const text = args.map((a) => (typeof a === 'string' ? a : String(a))).join('\n')
  if (text.includes('not wrapped in act') && /node_modules[\\/].*(?:antd|rc-[a-z-]+)/.test(text)) {
    return
  }
  originalConsoleError(...args)
}

// ── 抑制 jsdom 伪元素 getComputedStyle 未实现警告 ──────────────────────
// antd 内部测量滚动条样式时会调 getComputedStyle(ele, '::-webkit-scrollbar')。
// jsdom 收到非空伪元素参数时会走 notImplementedMethod → virtualConsole
// → console.error 打印噪音。单线程下 patch console.error 可拦截，但多 worker
// threads 模式下 vitest 可能把 jsdomError 直接写到 worker 的独立 stderr，
// 绕过主进程的 console.error patch。因此在源头 patch window.getComputedStyle：
// 伪元素参数非空时临时屏蔽 virtualConsole，调原始实现后恢复。
if (typeof window !== 'undefined') {
  const origGetComputedStyle = window.getComputedStyle.bind(window)
  const suppressedTypes = new Set<string>(['not-implemented'])
  window.getComputedStyle = function (elt: Element, pseudoElt?: string | null): CSSStyleDeclaration {
    // 无伪元素参数或空串：走原始实现，不触发警告
    if (pseudoElt == null || pseudoElt === '') {
      return origGetComputedStyle(elt, pseudoElt ?? undefined)
    }
    // 伪元素参数非空：临时屏蔽 jsdom virtualConsole 中 type=not-implemented 的事件
    const vc = (window as unknown as { _virtualConsole?: { emit?: (evt: string, e: { type: string }) => void } })._virtualConsole
    if (vc && typeof vc.emit === 'function') {
      const origEmit = vc.emit.bind(vc)
      vc.emit = (evt: string, e: { type: string }) => {
        if (evt === 'jsdomError' && e && suppressedTypes.has(e.type)) {
          return
        }
        return origEmit(evt, e)
      }
      try {
        return origGetComputedStyle(elt, pseudoElt)
      } finally {
        vc.emit = origEmit
      }
    }
    return origGetComputedStyle(elt, pseudoElt)
  }
}

beforeAll(() => {
  // MSW 网络层拦截：漏配端点直接报错，防止测试悄悄打到真实网络
  server.listen({ onUnhandledRequest: 'error' })
})

// 每个用例后自动清理：DOM 卸载 + 本地存储清空 + MSW handlers 还原
// 注：zustand store 为单例（按测试文件隔离），store 状态由 renderProviders
// 的 initialAuth 或各测试文件的 beforeEach 管理，不在此全局复位 ——
// 避免 afterEach 触发 persist 写 localStorage 与异常注入用例互相干扰。
afterEach(async () => {
  cleanup()
  // message.destroy() 先于 DOM 摘除：卸载静态 message 容器内的全部挂起通知，
  // 触发 React unmount 清理 rc-notification 的自动关闭定时器 —— 否则定时器在
  // 测试文件结束、jsdom 环境销毁后仍会触发，回调访问 window 抛
  // "ReferenceError: window is not defined"，vitest 计为 unhandled error。
  // 首次调用会经 rc-util 在独立 ReactDOM root 上挂载静态 holder，包一层 act
  // 避免 "An update to Root ... not wrapped in act" 警告。
  await act(async () => {
    message.destroy()
  })
  // antd 静态 Modal.confirm / message 渲染在 React 树之外的容器，cleanup() 无法卸载；
  // jsdom 不跑动画导致 destroyAll 的离场动画永不结束，残留的遮罩与文本会干扰后续用例
  document.querySelectorAll('.ant-modal-root, .ant-message, .ant-notification').forEach((n) => n.remove())
  window.localStorage.clear()
  window.sessionStorage.clear()
  server.resetHandlers()
})

afterAll(() => {
  server.close()
  server.events.removeAllListeners()
})
