/** 文档导出模板面板（ADR 0152）—— 视觉与交互对齐「质量检查」页.
 *
 * 布局（与 `PipelinesPage` 同一套原语）：
 * - `cn-page` + `cn-page-head`：页头（图标 / 标题 / 单行口径说明）由 `DocumentTemplatesPage` 提供；
 * - 左栏 `SectionBox flush`：模板清单（内置分组 + 自定义分组，`cn-qc-row` 行态、选中左边条、
 *   默认标记与字体字号摘要），只做选择，行内不放动作按钮，避免一行三个图标按钮；
 * - 右栏 `SectionBox`：排版配置（名称 / 说明 + 动作条 + CSS 预览 + 五组折叠配置），
 *   动作全部收敛到方盒标题条右侧，一排小图标按钮，点开即改、保存即生效。
 *
 * 后端接口（工作区级，`/api/v1/workspaces/{wid}/documents/templates`）：
 * - `GET ""` / `POST ""` / `PUT /{id}` / `DELETE /{id}` / `POST /preview`
 * - 内置预设只读：改配置后只能「另存为」
 * - 一份配置同时供电 Word 与 PDF（PDF 侧字体族最佳匹配并降级）
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, App, AutoComplete, Button, Collapse, Empty, Input, InputNumber, Modal,
  Segmented, Select, Space, Switch, Tag, Tooltip, Typography,
} from 'antd'
import {
  CopyOutlined, DeleteOutlined, DownOutlined, EyeInvisibleOutlined, EyeOutlined, FilePdfOutlined,
  FileTextOutlined, FileWordOutlined, PlusOutlined, RightOutlined, SaveOutlined,
  SnippetsOutlined, StarOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { workspaceApi, exportTemplateApi } from '@/api'
import type { ExportTemplateConfig, ExportTemplateItem } from '@/api'
import CnListMeta from '@/components/CnListMeta'
import SectionBox from '@/components/SectionBox'
import { SPACE } from '@/theme/tokens'
import {
  ALIGN_OPTIONS,
  CAPTION_NUMBERING_OPTIONS,
  CAPTION_POSITION_OPTIONS,
  CELL_VALIGN_OPTIONS,
  CODE_FONTS,
  EAST_ASIA_FONTS,
  LATIN_FONTS,
  LINE_RULE_OPTIONS,
  LIST_MARKER_OPTIONS,
  NUMBERING_OPTIONS,
  PAPER_OPTIONS,
  PAGE_NUMBER_OPTIONS,
  TABLE_STYLE_OPTIONS,
  fontPtLabel,
  numberingPrefix,
  pageNumberText,
  previewStyles,
} from './templateOptions'

const { Text } = Typography

/** 深拷贝一份模板配置（纯数据，JSON 往返足够且兼容旧内核） */
function cloneConfig(config: ExportTemplateConfig): ExportTemplateConfig {
  return JSON.parse(JSON.stringify(config)) as ExportTemplateConfig
}

/** 配置项：标签在上、控件在下（两列网格里比左右排更省宽度） */
function Field({
  label, children, hint, wide,
}: { label: string; children: React.ReactNode; hint?: string; wide?: boolean }) {
  return (
    <label className={['cn-doc-tpl-field', wide ? 'cn-doc-tpl-field--wide' : ''].filter(Boolean).join(' ')}>
      <span className="cn-doc-tpl-field-label">{label}</span>
      <div className="cn-doc-tpl-field-control">{children}</div>
      {hint && <span className="cn-doc-tpl-field-hint">{hint}</span>}
    </label>
  )
}

/** 字体输入：候选 + 自由输入（Word 端按打开文档机器的字体回落） */
function FontInput({
  value, options, onChange, testId,
}: { value: string; options: string[]; onChange: (v: string) => void; testId?: string }) {
  return (
    <AutoComplete
      data-testid={testId}
      value={value}
      options={options.map(font => ({ value: font }))}
      onChange={onChange}
      style={{ width: '100%' }}
      placeholder="字体名"
    />
  )
}

function ColorInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Input
      value={value}
      onChange={e => onChange(e.target.value)}
      maxLength={7}
      size="small"
      placeholder="#000000"
      prefix={
        <span
          aria-hidden
          className="cn-doc-tpl-color-dot"
          style={{ background: value }}
        />
      }
    />
  )
}

/** 模板缩略摘要：字号 + 行距 + 首行缩进，让左栏一眼看出各预设差异 */
function templateSummary(config: ExportTemplateConfig): string {
  const { body, numbering } = config
  const parts = [
    `${body.east_asia_font} ${body.size}pt`,
    body.line_spacing_rule === 'fixed' ? `固定行距 ${body.line_spacing_pt}pt` : `${body.line_spacing} 倍行距`,
  ]
  if (body.first_line_indent_chars > 0) parts.push(`首行缩进 ${body.first_line_indent_chars} 字符`)
  if (numbering.heading !== 'none') parts.push('标题自动编号')
  return parts.join(' · ')
}

