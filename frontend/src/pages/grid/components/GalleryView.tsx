/** 画廊视图组件 —— 以卡片网格展示记录.
 *
 * view_options 配置字段：
 * - title_field:   标题字段（可选，默认第一个 text 字段或主键）
 * - subtitle_field: 副标题字段（可选，卡片标题下方的补充文字）
 * - tag_field:     标签字段（可选，显示为右上角徽章）
 * - meta_fields:   附加信息字段（string[]，卡片底部脚注）
 * - image_field:   图片/附件字段（可选，缩略图来源）
 */

import { Row, Col, Empty } from 'antd'
import type { RowResponse, Field, View } from '@/api'
import type { Density } from '@/theme/tableSettings'
import { resolveOpts, GALLERY_OPTIONS, resolveAutoField, findOptionSchema } from './viewOptionSchema'
import { formatFieldDisplayValue, extractImageUrl } from './fieldValueFormat'

// ── 渐变色调色板 ──────────────────────────────────────

const PALETTE = [
  'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
  'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
  'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
  'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)',
  'linear-gradient(135deg, #14b8a6 0%, #3b82f6 100%)',
  'linear-gradient(135deg, #f43f5e 0%, #f59e0b 100%)',
  'linear-gradient(135deg, #6366f1 0%, #22d3ee 100%)',
  'linear-gradient(135deg, #84cc16 0%, #10b981 100%)',
]

function pickGradient(key: string): string {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) & 0x7fffffff
  return PALETTE[h % PALETTE.length]
}

// ── 组件 ──────────────────────────────────────────

interface GalleryViewProps {
  rows: RowResponse[]
  fields: Field[]
  view?: View | null
  density: Density
  onRowClick?: (r: RowResponse) => void
}

export default function GalleryView({ rows, fields, view, density, onRowClick }: GalleryViewProps) {
  const opts = resolveOpts(view?.view_options as Record<string, unknown> | undefined, GALLERY_OPTIONS)
  const titleFieldName = (opts.title_field as string)
    || resolveAutoField(fields, findOptionSchema('gallery', 'title_field'))
  const subtitleFieldName = opts.subtitle_field as string | undefined
  const tagFieldName = opts.tag_field as string | undefined
  const metaFieldNames = (opts.meta_fields as string[] | undefined) ?? []
  const imageFieldOpted = opts.image_field as string | undefined
  const imageFieldName = imageFieldOpted
    ?? resolveAutoField(fields, findOptionSchema('gallery', 'image_field'))

  // 字段查找表 — 避免每行多次 fields.find
  const fieldMap = new Map(fields.map(f => [f.name, f]))
  const find = (name: string | undefined): Field | undefined => name ? fieldMap.get(name) : undefined

  // density 配置
  const gutter: [number, number] = density === 'compact' ? [8, 8] : density === 'spacious' ? [20, 20] : [16, 16]
  const radius = density === 'compact' ? 6 : density === 'spacious' ? 10 : 8
  const textPadding = density === 'compact' ? 8 : density === 'spacious' ? 16 : 12
  const textFontSize = density === 'compact' ? 13 : density === 'spacious' ? 15 : 14
  const textSubFontSize = density === 'compact' ? 11 : density === 'spacious' ? 13 : 12
  const imgHeight = density === 'compact' ? 110 : density === 'spacious' ? 170 : 140
  const fallbackHeight = density === 'compact' ? 60 : density === 'spacious' ? 100 : 80
  const fallbackFontSize = density === 'compact' ? 16 : density === 'spacious' ? 24 : 20

  // 默认主键字段作为 title 的兜底
  const primaryField = fields.find(f => f.is_primary)
  const titleField = titleFieldName ? find(titleFieldName) : primaryField

  return (
    <Row gutter={gutter}>
      {rows.map(r => {
        const imgUrl = imageFieldName ? extractImageUrl(r[imageFieldName]) : null

        // 标题：主键字段或配置字段的格式化值
        const titleVal = titleField
          ? formatFieldDisplayValue(titleField, r[titleField.name]) || String(r.id)
          : String(r.id)

        // 副标题
        const subtitleField = find(subtitleFieldName)
        const subtitleVal = subtitleField
          ? formatFieldDisplayValue(subtitleField, r[subtitleField.name])
          : ''

        // 标签徽章
        const tagField = find(tagFieldName)
        const tagVal = tagField
          ? formatFieldDisplayValue(tagField, r[tagField.name])
          : ''

        const gradient = pickGradient(titleVal)

        return (
          <Col xs={24} sm={12} md={8} lg={6} key={r.id}>
            <div
              onClick={() => onRowClick?.(r)}
              style={{ padding: 0, border: '1px solid var(--cn-border)', borderRadius: radius, background: 'var(--cn-bg-container)', cursor: 'pointer', overflow: 'hidden', transition: 'box-shadow 0.15s' }}
            >
              {imgUrl ? (
                <div style={{ width: '100%', height: imgHeight, background: 'var(--cn-bg-canvas)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
                  <img
                    src={imgUrl}
                    alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  {tagVal && (
                    <span style={{ position: 'absolute', top: 6, right: 6, background: 'rgba(0,0,0,0.55)', color: '#fff', fontSize: textSubFontSize, padding: '1px 8px', borderRadius: 10, backdropFilter: 'blur(4px)' }}>{tagVal}</span>
                  )}
                </div>
              ) : (
                <div style={{ width: '100%', height: fallbackHeight, background: gradient, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 600, fontSize: fallbackFontSize, position: 'relative' }}>
                  {titleVal.slice(0, 2).toUpperCase()}
                  {tagVal && (
                    <span style={{ position: 'absolute', top: 6, right: 6, background: 'rgba(255,255,255,0.25)', color: '#fff', fontSize: textSubFontSize, padding: '1px 8px', borderRadius: 10, fontWeight: 500 }}>{tagVal}</span>
                  )}
                </div>
              )}
              <div style={{ padding: textPadding }}>
                <div style={{ fontWeight: 600, marginBottom: 2, fontSize: textFontSize, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{titleVal}</div>
                {subtitleVal && (
                  <div style={{ fontSize: textSubFontSize, color: 'var(--cn-text-secondary)', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{subtitleVal}</div>
                )}
                {metaFieldNames.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {metaFieldNames.map(mf => {
                      const fd = find(mf)
                      if (!fd) return null
                      const v = formatFieldDisplayValue(fd, r[mf])
                      if (!v) return null
                      return (
                        <span key={mf} style={{ fontSize: textSubFontSize - 1, color: '#6b7280', background: '#f3f4f6', padding: '1px 6px', borderRadius: 3 }}>{v}</span>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </Col>
        )
      })}
      {rows.length === 0 && <Empty description="暂无记录" style={{ padding: 48 }} />}
    </Row>
  )
}
