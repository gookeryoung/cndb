/**
 * SyntaxHelpPanel 组件测试 —— Jinja2 语法帮助面板.
 *
 * 覆盖：标题与引导文案 / 语法分组数据完整性 / 默认展开分组与插入回调 / 展开新分组。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import SyntaxHelpPanel, { SYNTAX_SECTIONS } from './SyntaxHelpPanel'
import { renderProviders } from '@/test/render-providers'

describe('SyntaxHelpPanel 语法帮助', () => {
  it('SYNTAX_SECTIONS 包含 7 组且 key 唯一', () => {
    expect(SYNTAX_SECTIONS).toHaveLength(7)
    expect(new Set(SYNTAX_SECTIONS.map(s => s.key)).size).toBe(7)
    // 每组示例非空
    for (const s of SYNTAX_SECTIONS) expect(s.examples.length).toBeGreaterThan(0)
  })

  it('渲染标题、引导文案与默认展开的示例', () => {
    renderProviders(<SyntaxHelpPanel onInsert={() => { }} />)

    expect(screen.getByText('Jinja2 语法帮助')).toBeInTheDocument()
    expect(screen.getByText(/点击代码块右侧「插入」即可填入编辑器/)).toBeInTheDocument()
    // variables 与 control 默认展开
    expect(screen.getByText('引用字段值')).toBeInTheDocument()
    expect(screen.getByText('遍历全部行')).toBeInTheDocument()
  })

  it('点击"插入"回调示例代码', () => {
    const onInsert = vi.fn()
    renderProviders(<SyntaxHelpPanel onInsert={onInsert} />)

    // 默认展开的 variables 分组第一个示例 {{ records[0].name }}
    fireEvent.click(screen.getAllByText('插入')[0])
    expect(onInsert).toHaveBeenCalledWith('{{ records[0].name }}')
  })

  it('点击未展开的分组标签后展开并插入其示例', () => {
    const onInsert = vi.fn()
    renderProviders(<SyntaxHelpPanel onInsert={onInsert} />)

    expect(screen.queryByText('转大写')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('常用过滤器'))
    expect(screen.getByText('转大写')).toBeInTheDocument()

    // 定位"转大写"所在示例卡片自己的插入按钮
    const example = screen.getByText('转大写').closest('.report-syntax-example')!
    fireEvent.click(example.querySelector('button')!)
    expect(onInsert).toHaveBeenCalledWith('{{ records[0].name | upper }}')
  })
})
