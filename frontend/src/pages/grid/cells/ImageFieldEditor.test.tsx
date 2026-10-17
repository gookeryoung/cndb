/**
 * ImageFieldEditor 交互测试 —— 点击只聚焦不弹文件框、选文件走显式按钮、粘贴直接上传.
 *
 * 背景：字段整块区域曾是「点击即上传」的拖拽区，点一下为了聚焦粘贴就会弹出
 * 系统文件选择框，必须先取消才能 Ctrl+V；这里锁定修复后的交互口径。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { ImageFieldEditor } from './ImageFieldEditor'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { makeField } from '@/test/fixtures'
import { resetFileObjectUrls } from '@/hooks/useFileObjectUrl'
import { http, HttpResponse } from 'msw'

const IMAGE_FIELD = makeField({ id: 2, name: '照片', field_type: 'image' })

/** 派发一次 paste 事件（jsdom 的 ClipboardEvent 只读，手工挂 clipboardData 替身） */
function firePasteEvent(file: File, text = '') {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', {
    value: {
      items: [{ kind: 'file', type: file.type, getAsFile: () => file }],
      files: [file],
      types: ['Files'],
      getData: () => text,
    },
  })
  fireEvent(document.body, event)
}

function renderEditor(overrides: Partial<ComponentProps<typeof ImageFieldEditor>> = {}) {
  return renderProviders(
    <ImageFieldEditor
      wid={5}
      field={IMAGE_FIELD}
      value={null}
      onChange={vi.fn()}
      {...overrides}
    />,
  )
}

