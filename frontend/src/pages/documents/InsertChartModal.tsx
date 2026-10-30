/** 插入图表弹窗（ADR 0048 / 0052 / 0058）：新建页签多级列表 + 图表素材库复制插入.
 *
 * 页签一「新建图表」（ADR 0058 / 需求卡片 0073）：左栏 antd Collapse 手风琴（一级分类常显、点开展开
 * 二级分类与模板项；同结构的主题变体模板合并为一个规范条目，主题选择移入设计器），
 * 右栏仅显示选中模板详情（大图预览走 render-preview 不落库且完整
 * 高度展示，未选中为空态不发请求）；「基于此模板新建」固定在弹窗底部「取消」左侧。
 * 页签二「已有图表」：素材库条目**复制定义**插入正文（不随素材库更新，D4）。
 * 弹窗自身拉取模板与素材库清单（React Query，open 时启用），页面只接回调。
 */

import { useMemo, useState } from 'react'
import { Button, Collapse, Empty, Listy, Modal, Skeleton, Tabs, Tag, Typography } from 'antd'
import { BarChartOutlined, PlusOutlined } from '@ant-design/icons'
import CnListMeta from '@/components/CnListMeta'
import { useQuery } from '@tanstack/react-query'
import { chartApi } from '@/api/charts'
import type { ChartInstance, ChartTemplateInfo } from '@/api/charts'
import { sanitizeSvg } from '@/components/Document/ChartEmbed'

const { Text, Paragraph } = Typography

/** 模板预览图：用模板默认配置走 render-preview（不落库，D5 同源；仅 active 时请求）.
 *
 * SVG 按原图比例完整展示（不裁剪高度）；height 仅约束加载骨架 / 失败占位。
 */
