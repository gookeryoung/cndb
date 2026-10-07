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

/** 点击下拉选项 content 元素（冒泡到选项根触发选中）.
 *
 * findAllByText + 取最后一个：连续操作多个下拉时，前一个下拉的 portal 选项可能
 * 仍残留在 DOM（同一文本命中多个），最新打开的下拉渲染在最后。
 */
async function pickOption(text: string) {
  const opts = await screen.findAllByText(text, { selector: '.ant-select-item-option-content' })
  fireEvent.click(opts.at(-1)!)
}

describe('CreateEditViewForm 视图表单', () => {
  it('默认渲染：名称为空时提交按钮禁用', () => {
    const onSubmit = vi.fn()
    renderProviders(<CreateEditViewForm fields={fields} onSubmit={onSubmit} />)

    expect(screen.getByPlaceholderText('例如：只看进行中')).toBeInTheDocument()
    expect(document.querySelector('.ant-select-selection-item')?.textContent).toBe('表格 (Grid)')
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
    await pickOption('看板 (Kanban)')

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
    await pickOption('看板 (Kanban)')

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
    await pickOption('表格 (Grid)')
    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('我的看板', 'grid', {})
  })

  it('switch 配置项：初始 undefined 回退 defaultValue，写入 opts 时仅保留显式修改', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="看板" initialType="kanban" onSubmit={onSubmit}
      />,
    )

    // pin_urgent defaultValue=true → 初始应该是"开"态
    const sw = document.querySelector('.ant-switch')!
    expect(sw).toHaveClass('ant-switch-checked')
    // 手动关闭 → 写入 false
    fireEvent.click(sw)
    expect(sw).not.toHaveClass('ant-switch-checked')

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('看板', 'kanban', { pin_urgent: false })
  })

  it('switch 配置项：显式传入 false 时回显为关，不受 defaultValue 影响', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="看板" initialType="kanban"
        initialOptions={{ pin_urgent: false }} onSubmit={onSubmit}
      />,
    )

    // pin_urgent 显式 false → 回显为关（defaultValue=true 被覆盖）
    const sw = document.querySelector('.ant-switch')!
    expect(sw).not.toHaveClass('ant-switch-checked')
    // 打开 → 写入 true
    fireEvent.click(sw)
    expect(sw).toHaveClass('ant-switch-checked')

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('看板', 'kanban', { pin_urgent: true })
  })

  it('switch 配置项：defaultValue=false 的 expand_all（WBS）初始显示为关', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={fields} initialName="WBS" initialType="wbs" onSubmit={onSubmit}
      />,
    )

    // expand_all 属于「操作」分区，该分区默认折叠，先展开
    fireEvent.click(screen.getByRole('button', { name: /操作/ }))

    // 操作分区有两个 switch：show_numbering (defaultValue=true) 在前，expand_all (defaultValue=false) 在后
    const switches = document.querySelectorAll('.ant-switch')
    expect(switches[0]).toHaveClass('ant-switch-checked')
    expect(switches[1]).not.toHaveClass('ant-switch-checked')
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
    await pickOption('日历 (Calendar)')
    expect(screen.queryByText('完成标志')).not.toBeInTheDocument()

    openSelect(0)
    await pickOption('看板 (Kanban)')
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

describe('CreateEditViewForm 图表视图配置', () => {
  const chartFields = [
    ...fields,
    makeField({ id: 5, name: '金额', field_type: 'number' }),
    makeField({ id: 6, name: '工时', field_type: 'number' }),
  ]

  it('切换类型到图表：渲染 chart 专属配置与三个分区', async () => {
    renderProviders(<CreateEditViewForm fields={chartFields} onSubmit={vi.fn()} />)

    openSelect(0)
    await pickOption('图表 (Chart)')

    expect(screen.getByText('图表类型')).toBeInTheDocument()
    expect(screen.getByText('维度字段')).toBeInTheDocument()
    expect(screen.getByText('度量字段')).toBeInTheDocument()
    expect(screen.getByText('系列分组字段')).toBeInTheDocument()
    expect(screen.getByText('聚合方式')).toBeInTheDocument()
    expect(screen.getByText('日期分桶粒度')).toBeInTheDocument()
    expect(screen.getByText('显示统计面板')).toBeInTheDocument()
  })

  it('chart_type 切到散点图：X/Y 数值字段出现，维度字段与聚合方式隐藏（visibleWhen），提交携带 chart_type', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="散点" initialType="chart" onSubmit={onSubmit}
      />,
    )

    // chart_type 是 chart 模式下第一个配置 Select（整体第 2 个）
    openSelect(1)
    await pickOption('散点图')

    expect(screen.getByText('X 数值字段')).toBeInTheDocument()
    expect(screen.getByText('Y 数值字段')).toBeInTheDocument()
    expect(screen.getByText('显示趋势线')).toBeInTheDocument()
    expect(screen.queryByText('维度字段')).not.toBeInTheDocument()
    expect(screen.queryByText('系列分组字段')).not.toBeInTheDocument()
    expect(screen.queryByText('聚合方式')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('散点', 'chart', { chart_type: 'scatter' })
  })

  it('chart_type 切到直方图：分箱策略出现、维度字段与散点专属项隐藏', async () => {
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="直方" initialType="chart" onSubmit={vi.fn()}
      />,
    )

    openSelect(1)
    await pickOption('直方图')

    expect(screen.getByText('分箱策略')).toBeInTheDocument()
    expect(screen.getByText('度量字段')).toBeInTheDocument()
    expect(screen.queryByText('维度字段')).not.toBeInTheDocument()
    expect(screen.queryByText('X 数值字段')).not.toBeInTheDocument()
    expect(screen.queryByText('显示趋势线')).not.toBeInTheDocument()
  })

  it('散点图配置 X/Y 字段后提交：opts 携带 x_field / y_field', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="金额散点" initialType="chart" onSubmit={onSubmit}
      />,
    )

    openSelect(1)
    await pickOption('散点图')
    // X 数值字段（整体第 2 个 Select）、Y 数值字段（第 3 个）—— 候选仅数值类字段
    openSelect(2)
    await pickOption('金额 (number)')
    openSelect(3)
    await pickOption('工时 (number)')

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('金额散点', 'chart', {
      chart_type: 'scatter',
      x_field: '金额',
      y_field: '工时',
    })
  })
})

