/** 导出格式偏好（exportPrefs）—— 默认 XLSX + 记住上次选择.
 *
 * 覆盖：未写过 / 合法值 / 脏值 / 存储不可用（读写都不得抛错）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_EXPORT_FORMAT,
  EXPORT_FORMAT_KEY,
  loadExportFormat,
  saveExportFormat,
} from './exportPrefs'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('loadExportFormat', () => {
  it('未写过偏好时默认 XLSX', () => {
    expect(DEFAULT_EXPORT_FORMAT).toBe('xlsx')
    expect(loadExportFormat()).toBe('xlsx')
  })

  it('返回上次保存的合法格式', () => {
    saveExportFormat('csv')
    expect(loadExportFormat()).toBe('csv')
    saveExportFormat('pdf')
    expect(loadExportFormat()).toBe('pdf')
  })

  it('脏值回退默认 XLSX', () => {
    localStorage.setItem(EXPORT_FORMAT_KEY, 'exe')
    expect(loadExportFormat()).toBe('xlsx')
    localStorage.setItem(EXPORT_FORMAT_KEY, '')
    expect(loadExportFormat()).toBe('xlsx')
  })

  it('存储不可用时回退默认且不抛错', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(loadExportFormat()).toBe('xlsx')
  })
})

describe('saveExportFormat', () => {
  it('写入固定键，跨会话可读', () => {
    saveExportFormat('json')
    expect(localStorage.getItem(EXPORT_FORMAT_KEY)).toBe('json')
    expect(loadExportFormat()).toBe('json')
  })

  it('存储不可用时静默失败', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(() => saveExportFormat('csv')).not.toThrow()
  })
})
