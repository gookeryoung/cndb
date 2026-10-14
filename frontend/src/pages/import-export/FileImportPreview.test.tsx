/**
 * FileImportPreview 组件测试 —— 文件导入预览.
 *
 * 覆盖：open 开关 / 渲染结构（默认表名/字段列表/统计） /
 * 类型实时转换展示（成功 → 对比与失败警示）/ 切换单选自动填充选项 /
 * 建表导入成功与失败 / 表名空校验。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import FileImportPreview from './FileImportPreview'
import { renderProviders } from '@/test/render-providers'
import { importApi } from '@/api'
import type { FileAnalyzeResult, FileImportResult } from '@/api'

const analyzeResult: FileAnalyzeResult = {
  filename: '客户数据.csv',
  format: 'csv',
  total_rows: 3,
  columns: [
    { name: '姓名', field_type: 'text', sample_values: ['张三'], null_ratio: 0 },
    { name: '分数', field_type: 'float', sample_values: ['90'], null_ratio: 0 },
  ],
  sample_rows: [
    { 姓名: '张三', 分数: '1,234.5' },
    { 姓名: '李四', 分数: 'oops' },
    { 姓名: '', 分数: '80' },
  ],
}

const file = new File(['姓名,分数\n张三,90'], '客户数据.csv', { type: 'text/csv' })

function setup() {
  const onClose = vi.fn()
  const onSuccess = vi.fn()
  renderProviders(
    <FileImportPreview
      open
      wid={10}
      file={file}
      analyzeResult={analyzeResult}
      onClose={onClose}
      onSuccess={onSuccess}
    />,
  )
  return { onClose, onSuccess }
}

describe('FileImportPreview 文件导入预览', () => {
  it('open=false 时不渲染', () => {
    renderProviders(
      <FileImportPreview open={false} wid={10} file={null} analyzeResult={null} onClose={() => { }} />,
    )

    expect(screen.queryByText(/导入数据预览/)).not.toBeInTheDocument()
  })

  it('open=true 渲染默认表名/字段列表/统计信息', () => {
    setup()

    expect(screen.getByText(/导入数据预览/)).toBeInTheDocument()
    const nameInput = screen.getByPlaceholderText('自动使用文件名') as HTMLInputElement
    expect(nameInput.value).toBe('客户数据')
    expect(screen.getByText('字段与类型（2）')).toBeInTheDocument()
    expect(screen.getByText('CSV · 3 行')).toBeInTheDocument()
    expect(screen.getByText('总行数')).toBeInTheDocument()
  })

  it('类型实时转换：成功值显示 → 对比，失败值显示原始值', () => {
    setup()

    // '1,234.5' 转 float 成功 → 显示转换后对比
    expect(screen.getByText('→ 1234.5')).toBeInTheDocument()
    // 'oops' 无法转为 float → 原值保留（删除线）
    expect(screen.getByText('oops')).toBeInTheDocument()
  })

  it('切换字段类型为单选：自动填充选项并显示编辑区', async () => {
    setup()

    // 打开第一个字段（姓名）的类型下拉并选择「单选」
    const selector = document.querySelectorAll('.ant-select-selector')[0]!
    fireEvent.mouseDown(selector)
    fireEvent.click(await screen.findByText('单选'))

    // 选项由 sample_rows 唯一值自动填充（空值跳过）：张三/李四 → 2 个
    expect(await screen.findByText(/的选项（2 个）/)).toBeInTheDocument()
    expect(screen.getByText('含 select')).toBeInTheDocument()
  })

  it('建表并导入成功：提示统计并回调 onSuccess/onClose', async () => {
    const { onClose, onSuccess } = setup()
    // multipart FormData 请求 msw 拦截器无法处理（jsdom 兼容性问题），在 api 层 mock
    const createSpy = vi.spyOn(importApi, 'createFromFile').mockResolvedValue({
      table_id: 1,
      table_name: '客户数据',
      imported_rows: 3,
      field_count: 2,
    } as FileImportResult)

    fireEvent.click(screen.getByRole('button', { name: /建表并导入$/ }))

    expect(await screen.findByText('已创建表 "客户数据"，导入 3 行')).toBeInTheDocument()
    expect(createSpy).toHaveBeenCalledWith(10, file, '客户数据', {})
    expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ table_id: 1, imported_rows: 3 }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('建表并导入失败：提示后端 detail 错误且不关闭', async () => {
    const { onClose } = setup()
    vi.spyOn(importApi, 'createFromFile').mockRejectedValue(new Error('表名已存在'))

    fireEvent.click(screen.getByRole('button', { name: /建表并导入$/ }))

    expect(await screen.findByText('表名已存在')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('表名为空白时提示请输入表名且不发起请求', async () => {
    const { onClose, onSuccess } = setup()

    fireEvent.change(screen.getByPlaceholderText('自动使用文件名'), { target: { value: '  ' } })
    fireEvent.click(screen.getByRole('button', { name: /建表并导入$/ }))

    expect(await screen.findByText('请输入表名')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
  })
})

describe('FileImportPreview 推断提示展示（timestamp/longtext）', () => {
  /** 后端推断层可产出 timestamp/longtext —— analyze 结果含这两类列 */
  const tsResult: FileAnalyzeResult = {
    filename: '事件日志.csv',
    format: 'csv',
    total_rows: 2,
    columns: [
      { name: '创建时间戳', field_type: 'timestamp', sample_values: ['1717200000000'], null_ratio: 0 },
      { name: '备注', field_type: 'longtext', sample_values: ['第一行\n第二行'], null_ratio: 0 },
    ],
    sample_rows: [
      { 创建时间戳: '1717200000000', 备注: '第一行\n第二行' },
      { 创建时间戳: 'oops', 备注: '' },
    ],
  }

  function setupTs() {
    renderProviders(
      <FileImportPreview
        open
        wid={10}
        file={file}
        analyzeResult={tsResult}
        onClose={() => { }}
      />,
    )
  }

  it('推断出的 timestamp/longtext 在下拉中显示中文标签而非原始英文值', () => {
    setupTs()

    // 下拉选中值与右侧表头 Tag 均以中文标签渲染（时间戳/多行文本）
    expect(screen.getAllByText('时间戳').length).toBeGreaterThan(0)
    expect(screen.getAllByText('多行文本').length).toBeGreaterThan(0)
  })

  it('识别提示行：timestamp/longtext 各自显示推断来源提示', () => {
    setupTs()

    expect(screen.getByText(/识别为时间戳/)).toBeInTheDocument()
    expect(screen.getByText(/识别为长文本/)).toBeInTheDocument()
  })

  it('timestamp 转换预览：毫秒归一为秒显示 → 对比，值域外原值警示', () => {
    setupTs()

    // '1717200000000'（毫秒）→ 归一为秒显示转换对比
    expect(screen.getByText('→ 1717200000')).toBeInTheDocument()
    // 'oops' 不在候选值域 → 原值保留（失败警示）
    expect(screen.getByText('oops')).toBeInTheDocument()
  })
})

