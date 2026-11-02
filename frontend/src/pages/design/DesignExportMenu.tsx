/** 设计导出菜单（P2，ADR 0079 D5）：STL / OBJ / GLB + 正交三视图 PNG.
 *
 * 本组件与 PreviewCanvas 同属 three lazy 边界（D4）：exporters 引 three，
 * 不静态 import 进编辑器主 chunk，由 DesignEditorPage 以 lazy 挂载。
 * 网格与预览共用同一 IR 求值路径（renderTree.buildIRMeshes），所见即所得。
 */

import { useState } from 'react'
import { App as AntApp, Button, Dropdown } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { MenuProps } from 'antd'
import type { DesignIR } from '@/api'
import {
  DesignExportError,
  buildGLB,
  buildOBJ,
  buildSTL,
  captureViews,
  downloadBlob,
  downloadDataURL,
  exportMeshesOf,
} from './exporters'

export default function DesignExportMenu({ ir, title }: { ir: DesignIR | null; title: string }) {
  const { message } = AntApp.useApp()
  const [busy, setBusy] = useState(false)

  // 可用性只看 IR 节点（边界 #3）；网格求值（buildIRMeshes 含 CSG，大装配可达数百 ms）
  // 延迟到真正导出时才做（ADR 0086 C9：打开编辑器不允许主线程长任务）
  const empty = !ir || ir.nodes.length === 0

  const onExport = async (kind: 'stl' | 'obj' | 'glb' | 'views') => {
    setBusy(true)
    try {
      const meshes = exportMeshesOf(ir)
      if (kind === 'stl') downloadBlob(buildSTL(meshes), `${title}.stl`)
      else if (kind === 'obj') downloadBlob(new Blob([buildOBJ(meshes)], { type: 'text/plain' }), `${title}.obj`)
      else if (kind === 'glb') downloadBlob(await buildGLB(meshes), `${title}.glb`)
      else {
        const views = captureViews(meshes)
        const names: Record<keyof typeof views, string> = { front: '前', top: '上', right: '右' }
        for (const [view, dataURL] of Object.entries(views)) {
          downloadDataURL(dataURL, `${title}-三视图-${names[view as keyof typeof names]}.png`)
        }
      }
      message.success('已生成导出文件')
    } catch (error) {
      if (error instanceof DesignExportError) message.warning(error.message)
      else message.error(error instanceof Error ? error.message : '导出失败')
    } finally {
      setBusy(false)
    }
  }

  const items: MenuProps['items'] = [
    { key: 'stl', label: 'STL（二进制，3D 打印）' },
    { key: 'obj', label: 'OBJ（网格交换）' },
    { key: 'glb', label: 'GLB（glTF 2.0 预览交付）' },
    { type: 'divider' },
    { key: 'views', label: '三视图 PNG（前 / 上 / 右）' },
  ]

  return (
    <Dropdown
      // 导出是显式动作（触摸设备无 hover），点击触发，对齐 TablesList 卡片菜单先例
      trigger={['click']}
      menu={{ items, onClick: ({ key }) => void onExport(key as 'stl' | 'obj' | 'glb' | 'views') }}
      disabled={empty || busy}
    >
      <Button icon={<DownloadOutlined />} disabled={empty || busy} loading={busy} aria-label="导出">
        导出
      </Button>
    </Dropdown>
  )
}
