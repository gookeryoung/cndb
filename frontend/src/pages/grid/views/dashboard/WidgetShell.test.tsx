/** WidgetShell 四态渲染测试（错误 > 加载 > 空 > 内容）. */
import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import WidgetShell from './WidgetShell'

describe('WidgetShell', () => {
  it('正常渲染标题与内容', () => {
    renderProviders(
      <WidgetShell title="销售额" testId="w">
        <div>42</div>
      </WidgetShell>,
    )
    expect(screen.getByTestId('w-title')).toHaveTextContent('销售额')
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('错误态覆盖内容', () => {
    renderProviders(
      <WidgetShell title="销售额" error="加载失败" testId="w">
        <div>42</div>
      </WidgetShell>,
    )
    expect(screen.getByTestId('w-error')).toHaveTextContent('加载失败')
    expect(screen.queryByText('42')).not.toBeInTheDocument()
  })

  it('加载态优先于空态', () => {
    renderProviders(
      <WidgetShell loading empty testId="w">
        <div>42</div>
      </WidgetShell>,
    )
    expect(screen.getByTestId('w-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('w-empty')).not.toBeInTheDocument()
  })

  it('空态显示自定义文案', () => {
    renderProviders(
      <WidgetShell empty emptyText="暂无订单" testId="w">
        <div>42</div>
      </WidgetShell>,
    )
    expect(screen.getByTestId('w-empty')).toHaveTextContent('暂无订单')
  })
})
