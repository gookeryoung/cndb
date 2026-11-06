/** DslEditor 自动完成挂载测试（需求卡 0110 C5）：只读 viewer 不挂补全扩展. */

import { describe, expect, it } from 'vitest'
import { act, render, waitFor } from '@testing-library/react'
import { EditorView } from '@codemirror/view'
import { completionStatus, startCompletion } from '@codemirror/autocomplete'
import DslEditor from './DslEditor'

function mount(readOnly: boolean) {
  const { container } = render(
    <DslEditor value="bo" onChange={() => {}} diagnostics={[]} readOnly={readOnly} />,
  )
  const view = EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)
  if (!view) throw new Error('编辑器视图未挂载')
  return view
}

describe('DslEditor 补全扩展', () => {
  it('可编辑态 Ctrl+Space 唤起补全', async () => {
    const view = mount(false)
    act(() => { startCompletion(view) })
    await waitFor(() => expect(completionStatus(view.state)).not.toBeNull())
  })

  it('只读 viewer 不挂补全扩展', async () => {
    const view = mount(true)
    act(() => { startCompletion(view) })
    expect(completionStatus(view.state)).toBeNull()
  })
})
