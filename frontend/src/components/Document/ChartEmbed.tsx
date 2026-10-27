/**
 * 图表引用只读嵌入 — 文档预览中渲染 `{{chart:…}}` 占位（ADR 0048）。
 *
 * 按实例 ID 拉取后端唯一渲染器产出的 SVG（ETag 304 复用），清洗后**内联**渲染
 * （对齐 HelpFigure：内联而非 <img>，让 SVG 跟随明暗主题）。实例不存在 /
 * 无权限时降级为占位提示（D7：单段降级，不阻断整篇预览）。
 */

import { useMemo } from 'react'
import { Alert, Button, Skeleton, Space } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { chartApi } from '@/api/charts'
import publicShareApi from '@/api/publicShare'
import RefWidthControl from './RefWidthControl'
import { DEFAULT_REF_WIDTH, parseRefWidth } from './refWidth'

/** 防御性清洗：后端产出不含脚本，仍去掉 `<script>` 与行内事件属性 */
export function sanitizeSvg(svg: string): string {
  return svg
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son[a-z]+\s*=\s*'[^']*'/gi, '')
}

export default function ChartEmbed({ workspaceId, chartId, shareToken, onEditChart, width, refOrdinal, onWidthChange }: {
  /** 工作区 ID（成员模式）；游客分享模式（shareToken）下不传 */
  workspaceId?: number
  chartId: number
  /** 游客分享 token（ADR 0048 D9）：提供后走免登录匿名渲染端点 */
  shareToken?: string
  /** 编辑入口（写权限由页面侧判断后传入）；不传不渲染（ADR 0042 模式） */
  onEditChart?: (chartId: number) => void
  /** 显示宽度百分比，缺省 / 非法回退 75（ADR 0051） */
  width?: number
  /** 同图表在正文中的出现序号（0 基），用于宽度控件定位 */
  refOrdinal?: number
  /** 宽度调整回调；不传不渲染控件（查看 / 游客只读） */
  onWidthChange?: (width: number) => void
}) {
  const pct = parseRefWidth(width ?? DEFAULT_REF_WIDTH)
  const isPublic = Boolean(shareToken)
  const svgQuery = useQuery({
    queryKey: isPublic
      ? ['chart-embed-public', shareToken, chartId]
      : ['chart-embed', workspaceId, chartId],
    queryFn: () =>
      isPublic ? publicShareApi.chartSvg(shareToken!, chartId) : chartApi.renderSvg(workspaceId!, chartId),
    enabled: isPublic
      ? Boolean(shareToken) && Number.isFinite(chartId)
      : Number.isFinite(workspaceId) && Number.isFinite(chartId),
    // 失效由 ETag / 实例编辑后手动失效处理；失败先降级提示，避免长时间骨架屏
    retry: false,
    staleTime: 60 * 1000,
  })

  const svg = useMemo(() => (svgQuery.data ? sanitizeSvg(svgQuery.data) : ''), [svgQuery.data])

  return (
    <figure
      style={{ margin: '0.8em 0', width: `${pct}%`, maxWidth: '100%' }}
      data-testid={`chart-embed-${chartId}`}
      data-width={pct}
    >
      {svg ? (
        <div
          data-testid={`chart-embed-svg-${chartId}`}
          style={{ lineHeight: 0, maxWidth: '100%', overflowX: 'auto' }}
          // 后端唯一渲染器产出 + sanitizeSvg 清洗，无脚本无外链
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : svgQuery.isLoading ? (
        <div data-testid={`chart-embed-loading-${chartId}`}>
          <Skeleton active title={false} paragraph={{ rows: 4 }} />
        </div>
      ) : (
        <Alert
          type="warning"
          showIcon
          message="图表引用无效"
          description={`图表 #${chartId} 不存在或无访问权限，请检查占位符 {{chart:${chartId}}} 中的图表 ID。`}
          style={{ margin: '0.8em 0' }}
        />
      )}
      {svg && (onEditChart || onWidthChange) && (
        <Space size={4} wrap style={{ marginTop: 4 }}>
          {onWidthChange && (
            <RefWidthControl
              value={pct}
              onChange={onWidthChange}
              testId={`chart-embed-width-${chartId}-${refOrdinal ?? 0}`}
            />
          )}
          {onEditChart && (
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              data-testid={`chart-embed-edit-${chartId}`}
              onClick={() => onEditChart(chartId)}
            >
              编辑图表
            </Button>
          )}
        </Space>
      )}
    </figure>
  )
}