function TemplateThumb({ workspaceId, template, active, height = 220 }: {
  workspaceId: number
  template: ChartTemplateInfo
  active: boolean
  height?: number
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
        style={{ borderRadius: 4, border: '1px solid var(--cn-border, #eee)', lineHeight: 0, overflow: 'hidden' }}
        // 后端唯一渲染器产出 + sanitizeSvg 清洗；SVG 自带 viewBox + width=100%，按比例自动撑满高度
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    )
  }
  if (thumbQuery.isLoading) return <Skeleton.Image active style={{ width: '100%', height }} />
  return (
    <div
      style={{
        height,
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

/** 左栏一个模板项（选中态高亮，选中后右栏出预览） */
function TemplateItem({ template, selected, onSelect }: {
  template: ChartTemplateInfo
  selected: boolean
  onSelect: (key: string) => void
}) {
  return (
    <Button
      block
      type={selected ? 'primary' : 'text'}
      ghost={selected}
      style={{ justifyContent: 'flex-start', paddingLeft: 8, textAlign: 'left' }}
      data-testid={`chart-template-item-${template.key}`}
      onClick={() => onSelect(template.key)}
    >
      {template.name}
    </Button>
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
  /** 页签二：选中素材库图表，页面复制其定义插入正文 */
  onPickExisting: (chart: ChartInstance) => void
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

  // 全部层级拍平（一级 + 二级），素材库 Tag 与模板归类查找用
  const flatCategories = useMemo(
    () => categories.flatMap(cat => (cat.children?.length ? [cat, ...cat.children] : [cat])),
    [categories],
  )

  // 新建列表按结构合并主题变体（需求卡片 0073）：variant_of 指向所属类型的变体不展示；
  // 变体仍留在 templates 里供设计器编辑存量实例
  const visibleTemplates = useMemo(() => templates.filter(t => !t.variant_of), [templates])

  /** 一级分类 → 模板分组（含二级；保持注册表顺序，空分类不输出） */
  const grouped = useMemo(
    () =>
      categories
        .map(cat => {
          const direct = visibleTemplates.filter(t => t.category === cat.key)
          const byChild = (cat.children ?? [])
            .map(child => ({ child, templates: visibleTemplates.filter(t => t.category === child.key) }))
            .filter(g => g.templates.length > 0)
          if (direct.length === 0 && byChild.length === 0) return null
          return { cat, direct, byChild }
        })
        .filter((g): g is NonNullable<typeof g> => g !== null),
    [categories, visibleTemplates],
  )

  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null)
  const selectedTemplate = useMemo(
    () => templates.find(t => t.key === selectedTemplateKey) ?? null,
    [templates, selectedTemplateKey],
  )

  /** 手风琴默认展开第一个含模板的一级分类，但不自动选中模板（ADR 0058 边界 1） */
  const defaultExpandKey = grouped[0]?.cat.key

  /** 底部操作区：「基于此模板新建」固定在「取消」左侧（未选中模板时仅取消） */
  const footer = selectedTemplate ? (
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
      <Button
        type="primary"
        icon={<PlusOutlined />}
        data-testid={`chart-template-pick-${selectedTemplate.key}`}
        onClick={() => onPickTemplate(selectedTemplate.key)}
      >
        基于此模板新建
      </Button>
      <Button onClick={onCancel}>取消</Button>
    </div>
  ) : (
    <Button onClick={onCancel}>取消</Button>
  )

  return (
    <Modal
      title="插入图表"
      open={open}
      onCancel={onCancel}
      footer={footer}
      className="cn-insert-chart-modal"
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
              <div style={{ display: 'flex', gap: 12, height: 420 }}>
                {/* 左栏：多级列表手风琴（一级常显、点开展开二级与模板项） */}
                <div style={{ width: 240, flexShrink: 0, overflowY: 'auto', borderInlineEnd: '1px solid var(--cn-border, #eee)', paddingRight: 8 }} data-testid="chart-template-list">
                  {templatesQuery.isLoading && <Skeleton active paragraph={{ rows: 4 }} />}
                  {templatesQuery.isError && (
                    <Text type="danger">模板清单加载失败，请稍后重试。</Text>
                  )}
                  {!templatesQuery.isLoading && grouped.length === 0 && !templatesQuery.isError && (
                    <Empty description="暂无可用的图表模板" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  )}
                  {grouped.length > 0 && (
                    <Collapse
                      accordion
                      size="small"
                      className="chart-template-collapse"
                      defaultActiveKey={defaultExpandKey ? [defaultExpandKey] : []}
                      items={grouped.map(({ cat, direct, byChild }) => ({
                        key: cat.key,
                        label: (
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <Text strong style={{ fontSize: 13 }}>
                              {cat.name}
                            </Text>
                            <Text type="secondary" style={{ fontSize: 11, fontWeight: 400 }}>
                              {cat.description}
                            </Text>
                          </div>
                        ),
                        children: (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {direct.map(tpl => (
                              <TemplateItem
                                key={tpl.key}
                                template={tpl}
                                selected={selectedTemplateKey === tpl.key}
                                onSelect={setSelectedTemplateKey}
                              />
                            ))}
                            {byChild.map(({ child, templates: tpls }) => (
                              <div key={child.key}>
                                <Text type="secondary" style={{ fontSize: 12, display: 'block', margin: '4px 0 2px' }}>
                                  {child.name}
                                </Text>
                                {tpls.map(tpl => (
                                  <TemplateItem
                                    key={tpl.key}
                                    template={tpl}
                                    selected={selectedTemplateKey === tpl.key}
                                    onSelect={setSelectedTemplateKey}
                                  />
                                ))}
                              </div>
                            ))}
                          </div>
                        ),
                      }))}
                    />
                  )}
                </div>
                {/* 右栏：仅选中模板后展示详情与预览（未选中空态，不发 render-preview） */}
                <div style={{ flex: 1, minWidth: 0, overflowY: 'auto' }} data-testid="chart-template-detail">
                  {!selectedTemplate && (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Empty description="在左侧选择一个模板查看预览" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    </div>
                  )}
                  {selectedTemplate && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <TemplateThumb workspaceId={workspaceId} template={selectedTemplate} active={open} />
                      <Text strong>{selectedTemplate.name}</Text>
                      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
                        {selectedTemplate.description}
                      </Paragraph>
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'existing',
            label: `图表素材库${charts.length > 0 ? ` (${charts.length})` : ''}`,
            children: (
              <div style={{ maxHeight: 420, overflowY: 'auto' }}>
                {chartsQuery.isLoading && <Skeleton active paragraph={{ rows: 4 }} />}
                {!chartsQuery.isLoading && charts.length === 0 && (
                  <Empty description="工作区还没有图表，先在「新建图表」里创建一个" />
                )}
                {/* antd List 弃用（ADR 0074）：Listy + 自绘 Meta / 操作区 */}
                <Listy
                  className="cn-listy-plain"
                  items={charts}
                  rowKey={item => item.id}
                  itemRender={item => (
                    <div className="cn-list-item" data-testid={`chart-existing-item-${item.id}`}>
                      <div className="cn-list-item-main">
                        <CnListMeta
                          title={
                            <span>
                              {item.title}
                              {item.category && (
                                <Tag style={{ marginLeft: 8 }}>
                                  {flatCategories.find(c => c.key === item.category)?.name ?? item.category}
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
                      </div>
                      <div className="cn-list-item-actions">
                        <Button
                          size="small"
                          type="primary"
                          data-testid={`chart-existing-insert-${item.id}`}
                          onClick={() => onPickExisting(item)}
                        >
                          插入
                        </Button>
                      </div>
                    </div>
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
