/**
 * TemplateEditor 组件测试 —— CodeMirror 模板编辑器.
 *
 * 覆盖：初值渲染 / insertText 触发 onChange / 外部 value 同步 / readOnly 标记 / dropzone 高亮类名。
 * CodeMirror 在 jsdom 需要 ResizeObserver polyfill。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderProviders } from '@/test/render-providers'
import TemplateEditor, { type TemplateEditorHandle } from './TemplateEditor'

beforeEach(() => {
  // jsdom 未实现 ResizeObserver，CodeMirror 依赖
  vi.stubGlobal('ResizeObserver', class {
    observe() { /* noop */ }
    unobserve() { /* noop */ }
    disconnect() { /* noop */ }
  })
})

describe('TemplateEditor 模板编辑器', () => {
  it('初值渲染到 CodeMirror 文档并可 getValue', () => {
    const ref = { current: null as TemplateEditorHandle | null }
    renderProviders(<TemplateEditor ref={ref} value="# 月度报告" onChange={() => { }} />)

    expect(ref.current?.getValue()).toBe('# 月度报告')
    expect(document.querySelector('.cm-editor')).not.toBeNull()
  })

  it('insertText 在光标处插入并触发 onChange', () => {
    const onChange = vi.fn()
    const ref = { current: null as TemplateEditorHandle | null }
    renderProviders(<TemplateEditor ref={ref} value="ab" onChange={onChange} />)

    // CodeMirror 初始光标在文档开头
    ref.current!.insertText('X')

    expect(ref.current!.getValue()).toBe('Xab')
    expect(onChange).toHaveBeenCalledWith('Xab')
  })

  it('外部 value 变化同步到编辑器文档', () => {
    const ref = { current: null as TemplateEditorHandle | null }
    const { rerender } = renderProviders(
      <TemplateEditor ref={ref} value="v1" onChange={() => { }} />,
    )
    rerender(<TemplateEditor ref={ref} value="v2" onChange={() => { }} />)

    expect(ref.current?.getValue()).toBe('v2')
  })

  it('readOnly 时 contentDOM 带 aria-readonly', () => {
    renderProviders(<TemplateEditor value="" readOnly onChange={() => { }} />)

    const content = document.querySelector('.cm-content')
    expect(content?.getAttribute('aria-readonly')).toBe('true')
  })

  it('isDragActive 时宿主带 dropzone-active 类', () => {
    renderProviders(<TemplateEditor value="" isDragActive onChange={() => { }} />)

    const host = document.querySelector('.report-codemirror-host')
    expect(host?.className).toContain('dropzone-active')
    expect(host?.getAttribute('data-dropzone')).toBe('active')
  })
})
