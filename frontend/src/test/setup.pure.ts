/**
 * 纯逻辑测试（node 环境）的极简 setup（需求 0181 C5）。
 *
 * 刻意不 import 任何 jsdom / antd / MSW 相关模块：`src/test/setup.ts` 里那套 polyfill 与
 * 网络桩是 DOM 用例的成本大头（实测 setup 占 jsdom 用例总耗时的 65%）。这里只留一条
 * 兜底清理，保证 mock 不跨用例泄漏（config 里的 restoreMocks 已覆盖 spy，这里补 vi.fn）。
 */
import { afterEach, vi } from 'vitest'

afterEach(() => {
  vi.clearAllMocks()
})
