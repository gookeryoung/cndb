/** OutlineList 引线树折叠行为单测. */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { OutlineItem } from '@/components/Document/outline'
import OutlineList from './OutlineList'

function item(level: number, text: string, index: number): OutlineItem {
  return { level, text, anchor: `doc-h-${text}`, line: index }
}

const outline: OutlineItem[] = [
  item(1, '第一章', 0),
  item(2, '第一节', 1),
  item(3, '小节', 2),
  item(2, '第二节', 3),
  item(1, '第二章', 4),
  item(2, '尾声', 5),
]

describe('OutlineList', () => {
  it('默认全展开渲染全部标题', () => {
    render(<OutlineList outline={outline} onAnchorClick={vi.fn()} />)
    for (const text of ['第一章', '第一节', '小节', '第二节', '第二章']) {
      expect(screen.getByText(text)).toBeInTheDocument()
    }
  })

  it('有子级标题显示折叠按钮，叶子标题无按钮', () => {
    render(<OutlineList outline={outline} onAnchorClick={vi.fn()} />)
    for (const i of [0, 1, 4]) {
      expect(screen.getByTestId(`doc-outline-toggle-${i}`)).toBeInTheDocument()
    }
    for (const i of [2, 3]) {
      expect(screen.queryByTestId(`doc-outline-toggle-${i}`)).not.toBeInTheDocument()
    }
    // 默认展开态箭头朝下（旋转 90°）
    expect(screen.getByTestId('doc-outline-toggle-0').className).toContain(
      'cn-outline-caret-expanded',
    )
  })

  it('点击按钮折叠子级，再点展开；正文点击不受影响', () => {
    const onAnchorClick = vi.fn()
    render(<OutlineList outline={outline} onAnchorClick={onAnchorClick} />)

    fireEvent.click(screen.getByTestId('doc-outline-toggle-0'))
    expect(screen.queryByText('第一节')).not.toBeInTheDocument()
    expect(screen.queryByText('小节')).not.toBeInTheDocument()
    expect(screen.queryByText('第二节')).not.toBeInTheDocument()
    expect(screen.getByText('第二章')).toBeInTheDocument()
    // 折叠后箭头朝右（无旋转）
    expect(screen.getByTestId('doc-outline-toggle-0').className).not.toContain(
      'cn-outline-caret-expanded',
    )

    fireEvent.click(screen.getByTestId('doc-outline-toggle-0'))
    expect(screen.getByText('第一节')).toBeInTheDocument()
    expect(screen.getByText('第二节')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('doc-outline-toggle-1'))
    expect(screen.queryByText('小节')).not.toBeInTheDocument()
    expect(screen.getByText('第二节')).toBeInTheDocument()

    fireEvent.click(screen.getByText('第一节'))
    expect(onAnchorClick).toHaveBeenCalledWith('doc-h-第一节')
  })

  it('折叠第二章不影响第一章分支', () => {
    render(<OutlineList outline={outline} onAnchorClick={vi.fn()} />)
    fireEvent.click(screen.getByTestId('doc-outline-toggle-4'))
    expect(screen.getByText('第一章')).toBeInTheDocument()
    expect(screen.getByText('第一节')).toBeInTheDocument()
    expect(screen.queryByText('尾声')).not.toBeInTheDocument()
  })

  it('空大纲显示占位文案', () => {
    render(<OutlineList outline={[]} onAnchorClick={vi.fn()} />)
    expect(screen.getByText(/暂无标题/)).toBeInTheDocument()
  })
})
