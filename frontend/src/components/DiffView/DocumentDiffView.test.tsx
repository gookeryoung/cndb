/** DocumentDiffView 组件测试：统计条 / 统一与并排模式切换 / 行内高亮 / 空态. */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'
import DocumentDiffView from './DocumentDiffView'

const DIFF = [
  '--- base',
  '+++ head',
  '@@ -1,4 +1,4 @@',
  ' # 标题',
  '-分级：A',
  '+分级：B',
  ' 备注：老客户',
  '',
].join('\n')

describe('DocumentDiffView', () => {
  it('默认统一视图：渲染双端行号、增删统计与行内高亮', () => {
    const { container } = renderProviders(<DocumentDiffView diff={DIFF} baseLabel="v3" headLabel="v4" />)

    expect(screen.getByTestId('document-diff')).toBeInTheDocument()
    expect(screen.getByTestId('diff-unified')).toBeInTheDocument()
    expect(screen.getByText('v3')).toBeInTheDocument()
    expect(screen.getByText('v4')).toBeInTheDocument()
    expect(screen.getByText('+1 新增')).toBeInTheDocument()
    expect(screen.getByText('−1 删除')).toBeInTheDocument()

    // 上下文与增删行都在
    expect(screen.getByText('# 标题')).toBeInTheDocument()
    expect(screen.getByText('备注：老客户')).toBeInTheDocument()

    // 行内高亮只标出变化的字元（A / B），未变化的「分级：」保持普通文本
    const marks = container.querySelectorAll('.cn-diff-inline')
    expect(Array.from(marks).map((m) => m.textContent)).toEqual(['A', 'B'])
  })

  it('可切换到并排视图，左右分栏各带行号', () => {
    const { container } = renderProviders(<DocumentDiffView diff={DIFF} />)

    fireEvent.click(screen.getByText('并排'))

    expect(screen.getByTestId('diff-split')).toBeInTheDocument()
    expect(screen.queryByTestId('diff-unified')).toBeNull()

    const cells = container.querySelectorAll('.cn-diff-row .cn-diff-cell')
    expect(cells.length).toBeGreaterThanOrEqual(2)
    expect(container.querySelector('.cn-diff-cell--del')).not.toBeNull()
    expect(container.querySelector('.cn-diff-cell--add')).not.toBeNull()
  })

  it('无差异时展示空态而不是空表格', () => {
    renderProviders(<DocumentDiffView diff="" baseLabel="v1" headLabel="v2" />)

    expect(screen.getByText('两个版本内容一致，无差异')).toBeInTheDocument()
    expect(screen.queryByTestId('diff-unified')).toBeNull()
  })

  it('区间头与文件头单独成行展示（不带行号槽）', () => {
    renderProviders(<DocumentDiffView diff={DIFF} />)

    const hunkLine = screen.getByText('@@ -1,4 +1,4 @@').closest('.cn-diff-line') as HTMLElement
    expect(hunkLine).not.toBeNull()
    expect(hunkLine.querySelectorAll('.cn-diff-no')).toHaveLength(0)

    const metaLine = screen.getByText('--- base').closest('.cn-diff-line') as HTMLElement
    expect(metaLine.querySelectorAll('.cn-diff-no')).toHaveLength(0)
  })
})
