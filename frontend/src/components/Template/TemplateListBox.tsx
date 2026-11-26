/** 模板清单方盒（ADR 0177 C4）—— 两类模板共用的左栏骨架.
 *
 * 导出模板与内容模板的右侧编辑器完全不同，但左侧「模板清单」是同一套：
 * `SectionBox flush` + 计数 + 行列表（选中态由行自己给）。这里只抽这一层的
 * 外壳与空态，**不抽数据与业务**（D5：公共层不引入 `kind` 分支）。
 *
 * 分组折叠由调用方决定：它把分组标题与行一起作为 `children` 传进来即可。
 */

import type { ReactNode } from 'react'

import SectionBox from '@/components/SectionBox'

export interface TemplateListBoxProps {
  /** 方盒标题（默认「模板清单」） */
  title?: string
  icon: ReactNode
  /** 计数展示（右上角「N 个」） */
  count: number
  /** 方盒 testId（两页各自沿用既有 testId，便于既有用例不改） */
  testId: string
  /** 清单为空时的节点（含引导动作）；有 `children` 时不渲染 */
  empty?: ReactNode
  children?: ReactNode
}

export default function TemplateListBox({
  title = '模板清单',
  icon,
  count,
  testId,
  empty,
  children,
}: TemplateListBoxProps) {
  return (
    <SectionBox title={title} icon={icon} extra={<span>{count} 个</span>} flush testId={testId}>
      {count === 0 && empty ? empty : children}
    </SectionBox>
  )
}
