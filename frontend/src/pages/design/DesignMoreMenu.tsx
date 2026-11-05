/** 设计编辑器「更多」菜单（ADR 0103 D6）：版本历史 + 导出（STL / OBJ / GLB / 三视图）.
 *
 * 工具栏单行化的溢出收纳：次要动作恒收进菜单（非断点式，D6），保存与编译状态常显。
 * 本组件与 PreviewCanvas 同属 three lazy 边界（ADR 0079 D4）：exporters 引 three，
 * 由 DesignEditorPage 以 lazy 挂载，不进编辑器主 chunk。
 * 网格求值（含 CSG，大装配可达数百 ms）延迟到真正导出时（ADR 0086 C9）。
 */

import { useState } from 'react'
import { App as AntApp, Button, Dropdown } from 'antd'
import { EllipsisOutlined } from '@ant-design/icons'
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

type ExportKind = 'stl' | 'obj' | 'glb' | 'views'

interface Props {
  ir: DesignIR | null
  title: string
  /** 版本数量（菜单项文案「版本历史（N）」） */
  versionCount: number
  /** 打开版本历史抽屉 */
  onHistory: () => void
}

export default function DesignMoreMenu({ ir, title, versionCount, onHistory }: Props) {
  const { message } = AntApp.useApp()
  const [busy, setBusy] = useState(false)

  // 可用性只看 IR 节点（边界 #3）；几何求值延迟到导出动作
  const empty = !ir || ir.nodes.length === 0

  const onExport = async (kind: ExportKind) => {
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
    { key: 'history', label: `版本历史（${versionCount}）` },
    { type: 'divider' },
    {
      type: 'group',
      label: '导出',
      children: [
        { key: 'stl', label: 'STL（二进制，3D 打印）', disabled: empty || busy },
        { key: 'obj', label: 'OBJ（网格交换）', disabled: empty || busy },
        { key: 'glb', label: 'GLB（glTF 2.0 预览交付）', disabled: empty || busy },
        { key: 'views', label: '三视图 PNG（前 / 上 / 右）', disabled: empty || busy },
      ],
    },
  ]

  return (
    <Dropdown
      trigger={['click']}
      menu={{
        items,
        onClick: ({ key }) => {
          if (key === 'history') onHistory()
          else void onExport(key as ExportKind)
        },
      }}
    >
      <Button icon={<EllipsisOutlined />} aria-label="更多" loading={busy}>更多</Button>
    </Dropdown>
  )
}
