/** 插入图表弹窗（ADR 0048）：模板两级浏览 + 已有实例列表.
 *
 * 页签一「新建图表」：左栏类别分组 → 右侧模板卡片（描述 + 模板默认配置的静态缩略图，
 * 缩略图走 render-preview 不落库）；「基于此模板新建」交给页面打开设计器。
 * 页签二「已有图表」：实例列表直接插入 `{{chart:<id>}}`。
 * 弹窗自身拉取模板与实例清单（React Query，open 时启用），页面只接回调。
 */

import { useMemo } from 'react'
import { Button, Empty, List, Modal, Skeleton, Tabs, Tag, Typography } from 'antd'
import { BarChartOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { chartApi } from '@/api/charts'
import type { ChartTemplateInfo } from '@/api/charts'
import { sanitizeSvg } from '@/components/Document/ChartEmbed'

const { Text, Paragraph } = Typography

/** 模板缩略图：用模板默认配置走 render-preview（不落库，D5 同源） */
function TemplateThumb({ workspaceId, template, active }: {
  workspaceId: number
  template: ChartTemplateInfo
  active: boolean
}) {
  const thumbQuery = useQuery({
    queryKey: ['chart-template-thumb', workspaceId, template.key],
    queryFn: () => chartApi.renderPreview(workspaceId, template.key, template.default_config),
    enabled: active,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const svg = useMemo(
    () => (thumbQuery.data ? sanitizeSvg(thumbQuery.data) : ''),
    [thumbQuery.data],
  )
  if (svg) {
    return (
      <div
        data-testid={`chart-template-thumb-${template.key}`}
        style={{ height: 110, overflow: 'hidden', borderRadius: 4, border: '1px solid var(--cn-border, #eee)', lineHeight: 0 }}
        // 后端唯一渲染器产出 + sanitizeSvg 清洗
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    )
  }
  if (thumbQuery.isLoading) return <Skeleton.Image active style={{ width: '100%', height: 110 }} />
  return (
    <div
      style={{
        height: 110,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: '1px dashed var(--cn-border, #ddd)',
        borderRadius: 4,
        color: 'var(--cn-text-secondary, #999)',
      }}
    >
      <BarChartOutlined style={{ fontSize: 28 }} />
    </div>
  )
}

export default function InsertChartModal({
  open,
  workspaceId,
  onCancel,
  onPickExisting,
  onPickTemplate,
}: {
  open: boolean
  workspaceId: number
  onCancel: () => void
  /** 页签二：选中已有实例，页面插入 `{{chart:<id>}}` */
  onPickExisting: (chartId: number) => void
  /** 页签一：选中模板，页面关闭本弹窗并打开设计器 */
  onPickTemplate: (templateKey: string) => void
}) {
  const templatesQuery = useQuery({
    queryKey: ['chart-templates', workspaceId],
    queryFn: () => chartApi.templates(workspaceId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })

  const chartsQuery = useQuery({
    queryKey: ['charts', workspaceId, 'list'],
    queryFn: () => chartApi.list(workspaceId),
    enabled: open,
  })

  // 稳定引用：undefined 数据兜底为同一空数组语义，避免 useMemo deps 每渲染变化
  const categories = useMemo(() => templatesQuery.data?.categories ?? [], [templatesQuery.data])
  const templates = useMemo(() => templatesQuery.data?.templates ?? [], [templatesQuery.data])
  const charts = useMemo(() => chartsQuery.data?.items ?? [], [chartsQuery.data])

  /** 类别 → 模板分组（保持注册表顺序） */
  const grouped = useMemo(
    () => categories.map(cat => ({
      cat,
      templates: templates.filter(t => t.category === cat.key),
    })),
    [categories, templates],
  )

  return (
    <Modal
      title="插入图表"
      open={open}
      onCancel={onCancel}
      footer={<Button onClick={onCancel}>取消</Button>}
      width={720}
      destroyOnHidden
    >
      <Tabs
        defaultActiveKey="new"
        items={[
          {
            key: 'new',
            label: '新建图表',
            children: (
              <div style={{ maxHeight: 420, overflowY: 'auto' }}>
                {templatesQuery.isLoading && <Skeleton active paragraph={{ rows: 4 }} />}
                {templatesQuery.isError && (
                  <Text type="danger">模板清单加载失败，请稍后重试。</Text>
                )}
                {grouped.map(({ cat, templates: tpls }) => (
                  <div key={cat.key} style={{ marginBottom: 16 }}>
                    <Text strong style={{ display: 'block', marginBottom: 8 }}>
                      {cat.name}
                      <Text type="secondary" style={{ fontWeight: 'normal', marginLeft: 8, fontSize: 12 }}>
                        {cat.description}
                      </Text>
                    </Text>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                      {tpls.map(tpl => (
                        <div
                          key={tpl.key}
                          data-testid={`chart-template-card-${tpl.key}`}
                          style={{
                            border: '1px solid var(--cn-border, #e8e8e8)',
                            borderRadius: 8,
                            padding: 12,
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 8,
                          }}
                        >
                          <TemplateThumb workspaceId={workspaceId} template={tpl} active={open} />
                          <Text strong>{tpl.name}</Text>
                          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }} ellipsis={{ rows: 2 }}>
                            {tpl.description}
                          </Paragraph>
                          <Button
                            size="small"
                            type="primary"
                            ghost
                            icon={<PlusOutlined />}
                            data-testid={`chart-template-pick-${tpl.key}`}
                            onClick={() => onPickTemplate(tpl.key)}
                          >
                            基于此模板新建
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'existing',
            label: `已有图表${charts.length > 0 ? ` (${charts.length})` : ''}`,
            children: (
              <div style={{ maxHeight: 420, overflowY: 'auto' }}>
                {chartsQuery.isLoading && <Skeleton active paragraph={{ rows: 4 }} />}
                {!chartsQuery.isLoading && charts.length === 0 && (
                  <Empty description="工作区还没有图表，先在「新建图表」里创建一个" />
                )}
                <List
                  dataSource={charts}
                  renderItem={item => (
                    <List.Item
                      data-testid={`chart-existing-item-${item.id}`}
                      actions={[
                        <Button
                          key="insert"
                          size="small"
                          type="primary"
                          data-testid={`chart-existing-insert-${item.id}`}
                          onClick={() => onPickExisting(item.id)}
                        >
                          插入
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <span>
                            {item.title}
                            {item.category && (
                              <Tag style={{ marginLeft: 8 }}>
                                {categories.find(c => c.key === item.category)?.name ?? item.category}
                              </Tag>
                            )}
                          </span>
                        }
                        description={
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            更新于 {item.updated_at.slice(0, 10)}
                          </Text>
                        }
                      />
                    </List.Item>
                  )}
                />
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}
