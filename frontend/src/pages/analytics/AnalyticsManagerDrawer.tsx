/** 分析列表 Drawer —— 已保存分析的浏览 / 打开 / 复制 / 删除 / 新建.
 *
 * 组件只做展示与交互（props 注入、不依赖路由），数据与 mutation 由 AnalyticsPage 编排：
 * - 打开：交给页面复用现有「未保存修改」确认逻辑；
 * - 复制：调用 duplicateTemplate，成功后刷新模板列表并打开副本；
 * - 删除：组件内二次确认（与页面删除入口语义一致）后交给页面删除。
 */

import { useState } from 'react'
import { App as AntApp, Button, Drawer, Empty, List, Space, Tag, Tooltip, Typography } from 'antd'
import {
  CaretRightOutlined,
  CopyOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import type { AnalyticsTemplate } from '@/api/analytics'
import { templateTableName } from './analyticsModel'
import { WEIGHT } from '@/theme/tokens'

const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
  /** 全部已保存分析 */
  templates: AnalyticsTemplate[]
  /** 工作区数据表（用于展示数据源表名） */
  tables: Array<{ id: number | string; name: string }>
  activeTemplateId: number | null
  /** 当前编辑态是否有未保存修改（用于「当前 + 未保存」标记） */
  dirty?: boolean
  duplicating?: boolean
  deleting?: boolean
  /** 打开分析（页面负责未保存确认） */
  onOpenTemplate: (template: AnalyticsTemplate) => void
  onDuplicate: (template: AnalyticsTemplate) => void
  /** 已二次确认的删除回调 */
  onDelete: (template: AnalyticsTemplate) => void
  onNew: () => void
}

/** 已保存分析的公式条数（忽略空键名 / 空表达式） */
function formulaCount(template: AnalyticsTemplate): number {
  return (template.config?.formulas ?? []).filter(f => f?.key?.trim() && f?.expr?.trim()).length
}

function formatUpdatedAt(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

export function AnalyticsManagerDrawer({
  open,
  onClose,
  templates,
  tables,
  activeTemplateId,
  dirty = false,
  duplicating = false,
  deleting = false,
  onOpenTemplate,
  onDuplicate,
  onDelete,
  onNew,
}: Props) {
  const { modal } = AntApp.useApp()
  /** 展开详情（描述 / 更新时间）的模板 id 集合 */
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const toggleExpanded = (id: number) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const confirmDelete = (template: AnalyticsTemplate) => {
    modal.confirm({
      title: `删除分析「${template.name}」？`,
      content: '删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => onDelete(template),
    })
  }

  return (
    <Drawer
      title={
        <Space>
          <span>分析列表</span>
          <Text type="secondary" style={{ fontSize: 12, fontWeight: WEIGHT.regular }}>共 {templates.length} 个</Text>
        </Space>
      }
      width={560}
      open={open}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          data-testid="analytics-manager-new"
          onClick={onNew}
        >
          新建分析
        </Button>
      }
    >
      <div data-testid="analytics-manager">
        {templates.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无已保存的分析，点击右上角「新建分析」开始"
          />
        ) : (
          <List
            dataSource={templates}
            rowKey={template => template.id}
            renderItem={template => {
              const isActive = template.id === activeTemplateId
              const updatedAt = formatUpdatedAt(template.updated_at)
              const expanded = expandedIds.has(template.id)
              return (
                <List.Item
                  data-testid={`analytics-manager-item-${template.id}`}
                  style={{
                    display: 'block',
                    marginBottom: 8,
                    padding: '6px 12px',
                    border: '1px solid var(--cn-border-soft, #d1d5db)',
                    borderRadius: 8,
                  }}
                >
                  {/* 紧凑主行：展开箭头 + 名称 / 标记 / 内联摘要 + 操作 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, minHeight: 28 }}>
                    <Tooltip title={expanded ? '收起详情' : '展开详情（描述 / 更新时间）'}>
                      <Button
                        type="text"
                        size="small"
                        aria-label={expanded ? `收起详情 ${template.name}` : `展开详情 ${template.name}`}
                        data-testid={`analytics-manager-expand-${template.id}`}
                        icon={
                          <CaretRightOutlined
                            rotate={expanded ? 90 : 0}
                            style={{ color: 'rgba(0,0,0,0.45)' }}
                          />
                        }
                        onClick={() => toggleExpanded(template.id)}
                      />
                    </Tooltip>
                    <Space size={4} style={{ flex: 1, minWidth: 0 }}>
                      <span
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          fontWeight: isActive ? WEIGHT.medium : WEIGHT.regular,
                        }}
                      >
                        {template.name}
                      </span>
                      {isActive && <Tag color="blue">当前</Tag>}
                      {isActive && dirty && <Tag color="orange">未保存</Tag>}
                      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                        {templateTableName(tables, template.table_id)} · {formulaCount(template)} 个公式
                      </Text>
                    </Space>
                    <Space size={0}>
                      <Tooltip title="打开该分析">
                        <Button
                          type="link"
                          size="small"
                          icon={<FolderOpenOutlined />}
                          data-testid={`analytics-manager-open-${template.id}`}
                          onClick={() => onOpenTemplate(template)}
                        >
                          打开
                        </Button>
                      </Tooltip>
                      <Tooltip title="复制为新分析（默认「原名 副本」）">
                        <Button
                          type="link"
                          size="small"
                          icon={<CopyOutlined />}
                          loading={duplicating}
                          data-testid={`analytics-manager-duplicate-${template.id}`}
                          onClick={() => onDuplicate(template)}
                        >
                          复制
                        </Button>
                      </Tooltip>
                      <Tooltip title="删除后不可恢复">
                        <Button
                          type="link"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          loading={deleting}
                          data-testid={`analytics-manager-delete-${template.id}`}
                          onClick={() => confirmDelete(template)}
                        >
                          删除
                        </Button>
                      </Tooltip>
                    </Space>
                  </div>
                  {/* 展开详情：描述 + 更新时间 */}
                  {expanded && (
                    <div
                      data-testid={`analytics-manager-desc-${template.id}`}
                      style={{ padding: '2px 0 4px 32px' }}
                    >
                      {template.description ? (
                        <div style={{ marginBottom: 2 }}>{template.description}</div>
                      ) : null}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        数据源：{templateTableName(tables, template.table_id)}
                        {updatedAt ? ` · 更新于 ${updatedAt}` : ''}
                      </Text>
                    </div>
                  )}
                </List.Item>
              )
            }}
          />
        )}
      </div>
    </Drawer>
  )
}

export default AnalyticsManagerDrawer