describe('CreateEditViewForm chart 多图条目管理', () => {
  const chartFields = [
    ...fields,
    makeField({ id: 5, name: '金额', field_type: 'number' }),
    makeField({ id: 6, name: '工时', field_type: 'number' }),
  ]

  it('新建多图：添加图表后逐条目配置，提交为 charts[] 形态', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="多图概览" initialType="chart" onSubmit={onSubmit}
      />,
    )

    // 图表 1：配置维度字段（chart_type 默认即 bar，受控同值再点不触发 onChange，无需重选）
    expect(screen.getByRole('button', { name: /删除当前图表/ })).toBeDisabled()
    openSelect(2)
    await pickOption('状态 (select)')

    // 添加图表 → 切到图表 2：散点图 + X/Y 字段
    fireEvent.click(screen.getByRole('button', { name: /添加图表/ }))
    fireEvent.click(screen.getByText('图表 2'))
    openSelect(1)
    await pickOption('散点图')
    openSelect(2)
    await pickOption('金额 (number)')
    openSelect(3)
    await pickOption('工时 (number)')

    fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }))
    expect(onSubmit).toHaveBeenCalledWith('多图概览', 'chart', {
      charts: [
        { dimension_field: '状态' },
        { chart_type: 'scatter', x_field: '金额', y_field: '工时' },
      ],
    })
  })

  it('编辑多图视图：条目回显可切换，修改当前条目后 charts[] 原样保留其余条目', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="概览" initialType="chart" submitLabel="保存"
        initialOptions={{
          charts: [
            { chart_type: 'bar', dimension_field: '状态' },
            { chart_type: 'scatter', x_field: '金额', y_field: '工时' },
          ],
        }}
        onSubmit={onSubmit}
      />,
    )

    // Segmented 回显两条目；图表 1 为 bar → 维度字段可见
    expect(screen.getByText('图表 2')).toBeInTheDocument()
    expect(screen.getByText('维度字段')).toBeInTheDocument()

    // 切到图表 2（scatter）→ 散点专属项可见；打开趋势线
    fireEvent.click(screen.getByText('图表 2'))
    expect(screen.getByText('X 数值字段')).toBeInTheDocument()
    const trendSwitch = [...document.querySelectorAll('.ant-switch')]
      .find(el => !el.classList.contains('ant-switch-checked'))!
    fireEvent.click(trendSwitch)

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    expect(onSubmit).toHaveBeenCalledWith('概览', 'chart', {
      charts: [
        { chart_type: 'bar', dimension_field: '状态' },
        { chart_type: 'scatter', x_field: '金额', y_field: '工时', show_trend_line: true },
      ],
    })
  })

  it('扁平单图编辑时添加再删除：写回扁平键形态，双形态不并存', async () => {
    const onSubmit = vi.fn()
    renderProviders(
      <CreateEditViewForm
        fields={chartFields} initialName="饼图" initialType="chart" submitLabel="保存"
        initialOptions={{ chart_type: 'pie', dimension_field: '状态' }} onSubmit={onSubmit}
      />,
    )

    // 添加（进入 charts[] 形态）再删除（回到扁平形态）
    fireEvent.click(screen.getByRole('button', { name: /添加图表/ }))
    fireEvent.click(screen.getByRole('button', { name: /删除当前图表/ }))

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    expect(onSubmit).toHaveBeenCalledWith('饼图', 'chart', {
      chart_type: 'pie',
      dimension_field: '状态',
    })
  })
})
