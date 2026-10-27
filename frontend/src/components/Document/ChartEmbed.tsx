/**
 * 图表内嵌块只读嵌入（ADR 0052 D3）：正文配置 → 后端唯一渲染器 SVG.
 *
 * 成员走工作区 render-preview、游客走分享 token 的 render-preview；渲染入参是
 * 块内定义的 template + config，不再按实例 ID 查库。坏块 / 模板下线 / 请求失败
 * 一律**单块降级**为提示，不阻断整篇（I5）。
 */

import { useMemo } from 'react'
import { Alert, Button, Skeleton, Space } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { chartApi } from '@/api/charts'
import publicShareApi from '@/api/publicShare'
import RefWidthControl from './RefWidthControl'
import { chartBlockErrorText, type ChartBlock, type ChartBlockSpec } from './chartBlock'
import { DEFAULT_REF_WIDTH, parseRefWidth } from './refWidth'

/** 防御性清洗：后端产出不含脚本，仍去掉 `<script>` 与行内事件属性 */
export function sanitizeSvg(svg: string): string {
  return svg
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son[a-z]+\s*=\s*'[^']*'/gi, '')
}

/** 定义指纹（仅用于渲染缓存键，规则：字段固定顺序的 JSON） */
function specCacheKey(spec: ChartBlockSpec | null): string {
  if (!spec) return ''
  return JSON.stringify([spec.templateKey, spec.width, spec.config])
}

export default function ChartEmbed({ workspaceId, block, shareToken, onEditChart, width, refOrdinal, onWidthChange }: {
  /** 工作区 ID（成员模式）；游客分享模式（shareToken）下不传 */
  workspaceId?: number
  /** 正文图表块：`spec` 为空时按 `error` 降级，不发请求 */
  block: ChartBlock
  /** 游客分享 token（ADR 0052 D10）：提供后走免登录匿名渲染端点 */
  shareToken?: string
  /** 编辑入口（写权限由页面侧判断后传入）；入参为定义与出现序号 */
  onEditChart?: (spec: ChartBlockSpec, occurrence: number) => void
  /** 显示宽度百分比（块字段，缺省 / 非法回退 75） */
  width?: number
  /** 同一定义在正文中的出现序号（0 基），用于编辑 / 宽度控件定位 */
  refOrdinal?: number
  /** 宽度调整回调；不传不渲染控件（查看 / 游客只读） */
  onWidthChange?: (width: number) => void
}) {
  const spec = block.spec
  const pct = parseRefWidth(width ?? spec?.width ?? DEFAULT_REF_WIDTH)
  const isPublic = Boolean(shareToken)
  const cacheKey = specCacheKey(spec)

  const svgQuery = useQuery({
    queryKey: isPublic
      ? ['chart-embed-public', shareToken, spec?.templateKey, cacheKey]
      : ['chart-embed', workspaceId, spec?.templateKey, cacheKey],
    queryFn: () =>
      isPublic
        ? publicShareApi.chartPreview(shareToken!, spec!.templateKey, spec!.config)
        : chartApi.renderPreview(workspaceId!, spec!.templateKey, spec!.config),
    enabled: spec !== null && (isPublic ? Boolean(shareToken) : Number.isFinite(workspaceId)),
    retry: false,
    staleTime: 60 * 1000,
  })

  const svg = useMemo(() => (svgQuery.data ? sanitizeSvg(svgQuery.data) : ''), [svgQuery.data])
  const message = block.error
    ? chartBlockErrorText(block.error)
    : spec
      ? `图表「${spec.title || spec.templateKey}」渲染失败`
      : '图表定义无效'

  return (
    <figure
      style={{ margin: '0.8em 0', width: `${pct}%`, maxWidth: '100%' }}
      data-testid={`chart-embed-${spec?.templateKey ?? 'invalid'}`}
      data-width={pct}
    >
      {svg ? (
        <div
          data-testid="chart-embed-svg"
          style={{ lineHeight: 0, maxWidth: '100%', overflowX: 'auto' }}
          // 后端唯一渲染器产出 + sanitizeSvg 清洗，无脚本无外链
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : block.error ? (
        <Alert
          type="warning"
          showIcon
          message="图表定义无效"
          description={message}
          style={{ margin: '0.8em 0' }}
          data-testid="chart-embed-invalid-message"
        />
      ) : svgQuery.isLoading ? (
        <div data-testid="chart-embed-loading">
          <Skeleton active title={false} paragraph={{ rows: 4 }} />
        </div>
      ) : (
        <Alert
          type="warning"
          showIcon
          message="图表暂时无法渲染"
          description="模板可能已下线或配置不完整；可编辑图表检查数据后重试。"
          style={{ margin: '0.8em 0' }}
          data-testid="chart-embed-error"
        />
      )}
      {svg && spec && (onEditChart || onWidthChange) && (
        <Space size={4} wrap style={{ marginTop: 4 }}>
          {onWidthChange && (
            <RefWidthControl
              value={pct}
              onChange={onWidthChange}
              testId={`chart-embed-width-${refOrdinal ?? 0}`}
            />
          )}
          {onEditChart && (
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              data-testid={`chart-embed-edit-${refOrdinal ?? 0}`}
              onClick={() => onEditChart(spec, refOrdinal ?? 0)}
            >
              编辑图表
            </Button>
          )}
        </Space>
      )}
    </figure>
  )
}
