/**
 * GalleryView 组件测试 —— 画廊卡片视图.
 *
 * 覆盖：空数据 Empty / 标题自动推断 / 副标题与标签徽章 / meta 脚注 / 点击回调 / density 渲染。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import GalleryView from './GalleryView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: '名称', field_type: 'text', is_primary: false }),
  makeField({ id: 2, name: '描述', field_type: 'long_text' }),
  makeField({ id: 3, name: '状态', field_type: 'select', config: { options: ['在售', '停售'] } }),
  makeField({ id: 4, name: '负责人', field_type: 'text' }),
]

const ROWS: RowResponse[] = [
  { id: 1, 名称: '商品A', 描述: '第一款商品', 状态: '在售', 负责人: 'alice' },
  { id: 2, 名称: '商品B', 描述: '第二款商品', 状态: '停售', 负责人: 'bob' },
]

function renderGallery(props?: {
  rows?: RowResponse[]
  view?: View | null
  density?: 'compact' | 'comfortable' | 'spacious'
  onRowClick?: (r: RowResponse) => void
}) {
  return renderProviders(
    <GalleryView
      rows={props?.rows ?? ROWS}
      fields={FIELDS}
      view={props?.view ?? null}
      density={props?.density ?? 'comfortable'}
      onRowClick={props?.onRowClick}
    />,
  )
}

describe('GalleryView 画廊视图', () => {
  it('空数据显示引导空态', () => {
    renderGallery({ rows: [] })

    expect(screen.getByText(/这张表还没有数据/)).toBeInTheDocument()
  })

  it('自动推断标题字段渲染卡片（首个 text 字段）', () => {
    renderGallery()

    // 标题与渐变兜底块可能渲染同文本，用 getAllByText 宽松断言
    expect(screen.getAllByText('商品A').length).toBeGreaterThan(0)
    expect(screen.getAllByText('商品B').length).toBeGreaterThan(0)
  })

  it('view_options 指定副标题/标签/附加字段渲染', () => {
    const view: View = {
      id: 1, name: '画廊', view_type: 'gallery', is_default: false,
      view_options: { subtitle_field: '描述', tag_field: '状态', meta_fields: ['负责人'] },
    }
    renderGallery({ view })

    expect(screen.getByText('第一款商品')).toBeInTheDocument()
    expect(screen.getByText('在售')).toBeInTheDocument()
    // meta 脚注
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
  })

  it('点击卡片回调对应行', () => {
    const onRowClick = vi.fn()
    renderGallery({ onRowClick })

    fireEvent.click(screen.getByText('商品A'))

    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].id).toBe(1)
  })

  it('density 传递不同间距样式（compact 渲染正常）', () => {
    renderGallery({ density: 'compact' })

    expect(screen.getByText('商品A')).toBeInTheDocument()
  })

  it('少于 100 行走全量渲染（不启用虚拟化容器）', () => {
    renderGallery()

    // 无虚拟化包装层的绝对定位容器
    expect(document.querySelector('[data-index]')).toBeNull()
    expect(screen.getAllByText(/商品[AB]/)).toHaveLength(2)
  })
})
