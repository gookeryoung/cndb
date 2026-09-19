/** FieldManager 组件测试 —— 字段行备注文字 + 编辑对话框自动填充 Radio 激活态.
 *
 * 验收：
 *  1. 字段行以备注风格显示「默认值：xxx」与「创建时/更新时自动填充」，未配置则不渲染备注
 *  2. 编辑 date 字段（config 缺失 auto_fill 键）时「不自动」Radio 处于激活态
 *  3. 编辑配置了 auto_fill=on_create 的 date 字段时「创建时」Radio 激活
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import FieldManager from './FieldManager'
import { renderProviders } from '@/test/render-providers'
import { tableApi } from '@/api'

const WID = '10'
const TID = '20'

/** 字段 fixture：覆盖 备注显示 / 缺失 auto_fill 键 / 已配置 auto_fill 三种形态 */
const FIELDS = [
    { id: 1, name: '状态', field_type: 'text', order: 0, default_value: '待办' },
    { id: 2, name: '创建日期', field_type: 'date', order: 1, config: { auto_fill: 'on_create' } },
    { id: 3, name: '普通日期', field_type: 'date', order: 2, config: {} },
    { id: 4, name: '无设置', field_type: 'text', order: 3 },
] as any

function renderFieldManager() {
    renderProviders(
        <FieldManager open wid={WID} tid={TID} fields={FIELDS} onClose={() => { }} onChanged={() => { }} embedded />,
        { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
    )
}

/** 点击指定字段行的「编辑」按钮（行操作第一个按钮） */
function clickEditRow(fieldName: string) {
    const rows = Array.from(document.querySelectorAll('.fm-row'))
    const row = rows.find(r => r.querySelector('.fm-row-name')?.textContent === fieldName)
    expect(row).toBeDefined()
    const editBtn = row!.querySelector('.fm-row-actions button')
    expect(editBtn).not.toBeNull()
    fireEvent.click(editBtn!)
}

/** 取对话框中指定文案的 Radio.Button 包装节点 */
function radioWrapper(text: string): HTMLElement | null {
    const el = screen.getByText(text)
    return el.closest('label')
}

beforeEach(() => {
    vi.spyOn(tableApi, 'list').mockResolvedValue([] as any)
})

describe('FieldManager 字段行备注文字', () => {
    it('配置了默认值/自动填充的字段行显示备注，未配置的不渲染', () => {
        renderFieldManager()

        // 状态（text + default_value）→ 仅默认值备注
        expect(screen.getByText('默认值：待办')).toBeInTheDocument()
        // 创建日期（date + on_create）→ 自动填充备注
        expect(screen.getByText('创建时自动填充')).toBeInTheDocument()
        // 无备注的字段（普通日期/无设置）不渲染 .fm-row-note
        const notes = document.querySelectorAll('.fm-row-note')
        expect(notes).toHaveLength(2)
    })
})

describe('FieldManager 编辑对话框自动填充激活态', () => {
    it('编辑缺失 auto_fill 键的 date 字段时「不自动」Radio 激活', async () => {
        renderFieldManager()
        clickEditRow('普通日期')

        await waitFor(() => {
            const wrapper = radioWrapper('不自动')
            expect(wrapper).toHaveClass('ant-radio-button-wrapper-checked')
        })
    })

    it('编辑 auto_fill=on_create 的 date 字段时「创建时」Radio 激活', async () => {
        renderFieldManager()
        clickEditRow('创建日期')

        await waitFor(() => {
            expect(radioWrapper('创建时')).toHaveClass('ant-radio-button-wrapper-checked')
        })
        // 其它按钮不激活
        expect(radioWrapper('不自动')).not.toHaveClass('ant-radio-button-wrapper-checked')
    })

    it('新建字段对话框中「不自动」默认激活', async () => {
        renderFieldManager()
        fireEvent.click(screen.getByRole('button', { name: /新\s*建\s*字\s*段/ }))

        // openDialog(null) 会安排 setTimeout(0) 的 form.resetFields()：若在 await 中
        // 让定时器先触发，Select 会因表单重置而关闭下拉。故下拉打开→选中须在同一个
        // 同步任务内完成（真实浏览器中用户交互远晚于该定时器，无此竞态）。
        fireEvent.mouseDown(document.querySelector('.ant-select .ant-select-selector')!)
        // 同步遍历选项，按文案定位「日期」
        const target = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
            .find(el => el.textContent === '日期（日期）')
        expect(target).toBeDefined()
        fireEvent.click(target!)

        // 选中「日期」→ ConfigEditor 渲染并填入类型默认 config（auto_fill: ''）
        await waitFor(() => {
            expect(radioWrapper('不自动')).toHaveClass('ant-radio-button-wrapper-checked')
        })
    })
})
