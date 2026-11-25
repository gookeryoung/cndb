/** 复合数据源配置弹窗（ADR 0159 P2）：多链接汇总（union）/ 跨工作区关联（join）.
 *
 * 页面只做编排：这里负责把「多个链接的字段」映射成一处输出字段清单；
 * 保存与执行仍由后端校验（逐输入同权 / 类型同族 / 关联键可见，L1–L4）。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Input, Modal, Select, Space, Table, Tag, Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DeleteOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useQueries, useQuery } from '@tanstack/react-query'
import { linksApi, tableApi } from '@/api'
import type { AnalyticsDatasources, AnalyticsSource, AnalyticsUnionColumn } from '@/api/analytics'
import { fieldFamily, joinOutputFields, unionAutoColumns } from './analyticsModel'

const { Text } = Typography

/** union 输出列允许声明的类型族（与后端 union_source._family 对称） */
const UNION_TYPES = [
  { value: 'text', label: '文本' },
  { value: 'number', label: '数值' },
  { value: 'date', label: '日期' },
  { value: 'boolean', label: '布尔' },
]

interface Props {
  open: boolean
  mode: 'union' | 'join'
  /** 当前生效的复合数据源（用于回填编辑态）；单源 / 空则为 null */
  source: AnalyticsSource | null
  wid: string
  datasources?: AnalyticsDatasources
  tables: Array<{ id: number | string; name: string }>
  onCancel: () => void
  onApply: (source: AnalyticsSource) => void
}

interface LinkItem {
  id: number
  name: string
  source_workspace_name?: string | null
  readable: boolean
}

interface JoinKeyDraft {
  left_field?: string
  right_field?: string
}

