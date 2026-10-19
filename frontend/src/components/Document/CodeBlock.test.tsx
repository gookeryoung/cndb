/** CodeBlock 单测 — 语言标签 / 高亮 token / 复制（含 http 兜底） / 空块 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import CodeBlock from './CodeBlock'

const writeText = vi.fn()

function setClipboard(value: Clipboard | undefined) {
  Object.defineProperty(navigator, 'clipboard', { value, configurable: true })
}

describe('CodeBlock', () => {
  beforeEach(() => {
    writeText.mockReset()
    writeText.mockResolvedValue(undefined)
    setClipboard({ writeText } as unknown as Clipboard)
  })

  it('展示语言标签、行数与高亮 token', () => {
    const { container } = render(<CodeBlock code={'const n = 42\n'} language="ts" />)
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
    expect(screen.getByText('1 行')).toBeInTheDocument()
    expect(container.querySelector('.cn-tok-keyword')?.textContent).toBe('const')
    expect(container.querySelector('.cn-tok-number')?.textContent).toBe('42')
    // 代码栏保留 language-* 类名，便于外部样式 / 测试定位
    expect(container.querySelector('code')).toHaveClass('language-ts')
    // 结尾换行被裁掉，不产生多余空行
    expect(container.querySelector('code')?.textContent).toBe('const n = 42')
  })

  it('未知语言只渲染纯文本与「代码」标签', () => {
    const { container } = render(<CodeBlock code={'a < b\n'} language="mystery" />)
    expect(screen.getByText('代码')).toBeInTheDocument()
    expect(container.querySelector('[class*="cn-tok-"]')).toBeNull()
    expect(container.querySelector('code')).toHaveTextContent('a < b')
  })

  it('点击复制写入剪贴板并提示已复制', async () => {
    render(<CodeBlock code={'print(1)\n'} language="py" />)
    fireEvent.click(screen.getByRole('button', { name: '复制代码' }))
    expect(await screen.findByText('已复制')).toBeInTheDocument()
    expect(writeText).toHaveBeenCalledWith('print(1)')
  })

  it('剪贴板不可用时退回 execCommand', async () => {
    setClipboard(undefined)
    const execCommand = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true })
    render(<CodeBlock code={'x = 1\n'} language="py" />)
    fireEvent.click(screen.getByRole('button', { name: '复制代码' }))
    expect(await screen.findByText('已复制')).toBeInTheDocument()
    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('写剪贴板被拒时同样走兜底；兜底失败则不改提示', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'))
    const execCommand = vi.fn().mockReturnValue(false)
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true })
    render(<CodeBlock code={'y = 2\n'} language="py" />)
    fireEvent.click(screen.getByRole('button', { name: '复制代码' }))
    await waitFor(() => expect(execCommand).toHaveBeenCalledWith('copy'))
    expect(screen.getByText('复制')).toBeInTheDocument()
  })

  it('空代码块显示「空」且不报错', () => {
    render(<CodeBlock code={''} language="js" />)
    expect(screen.getByText('空')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制代码' })).toBeInTheDocument()
  })
})
