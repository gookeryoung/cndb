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
import { http, HttpResponse } from 'msw'
import dayjs from 'dayjs'
import GridCell from './GridCell'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import { resetFileObjectUrls } from '@/hooks/useFileObjectUrl'

/** 派发一次 paste 事件（jsdom 的 ClipboardEvent 只读，手工挂 clipboardData 替身） */
function firePasteEvent(file: File | null, text = '') {
  const items = file ? [{ kind: 'file', type: file.type, getAsFile: () => file }] : []
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', {
    value: {
      items,
      files: file ? [file] : [],
      types: file ? ['Files'] : ['text/plain'],
      getData: () => text,
    },
  })
  fireEvent(document.body, event)
}

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
    renderProviders(<GridCell value="a@example.com" field={field} rowId={1} />)
    expect(screen.getByText('a@example.com')).toHaveAttribute('href', 'mailto:a@example.com')
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

  it('image JSON 字符串渲染为缩略图（经鉴权 blob 拉取，非直连 URL）', async () => {
    resetFileObjectUrls()
    const field = makeField({ id: 1, name: '照片', field_type: 'image' })
    const requested: string[] = []
    server.use(
      http.get('/api/v1/workspaces/:wid/files/:fileKey', ({ params }) => {
        requested.push(String(params.fileKey))
        return new HttpResponse(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { 'Content-Type': 'image/png' },
        })
      }),
    )
    const value = JSON.stringify([
      { file_key: 'abc123.png', filename: 'image1.png', mime_type: 'image/png' },
      { file_key: 'def456.png', filename: 'image2.png', mime_type: 'image/png' },
    ])
    renderProviders(<GridCell value={value} field={field} rowId={1} wid={10} />)
    // 附件端点经 axios 取 blob（带 Authorization 头），不是 <img> 直连
    await waitFor(() => expect(requested).toEqual(expect.arrayContaining(['abc123.png', 'def456.png'])))
    const srcs = screen.getAllByRole('img').map(el => el.getAttribute('src') ?? '')
    // antd Image 可能额外渲染预览副本；断言至少 2 个缩略图指向 blob URL
    expect(srcs.filter(s => s.startsWith('blob:')).length).toBeGreaterThanOrEqual(2)
  })

  it('image 已解析数组同样渲染缩略图；空值渲染占位符 —', async () => {
    const field = makeField({ id: 1, name: '照片', field_type: 'image' })
    const { rerender } = renderProviders(
      <GridCell value={[{ file_key: 'k.png', filename: 'a.png', mime_type: 'image/png' }]} field={field} rowId={1} wid={3} />,
    )
    const imgs = await screen.findAllByRole('img')
    expect(imgs.some(el => el.getAttribute('src')?.startsWith('blob:'))).toBe(true)

    rerender(<GridCell value={null} field={field} rowId={1} wid={3} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    rerender(<GridCell value="[]" field={field} rowId={1} wid={3} />)
    expect(screen.getByText('—')).toBeInTheDocument()
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

  it('双击可编辑单元格阻断冒泡，行级 onDoubleClick（Drawer）不触发', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onRowDoubleClick = vi.fn()
    renderProviders(
      <div onDoubleClick={onRowDoubleClick}>
        <GridCell value="张三" field={field} rowId={1} onSave={vi.fn()} />
      </div>,
    )

    fireEvent.doubleClick(screen.getByText('张三'))
    // 单元格进入编辑态
    expect(screen.getByDisplayValue('张三')).toBeInTheDocument()
    // 行级处理器未触发（Drawer 不弹出）
    expect(onRowDoubleClick).not.toHaveBeenCalled()
  })

  it('无保存回调（只读）时双击冒泡到行级，仍可打开行详情 Drawer', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onRowDoubleClick = vi.fn()
    renderProviders(
      <div onDoubleClick={onRowDoubleClick}>
        <GridCell value="张三" field={field} rowId={1} />
      </div>,
    )

    fireEvent.doubleClick(screen.getByText('张三'))
    expect(onRowDoubleClick).toHaveBeenCalledTimes(1)
    expect(screen.queryByDisplayValue('张三')).not.toBeInTheDocument()
  })

  it('编辑态中再双击控件阻断冒泡，Drawer 不弹出', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    const onRowDoubleClick = vi.fn()
    renderProviders(
      <div onDoubleClick={onRowDoubleClick}>
        <GridCell value="张三" field={field} rowId={1} onSave={vi.fn()} />
      </div>,
    )

    fireEvent.doubleClick(screen.getByText('张三'))
    fireEvent.doubleClick(screen.getByDisplayValue('张三'))
    expect(onRowDoubleClick).not.toHaveBeenCalled()
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
    // message 经 AntApp portal 异步挂载，必须用自带重试的 findBy，同步 getBy 会与 portal 渲染竞态
    expect(await screen.findByText('已保存')).toBeInTheDocument()
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

  it('只读字段（lookup 无物理列）双击不进入编辑态', () => {
    const field = makeField({ id: 1, name: '引用', field_type: 'lookup' })
    renderProviders(<GridCell value="A-001" field={field} rowId={1} onSave={vi.fn()} />)

    fireEvent.doubleClick(screen.getByText('A-001'))
    expect(screen.queryByDisplayValue('A-001')).not.toBeInTheDocument()
    expect(screen.getByText('A-001')).toBeInTheDocument()
  })

  // ─────────────── 编辑中锁定（locked）───────────────

  it('locked 行展示原值且双击不进入编辑态', () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={vi.fn()} locked />)

    expect(screen.getByTestId('cell-locked')).toBeInTheDocument()
    fireEvent.doubleClick(screen.getByText('张三'))
    expect(screen.queryByDisplayValue('张三')).not.toBeInTheDocument()
  })

  it('保存响应为修改申请载荷（202）时提示「已提交修改申请」', async () => {
    const field = makeField({ id: 1, name: '姓名', field_type: 'text' })
    // 查看者/关闭直编：onSave 返回 ChangeRequestBatchResponse 形状（含 change_request 字段）
    const onSave = vi.fn().mockResolvedValue({
      change_request: { id: 7, workspace_id: 10, table_id: 20, op: 'update', row_id: 1, status: 'open', changes: {} },
    })
    renderProviders(<GridCell value="张三" field={field} rowId={1} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('张三'))
    fireEvent.keyDown(screen.getByDisplayValue('张三'), { key: 'Enter' })

    expect(await screen.findByText('已提交修改申请，处理后生效')).toBeInTheDocument()
    expect(screen.queryByText('已保存')).not.toBeInTheDocument()
  })

  // ─────────────── 图片字段：双击以浮层打开 ───────────────

  it('图片字段双击打开浮层编辑器，上传后点「完成」保存草稿值', async () => {
    resetFileObjectUrls()
    const field = makeField({ id: 2, name: '照片', field_type: 'image' })
    const onSave = vi.fn().mockResolvedValue({})
    renderProviders(<GridCell value={null} field={field} rowId={1} wid={5} tableId={3} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('—'))
    expect(await screen.findByTestId('image-cell-popover')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('image-field-input'), {
      target: { files: [new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' })] },
    })
    // 等上传完成（预览图出现）后再提交，避免保存空草稿
    await waitFor(() => expect(document.querySelector('.ant-image-img')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /完\s*成/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('照片', [
      expect.objectContaining({ file_key: 'mock-upload.png' }),
    ]))
  })

  it('图片字段浮层取消关闭，不触发保存', async () => {
    resetFileObjectUrls()
    const field = makeField({ id: 2, name: '照片', field_type: 'image' })
    const onSave = vi.fn()
    renderProviders(<GridCell value={null} field={field} rowId={1} onSave={onSave} />)

    fireEvent.doubleClick(screen.getByText('—'))
    expect(await screen.findByTestId('image-cell-popover')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
    await waitFor(() => expect(screen.queryByTestId('image-cell-popover')).not.toBeInTheDocument())
    expect(onSave).not.toHaveBeenCalled()
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

  it('image 字段编辑态渲染图片上传区，空值草稿归一为空数组', () => {
    const field = makeField({ id: 1, name: '照片', field_type: 'image' })
    const onDraftChange = vi.fn()
    renderProviders(
      <GridCell
        value={null} field={field} rowId={1} wid={5} editing
        onDraftChange={onDraftChange} onDraftCommit={vi.fn()}
      />,
    )

    // 选文件走显式按钮（点击字段不再弹文件框），并保留粘贴入口
    expect(screen.getByTestId('image-field-pick')).toBeInTheDocument()
    expect(screen.getByText(/或拖拽到此/)).toBeInTheDocument()
    expect(screen.getByText(/Ctrl\+V 粘贴/)).toBeInTheDocument()
    // 上传 accept 默认仅收图片
    expect(screen.getByTestId('image-field-input')).toHaveAttribute('accept', 'image/*')
  })

  it('image 字段编辑态粘贴剪贴板图片：上传并追加到草稿', async () => {
    resetFileObjectUrls()
    const field = makeField({ id: 1, name: '照片', field_type: 'image' })
    const onDraftChange = vi.fn()
    renderProviders(
      <GridCell
        value={null} field={field} rowId={1} wid={5} editing
        onDraftChange={onDraftChange} onDraftCommit={vi.fn()}
      />,
    )

    const file = new File([new Uint8Array([1, 2, 3])], 'screenshot.png', { type: 'image/png' })
    firePasteEvent(file)

    // MSW 默认上传响应 mock-upload.png → 追加进草稿
    await waitFor(() => expect(onDraftChange).toHaveBeenCalledWith([
      expect.objectContaining({ file_key: 'mock-upload.png', mime_type: 'image/png' }),
    ]))
  })

  it('image 字段编辑态粘贴带文字的剪贴板：不劫持文本粘贴', async () => {
    const field = makeField({ id: 1, name: '照片', field_type: 'image' })
    const onDraftChange = vi.fn()
    renderProviders(
      <GridCell
        value={null} field={field} rowId={1} wid={5} editing
        onDraftChange={onDraftChange} onDraftCommit={vi.fn()}
      />,
    )

    const file = new File([new Uint8Array([1, 2, 3])], 'screenshot.png', { type: 'image/png' })
    firePasteEvent(file, '单元格文字')

    // 给异步上传留出时间窗，确认没有被触发
    await new Promise(r => setTimeout(r, 50))
    expect(onDraftChange).not.toHaveBeenCalled()
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
