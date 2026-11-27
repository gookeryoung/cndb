/** 文档模板页（ADR 0152 / 0169 / 0177 C3）—— 一个入口，两个分区.
 *
 * 两类模板模型独立、语义不同（导出模板 = Word / PDF 排版参数；内容模板 = 从模板新建
 * 文档的正文骨架），但入口收敛到同一个页面，用 `?kind=export|content` 分区（D4）：
 *
 * - `?kind=export`（缺省）→ `ExportTemplatePanel`（导出模板，本页提供 `.cn-page` 容器）
 * - `?kind=content`        → `ContentTemplatePanel`（内容模板，面板自带 `.cn-page` 与页头）
 *
 * 旧路径 `/documents/content-templates` 由 `App.tsx` 重定向到 `?kind=content`，深链不断；
 * 文档区页签「内容模板 / 导出模板」（内容模板在前）即分区开关，不在页内再放一套 Segmented。
 */

import { useSearchParams } from 'react-router-dom'

import ContentTemplatePanel from '@/pages/documents/ContentTemplatePanel'
import ExportTemplatePanel from '@/pages/documents/ExportTemplatePanel'

export type TemplateKind = 'export' | 'content'

/** 从查询串解析分区：只认 `content`，其余（含缺省 / 脏值）一律按导出模板。 */
export function resolveTemplateKind(kind: string | null): TemplateKind {
  return kind === 'content' ? 'content' : 'export'
}

export default function DocumentTemplatesPage() {
  const [params] = useSearchParams()
  if (resolveTemplateKind(params.get('kind')) === 'content') return <ContentTemplatePanel />

  return (
    <div className="cn-page cn-doc-tpl-page" data-testid="document-templates-page" data-kind="export">
      <ExportTemplatePanel />
    </div>
  )
}
