/** TooltipDropdown — 触发器带说明 Tooltip 的下拉菜单.
 *
 * 为什么不能直接写 `<Dropdown><Tooltip><Button/></Tooltip></Dropdown>`：
 * 触发器在视口顶部时，Tooltip 的 autoAdjustOverflow 会翻转到按钮**下方**，
 * 正好盖住刚展开的菜单；而 Tooltip 浮层默认可交互（指针移入后保持展开），
 * 于是菜单项被遮挡且点击被浮层拦截 —— E2E `critical/view-field-visibility`
 * 的「重置列宽与列序」用例曾因此稳定 30s 超时。
 *
 * 这里在菜单展开期间强制关闭 Tooltip（菜单收起后恢复悬浮行为），
 * 让菜单项始终可见、可点。
 */

import { useState, type ReactElement, type ReactNode } from 'react'
import { Dropdown, Tooltip } from 'antd'
import type { DropdownProps, TooltipProps } from 'antd'

export interface TooltipDropdownProps {
  /** 悬浮说明文案 */
  title: ReactNode
  /** 下拉菜单配置（items / selectedKeys 等原样透传） */
  menu: DropdownProps['menu']
  /** 触发器（通常是 Button，需能接收 ref） */
  children: ReactElement
  /** 菜单展开方式，默认 click */
  trigger?: DropdownProps['trigger']
  /** 菜单对齐位置（透传 Dropdown） */
  placement?: DropdownProps['placement']
  /** Tooltip 位置；缺省交给 antd 自动选择 */
  tooltipPlacement?: TooltipProps['placement']
}

export default function TooltipDropdown({
  title, menu, children, trigger = ['click'], placement, tooltipPlacement,
}: TooltipDropdownProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [tooltipOpen, setTooltipOpen] = useState(false)

  return (
    <Dropdown
      trigger={trigger}
      menu={menu}
      placement={placement}
      open={menuOpen}
      onOpenChange={setMenuOpen}
    >
      <Tooltip
        title={title}
        placement={tooltipPlacement}
        open={!menuOpen && tooltipOpen}
        onOpenChange={setTooltipOpen}
      >
        {children}
      </Tooltip>
    </Dropdown>
  )
}
