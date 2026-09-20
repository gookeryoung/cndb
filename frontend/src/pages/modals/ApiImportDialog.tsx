/** API 自动建表 / 数据抓取对话框 — 双模式：新建表 & 追加到已有表. */

import { useState, useCallback } from 'react'
import { Modal, Form, Input, Select, Button, Table, Alert, App as AntApp, Space, InputNumber, Collapse, Tag, Descriptions } from 'antd'
import { ApiOutlined, SearchOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import { importApi } from '@/api'
import type { ApiAnalyzeColumn, ApiAnalyzeResult, ApiFetchRequest } from '@/api'
import { getFieldTypeColor, getFieldTypeLabel } from '@/utils/fieldTypeMeta'

interface Props {
  /** Modal 模式时的开关；embed 模式下忽略 */
  open?: boolean
  wid: string
  /** 目标表 ID（追加模式必须提供；建表模式可选） */
  tid?: string
  /** 对话框标题；不传时按 mode 自动生成 */
  title?: string
  /** 关闭回调（Modal 模式使用；embed 模式下忽略） */
  onClose?: () => void
  /** 成功回调 — create 模式返回新表 id，append 模式返回追加行数 */
  onSuccess?: (result: { table_id?: number | string; appended_rows?: number }) => void
  /** embed 模式：嵌入到其他 Modal/Tab 中，不渲染外层 Modal 容器 */
  embed?: boolean
}

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

function renderSamples(col: ApiAnalyzeColumn): string {
  const list = col.samples
  if (!list || list.length === 0) return '—'
  return list
    .slice(0, 3)
    .map((v) => (v === null ? 'null' : typeof v === 'object' ? JSON.stringify(v) : String(v)))
    .join(' · ')
}

/** 安全解析 JSON 文本，失败返回 undefined */
function tryParseJson(text: string | undefined): unknown {
  if (!text || !text.trim()) return undefined
  try { return JSON.parse(text) } catch { return undefined }
}

/** 把 "k: v\nk2: v2" 文本转回 dict（忽略空行和 # 注释） */
function parseHeadersText(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const idx = line.indexOf(':')
    if (idx <= 0) continue
    const k = line.slice(0, idx).trim()
    const v = line.slice(idx + 1).trim()
    if (k) result[k] = v
  }
  return result
}

