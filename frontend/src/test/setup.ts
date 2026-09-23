/**
 * Vitest 全局测试 setup：
 * - 注册 jest-dom 匹配器
 * - antd 5 在 jsdom 下的所需 polyfill（matchMedia / ResizeObserver / getBoundingClientRect / scrollTo）
 * - RTL 自动 cleanup（globals 模式下 @testing-library/react 依赖 afterEach）
 * - 每个用例后清空 localStorage / sessionStorage，保证用例间隔离
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
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
  // jsdom 未实现 IntersectionObserver（antd 虚拟滚动可能用到）
  if (!window.IntersectionObserver) {
    class IntersectionObserverPolyfill {
      root = null
      rootMargin = ''
      thresholds = []
      observe = vi.fn()
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

beforeAll(() => {
  // MSW 网络层拦截：漏配端点直接报错，防止测试悄悄打到真实网络
  server.listen({ onUnhandledRequest: 'error' })
})

// 每个用例后自动清理：DOM 卸载 + 本地存储清空 + MSW handlers 还原
// 注：zustand store 为单例（按测试文件隔离），store 状态由 renderProviders
// 的 initialAuth 或各测试文件的 beforeEach 管理，不在此全局复位 ——
// 避免 afterEach 触发 persist 写 localStorage 与异常注入用例互相干扰。
afterEach(() => {
  // 纯逻辑测试跑在 node 环境（无 document/window），DOM 清理相关步骤全部守卫跳过
  if (typeof document !== 'undefined') {
    cleanup()
    // antd 静态 Modal.confirm / message 渲染在 React 树之外的容器，cleanup() 无法卸载；
    // jsdom 不跑动画导致 destroyAll 的离场动画永不结束，残留的遮罩与文本会干扰后续用例
    document.querySelectorAll('.ant-modal-root, .ant-message, .ant-notification').forEach((n) => n.remove())
  }
  if (typeof window !== 'undefined') {
    window.localStorage.clear()
    window.sessionStorage.clear()
  }
  server.resetHandlers()
})

afterAll(() => {
  server.close()
  server.events.removeAllListeners()
})
