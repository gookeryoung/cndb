/** HelpTip — 统一的「问号图标 + 说明」组件，用于表单标签旁、设置项旁、专业概念旁.
 *
 * - 仅传 title：渲染 Tooltip 短文案
 * - 同时传 content：渲染 Popover，点击图标展开长说明（适合多行解释）
 * - 颜色/尺寸走主题变量，5 套主题（含暗色）下自动适配
 */

import type { ReactNode } from 'react'
import { Popover, Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export interface HelpTipProps {
    /** 短说明（Tooltip 悬浮文案） */
    title: ReactNode
    /** 长说明（有值时改为 Popover 点击展开） */
    content?: ReactNode
    /** 弹出位置，默认 top */
    placement?: 'top' | 'bottom' | 'left' | 'right' | 'topLeft' | 'topRight' | 'bottomLeft' | 'bottomRight'
}

export default function HelpTip({ title, content, placement = 'top' }: HelpTipProps) {
    const icon = (
        <QuestionCircleOutlined
            aria-label="帮助"
            style={{
                fontSize: 14,
                color: 'var(--cn-text-muted)',
                cursor: 'help',
                marginLeft: 4,
            }}
        />
    )

    if (content != null) {
        return (
            <Popover
                content={content}
                title={title}
                trigger="click"
                placement={placement}
            >
                {icon}
            </Popover>
        )
    }

    return (
        <Tooltip title={title} placement={placement}>
            {icon}
        </Tooltip>
    )
}
