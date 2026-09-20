/**
 * FieldPanel 测试：单/多表点击回调契约、搜索过滤与双包裹回归.
 *
 * 双包裹回归（核心）：额外表字段点击后经 ReportTemplateEditor 最终插入文本
 * 必须恰好是 `{{ records_by_table['X'][0].f }}` 一次包裹（Bug F 回归锚点）。
 */

import React, { forwardRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FieldPanel from './FieldPanel'
import type { TableFieldGroup } from './FieldPanel'
import ReportTemplateEditor from './ReportTemplateEditor'
import type { TemplateEditorHandle } from './TemplateEditor'
import { renderProviders } from '@/test/render-providers'
import type { Field } from '@/api'

// ── mock TemplateEditor（CodeMirror）——捕获 insertText 调用 ──────────────
const { insertSpy } = vi.hoisted(() => ({ insertSpy: vi.fn() }))

vi.mock('./TemplateEditor', () => ({
  default: forwardRef(function MockTemplateEditor(
    _props: unknown,
    ref: React.Ref<TemplateEditorHandle>,
  ) {
    React.useImperativeHandle(
      ref,
      () =>
        ({
          insertText: insertSpy,
          getValue: () => '',
          setValue: () => undefined,
          setReadOnly: () => undefined,
        }) as unknown as TemplateEditorHandle,
    )
    return <div data-testid="mock-template-editor" />
  }),
}))

const mkField = (id: number, name: string): Field =>
  ({ id, name, field_type: 'text', table_id: 1 }) as unknown as Field

/** 测试用 DnD 包装 —— 传感器配置与 ReportTemplateEditor 一致（distance 5），
 *  避免默认传感器在 pointerdown 立即激活拖拽吞掉 click 事件 */
function TestDnd({ children }: { children: React.ReactNode }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )
  return (
    <DndContext sensors={sensors}>
      <SortableContext items={[]} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  )
}

describe('FieldPanel 点击回调契约', () => {
  it('单表模式：点击字段回调收到 (field, undefined)', async () => {
    const onInsert = vi.fn()
    const f1 = mkField(1, '姓名')
    renderProviders(
      <TestDnd><FieldPanel fields={[f1]} onInsert={onInsert} /></TestDnd>,
    )

    await userEvent.click(screen.getByText('姓名'))
    expect(onInsert).toHaveBeenCalledTimes(1)
    expect(onInsert).toHaveBeenCalledWith(f1, undefined)
  })

  it('多表模式：主表 Tab 点击回调收到 isPrimary:true 的分组', async () => {
    const onInsert = vi.fn()
    const groups: TableFieldGroup[] = [
      { tableId: 10, tableName: '员工表', fields: [mkField(1, '姓名')], isPrimary: true },
      { tableId: 20, tableName: '项目表', fields: [mkField(2, '项目名')] },
    ]
    renderProviders(<TestDnd><FieldPanel tableGroups={groups} onInsert={onInsert} /></TestDnd>)

    await userEvent.click(screen.getByText('姓名'))
    expect(onInsert).toHaveBeenCalledWith(
      groups[0].fields[0],
      { tableName: '员工表', isPrimary: true },
    )
  })

  it('多表模式：切换 Tab 后额外表字段点击收到 isPrimary:false 的分组', async () => {
    const onInsert = vi.fn()
    const groups: TableFieldGroup[] = [
      { tableId: 10, tableName: '员工表', fields: [mkField(1, '姓名')], isPrimary: true },
      { tableId: 20, tableName: '项目表', fields: [mkField(2, '项目名')] },
    ]
    renderProviders(<TestDnd><FieldPanel tableGroups={groups} onInsert={onInsert} /></TestDnd>)

    // 切到额外表 Tab
    await userEvent.click(screen.getByText('项目表'))
    await userEvent.click(await screen.findByText('项目名'))
    expect(onInsert).toHaveBeenCalledWith(
      groups[1].fields[0],
      { tableName: '项目表', isPrimary: false },
    )
  })

  it('搜索过滤：仅显示匹配字段', async () => {
    const onInsert = vi.fn()
    const many = Array.from({ length: 12 }, (_, i) => mkField(i + 1, `字段${i + 1}`))
    many.push(mkField(100, '薪资'))
    renderProviders(<TestDnd><FieldPanel fields={many} onInsert={onInsert} /></TestDnd>)

    await userEvent.type(screen.getByPlaceholderText('搜索字段'), '薪资')
    expect(screen.getByText('薪资')).toBeInTheDocument()
    expect(screen.queryByText('字段1')).not.toBeInTheDocument()
  })
})

describe('双包裹回归（ReportTemplateEditor 集成）', () => {
  it('额外表字段点击后编辑器收到恰好一次包裹的 records_by_table 语法', async () => {
    const groups: TableFieldGroup[] = [
      { tableId: 10, tableName: '员工表', fields: [mkField(1, '姓名')], isPrimary: true },
      { tableId: 20, tableName: '项目表', fields: [mkField(2, '项目名')] },
    ]
    renderProviders(
      <ReportTemplateEditor
        value=""
        onChange={() => undefined}
        tableGroups={groups}
      />,
    )

    insertSpy.mockClear()
    await userEvent.click(screen.getByText('项目表'))
    await userEvent.click(await screen.findByText('项目名'))

    expect(insertSpy).toHaveBeenCalledTimes(1)
    expect(insertSpy).toHaveBeenCalledWith("{{ records_by_table['项目表'][0].项目名 }}")
  })

  it('主表字段点击后编辑器收到简化语法', async () => {
    const groups: TableFieldGroup[] = [
      { tableId: 10, tableName: '员工表', fields: [mkField(1, '姓名')], isPrimary: true },
      { tableId: 20, tableName: '项目表', fields: [mkField(2, '项目名')] },
    ]
    renderProviders(
      <ReportTemplateEditor
        value=""
        onChange={() => undefined}
        tableGroups={groups}
      />,
    )

    insertSpy.mockClear()
    await userEvent.click(screen.getByText('姓名'))

    expect(insertSpy).toHaveBeenCalledTimes(1)
    expect(insertSpy).toHaveBeenCalledWith('{{ 姓名 }}')
  })
})
