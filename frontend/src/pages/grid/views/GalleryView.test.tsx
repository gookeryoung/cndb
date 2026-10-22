/** GalleryView 组件测试 —— 卡片渲染 / 空区块省略 / 点击与键盘 / 48 分批与重置 / 空态 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import GalleryView from './GalleryView'
import { renderProviders } from '@/test/render-providers'
import { makeField } from '@/test/fixtures'
import type { Field, RowResponse, View } from '@/api'

const FIELDS: Field[] = [
  makeField({ id: 1, name: 'title', field_type: 'text' }),
  makeField({ id: 2, name: 'summary', field_type: 'longtext' }),
  makeField({ id: 3, name: 'date', field_type: 'date' }),
  makeField({ id: 4, name: 'region', field_type: 'select', config: { options: ['亚太', '欧洲'] } }),
  makeField({ id: 5, name: 'source', field_type: 'text' }),
]

const ROWS = [
  { id: 1, title: '中美在经贸与科技领域保持高层沟通', summary: '中美围绕关税与出口管制维持工作层磋商。', date: '2026-10-22', region: '亚太', source: '综合整理' },
  { id: 2, title: '俄乌冲突延续', summary: '欧洲内部对军援力度意见分化。', date: '2026-10-22', region: '欧洲', source: '综合整理' },
] as unknown as RowResponse[]

const VIEW = {
  id: 1,
  name: '资讯画廊',
  view_type: 'gallery',
  is_default: true,
  view_options: {
    title_field: 'title',
    summary_field: 'summary',
    tag_fields: ['region'],
    meta_fields: ['source'],
    date_field: 'date',
  },
} as unknown as View

function renderGallery(props?: {
  rows?: RowResponse[]
  fields?: Field[]
  view?: View | null
  onRowClick?: (r: RowResponse) => void
  loading?: boolean
  error?: boolean
  onRetry?: () => void
}) {
  return renderProviders(
    <GalleryView
      rows={props?.rows ?? ROWS}
      fields={props?.fields ?? FIELDS}
      view={props?.view !== undefined ? props.view : VIEW}
      onRowClick={props?.onRowClick}
      loading={props?.loading}
      error={props?.error}
      onRetry={props?.onRetry}
    />,
  )
}

describe('GalleryView 卡片渲染', () => {
  it('渲染计数条、标题、摘要、标签、日期徽章与元信息', () => {
    renderGallery()

    expect(screen.getByTestId('gallery-count')).toHaveTextContent('共 2 条')
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(2)
    expect(screen.getAllByTestId('gallery-card-title').map((el) => el.textContent)).toEqual([
      '中美在经贸与科技领域保持高层沟通',
      '俄乌冲突延续',
    ])
    expect(screen.getAllByTestId('gallery-summary')).toHaveLength(2)
    expect(screen.getAllByTestId('gallery-tag').map((el) => el.textContent)).toEqual(['亚太', '欧洲'])
    expect(screen.getAllByText('2026-10-22')).toHaveLength(2)
    expect(screen.getAllByTestId('gallery-meta').map((el) => el.textContent)).toEqual([
      'source：综合整理',
      'source：综合整理',
    ])
  })

  it('无摘要 / 无日期 / 无标签 / 无元信息时对应区块整块省略', () => {
    const fields: Field[] = [
      makeField({ id: 1, name: 'title', field_type: 'text' }),
    ]
    const rows = [{ id: 3, title: '只有标题的一行' }] as unknown as RowResponse[]
    renderGallery({ fields, rows, view: { id: 2, name: '画廊', view_type: 'gallery', is_default: false, view_options: {} } as unknown as View })

    expect(screen.queryByTestId('gallery-summary')).toBeNull()
    expect(screen.queryByTestId('gallery-tag')).toBeNull()
    expect(screen.queryByTestId('gallery-meta')).toBeNull()
    expect(screen.getByTestId('gallery-card-title')).toHaveTextContent('只有标题的一行')
  })

  it('标题为空时回退 #id', () => {
    const rows = [{ id: 42, title: '' }] as unknown as RowResponse[]
    renderGallery({ rows })
    expect(screen.getByTestId('gallery-card-title')).toHaveTextContent('#42')
  })
})

describe('GalleryView 交互', () => {
  it('点击整卡触发 onRowClick(row)', () => {
    const onRowClick = vi.fn()
    renderGallery({ onRowClick })
    fireEvent.click(screen.getAllByTestId('gallery-card')[1]!)
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0]![0]).toMatchObject({ id: 2 })
  })

  it('键盘 Enter / Space 触发 onRowClick(row)', () => {
    const onRowClick = vi.fn()
    renderGallery({ onRowClick })
    const card = screen.getAllByTestId('gallery-card')[0]!
    expect(card).toHaveAttribute('role', 'button')
    fireEvent.keyDown(card, { key: 'Enter' })
    fireEvent.keyDown(card, { key: ' ' })
    expect(onRowClick).toHaveBeenCalledTimes(2)
    // 其他按键不触发
    fireEvent.keyDown(card, { key: 'a' })
    expect(onRowClick).toHaveBeenCalledTimes(2)
  })
})

describe('GalleryView 分批渲染', () => {
  const makeRows = (n: number): RowResponse[] =>
    Array.from({ length: n }, (_, i) => ({ id: i + 1, title: `资讯 ${i + 1}` })) as unknown as RowResponse[]

  it('初始只渲染 48 张，加载更多补齐并显示已显示全部', () => {
    const rows = makeRows(50)
    renderGallery({ rows })

    expect(screen.getByTestId('gallery-count')).toHaveTextContent('共 50 条')
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(48)
    const more = screen.getByTestId('gallery-load-more')
    expect(more).toHaveTextContent('加载更多（剩余 2）')

    fireEvent.click(more)
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(50)
    expect(screen.queryByTestId('gallery-load-more')).toBeNull()
    expect(screen.getByText('已显示全部')).toBeInTheDocument()
  })

  it('rows 变化时重置批次（换表 / 筛选后回到首批）', () => {
    const { rerender } = renderGallery({ rows: makeRows(50) })
    fireEvent.click(screen.getByTestId('gallery-load-more'))
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(50)

    rerender(
      <GalleryView rows={makeRows(49)} fields={FIELDS} view={VIEW} />,
    )
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(48)
    expect(screen.getByTestId('gallery-load-more')).toHaveTextContent('加载更多（剩余 1）')
  })

  it('不超过 48 张时不渲染加载更多', () => {
    renderGallery({ rows: makeRows(12) })
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(12)
    expect(screen.queryByTestId('gallery-load-more')).toBeNull()
    expect(screen.queryByText('已显示全部')).toBeNull()
  })
})

describe('GalleryView 空态 / 加载态 / 失败态', () => {
  it('空数据显示暂无数据', () => {
    renderGallery({ rows: [] })
    expect(screen.getByTestId('gallery-view')).toHaveTextContent('暂无数据')
    expect(screen.queryAllByTestId('gallery-card')).toHaveLength(0)
  })

  it('加载中（无缓存行）显示骨架卡而不是「暂无数据」', () => {
    renderGallery({ rows: [], loading: true })
    expect(screen.getByTestId('gallery-loading')).toBeInTheDocument()
    expect(screen.queryByText('暂无数据')).toBeNull()
  })

  it('已有缓存行时即便在请求中也不显示骨架', () => {
    renderGallery({ loading: true })
    expect(screen.getAllByTestId('gallery-card')).toHaveLength(2)
    expect(screen.queryByTestId('gallery-loading')).toBeNull()
  })

  it('请求失败显示失败态与重试按钮，点击触发 onRetry', () => {
    const onRetry = vi.fn()
    renderGallery({ rows: [], error: true, onRetry })
    expect(screen.getByTestId('gallery-view')).toHaveAttribute('data-state', 'error')
    expect(screen.getByText('数据加载失败')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('gallery-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
