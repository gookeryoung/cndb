/** FieldList 组件测试 —— 删除字段确认流程.
 *
 * 验收：
 *  1. 点击删除按钮弹出 Popconfirm（含字段名与后果提示），确认后 onRemove 收到对应字段
 *  2. Popconfirm 取消不触发 onRemove；按钮外不再嵌套 Tooltip（Tooltip 浮层会覆盖确认弹层）
 *  3. 主键字段不渲染删除按钮
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import FieldList from './FieldList'
import { renderProviders } from '@/test/render-providers'

const FIELDS = [
    { id: 1, name: '标题', field_type: 'text', order: 0, is_primary: true },
    { id: 2, name: '状态', field_type: 'text', order: 1 },
] as any

function renderFieldList(onRemove = vi.fn()) {
    renderProviders(
        <FieldList
            fields={FIELDS}
            isReordering={false}
            onEdit={() => { }}
            onRemove={onRemove}
            onReorder={() => { }}
            onOpenImport={() => { }}
            onCreate={() => { }}
        />,
    )
    return onRemove
}

describe('FieldList 删除字段确认', () => {
    it('删除按钮弹出 Popconfirm，确认后触发 onRemove', () => {
        const onRemove = renderFieldList()

        fireEvent.click(screen.getByRole('button', { name: '删除字段 状态' }))
        // Popconfirm 弹层出现，且提示文案在弹层中（原 Tooltip 文案并入 Popconfirm）
        expect(screen.getByText('删除字段 "状态" ？')).toBeInTheDocument()
        expect(screen.getByText('列及其数据将从表中移除，不可恢复')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /^删\s*除$/ }))
        expect(onRemove).toHaveBeenCalledTimes(1)
        expect(onRemove).toHaveBeenCalledWith(FIELDS[1])
    })

    it('Popconfirm 取消后不触发 onRemove', () => {
        const onRemove = renderFieldList()

        fireEvent.click(screen.getByRole('button', { name: '删除字段 状态' }))
        fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
        expect(onRemove).not.toHaveBeenCalled()
    })

    it('主键字段不渲染删除按钮', () => {
        renderFieldList()
        expect(screen.queryByRole('button', { name: '删除字段 标题' })).toBeNull()
    })
})
