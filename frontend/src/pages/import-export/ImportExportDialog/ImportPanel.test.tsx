/**
 * ImportPanel 组件测试 —— 文件导入两阶段流程.
 *
 * 覆盖：idle 拖拽上传区渲染 / 非法扩展名拦截 / 上传分析成功轮询到预览 /
 * 确认导入成功（轮询到 done + onImported 回调）/ 轮询到 failed 的错误分支 /
 * analyze 接口失败提示 / open=false 状态重置（轮询定时器清理）。
 *
 * 说明：multipart FormData 请求在 jsdom+MSW 下无法拦截（同 FileImportPreview.test），
 * 统一在 api 层用 vi.spyOn mock（vite restoreMocks: true 自动还原）；
 * 轮询间隔 800ms 为真实定时器，断言时放宽 findBy 超时等待首个 tick。
 */

import { describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { fireEvent, screen } from '@testing-library/react'
import ImportPanel from './ImportPanel'
import { renderProviders } from '@/test/render-providers'
import { importApi } from '@/api'
import type { ImportTaskInfo } from '@/api'
import type { ValidationReport } from '@/api/types'

const csvFile = new File(['姓名,分数\n张三,90'], '客户数据.csv', { type: 'text/csv' })
const txtFile = new File(['hello'], '说明.txt', { type: 'text/plain' })

/** 构造后端异步导入任务 fixture */
function makeTask(overrides: Partial<ImportTaskInfo> = {}): ImportTaskInfo {
  return {
    task_id: 77, status: 'pending', progress: 0,
    filename: '客户数据.csv', format: 'csv',
    imported_rows: null, error_message: null,
    validation_report: null,
    ...overrides,
  }
}

/** 预览阶段的校验报告：3 行新增 + 1 行有字段变化的更新 + 1 个待创建新字段 */
const previewReport = {
  total: 4, valid_count: 3, warning_count: 0, error_count: 0,
  new_count: 3, update_count: 1, update_changed_count: 1, multi_key_conflicts: 0,
  skipped_columns: [], missing_required: [],
  planned_columns: [{ name: '城市', field_type: 'text', sample_values: ['上海'] }],
  new_preview: [
    { row_number: 1, match_key_values: {}, field_sample: { 姓名: '张三', 分数: '90' } },
    { row_number: 2, match_key_values: {}, field_sample: { 姓名: '李四', 分数: '85' } },
  ],
  update_preview: [
    {
      row_number: 3, match_key_values: { 姓名: '王五' }, existing_row_id: 42,
      field_sample: { 分数: '95' },
      field_diffs: { 分数: { old: '88', new: '95', changed: true } },
    },
  ],
  warnings: [], errors: [],
} as unknown as ValidationReport

const previewTask = makeTask({ status: 'pending_confirm', progress: 60, validation_report: previewReport })
const doneTask = makeTask({ status: 'done', progress: 100, imported_rows: 5 })
const failedTask = makeTask({ status: 'failed', progress: 40, error_message: '第 3 行日期格式错误' })

/** 模拟向 Dragger 的隐藏 input 选择文件 */
function chooseFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  fireEvent.change(input, { target: { files: [file] } })
}

function setup(onImported?: () => void) {
  return renderProviders(<ImportPanel open wid="10" tid="100" onClose={() => { }} onImported={onImported} />)
}

