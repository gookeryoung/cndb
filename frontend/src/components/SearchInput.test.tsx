/** 公共搜索框 SearchInput —— 统一形态口径回归（需求 0068 C1/C2） */
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import SearchInput from './SearchInput'

describe('SearchInput 公共搜索框', () => {
  it('渲染 SearchOutlined prefix 与 allowClear，输入受控回显', () => {
    let value = ''
    const { container, rerender } = render(
      <SearchInput placeholder="过滤标题…" value={value} onChange={e => { value = e.target.value }} />,
    )

    // prefix 图标存在（统一形态 C1）
    expect(container.querySelector('.anticon-search')).not.toBeNull()

    fireEvent.change(screen.getByPlaceholderText('过滤标题…'), { target: { value: '报表' } })
    expect(value).toBe('报表')

    // 受控回显后出现清空按钮（allowClear C1）
    rerender(<SearchInput placeholder="过滤标题…" value={value} onChange={e => { value = e.target.value }} />)
    expect(container.querySelector('.ant-input-clear-icon')).not.toBeNull()
  })

  it('默认 small 尺寸，可通过 size 覆盖（C2）', () => {
    const { container, rerender } = render(<SearchInput data-testid="s1" />)
    expect(container.querySelector('.ant-input-sm')).not.toBeNull()

    rerender(<SearchInput size="middle" data-testid="s2" />)
    expect(container.querySelector('.ant-input-sm')).toBeNull()
  })
})
