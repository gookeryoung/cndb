/** 导出对话框 — 独立入口（与「更新」对话框剥离）.
 *
 * 只承载导出：格式选择（默认 XLSX + 记住上次选择）/ 按视图筛选 / XLSX / CSV /
 * JSON / PDF 下载。导入与 API 抓取在 `UpdateDialog`。
 */
import { Modal, Button } from 'antd'
import ExportPanel from './ImportExportDialog/ExportPanel'

interface Props {
  open: boolean
  wid: string
  tid: string
  onClose: () => void
  /** 当前激活的视图 ID（用于按视图筛选导出） */
  viewId?: number | string | null
  /** 当前激活的视图名称（仅用于提示） */
  viewName?: string
  /** 进入 PDF 导出模式（关闭虚拟滚动、全量渲染）并返回视图内容区根元素，resolve 前须等待重渲染完成 */
  getPdfTarget?: () => Promise<HTMLElement | null>
  /** PDF 导出结束后调用（退出导出模式，恢复虚拟滚动） */
  releasePdfTarget?: () => void
}

export default function ExportDialog({ open, wid, tid, onClose, viewId, viewName, getPdfTarget, releasePdfTarget }: Props) {
  return (
    <Modal
      title="导出"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={720}
      destroyOnHidden
    >
      <ExportPanel
        wid={wid}
        tid={tid}
        viewId={viewId}
        viewName={viewName}
        getPdfTarget={getPdfTarget}
        releasePdfTarget={releasePdfTarget}
      />
    </Modal>
  )
}
