/** RefWidthControl：宽度展示 / 预设 / 自定义 / 非法值归一（ADR 0051）. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderProviders } from '@/test/render-providers'
import RefWidthControl from './RefWidthControl'

describe('RefWidthControl', () => {
  it('展示当前宽度；选择预设透传百分比并收起浮层', async () => {
    const onChange = vi.fn()
    renderProviders(<RefWidthControl value={75} onChange={onChange} testId="w" />)

    expect(screen.getByTestId('w')).toHaveTextContent('宽度 75%')
    fireEvent.click(screen.getByTestId('w'))
    fireEvent.click(await screen.findByTestId('w-preset-25'))
    expect(onChange).toHaveBeenCalledWith(25)
  })

  it('自定义输入超界被钳制到上限 100', async () => {
    const onChange = vi.fn()
    renderProviders(<RefWidthControl value={50} onChange={onChange} testId="w" />)

    fireEvent.click(screen.getByTestId('w'))
    const input = (await screen.findByTestId('w-custom')) as HTMLInputElement
    fireEvent.change(input, { target: { value: '120' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenLastCalledWith(100)
  })
})
