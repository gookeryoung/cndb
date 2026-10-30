/**
 * 图表内嵌块只读嵌入（ADR 0052 D3）：正文配置 → 后端唯一渲染器 SVG.
 *
 * 成员走工作区 render-preview、游客走分享 token 的 render-preview；渲染入参是
 * 块内定义的 template + config，不再按实例 ID 查库。坏块 / 模板下线 / 请求失败
 * 一律**单块降级**为提示，不阻断整篇（I5）。
 */

import { useMemo, useState } from 'react'
import { Alert, App as AntApp, Button, Dropdown, Modal, Skeleton, Space } from 'antd'
import { DownOutlined, DownloadOutlined, EditOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { chartApi } from '@/api/charts'
import publicShareApi from '@/api/publicShare'
import RefWidthControl from './RefWidthControl'
import { saveChartImage, CHART_IMAGE_FORMATS, type ChartImageFormat } from './chartImageSave'
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

/** 保存图片下拉菜单项（PNG / JPEG / SVG） */
const CHART_SAVE_ITEMS = CHART_IMAGE_FORMATS.map(f => ({ key: f.value, label: f.label }))

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
  const { message: toast } = AntApp.useApp()
  const [saving, setSaving] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  // 缩放用整数百分比（50-300，步进 10），避免 1.1*100 浮点误差
  const [previewZoom, setPreviewZoom] = useState(100)

  const handleSaveImage = async (format: ChartImageFormat) => {
    if (!svg || !spec || saving) return
    setSaving(true)
    const ok = await saveChartImage(svg, format, spec.title)
    setSaving(false)
    if (ok) toast.success('图片已保存')
    else toast.error('保存图片失败，请重试')
  }

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
          role="button"
          tabIndex={0}
          aria-label={`放大查看图表「${spec?.title || spec?.templateKey}」`}
          onClick={() => {
            setPreviewZoom(100)
            setPreviewOpen(true)
          }}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              setPreviewZoom(100)
              setPreviewOpen(true)
            }
          }}
          style={{ lineHeight: 0, maxWidth: '100%', overflowX: 'auto', cursor: 'zoom-in' }}
          // 后端唯一渲染器产出 + sanitizeSvg 清洗，无脚本无外链
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : block.error ? (
        <Alert
          type="warning"
          showIcon
          title="图表定义无效"
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
          title="图表暂时无法渲染"
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
          {onEditChart && (
            <Dropdown
              menu={{
                items: CHART_SAVE_ITEMS,
                onClick: ({ key }) => handleSaveImage(key as ChartImageFormat),
              }}
              trigger={['click']}
            >
              <Button
                size="small"
                type="text"
                icon={<DownloadOutlined />}
                loading={saving}
                data-testid={`chart-embed-save-${refOrdinal ?? 0}`}
              >
                保存图片 <DownOutlined style={{ fontSize: 10 }} />
              </Button>
            </Dropdown>
          )}
        </Space>
      )}
      {/* 放大预览（ADR 0060 D1）：复用同一份已 sanitize 的 SVG，零额外请求；
          弹层 75vw，标题栏 +- 按钮缩放（0.5x-3x，步进 10%），滚轮仅用于弹层内滚动；
          禁用过渡动画（jsdom 不跑离场动画，卸载语义保持一致） */}
      <Modal
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width="75vw"
        title={
          <Space size="small">
            <span>{spec?.title || spec?.templateKey}</span>
            <Button
              size="small"
              type="text"
              icon={<ZoomOutOutlined />}
              aria-label="缩小"
              data-testid="chart-embed-zoom-out"
              disabled={previewZoom <= 50}
              onClick={() => setPreviewZoom(z => Math.max(50, z - 10))}
            />
            <span data-testid="chart-embed-zoom-level" style={{ fontSize: 12, minWidth: 40, textAlign: 'center' }}>
              {previewZoom}%
            </span>
            <Button
              size="small"
              type="text"
              icon={<ZoomInOutlined />}
              aria-label="放大"
              data-testid="chart-embed-zoom-in"
              disabled={previewZoom >= 300}
              onClick={() => setPreviewZoom(z => Math.min(300, z + 10))}
            />
          </Space>
        }
        transitionName=""
        maskTransitionName=""
        data-testid="chart-embed-preview"
      >
        {previewOpen && svg && (
          <div data-testid="chart-embed-preview-scroll" style={{ maxHeight: '70vh', overflow: 'auto' }}>
            <div
              data-testid="chart-embed-preview-svg"
              className="cn-chart-preview"
              style={{ lineHeight: 0, width: `${previewZoom}%`, margin: '0 auto' }}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </div>
        )}
      </Modal>
    </figure>
  )
}
