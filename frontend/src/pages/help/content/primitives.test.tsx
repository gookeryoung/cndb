/** 帮助正文原语 · 示例代码块 — 标题 / 复制 / http 兜底 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CodeBlock } from './primitives'

const writeText = vi.fn()

function setClipboard(value: Clipboard | undefined) {
    Object.defineProperty(navigator, 'clipboard', { value, configurable: true })
}

describe('help CodeBlock', () => {
    beforeEach(() => {
        writeText.mockReset()
        writeText.mockResolvedValue(undefined)
        setClipboard({ writeText } as unknown as Clipboard)
    })

    it('渲染标题、代码与复制按钮', () => {
        render(<CodeBlock title="最小设计" code={'box(w = 60)\n'} />)
        expect(screen.getByText('最小设计')).toBeInTheDocument()
        expect(screen.getByText('box(w = 60)')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: '复制示例代码' })).toBeInTheDocument()
    })

    it('点击复制写入剪贴板（裁掉结尾换行）并提示已复制', async () => {
        render(<CodeBlock title="参数化" code={'param width = 80\n'} />)
        fireEvent.click(screen.getByRole('button', { name: '复制示例代码' }))
        expect(await screen.findByText('已复制')).toBeInTheDocument()
        expect(writeText).toHaveBeenCalledWith('param width = 80')
    })

    it('剪贴板被拒时退回 execCommand；兜底失败则不改提示', async () => {
        writeText.mockRejectedValueOnce(new Error('denied'))
        const execCommand = vi.fn().mockReturnValue(false)
        Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true })
        render(<CodeBlock code={'y = 2\n'} />)
        fireEvent.click(screen.getByRole('button', { name: '复制示例代码' }))
        await waitFor(() => expect(execCommand).toHaveBeenCalledWith('copy'))
        expect(screen.getByText('复制')).toBeInTheDocument()
    })
})
