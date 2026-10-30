/** AI 字段批量填充抽屉 —— 「建议 → 预览 → 确认」的表格侧承载层（ADR 0020 P2 / D14）.
 *
 * 边界（硬约束）：
 * - 只调用 `POST /tables/{tid}/ai/actions/fill_field` **生成建议**，该端点不写库；
 * - 确认应用时**逐行**调用既有记录更新接口（`useUpdateRowOptimistic` → `recordApi.update`），
 *   不新增批量写 / 不绕过双轨制：无直编资格时后端返回 202 修改申请，提示仍沿用既有文案；
 * - 输入行固定取当前页可读行的前 20 行（后端还会按行级权限再过滤一次）。
 *
 * 组件由 GridPage 通过 `lazy(() => import(...))` 挂载，不进入表页首屏 chunk。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App as AntApp, Button, Drawer, Empty, Input, Skeleton, Space, Table, Tag, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined, RobotOutlined } from '@ant-design/icons'

import { useUpdateRowOptimistic } from '@/api/hooks'
import { isChangeRequestResponse } from '@/api'
import { tableApi, type TableAiFieldFillValue, type TableAiFillFieldPayload } from '@/api/tables'
import type { Field, RowResponse } from '@/api'
import { useLlmAction } from '@/hooks/useLlmAction'
import { SPACE, TEXT } from '@/theme/tokens'

const { Text } = Typography

/** 单次请求的输入行上限（与后端 `MAX_FILL_ROWS` 对齐） */
export const MAX_AI_FILL_ROWS = 20

export interface AiFillFieldDrawerProps {
  open: boolean
  wid: string
  tid: string
  /** 目标字段（入口来自该列列头；隐藏字段不提供服务） */
  field: Field
  /** 当前页可读行（内部只取前 20 行发起请求） */
  rows: RowResponse[]
  /** 当前页第一行的全局序号基准（展示「第 N 行」用） */
  rowIndexBase?: number
  onClose: () => void
  /** 应用完成后回调（刷新列表等；mutation 自身已 invalidate） */
  onApplied?: () => void
}

/** 建议值展示文案：null 表示模型无法确定，不参与应用 */
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') {
    try { return JSON.stringify(value) } catch { return String(value) }
  }
  return String(value)
}

/** 建议值是否为可应用值（null / 空串表示模型未给出，不清空原值） */
function isApplicable(value: TableAiFieldFillValue['value']): boolean {
  return value !== null && value !== undefined && value !== ''
}

interface SuggestionRow {
  row_id: number
  value: TableAiFieldFillValue['value']
  /** 行在结果中的顺序（用于取当前值与序号） */
  current: unknown
  pageNo: number
}

