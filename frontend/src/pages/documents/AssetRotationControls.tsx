/** 原件方向控件条（ADR 0164 P1/C2）：自动旋转 + 旋转 90° + 水平镜像.
 *
 * 浮在阅读区右上角，不挤压阅读器尺寸；三个按钮同一行，
 * 两个手动按钮并列相邻，自动旋转是独立开关。
 */
import { Button, Tooltip } from 'antd'
import { AimOutlined, RotateRightOutlined, SwapOutlined } from '@ant-design/icons'
import type { AutoOrientationReason } from './assetOrientation'

interface Props {
  autoEnabled: boolean
  onToggleAuto: () => void
  onRotate: () => void
  onFlip: () => void
  /** 派生副本请求中：手动按钮禁用，避免叠加请求 */
  loading?: boolean
  /** 自动判定的依据，用于开关的 tooltip 文案 */
  reason: AutoOrientationReason
  /** 自动判定是否高置信度 */
  confident: boolean
}

const REASON_TEXT: Record<AutoOrientationReason, string> = {
  exif: '已按图片方向信息自动校正',
  'pdf-rotate': '已按 PDF 页面方向标记显示',
  aspect: '已按页面长宽比自动校正',
  none: '未识别到明确方向，可手动调整',
}

export default function AssetRotationControls({
  autoEnabled,
  onToggleAuto,
  onRotate,
  onFlip,
  loading = false,
  reason,
  confident,
}: Props) {
  const autoTip = autoEnabled
    ? `自动旋转已开启：${confident ? REASON_TEXT[reason] : '当前未识别到明确方向，保持原始方向'}`
    : '自动旋转已关闭：按原始方向显示'

  return (
    <div className="cn-asset-rotate-bar" data-testid="doc-rotate-controls">
      <Tooltip title={autoTip}>
        <Button
          size="small"
          type={autoEnabled ? 'primary' : 'default'}
          icon={<AimOutlined />}
          aria-pressed={autoEnabled}
          aria-label="自动旋转"
          data-testid="doc-rotate-auto"
          onClick={onToggleAuto}
        >
          自动旋转
        </Button>
      </Tooltip>
      <span className="cn-asset-rotate-divider" aria-hidden="true" />
      <Tooltip title="顺时针旋转 90°">
        <Button
          size="small"
          icon={<RotateRightOutlined />}
          aria-label="顺时针旋转 90°"
          data-testid="doc-rotate-90"
          disabled={loading}
          onClick={onRotate}
        />
      </Tooltip>
      <Tooltip title="水平镜像翻转">
        <Button
          size="small"
          icon={<SwapOutlined />}
          aria-label="水平镜像翻转"
          data-testid="doc-rotate-flip"
          disabled={loading}
          onClick={onFlip}
        />
      </Tooltip>
    </div>
  )
}
