/** 更新（导入）对话框 — Tab 容器：更新 / API 抓取.
 *
 * 2026 拆分：导出口径已剥离为独立的 `ExportDialog`（不再共用一个 3 Tab 弹窗），
 * 本组件只承载「更新」相关能力。面板说明：
 *   ImportPanel.tsx  — 导入全流程（上传 / 预览 / DIFF / 进度轮询 / 数据质量）
 *   importPreview.ts — 导入预览纯逻辑（阶段常量 / Diff 列构建 / fmtValue）
 *   ApiImportDialog  — API 抓取追加（embed 模式，同目录）
 */
import { Modal, Tabs, Button } from 'antd'
import { UploadOutlined, ApiOutlined } from '@ant-design/icons'
import type { Field } from '@/api'
import ApiImportDialog from './ApiImportDialog'
import ImportPanel from './ImportExportDialog/ImportPanel'

interface Props {
  open: boolean
  wid: string
  tid: string
  /** 当前表的活动字段列表（用于参考列多选） */
  fields?: Field[]
  onClose: () => void
  /** 导入成功后调用（刷新列表等） */
  onImported?: () => void
}

export default function UpdateDialog({ open, wid, tid, fields, onClose, onImported }: Props) {
  return (
    <Modal
      title="更新"
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
        defaultActiveKey="import"
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
            key: 'api',
            label: <span><ApiOutlined /> API 抓取</span>,
            children: (
              <ApiImportDialog
                embed
                wid={wid}
                tid={tid}
                title="API 抓取 · 追加到当前表"
                onSuccess={() => onImported?.()}
              />
            ),
          },
        ]}
      />
    </Modal>
  )
}
