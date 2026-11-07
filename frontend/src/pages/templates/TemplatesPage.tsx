/** 工作区模板中心（需求 0094 / 0120）：模板列表 / 结构化预览 / 编辑与影响预览.
 *
 * 布局对齐质量检查与修改申请页：cn-page 紧凑页头 + cn-qc-split 双栏。
 * 左栏为模板清单（按「内置模板 / 自定义模板」分组，选中项高亮），
 * 右栏为选中模板的元信息与结构化详情（流程阶段 / 表单 / 端到端流程 / 文档规则），
 * 编辑、复制、导出、删除等操作收敛到右栏方盒标题条，避免左栏行内按钮过密。
 */

import { Suspense, lazy, useMemo, useState } from 'react'
import {
  Alert, App as AntApp, Button, Empty, Input, Popconfirm,
  Space, Spin, Tag, Tooltip, Typography,
} from 'antd'
import {
  AppstoreOutlined, PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined,
  FileTextOutlined, ImportOutlined, ExportOutlined, UnorderedListOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import SectionBox from '@/components/SectionBox'
import { workspaceTemplateApi } from '@/api'
import type { WorkspaceTemplate } from '@/api'
import TemplateDetail from './TemplateDetail'
import TemplateImportModal from './TemplateImportModal'
import { formatDateTime } from '@/utils/datetime'

const TemplateEditorDrawer = lazy(() => import('./TemplateEditorDrawer'))

const { Text, Paragraph } = Typography

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 左栏单行：模板名 + 版本 / 分类标签 + 规模摘要（选中态由 cn-qc-row--active 绘制） */
function TemplateRow({
  template, active, onClick,
}: {
  template: WorkspaceTemplate
  active: boolean
  onClick: () => void
}) {
  const { counts } = template
  const summary = [
    `${counts.stage_count} 阶段`,
    `${counts.form_count} 表单`,
    `${counts.document_rule_count} 文档规则`,
    counts.flow_count ? `${counts.flow_count} 流程` : '',
  ].filter(Boolean).join(' / ')
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      className={[
        'cn-cr-side-item',
        'cn-cr-group-item',
        'cn-qc-row',
        'cn-qc-row--selectable',
        active ? 'cn-qc-row--active' : '',
      ].filter(Boolean).join(' ')}
      data-testid={`template-item-${template.id}`}
      onClick={onClick}
    >
      <span className="cn-cr-side-main">
        <span className="cn-cr-side-title">
          <Text strong>{template.name}</Text>
          <Tag color="blue">v{template.version}</Tag>
          {template.category && <Tag>{template.category}</Tag>}
        </span>
        <span className="cn-cr-side-preview">{summary}</span>
      </span>
    </button>
  )
}

/** 概要条单元格：复用质量检查运行概要的样式（标签在上、数值在下） */
function TemplateStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="cn-qc-run-stat">
      <span className="cn-qc-run-stat-label">{label}</span>
      <Text strong className="cn-qc-run-stat-value">{value}</Text>
    </div>
  )
}

