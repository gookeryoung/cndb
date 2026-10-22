/** AiResultDrawer 单测 —— loading / error / 原文对照 / 应用回调 / 结构化分区（ADR 0020 P1） */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import AiResultDrawer from './AiResultDrawer'

function renderDrawer(over: Partial<Parameters<typeof AiResultDrawer>[0]> = {}) {
  const props: Parameters<typeof AiResultDrawer>[0] = {
    open: true,
    title: 'AI 润色',
    onClose: () => {},
    ...over,
  }
  return render(<AiResultDrawer {...props} />)
}

describe('AiResultDrawer', () => {
  it('loading：展示骨架屏，应用 / 重新生成均禁用', () => {
    const onApply = vi.fn()
    const onRegenerate = vi.fn()
    renderDrawer({ loading: true, originalText: '原文', resultText: '', onApply, onRegenerate })

    expect(screen.getByTestId('ai-result-drawer')).toBeInTheDocument()
    expect(screen.getByTestId('ai-result-loading')).toBeInTheDocument()
    expect(screen.getByTestId('ai-result-apply')).toBeDisabled()
    expect(screen.getByTestId('ai-result-regenerate')).toBeDisabled()
    expect(screen.queryByTestId('ai-result-compare')).toBeNull()

    fireEvent.click(screen.getByTestId('ai-result-apply'))
    expect(onApply).not.toHaveBeenCalled()
  })

  it('error：展示后端文案，应用禁用但允许重新生成', () => {
    const onApply = vi.fn()
    const onRegenerate = vi.fn()
    renderDrawer({ error: '选区超长（最多 4000 字）', onApply, onRegenerate })

    expect(screen.getByTestId('ai-result-error')).toHaveTextContent('选区超长（最多 4000 字）')
    expect(screen.getByTestId('ai-result-apply')).toBeDisabled()
    expect(screen.getByTestId('ai-result-regenerate')).toBeEnabled()

    fireEvent.click(screen.getByTestId('ai-result-regenerate'))
    expect(onRegenerate).toHaveBeenCalledTimes(1)
  })

  it('成功：原文 / AI 结果左右对照，应用与取消触发回调', () => {
    const onApply = vi.fn()
    const onClose = vi.fn()
    renderDrawer({
      originalText: '该方案需要对现有流程进行重新梳理。',
      resultText: '该方案需重新梳理现有流程。',
      onApply,
      onClose,
    })

    expect(screen.getByTestId('ai-result-original')).toHaveTextContent('该方案需要对现有流程进行重新梳理。')
    expect(screen.getByTestId('ai-result-text')).toHaveTextContent('该方案需重新梳理现有流程。')

    fireEvent.click(screen.getByTestId('ai-result-apply'))
    expect(onApply).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByTestId('ai-result-cancel'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('结构化分区：摘要文字 + 可多选标签 chips', () => {
    const onSelect = vi.fn()
    renderDrawer({
      sections: [
        { key: 'summary', title: '摘要', text: '本文给出流程优化的三步方案。', testId: 'ai-summary' },
        {
          key: 'tags',
          title: '建议标签',
          items: ['流程优化', '审批效率'],
          selectable: true,
          selected: [],
          onSelect,
          testId: 'ai-suggest-tags',
        },
      ],
    })

    expect(screen.getByTestId('ai-summary')).toHaveTextContent('本文给出流程优化的三步方案。')
    expect(screen.getByTestId('ai-suggest-tags-chips-item-流程优化')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('ai-suggest-tags-chips-item-流程优化'))
    expect(onSelect).toHaveBeenCalledWith(['流程优化'])
  })

  it('不定式（摘要）不渲染原文对照，也不渲染应用按钮', () => {
    renderDrawer({ sections: [{ key: 'summary', title: '摘要', text: '短文摘要' }] })

    expect(screen.queryByTestId('ai-result-compare')).toBeNull()
    expect(screen.queryByTestId('ai-result-apply')).toBeNull()
    expect(screen.getByTestId('ai-result-cancel')).toBeInTheDocument()
  })
})
