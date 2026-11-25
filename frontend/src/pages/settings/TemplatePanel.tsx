/** 个人设置「模板」页签 — 文档导出模板（ADR 0152）.
 *
 * 后端接口（工作区级，`/api/v1/workspaces/{wid}/documents/templates`）：
 * - `GET    ""`          内置只读预设 + 工作区自定义 + 当前默认引用
 * - `POST   ""`          新建（`preset_key` 另存为内置预设，或提交完整 config）
 * - `PUT    /{id}`       改名 / 改配置 / 设为默认
 * - `DELETE /{id}`       删除自定义（默认被删后回落内置 standard）
 * - `POST   /preview`    用**未保存**的当前配置渲染示例 docx / pdf
 *
 * 交互要点：
 * - 内置预设只读：改配置后只能「另存为」，写操作一律走后端 400 兜底；
 * - 一份配置同时供电 Word 与 PDF（PDF 侧字体按服务器可用字体最佳匹配并降级）；
 * - 面板内 CSS 等比预览即时反馈，真实效果用「下载示例」看；
 * - 仅 owner / editor 可写，viewer 只读浏览；未进入工作区时显示空态。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, App, AutoComplete, Button, Collapse, Empty, Input, InputNumber, Modal,
  Segmented, Select, Space, Switch, Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, DownloadOutlined, PlusOutlined, SaveOutlined, StarOutlined,
} from '@ant-design/icons'
import { workspaceApi, exportTemplateApi } from '@/api'
import type { ExportTemplateConfig, ExportTemplateItem } from '@/api'
import { SPACE } from '@/theme/tokens'
import SectionHeader from './SectionHeader'
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
  previewStyles,
} from './templateOptions'

const { Text } = Typography

/** 深拷贝一份模板配置（配置是纯数据，JSON 往返足够且兼容旧内核） */
function cloneConfig(config: ExportTemplateConfig): ExportTemplateConfig {
  return JSON.parse(JSON.stringify(config)) as ExportTemplateConfig
}

/** 一行标签 + 控件的紧凑布局 */
function Field({ label, children, width = 180 }: { label: string; children: React.ReactNode; width?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: SPACE.xs, marginBottom: SPACE.xs, flexWrap: 'wrap' }}>
      <Text style={{ fontSize: 'var(--cn-text-sm)', minWidth: 96 }}>{label}</Text>
      <div style={{ width }}>{children}</div>
    </div>
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
      placeholder="#000000"
      prefix={
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 12,
            height: 12,
            borderRadius: 2,
            border: '1px solid var(--cn-border)',
            background: value,
          }}
        />
      }
    />
  )
}

