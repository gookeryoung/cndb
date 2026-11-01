/** GitHub 风格分区方盒 —— 页面内「标题条 + 内容区」的统一容器.
 *
 * 为什么不用 antd Card：Card 的 48px 头部 + 16px 内边距在「配置密集 + 右侧结果」的
 * 双栏页面里过于松散，一屏放不下三个分区。这里压到 24px 标题条 / 8px 内边距，
 * 1px 边框 + 主题圆角 + 浅底标题条 + 无阴影，与 GitHub 的方盒语言一致，
 * 颜色全部走 var(--cn-*) / --cn-space-*，随主题（浅色 / 深色）自适应。
 *
 * 列表内容用 flush：盒体去内边距，行自带分隔线与 hover，外框由盒子本身承担，
 * 避免「盒子边框 + 内层列表边框」的双层描边。
 */

import type { ReactNode } from 'react'

interface Props {
  title: ReactNode
  /** 标题前的弱化小图标 */
  icon?: ReactNode
  /** 标题右侧操作区（小按钮 / 计数 / 说明） */
  extra?: ReactNode
  /** 底部一行提示（弱化小字，常用于快捷键与口径说明） */
  footer?: ReactNode
  /** 内容区去内边距与间距（列表行贴边、行间分隔线满宽绘制） */
  flush?: boolean
  children: ReactNode
  testId?: string
  className?: string
}

export function SectionBox({
  title,
  icon,
  extra,
  footer,
  flush = false,
  children,
  testId,
  className,
}: Props) {
  const classes = ['cn-box']
  if (flush) classes.push('cn-box--flush')
  if (className) classes.push(className)
  return (
    <section className={classes.join(' ')} data-testid={testId}>
      <header className="cn-box-head">
        {icon ? <span className="cn-box-icon" aria-hidden>{icon}</span> : null}
        <h3 className="cn-box-title">{title}</h3>
        {extra ? <div className="cn-box-extra">{extra}</div> : null}
      </header>
      <div className="cn-box-body">
        {children}
        {footer ? <div className="cn-box-foot">{footer}</div> : null}
      </div>
    </section>
  )
}

export default SectionBox
