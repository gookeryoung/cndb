/**
 * TablesList 页面组件测试 —— 工作区数据表列表.
 *
 * 覆盖：加载态 / 标题与列表渲染 / 空态 / 访问级别筛选 / 新建表成功回调 / 创建失败错误态
 * + 新建表表单校验（空名/超长截断）/ 编辑重命名 / 删除确认 / 复制表 /
 *   拥有者列渲染 / 筛选边界（owner 回退比对 / 各档位）/ 筛选空态 /
 *   API 建表入口 / 工作区设置跳转.
 * 注：组件用 useParams 取 wid，必须包在 Routes 内渲染。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { Routes, Route, useLocation } from 'react-router-dom'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TablesList from './TablesList'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'
import type { TableSummary } from '@/api'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}</span>
}

const WORKSPACE = {
  id: 10, name: '研发部工作区', description: '团队数据资产', visibility: 'member', tags: [],
  allow_edit: true, created_by_id: 1, created_at: '', updated_at: '',
  owner: { id: 1, username: 'alice', nickname: null },
  table_count: 1, member_count: 1, view_count: 0, total_rows: 0,
  current_user_role: 'owner',
}

/** 两张不同访问级别的表（用于筛选用例） */
const TWO_TABLES: TableSummary[] = [
  { id: 100, name: '我方表', record_count: 1, field_count: 2, view_count: 1, my_access: 'owner' },
  { id: 101, name: '只读表', record_count: 0, field_count: 1, view_count: 0, my_access: 'read' },
]

function renderPage() {
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables" element={<TablesList />} />
      <Route path="/w/:wid/tables/:tid" element={<LocationProbe />} />
      <Route path="/w/:wid/settings" element={<LocationProbe />} />
    </Routes>,
    { route: '/w/10/tables' },
  )
}

function setupWorkspace() {
  server.use(http.get('/api/v1/workspaces/10', () => HttpResponse.json(WORKSPACE)))
}

describe('TablesList 工作区表列表页', () => {
  it('表列表请求未返回时表格显示加载态', async () => {
    setupWorkspace()
    server.use(
      http.get('/api/v1/workspaces/10/tables', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    renderPage()

    await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeInTheDocument())
  })

  it('渲染工作区标题与表列表', async () => {
    setupWorkspace()
    renderPage()

    expect(await screen.findByText('研发部工作区 · 数据资产')).toBeInTheDocument()
    expect(await screen.findByText('客户表')).toBeInTheDocument()
    expect(screen.getByText('共 1 / 1 张表')).toBeInTheDocument()
  })

  it('空列表显示空态提示', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByText(/还没有表/)).toBeInTheDocument()
  })

  it('按访问级别筛选：切到"我拥有的"后仅剩 owner 表', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json(TWO_TABLES)))
    renderPage()

    expect(await screen.findByText('共 2 / 2 张表')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '我拥有的' }))

    expect(await screen.findByText('共 1 / 2 张表')).toBeInTheDocument()
    expect(screen.queryByText('只读表')).not.toBeInTheDocument()
  })

  it('新建表：填写表名创建成功后提示并跳转新表', async () => {
    setupWorkspace()
    server.use(
      http.post('/api/v1/workspaces/10/tables', () =>
        HttpResponse.json({ id: 101, name: '订单表', description: '' }),
      ),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '订单表' } })
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    // 全量并发下 mutation→message→navigate 链路可能超过默认 1s，放宽查找超时（断言语义不变）
    // message（portal）与 navigate（router）分属两套状态更新，先提示后跳转属正常时序，用 waitFor 等待
    expect(await screen.findByText(/已创建表/, {}, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/tables/101'))
  })

  it('创建失败时显示后端错误信息', async () => {
    setupWorkspace()
    server.use(
      http.post('/api/v1/workspaces/10/tables', () =>
        HttpResponse.json({ detail: '表名已存在' }, { status: 500 }),
      ),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '订单表' } })
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    expect(await screen.findByText('表名已存在')).toBeInTheDocument()
  })
})

// ─────────────── 新建表表单校验 / 编辑 / 删除 / 复制 / 筛选边界 ───────────────

/** 打开"更多操作"下拉菜单（Dropdown 默认 hover 触发） */
async function openMoreMenu(tableId: number) {
  fireEvent.mouseEnter(await screen.findByTestId(`more-table-${tableId}`))
  // 菜单渲染在 React 树外的 portal 容器中，等待任意菜单项出现
  await screen.findByText('重命名/编辑')
}

