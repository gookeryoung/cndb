/** AnalyticsManagerDrawer 单测 —— 已保存分析列表渲染 / 打开 / 复制 / 删除确认 / 新建. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { AnalyticsManagerDrawer } from './AnalyticsManagerDrawer'
import { renderProviders } from '@/test/render-providers'
import type { AnalyticsTemplate } from '@/api/analytics'

const TABLES = [
  { id: 20, name: '产品批次' },
  { id: 21, name: '其他表' },
]

function makeTemplate(overrides: Partial<AnalyticsTemplate> & Pick<AnalyticsTemplate, 'id' | 'name'>): AnalyticsTemplate {
  return {
    workspace_id: 1,
    table_id: 20,
    description: '',
    config: {
      formulas: [{ key: 'pass_rate', label: '合格率', expr: 'round([合格数] / [产量] * 100, 2)' }],
      chart: { type: 'bar', x: '产品', y: 'pass_rate', aggregation: 'avg' },
      summary: null,
      fields: [],
      limit: 1000,
    },
    updated_at: '2026-10-17T10:00:00Z',
    ...overrides,
  }
}

const TPL_MAIN = makeTemplate({ id: 7, name: '批次合格率分布', description: '按产品看合格率' })
const TPL_OTHER = makeTemplate({
  id: 8,
  name: '其他模板',
  table_id: 21,
  config: {
    formulas: [
      { key: 'total', label: '产量合计', expr: 'sum([产量])' },
      { key: 'blank', label: '', expr: '' },
    ],
    chart: null,
    summary: null,
    fields: [],
    limit: 1000,
  },
})

type DrawerProps = ComponentProps<typeof AnalyticsManagerDrawer>

function renderDrawer(props: Partial<DrawerProps> = {}) {
  const handlers = {
    onClose: vi.fn(),
    onOpenTemplate: vi.fn(),
    onDuplicate: vi.fn(),
    onDelete: vi.fn(),
    onNew: vi.fn(),
  }
  const result = renderProviders(
    <AnalyticsManagerDrawer
      open
      templates={[TPL_MAIN, TPL_OTHER]}
      tables={TABLES}
      activeTemplateId={TPL_MAIN.id}
      dirty
      {...handlers}
      {...props}
    />,
  )
  return { ...result, handlers }
}

describe('AnalyticsManagerDrawer', () => {
  it('列出全部分析：紧凑主行（名称 / 标记 / 数据源 / 公式数），描述与更新时间默认收起', () => {
    renderDrawer()

    expect(screen.getByTestId('analytics-manager')).toBeInTheDocument()
    expect(screen.getByTestId('analytics-manager-new')).toHaveTextContent('新建分析')

    const main = screen.getByTestId('analytics-manager-item-7')
    expect(main).toHaveTextContent('批次合格率分布')
    expect(main).toHaveTextContent('产品批次 · 1 个公式')
    expect(main).toHaveTextContent('当前')
    expect(main).toHaveTextContent('未保存')
    // 描述与更新时间收在详情里，主行不展示
    expect(main).not.toHaveTextContent('按产品看合格率')
    expect(main).not.toHaveTextContent('更新于')
    expect(screen.queryByTestId('analytics-manager-desc-7')).not.toBeInTheDocument()

    const other = screen.getByTestId('analytics-manager-item-8')
    expect(other).toHaveTextContent('其他表 · 1 个公式')
    // 空表达式公式不计入公式数
    expect(other).not.toHaveTextContent('2 个公式')
    expect(other).not.toHaveTextContent('当前')
  })

  it('点击展开箭头显示详情（描述 / 数据源 / 更新时间），再点收起', () => {
    renderDrawer()

    expect(screen.queryByTestId('analytics-manager-desc-7')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('analytics-manager-expand-7'))
    const desc = screen.getByTestId('analytics-manager-desc-7')
    expect(desc).toHaveTextContent('按产品看合格率')
    expect(desc).toHaveTextContent('数据源：产品批次')
    expect(desc).toHaveTextContent('更新于')

    fireEvent.click(screen.getByTestId('analytics-manager-expand-7'))
    expect(screen.queryByTestId('analytics-manager-desc-7')).not.toBeInTheDocument()
  })

  it('打开 / 复制按钮回调对应模板', () => {
    const { handlers } = renderDrawer()

    fireEvent.click(screen.getByTestId('analytics-manager-open-7'))
    expect(handlers.onOpenTemplate).toHaveBeenCalledWith(TPL_MAIN)

    fireEvent.click(screen.getByTestId('analytics-manager-duplicate-8'))
    expect(handlers.onDuplicate).toHaveBeenCalledWith(TPL_OTHER)
  })

  it('删除需二次确认，确认后回调 onDelete', async () => {
    const { handlers } = renderDrawer()

    fireEvent.click(screen.getByTestId('analytics-manager-delete-7'))
    // antd Modal.confirm 会同时渲染 .ant-modal-title 与 .ant-modal-confirm-title，取首个定位容器
    const titles = await screen.findAllByText('删除分析「批次合格率分布」？')
    const confirm = titles[0].closest('.ant-modal') as HTMLElement
    expect(handlers.onDelete).not.toHaveBeenCalled()

    fireEvent.click(within(confirm).getByRole('button', { name: /删\s*除/ }))
    expect(handlers.onDelete).toHaveBeenCalledWith(TPL_MAIN)
  })

  it('新建分析按钮回调 onNew', () => {
    const { handlers } = renderDrawer()
    fireEvent.click(screen.getByTestId('analytics-manager-new'))
    expect(handlers.onNew).toHaveBeenCalledTimes(1)
  })

  it('无已保存分析时展示空态', () => {
    renderDrawer({ templates: [], activeTemplateId: null })
    expect(screen.getByText(/暂无已保存的分析/)).toBeInTheDocument()
    expect(screen.getByTestId('analytics-manager')).toBeInTheDocument()
  })
})
