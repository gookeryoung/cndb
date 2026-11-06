/** DslEditor 自动完成挂载测试（需求卡 0110 C5）：只读 viewer 不挂补全扩展. */

import { describe, expect, it } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { EditorView } from '@codemirror/view'
import { completionStatus, startCompletion } from '@codemirror/autocomplete'
import { ThemeProvider, useTheme } from '@/theme/ThemeProvider'
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