describe('ImportPanel 导入面板', () => {
  it('open=true 渲染拖拽上传区', () => {
    setup()

    expect(screen.getByText('点击或拖拽文件到此处')).toBeInTheDocument()
    expect(screen.getByText(/支持 CSV \/ JSON \/ XLSX/)).toBeInTheDocument()
  })

  it('非法扩展名被拦截：提示支持的格式且不发起分析', async () => {
    const analyzeSpy = vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(previewTask)
    setup()

    chooseFile(txtFile)

    expect(await screen.findByText('仅支持 .csv / .json / .xlsx 文件')).toBeInTheDocument()
    expect(analyzeSpy).not.toHaveBeenCalled()
  })

  it('上传成功：先显示分析中，轮询首个 tick 后进入预览（统计三卡 + 确认按钮）', async () => {
    const analyzeSpy = vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(makeTask())
    vi.spyOn(importApi, 'getTask').mockResolvedValue(previewTask)
    setup()

    chooseFile(csvFile)

    // 上传即发起 analyze（不带 matchKeys，未知列走默认策略）
    expect(analyzeSpy).toHaveBeenCalledWith('10', '100', csvFile, [], 'add_text_field')
    expect(await screen.findByText('处理中...')).toBeInTheDocument()

    // 预览面板：进度摘要 + 三卡统计 + Diff 控制 + 操作按钮
    expect(await screen.findByText(/选择参考列/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('客户数据.csv')).toBeInTheDocument()
    expect(screen.getByText('校验完成，等待确认')).toBeInTheDocument()
    expect(screen.getByText('待新增 (3)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认导入（新增 3 / 更新 1）' })).toBeEnabled()
  })

  it('确认导入成功：confirm 请求发出，轮询到 done 后提示行数并回调 onImported', async () => {
    const onImported = vi.fn()
    vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(makeTask())
    const confirmSpy = vi.spyOn(importApi, 'confirmImport').mockResolvedValue({ task_id: 77, status: 'running', message: 'ok' })
    const getTaskSpy = vi.spyOn(importApi, 'getTask')
    getTaskSpy.mockResolvedValue(previewTask)
    setup(onImported)

    chooseFile(csvFile)
    fireEvent.click(await screen.findByRole('button', { name: '确认导入（新增 3 / 更新 1）' }, { timeout: 3000 }))

    expect(confirmSpy).toHaveBeenCalledWith('10', '100', 77, [], 'add_text_field', [], [])
    // 切换轮询返回值为 done，下一个 tick（约 800ms）触发完成分支
    getTaskSpy.mockResolvedValue(doneTask)
    expect(await screen.findByText('导入完成：5 行', {}, { timeout: 3000 })).toBeInTheDocument()
    // 进度摘要里"已完成"与"已导入 N 行"在同一 span（两个直接文本节点合并），用正则匹配
    expect(await screen.findByText(/已完成/)).toBeInTheDocument()
    expect(onImported).toHaveBeenCalledTimes(1)
  })

  it('轮询到 failed：提示失败原因并进入失败终态', async () => {
    vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(makeTask())
    vi.spyOn(importApi, 'getTask').mockResolvedValue(failedTask)
    setup()

    chooseFile(csvFile)

    expect(await screen.findByText('导入失败：第 3 行日期格式错误', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '导入另一份' })).toBeInTheDocument()
    // antd Button 对两个汉字自动插入空格，可访问名实际为"关 闭"
    expect(screen.getByRole('button', { name: /关\s*闭/ })).toBeInTheDocument()
  })

  it('analyze 接口失败：透出后端错误信息', async () => {
    vi.spyOn(importApi, 'previewAnalyze').mockRejectedValue(new Error('文件解析失败：CSV 列数不一致'))
    setup()

    chooseFile(csvFile)

    expect(await screen.findByText('文件解析失败：CSV 列数不一致')).toBeInTheDocument()
  })

  it('open=false 触发状态重置：回到上传区且轮询定时器被清理', async () => {
    vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(makeTask())
    const getTaskSpy = vi.spyOn(importApi, 'getTask').mockResolvedValue(previewTask)

    // 用内部状态开关模拟外层 Modal 关闭
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <>
          <button onClick={() => setOpen(false)}>force-close</button>
          <ImportPanel open={open} wid="10" tid="100" onClose={() => { }} />
        </>
      )
    }
    renderProviders(<Harness />)

    chooseFile(csvFile)
    expect(await screen.findByText('处理中...')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'force-close' }))
    expect(await screen.findByText('点击或拖拽文件到此处')).toBeInTheDocument()

    // 等待超过一个轮询周期，确认轮询已被清理（getTask 一次都没轮询到）
    await new Promise(r => setTimeout(r, 1000))
    expect(getTaskSpy).not.toHaveBeenCalled()
  })
})
