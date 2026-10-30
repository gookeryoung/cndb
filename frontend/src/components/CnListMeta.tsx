/** 自绘列表内容层（ADR 0074：antd List 组件弃用 → Listy + 自绘结构）.
 *
 * antd 6.6 弃用 `List`（v7 移除，官方推荐 Listy）。Listy 只提供列表骨架
 * （`.ant-listy-item` 的内边距 / 分隔线 / hover 走 token + cssinjs 兼容链），
 * 不含 `List.Item.Meta`；本组件按 v5 Meta 视觉口径自绘内容层，
 * 各列表站点共用，配套样式见 index.css 的 `.cn-list-*` 类。
 */
import type { ReactNode } from 'react'

export interface CnListMetaProps {
  /** 行首头像位（v5 List.Item.Meta avatar）：图标 / 勾选框等 */
  avatar?: ReactNode
  /** 标题行 */
  title: ReactNode
  /** 描述行（可省略） */
  description?: ReactNode
}

export default function CnListMeta({ avatar, title, description }: CnListMetaProps) {
  return (
    <div className="cn-list-meta">
      {avatar != null && <div className="cn-list-avatar">{avatar}</div>}
      <div className="cn-list-meta-content">
        <div className="cn-list-meta-title">{title}</div>
        {description != null && (
          <div className="cn-list-meta-description">{description}</div>
        )}
      </div>
    </div>
  )
}
