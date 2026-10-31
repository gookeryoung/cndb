/** FieldManager 组件测试 —— 字段行备注文字 + 编辑对话框自动填充 Radio 激活态 + DefaultValueInput 类型感知控件.
 *
 * 验收：
 *  1. 字段行以备注风格显示「默认值：xxx」与「创建时/更新时自动填充」，未配置则不渲染备注
 *  2. 编辑 date 字段（config 缺失 auto_fill 键）时「不自动」Radio 处于激活态
 *  3. 编辑配置了 auto_fill=on_create 的 date 字段时「创建时」Radio 激活
 *  4. DefaultValueInput 按字段类型渲染不同控件（Select/DatePicker/InputNumber/Switch）
 *  5. 不支持默认值的类型（link/attachment/timestamp）默认值控件禁用
 *  6. 编辑/新建已配置自动编号的 text 字段：模式 Radio 正确激活、参数可编辑，
 *     除 rc-util isEqual 对 rc-field-form 内部 meta 的已知误报外无任何警告
 *     （误报成因与白名单见 isUpstreamCircularNoise 注释）
 *  7. 字段顺序拖拽：手柄渲染、dragEnd 交换后按新顺序提交 reorder、成功回调 onChanged、失败提示
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import FieldManager, { fieldNoteText, formatIncrementExample } from './index'
import { renderProviders } from '@/test/render-providers'
import { fieldApi, tableApi, workspaceApi } from '@/api'

/** dnd-kit mock 共享状态：DndContext 挂载时捕获 onDragEnd 供用例直接驱动拖拽完成回调 */
const dnd = vi.hoisted(() => ({
    dragEnd: null as ((event: { active: { id: unknown }; over: { id: unknown } | null }) => void) | null,
}))

vi.mock('@dnd-kit/core', () => ({
    // 记录 onDragEnd（jsdom 下模拟 PointerSensor 拖拽不可靠，直接驱动回调验证核心逻辑）
    DndContext: ({ children, onDragEnd }: { children: ReactNode; onDragEnd?: (e: unknown) => void }) => {
        dnd.dragEnd = onDragEnd ?? null
        return <>{children}</>
    },
    closestCenter: () => null,
    PointerSensor: class { },
    useSensor: () => ({}),
    useSensors: (...sensors: unknown[]) => sensors,
}))

vi.mock('@dnd-kit/sortable', async (importOriginal) => {
    const actual = await importOriginal<Record<string, unknown>>()
    return {
        ...actual, // 保留 arrayMove / verticalListSortingStrategy 真实现
        SortableContext: ({ children }: { children: ReactNode }) => <>{children}</>,
        useSortable: () => ({
            attributes: {},
            listeners: {},
            setNodeRef: () => { },
            transform: null,
            transition: undefined,
            isDragging: false,
        }),
    }
})

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

    // 打开类型下拉 → 搜索定位 → 点选（antd 6：mousedown 根节点 .ant-select）
    // antd 6 弹层为异步两段挂载，且 openDialog(null) 的 setTimeout(0) resetFields 会重建表单
    // 节点：必须等 Select 挂载并让该定时器跑完后交互，否则 mousedown 落在被重建前的节点上无效
    await waitFor(() => {
        expect(document.querySelector('.ant-select')).not.toBeNull()
    })
    await act(async () => {
        await new Promise(r => setTimeout(r, 0))
    })
    fireEvent.mouseDown(document.querySelector('.ant-select')!)
    await waitFor(() => {
        expect(document.querySelector('.ant-select-dropdown')).not.toBeNull()
    })

    // 搜索框在 Select 根节点内部（v6 为 input.ant-select-input），不在 dropdown 里
    const typeSelect = document.querySelector('.ant-select') as HTMLElement
    const searchInput = typeSelect?.querySelector('input.ant-select-input') as HTMLInputElement
    expect(searchInput).not.toBeNull()
    fireEvent.change(searchInput, { target: { value: typeLabelZh } })

    // 筛选后 options 中至少有一个包含目标中文名，出现后再点击（点击副作用不放 waitFor 轮询内）
    const opt = await waitFor(() => {
        const opts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
            .filter(el => (el.textContent ?? '').includes(typeLabelZh))
        expect(opts.length).toBeGreaterThanOrEqual(1)
        return opts[0]!
    })
    fireEvent.click(opt)

    // 类型切换后，等待默认值 Form.Item（label 含「默认值」）渲染出来
    await waitFor(() => {
        const labels = Array.from(document.querySelectorAll('.ant-form-item-label'))
            .map(l => l.textContent ?? '')
        expect(labels.some(t => t.includes('默认值'))).toBe(true)
    })
}

