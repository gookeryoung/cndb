/** Office 预览内联渲染测试：HTML 拆分、脚本兜底剔除、Shadow DOM 隔离渲染. */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import OfficeHtmlPreview, { splitPreviewHtml } from './OfficeHtmlPreview'

const PAGE = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Excel预览</title><style>body{padding:12px} table.sheet{border-collapse:collapse}</style></head>
<body class="cn-preview-sheet-page"><div class="cn-sheet-tabs"><table class="sheet"><tbody><tr><td>一月</td></tr></tbody></table></div>
<script>window.__evil = 1</script></body></html>`

describe('OfficeHtmlPreview 内联预览', () => {
  it('拆分出样式与 body 片段，并剔除脚本', () => {
    const { css, body } = splitPreviewHtml(PAGE)
    expect(css).toContain('table.sheet{border-collapse:collapse}')
    expect(css).not.toContain('<script')
    expect(body).toContain('<table class="sheet">')
    expect(body).not.toContain('<script')
    expect(body).not.toContain('window.__evil')
    // body 标签本身不带入片段（其样式规则留在 css 里，不污染页面）
    expect(body.startsWith('<body')).toBe(false)
  })

  it('内容渲染进 Shadow DOM（样式不外泄、正文区只有一层滚动容器）', () => {
    render(<OfficeHtmlPreview html={PAGE} />)
    const host = screen.getByTestId('doc-asset-office')
    expect(host.tagName).toBe('DIV')
    expect(host.shadowRoot).not.toBeNull()
    expect(host.shadowRoot?.innerHTML).toContain('<table class="sheet">')
    expect(host.shadowRoot?.innerHTML).toContain('table.sheet{border-collapse:collapse}')
    // 页面 DOM 里不会出现预览表格（被影子根隔离）
    expect(document.querySelector('table.sheet')).toBeNull()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('html 更新时重新写入影子根（不叠加旧内容）', () => {
    const { rerender } = render(<OfficeHtmlPreview html={PAGE} />)
    rerender(<OfficeHtmlPreview html="<html><body><p>第二版</p></body></html>" />)
    const host = screen.getByTestId('doc-asset-office')
    expect(host.shadowRoot?.innerHTML).toContain('第二版')
    expect(host.shadowRoot?.innerHTML).not.toContain('class="sheet"')
  })
})