describe('FileImportPreview 图片列预览（WPS 带图片单元格 xlsx）', () => {
  /** 后端 analyze 对 WPS 图片列返回 image 类型，sample_rows 值为图片元数据数组 */
  const wpsResult: FileAnalyzeResult = {
    filename: '商品.xlsx',
    format: 'xlsx',
    total_rows: 2,
    columns: [
      { name: '名称', field_type: 'text', sample_values: ['商品A'], null_ratio: 0 },
      { name: '图片', field_type: 'image', sample_values: ['[图片] image1.png'], null_ratio: 0 },
    ],
    sample_rows: [
      {
        名称: '商品A',
        图片: [{ file_key: '', filename: 'image1.png', size: 95, mime_type: 'image/png' }],
      },
      {
        名称: '商品B',
        图片: [{ file_key: '', filename: 'image2.png', size: 95, mime_type: 'image/png' }],
      },
    ],
  }

  function setupWps() {
    renderProviders(
      <FileImportPreview
        open
        wid={10}
        file={new File(['x'], '商品.xlsx')}
        analyzeResult={wpsResult}
        onClose={() => { }}
      />,
    )
  }

  it('image 列在下拉/表头显示中文标签「图片」', () => {
    setupWps()

    expect(screen.getAllByText('图片').length).toBeGreaterThan(0)
  })

  it('图片元数据数组渲染为「[图片] 文件名」友好文本，无失败警示', () => {
    setupWps()

    expect(screen.getAllByText('[图片] image1.png').length).toBeGreaterThan(0)
    expect(screen.getAllByText('[图片] image2.png').length).toBeGreaterThan(0)
    // 字段卡片无转换失败红色计数 Tag
    const failTags = document.querySelectorAll('.ant-tag-red')
    expect(failTags.length).toBe(0)
  })
})
