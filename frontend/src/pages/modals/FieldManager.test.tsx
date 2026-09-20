/** FieldManager 组件测试 —— 字段行备注文字 + 编辑对话框自动填充 Radio 激活态 + DefaultValueInput 类型感知控件.
 *
 * 验收：
 *  1. 字段行以备注风格显示「默认值：xxx」与「创建时/更新时自动填充」，未配置则不渲染备注
 *  2. 编辑 date 字段（config 缺失 auto_fill 键）时「不自动」Radio 处于激活态
 *  3. 编辑配置了 auto_fill=on_create 的 date 字段时「创建时」Radio 激活
 *  4. DefaultValueInput 按字段类型渲染不同控件（Select/DatePicker/InputNumber/Switch）
 *  5. 不支持默认值的类型（link/attachment/timestamp）默认值控件禁用
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import FieldManager, { fieldNoteText, formatIncrementExample } from './FieldManager'
import { renderProviders } from '@/test/render-providers'
import { fieldApi, tableApi } from '@/api'

const WID = '10'
const TID = '20'

/** 字段 fixture：覆盖 备注显示 / 缺失 auto_fill 键 / 已配置 auto_fill / 必填唯一自动编号 */
const FIELDS = [
    { id: 1, name: '状态', field_type: 'text', order: 0, default_value: '待办' },
    { id: 2, name: '创建日期', field_type: 'date', order: 1, config: { auto_fill: 'on_create' } },
    { id: 3, name: '普通日期', field_type: 'date', order: 2, config: {} },
    { id: 4, name: '无设置', field_type: 'text', order: 3 },
    {
        id: 5, name: '编号', field_type: 'text', order: 4, required: true, is_unique: true,
        config: { default_mode: 'auto_increment', increment_prefix: 'PRJ-', increment_padding: 4, increment_start: 1 },
    },
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

/** 从所有 .ant-form-item 中找到 label 含「默认值」的那个，返回其 control 容器 */
function defaultValueControl(): HTMLElement {
    const item = Array.from(document.querySelectorAll('.ant-form-item')).find(el =>
        el.querySelector('.ant-form-item-label')?.textContent?.includes('默认值')
    )
    expect(item).toBeDefined()
    return (item as HTMLElement).querySelector('.ant-form-item-control') as HTMLElement
}

/** 打开新建字段对话框并切换到指定类型.
 *  通过 antd Select 的 showSearch（生产代码已加）做精确筛选，
 *  绕过虚拟滚动只渲染可见选项的问题。
 *
 * @param typeLabelZh 类型中文名（如 "单选"、"日期时间"），函数会在搜索框中输入该值，
 *                    筛选后点击匹配的完整选项（如 "单选（选择）"）。
 */
async function openNewDialogAndSelectType(typeLabelZh: string) {
    renderFieldManager()
    fireEvent.click(screen.getByRole('button', { name: /新\s*建\s*字\s*段/ }))

    // openDialog(null) 内部有 setTimeout(0) 的 form.resetFields()：等 Modal 先挂载
    await waitFor(() => {
        expect(document.querySelector('.ant-modal-body')).not.toBeNull()
    })

    // 打开类型下拉 → 搜索定位 → 点选
    fireEvent.mouseDown(document.querySelector('.ant-select-selector')!)
    await waitFor(() => {
        expect(document.querySelector('.ant-select-dropdown')).not.toBeNull()
    })

    // 搜索框在 Select 选择器内部（.ant-select-selection-search-input），不在 dropdown 里
    const typeSelect = document.querySelector('.ant-select') as HTMLElement
    const searchInput = typeSelect?.querySelector('.ant-select-selection-search-input') as HTMLInputElement
    expect(searchInput).not.toBeNull()
    fireEvent.change(searchInput, { target: { value: typeLabelZh } })

    // 筛选后 options 中至少有一个包含目标中文名
    await waitFor(() => {
        const opts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
            .filter(el => (el.textContent ?? '').includes(typeLabelZh))
        expect(opts.length).toBeGreaterThanOrEqual(1)
        fireEvent.click(opts[0]!)
    })

    // 类型切换后，等待默认值 Form.Item（label 含「默认值」）渲染出来
    await waitFor(() => {
        const labels = Array.from(document.querySelectorAll('.ant-form-item-label'))
            .map(l => l.textContent ?? '')
        expect(labels.some(t => t.includes('默认值'))).toBe(true)
    })
}

/** 在 ConfigEditor 里点击"添加选项"按钮并输入 label（第 N 个选项，从 0 开始） */
function addSelectOption(index: number, label: string) {
    // 精确匹配按钮文本 "添加选项"，避开 "全部智能推荐"
    const addBtn = Array.from(document.querySelectorAll('.fm-config-section button')).find(b =>
        b.textContent?.includes('添加选项')
    )
    expect(addBtn).not.toBeNull()
    fireEvent.click(addBtn!)

    // 等待新选项行出现，再输入 label
    const inputs = Array.from(document.querySelectorAll('.fm-option-row input')) as HTMLInputElement[]
    expect(inputs[index]).not.toBeUndefined()
    fireEvent.change(inputs[index]!, { target: { value: label } })
}

beforeEach(() => {
    vi.spyOn(tableApi, 'list').mockResolvedValue([] as any)
})

describe('FieldManager 字段行备注文字', () => {
    it('配置了默认值/自动填充/必填唯一自动编号的字段行显示备注，未配置的不渲染', () => {
        renderFieldManager()

        // 状态（text + default_value）→ 仅默认值备注
        expect(screen.getByText('默认值：待办')).toBeInTheDocument()
        // 创建日期（date + on_create）→ 自动填充备注
        expect(screen.getByText('创建时自动填充')).toBeInTheDocument()
        // 编号（text + auto_increment + required + unique）→ 必填 · 唯一 · 自动编号
        expect(screen.getByText('必填 · 唯一 · 自动编号：PRJ-0001 起')).toBeInTheDocument()
        // 无备注的字段（普通日期/无设置）不渲染 .fm-row-note
        const notes = document.querySelectorAll('.fm-row-note')
        expect(notes).toHaveLength(3)
    })
})

describe('fieldNoteText / formatIncrementExample 纯函数矩阵', () => {
    const f = (extra: Partial<Record<string, unknown>> & { config?: Record<string, unknown> }) =>
        ({ field_type: 'text', ...extra }) as any

    it('空字段返回空串（不渲染备注）', () => {
        expect(fieldNoteText(f({}))).toBe('')
    })

    it('必填/唯一单独与组合的顺序为 必填 · 唯一', () => {
        expect(fieldNoteText(f({ required: true }))).toBe('必填')
        expect(fieldNoteText(f({ is_unique: true }))).toBe('唯一')
        expect(fieldNoteText(f({ required: true, is_unique: true }))).toBe('必填 · 唯一')
    })

    it('静态默认值显示「默认值：xxx」', () => {
        expect(fieldNoteText(f({ default_value: '待办' }))).toBe('默认值：待办')
    })

    it('auto_increment 优先于静态默认值，且不显示默认值备注', () => {
        const field = f({
            default_value: '静态值',
            config: { default_mode: 'auto_increment', increment_prefix: 'WO-', increment_padding: 2, increment_start: 7 },
        })
        expect(fieldNoteText(field)).toBe('自动编号：WO-07 起')
    })

    it('必填 + 唯一 + 自动编号（text 三状态组合）', () => {
        const field = {
            field_type: 'text', required: true, is_unique: true,
            config: { default_mode: 'auto_increment', increment_padding: 0, increment_start: 0 },
        } as any
        expect(fieldNoteText(field)).toBe('必填 · 唯一 · 自动编号：0 起')
    })

    it('自动填充（date/datetime）与自动编号（text）按类型互斥，datetime 走自动填充分支', () => {
        const field = {
            field_type: 'datetime', required: true, is_unique: true,
            config: { default_mode: 'auto_increment', auto_fill: 'on_update' },
        } as any
        // auto_increment 仅对 text 生效，datetime 上不显示自动编号备注
        expect(fieldNoteText(field)).toBe('必填 · 唯一 · 更新时自动填充')
    })

    it('formatIncrementExample：prefix/padding/start 组合', () => {
        expect(formatIncrementExample({ increment_prefix: 'PRJ-', increment_padding: 4, increment_start: 1 })).toBe('PRJ-0001')
        expect(formatIncrementExample({ increment_prefix: 'WO-', increment_padding: 2, increment_start: 7 })).toBe('WO-07')
        expect(formatIncrementExample({ increment_prefix: '', increment_padding: 0, increment_start: 5 })).toBe('5')
        expect(formatIncrementExample(undefined)).toBe('0001')
    })

    it('formatIncrementExample：非法值按 clamp 处理（padding 0-10 / start ≥ 0）', () => {
        expect(formatIncrementExample({ increment_padding: 99 })).toBe('0000000001')
        expect(formatIncrementExample({ increment_padding: -3 })).toBe('1')
        expect(formatIncrementExample({ increment_padding: 'abc' })).toBe('0001')
        expect(formatIncrementExample({ increment_start: -5 })).toBe('0000')
        expect(formatIncrementExample({ increment_start: 7.9 })).toBe('0007')
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
        // 同步遍历选项，按文案定位「日期」（optionRender 会在类型名下追加说明小字，故用前缀匹配）
        const target = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
            .find(el => el.textContent?.startsWith('日期（日期）'))
        expect(target).toBeDefined()
        fireEvent.click(target!)

        // 选中「日期」→ ConfigEditor 渲染并填入类型默认 config（auto_fill: ''）
        await waitFor(() => {
            expect(radioWrapper('不自动')).toHaveClass('ant-radio-button-wrapper-checked')
        })
    })
})

// ─────────────── DefaultValueInput 类型感知控件 ───────────────

describe('FieldManager DefaultValueInput 类型感知控件', () => {
    describe('控件按字段类型渲染', () => {
        it('未选择类型：默认值控件禁用并提示「先选择字段类型」', async () => {
            renderFieldManager()
            fireEvent.click(screen.getByRole('button', { name: /新\s*建\s*字\s*段/ }))
            await waitFor(() => {
                expect(screen.getByPlaceholderText('先选择字段类型')).toBeInTheDocument()
            })
        })

        it('select：默认值渲染为 Select，空 options 时禁用', async () => {
            await openNewDialogAndSelectType('单选')

            const control = defaultValueControl()
            const select = control.querySelector('.ant-select') as HTMLElement
            expect(select).not.toBeNull()
            expect(select).toHaveClass('ant-select-disabled')

            // 添加 1 个选项后，默认值 Select 应启用
            addSelectOption(0, '待办')
            await waitFor(() => {
                expect(select).not.toHaveClass('ant-select-disabled')
            })
        })

        it('multiselect：默认值渲染为 multiple Select，初始禁用', async () => {
            await openNewDialogAndSelectType('多选')

            const control = defaultValueControl()
            const select = control.querySelector('.ant-select') as HTMLElement
            expect(select).not.toBeNull()
            expect(select).toHaveClass('ant-select-disabled')

            addSelectOption(0, '高优')
            addSelectOption(1, '低优')

            // 选项添加后 Select 应启用
            await waitFor(() => {
                expect(select).not.toHaveClass('ant-select-disabled')
            })
        })

        it('boolean：默认值渲染为 Switch，未设置文案为「未设置（= false）」', async () => {
            await openNewDialogAndSelectType('是/否')

            const control = defaultValueControl()
            const sw = control.querySelector('.ant-switch') as HTMLElement
            expect(sw).not.toBeNull()
            expect(sw).not.toHaveClass('ant-switch-disabled')
            expect(control.textContent).toContain('未设置（= false）')
        })

        it('date：默认值渲染为 DatePicker（不含时间）', async () => {
            await openNewDialogAndSelectType('日期')

            expect(screen.getByPlaceholderText('选择日期')).toBeInTheDocument()
        })

        it('datetime：默认值渲染为 DatePicker（含时间）', async () => {
            await openNewDialogAndSelectType('日期时间')

            expect(screen.getByPlaceholderText('选择日期时间')).toBeInTheDocument()
        })

        it('number：默认值渲染为 InputNumber', async () => {
            await openNewDialogAndSelectType('整数')

            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-number')).not.toBeNull()
        })

        it('float：默认值渲染为 InputNumber', async () => {
            await openNewDialogAndSelectType('小数')

            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-number')).not.toBeNull()
        })

        it('percentage：默认值渲染为 InputNumber', async () => {
            await openNewDialogAndSelectType('百分比')

            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-number')).not.toBeNull()
        })

        it('link：默认值控件禁用并提示「不支持」', async () => {
            await openNewDialogAndSelectType('关联')
            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-disabled')).not.toBeNull()
        })

        it('attachment：默认值控件禁用并提示「不支持」', async () => {
            await openNewDialogAndSelectType('附件')
            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-disabled')).not.toBeNull()
        })

        it('timestamp：默认值控件禁用并提示「不支持」', async () => {
            await openNewDialogAndSelectType('时间戳')
            const control = defaultValueControl()
            expect(control.querySelector('.ant-input-disabled')).not.toBeNull()
        })

        it('email：默认值渲染为普通 Input（文本类兜底）', async () => {
            await openNewDialogAndSelectType('邮箱')

            const control = defaultValueControl()
            expect(control.querySelector('.ant-input')).not.toBeNull()
            expect(screen.getByPlaceholderText(/邮箱/)).toBeInTheDocument()
        })
    })

    // ─────── 控件交互 & form store 验证 ───────

    describe('控件交互写入 form store', () => {
        it('percentage InputNumber 渲染 % 后缀', async () => {
            await openNewDialogAndSelectType('百分比')

            const control = defaultValueControl()
            const suffix = control.querySelector('.ant-input-number-suffix')
            expect(suffix).not.toBeNull()
            expect(suffix!.textContent).toBe('%')
        })

        it('boolean Switch 点击后 form store 变为 true', async () => {
            await openNewDialogAndSelectType('是/否')

            const control = defaultValueControl()
            // 初始文案
            expect(control.textContent).toContain('未设置（= false）')

            // antd v5 Switch 根元素是 <button class="ant-switch">，直接 click 即可触发 onChange
            const sw = control.querySelector('.ant-switch') as HTMLElement
            expect(sw).not.toBeNull()
            fireEvent.click(sw!)

            await waitFor(() => {
                // 文案切换为"是"
                expect(control.textContent).toContain('是')
            })

            // 再点一次切回 false
            fireEvent.click(sw!)
            await waitFor(() => {
                expect(control.textContent).toContain('否')
            })
        })

        it('select 设置默认值后提交包含 default_value', async () => {
            const createSpy = vi.spyOn(fieldApi, 'create').mockResolvedValue({} as any)
            await openNewDialogAndSelectType('单选')

            // 添加两个选项
            addSelectOption(0, '待办')
            addSelectOption(1, '已完成')

            // 等默认值 Select 启用
            const control = defaultValueControl()
            await waitFor(() => {
                const sel = control.querySelector('.ant-select')!
                expect(sel).not.toHaveClass('ant-select-disabled')
            })

            // 打开 Select 下拉 → 选一个选项
            const selector = control.querySelector('.ant-select-selector')!
            fireEvent.mouseDown(selector)
            await waitFor(() => {
                const option = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                    .find(el => el.textContent === '待办')
                expect(option).toBeDefined()
                fireEvent.click(option!)
            })

            // 填字段名 → 点确定 → 检查 create payload
            fireEvent.change(screen.getByPlaceholderText('例如：姓名') as HTMLInputElement, {
                target: { value: '优先级' },
            })
            fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))

            await waitFor(() => {
                expect(createSpy).toHaveBeenCalled()
                const payload = createSpy.mock.calls[0]![2] as unknown as Record<string, unknown>
                expect(payload.default_value).toBe('待办')
                expect(payload.field_type).toBe('select')
            })
        })

        it('text 类型输入默认值后提交正确', async () => {
            const createSpy = vi.spyOn(fieldApi, 'create').mockResolvedValue({} as any)
            await openNewDialogAndSelectType('多行')

            const control = defaultValueControl()
            const input = control.querySelector('input')!
            fireEvent.change(input, { target: { value: '默认备注' } })

            fireEvent.change(screen.getByPlaceholderText('例如：姓名') as HTMLInputElement, {
                target: { value: '备注' },
            })
            fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))

            await waitFor(() => {
                expect(createSpy).toHaveBeenCalled()
                const payload = createSpy.mock.calls[0]![2] as unknown as Record<string, unknown>
                expect(payload.default_value).toBe('默认备注')
            })
        })
    })

    // ─────── select/multiselect 默认值 ↔ 选项列表联动 ───────

    describe('select/multiselect 默认值与 options 联动', () => {
        /** 在 ConfigEditor 中删除第 index 个选项行 */
        function removeSelectOption(index: number) {
            const rows = Array.from(document.querySelectorAll('.fm-option-row'))
            expect(rows[index]).toBeDefined()
            // 找最后一个按钮（DeleteOutlined 对应的 danger 按钮）
            const buttons = rows[index]!.querySelectorAll('button')
            const lastBtn = buttons[buttons.length - 1]!
            fireEvent.click(lastBtn)
        }

        it('select：默认值对应选项被删除后自动清空', async () => {
            await openNewDialogAndSelectType('单选')

            addSelectOption(0, '待办')
            addSelectOption(1, '已完成')

            const control = defaultValueControl()
            await waitFor(() => {
                expect(control.querySelector('.ant-select')).not.toHaveClass('ant-select-disabled')
            })

            // 选中"待办"
            fireEvent.mouseDown(control.querySelector('.ant-select-selector')!)
            await waitFor(() => {
                const opt = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                    .find(el => el.textContent === '待办')
                fireEvent.click(opt!)
            })

            // 删除 index=0（"待办"）选项
            removeSelectOption(0)

            // 默认值 Select 的 value 应该被清空（显示 placeholder）
            await waitFor(() => {
                // 有值时 antd Select 会有 .ant-select-selection-item；清空后没有
                const selected = control.querySelectorAll('.ant-select-selection-item')
                expect(selected).toHaveLength(0)
            })
        })

        it('multiselect：删除选项后仅保留仍在列表中的默认值', async () => {
            await openNewDialogAndSelectType('多选')

            addSelectOption(0, '高优')
            addSelectOption(1, '中优')
            addSelectOption(2, '低优')

            const control = defaultValueControl()
            await waitFor(() => {
                expect(control.querySelector('.ant-select')).not.toHaveClass('ant-select-disabled')
            })

            // 打开多选 Select → 依次选"高优"和"低优"
            fireEvent.mouseDown(control.querySelector('.ant-select-selector')!)
            await waitFor(() => {
                const allOpts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                // multiselect 打开后会关闭，需要每次重开
                fireEvent.click(allOpts.find(el => el.textContent === '高优')!)
            })
            await waitFor(() => {
                expect(control.querySelectorAll('.ant-select-selection-item')).toHaveLength(1)
            })
            fireEvent.mouseDown(control.querySelector('.ant-select-selector')!)
            await waitFor(() => {
                const allOpts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                fireEvent.click(allOpts.find(el => el.textContent === '低优')!)
            })
            await waitFor(() => {
                expect(control.querySelectorAll('.ant-select-selection-item')).toHaveLength(2)
            })

            // 删除"高优"（index=0）
            removeSelectOption(0)

            // 只剩"低优"
            await waitFor(() => {
                const items = control.querySelectorAll('.ant-select-selection-item')
                expect(items).toHaveLength(1)
                expect(items[0]!.textContent).toBe('低优')
            })
        })

        it('multiselect：全部选项被删光后默认值清空', async () => {
            await openNewDialogAndSelectType('多选')

            addSelectOption(0, 'A')
            addSelectOption(1, 'B')

            const control = defaultValueControl()
            await waitFor(() => {
                expect(control.querySelector('.ant-select')).not.toHaveClass('ant-select-disabled')
            })

            // 全选
            fireEvent.mouseDown(control.querySelector('.ant-select-selector')!)
            await waitFor(() => {
                const allOpts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                fireEvent.click(allOpts.find(el => el.textContent === 'A')!)
            })
            fireEvent.mouseDown(control.querySelector('.ant-select-selector')!)
            await waitFor(() => {
                const allOpts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                fireEvent.click(allOpts.find(el => el.textContent === 'B')!)
            })
            await waitFor(() => {
                expect(control.querySelectorAll('.ant-select-selection-item')).toHaveLength(2)
            })

            // 两个都删除
            removeSelectOption(0)
            await waitFor(() => {
                expect(document.querySelectorAll('.fm-option-row')).toHaveLength(1)
            })
            removeSelectOption(0)

            // 默认值 Select 应被禁用（无选项） + 无选中项
            await waitFor(() => {
                expect(control.querySelector('.ant-select')).toHaveClass('ant-select-disabled')
                expect(control.querySelectorAll('.ant-select-selection-item')).toHaveLength(0)
            })
        })
    })

    // ─────── 编辑已有字段时默认值回填 ───────

    describe('编辑已有字段默认值回填', () => {
        it('编辑 boolean 字段：默认值 true → Switch 激活 + 文案「是」', async () => {
            const fields = [
                { id: 10, name: '启用', field_type: 'boolean', order: 0, default_value: true },
            ] as any
            renderProviders(
                <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />,
                { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
            )
            clickEditRow('启用')

            await waitFor(() => {
                const control = defaultValueControl()
                expect(control.querySelector('.ant-switch-checked')).not.toBeNull()
                expect(control.textContent).toContain('是')
            })
        })

        it('编辑 select 字段（含 default_value）：默认值回填到 Select', async () => {
            const fields = [
                {
                    id: 11, name: '状态', field_type: 'select', order: 0,
                    default_value: '进行中',
                    config: { options: [{ label: '待办', value: '待办' }, { label: '进行中', value: '进行中' }, { label: '已完成', value: '已完成' }] },
                },
            ] as any
            renderProviders(
                <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />,
                { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
            )
            clickEditRow('状态')

            await waitFor(() => {
                const control = defaultValueControl()
                const items = control.querySelectorAll('.ant-select-selection-item')
                expect(items).toHaveLength(1)
                expect(items[0]!.textContent).toBe('进行中')
            })
        })

        it('编辑 date 字段（含 default_value）：默认值回填到 DatePicker', async () => {
            const fields = [
                { id: 12, name: '截止日', field_type: 'date', order: 0, default_value: '2025-12-31' },
            ] as any
            renderProviders(
                <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />,
                { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
            )
            clickEditRow('截止日')

            await waitFor(() => {
                const control = defaultValueControl()
                const input = control.querySelector('input') as HTMLInputElement
                expect(input.value).toBe('2025-12-31')
            })
        })
    })
})
