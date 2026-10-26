/** 帮助文档正文原语（ADR 0036）.
 *
 * 层级与样式只在 `HelpDoc` 里落地，内容文件只描述「这一段是什么」：
 * 段落 `P`、要点 `Bullets`、步骤 `Steps`、提示 `Note`、交叉引用 `HelpLink`。
 * 交叉引用走 `helpLink`，让「同一事实只写一遍」在代码里也可执行（链接而非复制段落）。
 */

import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { helpLink } from '../helpNav'

export function P({ children }: { children: ReactNode }) {
    return <p className="cn-help-docs-text">{children}</p>
}

export function Bullets({ items }: { items: ReactNode[] }) {
    return (
        <ul className="cn-help-docs-list">
            {items.map((item, index) => (
                <li key={index}>{item}</li>
            ))}
        </ul>
    )
}

export function Steps({ items }: { items: ReactNode[] }) {
    return (
        <ol className="cn-help-docs-list cn-help-docs-steps">
            {items.map((item, index) => (
                <li key={index}>{item}</li>
            ))}
        </ol>
    )
}

/** 提示块：`tip` 为中性补充，`warn` 为会导致数据 / 权限问题的注意点。 */
export function Note({ children, kind = 'tip' }: { children: ReactNode; kind?: 'tip' | 'warn' }) {
    return (
        <div className={`cn-help-docs-note cn-help-docs-note-${kind}`} role="note">
            {children}
        </div>
    )
}

/** 主题内 / 跨主题交叉引用；`anchor` 传 L3 的 key，需要定位到 L4 时用 `itemAnchor`。 */
export function HelpLink({
    section,
    topic,
    anchor,
    children,
}: {
    section: string
    topic: string
    anchor?: string
    children: ReactNode
}) {
    return (
        <Link className="cn-help-docs-link" to={helpLink(section, topic, anchor)}>
            {children}
        </Link>
    )
}

/** 强调整句（等价于之前用 `Text strong` 的那类写法，但不引入行内 br）。 */
export function Strong({ children }: { children: ReactNode }) {
    return <strong className="cn-help-docs-strong">{children}</strong>
}
