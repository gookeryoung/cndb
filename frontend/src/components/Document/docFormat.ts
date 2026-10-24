/** 文档格式映射：content_type → 图标 / 配色 / 标签（单点维护，ADR 0025）.
 *
 * 出现文档条目的地方（文档树、列表、回收站、工作区搜索）统一取本表，
 * 不就地写死图标 —— 新增格式只改这里。
 *
 * 配色为「格式专属色」而不是统一品牌色：形状已不同，配色进一步降低辨识成本；
 * 色值是中等明度色，浅色与深色主题下都可读。
 */
import {
  FileExcelOutlined,
  FileImageOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FilePptOutlined,
  FileTextOutlined,
  FileWordOutlined,
  FolderOutlined,
} from '@ant-design/icons'
import type { CSSProperties, ComponentType } from 'react'

export interface DocFormatIconProps {
  style?: CSSProperties
  'aria-label'?: string
  'data-testid'?: string
  className?: string
}

export interface DocFormatMeta {
  /** 展示名（工具提示 / 标签用） */
  label: string
  Icon: ComponentType<DocFormatIconProps>
  color: string
  /** 原件族：只读，正文走阅读器而非 Markdown 编辑器 */
  asset: boolean
}

/** 原件族 content_type：后端 models.ASSET_CONTENT_TYPES 的同口径副本 */
export const DOC_ASSET_CONTENT_TYPES = ['pdf', 'image', 'xlsx', 'pptx'] as const

export const DOC_FORMAT_META: Record<string, DocFormatMeta> = {
  markdown: { label: 'Markdown', Icon: FileMarkdownOutlined, color: '#56728f', asset: false },
  folder: { label: '文件夹', Icon: FolderOutlined, color: 'var(--cn-warning, #faad14)', asset: false },
  pdf: { label: 'PDF', Icon: FilePdfOutlined, color: '#d4380d', asset: true },
  image: { label: '图片', Icon: FileImageOutlined, color: '#722ed1', asset: true },
  xlsx: { label: 'Excel', Icon: FileExcelOutlined, color: '#389e0d', asset: true },
  pptx: { label: 'PowerPoint', Icon: FilePptOutlined, color: '#d46b08', asset: true },
  // word 仅为「导出 / 未来保留」的映射：docx 导入仍转 Markdown，节点态是 markdown
  word: { label: 'Word', Icon: FileWordOutlined, color: '#2f54eb', asset: false },
}

const FALLBACK: DocFormatMeta = {
  label: '文档',
  Icon: FileTextOutlined,
  color: 'var(--cn-primary, #1890ff)',
  asset: false,
}

/** 取格式元数据；文件夹固定走文件夹图标，未知类型回退通用文件图标 */
export function formatMeta(contentType?: string | null, isFolder = false): DocFormatMeta {
  if (isFolder) return DOC_FORMAT_META.folder
  const key = (contentType ?? '').toLowerCase()
  return DOC_FORMAT_META[key] ?? FALLBACK
}

/** 是否原件族（只读、可预览 / 下载，不可编辑正文） */
export function isAssetContentType(contentType?: string | null): boolean {
  const key = (contentType ?? '').toLowerCase()
  return (DOC_ASSET_CONTENT_TYPES as readonly string[]).includes(key)
}