/** 面板内 CSS 等比预览（与 Word 不逐像素对齐，只表达字号 / 行距 / 缩进 / 表头） */
function TemplatePreview({ config }: { config: ExportTemplateConfig }) {
  const styles = useMemo(() => previewStyles(config), [config])
  const { numbering, captions, lists } = config
  // 标题编号计数器：与导出侧同一口径（进入某级时本级 +1、更深层清零）
  const counters = [0, 0, 0, 0, 0, 0]
  const headingText = (level: number, text: string) => {
    counters[level - 1] += 1
    for (let index = level; index < counters.length; index += 1) counters[index] = 0
    const prefix = numberingPrefix(numbering.heading, level, counters)
    return prefix ? `${prefix} ${text}` : text
  }
  const marker = lists.marker === 'dash' ? '–' : lists.marker === 'dot' ? '·' : '•'
  const figureCaption = captions.figure
  const tableCaption = captions.table

  return (
    <div data-testid="template-preview" className="cn-doc-tpl-preview">
      <div style={{ ...styles.page, margin: '0 auto' }}>
        {/* 页眉：模板未填文字时保留占位（visibility 隐藏）以体现页边距关系 */}
        <div style={styles.header} data-testid="preview-header">
          {config.header_footer.header_text || '页眉'}
        </div>

        <div style={styles.headings(1)}>{headingText(1, '概述')}</div>
        <div style={styles.body}>
          这是一段示例正文，用于查看中西文字体、字号、行距、段前段后、首行缩进与两端对齐效果。
          Mixed English text shows the latin font.
        </div>

        <div style={styles.headings(2)}>{headingText(2, '背景与方法')}</div>
        <div style={styles.body}>第二段正文：标题编号、段间距与正文缩进同时生效。</div>
        <div style={styles.list}>
          <div style={styles.listItem}>{marker} 列表项一（查看缩进 / 段后 / 符号）</div>
          <div style={styles.listItem}>{marker} 列表项二</div>
        </div>

        <div style={styles.headings(3)}>{headingText(3, '数据示例')}</div>
        {tableCaption.enabled && tableCaption.position === 'above' && (
          <div style={styles.caption('table')} data-testid="preview-table-caption">
            表 1 指标数据
          </div>
        )}
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.headerCell}>指标</th>
              <th style={styles.headerCell}>本期</th>
              <th style={styles.headerCell}>同比</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={{ ...styles.cell, ...styles.zebraRow }}>覆盖率</td>
              <td style={{ ...styles.cell, ...styles.zebraRow }}>95.2%</td>
              <td style={{ ...styles.cell, ...styles.zebraRow }}>+1.4%</td>
            </tr>
            <tr>
              <td style={styles.cell}>用例数</td>
              <td style={styles.cell}>7317</td>
              <td style={styles.cell}>+120</td>
            </tr>
          </tbody>
        </table>
        {tableCaption.enabled && tableCaption.position === 'below' && (
          <div style={styles.caption('table')} data-testid="preview-table-caption">
            表 1 指标数据
          </div>
        )}

        <div style={styles.headings(4)}>{headingText(4, '图示')}</div>
        <div
          data-testid="preview-figure"
          style={{
            height: 42,
            border: '1px dashed var(--cn-border)',
            borderRadius: 4,
            display: 'grid',
            placeItems: 'center',
            fontSize: 'var(--cn-text-2xs)',
            color: 'var(--cn-text-muted)',
          }}
        >
          图片占位
        </div>
        {figureCaption.enabled && figureCaption.position === 'below' && (
          <div style={styles.caption('figure')} data-testid="preview-figure-caption">
            图 1 架构示意
          </div>
        )}
        {figureCaption.enabled && figureCaption.position === 'above' && (
          <div style={styles.caption('figure')} data-testid="preview-figure-caption">
            图 1 架构示意
          </div>
        )}

        <pre style={styles.code} data-testid="preview-code">
          {'print("hello template")'}
        </pre>
        <div style={styles.quote}>引用块：模板只决定排版，不改变正文语义。</div>

        {/* 页脚页码：none 时不渲染（与导出侧一致） */}
        {config.header_footer.page_number !== 'none' && (
          <div style={styles.footer} data-testid="preview-footer">
            {pageNumberText(config.header_footer.page_number)}
          </div>
        )}
      </div>
    </div>
  )
}

