/** 复用模块只读页（ADR 0118 P1）
 *
 * 路径 `/w/:wid/design/library/:moduleId`：模块头 + 版本切换 + 参数覆盖 + DSL 只读 + 3D 预览。
 * 私有 / 归档模块由 `?designId=` 走既有引用授权（design_libraryref），否则后端 404。
 * 页面无编辑入口：版本不可变，修改走原设计重新发布（§4）。
 */

import { lazy, Suspense, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button, Empty, InputNumber, Select, Skeleton, Space, Spin, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, BookOutlined } from '@ant-design/icons'
import { designLibraryApi } from '@/api'
import type { LibraryModuleItem } from '@/api'

const PreviewCanvas = lazy(() => import('./PreviewCanvas'))

const { Text, Title } = Typography

export default function LibraryModulePage() {
  const { wid = '', moduleId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const designId = searchParams.get('designId') ?? undefined

  const detailQuery = useQuery({
    queryKey: ['design-library', wid, moduleId, designId ?? ''],
    queryFn: () => designLibraryApi.get(wid, moduleId, designId),
    enabled: !!wid && !!moduleId,
  })

  const [pickedVersion, setPickedVersion] = useState<number | null>(null)
  const detail = detailQuery.data
  const versions = detail?.versions ?? []
  const versionNumber = pickedVersion ?? detail?.latest_version ?? 0

  const versionQuery = useQuery({
    queryKey: ['design-library', wid, moduleId, versionNumber, 'version', designId ?? ''],
    queryFn: () => designLibraryApi.getVersion(wid, moduleId, versionNumber, designId),
    enabled: !!wid && !!moduleId && versionNumber > 0,
  })

  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const params = useMemo(() => versionQuery.data?.params ?? [], [versionQuery.data?.params])
  const effectiveOverrides = useMemo(() => {
    const next: Record<string, number> = {}
    for (const param of params) {
      const value = overrides[param.name]
      if (value !== undefined) next[param.name] = value
    }
    return next
  }, [params, overrides])

  const previewQuery = useQuery({
    queryKey: [
      'design-library', wid, moduleId, versionNumber, 'preview', effectiveOverrides, designId ?? '',
    ],
    queryFn: () => designLibraryApi.preview(
      wid,
      moduleId,
      versionNumber,
      { overrides: Object.keys(effectiveOverrides).length > 0 ? effectiveOverrides : null },
      designId,
    ),
    enabled: !!wid && !!moduleId && versionNumber > 0,
  })

  if (detailQuery.isLoading) {
    return <div className="cn-state" data-testid="library-detail-loading"><Spin /></div>
  }
  if (detailQuery.isError || !detail) {
    return (
      <div className="cn-state" data-testid="library-detail-error">
        <Empty description="模块不存在或无权查看" />
      </div>
    )
  }

  const module = detail as LibraryModuleItem
  const preview = previewQuery.data
  const currentVersion = versionQuery.data

  return (
    <div data-testid="library-module-page" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px',
          borderBottom: '1px solid var(--cn-border-color, #f0f0f0)', flexWrap: 'wrap',
        }}
      >
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(`/w/${wid}/design`)}
        >
          返回模块库
        </Button>
        <BookOutlined />
        <Title level={5} style={{ margin: 0 }}>{module.name}</Title>
        <Text type="secondary" code>{module.module_key}</Text>
        <Tag variant="filled" color={module.visibility === 'public' ? 'green' : 'default'}>
          {module.visibility === 'public' ? '公开' : '私有'}
        </Tag>
        {module.is_archived && <Tag color="red" variant="filled">已归档</Tag>}
        <Space size={6}>
          <Text type="secondary">版本</Text>
          <Select
            size="small"
            style={{ width: 110 }}
            value={versionNumber}
            onChange={value => {
              setPickedVersion(value)
              setOverrides({})
            }}
            options={versions.map(item => ({
              value: item.version_number,
              label: `v${item.version_number}`,
            }))}
            data-testid="library-version-select"
          />
        </Space>
        {params.map(param => (
          <Space key={param.name} size={4}>
            <Text type="secondary">{param.name}</Text>
            <InputNumber
              size="small"
              style={{ width: 90 }}
              value={overrides[param.name] ?? param.default}
              onChange={value => setOverrides(prev => ({
                ...prev,
                [param.name]: typeof value === 'number' ? value : param.default,
              }))}
            />
          </Space>
        ))}
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <div style={{ flex: '0 0 42%', minWidth: 260, overflow: 'auto', borderRight: '1px solid var(--cn-border-color, #f0f0f0)' }}>
          <Spin spinning={versionQuery.isLoading}>
            {currentVersion ? (
              <>
                {currentVersion.comment && (
                  <div style={{ padding: '8px 16px' }}>
                    <Text type="secondary">{currentVersion.comment}</Text>
                  </div>
                )}
                {currentVersion.files.length > 0 && (
                  <div style={{ padding: '0 16px 8px' }}>
                    <Text type="secondary">依赖：</Text>
                    {currentVersion.files.map(file => (
                      <Tag key={file.file_key} variant="filled">{file.file_key}</Tag>
                    ))}
                  </div>
                )}
                <pre
                  data-testid="library-dsl-content"
                  style={{ margin: 0, padding: 16, fontSize: 12, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}
                >
                  {currentVersion.content}
                </pre>
              </>
            ) : (
              <div className="cn-state"><Empty description="版本内容加载失败" /></div>
            )}
          </Spin>
        </div>
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          {preview?.ok && preview.ir ? (
            <Suspense fallback={<Skeleton active style={{ height: '100%' }} />}>
              <PreviewCanvas ir={preview.ir} />
            </Suspense>
          ) : (
            <div className="cn-state" data-testid="library-preview-error">
              <Empty description={preview?.diagnostics?.[0]?.message ?? '预览不可用'} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
