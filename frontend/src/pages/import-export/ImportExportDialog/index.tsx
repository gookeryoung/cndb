/** 导入/导出对话框 — Tab 容器：更新（导入）/ 导出.
 *
 * 拆分说明（重构自 1100 行单体）:
 *   ImportPanel.tsx  — 导入全流程（上传 / 预览 / DIFF / 进度轮询 / 数据质量）
 *   ExportPanel.tsx  — 导出（格式选择 / 视图筛选 / Blob 下载）
 *   importPreview.ts — 导入预览纯逻辑（阶段常量 / Diff 列构建 / fmtValue）
 */
import { Modal, Tabs, Button } from 'antd'
import { UploadOutlined, DownloadOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import ImportPanel from './ImportPanel'
import ExportPanel from './ExportPanel'

interface Props {
  open: boolean
  wid: string
  tid: string
  /** 当前表的活动字段列表（用于参考列多选） */
  fields?: Field[]
  onClose: () => void
  /** 导入成功后调用（刷新列表等） */
  onImported?: () => void
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
}

export default function ImportExportDialog({ open, wid, tid, fields, onClose, onImported, viewId, viewName }: Props) {
  return (
    <Modal
      title="更新 / 导出"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={1000}
      destroyOnHidden
    >
      {/* 行着色样式（:where 避免 specificity 冲突） */}
      <style>{`
        tr.diff-row td {
          background: var(--diff-row-bg, transparent) !important;
          border-left: 3px solid var(--diff-row-border, transparent) !important;
        }
      `}</style>
      <Tabs
        items={[
          {
            key: 'import',
            label: <span><UploadOutlined /> 更新</span>,
            children: (
              <ImportPanel
                open={open}
                wid={wid}
                tid={tid}
                fields={fields}
                onClose={onClose}
                onImported={onImported}
              />
            ),
          },
          {
            key: 'export',
            label: <span><DownloadOutlined /> 导出</span>,
            children: <ExportPanel wid={wid} tid={tid} viewId={viewId} viewName={viewName} />,
          },
        ]}
      />
    </Modal>
  )
}
