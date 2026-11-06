/** PipelineDslEditor 组件测试（需求卡 0111 C1 / C7）.
 *
 * jsdom 下挂真实 CodeMirror 视图：行号槽位、受控内容与「插入到光标处」。
 */

import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { act, render } from '@testing-library/react'
import { EditorView } from '@codemirror/view'
import PipelineDslEditor, { type PipelineDslEditorHandle } from './PipelineDslEditor'

function mount(value: string) {
  const ref = createRef<PipelineDslEditorHandle>()
  const changes: string[] = []
  const { container } = render(
    <PipelineDslEditor
      ref={ref}
      value={value}
      onChange={(next) => changes.push(next)}
    />,
  )
  const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)
  if (!view) throw new Error('编辑器视图未挂载')
  return { container, view, ref, changes }
}

describe('PipelineDslEditor', () => {
  it('挂行号槽位并渲染受控内容', () => {
    const { container, view } = mount('name: 巡检\njobs:')
    expect(container.querySelector('.cm-lineNumbers')).not.toBeNull()
    expect(view.state.doc.toString()).toBe('name: 巡检\njobs:')
  })

  it('外部 value 变化同步进编辑器', () => {
    const { container, rerender } = render(
      <PipelineDslEditor value="name: a" onChange={() => {}} />,
    )
    const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)!
    rerender(<PipelineDslEditor value="name: b" onChange={() => {}} />)
    expect(view.state.doc.toString()).toBe('name: b')
  })

  it('insertSnippet 在光标处插入，光标行有内容时先换行', () => {
    const { view, ref } = mount('jobs:\n  体检:\n    steps:')
    act(() => {
      view.dispatch({ selection: { anchor: view.state.doc.length } })
      ref.current!.insertSnippet('      - uses: table/null-rate')
    })
    expect(view.state.doc.toString()).toBe('jobs:\n  体检:\n    steps:\n      - uses: table/null-rate')
  })

  it('insertSnippet 在空行处直接插入，不重复换行', () => {
    const { view, ref } = mount('jobs:\n')
    act(() => {
      view.dispatch({ selection: { anchor: view.state.doc.length } })
      ref.current!.insertSnippet('  体检:')
    })
    expect(view.state.doc.toString()).toBe('jobs:\n  体检:')
  })
})
