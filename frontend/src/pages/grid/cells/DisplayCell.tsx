/** 单元格展示态 —— 按字段类型渲染只读外观. */

import { Tag, Tooltip, Typography } from 'antd'
import type { AttachmentFile, Field } from '@/api'
import { AuthedFileLink, AuthedImage } from '@/components/AuthedFile'
import { getTagColorName, resolveTagColor } from '@/utils/tagColors'
import dayjs from 'dayjs'

// ─────────────── 展示态 ───────────────

/** 字段 options 的截断信息（ADR 0046 D6：展示链路只带前 N 项，颜色 fallback 走值哈希） */
function optionsLayout(field: Field): { truncated?: boolean; total?: number } {
  const cfg = (field.config as Record<string, unknown> | undefined) || {}
  return {
    truncated: cfg.options_truncated === true,
    total: typeof cfg.options_total === 'number' ? cfg.options_total : undefined,
  }
}

/** 自动配色 Tag — 直接用 antd 预设色名 */
function ColoredTag({ value }: { value: string }) {
  return <Tag color={getTagColorName(value)}>{value}</Tag>
}

export function DisplayCell({ value, field, rowId, wid }: { value: unknown; field: Field; rowId: number | string; wid?: number | string }) {
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: '#cbd5e1' }}>—</span>
  }
  const ft = field.field_type
  switch (ft) {
    case 'boolean': {
      const v = Boolean(value)
      return <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>
    }
    case 'number':
    case 'decimal':
    case 'float': {
      // 小数位数根据 config 决定，默认保留全部
      const cfg = (field.config as Record<string, unknown> | undefined) || {}
      const decimals = cfg.decimals as number | undefined
      const num = Number(value)
      if (!Number.isNaN(num) && decimals !== undefined) {
        return <span className="font-num">{num.toFixed(decimals)}</span>
      }
      return <span className="font-num">{String(value)}</span>
    }
    case 'percentage': {
      const num = Number(value)
      if (!Number.isNaN(num)) {
        const cfg = (field.config as Record<string, unknown> | undefined) || {}
        const decimals = (cfg.decimals as number | undefined) ?? 0
        return <span className="font-num">{(num * 100).toFixed(decimals)}%</span>
      }
      return <span>{String(value)}</span>
    }
    case 'date':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD')}</span>
    case 'datetime':
      return <span>{dayjs(String(value)).format('YYYY-MM-DD HH:mm')}</span>
    case 'timestamp': {
      const n = Number(value)
      if (!Number.isNaN(n) && n > 0) {
        return <span>{dayjs.unix(n).format('YYYY-MM-DD HH:mm:ss')}</span>
      }
      return <span>{String(value)}</span>
    }
    case 'select': {
      const options = field.config?.options
      const v = String(value)
      const color = resolveTagColor(v, options, 0, optionsLayout(field))
      return <Tag color={color}>{v}</Tag>
    }
    case 'multi_select':
    case 'multiselect': {
      const options = field.config?.options
      const layout = optionsLayout(field)
      const arr = Array.isArray(value) ? value as unknown[] : String(value).split(',').map(s => s.trim()).filter(Boolean)
      return <>{arr.map((v, i) => {
        const sv = String(v)
        return <Tag key={i} color={resolveTagColor(sv, options, i, layout)}>{sv}</Tag>
      })}</>
    }
    case 'email':
      return <Typography.Link href={`mailto:${value}`}>{String(value)}</Typography.Link>
    case 'url':
      return <Typography.Link href={String(value)} target="_blank" rel="noreferrer">{String(value)}</Typography.Link>
    case 'link': {
      if (Array.isArray(value)) {
        return <span>{value.map((v: Record<string, unknown>, i: number) => <ColoredTag key={i} value={String(v?.value ?? v?.id ?? v)} />)}</span>
      }
      if (value && typeof value === 'object') {
        const o = value as Record<string, unknown>
        return <Tooltip title={`row ${o.id ?? rowId}`}><ColoredTag value={String(o.value ?? o.id ?? value)} /></Tooltip>
      }
      return <ColoredTag value={String(value)} />
    }
    case 'attachment': {
      // 值可能是 JSON 字符串或已经解析好的数组
      let files: AttachmentFile[] = []
      try {
        files = Array.isArray(value) ? (value as AttachmentFile[]) : JSON.parse(String(value || '[]'))
      } catch { files = [] }
      if (!files.length) return <span style={{ color: '#cbd5e1' }}>—</span>
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {files.map(f => {
            const isImg = (f.mime_type || f.filename).match(/image\/|\.(png|jpe?g|gif|webp|svg)$/i)
            if (isImg && wid) {
              return (
                <AuthedImage key={f.file_key} wid={wid} fileKey={f.file_key}
                  width={48} height={48} alt={f.filename} style={{ objectFit: 'cover', borderRadius: 4 }} />
              )
            }
            return (
              <AuthedFileLink key={f.file_key} wid={wid} fileKey={f.file_key} filename={f.filename}
                style={{ fontSize: 12 }}>
                📎 {f.filename}
              </AuthedFileLink>
            )
          })}
        </div>
      )
    }
    case 'image': {
      // 值可能是 JSON 字符串或已经解析好的数组（WPS 图片单元格导入产物）
      let images: AttachmentFile[] = []
      try {
        images = Array.isArray(value) ? (value as AttachmentFile[]) : JSON.parse(String(value || '[]'))
      } catch { images = [] }
      if (!images.length) return <span style={{ color: '#cbd5e1' }}>—</span>
      // 紧凑展示：最多 3 张，多余的收成 +N 角标（全部图片在行详情 / 预览里看）
      const visible = images.slice(0, 3)
      const extra = images.length - visible.length
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
          {visible.map(f => (
            <AuthedImage
              key={f.file_key || f.filename}
              wid={wid}
              fileKey={f.file_key}
              width={32}
              height={32}
              alt={f.filename}
              thumb={96}
              style={{ objectFit: 'cover', borderRadius: 4 }}
            />
          ))}
          {extra > 0 && (
            <Tooltip title={`共 ${images.length} 张图片，打开行详情查看全部`}>
              <span className="cn-image-count">+{extra}</span>
            </Tooltip>
          )}
        </div>
      )
    }
    case 'long_text':
    case 'longtext': {
      const s = String(value)
      return <Tooltip title={s}><span>{s.length > 40 ? s.slice(0, 40) + '…' : s}</span></Tooltip>
    }
    case 'phone':
      return <span>{String(value)}</span>
    default:
      return <span>{String(value)}</span>
  }
}
