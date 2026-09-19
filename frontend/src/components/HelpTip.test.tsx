/** HelpTip 组件测试：Tooltip / Popover 两形态与 placement 透传. */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HelpTip from './HelpTip'
import { renderProviders } from '@/test/render-providers'

describe('HelpTip', () => {
    it('仅传 title 时渲染 Tooltip 形态（问号图标）', async () => {
        renderProviders(<HelpTip title="什么是工作区" />)
        const icon = screen.getByLabelText('帮助')
        expect(icon).toBeInTheDocument()

        // antd Tooltip 悬浮后才渲染内容
        await userEvent.hover(icon)
        expect(await screen.findByText('什么是工作区')).toBeInTheDocument()
    })

    it('title + content 时渲染 Popover 形态（点击展开长说明）', async () => {
        renderProviders(<HelpTip title="匹配键" content="upsert 时用于判断两行是否为同一行的字段组合" />)
        const icon = screen.getByLabelText('帮助')

        // Popover 是点击触发，悬浮不展开
        await userEvent.hover(icon)
        expect(screen.queryByText(/判断两行是否为同一行/)).not.toBeInTheDocument()

        await userEvent.click(icon)
        expect(await screen.findByText('匹配键')).toBeInTheDocument()
        expect(screen.getByText(/判断两行是否为同一行/)).toBeInTheDocument()
    })

    it('placement 透传（渲染不报错即可）', () => {
        const { container } = renderProviders(<HelpTip title="提示" placement="bottomLeft" />)
        expect(container.querySelector('[aria-label="帮助"]')).toBeInTheDocument()
    })
})
