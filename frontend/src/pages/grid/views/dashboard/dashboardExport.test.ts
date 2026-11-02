/** dashboard 整屏导出编排测试（ADR 0023 / 原 0077 P0）.
 *
 * 覆盖：时间戳 / 文件名清洗与回退、主题背景读取与兜底、按格式分派到既有 PNG / PDF 实现。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  dashboardExportFilename,
  exportDashboard,
  formatExportTimestamp,
  resolveExportBackground,
} from './dashboardExport'

const pngMock = vi.hoisted(() => ({ exportElementToPng: vi.fn() }))
const pdfMock = vi.hoisted(() => ({ exportViewToPdf: vi.fn() }))
vi.mock('../../../import-export/ImportExportDialog/exportPng', () => ({
  exportElementToPng: pngMock.exportElementToPng,
}))
vi.mock('../../../import-export/ImportExportDialog/exportPdf', () => ({
  exportViewToPdf: pdfMock.exportViewToPdf,
}))

const DATE = new Date(2026, 10, 1, 9, 30, 15)

describe('formatExportTimestamp', () => {
  it('输出本地 YYYYMMDD_HHMMSS 并补零', () => {
    expect(formatExportTimestamp(DATE)).toBe('20261101_093015')
  })
})

describe('dashboardExportFilename', () => {
  it('按格式拼接扩展名', () => {
    expect(dashboardExportFilename('销售画布', 'png', DATE)).toBe('销售画布-20261101_093015.png')
    expect(dashboardExportFilename('销售画布', 'pdf', DATE)).toBe('销售画布-20261101_093015.pdf')
  })

  it('清洗 Windows 非法字符', () => {
    expect(dashboardExportFilename('Q1/销售:汇总*?', 'png', DATE)).toBe('Q1_销售_汇总__-20261101_093015.png')
  })

  it('空名 / 全非法字符回退「画布」', () => {
    expect(dashboardExportFilename(null, 'pdf', DATE)).toBe('画布-20261101_093015.pdf')
    expect(dashboardExportFilename('   ', 'png', DATE)).toBe('画布-20261101_093015.png')
  })
})

describe('resolveExportBackground', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('读取主题页面色', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({ getPropertyValue: () => '#141414' } as unknown as CSSStyleDeclaration)
    expect(resolveExportBackground(document.documentElement)).toBe('#141414')
  })

  it('变量为空 / 根元素缺失时回退白色', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({ getPropertyValue: () => '' } as unknown as CSSStyleDeclaration)
    expect(resolveExportBackground(document.documentElement)).toBe('#ffffff')
    expect(resolveExportBackground(null)).toBe('#ffffff')
  })
})

describe('exportDashboard 格式分派', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({ getPropertyValue: () => '#141414' } as unknown as CSSStyleDeclaration)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('png 走通用 PNG 实现，携带文件名与主题背景', async () => {
    const target = document.createElement('div')
    await exportDashboard(target, '销售画布', 'png', DATE)
    expect(pngMock.exportElementToPng).toHaveBeenCalledWith(target, '销售画布-20261101_093015.png', '#141414')
    expect(pdfMock.exportViewToPdf).not.toHaveBeenCalled()
  })

  it('pdf 走通用 PDF 实现，携带文件名与主题背景', async () => {
    const target = document.createElement('div')
    await exportDashboard(target, '销售画布', 'pdf', DATE)
    expect(pdfMock.exportViewToPdf).toHaveBeenCalledWith(target, '销售画布-20261101_093015.pdf', '#141414')
    expect(pngMock.exportElementToPng).not.toHaveBeenCalled()
  })

  it('失败向上透传，由调用方提示', async () => {
    pngMock.exportElementToPng.mockRejectedValueOnce(new Error('渲染崩溃'))
    const target = document.createElement('div')
    await expect(exportDashboard(target, '销售画布', 'png', DATE)).rejects.toThrow('渲染崩溃')
  })
})
