/**
 * helpContent 帮助内容测试 —— 静态数据与内容渲染.
 *
 * 覆盖：主题清单完整性（数量/唯一性）/ 标题常量 / 各主题内容可渲染且非空 / 关键内容抽查。
 */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { HELP_TOPICS, HELP_CENTER_TITLE } from './helpContent'
import { renderProviders } from '@/test/render-providers'

describe('helpContent 帮助内容', () => {
  it('包含 6 个主题且 key/label 唯一', () => {
    expect(HELP_TOPICS).toHaveLength(6)
    expect(new Set(HELP_TOPICS.map(t => t.key)).size).toBe(6)
    expect(new Set(HELP_TOPICS.map(t => t.label)).size).toBe(6)
  })

  it('标题常量为"帮助中心"', () => {
    expect(HELP_CENTER_TITLE).toBe('帮助中心')
  })

  it.each(HELP_TOPICS)('$label 主题内容可渲染且非空', (topic) => {
    renderProviders(<div data-testid="wrap">{topic.content}</div>)
    const wrap = screen.getByTestId('wrap')
    expect(wrap.textContent?.trim().length).toBeGreaterThan(10)
  })

  it('快速上手渲染 Steps 步骤"创建工作区"', () => {
    const topic = HELP_TOPICS.find(t => t.key === 'quick-start')!
    renderProviders(<div>{topic.content}</div>)
    expect(screen.getByText('创建工作区')).toBeInTheDocument()
  })

  it('权限主题渲染角色表格，含 owner 与 viewer 行', () => {
    const topic = HELP_TOPICS.find(t => t.key === 'roles')!
    renderProviders(<div>{topic.content}</div>)
    const table = document.querySelector('.ant-table-tbody')
    expect(table?.textContent).toContain('owner')
    expect(table?.textContent).toContain('viewer')
  })

  it('字段类型主题标注 16 种类型', () => {
    const topic = HELP_TOPICS.find(t => t.key === 'field-types')!
    renderProviders(<div>{topic.content}</div>)
    expect(screen.getByText(/共 16 种字段类型/)).toBeInTheDocument()
  })
})
