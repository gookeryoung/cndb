/** 背景切换器测试（ADR 0016 D3 / D8）：原生按钮、循环切换、键盘可达 */

import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { renderProviders } from '@/test/render-providers'

import AuthBackgroundSwitcher from './AuthBackgroundSwitcher'

describe('AuthBackgroundSwitcher', () => {
  it('展示当前风格并提示下一组', () => {
    renderProviders(<AuthBackgroundSwitcher value="constellation" onChange={vi.fn()} />)

    const button = screen.getByRole('button', { name: /当前 星座/ })
    expect(button).toHaveTextContent('星座')
    expect(button).toHaveAttribute('title', '当前背景：星座，点击切换')
  })

  it('点击回调循环到下一组', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderProviders(<AuthBackgroundSwitcher value="rain" onChange={onChange} />)

    await user.click(screen.getByRole('button'))

    expect(onChange).toHaveBeenCalledWith('orbs')
  })

  it('末尾风格回到星座', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderProviders(<AuthBackgroundSwitcher value="orbs" onChange={onChange} />)

    await user.click(screen.getByRole('button'))

    expect(onChange).toHaveBeenCalledWith('constellation')
  })

  it('可键盘聚焦并用回车切换', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderProviders(<AuthBackgroundSwitcher value="nebula" onChange={onChange} />)

    await user.tab()
    const button = screen.getByRole('button')
    expect(button).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(onChange).toHaveBeenCalledWith('aurora')
  })
})
