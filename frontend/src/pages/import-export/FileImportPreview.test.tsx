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

  it('header_detection 为 null（JSON 文件）时不渲染表头识别区域', () => {
    setup()

    expect(screen.queryByTestId('header-detection-alert')).not.toBeInTheDocument()
    expect(screen.queryByTestId('header-row-select')).not.toBeInTheDocument()
  })
})

/** 顶部有合并标题行的文件：第 1 行为标题，第 2 行才是真正表头 */
const titleRowResult: FileAnalyzeResult = {
  filename: '客户数据.csv',
  format: 'csv',
  total_rows: 3,
  columns: [
    { name: '姓名', field_type: 'text', sample_values: ['张三'], null_ratio: 0 },
    { name: '分数', field_type: 'float', sample_values: ['90'], null_ratio: 0 },
  ],
  sample_rows: [
    { 姓名: '张三', 分数: '90' },
    { 姓名: '李四', 分数: '85' },
    { 姓名: '王五', 分数: '80' },
  ],
  header_detection: {
    row: 2,
    confidence: 0.93,
    requires_review: false,
    skipped_rows: 1,
    message: '已自动识别第 2 行为表头（置信度 93%，已跳过上方 1 行标题/合并行）',
    candidates: [
      { row: 2, confidence: 0.93, values: ['姓名', '分数'] },
      { row: 1, confidence: 0.31, values: ['2024年客户数据', ''] },
    ],
  },
  header_row: 2,
}

/** 人工改选第 1 行作为表头后后端返回的新分析结果（低置信度 → 建议人工确认） */
const row1Result: FileAnalyzeResult = {
  filename: '客户数据.csv',
  format: 'csv',
  total_rows: 4,
  columns: [
    { name: '2024年客户数据', field_type: 'text', sample_values: ['姓名'], null_ratio: 0 },
    { name: 'Unnamed: 1', field_type: 'text', sample_values: ['分数'], null_ratio: 0 },
  ],
  sample_rows: [
    { '2024年客户数据': '姓名', 'Unnamed: 1': '分数' },
    { '2024年客户数据': '张三', 'Unnamed: 1': '90' },
  ],
  header_detection: {
    row: 1,
    confidence: 0.55,
    requires_review: true,
    skipped_rows: 0,
    message: '已自动识别第 1 行为表头（置信度 55%，请人工确认）',
    candidates: [
      { row: 1, confidence: 0.55, values: ['2024年客户数据', ''] },
      { row: 2, confidence: 0.52, values: ['姓名', '分数'] },
    ],
  },
  header_row: 1,
}

describe('FileImportPreview 表头行自动识别与人工改选', () => {
  function setupTitleRow() {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    renderProviders(
      <FileImportPreview
        open
        wid={10}
        file={file}
        analyzeResult={titleRowResult}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    )
    return { onClose, onSuccess }
  }

  it('展示识别结果提示、置信度与表头行下拉（默认当前识别行）', () => {
    setupTitleRow()

    expect(screen.getByTestId('header-detection-alert')).toBeInTheDocument()
    expect(screen.getByText(titleRowResult.header_detection!.message)).toBeInTheDocument()
    expect(screen.getByText('置信度 93%')).toBeInTheDocument()
    const select = screen.getByTestId('header-row-select')
    expect(select).toBeInTheDocument()
    // 下拉当前值 = header_detection.row（选中的标签文本包含候选预览）
    expect(select.textContent).toContain('第 2 行 · 93% · 姓名 / 分数')
  })

  it('改选表头行触发重新 analyze，并用新结果刷新字段列表与预览', async () => {
    setupTitleRow()
    const analyzeSpy = vi.spyOn(importApi, 'analyzeFile').mockResolvedValue(row1Result)

    fireEvent.mouseDown(screen.getByTestId('header-row-select').querySelector('.ant-select-selector')!)
    fireEvent.click(await screen.findByText(/^第 1 行 · 31%/, { selector: '.ant-select-item-option-content' }))

    expect(analyzeSpy).toHaveBeenCalledWith(10, file, 1)
    // 用新分析结果渲染：新列名出现在左侧字段列表与右侧表头，统计行数同步更新
    expect((await screen.findAllByText('2024年客户数据')).length).toBeGreaterThan(0)
    expect(await screen.findByText('CSV · 4 行')).toBeInTheDocument()
    // 新结果的提示与 warning 态（requires_review=true）生效
    expect(await screen.findByText(row1Result.header_detection!.message)).toBeInTheDocument()
    expect(screen.getByTestId('header-detection-alert').className).toContain('ant-alert-warning')
    expect(screen.getByText('置信度 55%')).toBeInTheDocument()
  })

  it('建表并导入时把当前选中的 header_row 传给后端', async () => {
    setupTitleRow()
    const createSpy = vi.spyOn(importApi, 'createFromFile').mockResolvedValue({
      table_id: 2,
      table_name: '客户数据',
      imported_rows: 3,
      field_count: 2,
    } as FileImportResult)

    fireEvent.click(screen.getByRole('button', { name: /建表并导入$/ }))

    expect(await screen.findByText('已创建表 "客户数据"，导入 3 行')).toBeInTheDocument()
    expect(createSpy).toHaveBeenCalledWith(10, file, '客户数据', {}, 2)
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
