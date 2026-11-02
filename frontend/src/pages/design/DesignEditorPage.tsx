/** 设计编辑器页 —— DSL 源码（CodeMirror）+ 3D 实时预览（three.js）+ 参数面板.
 *
 * 数据流（ADR 0079 I1/D3/D4）：
 * - 编辑防抖 300ms → POST /designs/preview（无落库）→ 结构化诊断回显错误行；
 * - 渲染只消费后端编译的 IR（前端零解析零求值），three 相关全部在 lazy chunk；
 * - 保存：编译在后端通过才落库并落新版本，失败保留草稿（边界 #2）；
 * - P2：版本历史支持回看（侧栏抽屉看原文）与恢复（旧版重编译落新版本）；
 *   导出（STL / OBJ / GLB / 三视图）与 PreviewCanvas 同属 lazy 边界（D4/D5）。
 *
 * 编辑区布局（UI 优化）：顶部一条工具栏收拢全部动作 —— 标题 / 版本标签 / 编译状态标签
 * （错误时下方展开诊断条）/ 参数按钮（抽屉）/ 版本历史按钮（侧栏抽屉）/ 导出 / 保存；
 * 左右两栏各自内置滚动，页面本身不产生纵向滚动条。
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Drawer, Empty, InputNumber, Popconfirm, Skeleton, Space, Tag, Typography,
} from 'antd'
import type { InputNumberProps } from 'antd'
import {
  ArrowLeftOutlined, CheckCircleFilled, CloseCircleFilled, ExperimentOutlined, HistoryOutlined,
  LoadingOutlined, RollbackOutlined, SaveOutlined, SlidersOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { designsApi, workspaceApi } from '@/api'
import type { DesignDiagnostic, DesignVersionItem } from '@/api'
import { formatDateTime } from '@/utils/datetime'
import DslEditor from './DslEditor'
import DesignConstraintsPanel from './DesignConstraintsPanel'
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
  // 结构树节点带 ?line= 打开编辑器并定位源行（ADR 0083 D7）
  const [searchParams, setSearchParams] = useSearchParams()
  const revealLine = Number(searchParams.get('line')) || undefined

  const { data: detail, isLoading } = useQuery({
    queryKey: ['designs', wid, designId],
    queryFn: () => designsApi.get(wid, designId),
    enabled: !!wid && !!designId,
  })

  // IR 快照（ADR 0086 D7 / I6）：首屏直用持久化 IR，干净状态不发 preview
  const { data: irResp } = useQuery({
    queryKey: ['designs', wid, designId, 'ir'],
    queryFn: () => designsApi.getIR(wid, designId),
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
  // 顶部工具栏抽屉：参数面板 / 版本历史（点击按钮从右侧展开）
  const [paramsOpen, setParamsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
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
  // 干净打开（内容未改且无参数覆盖）：直接消费 IR 快照，不发 preview（I6）
  const clean = !dirty && Object.keys(overrides).length === 0
  const preview = useDesignPreview(wid, content, overrides, {
    enabled: contentReady && !clean,
    designId: detail ? detail.id : null,
    initialIr: irResp?.ir ?? null,
  })

  // 依赖陈旧（ADR 0086 D6）：被引用零件更新后提示刷新，refresh 落新版本并清 stale
  const refresh = useMutation({
    mutationFn: () => designsApi.refresh(wid, designId),
    onSuccess: (updated) => {
      message.success(`依赖已刷新，保存为第 ${updated.version_number} 版`)
      setContent(updated.content)
      setOverrides({})
      invalidate()
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '依赖刷新失败'),
  })

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

  // 版本回看（P2）：历史侧栏内点选版本，看该版原文
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
      setHistoryOpen(false)
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
  const overrideCount = Object.keys(overrides).length

  const diagnostics: DesignDiagnostic[] = useMemo(() => preview.diagnostics, [preview.diagnostics])
  const errorCount = diagnostics.length
  const canSave = dirty && !isViewer && !preview.compiling

  const closeHistory = () => {
    setHistoryOpen(false)
    setViewingVersion(null)
  }

  return (
    <div className="cn-dsl-page">
      {/* 顶部工具栏：身份 / 状态标签在左，动作按钮在右 */}
      <div className="cn-dsl-toolbar">
        <div className="cn-dsl-toolbar-main">
          <Link to={`/w/${wid}/design`} aria-label="返回设计列表">
            <Button icon={<ArrowLeftOutlined />} type="text" />
          </Link>
          <Text strong className="cn-dsl-title">{detail?.title ?? '设计'}</Text>
          <Space size={4} wrap>
            {detail && (
              <Tag className="cn-dsl-status-tag" data-testid="design-version-tag">
                v{detail.version_number}
              </Tag>
            )}
            {preview.compiling ? (
              <Tag color="processing" className="cn-dsl-status-tag" data-testid="design-compile-status">
                <LoadingOutlined /> 编译中
              </Tag>
            ) : errorCount > 0 ? (
              <Tag color="error" className="cn-dsl-status-tag" data-testid="design-compile-status">
                <CloseCircleFilled /> {errorCount} 处错误
              </Tag>
            ) : (
              <Tag color="success" className="cn-dsl-status-tag" data-testid="design-compile-ok">
                <CheckCircleFilled /> 编译通过
                {preview.ir && preview.ir.nodes.length === 0 && '（顶层尚无实例）'}
              </Tag>
            )}
            {dirty && <Tag color="warning" className="cn-dsl-status-tag">未保存</Tag>}
            {isViewer && <Tag className="cn-dsl-status-tag">只读</Tag>}
          </Space>
        </div>
        <Space size={8} wrap className="cn-dsl-toolbar-actions">
          <Button
            icon={<SlidersOutlined />}
            aria-label="参数"
            onClick={() => setParamsOpen(true)}
          >
            参数{params.length > 0 ? `（${params.length}）` : ''}
            {overrideCount > 0 && <Tag color="processing" className="cn-dsl-btn-tag">{overrideCount} 覆盖</Tag>}
          </Button>
          <Button
            icon={<HistoryOutlined />}
            aria-label="版本历史"
            onClick={() => setHistoryOpen(true)}
          >
            版本历史（{versions.length}）
          </Button>
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

      {detail?.dependencies_stale && (
        <Alert
          type="warning"
          showIcon
          data-testid="design-stale-banner"
          message="依赖的零件文件已更新，当前打开的是旧快照"
          description="历史版本按依赖快照复现（不取最新）；点击刷新将以最新依赖重新编译并保存新版本。"
          action={(
            <Button
              size="small"
              type="primary"
              loading={refresh.isPending}
              disabled={isViewer || dirty}
              onClick={() => refresh.mutate()}
            >
              刷新依赖
            </Button>
          )}
        />
      )}

      {/* 诊断条：编译状态用标签表达，具体错误在标签下方单行横向滚动展开 */}
      {errorCount > 0 && (
        <div className="cn-dsl-diag-bar" role="status">
          <ExperimentOutlined />
          {diagnostics.map((item, index) => (
            <div key={`${item.line}-${item.col}-${index}`} className="cn-dsl-diag-item">
              <Tag color="error" style={{ marginInlineEnd: 4 }}>第{item.line}行</Tag>
              <Text type="danger">{item.message}</Text>
            </div>
          ))}
        </div>
      )}

      {/* 左右两栏：编辑器 / 预览各自内置滚动，页面不整体滚动 */}
      <div className="cn-dsl-workbench">
        <div className="cn-dsl-pane cn-dsl-pane--editor">
          <div className="cn-dsl-editor-host">
            {isLoading ? <Skeleton active /> : (
              <DslEditor
                value={content}
                onChange={(next) => { setContent(next); setSaveError('') }}
                diagnostics={diagnostics}
                placeholder="param width = 80&#10;box(size = [width, 40, 12])"
                readOnly={isViewer}
                // 原文回填完成后才定位，避免首帧空文档把行号钳到第 1 行
                revealLine={contentReady ? revealLine : undefined}
              />
            )}
          </div>
        </div>

        <div className="cn-dsl-pane cn-dsl-pane--preview">
          <div className="cn-dsl-preview-host">
            <Suspense fallback={<Skeleton active style={{ height: '100%' }} />}>
              <PreviewCanvas ir={preview.ir} />
            </Suspense>
          </div>
          <DesignConstraintsPanel
            constraints={preview.ir?.constraints ?? []}
            onReveal={(line) => setSearchParams(
              prev => {
                const next = new URLSearchParams(prev)
                next.set('line', String(line))
                return next
              },
              { replace: true },
            )}
          />
        </div>
      </div>

      {/* 参数抽屉：顶部「参数」按钮打开，改参即重编译 */}
      <Drawer
        title="参数"
        open={paramsOpen}
        size={380}
        onClose={() => setParamsOpen(false)}
        extra={overrideCount > 0 ? (
          <Button size="small" icon={<RollbackOutlined />} onClick={() => setOverrides({})}>
            重置
          </Button>
        ) : null}
      >
        {params.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前设计没有参数" />
        ) : (
          <div className="cn-dsl-param-list">
            {params.map(param => {
              const overridden = overrides[param.name] != null
              return (
                <div key={param.name} className="cn-dsl-param-row">
                  <div className="cn-dsl-param-name">
                    <Text code>{param.name}</Text>
                    <Text type="secondary" className="cn-dsl-param-default">
                      默认 {param.value}
                    </Text>
                    {overridden && <Tag color="processing" className="cn-dsl-status-tag">已覆盖</Tag>}
                  </div>
                  <InputNumber
                    size="small"
                    value={overrides[param.name] ?? param.value}
                    step={1}
                    aria-label={`参数 ${param.name}`}
                    onChange={value => onParamChange(param.name, value)}
                  />
                </div>
              )
            })}
          </div>
        )}
      </Drawer>

      {/* 版本历史侧栏：列表 → 选中版本回看原文 + 恢复入口（viewer 只读） */}
      <Drawer
        title={viewingVersion
          ? `版本回看：v${viewingVersion.version_number}`
          : `版本历史（${versions.length}）`}
        open={historyOpen}
        size={460}
        onClose={closeHistory}
        footer={viewingVersion != null && !isViewer ? (
          <Space>
            <Popconfirm
              title={`以 v${viewingVersion.version_number} 原文重新编译并保存为新版本？`}
              onConfirm={() => restore.mutate()}
            >
              <Button type="primary" danger icon={<RollbackOutlined />} loading={restore.isPending}>
                恢复此版本
              </Button>
            </Popconfirm>
            <Button onClick={() => setViewingVersion(null)}>返回列表</Button>
          </Space>
        ) : null}
      >
        {viewingVersion == null ? (
          versions.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本" />
          ) : (
            <div className="cn-dsl-version-list">
              {versions.map(version => (
                <Button
                  key={version.id}
                  type="text"
                  block
                  className="cn-dsl-version-row"
                  aria-label={`回看版本 ${version.version_number}`}
                  onClick={() => setViewingVersion(version)}
                >
                  <Tag style={{ marginInlineEnd: 8 }}>v{version.version_number}</Tag>
                  <span className="cn-dsl-version-text">
                    {version.comment ? version.comment : '未填写变更说明'}
                  </span>
                  <Text type="secondary" className="cn-dsl-version-time">
                    {formatDateTime(version.created_at)}
                  </Text>
                </Button>
              ))}
            </div>
          )
        ) : (
          <>
            <Space size={8} wrap style={{ marginBottom: 8 }}>
              <Tag>第 {viewingVersion.version_number} 版</Tag>
              <Text type="secondary">
                {formatDateTime(viewingDetail?.created_at ?? viewingVersion.created_at)}
              </Text>
            </Space>
            {viewingDetail?.comment && <Text type="secondary">备注：{viewingDetail.comment}</Text>}
            {viewingDetail && viewingDetail.dependencies.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">依赖快照：</Text>
                <Space size={4} wrap>
                  {viewingDetail.dependencies.map(dep => (
                    <Tag key={dep.file_key}>{dep.file_key}@v{dep.version_number}</Tag>
                  ))}
                </Space>
              </div>
            )}
            {viewingLoading ? (
              <Skeleton active />
            ) : (
              <pre data-testid="design-version-content" className="cn-dsl-version-pre">
                {viewingDetail?.content ?? ''}
              </pre>
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}
