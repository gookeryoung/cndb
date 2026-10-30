/** MarkdownLiveEditor 实时预览 — 代码块高亮 / 列表符号 / 待办复选框 / 表格渲染 */

import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import MarkdownLiveEditor, { type MarkdownEditorHandle } from './MarkdownLiveEditor'

function renderEditor(value: string) {
  return render(
    <MarkdownLiveEditor value={value} mode="live" workspaceId={1} onChange={() => {}} />,
  )
}

/** 受控包装：勾选等交互需要把写回结果反映到 value 上 */
function renderStateful(initial: string) {
  function Harness() {
    const [value, setValue] = useState(initial)
    return (
      <>
        <MarkdownLiveEditor value={value} mode="live" workspaceId={1} onChange={setValue} />
        <output data-testid="doc-value">{value}</output>
      </>
    )
  }
  return render(<Harness />)
}

describe('MarkdownLiveEditor 代码块高亮', () => {
  it('围栏代码块按语言着色，并区分围栏行与内容行', () => {
    const { container } = renderEditor('```ts\nconst n = 42\n```')
    expect(container.querySelector('.cn-tok-keyword')?.textContent).toBe('const')
    expect(container.querySelector('.cn-tok-number')?.textContent).toBe('42')
    // 围栏行淡色、内容行代码块底色
    expect(container.querySelectorAll('.cm-md-codefence').length).toBe(2)
    expect(container.querySelector('.cm-md-codeblock')).not.toBeNull()
  })

  it('未标注语言的围栏不高亮但仍套代码块样式', () => {
    const { container } = renderEditor('```\nplain text\n```')
    expect(container.querySelector('[class*="cn-tok-"]')).toBeNull()
    expect(container.querySelector('.cm-md-codeblock')).not.toBeNull()
  })

  it('源码模式仍为 textarea，不做装饰', () => {
    const { container } = render(
      <MarkdownLiveEditor value={'```ts\nconst a = 1\n```'} mode="source" onChange={() => {}} />,
    )
    expect(container.querySelector('textarea')).not.toBeNull()
    expect(container.querySelector('.cn-tok-keyword')).toBeNull()
  })
})

describe('MarkdownLiveEditor 列表与待办', () => {
  it('无序列表标记渲染成圆点，嵌套层级换符号', () => {
    const { container } = renderEditor('- 一级\n  - 二级\n- 另一个')
    const bullets = Array.from(container.querySelectorAll('.cm-md-bullet')).map(el => el.textContent)
    expect(bullets).toEqual(['•', '◦', '•'])
    expect(container.querySelector('.cm-content')?.textContent).not.toContain('- 一级')
  })

  it('有序列表保留序号，不做圆点替换', () => {
    const { container } = renderEditor('1. 第一步\n2. 第二步')
    expect(container.querySelector('.cm-md-bullet')).toBeNull()
    expect(container.querySelector('.cm-content')?.textContent).toContain('1. 第一步')
  })

  it('待办项渲染为复选框，已勾选保持勾选态', () => {
    const { container } = renderEditor('- [ ] 待办\n- [x] 已完成')
    const boxes = Array.from(container.querySelectorAll<HTMLInputElement>('.cm-md-task'))
    expect(boxes.map(box => box.checked)).toEqual([false, true])
  })

  it('点击复选框把 `[ ]` 写回为 `[x]`', () => {
    const { container, getByTestId } = renderStateful('- [ ] 待办事项')
    const box = container.querySelector<HTMLInputElement>('.cm-md-task')
    expect(box).not.toBeNull()
    fireEvent.click(box!)
    expect(getByTestId('doc-value').textContent).toBe('- [x] 待办事项')
  })
})

