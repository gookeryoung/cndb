import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'

import { renderProviders } from '@/test/render-providers'

import AuthBackgroundSwitcher from './AuthBackgroundSwitcher'

describe('AuthBackgroundSwitcher', () => {
  it('显示当前效果并标注下一组', () => {
    renderProviders(<AuthBackgroundSwitcher effect="flowfield" onSwitch={vi.fn()} />)

    const button = screen.getByTestId('auth-bg-switch')
    expect(button).toHaveAttribute('type', 'button')
    expect(button).toHaveAttribute('data-effect', 'flowfield')
    expect(button).toHaveTextContent('流场粒子')
    expect(button).toHaveAccessibleName('切换登录背景动效：当前流场粒子，下一组宇宙星系')
  })

  it('切到星系后文案同步更新', () => {
    renderProviders(<AuthBackgroundSwitcher effect="galaxy" onSwitch={vi.fn()} />)

    const button = screen.getByTestId('auth-bg-switch')
    expect(button).toHaveAttribute('data-effect', 'galaxy')
    expect(button).toHaveTextContent('宇宙星系')
    expect(button).toHaveAccessibleName('切换登录背景动效：当前宇宙星系，下一组流场粒子')
  })

  it('点击时触发切换', () => {
    const onSwitch = vi.fn()
    renderProviders(<AuthBackgroundSwitcher effect="flowfield" onSwitch={onSwitch} />)

    fireEvent.click(screen.getByTestId('auth-bg-switch'))

    expect(onSwitch).toHaveBeenCalledTimes(1)
  })
})
