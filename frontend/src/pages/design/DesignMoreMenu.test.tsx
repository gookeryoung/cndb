/** 设计工具栏动作测试（ADR 0103 D6 修订 / 承接 ADR 0079 D5）：入口接线、空模型禁用、导出失败提示.
 *
 * 版本历史与导出为两个独立图标按钮；exporters 本体由 exporters.test.ts 覆盖，
 * 此处 mock exporters 断言菜单 → 导出函数 → 下载的接线与异常分支，以及版本历史入口回调。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import DesignMoreMenu from './DesignMoreMenu'
import { renderProviders } from '@/test/render-providers'
import type { DesignIR } from '@/api'
import { DesignExportError } from './exporters'

vi.mock('./exporters', async (importOriginal) => {
  // 工厂体不得引用顶层 import（hoisting 抢跑）：DesignExportError 经 ...actual 原样保留
  const actual = await importOriginal<typeof import('./exporters')>()
  return {
    ...actual,
    buildSTL: vi.fn(() => new ArrayBuffer(10)),
    buildOBJ: vi.fn(() => 'v 1 2 3'),
    buildGLB: vi.fn(() => Promise.resolve(new Blob(['glb']))),
    captureViews: vi.fn(() => ({ front: 'f', top: 't', right: 'r' })),
    downloadBlob: vi.fn(),
    downloadDataURL: vi.fn(),
    exportMeshesOf: (ir: DesignIR | null) => (ir && ir.nodes.length > 0 ? ([{}] as never) : []),
  }
})

const IR: DesignIR = {
  version: 5,
  units: { length: 'mm', angle: 'deg' },
  params: [],
  nodes: [{ op: 'box', size: [10, 10, 10] }],
}

const EMPTY_IR: DesignIR = { ...IR, nodes: [] }

import { buildGLB, buildOBJ, buildSTL, captureViews, downloadBlob, downloadDataURL } from './exporters'

function renderMenu(ir: DesignIR | null, onHistory = vi.fn()) {
  renderProviders(<DesignMoreMenu ir={ir} title="法兰板" versionCount={3} onHistory={onHistory} />)
  return { onHistory }
}

function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: '导出' }))
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DesignMoreMenu', () => {
  it('版本历史为独立图标按钮，点击直接触发回调（D6）', () => {
    const { onHistory } = renderMenu(IR)
    fireEvent.click(screen.getByRole('button', { name: '版本历史' }))
    expect(onHistory).toHaveBeenCalled()
  })

  it('空 IR（顶层无实例）导出项禁用（边界 #3）', async () => {
    renderMenu(EMPTY_IR)
    openMenu()
    const item = await screen.findByText('STL（二进制，3D 打印）')
    expect(item.closest('.ant-dropdown-menu-item')).toHaveClass('ant-dropdown-menu-item-disabled')
  })

  it('点击菜单项分派到对应导出函数并下载', async () => {
    renderMenu(IR)
    openMenu()
    fireEvent.click(await screen.findByText('STL（二进制，3D 打印）'))
    await waitFor(() => expect(buildSTL).toHaveBeenCalled())
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(ArrayBuffer), '法兰板.stl')

    openMenu()
    fireEvent.click(await screen.findByText('OBJ（网格交换）'))
    await waitFor(() => expect(buildOBJ).toHaveBeenCalled())
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), '法兰板.obj')

    openMenu()
    fireEvent.click(await screen.findByText('GLB（glTF 2.0 预览交付）'))
    await waitFor(() => expect(buildGLB).toHaveBeenCalled())
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), '法兰板.glb'))

    openMenu()
    fireEvent.click(await screen.findByText('三视图 PNG（前 / 上 / 右）'))
    await waitFor(() => expect(captureViews).toHaveBeenCalled())
    // 前上右三张各下载一次
    await waitFor(() => expect(downloadDataURL).toHaveBeenCalledTimes(3))
    expect(downloadDataURL).toHaveBeenCalledWith('f', '法兰板-三视图-前.png')
    expect(downloadDataURL).toHaveBeenCalledWith('t', '法兰板-三视图-上.png')
    expect(downloadDataURL).toHaveBeenCalledWith('r', '法兰板-三视图-右.png')
  })

  it('DesignExportError 显示为警告（如 WebGL 缺失），不视为失败', async () => {
    vi.mocked(captureViews).mockImplementation(() => {
      throw new DesignExportError('当前环境不支持 WebGL')
    })
    renderMenu(IR)
    openMenu()
    fireEvent.click(await screen.findByText('三视图 PNG（前 / 上 / 右）'))
    expect(await screen.findByText('当前环境不支持 WebGL')).toBeInTheDocument()
  })

  it('未知导出异常显示为错误提示', async () => {
    vi.mocked(buildSTL).mockImplementation(() => {
      throw new Error('序列化失败')
    })
    renderMenu(IR)
    openMenu()
    fireEvent.click(await screen.findByText('STL（二进制，3D 打印）'))
    expect(await screen.findByText('序列化失败')).toBeInTheDocument()
  })
})
