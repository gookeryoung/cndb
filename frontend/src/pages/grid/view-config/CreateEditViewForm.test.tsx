/**
 * CreateEditViewForm 组件测试 —— 创建/编辑视图表单：
 * 名称必填校验、提交回调参数（trim / 类型 / 视图选项）、视图类型切换联动
 * （切换清空 opts、按 viewOptionSchema 渲染专属配置、fieldTypes 过滤候选字段）、
 * switch 配置项行为、编辑场景初值回显。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import CreateEditViewForm from './CreateEditViewForm'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'

const fields = [
  makeField({ id: 1, name: '标题', field_type: 'text' }),
  makeField({ id: 2, name: '状态', field_type: 'select' }),
  makeField({ id: 3, name: '截止', field_type: 'date' }),
  makeField({ id: 4, name: '编号', field_type: 'text', is_primary: true }),
]

/** 打开第 idx 个 antd Select（0 = 视图类型选择器） */
function openSelect(idx: number) {
  const selector = document.querySelectorAll('.ant-select .ant-select-selector')[idx]
  fireEvent.mouseDown(selector)
}

/** 点击下拉选项 content 元素（冒泡到选项根触发选中） */
async function pickOption(text: string) {
  fireEvent.click(await screen.findByText(text, { selector: '.ant-select-item-option-content' }))
}

describe('CreateEditViewForm 视图表单', () => {
  it('默认渲染：名称为空时提交按钮禁用', () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    expect(screen.getByPlaceholderText('例如：只看进行中')).toBeInTheDocument()
    expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('表格（Grid）')
    expect(screen.getByRole('button', { name: /创\s*建/ })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('输入名称后提交：onSubmit 收到 trim 后的名称 + 默认 grid 类型 + 空 options', async () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByPlaceholderText('例如：只看进行中'), {
      target: { value: '  只看进行中  ' },
    })
    fireEvent.click(await screen.findByRole('button', { name: /创\s*建/ }))

    expect(onSubmit).toHaveBeenCalledWith('只看进行中', 'grid', {})
  })

  it('grid 类型不渲染视图专属配置项', () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    expect(screen.queryByText('分组字段')).not.toBeInTheDocument()
    expect(screen.queryByText('日期字段')).not.toBeInTheDocument()
  })

  it('切换类型到看板：渲染 kanban 专属配置，候选字段按 fieldTypes 过滤', async () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    openSelect(0)
    await pickOption('看板（Kanban）')

    // kanban schema 的 11 项配置 label 出现
    expect(screen.getByText('分组字段')).toBeInTheDocument()
    expect(screen.getByText('卡片排序方向')).toBeInTheDocument()
    expect(screen.getByText('逾期/紧急卡片置顶')).toBeInTheDocument()
    expect(screen.getByText('紧急阈值（天）')).toBeInTheDocument()
  })

  it('kanban 分组字段下拉仅含 select/boolean/link 等匹配类型，排除 text', async () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    openSelect(0)
    await pickOption('看板（Kanban）')

    // group_field 是第一个配置 Select（整体第 2 个）
    openSelect(1)
    await pickOption('状态 (select)')

    fireEvent.change(screen.getByPlaceholderText('例如：只看进行中'), { target: { value: '看板视图' } })
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('看板视图', 'kanban', { group_field: '状态' })
  })

  it('切换视图类型时清空已填的视图选项草稿', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="我的看板" initialType="kanban"
        initialOptions={{ group_field: '状态' }} onSubmit={onSubmit}
      />,
    )

    // 初值就位
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('我的看板', 'kanban', { group_field: '状态' })

    // 切回表格类型 → opts 清空
    onSubmit.mockClear()
    openSelect(0)
    await pickOption('表格（Grid）')
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('我的看板', 'grid', {})
  })

  it('switch 配置项：初始 undefined 显示为关，打开后写入 opts', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="看板" initialType="kanban" onSubmit={onSubmit}
      />,
    )

    // pin_urgent switch：opts 无值（undefined）→ 判定为关
    const sw = document.querySelector('.ant-switch')!
    expect(sw).not.toHaveClass('ant-switch-checked')
    fireEvent.click(sw)

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('看板', 'kanban', { pin_urgent: true })
  })

  it('编辑场景：initialName/initialOptions 回显，自定义提交文案', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="我的看板" initialType="kanban"
        initialOptions={{ group_field: '状态' }} submitLabel="保存修改" onSubmit={onSubmit}
      />,
    )

    expect(screen.getByDisplayValue('我的看板')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }))
    expect(onSubmit).toHaveBeenCalledWith('我的看板', 'kanban', { group_field: '状态' })
  })
})

describe('CreateEditViewForm 分区与折叠布局', () => {
  /** 渲染 kanban 表单 */
  function renderKanban(onSubmit = vi.fn()) {
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialType="kanban" initialName="看板" onSubmit={onSubmit}
      />,
    )
    return onSubmit
  }

  it('按 schema 分区渲染分区卡片：基础信息不可折叠，其余为可折叠按钮', () => {
    renderKanban()

    expect(screen.getByText('基础信息')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /基础信息/ })).not.toBeInTheDocument()

    for (const label of ['分组与标题', '字段映射', '排序与提醒', '完成状态']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeInTheDocument()
    }
  })

  it('列宽按 optionColSpan 分配：字段下拉整行，方向下拉单列', () => {
    renderKanban()

    expect(screen.getByText('分组字段').closest('.cevf-col-2')).not.toBeNull()
    expect(screen.getByText('卡片排序方向').closest('.cevf-col-1')).not.toBeNull()
  })

  it('次要分区默认展开：完成状态内容默认渲染，点击可收起再展开', () => {
    renderKanban()

    const head = screen.getByRole('button', { name: /完成状态/ })
    expect(head).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('完成标志')).toBeInTheDocument()

    fireEvent.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()

    fireEvent.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('完成标志')).toBeInTheDocument()
  })

  it('默认展开的分区可手动收起', () => {
    renderKanban()
    expect(screen.getByText('分组字段')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /分组与标题/ }))
    expect(screen.queryByText('分组字段')).not.toBeInTheDocument()
  })

  it('切换视图类型后按新 schema 重置折叠状态', async () => {
    renderKanban()

    // 手动把 kanban 默认展开的「完成状态」收起
    fireEvent.click(screen.getByRole('button', { name: /完成状态/ }))
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()

    openSelect(0)
    await pickOption('日历（Calendar）')
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()

    openSelect(0)
    await pickOption('看板（Kanban）')
    // 回到 kanban：「完成状态」恢复默认展开
    expect(screen.getByRole('button', { name: /完成状态/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('完成标志')).toBeInTheDocument()
  })

  it('grid 类型只渲染「基础信息」一个分区（无视图专属分区）', () => {
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={vi.fn()} />)

    expect(screen.getByText('基础信息')).toBeInTheDocument()
    expect(document.querySelectorAll('.cevf-section')).toHaveLength(1)
  })
})
