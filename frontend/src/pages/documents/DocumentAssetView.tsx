/** 原件族文档阅读器（ADR 0025）：PDF / 图片 / MHTML / PPTX 直接渲染，其余 Office 给下载卡.
 *
 * 原件经带鉴权头的接口取回为 blob，再挂 objectURL —— 不用裸链接，
 * 否则未发布草稿的原件会绕过文档可见性。
 * MHTML（0064）：浏览器不渲染 multipart/related，改用后端自包含 HTML + 沙箱 iframe；
 * Excel（0087）/ Word archive（0087）：后端自包含 HTML 走 ``OfficeHtmlPreview``（Shadow DOM 内联），
 * 与 PPTX 一样只保留正文区一条滚动条，不再多一层 iframe 视口；下载仍走原件接口。
 * PPTX：先纯前端渲染（PptxPreview 懒加载）保证首屏；服务端 PDF 就绪后原位替换为
 * PDF iframe（ADR 0129），转换不可用 / 失败时静默保留客户端预览。旧版 .ppt 仍回落下载卡。
 */
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Spin } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi, type DocumentItem } from '@/api/documents'
import { formatMeta } from '@/components/Document/docFormat'
import OfficeHtmlPreview from './OfficeHtmlPreview'
import AssetRotationControls from './AssetRotationControls'
import RotatableImage from './RotatableImage'
import {
  combineOrientations,
  detectAutoOrientation,
  isDefaultOrientation,
  readExifOrientation,
  rotateBy,
  toggleFlip,
  type Orientation,
} from './assetOrientation'
import {
  isPreviewablePptx, PPTX_ASSET_GC_MS, PPTX_ASSET_STALE_MS,
} from './pptxLoader'
import { fetchPptxPdf, requestPptxPdf, type PptxPdfState } from './pptxPdf'

// PPTX 渲染库体积较大（jszip / echarts），只在打开 .pptx 时按需加载
const PptxPreview = lazy(() => import('./PptxPreview'))
const PptxSlideshow = lazy(() => import('./PptxSlideshow'))

interface Props {
  workspaceId: number
  doc: DocumentItem
  /** PPTX 放映覆盖层是否打开（按钮在文档页顶栏，状态由页面持有） */
  presenting?: boolean
  onPresentingChange?: (presenting: boolean) => void
}

/** 扩展名：优先用后端 MIME，缺失时退回 content_type（顶栏下载按钮与下载卡共用） */
export function assetSuffix(doc: DocumentItem): string {
  const mime = doc.asset_mime ?? ''
  const byMime: Record<string, string> = {
    'application/pdf': 'pdf',
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'image/bmp': 'bmp',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.ms-powerpoint': 'ppt',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
  }
  if (byMime[mime]) return byMime[mime]
  if (doc.content_type === 'xlsx') return 'xlsx'
  if (doc.content_type === 'pptx') return 'pptx'
  if (doc.content_type === 'word') return 'docx'
  return ''
}

