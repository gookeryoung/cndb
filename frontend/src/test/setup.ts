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
  // jsdom 未实现 Range#getClientRects / getBoundingClientRect：CodeMirror 6 测量
  // 光标与选区坐标时依赖，缺失会在 requestAnimationFrame 里抛 TypeError 刷 stderr。
  // 返回空矩形集合即可，不影响布局无关的断言。
  if (!Range.prototype.getClientRects) {
    Range.prototype.getClientRects = () => [] as unknown as DOMRectList
  }
  if (!Range.prototype.getBoundingClientRect) {
    Range.prototype.getBoundingClientRect = () => new DOMRect(0, 0, 0, 0)
  }
  // jsdom 未实现 canvas 2D 上下文：zrender 仅用它测量文本（SVG renderer 不绘制 canvas），
  // 缺失时 jsdom 会打印 "Not implemented: getContext"，而 zrender 本就有内置换算回退。
  // 返回 null 保留回退路径，同时消除 jsdomError。
  if (typeof HTMLCanvasElement !== 'undefined') {
    HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext
  }
  // jsdom 没有布局引擎，所有元素 clientWidth/clientHeight 恒为 0，ECharts init 会告警
  // "Can't get DOM width or height"。仅给图表容器返回非零尺寸，让初始化走正常路径；
  // 其他元素维持 0，避免影响依赖真实测量值的组件（虚拟滚动等）。
  if (typeof HTMLElement !== 'undefined') {
    for (const [prop, value] of [['clientWidth', 640], ['clientHeight', 320]] as const) {
      Object.defineProperty(HTMLElement.prototype, prop, {
        configurable: true,
        get(this: HTMLElement) {
          return this.dataset?.testid === 'chart-container' ? value : 0
        },
      })
    }
  }
  // jsdom 未实现 URL.createObjectURL/revokeObjectURL（useFileObjectUrl 把鉴权 blob
  // 转成 object URL 后交给 <img>；测试只需拿到可断言的假 URL）
  if (!URL.createObjectURL) {
    let seq = 0
    URL.createObjectURL = () => `blob:mock-${++seq}`
  }
  if (!URL.revokeObjectURL) {
    URL.revokeObjectURL = () => { /* noop */ }
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
  // 抑制 antd / rc-* 在 requestAnimationFrame 中更新状态产生的 act 警告
  if (text.includes('not wrapped in act') && /node_modules[\\/].*(?:antd|rc-[a-z-]+)/.test(text)) {
    return
  }
  // 抑制 rc-trigger 在 jsdom 中 Modal + Popconfirm 组合场景下的 shadow root 警告：
  // 两者都 Portal 到 body，真实浏览器中 getRootNode() 相同；jsdom 对多 Portal
  // 根元素的 getRootNode 实现与浏览器有差异，触发条件性误报，不影响功能。
  if (text.includes('trigger element and popup element should in same shadow root')) {
    return
  }
  // 抑制 MSW onUnhandledRequest: 'error' 在 stderr 打印的"未命中 handler"错误——
  // 该配置已让请求 Promise reject（测试侧用 expect(...).rejects 断言），
  // stderr 输出纯属噪音，掩盖真正的业务报错线索。
  if (text.includes('[MSW] Error: intercepted a request without a matching request handler')) {
    return
  }
  // 过滤 antd 静态 message 的上下文警告：
  // 仓库里仍有若干页面使用 `message.xxx()`（静态调用），antd 会提示
  // "[antd: message] Static function can not consume context like dynamic theme."
  // 这是**应用级**待迁移项（应改用 App.useApp() 的 message），一次 CI 会刷出上百行；
  // 在测试输出里屏蔽，避免淹没真正的失败信息。迁移完成即可删除本过滤。
  if (text.includes('[antd: message] Static function can not consume context')) {
    return
  }
  originalConsoleError(...args)
}

// ── 修复 jsdom 伪元素 getComputedStyle 未实现警告 ──────────────────────
// antd 内部测量样式时会调 getComputedStyle(ele, '::-webkit-scrollbar')。
// jsdom 30 收到非空伪元素参数时经 virtualConsole 发 jsdomError（"Not implemented:
// Window's getComputedStyle() method: with pseudo-elements"）——多 worker 下该
// 错误直写 worker stderr，patch console.error 拦不住。且 virtualConsole 挂在
// window._settings 上（非 window._virtualConsole），事件级抑制不可靠。
// 处理：jsdom 对伪元素本来就只返回元素本身的样式声明（notImplemented 后继续
// 执行），这里直接降级为无伪元素调用，行为完全一致且不再触发警告。
if (typeof window !== 'undefined') {
  const origGetComputedStyle = window.getComputedStyle.bind(window)
  window.getComputedStyle = function (elt: Element, pseudoElt?: string | null): CSSStyleDeclaration {
    void pseudoElt
    return origGetComputedStyle(elt)
  }
}

// ── 抑制 jsdom 已知噪音（virtualConsole 层）────────────────────────────
// 以下两类 jsdomError 经 virtualConsole 转发到 worker console 并直写 stderr
// （绕过 console.error patch），需在 emit 层拦截：
// 1) "navigation to another Document"：测试中渲染下载 / 导出等逻辑会程序化
//    a.click() 触发跳转，jsdom 无法跨文档导航。
// 2) "Could not parse CSS stylesheet"（type=css-parsing）：antd cssinjs 运行时
//    注入的样式含 jsdom 内置 CSS 解析器不支持的现代语法，真实浏览器可正常解析，
//    不影响任何断言；一次全量测试会刷出数百行。仅过滤该类，其他 jsdomError 照常抛出。
if (typeof window !== 'undefined') {
  const vc = (window as unknown as {
    _settings?: { virtualConsole?: { emit?: (evt: string, e: { message?: string; type?: string }) => void } }
  })._settings?.virtualConsole
  if (vc && typeof vc.emit === 'function') {
    const origEmit = vc.emit.bind(vc)
    vc.emit = (evt: string, e: { message?: string; type?: string }) => {
      if (evt === 'jsdomError') {
        if (e?.type === 'css-parsing' || (typeof e?.message === 'string' && e.message.includes('Could not parse CSS stylesheet'))) {
          return
        }
        if (typeof e?.message === 'string' && e.message.includes('navigation to another Document')) {
          return
        }
      }
      return origEmit(evt, e)
    }
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

afterAll(async () => {
  server.close()
  server.events.removeAllListeners()
  // 文件收尾兜底：React 19 并发渲染可能自我连续调度 immediate（长链收尾），
  // 固定波数排不干净——连续排空直到连续 3 波无新任务（近似判定），上限 30 波，
  // 避免 jsdom 环境销毁后仍有回调访问 window / HTMLElement 抛
  // ReferenceError / TypeError，被 vitest 计为 unhandled error（覆盖率模式必现）。
  let idleWaves = 0
  for (let i = 0; i < 30 && idleWaves < 3; i += 1) {
    await new Promise<void>((resolve) => setImmediate(() => resolve()))
    idleWaves += 1
  }
})
