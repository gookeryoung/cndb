/**
 * GridCell 组件测试 —— 单元格按字段类型渲染 + inline 编辑回调.
 *
 * 三条主线：
 * 1. 展示态：DisplayCell 按字段类型分派渲染（空值/布尔/数值/日期/选择/链接/长文本等）
 * 2. 传统编辑：双击进入编辑态，Enter 提交 onSave、Escape 取消，只读字段不可编辑
 * 3. 受控编辑（行级编辑复用）：onDraftChange / onDraftCommit / onDraftCancel 回调
 * 另：link 字段编辑从 MSW 拉取目标表行作为选项。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import dayjs from 'dayjs'
import GridCell from './GridCell'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'

// ─────────────── 展示态：按字段类型分派渲染 ───────────────

describe('GridCell 展示态', () => {
  it('空值（null / 空串）渲染占位符 —', () => {
    const field = makeField({ id: 1, name: '文本', field_type: 'text' })
    const { rerender } = renderProviders(<GridCell value={null} field={field} rowId={1} />)
    expect(screen.getByText('—')).toBeInTheDocument()

    rerender(<GridCell value="" field={field} rowId={1} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('boolean 渲染为 是/否 Tag', () => {
    const field = makeField({ id: 1, name: '开关', field_type: 'boolean' })
    const { rerender } = renderProviders(<GridCell value={true} field={field} rowId={1} />)
    expect(screen.getByText('是')).toBeInTheDocument()

    rerender(<GridCell value={0} field={field} rowId={1} />)
    expect(screen.getByText('否')).toBeInTheDocument()
  })

  it('number 按 config.decimals 保留小数位', () => {
    const field = makeField({ id: 1, name: '数值', field_type: 'number', config: { decimals: 2 } })
    renderProviders(<GridCell value={3.14159} field={field} rowId={1} />)
    expect(screen.getByText('3.14')).toBeInTheDocument()
  })

  it('percentage 乘以 100 并按默认 0 位小数显示百分号', () => {
    const field = makeField({ id: 1, name: '占比', field_type: 'percentage' })
    renderProviders(<GridCell value={0.256} field={field} rowId={1} />)
    expect(screen.getByText('26%')).toBeInTheDocument()
  })

  it('date/datetime 按格式化输出', () => {
    const dateField = makeField({ id: 1, name: '日期', field_type: 'date' })
    const dtField = makeField({ id: 2, name: '时刻', field_type: 'datetime' })
    const { rerender } = renderProviders(
      <GridCell value="2026-01-05T10:30:00" field={dateField} rowId={1} />,
    )
    expect(screen.getByText('2026-01-05')).toBeInTheDocument()

    rerender(<GridCell value="2026-01-05T10:30:00" field={dtField} rowId={1} />)
    expect(screen.getByText('2026-01-05 10:30')).toBeInTheDocument()
  })

  it('timestamp（unix 秒）与 dayjs.unix 本地时区格式一致', () => {
    const field = makeField({ id: 1, name: '时间戳', field_type: 'timestamp' })
    renderProviders(<GridCell value={1700000000} field={field} rowId={1} />)
    // 用 dayjs 同源计算期望值，保证断言与运行时区无关
    expect(screen.getByText(dayjs.unix(1700000000).format('YYYY-MM-DD HH:mm:ss'))).toBeInTheDocument()
  })

  it('select 渲染为 Tag', () => {
    const field = makeField({ id: 1, name: '状态', field_type: 'select', config: { options: ['进行中', '已完成'] } })
    renderProviders(<GridCell value="进行中" field={field} rowId={1} />)
    expect(screen.getByText('进行中')).toBeInTheDocument()
    expect(document.querySelector('.ant-tag')).toBeInTheDocument()
  })

  it('multi_select 数组渲染为多个 Tag', () => {
    const field = makeField({ id: 1, name: '标签', field_type: 'multi_select', config: { options: ['红', '蓝'] } })
    renderProviders(<GridCell value={['红', '蓝']} field={field} rowId={1} />)
    expect(screen.getByText('红')).toBeInTheDocument()
    expect(screen.getByText('蓝')).toBeInTheDocument()
  })

  it('email 渲染 mailto 链接', () => {
    const field = makeField({ id: 1, name: '邮箱', field_type: 'email' })
    renderProviders(<GridCell value="a@x.com" field={field} rowId={1} />)
    expect(screen.getByText('a@x.com')).toHaveAttribute('href', 'mailto:a@x.com')
  })

  it('long_text 超过 40 字符截断加省略号', () => {
    const field = makeField({ id: 1, name: '备注', field_type: 'long_text' })
    const long = '甲'.repeat(50)
    renderProviders(<GridCell value={long} field={field} rowId={1} />)
    expect(screen.getByText('甲'.repeat(40) + '…')).toBeInTheDocument()
  })

  it('text 默认按字符串展示', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    renderProviders(<GridCell value="张三" field={field} rowId={1} />)
    expect(screen.getByText('张三')).toBeInTheDocument()
  })
})

// ─────────────── 传统编辑：双击进入编辑态 ───────────────

describe('GridCell 传统编辑流', () => {
  it('双击 text 单元格进入编辑态，输入框同步原值', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={vi.fn()} />)

    fireEvent.doubleClick(screen.getByText('张三'))
    expect(screen.getByDisplayValue('张三')).toBeInTheDocument()
  })

  it('Enter 提交：onSave 收到字段名与草稿值，成功后退出编辑态', async () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onSave = vi.fn().mockResolvedValue(undefined)
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('张三'))
    const input = screen.getByDisplayValue('张三')
    fireEvent.change(input, { target: { value: '李四' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onSave).toHaveBeenCalledWith('姓名', '李四'))
    // 保存成功后退出编辑态（prop value 未变，展示回显原值）+ 成功提示
    await waitFor(() => expect(screen.queryByDisplayValue('李四')).not.toBeInTheDocument())
    expect(screen.getByText('已保存')).toBeInTheDocument()
  })

  it('Escape 取消：退出编辑态并回显原值，不调用 onSave', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onSave = vi.fn().mockResolvedValue(undefined)
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('张三'))
    fireEvent.keyDown(screen.getByDisplayValue('张三'), { key: 'Escape' })

    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('张三')).not.toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('保存失败：message.error 展示错误信息且停留在编辑态', async () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onSave = vi.fn().mockRejectedValue(new Error('网络异常'))
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('张三'))
    fireEvent.keyDown(screen.getByDisplayValue('张三'), { key: 'Enter' })

    expect(await screen.findByText('网络异常')).toBeInTheDocument()
    // 仍在编辑态
    expect(screen.getByDisplayValue('张三')).toBeInTheDocument()
  })

  it('只读字段（auto_id）双击不进入编辑态', () => {
    const field = makeField({ id: 1, name: '编号', field_type: 'auto_id' })
    renderProviders(<GridCell value="A-001" field={field} rowId={1} onSave={vi.fn()} />)

    fireEvent.doubleClick(screen.getByText('A-001'))
    expect(screen.queryByDisplayValue('A-001')).not.toBeInTheDocument()
    expect(screen.getByText('A-001')).toBeInTheDocument()
  })
})

// ─────────────── 受控编辑（行级编辑复用）───────────────

describe('GridCell 受控编辑', () => {
  it('editing=true 渲染编辑态，输入触发 onDraftChange', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onDraftChange = vi.fn()
    renderProviders(
      <GridCell value="hello" field={field} rowId={1} editing onDraftChange={onDraftChange} />,
    )

    const input = screen.getByDisplayValue('hello')
    fireEvent.change(input, { target: { value: 'world' } })
    expect(onDraftChange).toHaveBeenCalledWith('world')
  })

  it('Enter 触发 onDraftCommit（字段名 + finalize 后的值）', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onDraftCommit = vi.fn()
    renderProviders(
      <GridCell
        value="hello" field={field} rowId={1} editing
        onDraftChange={vi.fn()} onDraftCommit={onDraftCommit}
      />,
    )

    fireEvent.keyDown(screen.getByDisplayValue('hello'), { key: 'Enter' })
    // text 字段 finalize 原样透传
    expect(onDraftCommit).toHaveBeenCalledWith('姓名', 'hello')
  })

  it('Escape 触发 onDraftCancel', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onDraftCancel = vi.fn()
    renderProviders(
      <GridCell
        value="hello" field={field} rowId={1} editing
        onDraftChange={vi.fn()} onDraftCancel={onDraftCancel}
      />,
    )

    fireEvent.keyDown(screen.getByDisplayValue('hello'), { key: 'Escape' })
    expect(onDraftCancel).toHaveBeenCalledTimes(1)
  })

  it('number 字段受控提交时草稿串归一化为数字', () => {
    const field = makeField({ id: 1, name: '年龄', field_type: 'number' })
    const onDraftCommit = vi.fn()
    renderProviders(
      <GridCell
        value="42" field={field} rowId={1} editing
        onDraftChange={vi.fn()} onDraftCommit={onDraftCommit}
      />,
    )

    // number 字段渲染 InputNumber，其显示值为 42
    fireEvent.keyDown(screen.getByDisplayValue('42'), { key: 'Enter' })
    expect(onDraftCommit).toHaveBeenCalledWith('年龄', 42)
  })
})

// ─────────────── link 字段编辑（MSW 拉取目标表行）───────────────

describe('GridCell link 字段编辑', () => {
  it('受控编辑时经 MSW 拉取目标表行，下拉选项用主字段值而非纯 id', async () => {
    const field = makeField({
      id: 1, name: '关联', field_type: 'link',
      config: { target_table_id: 100, multiple: true },
    })
    renderProviders(
      <GridCell
        value={[{ id: 1, value: '张三' }]} field={field} rowId={9} wid={10} editing
      />,
    )

    // 预选值 id=1 → 目标行 label 为"张三"（主字段姓名的值），不再是 #1
    expect(await screen.findByText('张三')).toBeInTheDocument()

    // 打开下拉，第二个选项同样用主字段值"李四"
    fireEvent.mouseDown(document.querySelector('.ant-select-selector')!)
    expect(await screen.findByText('李四')).toBeInTheDocument()
  })
})
