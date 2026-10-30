/** FieldConfigPanel 统一面板组件测试 —— 分区卡片渲染 + 表单读写 + 类型联动.
 *
 * 验收：
 *  1. 三个分区卡片（基础属性 / 默认值 / 类型专属配置）按 fieldType 条件渲染
 *  2. 必填 / 唯一 / 视图中隐藏 Checkbox 切换正确写入 form store
 *  3. 默认值控件按类型渲染，输入写回 form.default_value
 *  4. 不支持默认值的类型显示禁用态「不支持」；未选类型显示占位提示
 *  5. isEdit=false 时按类型补齐 config 默认值；isEdit=true 时保留已存 config 不覆盖
 */

import { describe, expect, it, vi } from 'vitest'
import { Form } from 'antd'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import type { FieldType } from '@/api'
import { fieldApi } from '@/api/tables'
import { renderProviders } from '@/test/render-providers'
import FieldConfigPanel from './FieldConfigPanel'

/** 捕获 Form 实例供断言读写 */
const formRef: { current: ReturnType<typeof Form.useForm>[0] | null } = { current: null }

/** 测试宿主：提供 Form 实例并把 formRef 暴露给断言 */
function Host({ fieldType, isEdit = false, editTargetId = null, initialValues }: {
    fieldType: FieldType | undefined
    isEdit?: boolean
    editTargetId?: number | string | null
    initialValues?: Record<string, unknown>
}) {
    const [form] = Form.useForm()
    formRef.current = form
    return (
        <Form form={form} initialValues={initialValues as never}>
            <FieldConfigPanel fieldType={fieldType} form={form} wid="1" tid="2" tables={[]} isEdit={isEdit} editTargetId={editTargetId} />
        </Form>
    )
}

/** 从所有 .ant-form-item 中找到 label 含「默认值」的那个，返回其控件容器 */
function defaultValueControl(): HTMLElement {
    const item = Array.from(document.querySelectorAll('.ant-form-item')).find(el =>
        el.querySelector('.ant-form-item-label')?.textContent?.includes('默认值'),
    )
    expect(item).toBeDefined()
    return (item as HTMLElement).querySelector('.ant-form-item-control') as HTMLElement
}

/** getFieldsValue 的类型收窄（antd 在 strict 模式下返回 unknown） */
function formValues(): Record<string, any> {
    return formRef.current!.getFieldsValue() as Record<string, any>
}

describe('FieldConfigPanel 分区卡片渲染', () => {
    it('渲染基础属性与默认值两个分区；未选类型时不渲染类型专属配置', () => {
        renderProviders(<Host fieldType={undefined} />)
        expect(screen.getByText('基础属性')).toBeInTheDocument()
        expect(screen.getByText('默认值（可选）')).toBeInTheDocument()
        expect(screen.queryByText(/类型专属配置/)).not.toBeInTheDocument()
        // 未选类型：默认值控件禁用并提示先选类型
        expect(screen.getByPlaceholderText('先选择字段类型')).toBeDisabled()
    })

    it('选择有配置项的类型后渲染「类型专属配置 · 类型名」标题', () => {
        renderProviders(<Host fieldType="number" />)
        const title = document.querySelector('.fm-config-title')
        expect(title?.textContent).toContain('类型专属配置')
        expect(title?.textContent).toContain('整数')
    })

    it('整数类型专属分区仅包含最小值/最大值；小数类型额外包含小数位数', () => {
        renderProviders(<Host fieldType="number" />)
        expect(screen.getAllByPlaceholderText('不限').length).toBe(2)
        expect(screen.queryByText('小数位数')).not.toBeInTheDocument()
    })

    it('小数类型专属分区包含最小值/最大值/小数位数', () => {
        renderProviders(<Host fieldType="float" />)
        expect(screen.getAllByPlaceholderText('不限').length).toBe(2)
        expect(screen.getByText('小数位数')).toBeInTheDocument()
    })
})

describe('FieldConfigPanel 基础属性读写', () => {
    it('勾选必填 / 唯一 / 视图中隐藏后写入 form store', () => {
        renderProviders(<Host fieldType="text" />)
        fireEvent.click(screen.getByRole('checkbox', { name: '必填' }))
        fireEvent.click(screen.getByRole('checkbox', { name: '唯一' }))
        fireEvent.click(screen.getByRole('checkbox', { name: '视图中隐藏' }))
        const values = formValues()
        expect(values.required).toBe(true)
        expect(values.is_unique).toBe(true)
        expect(values.hidden).toBe(true)
    })

    it('initialValues 为 true 时 Checkbox 初始激活，取消后写回 false', () => {
        renderProviders(<Host fieldType="text" initialValues={{ required: true }} />)
        const checkbox = screen.getByRole('checkbox', { name: '必填' }) as HTMLInputElement
        expect(checkbox.checked).toBe(true)
        fireEvent.click(checkbox)
        expect(formValues().required).toBe(false)
    })
})