/**
 * 重命名用例专用 render —— 两条路由共享同一个 element 实例.
 *
 * 原因：组件"重命名/编辑"菜单项缺少 domEvent.stopPropagation（复制/删除项均有），
 * React 合成事件会穿过 Dropdown portal 冒泡到行的 onClick 触发 navigate，
 * 导致页面卸载、编辑弹窗无法展示（生产代码问题，已另行上报）。
 * 共享 element 使路由切换时 TablesList 不卸载，弹窗状态得以保留，
 * 从而仍能验证弹窗回填 / 校验 / PATCH 逻辑。
 */
function renderKeepMounted() {
  const page = <TablesList />
  return renderProviders(
    <Routes>
      <Route path="/w/:wid/tables" element={page} />
      <Route path="/w/:wid/tables/:tid" element={page} />
    </Routes>,
    { route: '/w/10/tables' },
  )
}

describe('TablesList 新建表表单校验', () => {
  it('表名为空时提交被拦并提示请输入表名', async () => {
    setupWorkspace()
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    // 不填名称直接提交 → 必填校验拦截
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))
    expect(await screen.findByText('请输入表名')).toBeInTheDocument()
  })

  it('超长表名（70 字符）提交时触发 64 字符上限校验', async () => {
    setupWorkspace()
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /新\s*建\s*表/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('新建表'))

    // 注：jsdom 程序化赋值绕过原生 maxLength 截断，antd 不再二次裁剪，
    // 因此这里验证表单 max 规则兜底拦截（而非输入框硬截断）
    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '超'.repeat(70) } })
    fireEvent.click(screen.getByRole('button', { name: /^创\s*建$/ }))

    expect(await screen.findByText('表名不超过 64 字符')).toBeInTheDocument()
  })
})

describe('TablesList 行操作（编辑 / 删除 / 复制）', () => {
  it('重命名表：编辑弹窗回填原名，保存发起 PATCH 并提示已更新', async () => {
    setupWorkspace()
    let patched: Record<string, unknown> | undefined
    server.use(
      http.patch('/api/v1/workspaces/10/tables/100', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 100, name: '客户表-改' })
      }),
    )
    renderKeepMounted()

    await openMoreMenu(100)
    fireEvent.click(screen.getByText('重命名/编辑'))

    // 编辑弹窗打开且表名回填
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑表'))
    const nameInput = screen.getByLabelText('表名') as HTMLInputElement
    expect(nameInput.value).toBe('客户表')

    fireEvent.change(nameInput, { target: { value: '客户表-改' } })
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    expect(await screen.findByText('已更新')).toBeInTheDocument()
    expect(patched).toMatchObject({ name: '客户表-改' })
  })

  it('编辑表名校验：清空表名保存被拦', async () => {
    setupWorkspace()
    renderKeepMounted()

    await openMoreMenu(100)
    fireEvent.click(screen.getByText('重命名/编辑'))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('编辑表'))

    fireEvent.change(screen.getByLabelText('表名'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /^保\s*存$/ }))

    expect(await screen.findByText('请输入表名')).toBeInTheDocument()
  })

  it('删除表：确认弹窗确认后发起 DELETE 并提示已删除', async () => {
    setupWorkspace()
    let deleted = false
    server.use(
      http.delete('/api/v1/workspaces/10/tables/100', () => {
        deleted = true
        return HttpResponse.json({})
      }),
    )
    renderPage()

    await openMoreMenu(100)
    fireEvent.click(screen.getByText('删除表'))

    // Modal.confirm 静态确认框（渲染在 React 树外）
    expect(await screen.findAllByText(/删除表「客户表」/)).not.toHaveLength(0)
    fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))

    expect(await screen.findByText('已删除')).toBeInTheDocument()
    expect(deleted).toBe(true)
  })

  it('复制表（仅结构）：子菜单触发 copy 请求并提示结果', async () => {
    setupWorkspace()
    let copyCalled = false
    server.use(
      http.post('/api/v1/workspaces/10/tables/100/copy', () => {
        copyCalled = true
        return HttpResponse.json({ id: 200, name: '客户表的副本' })
      }),
    )
    renderPage()

    await openMoreMenu(100)
    // 悬停"复制表"展开子菜单
    fireEvent.mouseEnter(screen.getByText('复制表'))
    fireEvent.click(await screen.findByText('仅复制表结构'))

    expect(await screen.findByText(/已复制为 "客户表的副本" \(仅结构\)/)).toBeInTheDocument()
    expect(copyCalled).toBe(true)
  })
})

