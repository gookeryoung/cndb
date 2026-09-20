/** 报表模板编辑器组件 — 统一导出. */

export { default as TemplateEditor } from './TemplateEditor'
export type { TemplateEditorHandle, TemplateEditorProps } from './TemplateEditor'

export { default as FieldPanel } from './FieldPanel'
export type { FieldPanelProps } from './FieldPanel'

export { default as SyntaxHelpPanel } from './SyntaxHelpPanel'
export type { SyntaxHelpPanelProps, SyntaxExample, SyntaxSection } from './SyntaxHelpPanel'
export { SYNTAX_SECTIONS } from './SyntaxHelpPanel'

export { default as PreviewPanel } from './PreviewPanel'
export type { PreviewPanelProps } from './PreviewPanel'

export { default as ReportTemplateEditor } from './ReportTemplateEditor'
export { buildFieldInsertText } from './ReportTemplateEditor'
export type { FieldGroupInfo } from './ReportTemplateEditor'

export { jinja2Extensions } from './jinja2Highlight'

import './reportEditor.css'