/** 在下拉菜单中等待指定文本的选项出现后点击（waitFor 内只查询断言，点击放外层避免轮询副作用） */
async function clickSelectOption(label: string) {
    const opt = await waitFor(() => {
        const opt = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
            .find(el => el.textContent === label)
        expect(opt).toBeDefined()
        return opt!
    })
    fireEvent.click(opt)
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
        fireEvent.mouseDown(document.querySelector('.ant-select')!)
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

            // antd Switch 根元素是 <button class="ant-switch">，直接 click 即可触发 onChange
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

            // 打开 Select 下拉 → 选一个选项（antd 6：mousedown 根节点）
            const selector = control.querySelector('.ant-select')!
            fireEvent.mouseDown(selector)
            await clickSelectOption('待办')

            // 填字段名 → 点确定 → 检查 create payload
            fireEvent.change(screen.getByPlaceholderText('例如：姓名') as HTMLInputElement, {
                target: { value: '优先级' },
            })
            // 用模态框底部主按钮定位：字段列表中「创建日期」字段的删除按钮 aria-label 也含"创建"，会误匹配
            fireEvent.click(document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement)

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
            // 同上：用模态框底部主按钮定位，避免误匹配「删除字段 创建日期」
            fireEvent.click(document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement)

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
            fireEvent.mouseDown(control.querySelector('.ant-select')!)
            await clickSelectOption('待办')

            // 删除 index=0（"待办"）选项
            removeSelectOption(0)

            // 默认值 Select 的 value 应该被清空（显示 placeholder）
            await waitFor(() => {
                // antd 6 单选有值时 .ant-select-content 带 has-value 类；清空后消失
                expect(control.querySelector('.ant-select-content')).not.toHaveClass('ant-select-content-has-value')
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
            fireEvent.mouseDown(control.querySelector('.ant-select')!)
            // multiselect 打开后会关闭，需要每次重开
            await clickSelectOption('高优')
            await waitFor(() => {
                expect(control.querySelectorAll('.ant-select-selection-item')).toHaveLength(1)
            })
            fireEvent.mouseDown(control.querySelector('.ant-select')!)
            await clickSelectOption('低优')
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
            fireEvent.mouseDown(control.querySelector('.ant-select')!)
            await clickSelectOption('A')
            fireEvent.mouseDown(control.querySelector('.ant-select')!)
            await clickSelectOption('B')
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
                // antd 6 单选选中值直接渲染在 .ant-select-content（不再有 .ant-select-selection-item）
                const content = control.querySelector('.ant-select-content')
                expect(content).not.toBeNull()
                expect(content).toHaveClass('ant-select-content-has-value')
                expect(content!.textContent).toBe('进行中')
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

    // ─────── 单行文本自动编号 UI ───────

    describe('单行文本自动编号 UI', () => {
        /** 捕获 console.warn/error 消息，返回读回函数（供零容忍断言） */
        function captureConsole() {
            const messages: string[] = []
            const push = (...args: unknown[]) => messages.push(args.map(String).join(' '))
            const warnSpy = vi.spyOn(console, 'warn').mockImplementation(push)
            const errorSpy = vi.spyOn(console, 'error').mockImplementation(push)
            return {
                messages,
                restore: () => { warnSpy.mockRestore(); errorSpy.mockRestore() },
            }
        }

        /** 上游 rc-util isEqual 的已知误报白名单：rc-field-form 内部 meta 的
         *  errors/warnings 引用同一个 EMPTY_ERRORS 常量数组，同一被比较对象在两个键下
         *  重复出现该数组时，deepEqual 的 refSet（先查 has、后 add、且只 add a）会把它
         *  误判为循环引用。经堆栈定位，比较对象 keys 均为 rc 内部 meta 字段
         *  （touched,validating,errors,...），与本组件写入的 config 数据无关；
         *  该警告仅是开发态控制台噪音（rc-util warning 生产构建不输出），白名单化。
         */
        function isUpstreamCircularNoise(m: string): boolean {
            return m.includes('There may be circular references')
        }

        it('编辑已配置自动编号的字段：对话框正常打开且模式 Radio 激活（无异常警告）', async () => {
            const captured = captureConsole()
            try {
                renderFieldManager()
                clickEditRow('编号')

                await waitFor(() => {
                    expect(radioWrapper('自动编号')).toHaveClass('ant-radio-button-wrapper-checked')
                })
                // 参数编辑区渲染：前缀/补零/起始输入框 + 示例文字
                await waitFor(() => {
                    const control = defaultValueControl()
                    expect(control.querySelector('input[placeholder="前缀，如 PRJ-"]')).not.toBeNull()
                    expect(control.textContent).toContain('PRJ-0001')
                })
                // 除上游 isEqual 误报外，任何警告/错误零容忍
                expect(captured.messages.filter(m => !isUpstreamCircularNoise(m))).toEqual([])
            } finally {
                captured.restore()
            }
        })

        it('编辑已配置自动编号的字段：回填参数正确且可切回静态值再切回（无异常警告）', async () => {
            const captured = captureConsole()
            try {
                renderFieldManager()
                clickEditRow('编号')

                await waitFor(() => {
                    expect(radioWrapper('自动编号')).toHaveClass('ant-radio-button-wrapper-checked')
                })
                // 切回静态值
                fireEvent.click(radioWrapper('静态值')!)
                await waitFor(() => {
                    expect(radioWrapper('静态值')).toHaveClass('ant-radio-button-wrapper-checked')
                })
                // 再切回自动编号
                fireEvent.click(radioWrapper('自动编号')!)
                await waitFor(() => {
                    expect(radioWrapper('自动编号')).toHaveClass('ant-radio-button-wrapper-checked')
                    expect(defaultValueControl().querySelector('input[placeholder="前缀，如 PRJ-"]')).not.toBeNull()
                })
                expect(captured.messages.filter(m => !isUpstreamCircularNoise(m))).toEqual([])
            } finally {
                captured.restore()
            }
        })

        it('新建单行文本字段：点击「自动编号」展开参数区并写入 config（无异常警告）', async () => {
            const captured = captureConsole()
            try {
                await openNewDialogAndSelectType('单行文本')

                fireEvent.click(radioWrapper('自动编号')!)
                await waitFor(() => {
                    const control = defaultValueControl()
                    expect(control.querySelector('input[placeholder="前缀，如 PRJ-"]')).not.toBeNull()
                    expect(control.textContent).toContain('示例：0001')
                })

                // 修改前缀 → 示例实时更新
                const prefixInput = defaultValueControl().querySelector('input[placeholder="前缀，如 PRJ-"]') as HTMLInputElement
                fireEvent.change(prefixInput, { target: { value: 'WO-' } })
                await waitFor(() => {
                    expect(defaultValueControl().textContent).toContain('示例：WO-0001')
                })
                expect(captured.messages.filter(m => !isUpstreamCircularNoise(m))).toEqual([])
            } finally {
                captured.restore()
            }
        })
    })
})

// ─────────────── 字段顺序拖拽（reorder）───────────────

describe('FieldManager 字段顺序拖拽', () => {
    /** 驱动 dnd-kit onDragEnd 回调（拖拽交互已 mock，直接触发完成事件） */
    function fireDragEnd(activeId: string | number, overId: string | number | null) {
        expect(dnd.dragEnd).not.toBeNull()
        dnd.dragEnd!({ active: { id: activeId }, over: overId === null ? null : { id: overId } })
    }

    /** 渲染带 spies 的 FieldManager：返回 onChanged spy */
    function renderWithSpies() {
        const onChanged = vi.fn()
        renderProviders(
            <FieldManager open wid={WID} tid={TID} fields={FIELDS} onClose={() => { }} onChanged={onChanged} embedded />,
            { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
        )
        return { onChanged }
    }

    it('每个字段行渲染拖拽手柄，工具栏提示可拖拽调整顺序', () => {
        renderWithSpies()

        const handles = document.querySelectorAll('.fm-row-drag-handle')
        expect(handles).toHaveLength(FIELDS.length)
        handles.forEach(h => expect(h.getAttribute('title')).toBe('拖拽调整字段顺序'))
        expect(screen.getByText(/共 5 个字段 · 拖拽手柄可调整顺序/)).toBeInTheDocument()
    })

    it('拖拽第 1 个字段到第 3 位：按新顺序提交 reorder 并回调 onChanged', async () => {
        const { onChanged } = renderWithSpies()
        const reorderSpy = vi.spyOn(fieldApi, 'reorder').mockResolvedValue([] as any)

        // FIELDS 按 order 排序为 [1,2,3,4,5]，把 id=1 移到 id=3 的位置 → [2,3,1,4,5]
        fireDragEnd('1', '3')

        await waitFor(() => {
            expect(reorderSpy).toHaveBeenCalledTimes(1)
            expect(reorderSpy).toHaveBeenCalledWith(WID, TID, [2, 3, 1, 4, 5])
        })
        await waitFor(() => {
            expect(onChanged).toHaveBeenCalledTimes(1)
        })
    })

    it('拖拽目标为 null（拖出列表）时不提交', () => {
        renderWithSpies()
        const reorderSpy = vi.spyOn(fieldApi, 'reorder').mockResolvedValue([] as any)

        fireDragEnd('1', null)

        expect(reorderSpy).not.toHaveBeenCalled()
    })

    it('拖回原位（active === over）时不提交', () => {
        renderWithSpies()
        const reorderSpy = vi.spyOn(fieldApi, 'reorder').mockResolvedValue([] as any)

        fireDragEnd('2', '2')

        expect(reorderSpy).not.toHaveBeenCalled()
    })

    it('reorder 失败时提示错误且不回调 onChanged', async () => {
        const { onChanged } = renderWithSpies()
        vi.spyOn(fieldApi, 'reorder').mockRejectedValue(new Error('排序冲突'))

        fireDragEnd('1', '3')

        expect(await screen.findByText('排序冲突')).toBeInTheDocument()
        expect(onChanged).not.toHaveBeenCalled()
    })
})

// ─────────────── 从其他表引入字段对话框（跨工作区） ───────────────

describe('FieldManager 从其他表引入字段', () => {
    const WORKSPACES = [
        { id: 10, name: '当前工作区' },
        { id: 11, name: '其他工作区' },
    ] as any

    const SOURCE_FIELDS = [
        { id: 101, name: '名称', field_type: 'text', order: 0 },
        { id: 102, name: '金额', field_type: 'number', order: 1 },
        { id: 103, name: '主键列', field_type: 'text', order: 2 },
    ] as any

    /** 打开引入对话框并选中"其他工作区"→"外部表"，等源字段渲染完成 */
    async function openImportDialogWithSource() {
        renderFieldManager()
        fireEvent.click(screen.getByRole('button', { name: /从其他表引入/ }))

        await waitFor(() => {
            expect(screen.getByText('选择源工作区')).toBeInTheDocument()
        })

        // 选工作区：打开第一个 Select 下拉 → 点"其他工作区"
        const selectors = document.querySelectorAll('.ant-modal-body .ant-select')
        fireEvent.mouseDown(selectors[0]!)
        await clickSelectOption('其他工作区')

        // 选源表：先打开第二个 Select（源表）下拉，再点"外部表"
        await waitFor(() => {
            expect(document.querySelectorAll('.ant-modal-body .ant-select').length).toBeGreaterThanOrEqual(2)
        })
        fireEvent.mouseDown(document.querySelectorAll('.ant-modal-body .ant-select')[1]!)
        await clickSelectOption('外部表')

        // 等源字段勾选区渲染
        await waitFor(() => {
            expect(screen.getByText('选择要引入的字段')).toBeInTheDocument()
        })
    }

    beforeEach(() => {
        vi.spyOn(tableApi, 'list').mockImplementation(((wid: unknown) => {
            if (String(wid) === '11') {
                return Promise.resolve([
                    { id: 20, name: '内部表' },
                    { id: 30, name: '外部表' },
                ]) as any
            }
            return Promise.resolve([]) as any
        }) as any)
        vi.spyOn(workspaceApi, 'list').mockResolvedValue(WORKSPACES as any)
        vi.spyOn(fieldApi, 'list').mockResolvedValue(SOURCE_FIELDS as any)
    })

    it('AC-3: 工作区下拉列出可访问工作区，选表后用源工作区 wid 拉字段', async () => {
        await openImportDialogWithSource()

        // 源字段按源工作区 wid=11 拉取
        expect(fieldApi.list).toHaveBeenCalledWith('11', '30')
        // 勾选区渲染 3 个源字段
        expect(screen.getByText('名称')).toBeInTheDocument()
        expect(screen.getByText('金额')).toBeInTheDocument()
    })

    it('AC-4: 过滤后全选只作用于可见项', async () => {
        await openImportDialogWithSource()

        // 过滤"名称" → 可见项只剩 名称
        fireEvent.change(screen.getByPlaceholderText('过滤字段名…'), { target: { value: '名称' } })
        await waitFor(() => {
            expect(screen.queryByText('金额')).not.toBeInTheDocument()
        })

        // 全选 → 只勾上"名称"（AntD 双汉字按钮会自动插入空格，用正则匹配）
        const allBtn = screen.getByRole('button', { name: /全\s*选/ })
        fireEvent.click(allBtn)
        await waitFor(() => {
            expect(screen.getByText(/已选 1\/3/)).toBeInTheDocument()
        })

        // 清空过滤 → 全选补齐剩余字段（3 个源字段全部可选）
        fireEvent.change(screen.getByPlaceholderText('过滤字段名…'), { target: { value: '' } })
        fireEvent.click(screen.getByRole('button', { name: /全\s*选/ }))
        await waitFor(() => {
            expect(screen.getByText(/已选 3\/3/)).toBeInTheDocument()
        })
    })

    it('link 字段显示关联目标所在工作区提示', async () => {
        vi.spyOn(fieldApi, 'list').mockResolvedValue([
            ...SOURCE_FIELDS,
            { id: 104, name: '外部关联', field_type: 'link', order: 3, config: { target_table_id: 30 } },
            { id: 105, name: '未知关联', field_type: 'link', order: 4, config: { target_table_id: 999 } },
        ] as any)

        await openImportDialogWithSource()

        // 目标表 #30 在源工作区表列表里 → "（源工作区）"
        expect(screen.getByText('关联目标：外部表（源工作区）')).toBeInTheDocument()
        // 目标表 #999 解析不到 → 兜底"其他工作区"
        expect(screen.getByText('关联目标：表 #999（其他工作区）')).toBeInTheDocument()
    })

    it('AC-5: 映射面板分组展示，仅引入已匹配把低置信度置为跳过', async () => {
        const previewResp = {
            created: [], skipped: [], total_source_count: 2,
            gap_analysis: { matched: ['名称'], unmapped_source: ['金额'], target_missing: [], conflicts: [] },
            suggestions: [
                { source: '名称', target: '状态', score: 0.9, reason: '完全同名', will_map: true },
                { source: '金额', target: '状态', score: 0.3, reason: '弱匹配', will_map: false },
            ],
        } as any
        vi.spyOn(fieldApi, 'importFields').mockResolvedValue(previewResp)

        await openImportDialogWithSource()

        // 两个源字段都勾上 → 点"分析字段映射"
        fireEvent.click(screen.getByRole('button', { name: /全\s*选/ }))
        fireEvent.click(screen.getByRole('button', { name: /分析字段映射/ }))

        await waitFor(() => {
            expect(screen.getByText(/已匹配推荐/)).toBeInTheDocument()
            // 组头 Tag 文案（"低置信度 1"在按钮文案里也出现，改用唯一片段）
            expect(screen.getByText(/默认将引入为新字段/)).toBeInTheDocument()
        })

        // 点击"仅引入已匹配" → 金额被跳过 → 确认按钮计数变为 1
        fireEvent.click(screen.getByRole('button', { name: /仅引入已匹配/ }))
        await waitFor(() => {
            const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement
            expect(okBtn.textContent).toBe('确认引入（1 个字段）')
        })
        // 多轮 AntD 异步渲染，全量并发时偶发超过全局 5s，显式放宽
    }, 15000)

    // ─────────── 引入模式选择（复制 copy / 关联引用 link） ───────────

    it('默认复制模式：请求 import_mode=copy，映射面板正常展示', async () => {
        const spy = vi.spyOn(fieldApi, 'importFields').mockResolvedValue({
            created: [], skipped: [], total_source_count: 0,
            gap_analysis: { matched: [], unmapped_source: [], target_missing: [], conflicts: [] },
            suggestions: [],
        } as any)
        await openImportDialogWithSource()
        fireEvent.click(screen.getByRole('button', { name: /分析字段映射/ }))
        await waitFor(() => {
            expect(spy).toHaveBeenCalled()
        })
        expect(spy.mock.calls[0]![2]!.import_mode).toBe('copy')
    })

    it('切换关联引用模式：请求带 import_mode=link，预览展示将创建的关联字段', async () => {
        const spy = vi.spyOn(fieldApi, 'importFields').mockResolvedValue({
            created: [], skipped: [], total_source_count: 1,
            gap_analysis: {
                matched: [], unmapped_source: [], target_missing: [], conflicts: [],
                planned_fields: [
                    { name: '名称', field_type: 'lookup', action: 'create' },
                    { name: '名称_link', field_type: 'link', action: 'create' },
                ],
            },
            suggestions: [],
        } as any)
        await openImportDialogWithSource()

        // 切到"关联引用"模式
        fireEvent.click(screen.getByText('关联引用（实时同步）'))
        fireEvent.click(screen.getByRole('button', { name: /分析字段映射/ }))

        await waitFor(() => {
            expect(spy).toHaveBeenCalled()
        })
        expect(spy.mock.calls[0]![2]!.import_mode).toBe('link')
        // link 模式展示将创建的字段清单，不展示 copy 语义的映射对照
        await waitFor(() => {
            expect(screen.getByText(/将创建以下关联字段/)).toBeInTheDocument()
        })
        expect(screen.queryByText('字段映射对照')).not.toBeInTheDocument()
    })
})

// ─────────────── 关联字段编辑对话框：数据回流同步 + 引用字段一致性 ───────────────

describe('FieldManager 关联字段对话框数据同步', () => {
    function itemByLabel(label: string): HTMLElement {
        const item = Array.from(document.querySelectorAll('.ant-form-item')).find(el =>
            el.querySelector('.ant-form-item-label')?.textContent?.includes(label))
        expect(item).toBeDefined()
        return item as HTMLElement
    }
    function targetTableText(): string | undefined {
        // antd 6 单选选中值渲染在 .ant-select-content（无 selection-item 包装）
        return itemByLabel('关联目标表').querySelector('.ant-select-content')?.textContent?.trim() ?? undefined
    }
    function renderFMWith(fields: any) {
        return renderProviders(
            <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />,
            { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
        )
    }

    beforeEach(() => {
        vi.spyOn(tableApi, 'list').mockResolvedValue([{ id: 30, name: '项目表' }, { id: 31, name: '客户表' }] as any)
        vi.spyOn(fieldApi, 'list').mockImplementation(((_wid: unknown, tid: unknown) => {
            if (String(tid) === '31') {
                return Promise.resolve([
                    { id: 21, name: '客户名称', field_type: 'text' },
                    { id: 22, name: '联系人', field_type: 'text' },
                ]) as any
            }
            return Promise.resolve([
                { id: 11, name: '名称', field_type: 'text' },
                { id: 12, name: '负责人', field_type: 'text' },
            ]) as any
        }) as any)
    })

    it('fields 异步回流时对话框同步最新配置，不再停留旧快照（避免「需再点一次编辑」）', async () => {
        const ui = (f: any) => (
            <FieldManager open wid={WID} tid={TID} fields={f} onClose={() => { }} onChanged={() => { }} embedded />
        )
        const v1 = [{ id: 5, name: '所属项目', field_type: 'link', order: 0, config: { target_table_id: 30, multiple: true } }] as any
        const v2 = [{ id: 5, name: '所属项目', field_type: 'link', order: 0, config: { target_table_id: 31, multiple: true } }] as any
        const r = renderProviders(ui(v1), { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } })
        clickEditRow('所属项目')
        await waitFor(() => expect(targetTableText()).toBe('项目表'))

        // 模拟保存后父层 refetch 回流的 fields
        r.rerender(ui(v2))
        await waitFor(() => expect(targetTableText()).toBe('客户表'))
    })

    it('用户已改动表单时，异步回流不覆盖正在编辑的内容', async () => {
        const ui = (f: any) => (
            <FieldManager open wid={WID} tid={TID} fields={f} onClose={() => { }} onChanged={() => { }} embedded />
        )
        const v1 = [{ id: 5, name: '所属项目', field_type: 'link', order: 0, config: { target_table_id: 30, multiple: true } }] as any
        const v2 = [{ id: 5, name: '所属项目', field_type: 'link', order: 0, config: { target_table_id: 31, multiple: true } }] as any
        const r = renderProviders(ui(v1), { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } })
        clickEditRow('所属项目')
        await waitFor(() => expect(targetTableText()).toBe('项目表'))

        // 用户改写字段名 → onValuesChange 置脏
        const nameInput = itemByLabel('字段名').querySelector('input') as HTMLInputElement
        fireEvent.change(nameInput, { target: { value: '新名字' } })
        r.rerender(ui(v2))
        await new Promise(res => setTimeout(res, 30))
        expect(nameInput.value).toBe('新名字')
        expect(targetTableText()).toBe('项目表')
    })

    it('关联字段缺失 reference_fields 时从同表 lookup 反推展示（修复历史/种子数据不一致）', async () => {
        const fields = [
            { id: 5, name: '部门', field_type: 'link', order: 0, config: { target_table_id: 30, multiple: false } },
            { id: 9, name: '负责人', field_type: 'lookup', order: 1, config: { via_link_field_id: 5, source_field_id: 12, source_field_type: 'text' } },
        ] as any
        renderFMWith(fields)
        clickEditRow('部门')
        await waitFor(() => expect(targetTableText()).toBe('项目表'))
        // 目标表字段加载后，引用字段区应解析出「负责人」
        await waitFor(() => {
            expect(document.querySelector('.fm-ref-list')?.textContent).toContain('负责人')
        })
    })

    it('关联字段 reference_fields 为空数组（后端归一化结果）时同样反推展示，不显示空态', async () => {
        // 后端 _validate_field_config 归一化后 config 恒含 reference_fields（可能为空数组），
        // 此时若仅按「键是否存在」判断会跳过反推，导致编辑关联字段时「引用字段」区内容为空。
        const fields = [
            {
                id: 5, name: '部门', field_type: 'link', order: 0,
                config: { target_table_id: 30, multiple: false, display_field_id: null, match_field_id: null, reference_fields: [] },
            },
            { id: 9, name: '负责人', field_type: 'lookup', order: 1, config: { via_link_field_id: 5, source_field_id: 12, source_field_type: 'text' } },
        ] as any
        renderFMWith(fields)
        clickEditRow('部门')
        await waitFor(() => expect(targetTableText()).toBe('项目表'))
        // 反推后引用字段区应列出「负责人」，而不是「暂无引用字段」空态
        await waitFor(() => {
            expect(document.querySelector('.fm-ref-list')?.textContent).toContain('负责人')
        })
        expect(document.querySelector('.fm-ref-empty')).toBeNull()
    })

    it('对话框打开后归属该关联字段的 lookup 行才异步到达时，引用字段区应随之反推同步', async () => {
        // 首次进入编辑页面时 fields 可能尚未包含该关联字段名下的 lookup 行（分两批回流），
        // 同步指纹若只看关联字段自身的 config，会误判「无变化」而跳过回填，
        // 「引用字段」区就停在打开时的空态 —— 即「首次进入无法同步数据到页面」。
        const ui = (f: any) => (
            <FieldManager open wid={WID} tid={TID} fields={f} onClose={() => { }} onChanged={() => { }} embedded />
        )
        const v1 = [
            { id: 5, name: '部门', field_type: 'link', order: 0, config: { target_table_id: 30, multiple: false } },
        ] as any
        const v2 = [
            { id: 5, name: '部门', field_type: 'link', order: 0, config: { target_table_id: 30, multiple: false } },
            { id: 9, name: '负责人', field_type: 'lookup', order: 1, config: { via_link_field_id: 5, source_field_id: 12, source_field_type: 'text' } },
        ] as any
        const r = renderProviders(ui(v1), { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } })
        clickEditRow('部门')
        await waitFor(() => expect(targetTableText()).toBe('项目表'))
        // 打开时 lookup 行尚未到达 → 引用字段区为空态
        expect(document.querySelector('.fm-ref-list')).toBeNull()

        // lookup 行异步回流后，引用字段区应同步反推出「负责人」
        r.rerender(ui(v2))
        await waitFor(() => {
            expect(document.querySelector('.fm-ref-list')?.textContent).toContain('负责人')
        })
    })

    it('StrictMode 下打开编辑：目标表与引用字段正常回填，不被字段卸载清空', async () => {
        // 回归：<Form preserve={false}> 会在字段组件卸载时丢弃其值，而 React StrictMode 开发态
        // 的「挂载→卸载→重挂载」会连带把父层刚回填的 config 清空，表现为编辑关联字段时
        // 「关联目标表」为空、「引用字段」区显示空态（真实页面 dev 环境即此现象）。
        const fields = [
            {
                id: 5, name: '部门', field_type: 'link', order: 0,
                config: { target_table_id: 30, multiple: false, reference_fields: [12] },
            },
            { id: 9, name: '负责人', field_type: 'lookup', order: 1, config: { via_link_field_id: 5, source_field_id: 12, source_field_type: 'text' } },
        ] as any
        renderProviders(
            <StrictMode>
                <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />
            </StrictMode>,
            { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
        )
        clickEditRow('部门')
        // 字段名回填：受同一卸载清空影响，StrictMode 下曾整体为空
        await waitFor(() => {
            expect((itemByLabel('字段名').querySelector('input') as HTMLInputElement).value).toBe('部门')
        })
        await waitFor(() => expect(targetTableText()).toBe('项目表'))
        await waitFor(() => {
            expect(document.querySelector('.fm-ref-list')?.textContent).toContain('负责人')
        })
    })

    it('字段列表中引用字段行只读：不渲染编辑/删除按钮，也不提供拖拽手柄', () => {
        const fields = [
            { id: 5, name: '部门', field_type: 'link', order: 0, config: { target_table_id: 30 } },
            { id: 9, name: '负责人', field_type: 'lookup', order: 1, config: { via_link_field_id: 5, source_field_id: 12 } },
        ] as any
        renderFMWith(fields)
        const rows = Array.from(document.querySelectorAll('.fm-row'))
        const lookupRow = rows.find(r => r.querySelector('.fm-row-name')?.textContent === '负责人')!
        expect(lookupRow.querySelectorAll('.fm-row-actions button').length).toBe(0)
        // 手柄为占位（无 HolderOutlined 图标）
        expect(lookupRow.querySelector('.anticon-holder')).toBeNull()
        // 归属标注仍在
        expect(lookupRow.textContent).toContain('来自关联')
    })
})

describe('FieldManager 切换字段类型时重置 config', () => {
    /** 在已打开的对话框中把类型切到指定中文类型（复用类型 Select 的 showSearch 精确筛选）.
     *  定位方式：类型 Form.Item（label 含「类型」）内的 .ant-select，避免与配置面板的下拉混用。 */
    async function switchTypeInDialog(typeLabelZh: string) {
        const item = Array.from(document.querySelectorAll('.ant-modal-body .ant-form-item')).find(el =>
            el.querySelector('.ant-form-item-label')?.textContent?.includes('类型'))
        expect(item).toBeDefined()
        const sel = item!.querySelector('.ant-select') as HTMLElement
        fireEvent.mouseDown(sel)
        await waitFor(() => {
            expect(document.querySelector('.ant-select-dropdown')).not.toBeNull()
        })
        const searchInput = sel.querySelector('input.ant-select-input') as HTMLInputElement
        fireEvent.change(searchInput, { target: { value: typeLabelZh } })
        const opt = await waitFor(() => {
            const opts = Array.from(document.querySelectorAll('.ant-select-item-option-content'))
                .filter(el => (el.textContent ?? '').includes(typeLabelZh))
            expect(opts.length).toBeGreaterThanOrEqual(1)
            return opts[0]!
        })
        fireEvent.click(opt)
    }

    /** 点击对话框底部主按钮提交（字段行删除按钮文本可能含「创建」，故不走 getByText） */
    function clickDialogSubmit() {
        fireEvent.click(document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement)
    }

    it('新建字段：配好选项后切换类型，提交的 config 不残留旧类型的 options', async () => {
        // 回归：旧实现靠 <Form preserve={false}> 在卸载时丢弃旧值；该行为会与 StrictMode 交互
        // 清空回填数据（见「关联字段对话框数据同步」里的 StrictMode 用例），改为类型切换时
        // 显式重置 config —— 本用例锁定「切换类型绝不提交旧类型配置」这一不变量。
        const createSpy = vi.spyOn(fieldApi, 'create').mockResolvedValue({} as any)
        await openNewDialogAndSelectType('单选')
        addSelectOption(0, '待办')
        addSelectOption(1, '已完成')
        // 前置确认：选项确实写入了配置（否则下面的「不残留」断言会退化为空断言）
        expect(document.querySelectorAll('.fm-option-row').length).toBeGreaterThanOrEqual(2)

        await switchTypeInDialog('多行')
        fireEvent.change(screen.getByPlaceholderText('例如：姓名') as HTMLInputElement, {
            target: { value: '备注' },
        })
        clickDialogSubmit()

        await waitFor(() => {
            expect(createSpy).toHaveBeenCalled()
            const payload = createSpy.mock.calls[0]![2] as unknown as Record<string, unknown>
            expect(payload.field_type).not.toBe('select')
            expect(payload.config ?? {}).not.toHaveProperty('options')
        })
    })

    it('编辑字段：切换类型后提交的 config 不残留原类型配置', async () => {
        const updateSpy = vi.spyOn(fieldApi, 'update').mockResolvedValue({} as any)
        const fields = [
            ...FIELDS,
            { id: 9, name: '优先级', field_type: 'select', order: 5, config: { options: ['高', '低'] } },
        ] as any
        renderProviders(
            <FieldManager open wid={WID} tid={TID} fields={fields} onClose={() => { }} onChanged={() => { }} embedded />,
            { initialAuth: { user: { id: 1, username: 'alice', role: 'system_admin' } as any, token: 'fake' } },
        )
        clickEditRow('优先级')
        // 等回填完成（字段名 = 优先级），否则切换类型前表单还可能是空的
        await waitFor(() => {
            expect((screen.getByPlaceholderText('例如：姓名') as HTMLInputElement).value).toBe('优先级')
        })

        await switchTypeInDialog('多行')
        clickDialogSubmit()

        await waitFor(() => {
            expect(updateSpy).toHaveBeenCalled()
            const payload = updateSpy.mock.calls[0]![3] as unknown as Record<string, unknown>
            expect(payload.config ?? {}).not.toHaveProperty('options')
        })
    })
})
