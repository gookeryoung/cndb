/**
 * reportEditor.css 深色主题回归测试.
 *
 * 编辑器容器样式必须使用 --cn-* 主题变量，禁止硬编码浅色背景/边框，
 * 否则深色主题（theme-dark/midnight/oled/github-dark）下出现白色块。
 */

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const css = readFileSync(join(__dirname, 'reportEditor.css'), 'utf-8')

describe('reportEditor.css 深色主题适配', () => {
  it('容器/面板背景与边框使用主题变量而非硬编码浅色', () => {
    // 硬编码浅色背景/边框（深色主题下呈现白色块）
    const hardcoded = [
      /background:\s*#(fff|fafafa|f5f5f5|f0f0f0)\b/i,
      /border[^:]*:\s*[^;]*#(e8e8e8|f0f0f0|e5e7eb)\b/i,
    ]
    for (const re of hardcoded) {
      expect(css.match(re)).toBeNull()
    }
    // 关键容器使用变量
    expect(css).toMatch(/\.report-editor-viewpane\s*{[^}]*var\(--cn-bg-container\)/)
    expect(css).toMatch(/\.report-field-panel\s*{[^}]*var\(--cn-bg-subtle\)/)
  })

  it('三栏布局子元素不得使用 display: contents', () => {
    // dnd-kit 的 DndContext/SortableContext 不渲染 DOM，
    // `.report-template-editor > *` 会命中字段面板/编辑器根节点，
    // display: contents 使其盒模型失效（宽度/边框/flex 尺寸全丢），三栏布局错乱
    expect(css).not.toMatch(/\.report-template-editor[^{]*{[^}]*display:\s*contents/)
    expect(css).not.toContain('display: contents')
  })

  it('文字颜色使用主题变量', () => {
    expect(css).not.toMatch(/color:\s*#262626\b/)
    expect(css).not.toMatch(/color:\s*#8c8c8c\b/)
    expect(css).toMatch(/var\(--cn-text-primary\)/)
    expect(css).toMatch(/var\(--cn-text-muted\)/)
  })
})
