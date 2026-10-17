/** 网格内图片字段浮层编辑器 —— 双击单元格后以 Popover 展开，不撑高行.
 *
 * 为什么单独做：表格列宽通常 160px 左右，内联放不下 64px 瓦片 + 拖拽排序；
 * 浮层可以复用 `ImageFieldEditor` 的「大图模式（comfortable）」：更大的缩略图、
 * 逐图替换、拖拽排序，同时行高保持不变。
 *
 * 提交语义：浮层内改动只写草稿（受控），「完成」触发外层保存，关闭浮层 / 取消
 * 则回滚草稿 —— 与普通单元格双击编辑的保存/取消语义一致。
 */

import { useState } from 'react'
import { Button, Popover } from 'antd'
import type { AttachmentFile, Field } from '@/api'
import { DisplayCell } from './DisplayCell'
import { ImageFieldEditor } from './ImageFieldEditor'

interface Props {
  wid?: number | string
  tableId?: number | string
  rowId: number | string
  field: Field
  /** 当前草稿值（AttachmentFile[] 或 JSON 字符串） */
  value: unknown
  onChange: (value: unknown) => void
  /** 「完成」→ 交由外层保存并退出编辑 */
  onCommit: () => void
  /** 取消 / 点击浮层外 → 回滚草稿并退出编辑 */
  onCancel: () => void
  saving?: boolean
}

export function ImageCellEditor({
  wid,
  tableId,
  rowId,
  field,
  value,
  onChange,
  onCommit,
  onCancel,
  saving,
}: Props) {
  const [open, setOpen] = useState(true)

  const cancel = () => {
    setOpen(false)
    onCancel()
  }

  return (
    <Popover
      open={open}
      onOpenChange={next => {
        // 点击浮层外部：按「取消」处理；受控模式下重新点单元格可再次打开
        if (next) setOpen(true)
        else cancel()
      }}
      trigger="click"
      placement="bottomLeft"
      content={(
        <div
          className="cn-image-cell-popover"
          data-testid="image-cell-popover"
          onKeyDown={e => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              cancel()
            }
          }}
        >
          <ImageFieldEditor
            wid={wid}
            tableId={tableId}
            rowId={rowId}
            field={field}
            value={value}
            onChange={(images: AttachmentFile[]) => onChange(images)}
            thumbSize={64}
          />
          <div className="cn-image-cell-popover__foot">
            <Button size="small" onClick={cancel}>取消</Button>
            <Button size="small" type="primary" loading={saving} onClick={onCommit}>完成</Button>
          </div>
        </div>
      )}
    >
      <div className="cn-image-cell-editor" onClick={e => e.stopPropagation()}>
        <DisplayCell value={value} field={field} rowId={rowId} wid={wid} />
      </div>
    </Popover>
  )
}
