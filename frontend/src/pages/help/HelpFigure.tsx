/** 帮助图示（ADR 0030）—— 正文里的 SVG 图.
 *
 * 图示由后端按「构建代码 + 真实数据源（字段类型注册表 / 权限枚举 / 示例 CSV）」
 * 生成，请求期按指纹即时重建、后台按周期全量重建，因此代码更新后不会停留在旧图。
 *
 * 这里只做三件事：拿清单（含指纹）→ 按指纹拉 SVG 文本 → **内联**渲染。
 * 内联而非 `<img>`，是为了让 SVG 里的 `var(--cn-*)` 跟随浅色 / 暗色主题切换。
 * 图示失败不阻塞正文：降级为只显示图注。
 */

import { useQuery } from '@tanstack/react-query'
import { Skeleton, Typography } from 'antd'
import { useMemo } from 'react'
import { helpApi } from '@/api/help'

const { Text } = Typography

export interface HelpFigureProps {
  /** 图示 key，与后端 `FIGURE_SPECS` 一一对应 */
  id: string
  /** 覆盖后端登记的图注（默认用清单里的 caption） */
  caption?: string
}

/** 防御性清洗：后端产出不含脚本，仍去掉 `<script>` 与行内事件属性 */
function sanitizeSvg(svg: string): string {
    return svg
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/\son[a-z]+\s*=\s*"[^"]*"/gi, '')
        .replace(/\son[a-z]+\s*=\s*'[^']*'/gi, '')
}

function formatGeneratedAt(seconds: number): string {
    if (!seconds) return ''
    const date = new Date(seconds * 1000)
    const pad = (value: number) => String(value).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function HelpFigure({ id, caption }: HelpFigureProps) {
    const metaQuery = useQuery({
        queryKey: ['help', 'figures'],
        queryFn: helpApi.listFigures,
        staleTime: 5 * 60 * 1000,
    })

    const meta = metaQuery.data?.items.find((item) => item.key === id)
    const fingerprint = meta?.fingerprint ?? ''

    const svgQuery = useQuery({
        queryKey: ['help', 'figure', id, fingerprint],
        queryFn: () => helpApi.getFigureSvg(id),
        enabled: Boolean(fingerprint),
        staleTime: Infinity,
        // 不做自动重试：指纹变化会重新拉取，失败时先降级提示，避免长时间骨架屏
        retry: false,
    })

    const svg = useMemo(() => (svgQuery.data ? sanitizeSvg(svgQuery.data) : ''), [svgQuery.data])
    const captionText = caption ?? meta?.caption ?? ''
    const generatedAt = formatGeneratedAt(meta?.generatedAt ?? 0)

    // 清单里没有这个 key（内容引用了已删除的图示）与拉图失败都降级为一行提示，不阻塞正文
    const notFound = metaQuery.isSuccess && !meta
    const failed = metaQuery.isError || notFound || svgQuery.isError
    const showSvg = Boolean(svg)

    return (
        <figure className="cn-help-figure" data-testid={`help-figure-${id}`}>
            {showSvg ? (
                <div
                    className="cn-help-figure-canvas"
                    data-testid={`help-figure-canvas-${id}`}
                    dangerouslySetInnerHTML={{ __html: svg }}
                />
            ) : failed ? (
                <div className="cn-help-figure-fallback" data-testid={`help-figure-error-${id}`}>
                    {notFound ? '图示未登记' : '图示暂不可用'}
                </div>
            ) : (
                <div className="cn-help-figure-canvas" data-testid={`help-figure-loading-${id}`}>
                    <Skeleton active title={false} paragraph={{ rows: 3 }} />
                </div>
            )}
            {(captionText || generatedAt) && (
                <figcaption className="cn-help-figure-caption">
                    {captionText && <Text type="secondary">{captionText}</Text>}
                    {generatedAt && (
                        <Text type="secondary" className="cn-help-figure-stamp">
                            图示更新于 {generatedAt}
                        </Text>
                    )}
                </figcaption>
            )}
        </figure>
    )
}
