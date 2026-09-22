/** DoneFlagFields 交互测试 —— 操作符切换、无值操作符隐藏匹配值控件 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import DoneFlagFields from './DoneFlagFields'
import { makeField } from '@/test/fixtures'
import type { Field } from '@/api'

const fields: Field[] = [
    makeField({ id: 1, name: '名称', field_type: 'text' }),
    makeField({ id: 2, name: '状态', field_type: 'select', config: { options: [{ label: '完成', value: 'done' }] } }),
]

describe('DoneFlagFields 操作符与匹配值联动', () => {
    it('等值操作符（缺省）渲染匹配值输入框', () => {
        const onChange = vi.fn()
        render(
            <DoneFlagFields fields={fields} doneField="名称" onChange={onChange} />,
        )
        expect(screen.getByPlaceholderText('输入完成匹配文本（精确匹配）')).toBeInTheDocument()
    })

    it('is_not_empty（无值操作符）隐藏匹配值控件', () => {
        const onChange = vi.fn()
        render(
            <DoneFlagFields fields={fields} doneField="名称" doneOp="is_not_empty" onChange={onChange} />,
        )
        expect(screen.queryByPlaceholderText('输入完成匹配文本（精确匹配）')).not.toBeInTheDocument()
    })

    it('未选字段时提示先选字段', () => {
        render(<DoneFlagFields fields={fields} onChange={vi.fn()} />)
        expect(screen.getByText('先选择字段')).toBeInTheDocument()
    })

    it('文本输入回写 done_value', () => {
        const onChange = vi.fn()
        render(<DoneFlagFields fields={fields} doneField="名称" onChange={onChange} />)
        fireEvent.change(screen.getByPlaceholderText('输入完成匹配文本（精确匹配）'), { target: { value: '已完成' } })
        expect(onChange).toHaveBeenLastCalledWith({ done_value: '已完成' })
    })
})