/** 面板内 CSS 等比预览（与 Word 不逐像素对齐，只表达字号 / 行距 / 缩进 / 表头） */
function TemplatePreview({ config }: { config: ExportTemplateConfig }) {
  const styles = useMemo(() => previewStyles(config), [config])
  return (
    <div
      data-testid="template-preview"
      style={{
        border: '1px solid var(--cn-border)',
        borderRadius: 6,
        padding: SPACE.md,
        background: 'var(--cn-bg-container)',
        maxHeight: 260,
        overflow: 'auto',
      }}
    >
      <div style={{ ...styles.page, margin: '0 auto' }}>
        <div style={styles.headings(1)}>第一章 概述</div>
        <div style={styles.headings(2)}>1.1 背景</div>
        <div style={styles.body}>
          这是一段示例正文，用于查看字体、字号、行距、段前段后与首行缩进的实际效果。
        </div>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.headerCell}>指标</th>
              <th style={styles.headerCell}>数量</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={styles.cell}>覆盖率</td>
              <td style={styles.cell}>95.2</td>
            </tr>
          </tbody>
        </table>
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

  const items = listQuery.data?.items ?? []
  const selected: ExportTemplateItem | undefined = items.find(item => item.ref === selectedRef)
  const isBuiltin = selected?.source === 'builtin'
  const baseline = useMemo(
    () => (selected ? JSON.stringify(selected.config) : ''),
    [selected],
  )
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
      exportTemplateApi.update(workspaceId, Number(selected!.ref), {
        name,
        description,
        config: draft!,
      }),
    onSuccess: () => {
      message.success('模板已保存')
      invalidate()
      queryClient.invalidateQueries({ queryKey: ['export-templates-all'] })
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

  if (!hasWorkspace) {
    return (
      <div style={{ padding: '12px 0' }}>
        <Alert
          type="info"
          showIcon
          message="模板属于工作区"
          description="请先进入一个工作区，再在「模板」页签管理该工作区的文档导出模板。"
        />
      </div>
    )
  }

  if (listQuery.isLoading) {
    return <div className="cn-state">加载中…</div>
  }

  const builtins = items.filter(item => item.source === 'builtin')
  const customs = items.filter(item => item.source === 'custom')
  const defaultRef = listQuery.data?.default_ref

  const listNode = (
    <div data-testid="template-list" style={{ minWidth: 200, maxWidth: 240 }}>
      <SectionHeader title="内置模板" description="只读，可另存为自定义" />
      {builtins.map(item => (
        <div
          key={item.ref}
          role="button"
          tabIndex={0}
          data-testid={`template-item-${item.ref}`}
          onClick={() => selectTemplate(item.ref)}
          onKeyDown={event => { if (event.key === 'Enter') selectTemplate(item.ref) }}
          style={{
            cursor: 'pointer',
            padding: `${SPACE.xs} ${SPACE.xs}`,
            borderRadius: 4,
            marginBottom: 2,
            background: item.ref === selectedRef ? 'var(--cn-bg-selected)' : undefined,
          }}
        >
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>{item.name}</Text>
          {item.ref === defaultRef && <Tag style={{ marginLeft: SPACE.xs }}>默认</Tag>}
        </div>
      ))}
      <SectionHeader title="自定义模板" description="随工作区备份往返" topGap={12} />
      {customs.length === 0 && (
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
          还没有自定义模板，选一个内置模板后「另存为」即可修改。
        </Text>
      )}
      {customs.map(item => (
        <div
          key={item.ref}
          role="button"
          tabIndex={0}
          data-testid={`template-item-${item.ref}`}
          onClick={() => selectTemplate(item.ref)}
          onKeyDown={event => { if (event.key === 'Enter') selectTemplate(item.ref) }}
          style={{
            cursor: 'pointer',
            padding: `${SPACE.xs} ${SPACE.xs}`,
            borderRadius: 4,
            marginBottom: 2,
            background: item.ref === selectedRef ? 'var(--cn-bg-selected)' : undefined,
          }}
        >
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>{item.name}</Text>
          {item.is_default && <Tag style={{ marginLeft: SPACE.xs }}>默认</Tag>}
        </div>
      ))}
    </div>
  )

  const actions = (
    <Space wrap>
      <Button
        size="small"
        icon={<PlusOutlined />}
        data-testid="template-save-as-btn"
        onClick={() => {
          setSaveAsName(selected ? `${selected.name} 副本` : '新模板')
          setSaveAsOpen(true)
        }}
      >
        另存为
      </Button>
      {!isBuiltin && canEdit && (
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
      )}
      {!isBuiltin && canEdit && !selected?.is_default && (
        <Button
          size="small"
          icon={<StarOutlined />}
          data-testid="template-default-btn"
          loading={defaultMut.isPending}
          onClick={() => defaultMut.mutate()}
        >
          设为默认
        </Button>
      )}
      {!isBuiltin && canEdit && (
        <Button
          size="small"
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
      )}
      <Button
        size="small"
        icon={<DownloadOutlined />}
        data-testid="template-preview-btn"
        loading={previewMut.isPending}
        onClick={() => previewMut.mutate('docx')}
      >
        下载示例 Word
      </Button>
      <Button
        size="small"
        data-testid="template-preview-pdf-btn"
        loading={previewMut.isPending}
        onClick={() => previewMut.mutate('pdf')}
      >
        下载示例 PDF
      </Button>
    </Space>
  )

  const editor = draft && (
    <div style={{ flex: 1, minWidth: 320 }}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Input
          data-testid="template-name-input"
          value={name}
          onChange={e => setName(e.target.value)}
          disabled={isBuiltin || !canEdit}
          maxLength={80}
          addonBefore="名称"
        />
        <Input
          data-testid="template-desc-input"
          value={description}
          onChange={e => setDescription(e.target.value)}
          disabled={isBuiltin || !canEdit}
          maxLength={200}
          addonBefore="说明"
        />
      </Space>
      <div style={{ margin: `${SPACE.xs} 0` }}>{actions}</div>
      {isBuiltin && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: SPACE.xs }}
          message="内置模板只读"
          description="修改配置后点「另存为」生成自定义模板；内置模板不可修改或删除。"
        />
      )}
      {!canEdit && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: SPACE.xs }}
          message="只读浏览"
          description="仅工作区所有者 / 编辑者可以新增或修改模板。"
        />
      )}
      <TemplatePreview config={draft} />
      <Collapse
        size="small"
        style={{ marginTop: SPACE.xs }}
        defaultActiveKey={['body']}
        items={[
          {
            key: 'page',
            label: '页面与页眉页脚',
            children: (
              <div data-testid="template-section-page">
                <Field label="纸张" width={220}>
                  <Select
                    value={draft.page.paper}
                    onChange={v => update(next => { next.page.paper = v })}
                    options={PAPER_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="页边距(cm)">
                  <Space size={4}>
                    {(['margin_top', 'margin_bottom', 'margin_left', 'margin_right'] as const).map(key => (
                      <InputNumber
                        key={key}
                        value={draft.page[key]}
                        min={0.5}
                        max={5}
                        step={0.1}
                        style={{ width: 72 }}
                        onChange={value => update(next => { next.page[key] = Number(value ?? 2.54) })}
                      />
                    ))}
                  </Space>
                </Field>
                <Field label="页眉文字" width={220}>
                  <Input
                    value={draft.header_footer.header_text}
                    maxLength={120}
                    placeholder="留空则不显示页眉"
                    onChange={e => update(next => { next.header_footer.header_text = e.target.value })}
                  />
                </Field>
                <Field label="页脚页码" width={180}>
                  <Select
                    value={draft.header_footer.page_number}
                    onChange={v => update(next => { next.header_footer.page_number = v })}
                    options={PAGE_NUMBER_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="首页不同">
                  <Switch
                    checked={draft.header_footer.first_page_different}
                    onChange={v => update(next => { next.header_footer.first_page_different = v })}
                  />
                </Field>
                <Field label="页眉页脚字号">
                  <InputNumber
                    value={draft.header_footer.font_size}
                    min={6}
                    max={14}
                    step={0.5}
                    onChange={value => update(next => { next.header_footer.font_size = Number(value ?? 8) })}
                  />
                </Field>
              </div>
            ),
          },
          {
            key: 'body',
            label: '正文段落',
            children: (
              <div data-testid="template-section-body">
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
                <Field label="字号(pt)">
                  <InputNumber
                    data-testid="template-body-size"
                    value={draft.body.size}
                    min={8}
                    max={72}
                    step={0.5}
                    addonAfter={fontPtLabel(draft.body.size)}
                    style={{ width: 150 }}
                    onChange={value => update(next => { next.body.size = Number(value ?? 10.5) })}
                  />
                </Field>
                <Field label="对齐">
                  <Select
                    value={draft.body.align}
                    onChange={v => update(next => { next.body.align = v })}
                    options={ALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="行距">
                  <Space size={4}>
                    <Segmented
                      size="small"
                      value={draft.body.line_spacing_rule}
                      options={LINE_RULE_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                      onChange={v => update(next => { next.body.line_spacing_rule = v as 'multiple' | 'fixed' })}
                    />
                    {draft.body.line_spacing_rule === 'multiple' ? (
                      <InputNumber
                        value={draft.body.line_spacing}
                        min={1}
                        max={3}
                        step={0.05}
                        onChange={value => update(next => { next.body.line_spacing = Number(value ?? 1.5) })}
                      />
                    ) : (
                      <InputNumber
                        value={draft.body.line_spacing_pt}
                        min={10}
                        max={60}
                        step={1}
                        addonAfter="pt"
                        onChange={value => update(next => { next.body.line_spacing_pt = Number(value ?? 28) })}
                      />
                    )}
                  </Space>
                </Field>
                <Field label="段前/段后">
                  <Space size={4}>
                    <InputNumber
                      value={draft.body.space_before}
                      min={0}
                      max={36}
                      onChange={value => update(next => { next.body.space_before = Number(value ?? 0) })}
                    />
                    <InputNumber
                      value={draft.body.space_after}
                      min={0}
                      max={36}
                      onChange={value => update(next => { next.body.space_after = Number(value ?? 0) })}
                    />
                  </Space>
                </Field>
                <Field label="首行缩进(字符)">
                  <InputNumber
                    value={draft.body.first_line_indent_chars}
                    min={0}
                    max={8}
                    step={0.5}
                    onChange={value => update(next => { next.body.first_line_indent_chars = Number(value ?? 0) })}
                  />
                </Field>
                <Field label="字间距(pt)">
                  <InputNumber
                    value={draft.body.char_spacing}
                    min={-2}
                    max={10}
                    step={0.5}
                    onChange={value => update(next => { next.body.char_spacing = Number(value ?? 0) })}
                  />
                </Field>
                <Field label="加粗 / 颜色">
                  <Space size={4}>
                    <Switch
                      checked={draft.body.bold}
                      onChange={v => update(next => { next.body.bold = v })}
                    />
                    <div style={{ width: 130 }}>
                      <ColorInput
                        value={draft.body.color}
                        onChange={v => update(next => { next.body.color = v })}
                      />
                    </div>
                  </Space>
                </Field>
                <Field label="孤行控制 / 与下段同页">
                  <Space size={4}>
                    <Switch
                      checked={draft.body.widow_control}
                      onChange={v => update(next => { next.body.widow_control = v })}
                    />
                    <Switch
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
                <Field label="标题编号" width={200}>
                  <Select
                    value={draft.numbering.heading}
                    onChange={v => update(next => { next.numbering.heading = v })}
                    options={NUMBERING_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                {draft.headings.map((heading, index) => (
                  <div
                    key={`h${index + 1}`}
                    style={{ display: 'flex', alignItems: 'center', gap: SPACE.xs, marginBottom: 4, flexWrap: 'wrap' }}
                  >
                    <Text style={{ width: 34, fontSize: 'var(--cn-text-sm)' }}>H{index + 1}</Text>
                    <FontInput
                      value={heading.east_asia_font}
                      options={EAST_ASIA_FONTS}
                      onChange={v => update(next => { next.headings[index].east_asia_font = v })}
                    />
                    <InputNumber
                      value={heading.size}
                      min={8}
                      max={72}
                      step={0.5}
                      style={{ width: 84 }}
                      onChange={value => update(next => { next.headings[index].size = Number(value ?? 12) })}
                    />
                    <Select
                      value={heading.align}
                      style={{ width: 110 }}
                      onChange={v => update(next => { next.headings[index].align = v })}
                      options={ALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                    <Space size={2}>
                      <Text type="secondary" style={{ fontSize: 'var(--cn-text-2xs)' }}>段前</Text>
                      <InputNumber
                        value={heading.space_before}
                        min={0}
                        max={36}
                        style={{ width: 62 }}
                        onChange={value => update(next => { next.headings[index].space_before = Number(value ?? 0) })}
                      />
                      <Text type="secondary" style={{ fontSize: 'var(--cn-text-2xs)' }}>段后</Text>
                      <InputNumber
                        value={heading.space_after}
                        min={0}
                        max={36}
                        style={{ width: 62 }}
                        onChange={value => update(next => { next.headings[index].space_after = Number(value ?? 0) })}
                      />
                    </Space>
                    <Tooltip title="加粗">
                      <Switch
                        checked={heading.bold}
                        onChange={v => update(next => { next.headings[index].bold = v })}
                      />
                    </Tooltip>
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'table',
            label: '表格与题注',
            children: (
              <div data-testid="template-section-table">
                <Field label="表格样式" width={160}>
                  <Select
                    value={draft.table.style}
                    onChange={v => update(next => { next.table.style = v })}
                    options={TABLE_STYLE_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field label="表头底色 / 字色">
                  <Space size={4}>
                    <div style={{ width: 110 }}>
                      <ColorInput
                        value={draft.table.header_bg}
                        onChange={v => update(next => { next.table.header_bg = v })}
                      />
                    </div>
                    <div style={{ width: 110 }}>
                      <ColorInput
                        value={draft.table.header_color}
                        onChange={v => update(next => { next.table.header_color = v })}
                      />
                    </div>
                  </Space>
                </Field>
                <Field label="表格字号 / 边框色" width={260}>
                  <Space size={4}>
                    <InputNumber
                      value={draft.table.size}
                      min={6}
                      max={24}
                      step={0.5}
                      style={{ width: 84 }}
                      onChange={value => update(next => { next.table.size = Number(value ?? 10.5) })}
                    />
                    <div style={{ width: 110 }}>
                      <ColorInput
                        value={draft.table.border_color}
                        onChange={v => update(next => { next.table.border_color = v })}
                      />
                    </div>
                  </Space>
                </Field>
                <Field label="表头加粗 / 跨页重复">
                  <Space size={4}>
                    <Switch
                      checked={draft.table.header_bold}
                      onChange={v => update(next => { next.table.header_bold = v })}
                    />
                    <Switch
                      checked={draft.table.header_repeat}
                      onChange={v => update(next => { next.table.header_repeat = v })}
                    />
                  </Space>
                </Field>
                <Field label="斑马纹 / 单元格">
                  <Space size={4}>
                    <Switch
                      checked={draft.table.zebra}
                      onChange={v => update(next => { next.table.zebra = v })}
                    />
                    <Select
                      value={draft.table.cell_valign}
                      style={{ width: 120 }}
                      onChange={v => update(next => { next.table.cell_valign = v })}
                      options={CELL_VALIGN_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                    />
                  </Space>
                </Field>
                {(['figure', 'table'] as const).map(kind => {
                  const caption = draft.captions[kind]
                  const label = kind === 'figure' ? '图题注' : '表题注'
                  return (
                    <Field key={kind} label={label} width={330}>
                      <Space size={4}>
                        <Switch
                          checked={caption.enabled}
                          onChange={v => update(next => { next.captions[kind].enabled = v })}
                        />
                        <Select
                          value={caption.position}
                          style={{ width: 110 }}
                          onChange={v => update(next => { next.captions[kind].position = v })}
                          options={CAPTION_POSITION_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                        />
                        <Select
                          value={caption.numbering}
                          style={{ width: 130 }}
                          onChange={v => update(next => { next.captions[kind].numbering = v })}
                          options={CAPTION_NUMBERING_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
                        />
                      </Space>
                    </Field>
                  )
                })}
                <Text type="secondary" style={{ fontSize: 'var(--cn-text-2xs)' }}>
                  表题注取表格前紧邻的「表：说明」段落；图题注取图片替代文字（alt）。
                </Text>
              </div>
            ),
          },
          {
            key: 'listcode',
            label: '列表与代码',
            children: (
              <div data-testid="template-section-list">
                <Field label="列表缩进(pt)">
                  <Space size={4}>
                    <InputNumber
                      value={draft.lists.indent_pt}
                      min={8}
                      max={40}
                      onChange={value => update(next => { next.lists.indent_pt = Number(value ?? 16) })}
                    />
                    <InputNumber
                      value={draft.lists.hanging_pt}
                      min={4}
                      max={30}
                      onChange={value => update(next => { next.lists.hanging_pt = Number(value ?? 14) })}
                    />
                  </Space>
                </Field>
                <Field label="列表段后 / 符号" width={220}>
                  <Space size={4}>
                    <InputNumber
                      value={draft.lists.space_after}
                      min={0}
                      max={12}
                      onChange={value => update(next => { next.lists.space_after = Number(value ?? 2) })}
                    />
                    <Select
                      value={draft.lists.marker}
                      style={{ width: 110 }}
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
                <Field label="代码字号 / 底色" width={260}>
                  <Space size={4}>
                    <InputNumber
                      value={draft.code.size}
                      min={6}
                      max={24}
                      step={0.5}
                      style={{ width: 84 }}
                      onChange={value => update(next => { next.code.size = Number(value ?? 9) })}
                    />
                    <div style={{ width: 110 }}>
                      <ColorInput
                        value={draft.code.bg}
                        onChange={v => update(next => { next.code.bg = v })}
                      />
                    </div>
                  </Space>
                </Field>
                <Field label="边框色 / 左侧强调条">
                  <Space size={4}>
                    <div style={{ width: 110 }}>
                      <ColorInput
                        value={draft.code.border}
                        onChange={v => update(next => { next.code.border = v })}
                      />
                    </div>
                    <Switch
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
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: SPACE.xs }}>
          有未保存的修改（内置模板请用「另存为」）
        </Text>
      )}
    </div>
  )

  return (
    <div style={{ padding: '12px 0' }}>
      <div data-testid="template-panel" style={{ display: 'flex', gap: SPACE.lg, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {listNode}
        {editor ?? <Empty description="选择一个模板开始配置" />}
      </div>
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
    </div>
  )
}
