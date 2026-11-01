/** 设计编辑器页 —— DSL 源码（CodeMirror）+ 3D 实时预览（three.js）+ 参数面板.
 *
 * 数据流（ADR 0079 I1/D3/D4）：
 * - 编辑防抖 300ms → POST /designs/preview（无落库）→ 结构化诊断回显错误行；
 * - 渲染只消费后端编译的 IR（前端零解析零求值），three 相关全部在 lazy chunk；
 * - 保存：编译在后端通过才落库并落新版本，失败保留草稿（边界 #2）；
 * - P2：版本历史支持回看（Drawer 看原文）与恢复（旧版重编译落新版本）；
 *   导出（STL / OBJ / GLB / 三视图）与 PreviewCanvas 同属 lazy 边界（D4/D5）。
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, InputNumber, Popconfirm, Skeleton, Space, Spin, Tag, Typography,
} from 'antd'
import type { InputNumberProps } from 'antd'
import {
  ArrowLeftOutlined, ExperimentOutlined, HistoryOutlined, RollbackOutlined, SaveOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignDiagnostic, DesignVersionItem } from '@/api'
import { formatDateTime } from '@/utils/datetime'
import DslEditor from './DslEditor'
import { useDesignPreview } from './useDesignPreview'

// three 渲染整块 lazy：three + three-bvh-csg 只进设计编辑器 chunk（D4 体积预算）
const PreviewCanvas = lazy(() => import('./PreviewCanvas'))
// 导出菜单同样落在 three lazy 边界（exporters 引 three，D5）
const DesignExportMenu = lazy(() => import('./DesignExportMenu'))

const { Text } = Typography

export default function DesignEditorPage() {
  const { wid = '', designId = '' } = useParams<{ wid: string; designId: string }>()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()

  const { data: detail, isLoading } = useQuery({
    queryKey: ['designs', wid, designId],
    queryFn: () => designsApi.get(wid, designId),
    enabled: !!wid && !!designId,
  })

  const { data: wsDetail } = useQuery({
    queryKey: ['workspace-detail', wid],
    queryFn: () => workspaceApi.get(wid),
    enabled: !!wid,
  })
  const isViewer = wsDetail?.current_user_role === 'viewer'

  const [content, setContent] = useState('')
  const [contentReady, setContentReady] = useState(false)
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [saveError, setSaveError] = useState('')
  // 详情到达只回填一次（此后编辑权归用户；保存成功后 dirty 归零再回填最新态）
  const [loadedId, setLoadedId] = useState('')
  useEffect(() => {
    if (detail && loadedId !== String(detail.id)) {
      setContent(detail.content)
      setLoadedId(String(detail.id))
      setContentReady(true)
    }
  }, [detail, loadedId])

  const dirty = contentReady && detail != null && content !== detail.content
  const preview = useDesignPreview(wid, content, overrides, { enabled: contentReady })

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['designs', wid] })
  }, [queryClient, wid])

  const save = useMutation({
    mutationFn: () => designsApi.saveContent(wid, designId, { content }),
    onSuccess: (saved) => {
      message.success(`已保存为第 ${saved.version_number} 版`)
      setSaveError('')
      setContent(saved.content)
      invalidate()
    },
    onError: (err) => {
      // 保存被拒但内容不丢（边界 #2）：草稿保留在编辑器，错误详情在页头回显
      setSaveError(err instanceof Error ? err.message : '保存失败')
    },
  })

  const { data: versions = [] } = useQuery({
    queryKey: ['designs', wid, designId, 'versions'],
    queryFn: () => designsApi.listVersions(wid, designId),
    enabled: !!wid && !!designId,
  })

  // 版本回看（P2）：点击历史版本打开 Drawer 看该版原文
  const [viewingVersion, setViewingVersion] = useState<DesignVersionItem | null>(null)
  const { data: viewingDetail, isLoading: viewingLoading } = useQuery({
    queryKey: ['designs', wid, designId, 'versions', viewingVersion?.version_number],
    queryFn: () => designsApi.getVersion(wid, designId, viewingVersion!.version_number),
    enabled: viewingVersion != null,
  })

  // 版本恢复（P2）：以历史版原文重编译保存为新版本（viewer 不可用）
  const restore = useMutation({
    mutationFn: () => designsApi.restoreVersion(wid, designId, viewingVersion!.version_number),
    onSuccess: (restored) => {
      message.success(`已恢复 v${viewingVersion?.version_number} 为第 ${restored.version_number} 版`)
      setViewingVersion(null)
      setContent(restored.content)
      setOverrides({})
      setSaveError('')
      invalidate()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '恢复失败')
    },
  })

  // Ctrl+S 保存（编辑器与全局快捷键都走到这里）
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        if (dirty && !isViewer && !save.isPending) save.mutate()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  /** 参数面板：当前 IR 的参数（改参即重编译，D3 —— 前端不做任何求值） */
  const params = preview.ir?.params ?? []
  const onParamChange = (name: string, value: InputNumberProps['value']) => {
    setOverrides(prev => {
      const next = { ...prev }
      if (value == null || Number.isNaN(value)) delete next[name]
      else next[name] = Number(value)
      return next
    })
  }

  const diagnostics: DesignDiagnostic[] = useMemo(() => preview.diagnostics, [preview.diagnostics])
  const canSave = dirty && !isViewer && !preview.compiling

  return (
    <div style={{ padding: '12px 16px', height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <Space size={8} wrap>
          <Link to={`/w/${wid}/design`}><Button icon={<ArrowLeftOutlined />} type="text" /></Link>
          <Text strong style={{ fontSize: 17 }}>{detail?.title ?? '设计'}</Text>
          {detail && <Tag style={{ marginInlineEnd: 0 }}>v{detail.version_number}</Tag>}
          {dirty && <Tag color="warning" style={{ marginInlineEnd: 0 }}>未保存</Tag>}
          {isViewer && <Tag color="default" style={{ marginInlineEnd: 0 }}>只读</Tag>}
        </Space>
        <Space size={8}>
          <Suspense fallback={null}>
            <DesignExportMenu ir={preview.ir} title={detail?.title ?? '设计'} />
          </Suspense>
          <Button
            icon={<SaveOutlined />}
            type="primary"
            disabled={!canSave}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            保存{dirty ? '' : '（无变更）'}
          </Button>
        </Space>
      </div>

      {saveError && (
        <Alert
          type="error"
          showIcon
          message="保存被拒绝（草稿已保留）"
          description={saveError}
          closable
          onClose={() => setSaveError('')}
        />
      )}

      <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0, flexWrap: 'wrap' }}>
        {/* 左：源码 + 诊断 */}
        <div style={{ flex: '1 1 380px', minWidth: 320, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
          <div className="cn-dsl-editor-host" style={{ flex: 1, minHeight: 260, overflow: 'hidden' }}>
            {isLoading ? <Skeleton active /> : (
              <DslEditor
                value={content}
                onChange={(next) => { setContent(next); setSaveError('') }}
                diagnostics={diagnostics}
                placeholder="param width = 80&#10;box(size = [width, 40, 12])"
                readOnly={isViewer}
              />
            )}
          </div>
          <div style={{ maxHeight: 160, overflow: 'auto' }}>
            {preview.compiling && <Spin size="small" />}
            {!preview.compiling && diagnostics.length === 0 && (
              <Text type="secondary">
                <ExperimentOutlined /> 编译通过{preview.ir && preview.ir.nodes.length === 0 && '（顶层尚无实例）'}
              </Text>
            )}
            {diagnostics.map((item, index) => (
              <div key={`${item.line}-${item.col}-${index}`} className="cn-dsl-diag-item">
                <Tag color="error" style={{ marginInlineEnd: 4 }}>第{item.line}行</Tag>
                <Text type="danger">{item.message}</Text>
              </div>
            ))}
          </div>
        </div>

        {/* 右：预览 + 参数面板 */}
        <div style={{ flex: '1 1 420px', minWidth: 320, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
          <div className="cn-dsl-preview-host" style={{ flex: 1, minHeight: 300, position: 'relative' }}>
            <Suspense fallback={<Skeleton active style={{ height: '100%' }} />}>
              <PreviewCanvas ir={preview.ir} />
            </Suspense>
          </div>
          {params.length > 0 && (
            <div className="cn-dsl-params">
              <Space size={12} wrap align="center">
                <Text type="secondary">参数：</Text>
                {params.map(param => (
                  <Space key={param.name} size={4}>
                    <Text code>{param.name}</Text>
                    <InputNumber
                      size="small"
                      value={overrides[param.name] ?? param.value}
                      step={1}
                      aria-label={`参数 ${param.name}`}
                      onChange={value => onParamChange(param.name, value)}
                    />
                  </Space>
                ))}
                {Object.keys(overrides).length > 0 && (
                  <Button size="small" icon={<RollbackOutlined />} onClick={() => setOverrides({})}>
                    重置
                  </Button>
                )}
              </Space>
            </div>
          )}
        </div>
      </div>

      {/* 版本列表：点击回看该版原文（P2），非 viewer 可恢复 */}
      <div style={{ borderTop: '1px solid var(--cn-border, #eee)', paddingTop: 8 }}>
        <Space size={16} wrap>
          <Text type="secondary"><HistoryOutlined /> 版本历史（{versions.length}）：</Text>
          {versions.length === 0 ? (
            <Text type="secondary">暂无版本</Text>
          ) : versions.map(version => (
            <span key={version.id} className="cn-dsl-version-item">
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                aria-label={`回看版本 ${version.version_number}`}
                onClick={() => setViewingVersion(version)}
              >
                <Tag style={{ marginInlineEnd: 4 }}>v{version.version_number}</Tag>
                {version.comment ? version.comment : formatDateTime(version.created_at)}
              </Button>
            </span>
          ))}
        </Space>
      </div>

      {/* 版本回看抽屉：该版原文 + 恢复入口（viewer 只读） */}
      <Drawer
        title={`版本回看：v${viewingVersion?.version_number ?? ''}`}
        open={viewingVersion != null}
        size={520}
        onClose={() => setViewingVersion(null)}
        footer={
          viewingVersion != null && !isViewer ? (
            <Space>
              <Popconfirm
                title={`以 v${viewingVersion.version_number} 原文重新编译并保存为新版本？`}
                onConfirm={() => restore.mutate()}
              >
                <Button type="primary" danger icon={<RollbackOutlined />} loading={restore.isPending}>
                  恢复此版本
                </Button>
              </Popconfirm>
              <Button onClick={() => setViewingVersion(null)}>关闭</Button>
            </Space>
          ) : null
        }
      >
        {viewingVersion != null && (
          <>
            <Space size={8} wrap style={{ marginBottom: 8 }}>
              <Tag>第 {viewingVersion.version_number} 版</Tag>
              <Text type="secondary">{formatDateTime(viewingDetail?.created_at ?? viewingVersion.created_at)}</Text>
            </Space>
            {viewingDetail?.comment && <Text type="secondary">备注：{viewingDetail.comment}</Text>}
            {viewingLoading ? (
              <Skeleton active />
            ) : (
              <pre
                data-testid="design-version-content"
                className="cn-dsl-version-pre"
                style={{ whiteSpace: 'pre-wrap', margin: 0 }}
              >
                {viewingDetail?.content ?? ''}
              </pre>
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}
