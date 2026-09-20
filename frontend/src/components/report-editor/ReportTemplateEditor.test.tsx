/**
 * ReportTemplateEditor 组件测试 —— 字段面板 + 编辑器组合.
 *
 * 覆盖：组合渲染 / 点击字段插入 {{ 字段 }} / 多表额外表插入 records_by_table 表达式（不嵌套）/ editorRef 透传。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import ReportTemplateEditor from './ReportTemplateEditor'
import type { TemplateEditorHandle } from './TemplateEditor'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field } from '@/api'

beforeEach(() => {
  // jsdom 未实现 ResizeObserver，CodeMirror 依赖
  vi.stubGlobal('ResizeObserver', class {
    observe() { /* noop */ }
    unobserve() { /* noop */ }
    disconnect() { /* noop */ }
  })
})

const FIELDS: Field[] = [
  makeField({ id: 1, name: '姓名', field_type: 'text' }),
  makeField({ id: 2, name: '年龄', field_type: 'number' }),
]

describe('ReportTemplateEditor 报告模板编辑器', () => {
  it('渲染字段面板与 CodeMirror 编辑器', () => {
    renderProviders(<ReportTemplateEditor value="" onChange={() => { }} fields={FIELDS} />)

    expect(screen.getByText('字段 (2)')).toBeInTheDocument()
    expect(screen.getByText('姓名')).toBeInTheDocument()
    expect(document.querySelector('.cm-editor')).not.toBeNull()
  })

  it('点击字段插入 {{ 字段 }} 表达式到编辑器', () => {
    const onChange = vi.fn()
    const ref = { current: null as TemplateEditorHandle | null }
    renderProviders(<ReportTemplateEditor value="" onChange={onChange} fields={FIELDS} editorRef={ref} />)

    fireEvent.click(screen.getByText('姓名'))

    expect(ref.current?.getValue()).toBe('{{ 姓名 }}')
  })

  it('单表模式插入后触发 onChange', () => {
    const onChange = vi.fn()
    renderProviders(<ReportTemplateEditor value="" onChange={onChange} fields={FIELDS} />)

    fireEvent.click(screen.getByText('年龄'))

    expect(onChange).toHaveBeenCalledWith('{{ 年龄 }}')
  })

  it('多表模式：额外表字段插入 records_by_table 表达式且不产生嵌套', () => {
    const ref = { current: null as TemplateEditorHandle | null }
    renderProviders(
      <ReportTemplateEditor
        value=""
        onChange={() => { }}
        tableGroups={[
          { tableId: 1, tableName: '客户表', isPrimary: true, fields: FIELDS },
          { tableId: 2, tableName: '员工表', fields: [makeField({ id: 2, name: '员工名', field_type: 'text' })] },
        ]}
        editorRef={ref}
      />,
    )

    // 切到额外表 Tab 并点击其字段
    fireEvent.click(screen.getByText('员工表'))
    fireEvent.click(screen.getByText('员工名'))

    expect(ref.current?.getValue()).toBe("{{ records_by_table['员工表'][0].员工名 }}")
  })
})