export function CompositeSourceModal({
  open, mode, source, wid, datasources, tables, onCancel, onApply,
}: Props) {
  const [error, setError] = useState<string | null>(null)

  // ── union 编辑态 ──
  const [unionInputs, setUnionInputs] = useState<number[]>([])
  const [unionColumns, setUnionColumns] = useState<AnalyticsUnionColumn[]>([])

  // ── join 编辑态 ──
  const [joinType, setJoinType] = useState<'left' | 'inner'>('left')
  const [leftKind, setLeftKind] = useState<'table' | 'link'>('table')
  const [leftTableId, setLeftTableId] = useState<number | null>(null)
  const [leftLinkId, setLeftLinkId] = useState<number | null>(null)
  const [rightLinkId, setRightLinkId] = useState<number | null>(null)
  const [joinKeys, setJoinKeys] = useState<JoinKeyDraft[]>([])

  const links = useMemo<LinkItem[]>(
    () => (datasources?.links ?? []).map(link => ({
      id: Number(link.link_id ?? link.id),
      name: link.name,
      source_workspace_name: link.source_workspace_name,
      readable: link.readable,
    })),
    [datasources],
  )

  const linkById = useMemo(() => new Map(links.map(link => [link.id, link])), [links])

  /** 需要的链接字段：union 输入 + join 的两侧链接（同一 queryKey 与页面共享缓存） */
  const neededLinkIds = useMemo(() => {
    const ids = new Set<number>(unionInputs)
    if (mode === 'join') {
      if (leftKind === 'link' && leftLinkId != null) ids.add(leftLinkId)
      if (rightLinkId != null) ids.add(rightLinkId)
    }
    return Array.from(ids)
  }, [unionInputs, mode, leftKind, leftLinkId, rightLinkId])

  const fieldQueries = useQueries({
    queries: neededLinkIds.map(id => ({
      queryKey: ['analytics-link-fields', wid, id],
      queryFn: () => linksApi.fields(wid, id),
      enabled: open && !!wid,
      retry: false,
    })),
  })

  const fieldsByLink = useMemo<Record<string, Array<{ name: string; field_type: string }>>>(() => {
    const result: Record<string, Array<{ name: string; field_type: string }>> = {}
    neededLinkIds.forEach((id, index) => {
      const payload = fieldQueries[index]?.data
      result[String(id)] = (payload?.fields ?? []).map(field => ({
        name: field.name,
        field_type: field.field_type,
      }))
    })
    return result
  }, [neededLinkIds, fieldQueries])

  const linkFieldsKey = useMemo(
    () => neededLinkIds
      .map(id => `${id}:${(fieldsByLink[String(id)] ?? []).map(field => `${field.name}/${field.field_type}`).join(',')}`)
      .join('|'),
    [neededLinkIds, fieldsByLink],
  )

  const leftTableQuery = useQuery({
    queryKey: ['table', wid, leftTableId],
    queryFn: () => tableApi.get(wid, leftTableId!),
    enabled: open && mode === 'join' && leftKind === 'table' && !!leftTableId,
  })

  const leftFields = useMemo<Array<{ name: string; field_type: string }>>(() => {
    if (leftKind === 'link') return leftLinkId != null ? fieldsByLink[String(leftLinkId)] ?? [] : []
    return (leftTableQuery.data?.fields ?? []).map(field => ({
      name: field.name,
      field_type: String(field.field_type),
    }))
  }, [leftKind, leftLinkId, fieldsByLink, leftTableQuery.data])

  const rightFields = useMemo(
    () => (rightLinkId != null ? fieldsByLink[String(rightLinkId)] ?? [] : []),
    [rightLinkId, fieldsByLink],
  )

  const joinOutputPreview = useMemo(
    () => joinOutputFields(
      leftFields.map(field => field.name),
      rightFields.map(field => field.name),
      joinKeys.map(key => key.right_field ?? '').filter(Boolean),
    ),
    [leftFields, rightFields, joinKeys],
  )

  // 打开时按当前 source 回填（取消不落任何状态）
  useEffect(() => {
    if (!open) return
    setError(null)
    if (mode === 'union') {
      const current = source?.type === 'union' ? source : null
      setUnionInputs((current?.inputs ?? []).map(item => Number(item.link_id)))
      setUnionColumns((current?.columns ?? []).map(column => ({
        name: column.name,
        type: column.type,
        map: { ...column.map },
      })))
      return
    }
    const current = source?.type === 'join' ? source : null
    setJoinType(current?.join_type === 'inner' ? 'inner' : 'left')
    const left = current?.left ?? null
    setLeftKind(left?.link_id != null ? 'link' : 'table')
    setLeftTableId(left?.table_id != null ? Number(left.table_id) : null)
    setLeftLinkId(left?.link_id != null ? Number(left.link_id) : null)
    setRightLinkId(current?.right?.link_id != null ? Number(current.right.link_id) : null)
    setJoinKeys((current?.on ?? []).map(key => ({
      left_field: key.left_field,
      right_field: key.right_field,
    })))
  }, [open, mode, source])

  // union：输入字段加载完成后自动补一版同名列（用户仍可增删改）
  useEffect(() => {
    if (!open || mode !== 'union' || unionInputs.length < 2) return
    setUnionColumns(prev => (prev.length ? prev : unionAutoColumns(unionInputs, fieldsByLink)))
    // fieldsByLink 的内容由 linkFieldsKey 表示，避免对象身份变化触发无意义 setState
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, unionInputs, linkFieldsKey])

  const changeUnionInputs = (ids: number[]) => {
    setUnionInputs(ids)
    const allowed = new Set(ids.map(String))
    setUnionColumns(prev => {
      const pruned = prev
        .map(column => ({
          ...column,
          map: Object.fromEntries(Object.entries(column.map).filter(([key]) => allowed.has(key))),
        }))
        .filter(column => Object.keys(column.map).length > 0)
      if (pruned.length) return pruned
      return unionAutoColumns(ids, fieldsByLink)
    })
  }

  const updateUnionColumn = (index: number, patch: Partial<AnalyticsUnionColumn>) => {
    setUnionColumns(prev => prev.map((column, i) => (i === index ? { ...column, ...patch } : column)))
  }

  const updateUnionMap = (index: number, linkId: number, field: string | undefined) => {
    setUnionColumns(prev => prev.map((column, i) => {
      if (i !== index) return column
      const nextMap = { ...column.map }
      if (field) nextMap[String(linkId)] = field
      else delete nextMap[String(linkId)]
      return { ...column, map: nextMap }
    }))
  }

  const addUnionColumn = () => {
    const used = new Set(unionColumns.map(column => column.name))
    let index = unionColumns.length + 1
    let name = `列${index}`
    while (used.has(name)) {
      index += 1
      name = `列${index}`
    }
    setUnionColumns(prev => [...prev, { name, type: 'text', map: {} }])
  }

  const unionTableColumns: TableColumnsType<AnalyticsUnionColumn> = [
    {
      title: '输出列名',
      key: 'name',
      width: 150,
      render: (_, _row, index) => (
        <Input
          size="small"
          data-testid={`analytics-union-column-name-${index}`}
          value={unionColumns[index]?.name ?? ''}
          onChange={event => updateUnionColumn(index, { name: event.target.value })}
        />
      ),
    },
    {
      title: '类型',
      key: 'type',
      width: 100,
      render: (_, _row, index) => (
        <Select
          size="small"
          data-testid={`analytics-union-column-type-${index}`}
          value={unionColumns[index]?.type ?? 'text'}
          options={UNION_TYPES}
          onChange={value => updateUnionColumn(index, { type: value })}
        />
      ),
    },
    ...unionInputs.map(linkId => ({
      title: linkById.get(linkId)?.name ?? `链接 #${linkId}`,
      key: `map-${linkId}`,
      width: 160,
      render: (_: unknown, _row: AnalyticsUnionColumn, index: number) => {
        const options = (fieldsByLink[String(linkId)] ?? []).map(field => ({
          value: field.name,
          label: field.name,
        }))
        return (
          <Select
            size="small"
            allowClear
            style={{ width: '100%' }}
            data-testid={`analytics-union-column-map-${index}-${linkId}`}
            placeholder="不映射"
            value={unionColumns[index]?.map?.[String(linkId)]}
            options={options}
            onChange={value => updateUnionMap(index, linkId, value)}
          />
        )
      },
    })),
    {
      title: '',
      key: 'actions',
      width: 48,
      render: (_, _row, index) => (
        <Button
          size="small"
          type="text"
          danger
          aria-label="删除输出列"
          data-testid={`analytics-union-remove-column-${index}`}
          icon={<DeleteOutlined />}
          onClick={() => setUnionColumns(prev => prev.filter((_, i) => i !== index))}
        />
      ),
    },
  ]

  const unionInputOptions = useMemo(() => {
    const base = links.map(link => ({
      value: link.id,
      label: `${link.name} · ${link.source_workspace_name ?? '外部工作区'}`,
      disabled: !link.readable,
    }))
    const missing = unionInputs
      .filter(id => !linkById.has(id))
      .map(id => ({ value: id, label: `链接 #${id}（已失效）`, disabled: true }))
    return [...base, ...missing]
  }, [links, unionInputs, linkById])

  const leftOptions = useMemo(() => {
    if (leftKind === 'table') {
      const base = tables.map(table => ({ value: Number(table.id), label: table.name }))
      const missing = leftTableId != null && !tables.some(table => Number(table.id) === leftTableId)
        ? [{ value: leftTableId, label: `表 #${leftTableId}（已删除）`, disabled: true }]
        : []
      return [...base, ...missing]
    }
    return unionInputOptions
  }, [leftKind, tables, leftTableId, unionInputOptions])

  const rightOptions = useMemo(() => {
    const base = links.map(link => ({
      value: link.id,
      label: `${link.name} · ${link.source_workspace_name ?? '外部工作区'}`,
      disabled: !link.readable,
    }))
    const missing = rightLinkId != null && !linkById.has(rightLinkId)
      ? [{ value: rightLinkId, label: `链接 #${rightLinkId}（已失效）`, disabled: true }]
      : []
    return [...base, ...missing]
  }, [links, rightLinkId, linkById])

  const updateJoinKey = (index: number, patch: JoinKeyDraft) => {
    setJoinKeys(prev => prev.map((key, i) => (i === index ? { ...key, ...patch } : key)))
  }

  function submit() {
    if (mode === 'union') {
      if (unionInputs.length < 2 || unionInputs.length > 5) {
        setError('多链接汇总需要选择 2–5 个链接')
        return
      }
      if (unionColumns.length === 0) {
        setError('至少配置一个输出列')
        return
      }
      const names = unionColumns.map(column => column.name.trim())
      if (names.some(name => !name)) {
        setError('输出列名不能为空')
        return
      }
      if (new Set(names).size !== names.length) {
        setError('输出列名不能重复')
        return
      }
      if (unionColumns.some(column => Object.values(column.map).filter(Boolean).length === 0)) {
        setError('每个输出列至少要映射一个输入字段')
        return
      }
      onApply({
        type: 'union',
        inputs: unionInputs.map(id => ({
          link_id: id,
          alias: linkById.get(id)?.name ?? null,
        })),
        columns: unionColumns.map((column, index) => ({
          name: names[index],
          type: column.type || 'text',
          map: Object.fromEntries(
            Object.entries(column.map).filter(([key, value]) => !!value && unionInputs.includes(Number(key))),
          ),
        })),
      })
      return
    }

    if (leftKind === 'table' ? leftTableId == null : leftLinkId == null) {
      setError('请选择关联的左侧数据源')
      return
    }
    if (rightLinkId == null) {
      setError('关联的右侧必须是工作区链接')
      return
    }
    const keys = joinKeys.filter(key => key.left_field && key.right_field)
    if (keys.length === 0) {
      setError('至少配置一个关联键')
      return
    }
    const leftNames = new Set(leftFields.map(field => field.name))
    const rightNames = new Set(rightFields.map(field => field.name))
    for (const key of keys) {
      if (!leftNames.has(key.left_field!)) {
        setError(`左表关联键不可用（不存在或被隐藏）: ${key.left_field}`)
        return
      }
      if (!rightNames.has(key.right_field!)) {
        setError(`右表关联键不可用（不存在或被隐藏）: ${key.right_field}`)
        return
      }
    }
    onApply({
      type: 'join',
      join_type: joinType,
      left: leftKind === 'table' ? { table_id: leftTableId } : { link_id: leftLinkId },
      right: { link_id: rightLinkId },
      on: keys.map(key => ({ left_field: key.left_field!, right_field: key.right_field! })),
    })
  }

  const joinKeyColumns: TableColumnsType<JoinKeyDraft> = [
    {
      title: '左侧字段（本表 / 链接）',
      key: 'left',
      render: (_, _row, index) => (
        <Select
          size="small"
          style={{ width: '100%' }}
          data-testid={`analytics-join-key-left-${index}`}
          placeholder="选择左侧字段"
          value={joinKeys[index]?.left_field}
          options={leftFields.map(field => ({
            value: field.name,
            label: `${field.name}（${fieldFamily(field.field_type)}）`,
          }))}
          onChange={value => updateJoinKey(index, { left_field: value })}
        />
      ),
    },
    {
      title: '右侧字段（链接）',
      key: 'right',
      render: (_, _row, index) => (
        <Select
          size="small"
          style={{ width: '100%' }}
          data-testid={`analytics-join-key-right-${index}`}
          placeholder="选择右侧字段"
          value={joinKeys[index]?.right_field}
          options={rightFields.map(field => ({
            value: field.name,
            label: `${field.name}（${fieldFamily(field.field_type)}）`,
          }))}
          onChange={value => updateJoinKey(index, { right_field: value })}
        />
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 48,
      render: (_, _row, index) => (
        <Button
          size="small"
          type="text"
          danger
          aria-label="删除关联键"
          data-testid={`analytics-join-remove-key-${index}`}
          icon={<DeleteOutlined />}
          onClick={() => setJoinKeys(prev => prev.filter((_, i) => i !== index))}
        />
      ),
    },
  ]

  return (
    <Modal
      open={open}
      title={mode === 'union' ? '多链接汇总（合并行）' : '跨工作区关联（left / inner）'}
      width={mode === 'union' ? 860 : 720}
      okText="应用数据源"
      cancelText="取消"
      onCancel={onCancel}
      onOk={submit}
      destroyOnHidden
      data-testid="analytics-composite-modal"
    >
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
          {mode === 'union'
            ? '把 2–5 个工作区链接按显式列映射纵向拼接（union all，不去重）；任一链接不可读则整体无法运行。'
            : '仅支持 left / inner，且由左侧驱动：右侧未匹配的行不会出现在结果里；关联键必须两侧可见。'}
        </Text>

        {error && <Alert type="error" showIcon data-testid="analytics-composite-error" title={error} />}

        {mode === 'union' ? (
          <>
            <div className="cn-an-field">
              <span className="cn-an-label">输入链接（2–5 个）</span>
              <Select
                mode="multiple"
                data-testid="analytics-union-inputs"
                placeholder="选择需要汇总的链接"
                value={unionInputs}
                options={unionInputOptions}
                onChange={ids => changeUnionInputs(ids.map(Number))}
              />
              <div data-testid="analytics-union-input-status">
                {unionInputs.map(id => {
                  const link = linkById.get(id)
                  return (
                    <span key={id} style={{ marginRight: 8 }}>
                      <Tag color={!link ? 'red' : link.readable ? 'green' : 'orange'}>
                        {link?.name ?? `链接 #${id}`} · {!link ? '已失效' : link.readable ? '可读' : '无读取权限'}
                      </Tag>
                    </span>
                  )
                })}
              </div>
            </div>

            <div>
              <Space wrap>
                <Text strong>输出列映射</Text>
                <Button
                  size="small"
                  icon={<ThunderboltOutlined />}
                  data-testid="analytics-union-autofill"
                  onClick={() => setUnionColumns(unionAutoColumns(unionInputs, fieldsByLink))}
                >
                  按同名字段生成
                </Button>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  data-testid="analytics-union-add-column"
                  onClick={addUnionColumn}
                >
                  添加输出列
                </Button>
              </Space>
              <Table<AnalyticsUnionColumn>
                size="small"
                style={{ marginTop: 8 }}
                rowKey={(_, index) => String(index)}
                dataSource={unionColumns}
                columns={unionTableColumns}
                pagination={false}
                scroll={{ x: 'max-content' }}
                locale={{ emptyText: '选择链接后点「按同名字段生成」，或手动添加输出列' }}
              />
            </div>
          </>
        ) : (
          <>
            <div className="cn-an-grid">
              <div className="cn-an-field">
                <span className="cn-an-label">连接方式</span>
                <Select
                  data-testid="analytics-join-type"
                  value={joinType}
                  options={[
                    { value: 'left', label: 'left（保留左侧全部行）' },
                    { value: 'inner', label: 'inner（仅保留匹配行）' },
                  ]}
                  onChange={value => setJoinType(value as 'left' | 'inner')}
                />
              </div>
              <div className="cn-an-field">
                <span className="cn-an-label">左侧类型</span>
                <Select
                  data-testid="analytics-join-left-kind"
                  value={leftKind}
                  options={[
                    { value: 'table', label: '本工作区表' },
                    { value: 'link', label: '工作区链接' },
                  ]}
                  onChange={value => {
                    setLeftKind(value as 'table' | 'link')
                    setJoinKeys([])
                  }}
                />
              </div>
              <div className="cn-an-field">
                <span className="cn-an-label">左侧数据源</span>
                <Select
                  showSearch
                  optionFilterProp="label"
                  data-testid="analytics-join-left"
                  placeholder={leftKind === 'table' ? '选择本工作区表' : '选择链接'}
                  value={(leftKind === 'table' ? leftTableId : leftLinkId) ?? undefined}
                  options={leftOptions}
                  onChange={value => {
                    if (leftKind === 'table') setLeftTableId(Number(value))
                    else setLeftLinkId(Number(value))
                    setJoinKeys([])
                  }}
                />
              </div>
              <div className="cn-an-field">
                <span className="cn-an-label">右侧数据源（必须是链接）</span>
                <Select
                  showSearch
                  optionFilterProp="label"
                  data-testid="analytics-join-right"
                  placeholder="选择链接"
                  value={rightLinkId ?? undefined}
                  options={rightOptions}
                  onChange={value => {
                    setRightLinkId(Number(value))
                    setJoinKeys([])
                  }}
                />
              </div>
            </div>

            <div>
              <Space wrap>
                <Text strong>关联键</Text>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  data-testid="analytics-join-add-key"
                  disabled={leftFields.length === 0 || rightFields.length === 0}
                  onClick={() => setJoinKeys(prev => [...prev, {}])}
                >
                  添加关联键
                </Button>
              </Space>
              <Table<JoinKeyDraft>
                size="small"
                style={{ marginTop: 8 }}
                rowKey={(_, index) => String(index)}
                dataSource={joinKeys}
                columns={joinKeyColumns}
                pagination={false}
                locale={{ emptyText: '选择左右数据源后添加关联键' }}
              />
            </div>

            <div data-testid="analytics-join-output-preview">
              <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
                输出字段（{joinOutputPreview.length}）：{joinOutputPreview.join('、') || '—'}
              </Text>
            </div>
          </>
        )}
      </Space>
    </Modal>
  )
}

export default CompositeSourceModal