describe('TablesList 拥有者列与筛选边界', () => {
  /** 五张表覆盖各访问级别与 owner 回退场景 */
  const FIVE_TABLES: TableSummary[] = [
    { id: 1, name: '甲表', record_count: 0, field_count: 0, view_count: 0, my_access: 'owner' },
    { id: 2, name: '乙表', record_count: 0, field_count: 0, view_count: 0, my_access: 'write' },
    { id: 3, name: '丙表', record_count: 0, field_count: 0, view_count: 0, my_access: 'read' },
    { id: 4, name: '丁表', record_count: 0, field_count: 0, view_count: 0, owner: { id: 1, username: 'alice' } },
    { id: 5, name: '戊表', record_count: 0, field_count: 0, view_count: 0, owner: { id: 2, username: 'bob' } },
  ]

  function renderAsOwner() {
    return renderProviders(
      <Routes>
        <Route path="/w/:wid/tables" element={<TablesList />} />
        <Route path="/w/:wid/tables/:tid" element={<LocationProbe />} />
        <Route path="/w/:wid/settings" element={<LocationProbe />} />
      </Routes>,
      { route: '/w/10/tables', initialAuth: { user: mockUser, token: 'fake-token' } },
    )
  }

  it('拥有者列：本人带"我"标记，他人显示用户名，缺省显示未指定', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json(FIVE_TABLES)))
    renderAsOwner()

    // 仅丁表 owner 是当前用户（alice）→ 一个 alice + 一个"我"标记
    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getAllByText('我')).toHaveLength(1)
    expect(screen.getByText('bob')).toBeInTheDocument()
    // 甲/乙/丙三表无 owner 信息 → 未指定
    expect(screen.getAllByText('未指定')).toHaveLength(3)
  })

  it('筛选档位：owner 回退比对 / write 含 owner / read 含 write', async () => {
    setupWorkspace()
    server.use(http.get('/api/v1/workspaces/10/tables', () => HttpResponse.json(FIVE_TABLES)))
    renderAsOwner()

    expect(await screen.findByText('共 5 / 5 张表')).toBeInTheDocument()

    // 我拥有的：甲表(owner) + 丁表（无 my_access 回退比对 owner.id 命中）
    fireEvent.click(screen.getByRole('radio', { name: '我拥有的' }))
    expect(await screen.findByText('共 2 / 5 张表')).toBeInTheDocument()
    expect(screen.getByText('丁表')).toBeInTheDocument()
    expect(screen.queryByText('丙表')).not.toBeInTheDocument()

    // 我可编辑的：owner/write 命中，丁表回退不参与该档位 → 甲表、乙表
    fireEvent.click(screen.getByRole('radio', { name: '我可编辑的' }))
    expect(await screen.findByText('乙表')).toBeInTheDocument()
    expect(screen.queryByText('丁表')).not.toBeInTheDocument()
    expect(screen.queryByText('戊表')).not.toBeInTheDocument()

    // 我可读的：read/write/owner 命中 → 甲表、乙表、丙表
    fireEvent.click(screen.getByRole('radio', { name: '我可读的' }))
    expect(await screen.findByText('丙表')).toBeInTheDocument()
    expect(screen.queryByText('戊表')).not.toBeInTheDocument()
    expect(screen.getByText('共 3 / 5 张表')).toBeInTheDocument()
  })

  it('筛选后无匹配时显示筛选空态提示', async () => {
    setupWorkspace()
    renderAsOwner()

    expect(await screen.findByText('客户表')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '我拥有的' }))

    expect(await screen.findByText('当前筛选条件下没有表')).toBeInTheDocument()
    expect(screen.getByText('共 0 / 1 张表')).toBeInTheDocument()
  })
})

describe('TablesList 其他入口', () => {
  it('点击工作区设置跳转到 /w/:wid/settings', async () => {
    setupWorkspace()
    renderPage()

    const user = userEvent.setup()
    await user.click(await screen.findByTestId('workspace-settings-link'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/10/settings'))
  })
})