describe('ImageFieldEditor 上传入口', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('点击拖拽上传区只聚焦粘贴区，不打开系统文件选择框', () => {
    const inputClickSpy = vi.spyOn(HTMLInputElement.prototype, 'click')
    renderEditor()

    // 点的是真正会触发「点击上传」的区域（Dragger 内部文案），不是外层容器
    fireEvent.click(screen.getByText(/或拖拽到此/))

    // 不弹文件选择框，且字段已获得焦点（可直接 Ctrl+V）
    expect(inputClickSpy).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(screen.getByTestId('image-field'))
  })

  it('点击「选择图片」按钮才触发文件选择框', () => {
    const inputClickSpy = vi.spyOn(HTMLInputElement.prototype, 'click')
    renderEditor()

    fireEvent.click(screen.getByTestId('image-field-pick'))
    expect(inputClickSpy).toHaveBeenCalledTimes(1)
  })

  it('字段配置透传：multiple=false / allowed_mime_types 约束选择入口', () => {
    const field = makeField({
      id: 3,
      name: '证件照',
      field_type: 'image',
      config: { multiple: false, allowed_mime_types: ['image/png', 'image/jpeg'] },
    })
    renderEditor({ field })

    const input = screen.getByTestId('image-field-input') as HTMLInputElement
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg')
    expect(input).not.toHaveAttribute('multiple')
  })

  it('点选文件后上传并写回字段值', async () => {
    const onChange = vi.fn()
    renderEditor({ onChange })

    const input = screen.getByTestId('image-field-input') as HTMLInputElement
    fireEvent.change(input, {
      target: { files: [new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' })] },
    })

    // MSW 默认上传响应 mock-upload.png
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ file_key: 'mock-upload.png', mime_type: 'image/png' }),
    ]))
  })

  it('点击字段聚焦后可直接粘贴截图（无需先取消文件框）', async () => {
    const onChange = vi.fn()
    renderEditor({ onChange })

    fireEvent.click(screen.getByText(/或拖拽到此/))
    expect(document.activeElement).toBe(screen.getByTestId('image-field'))
    firePasteEvent(new File([new Uint8Array([1, 2, 3])], 'screenshot.png', { type: 'image/png' }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ file_key: 'mock-upload.png' }),
    ]))
  })

  it('同屏多个图片字段：粘贴只进最近点击聚焦的那个', async () => {
    const first = vi.fn()
    const second = vi.fn()
    renderProviders(
      <>
        <ImageFieldEditor wid={5} field={IMAGE_FIELD} value={null} onChange={first} />
        <ImageFieldEditor wid={5} field={IMAGE_FIELD} value={null} onChange={second} />
      </>,
    )

    // 两个字段都在场时不会兜底派发，只有被点击聚焦的那个接收粘贴
    fireEvent.click(screen.getAllByText(/或拖拽到此/)[1])
    firePasteEvent(new File([new Uint8Array([1])], 'shot.png', { type: 'image/png' }))

    await waitFor(() => expect(second).toHaveBeenCalledTimes(1))
    expect(first).not.toHaveBeenCalled()
  })

  it('非图片文件被拒绝：不上传并提示格式不支持', async () => {
    const uploadSpy = vi.fn(() => HttpResponse.json({ file_key: 'x.txt' }, { status: 201 }))
    server.use(http.post('/api/v1/workspaces/:wid/files', uploadSpy))
    const onChange = vi.fn()
    renderEditor({ onChange })

    const input = screen.getByTestId('image-field-input') as HTMLInputElement
    fireEvent.change(input, {
      target: { files: [new File(['hello'], 'a.txt', { type: 'text/plain' })] },
    })

    expect(await screen.findByText(/格式不支持/)).toBeInTheDocument()
    expect(uploadSpy).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('只读态：无图显示占位「—」，有图仍展示缩略图但无删除入口', async () => {
    resetFileObjectUrls()
    const { rerender } = renderEditor({ disabled: true, value: [] })
    expect(screen.getByText('—')).toBeInTheDocument()

    rerender(
      <ImageFieldEditor
        wid={5}
        disabled
        field={IMAGE_FIELD}
        value={[{ file_key: 'k.png', filename: 'a.png', mime_type: 'image/png' }]}
        onChange={vi.fn()}
      />,
    )
    // 缩略图经鉴权 blob 拉取（MSW 默认返回 1x1 PNG）
    await waitFor(() => expect(document.querySelector('.ant-image-img')).toBeInTheDocument())
    expect(screen.queryByText('—')).not.toBeInTheDocument()
    expect(screen.queryByTestId('image-field-pick')).not.toBeInTheDocument()
  })

  it('只读态不渲染上传入口，也不接收粘贴', async () => {
    const uploadSpy = vi.fn(() => HttpResponse.json({ file_key: 'x.png' }, { status: 201 }))
    server.use(http.post('/api/v1/workspaces/:wid/files', uploadSpy))
    const onChange = vi.fn()
    renderEditor({ disabled: true, onChange })

    expect(screen.queryByTestId('image-field-pick')).not.toBeInTheDocument()
    expect(screen.queryByTestId('image-field-input')).not.toBeInTheDocument()
    expect(screen.queryByText(/Ctrl\+V 粘贴/)).not.toBeInTheDocument()

    firePasteEvent(new File([new Uint8Array([1])], 'screenshot.png', { type: 'image/png' }))
    await new Promise(r => setTimeout(r, 50))
    expect(uploadSpy).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('超过字段 max_size_mb 的图片在上传前被拒绝', async () => {
    const uploadSpy = vi.fn(() => HttpResponse.json({ file_key: 'x.png' }, { status: 201 }))
    server.use(http.post('/api/v1/workspaces/:wid/files', uploadSpy))
    const onChange = vi.fn()
    const field = makeField({
      id: 6,
      name: '照片',
      field_type: 'image',
      config: { max_size_mb: 1 },
    })
    renderEditor({ field, onChange })

    const big = new File([new Uint8Array(2 * 1024 * 1024)], 'big.png', { type: 'image/png' })
    fireEvent.change(screen.getByTestId('image-field-input'), { target: { files: [big] } })

    expect(await screen.findByText(/超过单张 1MB 限制/)).toBeInTheDocument()
    expect(uploadSpy).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('单图字段选择新图是替换而非追加（旧图不进入字段值）', async () => {
    const onChange = vi.fn()
    const field = makeField({
      id: 7,
      name: '证件照',
      field_type: 'image',
      config: { multiple: false },
    })
    renderEditor({
      field,
      value: [{ file_key: 'old.png', filename: 'old.png', mime_type: 'image/png' }],
      onChange,
    })

    // 已有图时按钮变为「替换」
    expect(screen.getByTestId('image-field-pick')).toHaveAttribute('title', '替换图片')

    fireEvent.change(screen.getByTestId('image-field-input'), {
      target: { files: [new File([new Uint8Array([1, 2, 3])], 'new.png', { type: 'image/png' })] },
    })

    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ file_key: 'mock-upload.png' }),
    ]))
    const lastValue = onChange.mock.calls.at(-1)?.[0] as unknown[]
    expect(lastValue).toHaveLength(1)
  })

  it('上传失败的瓦片支持原地重试，成功后写回字段值', async () => {
    let attempt = 0
    server.use(http.post('/api/v1/workspaces/:wid/files', () => {
      attempt += 1
      if (attempt === 1) return HttpResponse.json({ detail: '上传失败' }, { status: 500 })
      return HttpResponse.json(
        { file_key: 'retry-ok.png', filename: 'a.png', size: 3, mime_type: 'image/png' },
        { status: 201 },
      )
    }))
    const onChange = vi.fn()
    renderEditor({ onChange })

    fireEvent.change(screen.getByTestId('image-field-input'), {
      target: { files: [new File([new Uint8Array([1])], 'a.png', { type: 'image/png' })] },
    })

    expect(await screen.findByText('上传失败')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ file_key: 'retry-ok.png' }),
    ]))
    expect(attempt).toBe(2)
  })

  it('行详情大图模式支持逐图替换：新图占据原位置，其余顺序不变', async () => {
    resetFileObjectUrls()
    const onChange = vi.fn()
    const field = makeField({ id: 8, name: '照片', field_type: 'image' })
    renderEditor({
      field,
      thumbSize: 56,
      value: [
        { file_key: 'a.png', filename: 'a.png', mime_type: 'image/png' },
        { file_key: 'b.png', filename: 'b.png', mime_type: 'image/png' },
      ],
      onChange,
    })

    fireEvent.click(screen.getByRole('button', { name: '替换 a.png' }))
    fireEvent.change(screen.getByTestId('image-field-input'), {
      target: { files: [new File([new Uint8Array([1])], 'new.png', { type: 'image/png' })] },
    })

    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ file_key: 'mock-upload.png' }),
      expect.objectContaining({ file_key: 'b.png' }),
    ]))
  })
})