export default function TemplatesPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<WorkspaceTemplate | null>(null)
  const [seed, setSeed] = useState<WorkspaceTemplate | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: templates = [], isLoading, error } = useQuery({
    queryKey: ['workspace-templates', search],
    queryFn: () => workspaceTemplateApi.list(search.trim() || undefined),
  })

  const grouped = useMemo(() => {
    const builtin = templates.filter(t => t.is_builtin)
    const custom = templates.filter(t => !t.is_builtin)
    return { builtin, custom }
  }, [templates])

  // 选中项被删除 / 搜索过滤后回落到清单第一条（内置优先，与接口顺序一致）
  const selected = useMemo(() => (
    templates.find(t => String(t.id) === selectedId) ?? templates[0] ?? null
  ), [templates, selectedId])

  const remove = useMutation({
    mutationFn: (id: number) => workspaceTemplateApi.remove(id),
    onSuccess: () => {
      message.success('模板已删除')
      setSelectedId(null)
      queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const exportTemplate = useMutation({
    mutationFn: (t: WorkspaceTemplate) => workspaceTemplateApi.exportFile(t.id),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename)
      message.success('模板已导出')
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '导出失败'),
  })

  const openCreate = () => { setEditing(null); setSeed(null); setEditorOpen(true) }
  const openEdit = (t: WorkspaceTemplate) => { setEditing(t); setSeed(null); setEditorOpen(true) }
  const openClone = (t: WorkspaceTemplate) => { setEditing(null); setSeed(t); setEditorOpen(true) }

  const renderGroup = (title: string, items: WorkspaceTemplate[]) => {
    if (!items.length) return null
    return (
      <div key={title} role="group" aria-label={title}>
        <div className="cn-tpl-group-label">{title}（{items.length}）</div>
        {items.map(t => (
          <TemplateRow
            key={t.id}
            template={t}
            active={selected != null && String(t.id) === String(selected.id)}
            onClick={() => setSelectedId(String(t.id))}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="cn-page cn-qc-page cn-tpl-page" data-testid="templates-page">
      {/* ── 页头：标题 + 口径说明 + 搜索 / 导入 / 新建入口（与质量检查页同款紧凑页头） ── */}
      <header className="cn-page-head">
        <div className="cn-page-head-main">
          <span className="cn-page-head-icon" aria-hidden><AppstoreOutlined /></span>
          <div className="cn-page-head-text">
            <h1 className="cn-page-head-title">工作区模板</h1>
            <div className="cn-page-head-sub">
              <span className="cn-page-head-meta">
                左侧为内置与自定义模板清单，右侧为选中模板的结构化详情；更新时先看 diff 与已有数据影响，再确认保存。
              </span>
            </div>
          </div>
        </div>
        <div className="cn-page-head-actions">
          <Input.Search
            placeholder="搜索模板 / 分类"
            allowClear
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ width: 200 }}
          />
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)} data-testid="import-template-btn">
            导入模板
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} data-testid="create-template-btn">
            新建模板
          </Button>
          <Button onClick={() => navigate('/w')}>返回工作区</Button>
        </div>
      </header>

      {error ? (
        <Alert type="error" showIcon message="模板加载失败" description={error instanceof Error ? error.message : String(error)} />
      ) : (
        <div className="cn-qc-split" data-testid="templates-split">
          {/* 左栏：模板清单（内置 / 自定义分组） */}
          <SectionBox
            title="模板清单"
            icon={<UnorderedListOutlined />}
            extra={<span>共 {templates.length} 条</span>}
            flush
            testId="template-list-box"
          >
            <Spin spinning={isLoading}>
              {!isLoading && templates.length === 0 ? (
                <div className="cn-qc-empty">
                  <Empty description="还没有模板，新建一个或用内置科研项目模板复制" />
                </div>
              ) : (
                <div role="listbox" aria-label="模板清单" className="cn-cr-side-list">
                  {renderGroup('内置模板', grouped.builtin)}
                  {renderGroup('自定义模板', grouped.custom)}
                </div>
              )}
            </Spin>
          </SectionBox>

          {/* 右栏：选中模板的元信息与结构化详情 + 操作（编辑为主动作，其余为图标操作） */}
          <SectionBox
            title="模板详情"
            icon={<FileTextOutlined />}
            extra={selected ? (
              <Space size={4} wrap>
                <Button
                  type="primary"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => openEdit(selected)}
                  data-testid="edit-template-btn"
                >
                  编辑模板
                </Button>
                <Tooltip title="复制为新模板">
                  <Button
                    size="small"
                    type="text"
                    aria-label="复制模板"
                    icon={<CopyOutlined />}
                    onClick={() => openClone(selected)}
                  />
                </Tooltip>
                <Tooltip title="导出为 JSON 文件">
                  <Button
                    size="small"
                    type="text"
                    aria-label="导出模板"
                    icon={<ExportOutlined />}
                    loading={exportTemplate.isPending && exportTemplate.variables?.id === selected.id}
                    onClick={() => exportTemplate.mutate(selected)}
                    data-testid={`export-template-${selected.id}`}
                  />
                </Tooltip>
                <Popconfirm
                  title="删除模板？"
                  description={selected.workspace_count > 0 ? '仍有工作区在使用，无法删除' : '删除后不可恢复（历史版本一并删除）'}
                  disabled={selected.workspace_count > 0}
                  onConfirm={() => remove.mutate(Number(selected.id))}
                >
                  <Tooltip title={selected.workspace_count > 0 ? '仍有工作区在使用，无法删除' : '删除模板'}>
                    <Button
                      size="small"
                      type="text"
                      danger
                      disabled={selected.workspace_count > 0}
                      aria-label="删除模板"
                      icon={<DeleteOutlined />}
                    />
                  </Tooltip>
                </Popconfirm>
              </Space>
            ) : undefined}
            footer={(
              <span className="cn-tpl-hint">
                <InfoCircleOutlined aria-hidden />
                模板更新不会破坏已有数据：保存时只增量补齐缺失的表 / 字段 / 文档，被移出模板的对象一律保留；字段类型切换与删除当前阶段会提示确认。
              </span>
            )}
            testId="template-detail-box"
          >
            <Spin spinning={isLoading}>
              {!selected ? (
                <div className="cn-qc-empty">
                  <Empty description="选择左侧模板查看详情" />
                </div>
              ) : (
                <div className="cn-tpl-detail" data-testid="template-detail">
                  {/* 模板头：完整名称 + 标签 + 说明 + 更新信息（名称不截断，便于查阅） */}
                  <div className="cn-tpl-detail-head">
                    <div className="cn-tpl-detail-title">
                      <Text strong className="cn-tpl-detail-name">{selected.name}</Text>
                      {selected.is_builtin && <Tag color="gold">内置</Tag>}
                      <Tag color="blue">v{selected.version}</Tag>
                      {selected.category && <Tag>{selected.category}</Tag>}
                    </div>
                    <Paragraph
                      type="secondary"
                      className="cn-tpl-detail-desc"
                      ellipsis={{ rows: 2, tooltip: selected.description || undefined }}
                    >
                      {selected.description || '暂无说明'}
                    </Paragraph>
                    <div className="cn-tpl-detail-meta">
                      <span>{selected.workspace_count} 个工作区使用</span>
                      <span aria-hidden>·</span>
                      <span>更新于 {formatDateTime(selected.updated_at)}</span>
                      {selected.modules.length > 0 && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="cn-tpl-detail-modules">
                            模块：{selected.modules.map(m => <Tag key={m}>{m}</Tag>)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* 概要计数条：规模与使用情况一眼可读（复用质量检查的运行概要样式） */}
                  <section className="cn-qc-run-summary" aria-label="模板概要">
                    <TemplateStat label="阶段" value={selected.counts.stage_count} />
                    <TemplateStat label="表单" value={selected.counts.form_count} />
                    <TemplateStat label="字段" value={selected.counts.field_count} />
                    <TemplateStat label="文档规则" value={selected.counts.document_rule_count} />
                    <TemplateStat label="流程" value={selected.counts.flow_count ?? 0} />
                    <TemplateStat label="使用工作区" value={selected.workspace_count} />
                  </section>

                  {/* 详情页签：内容区独立滚动，长表单 / 文档清单不把整页撑高 */}
                  <div className="cn-tpl-detail-body">
                    <TemplateDetail template={selected} />
                  </div>
                </div>
              )}
            </Spin>
          </SectionBox>
        </div>
      )}

      {editorOpen && (
        <Suspense fallback={null}>
          <TemplateEditorDrawer
            open
            template={editing}
            seed={seed}
            onClose={() => setEditorOpen(false)}
          />
        </Suspense>
      )}
      <TemplateImportModal open={importOpen} onClose={() => setImportOpen(false)} />
    </div>
  )
}
