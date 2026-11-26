/** 可旋转 / 镜像的图片阅读器（ADR 0164 P1）.
 *
 * 只做显示层变换：`<img>` 显式 `image-orientation: none`，方向完全由本组件按
 * `(rotate, flip)` 应用（ADR 0164 D5 / I2），避免与浏览器原生 EXIF 叠加。
 * 尺寸按「旋转后包围盒 + contain」计算，90°/270° 时不裁切、不溢出。
 */
import { useEffect, useRef, useState } from 'react'
import { orientationTransform, type Orientation } from './assetOrientation'

interface Props {
  src: string
  alt: string
  orientation: Orientation
  onNaturalSize?: (size: { width: number; height: number }) => void
}

interface Size {
  width: number
  height: number
}

export default function RotatableImage({ src, alt, orientation, onNaturalSize }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [stage, setStage] = useState<Size>({ width: 0, height: 0 })
  const [natural, setNatural] = useState<Size | null>(null)

  useEffect(() => {
    const node = stageRef.current
    if (!node) return
    const measure = () => {
      setStage({ width: node.clientWidth, height: node.clientHeight })
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const swapped = orientation.rotate === 90 || orientation.rotate === 270
  const layout = (() => {
    if (!natural || !stage.width || !stage.height) return null
    const boxWidth = swapped ? natural.height : natural.width
    const boxHeight = swapped ? natural.width : natural.height
    const scale = Math.min(stage.width / boxWidth, stage.height / boxHeight, 1)
    return {
      frameWidth: boxWidth * scale,
      frameHeight: boxHeight * scale,
      imageWidth: natural.width * scale,
      imageHeight: natural.height * scale,
    }
  })()

  return (
    <div className="cn-asset-image-stage" ref={stageRef} data-testid="doc-asset-image-stage">
      {layout ? (
        <div
          className="cn-asset-image-frame"
          style={{ width: layout.frameWidth, height: layout.frameHeight }}
        >
          <img
            src={src}
            alt={alt}
            data-testid="doc-asset-image"
            draggable={false}
            style={{
              width: layout.imageWidth,
              height: layout.imageHeight,
              transform: `translate(-50%, -50%) ${orientationTransform(orientation)}`,
              imageOrientation: 'none',
            }}
          />
        </div>
      ) : (
        <img
          src={src}
          alt={alt}
          data-testid="doc-asset-image"
          draggable={false}
          style={{
            maxWidth: '100%',
            maxHeight: '100%',
            objectFit: 'contain',
            transform: orientationTransform(orientation),
            imageOrientation: 'none',
          }}
          onLoad={event => {
            const image = event.currentTarget
            const size = { width: image.naturalWidth, height: image.naturalHeight }
            if (size.width > 0 && size.height > 0) {
              setNatural(size)
              onNaturalSize?.(size)
            }
          }}
        />
      )}
    </div>
  )
}