export default function DocumentAssetView({
  workspaceId,
  doc,
  presenting = false,
  onPresentingChange,
}: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [retryingPdf, setRetryingPdf] = useState(false)
  const queryClient = useQueryClient()
  const fmt = formatMeta(doc.content_type)
  const suffix = assetSuffix(doc)
  const isMhtml = doc.content_type === 'mhtml'
  // 仅标准 OOXML .pptx 可纯前端渲染；旧版二进制 .ppt 没有 zip 结构，仍下载查看
  const isPptx = isPreviewablePptx(doc)
  // Excel / Word 预览走后端 HTML：仅标准 .xlsx 与 archive 存档的 .docx；
  // 旧版二进制 .xls / .doc 保持下载卡（后端也会 400）
  const isOfficePreview = (doc.content_type === 'xlsx' && suffix === 'xlsx') || doc.content_type === 'word'
  const isPdfAsset = doc.content_type === 'pdf'
  const isImageAsset = doc.content_type === 'image'

  // 方向状态（ADR 0164）：自动旋转默认开启；手动调整叠加在自动基线之上，切文档重置
  const [autoEnabled, setAutoEnabled] = useState(true)
  const [manualOrientation, setManualOrientation] = useState<Orientation>({ rotate: 0, flip: false })
  const [exifOrientation, setExifOrientation] = useState<number | null>(null)
  const [imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const [viewport, setViewport] = useState({ width: 0, height: 0 })
  const [rotateNotice, setRotateNotice] = useState<string | null>(null)
  const viewerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setAutoEnabled(true)
    setManualOrientation({ rotate: 0, flip: false })
    setExifOrientation(null)
    setImageNaturalSize(null)
    setRotateNotice(null)
  }, [workspaceId, doc.id])

  // 阅读区尺寸用于长宽比兜底判定（横置页面 + 竖置阅读区）
  useEffect(() => {
    const node = viewerRef.current
    if (!node) return
    const measure = () => setViewport({ width: node.clientWidth, height: node.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const assetQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset'],
    queryFn: () => documentsApi.assetBlob(workspaceId, doc.id),
    retry: false,
    // 大原件在文档页卸载 / 重挂载时优先命中内存缓存（需求 0128 C4）
    staleTime: PPTX_ASSET_STALE_MS,
    gcTime: PPTX_ASSET_GC_MS,
  })

  // 服务端 PDF 衍生预览（ADR 0129）：与原件并行请求；未就绪不阻塞客户端预览。
  // 轮询中间态由 onState 实时回传，promise 只在链路结束时 resolve。
  const [pdfLiveState, setPdfLiveState] = useState<PptxPdfState | undefined>(undefined)
  const pdfQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-pdf'],
    queryFn: ({ signal }) => fetchPptxPdf(workspaceId, doc.id, { signal, onState: setPdfLiveState }),
    retry: false,
    enabled: isPptx,
    staleTime: PPTX_ASSET_STALE_MS,
    gcTime: PPTX_ASSET_GC_MS,
  })
  // 切换文档时清掉上一份的实时态，避免短暂误显示 pending / 重试入口
  useEffect(() => {
    setPdfLiveState(undefined)
  }, [workspaceId, doc.id])

  // MHTML 预览取 blob（沙箱 iframe）；Office 预览取文本（Shadow DOM 内联）
  const previewQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-preview'],
    queryFn: () => documentsApi.assetPreviewBlob(workspaceId, doc.id),
    retry: false,
    enabled: isMhtml,
  })
  const officePreviewQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-preview-text'],
    queryFn: () => documentsApi.assetPreviewText(workspaceId, doc.id),
    retry: false,
    enabled: isOfficePreview,
  })

  const blob = assetQuery.data
  useEffect(() => {
    if (!blob) {
      setObjectUrl(null)
      return
    }
    const url = URL.createObjectURL(blob)
    setObjectUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [blob])

  // 图片 EXIF 方向：显式关闭浏览器原生方向后由本功能单点应用（ADR 0164 D5 / I2）
  useEffect(() => {
    let cancelled = false
    setExifOrientation(null)
    setImageNaturalSize(null)
    if (!blob || doc.content_type !== 'image') return
    blob
      .arrayBuffer()
      .then(buffer => {
        if (!cancelled) setExifOrientation(readExifOrientation(buffer))
      })
      .catch(() => {
        if (!cancelled) setExifOrientation(null)
      })
    return () => {
      cancelled = true
    }
  }, [blob, doc.content_type])

  // PDF 页面方向信息（P0 端点）：仅 PDF 原件请求，失败按「无信息」处理
  const orientationQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-orientation'],
    queryFn: () => documentsApi.assetOrientation(workspaceId, doc.id),
    retry: false,
    enabled: isPdfAsset,
    staleTime: PPTX_ASSET_STALE_MS,
    gcTime: PPTX_ASSET_GC_MS,
  })

  const autoResult = useMemo(
    () =>
      detectAutoOrientation({
        kind: isPdfAsset ? 'pdf' : 'image',
        exifOrientation,
        imageSize: imageNaturalSize,
        pdf: isPdfAsset ? (orientationQuery.data ?? null) : null,
        viewport,
      }),
    [isPdfAsset, exifOrientation, imageNaturalSize, orientationQuery.data, viewport],
  )

  const orientation: Orientation = autoEnabled
    ? combineOrientations(autoResult.orientation, manualOrientation)
    : manualOrientation
  const rotatedEnabled = isPdfAsset && !isDefaultOrientation(orientation)

  // 派生副本：方向非默认时向服务端取旋转 / 镜像后的 PDF（不改原件，ADR 0164 C5）
  const rotatedQuery = useQuery({
    queryKey: ['documents', workspaceId, doc.id, 'asset-rotated', orientation.rotate, orientation.flip],
    queryFn: ({ signal }) =>
      documentsApi.assetRotated(workspaceId, doc.id, orientation.rotate, orientation.flip, signal),
    retry: false,
    enabled: rotatedEnabled,
    staleTime: PPTX_ASSET_STALE_MS,
    gcTime: PPTX_ASSET_GC_MS,
    placeholderData: previous => previous,
  })
  const rotatedBlob = rotatedEnabled ? rotatedQuery.data : undefined
  const [rotatedUrl, setRotatedUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!rotatedBlob) {
      setRotatedUrl(null)
      return
    }
    const url = URL.createObjectURL(rotatedBlob)
    setRotatedUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [rotatedBlob])

  useEffect(() => {
    setRotateNotice(rotatedQuery.isError ? '该 PDF 无法旋转，已保留上一次可用方向' : null)
  }, [rotatedQuery.isError])

  const pdfViewerUrl = rotatedUrl ?? objectUrl

  const toggleAutoRotate = () => {
    setAutoEnabled(previous => !previous)
    setManualOrientation({ rotate: 0, flip: false })
  }
  const rotateViewer = () => setManualOrientation(previous => rotateBy(previous, 90))
  const flipViewer = () => setManualOrientation(previous => toggleFlip(previous))

  const previewBlob = previewQuery.data
  useEffect(() => {
    if (!previewBlob) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(previewBlob)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [previewBlob])

  // PDF 衍生件到位后切换 iframe；objectURL 在切换 / 卸载时释放
  const pdfBlob = pdfQuery.data?.blob
  useEffect(() => {
    if (!pdfBlob) {
      setPdfUrl(null)
      return
    }
    const url = URL.createObjectURL(pdfBlob)
    setPdfUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [pdfBlob])

  const pdfState = pdfLiveState ?? pdfQuery.data?.state
  const pdfReady = pdfState === 'ready' && Boolean(pdfUrl)

  /** 手动重试一次转换：POST 只触发，随后重新读取最新状态 */
  const retryPdf = async () => {
    setRetryingPdf(true)
    try {
      await requestPptxPdf(workspaceId, doc.id)
    } catch {
      // PDF 是增强路径：重试失败静默保留客户端预览
    } finally {
      setRetryingPdf(false)
    }
    await queryClient.invalidateQueries({ queryKey: ['documents', workspaceId, doc.id, 'asset-pdf'] })
  }

  const officeHtml = officePreviewQuery.data
  const loading = isMhtml
    ? previewQuery.isLoading
    : isOfficePreview
      ? officePreviewQuery.isLoading
      : assetQuery.isLoading
  // Office 预览失败（损坏 / 加密）不吞成「原件缺失」：退化为下载卡，原件仍可取
  const officePreviewFailed = isOfficePreview && (officePreviewQuery.isError || !officeHtml)
  const failed = isMhtml
    ? previewQuery.isError || !previewUrl
    : officePreviewFailed
      ? false
      : assetQuery.isError || !objectUrl

  const downloadName = useMemo(() => `${doc.title || 'download'}${suffix ? `.${suffix}` : ''}`, [doc.title, suffix])

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (failed) {
    return (
      <div style={{ padding: 24 }} data-testid="doc-asset-error">
        <Alert
          type="warning"
          showIcon
          title="原件缺失或无法读取"
          description="该文档的原件可能已被清理，请联系上传者重新导入。"
        />
      </div>
    )
  }

  const viewer = (() => {
    if (isPdfAsset) {
      return (
        <iframe
          title={doc.title}
          src={pdfViewerUrl ?? undefined}
          data-testid="doc-asset-pdf"
          style={{ flex: 1, minHeight: 0, width: '100%', border: 'none' }}
        />
      )
    }
    if (isImageAsset) {
      // 可旋转 / 镜像阅读器：方向由本组件单点应用（ADR 0164 D5），SVG 仍走 <img> 不执行脚本
      return (
        <RotatableImage
          src={objectUrl ?? ''}
          alt={doc.title}
          orientation={orientation}
          onNaturalSize={setImageNaturalSize}
        />
      )
    }
    if (isPptx && blob) {
      // 服务端 PDF 就绪后原位替换；否则始终保留 0128 客户端逐页预览（ADR 0129 D10）
      if (pdfReady) {
        return (
          <iframe
            title={doc.title}
            src={pdfUrl ?? undefined}
            data-testid="doc-asset-pptx-pdf"
            style={{ flex: 1, minHeight: 0, width: '100%', border: 'none' }}
          />
        )
      }
      return (
        <>
          <Suspense fallback={(
            <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Spin />
            </div>
          )}
          >
            <PptxPreview blob={blob} title={doc.title} />
          </Suspense>
          {pdfState === 'pending' && (
            <div
              data-testid="doc-pptx-pdf-pending"
              style={{
                position: 'absolute',
                right: 24,
                bottom: 20,
                padding: '4px 10px',
                borderRadius: 12,
                background: 'rgba(0, 0, 0, 0.6)',
                color: '#fff',
                fontSize: 12,
                pointerEvents: 'none',
              }}
            >
              正在生成高清预览…
            </div>
          )}
          {(pdfState === 'failed' || pdfState === 'busy') && (
            <Button
              type="link"
              size="small"
              loading={retryingPdf}
              onClick={() => void retryPdf()}
              data-testid="doc-pptx-pdf-retry"
              style={{ position: 'absolute', right: 16, bottom: 12 }}
            >
              重试高清预览
            </Button>
          )}
        </>
      )
    }
    if (isMhtml) {
      // MHTML 预览（0064 C3）：后端自包含 HTML，沙箱 iframe 渲染——
      // sandbox 空值 = 禁脚本、禁同源、禁表单；网页存档视为不可信内容
      return (
        <iframe
          title={doc.title}
          src={previewUrl ?? undefined}
          sandbox=""
          data-testid="doc-asset-mhtml"
          style={{ flex: 1, minHeight: 0, width: '100%', border: 'none' }}
        />
      )
    }
    if (isOfficePreview && !officePreviewFailed && officeHtml) {
      // Excel / Word 预览（0087 C1/C3）：后端自包含 HTML 内联到 Shadow DOM，
      // 正文区只保留一条滚动条（与 PPTX 一致）；失败时落到下面的下载卡
      return <OfficeHtmlPreview html={officeHtml} />
    }
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          isOfficePreview
            ? `${fmt.label} 原件无法在线预览，请下载后查看`
            : `${fmt.label} 文件不支持在线预览，请下载后查看`
        }
        style={{ marginTop: 64 }}
        data-testid="doc-asset-download-card"
      >
        <Button type="primary" icon={<DownloadOutlined />} href={objectUrl ?? undefined} download={downloadName}>
          下载原件
        </Button>
      </Empty>
    )
  })()

  return (
    <div
      ref={viewerRef}
      style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '12px 24px', position: 'relative' }}
      data-testid="doc-asset-view"
    >
      {viewer}
      {Boolean(objectUrl) && (isPdfAsset || isImageAsset) && (
        <AssetRotationControls
          autoEnabled={autoEnabled}
          onToggleAuto={toggleAutoRotate}
          onRotate={rotateViewer}
          onFlip={flipViewer}
          loading={rotatedQuery.isFetching}
          reason={autoResult.reason}
          confident={autoResult.confident}
        />
      )}
      {isPdfAsset && rotatedQuery.isFetching && (
        <div className="cn-asset-rotate-loading" data-testid="doc-rotate-loading">
          <Spin size="small" />
        </div>
      )}
      {rotateNotice && (
        <div className="cn-asset-rotate-notice" data-testid="doc-rotate-error">
          {rotateNotice}
        </div>
      )}
      {presenting && blob && (
        <Suspense fallback={null}>
          <PptxSlideshow
            blob={blob}
            title={doc.title}
            storageKey={`pptx-present-page:${workspaceId}:${doc.id}`}
            onClose={() => onPresentingChange?.(false)}
          />
        </Suspense>
      )}
    </div>
  )
}
