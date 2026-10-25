/** 分析列表 Drawer —— 已保存分析的浏览 / 打开 / 复制 / 删除 / 新建.
 *
 * 组件只做展示与交互（props 注入、不依赖路由），数据与 mutation 由 AnalyticsPage 编排：
 * - 打开：交给页面复用现有「未保存修改」确认逻辑；
 * - 复制：调用 duplicateTemplate，成功后刷新模板列表并打开副本；
 * - 删除：组件内二次确认（与页面删除入口语义一致）后交给页面删除。
 */

import { App as AntApp, Button, Drawer, Empty, List, Space, Tag, Tooltip, Typography } from 'antd'
import { CopyOutlined, DeleteOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
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
              return (
                <List.Item
                  data-testid={`analytics-manager-item-${template.id}`}
                  actions={[
                    <Tooltip key="open" title="打开该分析">
                      <Button
                        type="link"
                        size="small"
                        icon={<FolderOpenOutlined />}
                        data-testid={`analytics-manager-open-${template.id}`}
                        onClick={() => onOpenTemplate(template)}
                      >
                        打开
                      </Button>
                    </Tooltip>,
                    <Tooltip key="duplicate" title="复制为新分析（默认「原名 副本」）">
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
                    </Tooltip>,
                    <Tooltip key="delete" title="删除后不可恢复">
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
                    </Tooltip>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap size={4}>
                        <span>{template.name}</span>
                        {isActive && <Tag color="blue">当前</Tag>}
                        {isActive && dirty && <Tag color="orange">未保存</Tag>}
                      </Space>
                    }
                    description={
                      <div data-testid={`analytics-manager-desc-${template.id}`}>
                        {template.description ? (
                          <div style={{ marginBottom: 2 }}>{template.description}</div>
                        ) : null}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          数据源：{templateTableName(tables, template.table_id)}
                          {' · '}
                          {formulaCount(template)} 个公式
                          {updatedAt ? ` · 更新于 ${updatedAt}` : ''}
                        </Text>
                      </div>
                    }
                  />
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
