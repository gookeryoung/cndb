/** 装配大纲 → antd Tree 节点（ADR 0083 D7；ADR 0109 D2 / D5）.
 *
 * 「设计结构」根页右栏（DesignsPage）与编辑器侧栏（DesignStructureNav）共用这一套
 * 图标 / 标题 / 类型与行号描述的映射，避免两处树形口径漂移；
 * 纯展示层，数据仍来自 `designOutline.ts` 的纯函数映射（ADR 0083 D3 / D4）。
 */

import { Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  ApartmentOutlined, AppstoreOutlined, ClusterOutlined, NodeIndexOutlined,
} from '@ant-design/icons'
import type { DesignTreeEntry, DesignTreeMeta } from './designOutline'

const { Text } = Typography

/** 大纲节点图标：系统 / 组件 / 分组 / 零件各一类（设计根用工具图标） */
export const ENTRY_ICONS = {
  system: ApartmentOutlined,
  assembly: ClusterOutlined,
  group: NodeIndexOutlined,
  part: AppstoreOutlined,
} as const

export interface DesignTreeDataNode extends DataNode {
  meta?: DesignTreeMeta
  children?: DesignTreeDataNode[]
}

/** 大纲条 → antd Tree 节点（标题 + 类型 / 行号 / 零件数描述） */
export function entryToTreeNode(entry: DesignTreeEntry): DesignTreeDataNode {
  const Icon = ENTRY_ICONS[entry.meta.type as keyof typeof ENTRY_ICONS]
  return {
    key: entry.key,
    meta: entry.meta,
    isLeaf: entry.isLeaf,
    icon: <Icon />,
    title: (
      <span className="cn-design-outline-title" data-testid={`design-outline-node-${entry.key}`}>
        <span>{entry.title}</span>
        <Text type="secondary" className="cn-design-outline-detail">{entry.detail}</Text>
      </span>
    ),
    children: entry.children?.map(entryToTreeNode),
  }
}

export default entryToTreeNode