export default function AiFillFieldDrawer({
  open,
  wid,
  tid,
  field,
  rows,
  rowIndexBase = 0,
  onClose,
  onApplied,
}: AiFillFieldDrawerProps) {
  const { message } = AntApp.useApp()
  const updateRow = useUpdateRowOptimistic(wid, tid)
  const [instruction, setInstruction] = useState('')
  const [applying, setApplying] = useState(false)
  /** 已发起过的请求标识：open / 字段 / 行集合变化时才自动重发，避免重复渲染重复调用 */
  const lastRequestRef = useRef<string | null>(null)

  // 请求行固定取当前页前 20 行；row_id 统一转 number（后端 row_ids 为 int 数组）
  const targetRows = useMemo(
    () => rows.slice(0, MAX_AI_FILL_ROWS).map((row, index) => ({
      row,
      rowId: Number(row.id),
      pageNo: rowIndexBase + index + 1,
    })).filter(item => Number.isFinite(item.rowId)),
    [rows, rowIndexBase],
  )
  const rowIdsKey = targetRows.map(item => item.rowId).join(',')
  const requestKey = `${field.name}|${rowIdsKey}`
  const rowIds = useMemo(() => targetRows.map(item => item.rowId), [targetRows])

  const fillAi = useLlmAction(
    (payload: TableAiFillFieldPayload) => tableApi.aiFillField(wid, tid, payload),
    { fallbackError: 'AI 填充失败，请稍后重试' },
  )
  const run = fillAi.run
  const reset = fillAi.reset

  /** 打开抽屉即发起一次建议生成（与文档 AI 入口一致：点击即请求、抽屉展示 loading） */
  useEffect(() => {
    if (!open) {
      lastRequestRef.current = null
      return
    }
    if (lastRequestRef.current === requestKey) return
    if (rowIds.length === 0) {
      lastRequestRef.current = requestKey
      return
    }
    lastRequestRef.current = requestKey
    void run({ field_name: field.name, row_ids: rowIds })
  }, [open, requestKey, field.name, rowIds, run])

  const close = useCallback(() => {
    reset()
    setInstruction('')
    setApplying(false)
    onClose()
  }, [onClose, reset])

  const regenerate = useCallback(() => {
    if (rowIds.length === 0) return
    const text = instruction.trim()
    void run({ field_name: field.name, row_ids: rowIds, ...(text ? { instruction: text } : {}) })
  }, [instruction, rowIds, field.name, run])

  const fillData = fillAi.data
  const suggestions: SuggestionRow[] = useMemo(() => {
    const values = fillData?.result.values ?? []
    const byRowId = new Map(targetRows.map(item => [item.rowId, item]))
    return values
      .map(value => {
        const target = byRowId.get(value.row_id)
        return {
          ...value,
          current: target ? target.row[field.name] : undefined,
          pageNo: target?.pageNo ?? 0,
        }
      })
  }, [fillData, targetRows, field.name])
  const skippedRowIds = fillData?.skipped_row_ids ?? []
  const applicableCount = suggestions.filter(item => isApplicable(item.value)).length

  /** 确认应用：逐行调用既有更新接口（复用乐观更新 mutation + 202 修改申请语义） */
  const handleApply = useCallback(async () => {
    const applicable = suggestions.filter(item => isApplicable(item.value))
    if (applicable.length === 0 || applying) return
    setApplying(true)
    let success = 0
    let changeRequests = 0
    let failed = 0
    const changeRequestIds: number[] = []
    for (const item of applicable) {
      try {
        const res = await updateRow.mutateAsync({
          rowId: item.row_id,
          fieldName: field.name,
          value: item.value,
        })
        if (isChangeRequestResponse(res)) {
          changeRequests += 1
          if (res.change_request?.id != null) changeRequestIds.push(Number(res.change_request.id))
        } else {
          success += 1
        }
      } catch {
        // 单行失败不阻断后续行；hook 已回滚乐观写入并提示错误
        failed += 1
      }
    }
    setApplying(false)

    const parts: string[] = []
    if (success > 0) parts.push(`成功 ${success} 行`)
    if (changeRequests > 0) {
      const idText = changeRequestIds.slice(0, 3).map(id => `#${id}`).join('、')
      parts.push(`已提交修改申请 ${changeRequests} 行${idText ? `（${idText}）` : ''}`)
    }
    if (failed > 0) parts.push(`失败 ${failed} 行`)
    const summary = `AI 填充应用完成：${parts.join('；')}`
    const finalSummary = changeRequests > 0 ? `${summary}，审批通过后生效` : summary
    if (failed > 0) message.warning(finalSummary)
    else message.success(finalSummary)

    onApplied?.()
    close()
  }, [suggestions, applying, updateRow, field.name, message, onApplied, close])

  const columns: ColumnsType<SuggestionRow> = [
    {
      key: 'row',
      title: '行',
      width: 130,
      render: (_v, record) => (
        <span data-testid={`ai-fill-row-${record.row_id}`}>
          <Text type="secondary">第 {record.pageNo || '—'} 行</Text>
          <Text type="secondary" style={{ fontSize: TEXT['2xs'], marginLeft: SPACE.xs }}>#{record.row_id}</Text>
        </span>
      ),
    },
    {
      key: 'current',
      title: '当前值',
      ellipsis: true,
      render: (_v, record) => (
        <Text type="secondary">{displayValue(record.current)}</Text>
      ),
    },
    {
      key: 'suggestion',
      title: 'AI 建议值',
      ellipsis: true,
      render: (_v, record) => (
        isApplicable(record.value)
          ? <Text strong data-testid={`ai-fill-value-${record.row_id}`}>{displayValue(record.value)}</Text>
          : <Text type="secondary" data-testid={`ai-fill-value-${record.row_id}`}>未给出建议（不会清空原值）</Text>
      ),
    },
  ]

  const meta = fillData
    ? [
        fillData.model ? `模型 ${fillData.model}` : '',
        typeof fillData.usage?.total_tokens === 'number' ? `本次 ${fillData.usage.total_tokens} tokens` : '',
        `留痕 #${fillData.run_id}`,
        `本次分析 ${fillData.row_count} 行`,
      ].filter(Boolean).join(' · ')
    : undefined

  const headerHint = targetRows.length > 0
    ? `将基于当前页可读的 ${targetRows.length} 行生成「${field.name}」建议值${rows.length > MAX_AI_FILL_ROWS ? `（最多 ${MAX_AI_FILL_ROWS} 行）` : ''}`
    : '当前页没有可读取的行'

  return (
    <Drawer
      open={open}
      size={760}
      onClose={close}
      destroyOnHidden
      title={<Space size={SPACE.sm}><RobotOutlined /><span>AI 填充本列：{field.name}</span></Space>}
      footer={(
        <Space style={{ width: '100%', justifyContent: 'flex-end' }} wrap>
          <Button data-testid="ai-fill-cancel" onClick={close}>取消</Button>
          <Button
            data-testid="ai-fill-regenerate"
            icon={<ReloadOutlined />}
            loading={fillAi.loading}
            disabled={fillAi.loading || applying || rowIds.length === 0}
            onClick={regenerate}
          >
            重新生成
          </Button>
          <Button
            type="primary"
            data-testid="ai-fill-apply"
            loading={applying}
            disabled={fillAi.loading || applying || applicableCount === 0}
            onClick={() => { void handleApply() }}
          >
            应用到 {applicableCount} 行
          </Button>
        </Space>
      )}
    >
      <div data-testid="ai-fill-field-drawer" style={{ display: 'flex', flexDirection: 'column', gap: SPACE.lg }}>
        <Text type="secondary" style={{ fontSize: TEXT.xs }} data-testid="ai-fill-hint">
          {headerHint}。结果只是建议，确认后逐行调用原有记录更新接口（无直编资格时自动提交修改申请），不会批量写库。
        </Text>

        {meta && (
          <Text type="secondary" style={{ fontSize: TEXT.xs }} data-testid="ai-fill-meta">{meta}</Text>
        )}

        {fillAi.loading && (
          <div data-testid="ai-fill-loading">
            <Skeleton active title={false} paragraph={{ rows: 5 }} />
          </div>
        )}

        {fillAi.error && (
          <div data-testid="ai-fill-error">
            <Alert
              type="error"
              showIcon
              title={fillAi.error}
              description="本次调用未改动任何行；可点击「重新生成」重试，或缩短输入行后重试。"
            />
          </div>
        )}

        {!fillAi.loading && !fillAi.error && suggestions.length > 0 && (
          <Table<SuggestionRow>
            size="small"
            rowKey="row_id"
            pagination={false}
            scroll={{ y: 320 }}
            dataSource={suggestions}
            columns={columns}
          />
        )}

        {!fillAi.loading && !fillAi.error && suggestions.length === 0 && (
          <Empty
            data-testid="ai-fill-empty"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={rowIds.length === 0 ? '当前页没有可读取的行' : '模型未返回任何建议，可换个说明后重新生成'}
          />
        )}

        {skippedRowIds.length > 0 && (
          <Alert
            data-testid="ai-fill-skipped"
            type="warning"
            showIcon
            title={`有 ${skippedRowIds.length} 行不在你的可读范围或已被删除，已跳过：${skippedRowIds.join('、')}`}
          />
        )}

        {!fillAi.loading && !fillAi.error && (
          <div>
            <Text strong style={{ display: 'block', fontSize: TEXT.sm, marginBottom: SPACE.xs }}>
              补充要求（可选）
            </Text>
            <Input.TextArea
              data-testid="ai-fill-instruction"
              value={instruction}
              onChange={event => setInstruction(event.target.value)}
              placeholder="例如：根据「标题」和「正文」生成不超过 40 字的中文摘要"
              autoSize={{ minRows: 2, maxRows: 4 }}
              maxLength={500}
              showCount
            />
          </div>
        )}

        <Text type="secondary" style={{ fontSize: TEXT.xs }}>
          生成结果中 value 为 null 的行视为「无法确定」，应用时会跳过，不会清空单元格。
        </Text>
        {applicableCount < suggestions.length && suggestions.length > 0 && (
          <Tag color="gold" data-testid="ai-fill-skipped-count">
            {suggestions.length - applicableCount} 行无建议，应用时跳过
          </Tag>
        )}
        {fillAi.data && (
          <Tooltip title="AI 只生成建议，不会直接写库">
            <Text type="secondary" style={{ fontSize: TEXT['2xs'] }}>
              应用使用既有记录更新接口；如当前账号无直编资格，将按双轨制转为修改申请。
            </Text>
          </Tooltip>
        )}
      </div>
    </Drawer>
  )
}
