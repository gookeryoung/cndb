/** DslEditor 自动完成挂载测试（需求卡 0110 C5）：只读 viewer 不挂补全扩展. */

import { describe, expect, it } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { getIndentUnit } from '@codemirror/language'
import { completionStatus, startCompletion } from '@codemirror/autocomplete'
import { ThemeProvider, useTheme } from '@/theme/ThemeProvider'
import DslEditor from './DslEditor'

function mount(readOnly: boolean, value = 'bo') {
  const { container } = render(
    <DslEditor value={value} onChange={() => {}} diagnostics={[]} readOnly={readOnly} />,
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

describe('DslEditor 编辑体验（0127）', () => {
  it('编辑态显示空白标记，只读态不显示', () => {
    const editable = mount(false, 'param w = 1')
    expect(editable.contentDOM.querySelector('.cm-highlightSpace')).not.toBeNull()
    const readonly = mount(true, 'param w = 1')
    expect(readonly.contentDOM.querySelector('.cm-highlightSpace')).toBeNull()
  })

  it('固定 2 空格缩进单位与 tabSize', () => {
    const view = mount(false)
    expect(getIndentUnit(view.state)).toBe(2)
    expect(view.state.facet(EditorState.tabSize)).toBe(2)
  })
})

/** 设置探针：提供切换编辑器配色按钮 */
function ThemeSwitchHarness() {
  const { updateEditorSettings } = useTheme()
  return (
    <>
      <button onClick={() => updateEditorSettings({ theme: 'one-dark' })}>切到 One Dark</button>
      <DslEditor value="param w = 10" onChange={() => {}} diagnostics={[]} />
    </>
  )
}

describe('DslEditor 外观设置（需求 0112 C1）', () => {
  it('切换编辑器配色后热更新背景色，且视图实例不重建', () => {
    const { container } = render(
      <ThemeProvider>
        <ThemeSwitchHarness />
      </ThemeProvider>,
    )
    const host = container.querySelector('.cm-editor') as HTMLElement
    const view = EditorView.findFromDOM(host)!

    fireEvent.click(screen.getByText('切到 One Dark'))

    expect(getComputedStyle(host).backgroundColor).toBe('rgb(40, 44, 52)')
    // 热更新：同一个 EditorView 实例，未重建
    expect(EditorView.findFromDOM(container.querySelector('.cm-editor') as HTMLElement)).toBe(view)
  })
})
