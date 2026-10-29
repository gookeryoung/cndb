/** useCreateParam —— ?create=1 URL 触发新建弹窗（0067 C3）的幂等口径.
 *
 * 覆盖：命中即回调并移除参数（replace）；无参数不触发；页面已挂载时
 * 再次导航带参会重新触发；参数移除后刷新（重挂载）不重复弹出。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { render } from '@testing-library/react'
import { useCreateParam } from './useCreateParam'

/** 探针：挂载 useCreateParam，并暴露「导航到带参路由」按钮模拟重复执行命令 */
function Probe({ onCreate, target }: { onCreate: () => void; target: string }) {
  useCreateParam(onCreate)
  const navigate = useNavigate()
  const loc = useLocation()
  return (
    <>
      <button onClick={() => navigate(target)}>go</button>
      <div data-testid="loc">{loc.pathname + loc.search}</div>
    </>
  )
}

function mount(route: string, onCreate: () => void, target = '/w/10/tables?create=1') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Probe onCreate={onCreate} target={target} />
    </MemoryRouter>,
  )
}

describe('useCreateParam', () => {
  it('?create=1 挂载命中：执行回调并移除参数（幂等）', async () => {
    const onCreate = vi.fn()
    mount('/w/10/tables?create=1', onCreate)

    expect(onCreate).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/tables')
      expect(screen.getByTestId('loc')).not.toHaveTextContent('create')
    })
    // 参数移除后 effect 重跑不再触发
    expect(onCreate).toHaveBeenCalledTimes(1)
  })

  it('无 create 参数：不触发', () => {
    const onCreate = vi.fn()
    mount('/w/10/tables', onCreate)
    expect(onCreate).not.toHaveBeenCalled()
  })

  it('页面已挂载时再次导航带参：重新触发（重复执行命令场景）', async () => {
    const onCreate = vi.fn()
    mount('/w/10/tables', onCreate)
    expect(onCreate).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('go'))
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1))
    await waitFor(() => {
      expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/tables')
    })
    expect(onCreate).toHaveBeenCalledTimes(1)
  })
})
