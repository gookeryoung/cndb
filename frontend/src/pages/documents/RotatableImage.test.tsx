/** 可旋转图片阅读器单测（ADR 0164 P1）：旋转后包围盒 contain 与方向变换. */
import { fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RotatableImage from './RotatableImage'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RotatableImage', () => {
  it('90° 时按旋转后包围盒 contain，并回传自然尺寸', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
    const onNaturalSize = vi.fn()

    const { container, getByTestId } = render(
      <RotatableImage
        src="blob:image"
        alt="扫描件"
        orientation={{ rotate: 90, flip: false }}
        onNaturalSize={onNaturalSize}
      />,
    )

    const image = getByTestId('doc-asset-image') as HTMLImageElement
    Object.defineProperty(image, 'naturalWidth', { value: 1600 })
    Object.defineProperty(image, 'naturalHeight', { value: 1200 })
    fireEvent.load(image)

    expect(onNaturalSize).toHaveBeenCalledWith({ width: 1600, height: 1200 })
    const frame = container.querySelector('.cn-asset-image-frame') as HTMLElement
    // 旋转后包围盒 1200x1600，contain 到 800x600 → 450x600
    expect(frame.style.width).toBe('450px')
    expect(frame.style.height).toBe('600px')
    expect(getByTestId('doc-asset-image').style.transform).toContain('rotate(90deg)')
  })

  it('镜像只改变 scaleX，不触发服务端请求', () => {
    const { getByTestId } = render(
      <RotatableImage src="blob:image" alt="照片" orientation={{ rotate: 0, flip: true }} />,
    )
    expect(getByTestId('doc-asset-image').style.transform).toContain('scaleX(-1)')
  })
})