export default function TemplatePanel() {
  const { wid = '' } = useParams<{ wid: string }>()
  const workspaceId = Number(wid)
  const hasWorkspace = Number.isFinite(workspaceId) && workspaceId > 0
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()

  const { data: workspaces = [] } = useQuery({ queryKey: ['workspaces'], queryFn: () => workspaceApi.list() })
  const currentWs = workspaces.find(w => String(w.id) === wid)
  const canEdit = currentWs?.current_user_role === 'owner' || currentWs?.current_user_role === 'editor'

  const listQuery = useQuery({
    queryKey: ['export-templates', workspaceId],
    queryFn: () => exportTemplateApi.list(workspaceId),
    enabled: hasWorkspace,
  })

  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [draft, setDraft] = useState<ExportTemplateConfig | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saveAsOpen, setSaveAsOpen] = useState(false)
  const [saveAsName, setSaveAsName] = useState('')
  // 新建模板（可选内置预设作为起点）
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createPreset, setCreatePreset] = useState('research')
  // 左栏分组折叠（内置 / 自定义各自独立，默认展开）
  const [collapsedGroups, setCollapsedGroups] = useState<Record<'builtin' | 'custom', boolean>>({
    builtin: false,
    custom: false,
  })
  // 右栏预览独立收起（避免长配置被预览挤到一屏之外）
  const [previewOpen, setPreviewOpen] = useState(true)

  const items = listQuery.data?.items ?? []
  const selected: ExportTemplateItem | undefined = items.find(item => item.ref === selectedRef)
  const isBuiltin = selected?.source === 'builtin'
  const baseline = useMemo(() => (selected ? JSON.stringify(selected.config) : ''), [selected])
  const dirty = Boolean(draft) && JSON.stringify(draft) !== baseline
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty

  // 首次加载 / 列表变化时选中当前默认模板
  useEffect(() => {
    if (!listQuery.data || selectedRef) return
    setSelectedRef(listQuery.data.default_ref)
  }, [listQuery.data, selectedRef])

  // 选中项变化 → 载入工作副本
  useEffect(() => {
    if (!selected) {
      setDraft(null)
      return
    }
    setDraft(cloneConfig(selected.config))
    setName(selected.name)
    setDescription(selected.description)
  }, [selected])

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['export-templates', workspaceId] })

  const saveMut = useMutation({
    mutationFn: () =>
      exportTemplateApi.update(workspaceId, Number(selected!.ref), { name, description, config: draft! }),
    onSuccess: () => {
      message.success('模板已保存')
      invalidate()
    },
    onError: () => message.error('保存失败，请检查配置'),
  })

  const saveAsMut = useMutation({
    mutationFn: () =>
      exportTemplateApi.create(workspaceId, {
        name: saveAsName.trim(),
        description,
        config: draft ?? undefined,
      }),
    onSuccess: result => {
      message.success('已另存为自定义模板')
      setSaveAsOpen(false)
      setSaveAsName('')
      invalidate()
      setSelectedRef(result.ref)
    },
    onError: () => message.error('另存为失败（名称可能重复或配置非法）'),
  })

  const createMut = useMutation({
    mutationFn: () =>
      exportTemplateApi.create(workspaceId, {
        name: createName.trim(),
        preset_key: createPreset,
      }),
    onSuccess: result => {
      message.success('模板已创建')
      setCreateOpen(false)
      setCreateName('')
      invalidate()
      setSelectedRef(result.ref)
    },
    onError: () => message.error('创建失败（名称可能重复或配置非法）'),
  })

  const defaultMut = useMutation({
    mutationFn: () => exportTemplateApi.update(workspaceId, Number(selected!.ref), { is_default: true }),
    onSuccess: () => {
      message.success('已设为工作区默认模板')
      invalidate()
    },
    onError: () => message.error('设置默认失败'),
  })

  const deleteMut = useMutation({
    mutationFn: () => exportTemplateApi.remove(workspaceId, Number(selected!.ref)),
    onSuccess: result => {
      message.success('模板已删除')
      invalidate()
      setSelectedRef(result.default_ref)
    },
    onError: () => message.error('删除失败'),
  })

  const previewMut = useMutation({
    mutationFn: (format: 'docx' | 'pdf') =>
      exportTemplateApi.preview(
        workspaceId,
        draft ? { config: draft } : { ref: selectedRef ?? undefined },
        format,
      ),
    onSuccess: (blob, format) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `模板示例.${format}`
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)
    },
    onError: () => message.error('示例生成失败，请检查配置'),
  })

  const update = (mutator: (next: ExportTemplateConfig) => void) => {
    setDraft(prev => {
      if (!prev) return prev
      const next = cloneConfig(prev)
      mutator(next)
      return next
    })
  }

  const selectTemplate = (ref: string) => {
    if (ref === selectedRef) return
    if (!dirtyRef.current) {
      setSelectedRef(ref)
      return
    }
    modal.confirm({
      title: '放弃未保存的修改？',
      content: '切换模板会丢弃当前未保存的配置修改。',
      okText: '放弃并切换',
      cancelText: '继续编辑',
      onOk: () => setSelectedRef(ref),
    })
  }

  const pageHead = (
    <header className="cn-page-head">
      <div className="cn-page-head-main">
        <span className="cn-page-head-icon" aria-hidden>
          <SnippetsOutlined />
        </span>
        <div className="cn-page-head-text">
          <h1 className="cn-page-head-title">文档模板</h1>
          <div className="cn-page-head-sub">
            <span
              className="cn-page-head-meta"
              title="左侧模板清单、右侧排版配置（预览可收起）；一份模板同时作用于 Word 与 PDF。内置模板只读，可另存为自定义；未指定模板时按「工作区默认 → 标准」导出。"
            >
              左侧模板清单（分组可折叠）、右侧排版配置（预览可收起）；一份模板同时作用于 Word 与 PDF。
              内置模板只读，可另存为自定义；未指定模板时按「工作区默认 → 标准」导出。
            </span>
          </div>
        </div>
      </div>
      <div className="cn-page-head-actions">
        <Tooltip title={canEdit ? '从内置预设新建一份自定义模板' : '仅工作区所有者 / 编辑者可以新建模板'}>
          <span>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              data-testid="template-create-btn"
              disabled={!canEdit}
              onClick={() => {
                setCreateName('')
                setCreatePreset('research')
                setCreateOpen(true)
              }}
            >
              新建模板
            </Button>
          </span>
        </Tooltip>
      </div>
    </header>
  )

  if (!hasWorkspace) {
    return (
      <>
        {pageHead}
        <Alert
          type="info"
          showIcon
          message="模板属于工作区"
          description="请先进入一个工作区，再在「模板」页签管理该工作区的文档导出模板。"
        />
      </>
    )
  }

  if (listQuery.isLoading) {
    return (
      <>
        {pageHead}
        <div className="cn-state">加载中…</div>
      </>
    )
  }

  const builtins = items.filter(item => item.source === 'builtin')
  const customs = items.filter(item => item.source === 'custom')
  const defaultRef = listQuery.data?.default_ref

  const rowNode = (item: ExportTemplateItem) => {
    const active = item.ref === selectedRef
    const isDefault = item.is_default || (!item.is_default && item.ref === defaultRef && item.source === 'custom')
    return (
      <div
        key={item.ref}
        role="button"
        tabIndex={0}
        data-testid={`template-item-${item.ref}`}
        className={['cn-list-item', 'cn-qc-row', 'cn-qc-row--selectable', active ? 'cn-qc-row--active' : '']
          .filter(Boolean)
          .join(' ')}
        onClick={() => selectTemplate(item.ref)}
        onKeyDown={event => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            selectTemplate(item.ref)
          }
        }}
      >
        <div className="cn-list-item-main">
          <CnListMeta
            avatar={<FileTextOutlined style={{ color: active ? 'var(--cn-brand-color)' : 'var(--cn-text-muted)' }} />}
            title={
              <span className="cn-doc-tpl-row-title">
                <Text strong={active}>{item.name}</Text>
                {isDefault && <Tag color="blue">默认</Tag>}
                {item.source === 'custom' && <Tag>自定义</Tag>}
              </span>
            }
            description={<span title={templateSummary(item.config)}>{templateSummary(item.config)}</span>}
          />
        </div>
      </div>
    )
  }

  const actionBar = (
    <div className="cn-doc-tpl-actions">
      <Tooltip title="另存为自定义模板（复制当前配置）">
        <Button
          size="small"
          type="text"
          icon={<CopyOutlined />}
          data-testid="template-save-as-btn"
          onClick={() => {
            setSaveAsName(selected ? `${selected.name} 副本` : '新模板')
            setSaveAsOpen(true)
          }}
        >
          另存为
        </Button>
      </Tooltip>
      {!isBuiltin && canEdit && (
        <Tooltip title={dirty ? '保存模板配置' : '没有需要保存的修改'}>
          <Button
            size="small"
            type="primary"
            icon={<SaveOutlined />}
            data-testid="template-save-btn"
            loading={saveMut.isPending}
            disabled={!dirty}
            onClick={() => saveMut.mutate()}
          >
            保存
          </Button>
        </Tooltip>
      )}
      {!isBuiltin && canEdit && !selected?.is_default && (
        <Tooltip title="设为工作区默认模板（导出未指定模板时使用）">
          <Button
            size="small"
            type="text"
            icon={<StarOutlined />}
            data-testid="template-default-btn"
            loading={defaultMut.isPending}
            onClick={() => defaultMut.mutate()}
          >
            设为默认
          </Button>
        </Tooltip>
      )}
      {!isBuiltin && canEdit && (
        <Tooltip title="删除该模板">
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            data-testid="template-delete-btn"
            onClick={() =>
              modal.confirm({
                title: '删除该模板？',
                content: '删除后不影响已导出的文件；若它是默认模板，会回落为「标准」。',
                okText: '删除',
                okButtonProps: { danger: true },
                cancelText: '取消',
                onOk: () => deleteMut.mutateAsync(),
              })
            }
          >
            删除
          </Button>
        </Tooltip>
      )}
      <Tooltip title="下载示例 Word（用当前配置，不落库）">
        <Button
          size="small"
          type="text"
          icon={<FileWordOutlined />}
          loading={previewMut.isPending}
          data-testid="template-preview-btn"
          onClick={() => previewMut.mutate('docx')}
        >
          示例 Word
        </Button>
      </Tooltip>
      <Tooltip title="下载示例 PDF（同一份配置，字体按服务器可用字体匹配）">
        <Button
          size="small"
          type="text"
          icon={<FilePdfOutlined />}
          data-testid="template-preview-pdf-btn"
          onClick={() => previewMut.mutate('pdf')}
        >
          示例 PDF
        </Button>
      </Tooltip>
    </div>
  )

  const configBody = draft && (
    <div className="cn-doc-tpl-config-col">
      {isBuiltin ? (
        <div className="cn-doc-tpl-readonly">
          <Text strong>{selected?.name}</Text>
          <Text type="secondary">{selected?.description || '—'}</Text>
        </div>
      ) : (
        <div className="cn-doc-tpl-meta">
          <Field label="模板名称">
            <Input
              data-testid="template-name-input"
              value={name}
              onChange={e => setName(e.target.value)}
              disabled={!canEdit}
              maxLength={80}
              size="small"
            />
          </Field>
          <Field label="说明">
            <Input
              data-testid="template-desc-input"
              value={description}
              onChange={e => setDescription(e.target.value)}
              disabled={!canEdit}
              maxLength={200}
              size="small"
              placeholder="用途 / 适用场景（可选）"
            />
          </Field>
        </div>
      )}

      {!canEdit && (
        <Alert
          type="warning"
          showIcon
          className="cn-doc-tpl-note"
          message="只读浏览：仅工作区所有者 / 编辑者可以新增或修改模板。"
        />
      )}

      <Collapse
        size="small"
        ghost
        className="cn-doc-tpl-config"
        defaultActiveKey={['body']}
        items={[
          {
            key: 'page',
            label: '页面与页眉页脚',
            children: (
              <div className="cn-doc-tpl-fields" data-testid="template-section-page">
                <Field label="纸张">
                  <Select
                    size="small"
                    value={draft.page.paper}
                    onChange={v => update(next => { next.page.paper = v })}
                    options={PAPER_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="页边距 (cm)" hint="上 / 下 / 左 / 右" wide>
                  <Space size={SPACE.xs}>
                    {(['margin_top', 'margin_bottom', 'margin_left', 'margin_right'] as const).map(key => (
                      <InputNumber
                        key={key}
                        size="small"
                        value={draft.page[key]}
                        min={0.5}
                        max={5}
                        step={0.1}
                        style={{ width: 68 }}
                        onChange={value => update(next => { next.page[key] = Number(value ?? 2.54) })}
                      />
                    ))}
                  </Space>
                </Field>
                <Field label="页眉文字">
                  <Input
                    size="small"
                    value={draft.header_footer.header_text}
                    maxLength={120}
                    placeholder="留空则不显示页眉"
                    onChange={e => update(next => { next.header_footer.header_text = e.target.value })}
                  />
                </Field>
                <Field label="页脚页码">
                  <Select
                    size="small"
                    value={draft.header_footer.page_number}
                    onChange={v => update(next => { next.header_footer.page_number = v })}
                    options={PAGE_NUMBER_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="首页不同 / 字号" wide>
                  <Space size={SPACE.xs}>
                    <Switch
                      size="small"
                      checked={draft.header_footer.first_page_different}
                      onChange={v => update(next => { next.header_footer.first_page_different = v })}
                    />
                    <InputNumber
                      size="small"
                      value={draft.header_footer.font_size}
                      min={6}
                      max={14}
                      step={0.5}
                      style={{ width: 72 }}
                      onChange={value => update(next => { next.header_footer.font_size = Number(value ?? 8) })}
                    />
                  </Space>
                </Field>
              </div>
            ),
          },
          {
            key: 'body',
            label: '正文段落',
            children: (
              <div className="cn-doc-tpl-fields" data-testid="template-section-body">
                <Field label="中文字体">
                  <FontInput
                    testId="template-body-font"
                    value={draft.body.east_asia_font}
                    options={EAST_ASIA_FONTS}
                    onChange={v => update(next => { next.body.east_asia_font = v })}
                  />
                </Field>
                <Field label="西文字体">
                  <FontInput
                    value={draft.body.latin_font}
                    options={LATIN_FONTS}
                    onChange={v => update(next => { next.body.latin_font = v })}
                  />
                </Field>
                <Field label="字号" hint={fontPtLabel(draft.body.size)}>
                  <InputNumber
                    data-testid="template-body-size"
                    size="small"
                    value={draft.body.size}
                    min={8}
                    max={72}
                    step={0.5}
                    style={{ width: '100%' }}
                    onChange={value => update(next => { next.body.size = Number(value ?? 10.5) })}
                  />
                </Field>
                <Field label="对齐">
                  <Select
                    size="small"
                    value={draft.body.align}
                    onChange={v => update(next => { next.body.align = v })}
                    options={ALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="行距" wide>
                  <Space.Compact style={{ width: '100%' }}>
                    <Segmented
                      size="small"
                      value={draft.body.line_spacing_rule}
                      options={LINE_RULE_OPTIONS.map(o => ({ value: o.value, label: o.label === '倍数行距' ? '倍数' : '固定' }))}
                      onChange={v => update(next => { next.body.line_spacing_rule = v as 'multiple' | 'fixed' })}
                    />
                    {draft.body.line_spacing_rule === 'multiple' ? (
                      <InputNumber
                        size="small"
                        value={draft.body.line_spacing}
                        min={1}
                        max={3}
                        step={0.05}
                        onChange={value => update(next => { next.body.line_spacing = Number(value ?? 1.5) })}
                      />
                    ) : (
                      <InputNumber
                        size="small"
                        value={draft.body.line_spacing_pt}
                        min={10}
                        max={60}
                        step={1}
                        addonAfter="pt"
                        onChange={value => update(next => { next.body.line_spacing_pt = Number(value ?? 28) })}
                      />
                    )}
                  </Space.Compact>
                </Field>
                <Field label="段前 / 段后 (pt)" wide>
                  <Space size={SPACE.xs}>
                    <InputNumber
                      size="small"
                      value={draft.body.space_before}
                      min={0}
                      max={36}
                      style={{ width: 68 }}
                      onChange={value => update(next => { next.body.space_before = Number(value ?? 0) })}
                    />
                    <InputNumber
                      size="small"
                      value={draft.body.space_after}
                      min={0}
                      max={36}
                      style={{ width: 68 }}
                      onChange={value => update(next => { next.body.space_after = Number(value ?? 0) })}
                    />
                  </Space>
                </Field>
                <Field label="首行缩进 (字符)">
                  <InputNumber
                    size="small"
                    value={draft.body.first_line_indent_chars}
                    min={0}
                    max={8}
                    step={0.5}
                    style={{ width: '100%' }}
                    onChange={value => update(next => { next.body.first_line_indent_chars = Number(value ?? 0) })}
                  />
                </Field>
                <Field label="字间距 (pt)">
                  <InputNumber
                    size="small"
                    value={draft.body.char_spacing}
                    min={-2}
                    max={10}
                    step={0.5}
                    style={{ width: '100%' }}
                    onChange={value => update(next => { next.body.char_spacing = Number(value ?? 0) })}
                  />
                </Field>
                <Field label="加粗 / 颜色" wide>
                  <Space size={SPACE.xs}>
                    <Switch
                      size="small"
                      checked={draft.body.bold}
                      onChange={v => update(next => { next.body.bold = v })}
                    />
                    <div style={{ width: 104 }}>
                      <ColorInput value={draft.body.color} onChange={v => update(next => { next.body.color = v })} />
                    </div>
                  </Space>
                </Field>
                <Field label="孤行控制 / 与下段同页" wide>
                  <Space size={SPACE.xs}>
                    <Switch
                      size="small"
                      checked={draft.body.widow_control}
                      onChange={v => update(next => { next.body.widow_control = v })}
                    />
                    <Switch
                      size="small"
                      checked={draft.body.keep_with_next}
                      onChange={v => update(next => { next.body.keep_with_next = v })}
                    />
                  </Space>
                </Field>
              </div>
            ),
          },
          {
            key: 'headings',
            label: '标题与编号',
            children: (
              <div data-testid="template-section-headings">
                <div className="cn-doc-tpl-fields">
                  <Field label="标题编号">
                    <Select
                      size="small"
                      value={draft.numbering.heading}
                      onChange={v => update(next => { next.numbering.heading = v })}
                      options={NUMBERING_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                  </Field>
                </div>
                <div className="cn-doc-tpl-headings">
                  <div className="cn-doc-tpl-headings-head">
                    <span>级别</span>
                    <span>中文字体</span>
                    <span>字号</span>
                    <span>对齐</span>
                    <span>段前 / 段后</span>
                    <span>加粗</span>
                  </div>
                  {draft.headings.map((heading, index) => (
                    <div className="cn-doc-tpl-headings-row" key={`h${index + 1}`}>
                      <Text strong className="cn-doc-tpl-headings-level">H{index + 1}</Text>
                      <FontInput
                        value={heading.east_asia_font}
                        options={EAST_ASIA_FONTS}
                        onChange={v => update(next => { next.headings[index].east_asia_font = v })}
                      />
                      <InputNumber
                        size="small"
                        value={heading.size}
                        min={8}
                        max={72}
                        step={0.5}
                        onChange={value => update(next => { next.headings[index].size = Number(value ?? 12) })}
                      />
                      <Select
                        size="small"
                        value={heading.align}
                        onChange={v => update(next => { next.headings[index].align = v })}
                        options={ALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                      />
                      <Space size={SPACE.hairline}>
                        <InputNumber
                          size="small"
                          value={heading.space_before}
                          min={0}
                          max={36}
                          style={{ width: 60 }}
                          onChange={value => update(next => { next.headings[index].space_before = Number(value ?? 0) })}
                        />
                        <InputNumber
                          size="small"
                          value={heading.space_after}
                          min={0}
                          max={36}
                          style={{ width: 60 }}
                          onChange={value => update(next => { next.headings[index].space_after = Number(value ?? 0) })}
                        />
                      </Space>
                      <Switch
                        size="small"
                        checked={heading.bold}
                        onChange={v => update(next => { next.headings[index].bold = v })}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ),
          },
          {
            key: 'table',
            label: '表格与题注',
            children: (
              <div data-testid="template-section-table">
                <div className="cn-doc-tpl-fields">
                  <Field label="表格样式">
                    <Select
                      size="small"
                      value={draft.table.style}
                      onChange={v => update(next => { next.table.style = v })}
                      options={TABLE_STYLE_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                  </Field>
                  <Field label="表头底色 / 字色" wide>
                    <Space size={SPACE.xs}>
                      <div style={{ width: 96 }}>
                        <ColorInput
                          value={draft.table.header_bg}
                          onChange={v => update(next => { next.table.header_bg = v })}
                        />
                      </div>
                      <div style={{ width: 96 }}>
                        <ColorInput
                          value={draft.table.header_color}
                          onChange={v => update(next => { next.table.header_color = v })}
                        />
                      </div>
                    </Space>
                  </Field>
                  <Field label="表格字号 / 边框色" wide>
                    <Space size={SPACE.xs}>
                      <InputNumber
                        size="small"
                        value={draft.table.size}
                        min={6}
                        max={24}
                        step={0.5}
                        style={{ width: 72 }}
                        onChange={value => update(next => { next.table.size = Number(value ?? 10.5) })}
                      />
                      <div style={{ width: 96 }}>
                        <ColorInput
                          value={draft.table.border_color}
                          onChange={v => update(next => { next.table.border_color = v })}
                        />
                      </div>
                    </Space>
                  </Field>
                  <Field label="单元格对齐">
                    <Select
                      size="small"
                      value={draft.table.cell_valign}
                      onChange={v => update(next => { next.table.cell_valign = v })}
                      options={CELL_VALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                  </Field>
                  <Field label="表头加粗 / 跨页重复 / 斑马纹" wide>
                    <Space size={SPACE.xs}>
                      <Switch
                        size="small"
                        checked={draft.table.header_bold}
                        onChange={v => update(next => { next.table.header_bold = v })}
                      />
                      <Switch
                        size="small"
                        checked={draft.table.header_repeat}
                        onChange={v => update(next => { next.table.header_repeat = v })}
                      />
                      <Switch
                        size="small"
                        checked={draft.table.zebra}
                        onChange={v => update(next => { next.table.zebra = v })}
                      />
                    </Space>
                  </Field>
                </div>
                <div className="cn-doc-tpl-fields">
                  {(['figure', 'table'] as const).map(kind => {
                    const caption = draft.captions[kind]
                    return (
                      <Field
                        key={kind}
                        label={kind === 'figure' ? '图题注' : '表题注'}
                        hint={kind === 'figure' ? '取图片 alt 文字' : '取表格前「表：说明」段落'}
                      >
                        <Space size={SPACE.xs}>
                          <Switch
                            size="small"
                            checked={caption.enabled}
                            onChange={v => update(next => { next.captions[kind].enabled = v })}
                          />
                          <Select
                            size="small"
                            value={caption.position}
                            style={{ width: 96 }}
                            onChange={v => update(next => { next.captions[kind].position = v })}
                            options={CAPTION_POSITION_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                          />
                          <Select
                            size="small"
                            value={caption.numbering}
                            style={{ width: 118 }}
                            onChange={v => update(next => { next.captions[kind].numbering = v })}
                            options={CAPTION_NUMBERING_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                          />
                        </Space>
                      </Field>
                    )
                  })}
                </div>
              </div>
            ),
          },
          {
            key: 'listcode',
            label: '列表与代码',
            children: (
              <div className="cn-doc-tpl-fields" data-testid="template-section-list">
                <Field label="列表缩进 / 悬挂 (pt)" wide>
                  <Space size={SPACE.xs}>
                    <InputNumber
                      size="small"
                      value={draft.lists.indent_pt}
                      min={8}
                      max={40}
                      style={{ width: 68 }}
                      onChange={value => update(next => { next.lists.indent_pt = Number(value ?? 16) })}
                    />
                    <InputNumber
                      size="small"
                      value={draft.lists.hanging_pt}
                      min={4}
                      max={30}
                      style={{ width: 68 }}
                      onChange={value => update(next => { next.lists.hanging_pt = Number(value ?? 14) })}
                    />
                  </Space>
                </Field>
                <Field label="列表段后 / 符号" wide>
                  <Space size={SPACE.xs}>
                    <InputNumber
                      size="small"
                      value={draft.lists.space_after}
                      min={0}
                      max={12}
                      style={{ width: 68 }}
                      onChange={value => update(next => { next.lists.space_after = Number(value ?? 2) })}
                    />
                    <Select
                      size="small"
                      value={draft.lists.marker}
                      style={{ width: 96 }}
                      onChange={v => update(next => { next.lists.marker = v })}
                      options={LIST_MARKER_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                  </Space>
                </Field>
                <Field label="代码字体">
                  <FontInput
                    value={draft.code.latin_font}
                    options={CODE_FONTS}
                    onChange={v => update(next => { next.code.latin_font = v; next.code.east_asia_font = v })}
                  />
                </Field>
                <Field label="代码字号 / 底色" wide>
                  <Space size={SPACE.xs}>
                    <InputNumber
                      size="small"
                      value={draft.code.size}
                      min={6}
                      max={24}
                      step={0.5}
                      style={{ width: 72 }}
                      onChange={value => update(next => { next.code.size = Number(value ?? 9) })}
                    />
                    <div style={{ width: 96 }}>
                      <ColorInput value={draft.code.bg} onChange={v => update(next => { next.code.bg = v })} />
                    </div>
                  </Space>
                </Field>
                <Field label="代码边框色 / 左侧强调条" wide>
                  <Space size={SPACE.xs}>
                    <div style={{ width: 96 }}>
                      <ColorInput value={draft.code.border} onChange={v => update(next => { next.code.border = v })} />
                    </div>
                    <Switch
                      size="small"
                      checked={draft.code.left_bar}
                      onChange={v => update(next => { next.code.left_bar = v })}
                    />
                  </Space>
                </Field>
              </div>
            ),
          },
        ]}
      />

      {dirty && (
        <Text type="secondary" className="cn-doc-tpl-dirty">
          有未保存的修改（内置模板请用「另存为」）
        </Text>
      )}
    </div>
  )

  return (
    <>
      {pageHead}

      <div className="cn-doc-tpl-split" data-testid="template-panel">
        <SectionBox
          title="模板清单"
          icon={<UnorderedListOutlined />}
          extra={<span>{items.length} 个</span>}
          flush
          testId="template-list"
        >
          <button
            type="button"
            className="cn-doc-tpl-group"
            aria-expanded={!collapsedGroups.builtin}
            data-testid="template-group-builtin"
            onClick={() => setCollapsedGroups(groups => ({ ...groups, builtin: !groups.builtin }))}
          >
            <span className="cn-doc-tpl-group-title">
              {collapsedGroups.builtin ? <RightOutlined /> : <DownOutlined />}
              内置模板
            </span>
            <span>{builtins.length}</span>
          </button>
          {!collapsedGroups.builtin && builtins.map(rowNode)}
          <button
            type="button"
            className="cn-doc-tpl-group"
            aria-expanded={!collapsedGroups.custom}
            data-testid="template-group-custom"
            onClick={() => setCollapsedGroups(groups => ({ ...groups, custom: !groups.custom }))}
          >
            <span className="cn-doc-tpl-group-title">
              {collapsedGroups.custom ? <RightOutlined /> : <DownOutlined />}
              自定义模板
            </span>
            <span>{customs.length}</span>
          </button>
          {!collapsedGroups.custom && (
            customs.length === 0 ? (
              <div className="cn-doc-tpl-empty">
                <Text type="secondary">还没有自定义模板：选一个内置模板后点「另存为」即可修改。</Text>
              </div>
            ) : (
              customs.map(rowNode)
            )
          )}
        </SectionBox>

        {draft ? (
          <div
            className={[
              'cn-doc-tpl-detail-area',
              previewOpen ? '' : 'cn-doc-tpl-detail-area--preview-collapsed',
            ].filter(Boolean).join(' ')}
          >
            <SectionBox
              title={selected ? selected.name : '排版配置'}
              icon={<FileTextOutlined />}
              extra={
                <span className="cn-doc-tpl-head-extra">
                  <span className="cn-doc-tpl-tags">
                    {isBuiltin && <Tag>内置</Tag>}
                    {!isBuiltin && selected && <Tag>自定义</Tag>}
                    {selected && (selected.is_default || selected.ref === defaultRef) && (
                      <Tag color="blue">默认</Tag>
                    )}
                    {dirty && <Tag color="orange">未保存</Tag>}
                  </span>
                  {/* 预览收起 / 展开：放在配置方盒标题行最右侧（与标题同一行） */}
                  <Tooltip title={previewOpen ? '收起预览' : '展开预览'}>
                    <Button
                      size="small"
                      type="text"
                      data-testid="template-preview-toggle"
                      aria-expanded={previewOpen}
                      aria-label={previewOpen ? '收起预览' : '展开预览'}
                      icon={previewOpen ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                      onClick={() => setPreviewOpen(value => !value)}
                    />
                  </Tooltip>
                </span>
              }
              testId="template-detail"
              className="cn-doc-tpl-detail"
            >
              {actionBar}
              {configBody}
            </SectionBox>

            {previewOpen && (
              <SectionBox
                title="预览"
                icon={<EyeOutlined />}
                extra={<span className="cn-doc-tpl-preview-hint">示例正文</span>}
                testId="template-preview-box"
                className="cn-doc-tpl-preview-box"
              >
                <TemplatePreview config={draft} />
              </SectionBox>
            )}
          </div>
        ) : (
          <SectionBox
            title="排版配置"
            icon={<FileTextOutlined />}
            testId="template-detail"
            className="cn-doc-tpl-detail"
          >
            <Empty description="选择一个模板开始配置" />
          </SectionBox>
        )}
      </div>

      <Modal
        title="新建模板"
        open={createOpen}
        okText="创建"
        cancelText="取消"
        confirmLoading={createMut.isPending}
        onOk={() => createMut.mutate()}
        onCancel={() => setCreateOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            data-testid="template-create-name"
            value={createName}
            maxLength={80}
            placeholder="模板名称（同工作区不可重名）"
            onChange={e => setCreateName(e.target.value)}
          />
          <Select
            data-testid="template-create-preset"
            value={createPreset}
            style={{ width: '100%' }}
            onChange={setCreatePreset}
            options={builtins.map(item => ({
              value: item.ref.replace('builtin:', ''),
              label: `${item.name}：${item.description}`,
            }))}
          />
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
            新模板以所选内置预设为起点，创建后可在右侧继续调整并保存。
          </Text>
        </Space>
      </Modal>

      <Modal
        title="另存为自定义模板"
        open={saveAsOpen}
        okText="另存为"
        cancelText="取消"
        confirmLoading={saveAsMut.isPending}
        onOk={() => saveAsMut.mutate()}
        onCancel={() => setSaveAsOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            data-testid="template-save-as-name"
            value={saveAsName}
            maxLength={80}
            placeholder="模板名称（同工作区不可重名）"
            onChange={e => setSaveAsName(e.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
            另存为会复制当前面板里的配置（含未保存修改），保存后可继续调整。
          </Text>
        </Space>
      </Modal>
    </>
  )
}