export default function ApiImportDialog({ open, wid, tid, title, onClose, onSuccess, embed }: Props) {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [analyzeResult, setAnalyzeResult] = useState<ApiAnalyzeResult | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const mode: 'append' | 'create' = tid ? 'append' : 'create'
  const dialogTitle = title ?? (mode === 'append' ? 'API 抓取 · 追加到当前表' : 'API 抓取 · 自动建表')

  const buildPayload = useCallback((): ApiFetchRequest => {
    const values = form.getFieldsValue() as {
      url: string; method: string; headers_text?: string; params_text?: string
      body_text?: string; data_path?: string; timeout?: number
    }
    const payload: ApiFetchRequest = {
      url: values.url,
      method: values.method as ApiFetchRequest['method'],
      data_path: values.data_path || null,
      timeout: values.timeout ?? 15,
    }
    const headers = parseHeadersText(values.headers_text ?? '')
    if (Object.keys(headers).length) payload.headers = headers

    const paramsJson = tryParseJson(values.params_text)
    if (paramsJson && typeof paramsJson === 'object' && !Array.isArray(paramsJson)) {
      payload.params = paramsJson as Record<string, unknown>
    }

    const bodyJson = tryParseJson(values.body_text)
    if (bodyJson !== undefined) payload.body = bodyJson
    else if (values.body_text && values.body_text.trim()) payload.body = values.body_text

    return payload
  }, [form])

  const handleAnalyze = useCallback(async () => {
    try {
      await form.validateFields(['url', 'method'])
    } catch {
      return
    }
    setErrorMsg(null)
    setAnalyzing(true)
    try {
      const payload = buildPayload()
      const result = await importApi.fetchAnalyze(wid, payload)
      setAnalyzeResult(result)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '分析失败'
      setErrorMsg(msg)
      setAnalyzeResult(null)
    } finally {
      setAnalyzing(false)
    }
  }, [form, wid, buildPayload])

  const handleImport = useCallback(async () => {
    if (!analyzeResult) {
      message.warning('请先点击"分析"获取 API 返回结构')
      return
    }
    try {
      if (mode === 'create') {
        await form.validateFields(['url', 'method', 'table_name'])
      } else {
        await form.validateFields(['url', 'method'])
      }
    } catch {
      return
    }

    setImporting(true)
    setErrorMsg(null)
    try {
      const payload = buildPayload()
      let result: { table_id?: number | string; appended_rows?: number }
      if (mode === 'create') {
        const tableName = form.getFieldValue('table_name') as string
        const r = await importApi.fetchCreateTable(wid, tableName, payload)
        result = { table_id: r.table_id }
        message.success(`已创建表 "${r.table_name}"，导入 ${r.imported_rows} 行`)
      } else {
        if (!tid) throw new Error('缺少目标表 ID')
        const r = await importApi.fetchAppend(wid, tid, payload)
        result = { appended_rows: r.appended_rows }
        message.success(`已追加 ${r.appended_rows} 行`)
      }
      onSuccess?.(result)
      // 成功后重置对话框状态
      setAnalyzeResult(null)
      onClose?.()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '导入失败'
      setErrorMsg(msg)
    } finally {
      setImporting(false)
    }
  }, [analyzeResult, form, mode, wid, tid, buildPayload, onClose, onSuccess, message])

  const columnsPreview = analyzeResult?.columns ?? []

  // 预览表格列定义
  const previewCols = [
    {
      title: '字段名',
      dataIndex: 'name',
      key: 'name',
      width: 160,
      render: (name: string) => <code style={{ fontSize: 12 }}>{name}</code>,
    },
    {
      title: '类型推断',
      dataIndex: 'field_type',
      key: 'field_type',
      width: 120,
      render: (t: string) => <Tag color={getFieldTypeColor(t)}>{getFieldTypeLabel(t)}</Tag>,
    },
    {
      title: '空值率',
      key: 'null_ratio',
      width: 100,
      render: (_: unknown, col: ApiAnalyzeColumn) => (
        <span style={{ color: col.null_ratio && col.null_ratio > 0.8 ? '#ef4444' : undefined }}>
          {((col.null_ratio ?? 0) * 100).toFixed(0)}%
        </span>
      ),
    },
    {
      title: '样本值',
      key: 'samples',
      render: (_: unknown, col: ApiAnalyzeColumn) => (
        <span style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>{renderSamples(col)}</span>
      ),
    },
  ]

  const content = (
    <>
      <Form form={form} layout="vertical" preserve={false} initialValues={{ method: 'GET', timeout: 15 }}>
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <Form.Item
            name="method"
            label="请求方法"
            rules={[{ required: true }]}
            style={{ marginBottom: 0, width: 120 }}
          >
            <Select options={HTTP_METHODS.map(m => ({ value: m, label: m }))} />
          </Form.Item>
          <Form.Item
            name="url"
            label="API URL"
            rules={[
              { required: true, message: '请输入 API URL' },
              { pattern: /^https?:\/\//, message: '仅支持 http:// 或 https:// 开头' },
            ]}
            style={{ marginBottom: 0, flex: 1 }}
          >
            <Input
              placeholder="例如：https://api.github.com/search/repositories?q=cn..."
              autoFocus
              data-testid="api-url-input"
            />
          </Form.Item>
          <Form.Item
            name="timeout"
            label="超时(s)"
            style={{ marginBottom: 0, width: 100 }}
          >
            <InputNumber min={3} max={60} style={{ width: '100%' }} />
          </Form.Item>
        </Space.Compact>

        <Collapse
          ghost
          size="small"
          items={[
            {
              key: 'advanced',
              label: '高级参数（可选）',
              children: (
                <>
                  <Form.Item
                    name="headers_text"
                    label="自定义请求头"
                    extra="每行一个，格式：Key: Value"
                  >
                    <Input.TextArea
                      rows={3}
                      placeholder="Authorization: Bearer xxx\nX-Api-Key: your-key"
                    />
                  </Form.Item>
                  <Form.Item
                    name="params_text"
                    label="URL 查询参数（JSON 对象）"
                    extra={'必须是合法 JSON 对象，如 {"page": 1, "limit": 50}'}
                  >
                    <Input.TextArea rows={2} placeholder='{"page": 1}' />
                  </Form.Item>
                  <Form.Item
                    name="body_text"
                    label="请求体（JSON 或纯文本）"
                    extra="POST/PUT/PATCH 时填写"
                  >
                    <Input.TextArea rows={3} placeholder='{"query": "hello"}' />
                  </Form.Item>
                  <Form.Item
                    name="data_path"
                    label="响应数据路径"
                    extra={
                      <>
                        数组定位路径，如 <code>data.items</code>；留空自动尝试
                        <Tag style={{ marginLeft: 4 }}>data</Tag>
                        <Tag>items</Tag>
                        <Tag>results</Tag>
                      </>
                    }
                  >
                    <Input placeholder="留空自动推断" />
                  </Form.Item>
                </>
              ),
            },
          ]}
        />

        {mode === 'create' && (
          <Form.Item
            name="table_name"
            label="新表名称"
            rules={[
              { required: true, message: '请输入新表名称' },
              { max: 64, message: '不超过 64 字符' },
            ]}
            style={{ marginTop: 12 }}
          >
            <Input placeholder="例如：GitHub 热门仓库 / 加密货币行情" maxLength={64} showCount />
          </Form.Item>
        )}
      </Form>

      {errorMsg && (
        <Alert
          type="error"
          showIcon
          message="请求失败"
          description={errorMsg}
          style={{ marginTop: 12 }}
          closable
          onClose={() => setErrorMsg(null)}
          data-testid="api-error-alert"
        />
      )}

      {analyzeResult && (
        <div style={{ marginTop: 12 }} data-testid="api-analyze-preview">
          <Descriptions
            size="small"
            column={3}
            bordered
            style={{ marginBottom: 8 }}
            labelStyle={{ width: 110, background: 'var(--cn-bg-subtle)', color: 'var(--cn-text-secondary)' }}
          >
            <Descriptions.Item label="命中记录数">
              <Tag color="blue">{analyzeResult.total_rows}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="识别字段数">
              <Tag color="green">{columnsPreview.length}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="顶层键">
              <span style={{ color: 'var(--cn-text-muted)', fontSize: 12 }}>
                {analyzeResult.sample_row_keys.slice(0, 6).join(', ')}
                {analyzeResult.sample_row_keys.length > 6 ? ` … (+${analyzeResult.sample_row_keys.length - 6})` : ''}
              </span>
            </Descriptions.Item>
          </Descriptions>
          <Table
            size="small"
            dataSource={columnsPreview}
            columns={previewCols}
            rowKey="name"
            pagination={false}
            scroll={{ y: 260 }}
            style={{ border: '1px solid var(--cn-border)', borderRadius: 6 }}
          />
        </div>
      )}

      {!analyzeResult && !errorMsg && (
        <div
          data-testid="api-placeholder"
          style={{
            marginTop: 16,
            padding: 16,
            background: 'var(--cn-bg-subtle)',
            borderRadius: 8,
            textAlign: 'center',
            border: '1px solid var(--cn-border)',
          }}
        >
          <ReloadOutlined style={{ fontSize: 28, color: 'var(--cn-text-muted)' }} />
          <div style={{ color: 'var(--cn-text-secondary)', marginTop: 8 }}>
            填写 API 参数后点击「分析」，预览返回的数据结构和推断字段类型
          </div>
        </div>
      )}
    </>
  )

  // embed 模式：直接返回内容；Modal 模式：用 Modal 包裹
  if (embed) {
    return (
      <div>
        {content}
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Space>
            <Button
              icon={<SearchOutlined />}
              loading={analyzing}
              onClick={handleAnalyze}
              disabled={importing}
              data-testid="api-analyze-btn"
            >
              分析
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={importing}
              onClick={handleImport}
              disabled={!analyzeResult}
              data-testid="api-import-btn"
            >
              {mode === 'create' ? '建表并导入' : '追加到当前表'}
            </Button>
          </Space>
        </div>
      </div>
    )
  }

  return (
    <Modal
      title={<Space><ApiOutlined />{dialogTitle}</Space>}
      open={open}
      onCancel={() => { onClose?.(); setAnalyzeResult(null); setErrorMsg(null) }}
      width={760}
      confirmLoading={importing}
      okButtonProps={{ style: { display: 'none' } }}
      destroyOnHidden
      footer={[
        <Button key="close" onClick={() => { onClose?.(); setAnalyzeResult(null); setErrorMsg(null) }}>关闭</Button>,
        <Button
          key="analyze"
          icon={<SearchOutlined />}
          loading={analyzing}
          onClick={handleAnalyze}
          disabled={importing}
          data-testid="api-analyze-btn"
        >
          分析
        </Button>,
        <Button
          key="import"
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={importing}
          onClick={handleImport}
          disabled={!analyzeResult}
          data-testid="api-import-btn"
        >
          {mode === 'create' ? '建表并导入' : '追加到当前表'}
        </Button>,
      ]}
    >
      {content}
    </Modal>
  )
}
