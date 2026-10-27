/**
 * 正文内嵌图表块（ADR 0052）：`` ```chart `` 围栏 + JSON 定义的解析 / 序列化 / 定位改写.
 *
 * 与后端 `services/charts/inline.py` 同构：围栏必须独占段落，JSON 规范字段为
 * `version` / `template` / `title` / `width` / `config`（迁移期另有 `legacy_id`）。
 * 正文自包含，渲染入参是配置而不是实例 ID。
 */

import { DEFAULT_REF_WIDTH, parseRefWidth } from './refWidth'

export const INLINE_CHART_LANG = 'chart'
export const INLINE_CHART_VERSION = 1
/** 单块定义上限（与后端一致） */
export const MAX_BLOCK_BYTES = 32 * 1024
/** 单篇正文图表块上限（与后端一致） */
export const MAX_BLOCKS_PER_DOC = 50

export type ChartBlockError =
  | 'json_invalid'
  | 'version_unsupported'
  | 'template_missing'
  | 'config_invalid'
  | 'too_large'

const ERROR_TEXT: Record<ChartBlockError, string> = {
  json_invalid: 'JSON 格式错误',
  version_unsupported: '版本不受支持',
  template_missing: '模板不存在或已下线',
  config_invalid: '配置校验失败',
  too_large: '定义超过 32KB',
}

export function chartBlockErrorText(code: ChartBlockError): string {
  return `[图表定义无效：${ERROR_TEXT[code]}]`
}

export interface ChartBlockSpec {
  version: number
  templateKey: string
  title: string
  width: number
  config: Record<string, unknown>
  legacyId?: number
  /** 手写 / 未来字段：原样保留，序列化时回写 */
  extra?: Record<string, unknown>
}

export interface ChartBlock {
  /** 块原文（含围栏），导出 / 未识别时原样透传 */
  source: string
  spec: ChartBlockSpec | null
  error?: ChartBlockError
}

const FENCE_START_RE = /^[ \t]{0,3}(`{3,})chart[ \t]*$/
const FENCE_END_RE = /^[ \t]{0,3}(`{3,})[ \t]*$/
const PARAGRAPH_SPLIT_RE = /(\n\n+)/

/** 解析一个独占段落；非图表块返回 null，坏块返回带 `error` 的块 */
export function parseChartBlock(paragraph: string): ChartBlock | null {
  const text = paragraph.replace(/^\n+|\n+$/g, '')
  if (!text) return null
  const lines = text.split('\n')
  const start = FENCE_START_RE.exec(lines[0] ?? '')
  if (!start) return null
  const end = lines.length > 1 ? FENCE_END_RE.exec(lines[lines.length - 1]!) : null
  if (!end || end[1]!.length < start[1]!.length) return null

  const source = lines.join('\n')
  if (new TextEncoder().encode(source).length > MAX_BLOCK_BYTES) {
    return { source, spec: null, error: 'too_large' }
  }

  const body = lines.slice(1, -1).join('\n').trim()
  let payload: unknown
  try {
    payload = body ? JSON.parse(body) : null
  } catch {
    return { source, spec: null, error: 'json_invalid' }
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { source, spec: null, error: 'json_invalid' }
  }
  const record = payload as Record<string, unknown>

  const version = record.version ?? INLINE_CHART_VERSION
  if (typeof version !== 'number' || !Number.isInteger(version) || version !== INLINE_CHART_VERSION) {
    return { source, spec: null, error: 'version_unsupported' }
  }

  const templateKey = typeof record.template === 'string' ? record.template.trim() : ''
  if (!templateKey) return { source, spec: null, error: 'template_missing' }

  const rawConfig = record.config
  if (!rawConfig || typeof rawConfig !== 'object' || Array.isArray(rawConfig)) {
    return { source, spec: null, error: 'config_invalid' }
  }

  const title = typeof record.title === 'string' ? record.title.trim() : ''
  const extra: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(record)) {
    if (!['version', 'template', 'title', 'width', 'config', 'legacy_id'].includes(key)) extra[key] = value
  }
  const spec: ChartBlockSpec = {
    version,
    templateKey,
    title,
    width: parseRefWidth(
      typeof record.width === 'number' || typeof record.width === 'string' ? record.width : undefined,
    ),
    config: rawConfig as Record<string, unknown>,
  }
  if (typeof record.legacy_id === 'number') spec.legacyId = record.legacy_id
  if (Object.keys(extra).length > 0) spec.extra = extra
  return { source, spec }
}

/** 序列化为可读块（2 空格缩进、键顺序固定，与后端一致） */
export function serializeChartBlock(spec: ChartBlockSpec): string {
  const payload: Record<string, unknown> = {
    version: spec.version || INLINE_CHART_VERSION,
    template: spec.templateKey,
    title: spec.title,
    width: parseRefWidth(spec.width),
    config: spec.config,
  }
  if (spec.legacyId !== undefined) payload.legacy_id = spec.legacyId
  for (const [key, value] of Object.entries(spec.extra ?? {})) {
    if (!(key in payload)) payload[key] = value
  }
  return `\`\`\`${INLINE_CHART_LANG}\n${JSON.stringify(payload, null, 2)}\n\`\`\``
}

/** 按出现序号改写块（编辑 / 调宽共用）；未命中返回原正文 */
export function rewriteChartBlock(
  content: string,
  occurrence: number,
  next: ChartBlockSpec,
): string {
  if (!content) return content
  const parts = content.split(PARAGRAPH_SPLIT_RE)
  let seen = -1
  for (let i = 0; i < parts.length; i += 2) {
    const part = parts[i]
    if (!part) continue
    const block = parseChartBlock(part)
    if (!block) continue
    seen += 1
    if (seen !== occurrence) continue
    // 保留段落首尾空白（缩进 / 空行），仅替换块本身
    const trimmed = part.replace(/^\n+|\n+$/g, '')
    const start = part.indexOf(trimmed)
    parts[i] = part.slice(0, start) + serializeChartBlock(next) + part.slice(start + trimmed.length)
    break
  }
  return parts.join('')
}

/** 调整第 N 个图表块的宽度（ADR 0052 D8：宽度随块分发） */
export function rewriteChartBlockWidth(content: string, occurrence: number, width: number): string {
  const parts = content.split(PARAGRAPH_SPLIT_RE)
  let seen = -1
  for (let i = 0; i < parts.length; i += 2) {
    const part = parts[i]
    if (!part) continue
    const block = parseChartBlock(part)
    if (!block?.spec) continue
    seen += 1
    if (seen !== occurrence) continue
    return rewriteChartBlock(content, occurrence, { ...block.spec, width: parseRefWidth(width) })
  }
  return content
}

/** 全部图表块（含坏块），按出现顺序 */
export function iterChartBlocks(content: string): ChartBlock[] {
  if (!content) return []
  const parts = content.split(PARAGRAPH_SPLIT_RE)
  const blocks: ChartBlock[] = []
  for (let i = 0; i < parts.length; i += 2) {
    const parsed = parseChartBlock(parts[i] ?? '')
    if (parsed) blocks.push(parsed)
  }
  return blocks
}

/** 序列化后体积（插入 / 保存前的上限检查） */
export function chartBlockBytes(spec: ChartBlockSpec): number {
  return new TextEncoder().encode(serializeChartBlock(spec)).length
}

/** 与后端一致的默认宽度常量（供设计器 / 插入复制保留） */
export { DEFAULT_REF_WIDTH }
