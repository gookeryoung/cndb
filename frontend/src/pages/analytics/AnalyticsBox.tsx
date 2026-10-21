/** GitHub 风格分区盒子 —— 数据分析页配置区 / 结果区的统一容器.
 *
 * 为什么不用 antd Card：Card 的 48px 头部 + 16px 内边距在「配置密集 + 右侧结果」的
 * 双栏页面里过于松散，一屏放不下三个分区。这里压到 30px 标题条 / 8px 内边距，
 * 1px 边框 + 6px 圆角 + 浅底标题条 + 无阴影，与 GitHub 的方盒语言一致，
 * 颜色全部走 var(--cn-*)，随主题（浅色 / 深色）自适应。
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
  children: ReactNode
  testId?: string
  className?: string
}

export function AnalyticsBox({ title, icon, extra, footer, children, testId, className }: Props) {
  return (
    <section className={className ? `cn-an-box ${className}` : 'cn-an-box'} data-testid={testId}>
      <header className="cn-an-box-head">
        {icon ? <span className="cn-an-box-icon" aria-hidden>{icon}</span> : null}
        <h3 className="cn-an-box-title">{title}</h3>
        {extra ? <div className="cn-an-box-extra">{extra}</div> : null}
      </header>
      <div className="cn-an-box-body">
        {children}
        {footer ? <div className="cn-an-box-foot">{footer}</div> : null}
      </div>
    </section>
  )
}

export default AnalyticsBox
