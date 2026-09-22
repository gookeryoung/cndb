/** webVitals 单元测试 —— 指标注册、环形缓冲上限、dev 打印、sendBeacon 上报 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Metric } from 'web-vitals'

type VitalsCallback = (metric: Metric) => void

// mock web-vitals：捕获各指标回调，测试内手动触发
const callbacks: Record<string, VitalsCallback> = {}
vi.mock('web-vitals', () => ({
    onCLS: vi.fn((cb: VitalsCallback) => { callbacks.CLS = cb }),
    onINP: vi.fn((cb: VitalsCallback) => { callbacks.INP = cb }),
    onLCP: vi.fn((cb: VitalsCallback) => { callbacks.LCP = cb }),
    onFCP: vi.fn((cb: VitalsCallback) => { callbacks.FCP = cb }),
    onTTFB: vi.fn((cb: VitalsCallback) => { callbacks.TTFB = cb }),
}))

import { reportWebVitals } from './webVitals'

function makeMetric(name: string, value: number, rating: Metric['rating'] = 'good'): Metric {
    return { name, value, rating, id: `${name}-1`, delta: value, navigationType: 'navigate' } as Metric
}

beforeEach(() => {
    vi.clearAllMocks()
    const w = window as unknown as { __cndWebVitals?: Metric[]; __cndVitalsEndpoint?: string }
    delete w.__cndWebVitals
    delete w.__cndVitalsEndpoint
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe('reportWebVitals 注册', () => {
    it('注册全部 5 项核心指标且回调唯一（同一 pushMetric 通道）', async () => {
        const { onCLS, onINP, onLCP, onFCP, onTTFB } = await import('web-vitals')
        reportWebVitals()
        expect(onCLS).toHaveBeenCalledTimes(1)
        expect(onINP).toHaveBeenCalledTimes(1)
        expect(onLCP).toHaveBeenCalledTimes(1)
        expect(onFCP).toHaveBeenCalledTimes(1)
        expect(onTTFB).toHaveBeenCalledTimes(1)
    })

    it('重复调用幂等（重复注册不崩溃）', () => {
        expect(() => {
            reportWebVitals()
            reportWebVitals()
        }).not.toThrow()
    })
})

describe('指标缓冲', () => {
    it('指标写入 window.__cndWebVitals', () => {
        reportWebVitals()
        callbacks.LCP(makeMetric('LCP', 1200))
        const buffer = (window as unknown as { __cndWebVitals?: Metric[] }).__cndWebVitals
        expect(buffer).toHaveLength(1)
        expect(buffer![0].name).toBe('LCP')
        expect(buffer![0].value).toBe(1200)
    })

    it('环形缓冲：超过 50 条丢弃最旧一条', () => {
        reportWebVitals()
        for (let i = 0; i < 55; i++) callbacks.LCP(makeMetric('LCP', i))
        const buffer = (window as unknown as { __cndWebVitals?: Metric[] }).__cndWebVitals!
        expect(buffer).toHaveLength(50)
        expect(buffer[0].value).toBe(5) // 前 5 条被丢弃
        expect(buffer.at(-1)!.value).toBe(54)
    })

    it('dev 环境 console.debug 含指标名与评级', () => {
        const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => { })
        reportWebVitals()
        callbacks.FCP(makeMetric('FCP', 987.654, 'needs-improvement'))
        expect(debugSpy).toHaveBeenCalledOnce()
        expect(String(debugSpy.mock.calls[0][0])).toContain('FCP')
        expect(String(debugSpy.mock.calls[0][0])).toContain('987.65')
        expect(String(debugSpy.mock.calls[0][0])).toContain('needs-improvement')
    })
})

describe('sendBeacon 上报', () => {
    it('配置端点时按 JSON Blob 上报指标与路径', () => {
        const beacon = vi.fn()
        Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
            ; (window as unknown as { __cndVitalsEndpoint?: string }).__cndVitalsEndpoint = 'https://example.com/vitals'
        reportWebVitals()
        callbacks.TTFB(makeMetric('TTFB', 88))
        expect(beacon).toHaveBeenCalledOnce()
        const [url, blob] = beacon.mock.calls[0] as [string, Blob]
        expect(url).toBe('https://example.com/vitals')
        return blob.text().then((text) => {
            const payload = JSON.parse(text)
            expect(payload).toMatchObject({ name: 'TTFB', value: 88, rating: 'good' })
            expect(payload.path).toBe(window.location.pathname)
        })
    })

    it('未配置端点时不调用 sendBeacon', () => {
        const beacon = vi.fn()
        Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
        reportWebVitals()
        callbacks.CLS(makeMetric('CLS', 0.01))
        expect(beacon).not.toHaveBeenCalled()
    })

    it('sendBeacon 缺失（旧浏览器）时不抛错', () => {
        Object.defineProperty(navigator, 'sendBeacon', { value: undefined, configurable: true })
            ; (window as unknown as { __cndVitalsEndpoint?: string }).__cndVitalsEndpoint = 'https://example.com/vitals'
        reportWebVitals()
        expect(() => callbacks.INP(makeMetric('INP', 100))).not.toThrow()
    })
})

describe('Array.prototype.at polyfill（模块内置）', () => {
    it('缺 at 的数组走 polyfill 路径：负索引与越界', async () => {
        vi.resetModules()
        const originalAt = Array.prototype.at
        // 模拟旧内核：删除 at 再加载模块
        delete (Array.prototype as unknown as Record<string, unknown>).at
        try {
            await import('./webVitals')
            const arr = [1, 2, 3]
            expect(arr.at(-1)).toBe(3)
            expect(arr.at(-3)).toBe(1)
            expect(arr.at(1)).toBe(2)
            expect(arr.at(-4)).toBeUndefined()
            expect(arr.at(3)).toBeUndefined()
            // 不可枚举、可写可配置（符合规范描述）
            const desc = Object.getOwnPropertyDescriptor(Array.prototype, 'at')!
            expect(desc.enumerable).toBe(false)
            expect(desc.writable).toBe(true)
            expect(desc.configurable).toBe(true)
        } finally {
            Object.defineProperty(Array.prototype, 'at', originalAt as never)
            vi.resetModules()
        }
    })
})