describe('FieldConfigPanel 默认值分区', () => {
    it('text 类型：输入静态默认值写回 form.default_value', () => {
        renderProviders(<Host fieldType="text" />)
        // text 分支先渲染「静态值/自动编号」Radio.Group，需跳过 radio 取文本输入框
        const input = defaultValueControl().querySelector('input:not([type=radio])') as HTMLInputElement
        fireEvent.change(input, { target: { value: '待办' } })
        expect(formValues().default_value).toBe('待办')
    })

    it('boolean 类型：Switch 切换写回 true / false', async () => {
        renderProviders(<Host fieldType="boolean" />)
        // antd 6：Switch 受控 checked 经 Form.useWatch 异步回流，
        // 两次点击之间需等 watch 触发的重渲染落地，否则第二次 onChange 计算出旧值
        fireEvent.click(screen.getByRole('switch'))
        await waitFor(() => expect(formValues().default_value).toBe(true))
        await act(async () => { await Promise.resolve() })
        fireEvent.click(screen.getByRole('switch'))
        await waitFor(() => expect(formValues().default_value).toBe(false))
    })

    it('link 类型：默认值控件禁用并提示「不支持」', () => {
        renderProviders(<Host fieldType="link" />)
        expect(screen.getByPlaceholderText('不支持')).toBeDisabled()
    })

    it('default_value 的 hidden Form.Item 已注册到 form store（保存语义依赖此注册）', () => {
        renderProviders(<Host fieldType="text" initialValues={{ default_value: 'abc' }} />)
        expect(formValues().default_value).toBe('abc')
    })
})

describe('FieldConfigPanel config 默认值补齐', () => {
    it('isEdit=false 且 config 为空：整数默认仅 min/max；小数含 decimals 2', async () => {
        // 用例内连续两次渲染必须先卸载前一个 Host，
        // 否则「类型专属配置」标题在 document 中重复，findByText 直接抛 multiple elements
        const first = renderProviders(<Host fieldType="number" />)
        await screen.findByText(/类型专属配置/)
        expect(formRef.current!.getFieldValue(['config', 'decimals'])).toBeUndefined()
        // 同一用例内二次渲染前先卸载前一实例，避免双实例并存导致查询失败
        cleanup()
        first.unmount()

        renderProviders(<Host fieldType="float" />)
        await screen.findByText(/类型专属配置/)
        expect(formRef.current!.getFieldValue(['config', 'decimals'])).toBe(2)
    })

    it('isEdit=true：已存 config 不被默认值覆盖', async () => {
        renderProviders(
            <Host fieldType="number" isEdit editTargetId={9} initialValues={{ config: { min: 1, max: 9 } }} />,
        )
        await screen.findByText(/类型专属配置/)
        const cfg = formValues().config
        expect(cfg.min).toBe(1)
        expect(cfg.max).toBe(9)
        expect(cfg.decimals).toBeUndefined()
    })
})

/** 从所有 .ant-form-item 中找到 label 含指定文本的那个，返回其控件容器 */
function formItemByLabel(label: string): HTMLElement {
    const item = Array.from(document.querySelectorAll('.ant-form-item')).find(el =>
        el.querySelector('.ant-form-item-label')?.textContent?.includes(label),
    )
    expect(item).toBeDefined()
    return item as HTMLElement
}

describe('FieldConfigPanel 关联字段业务键', () => {
    it('目标表已选：加载目标表字段作为显示/匹配字段候选，并过滤无物理列的关联字段', async () => {
        const spy = vi.spyOn(fieldApi, 'list').mockResolvedValue([
            { id: 11, name: '编号', field_type: 'text' },
            { id: 12, name: '名称', field_type: 'text' },
            { id: 13, name: '内联关联', field_type: 'link' },
        ] as never)
        renderProviders(
            <Host fieldType="link" isEdit editTargetId={1} initialValues={{ config: { target_table_id: 30, multiple: true } }} />,
        )

        await waitFor(() => expect(spy).toHaveBeenCalledWith('1', 30))
        // 候选里应过滤掉 link 字段，仅保留有物理列的字段
        fireEvent.mouseDown(formItemByLabel('显示字段').querySelector('.ant-select')!)
        expect(await screen.findByText('编号')).toBeInTheDocument()
        expect(screen.getByText('名称')).toBeInTheDocument()
        expect(screen.queryByText('内联关联')).not.toBeInTheDocument()

        // 选择候选后写回 config.display_field_id
        fireEvent.click(screen.getByText('编号'))
        expect(formValues().config.display_field_id).toBe(11)
        spy.mockRestore()
    })
})