describe('MarkdownLiveEditor 表格', () => {
  const md = '前情提要\n\n| 名称 | 数量 |\n| :-- | --: |\n| 苹果 | 3 |'

  it('光标不在表格内时渲染成真表格', () => {
    const { container } = renderEditor(md)
    expect(container.querySelector('.cm-md-table table')).not.toBeNull()
    expect(
      Array.from(container.querySelectorAll('.cm-md-table th')).map(th => th.textContent),
    ).toEqual(['名称', '数量'])
    const cells = Array.from(container.querySelectorAll<HTMLTableCellElement>('.cm-md-table td'))
    expect(cells.map(td => td.textContent)).toEqual(['苹果', '3'])
    // 对齐方式来自分隔行
    expect(cells[0].style.textAlign).toBe('left')
    expect(cells[1].style.textAlign).toBe('right')
    // 源码竖线与分隔行不再直接显示
    expect(container.querySelector('.cm-content')?.textContent).not.toContain('| :-- |')
  })

  it('单元格内的行内语法按渲染态显示', () => {
    const { container } = renderEditor('说明\n\n| 列 |\n| --- |\n| **粗体** 与 `code` |')
    const cell = container.querySelector('.cm-md-table td')
    expect(cell?.querySelector('strong')?.textContent).toBe('粗体')
    expect(cell?.querySelector('code')?.textContent).toBe('code')
  })

  it('光标在表格内时回到源码，便于编辑', () => {
    const { container } = renderEditor('| a | b |\n| --- | --- |\n| 1 | 2 |')
    expect(container.querySelector('.cm-md-table')).toBeNull()
    expect(container.querySelector('.cm-content')?.textContent).toContain('| --- | --- |')
  })

  it('分隔行不合法时不做表格渲染', () => {
    const { container } = renderEditor('说明\n\n| a | b |\n| x | y |')
    expect(container.querySelector('.cm-md-table')).toBeNull()
  })
})

// ── 数据表引用占位符徽章（0071）────────────────────────

const { badgeMock, subscribeMock } = vi.hoisted(() => ({
  badgeMock: vi.fn(),
  subscribeMock: vi.fn(),
}))

vi.mock('./tableRefNames', () => ({
  tableRefBadge: badgeMock,
  subscribeRefNames: subscribeMock,
}))

describe('MarkdownLiveEditor 数据表引用徽章', () => {
  beforeEach(() => {
    badgeMock.mockReset().mockReturnValue({ label: null, invalid: false })
    subscribeMock.mockReset().mockReturnValue(() => {})
  })

  it('名称解析完成后独占行占位符渲染成可读徽章，源码不再直接显示', () => {
    badgeMock.mockReturnValue({ label: '客户表 · 重点客户', invalid: false })
    const { container } = renderEditor('正文\n\n{{table:7|view=200}}\n\n后文')
    const chip = container.querySelector<HTMLElement>('.cm-md-tableref')
    expect(chip?.textContent).toBe('▦ 客户表 · 重点客户')
    expect(chip?.title).toContain('{{table:7|view=200}}')
    expect(container.querySelector('.cm-content')?.textContent).not.toContain('{{table:7')
  })

  it('名称拉取失败时徽章带警示样式', () => {
    badgeMock.mockReturnValue({ label: '#7', invalid: true })
    // 占位行不能与光标同处首行，否则还原源码不渲染徽章
    const { container } = renderEditor('前文\n\n{{table:7}}\n\n后文')
    const chip = container.querySelector<HTMLElement>('.cm-md-tableref')
    expect(chip).not.toBeNull()
    expect(chip?.className).toContain('cm-md-tableref-invalid')
    expect(chip?.title).toContain('引用可能已失效')
  })

  it('名称加载中（label=null）保持源码展示', () => {
    const { container } = renderEditor('前文\n\n{{table:7}}\n\n后文')
    expect(container.querySelector('.cm-md-tableref')).toBeNull()
    expect(container.querySelector('.cm-content')?.textContent).toContain('{{table:7}}')
  })

  it('光标进入占位行还原为源码，便于编辑', () => {
    badgeMock.mockReturnValue({ label: '客户表', invalid: false })
    let handle: MarkdownEditorHandle | null = null
    const { container } = render(
      <MarkdownLiveEditor
        ref={h => { handle = h }}
        value={'前文\n\n{{table:7}}\n\n后文'}
        mode="live"
        workspaceId={1}
        onChange={() => {}}
      />,
    )
    expect(container.querySelector('.cm-md-tableref')).not.toBeNull()
    // 光标定位到第 3 行行首（占位行）→ 还原源码
    handle!.setSelection(4)
    expect(container.querySelector('.cm-md-tableref')).toBeNull()
    expect(container.querySelector('.cm-content')?.textContent).toContain('{{table:7}}')
  })

  it('代码块内的同形文本不渲染徽章', () => {
    badgeMock.mockReturnValue({ label: '客户表', invalid: false })
    const { container } = renderEditor('```\n{{table:7}}\n```')
    expect(container.querySelector('.cm-md-tableref')).toBeNull()
  })

  it('live 模式订阅名称解析通知；源码模式不订阅', () => {
    renderEditor('{{table:7}}')
    expect(subscribeMock).toHaveBeenCalledTimes(1)
    const { unmount } = render(
      <MarkdownLiveEditor value="{{table:7}}" mode="source" workspaceId={1} onChange={() => {}} />,
    )
    expect(subscribeMock).toHaveBeenCalledTimes(1)
    unmount()
  })
})
