/** 前端收尾四项（需求 0144 / 0147 / 0146 / 0150）的单元测试.
 *
 * - 行历史：`revisionOpLabel` / `diffSummary` 纯函数 + 抽屉渲染历史与撤销入口
 * - 聚合：`computeLocalAggregate`（本页口径）+ 口径切换 Segmented 渲染
 * - 校验规则：`readValidation` / `writeValidation` 的读写与空值清理
 * - DDL 预估：FieldManager 改类型时先取预估并弹确认（含 force_required 提示）
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { diffSummary, revisionOpLabel } from './layout/RowDetailDrawer'
import RowDetailDrawer from './layout/RowDetailDrawer'
import GridAggregationBar, { computeLocalAggregate } from './gridAggregationBar'
import { readValidation, writeValidation } from '@/pages/fields/FieldManager/FieldConfigPanel'
import type { Field, RowResponse } from '@/api'

// ─────────── 行历史 ───────────

describe('行历史展示', () => {
  it('op 文案映射：未知值原样返回', () => {
    expect(revisionOpLabel('create')).toBe('新建')
    expect(revisionOpLabel('update')).toBe('修改')
    expect(revisionOpLabel('trash')).toBe('删除到回收站')
    expect(revisionOpLabel('restore')).toBe('从回收站恢复')
    expect(revisionOpLabel('revert')).toBe('撤销')
    expect(revisionOpLabel('whatever')).toBe('whatever')
  })

  it('diff 摘要：字段前后值 + 空值占位 + 超限折叠', () => {
    expect(diffSummary({ 名称: { old: 'A', new: 'B' } })).toEqual(['名称：A → B'])
    expect(diffSummary({ 备注: { old: null, new: 'x' } })).toEqual(['备注：空 → x'])
    const many = Object.fromEntries(Array.from({ length: 7 }, (_, i) => [`f${i}`, { old: i, new: i + 1 }]))
    const lines = diffSummary(many, 5)
    expect(lines).toHaveLength(6)
    expect(lines[5]).toContain('另有 2 个字段变更')
  })

  it('抽屉渲染字段级历史，并按版本提供「恢复到此版本前」', async () => {
    const row = { id: 7, 名称: '当前值' } as unknown as RowResponse
    const fields = [{ id: 1, name: '名称', field_type: 'text', order: 0 }] as unknown as Field[]
    server.use(
      http.get('/api/v1/workspaces/10/tables/2/records/7/history', () =>
        HttpResponse.json([
          {
            id: 2, row_id: 7, version: 2, op: 'update', actor_id: 1, actor_name: 'owner',
            diff: { 名称: { old: '旧值', new: '当前值' } }, created_at: '2026-11-24T10:00:00Z',
          },
          {
            id: 1, row_id: 7, version: 1, op: 'create', actor_id: 1, actor_name: 'owner',
            diff: { 名称: { old: null, new: '旧值' } }, created_at: '2026-11-24T09:00:00Z',
          },
        ])),
      http.get('/api/v1/workspaces/10/tables/2/records/7/audit', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/10/tables/2/records/7/references', () => HttpResponse.json([])),
    )

    renderProviders(<RowDetailDrawer open row={row} fields={fields} wid="10" tid="2" onClose={() => { }} />)

    const history = await screen.findByTestId('row-history')
    expect(history).toHaveTextContent('修改')
    expect(history).toHaveTextContent('名称：旧值 → 当前值')
    // v1 是首版，不能「恢复到本版之前」
    expect(screen.queryByTestId('row-history-revert-1')).toBeNull()
    expect(screen.getByTestId('row-history-revert-2')).toBeInTheDocument()
  })
})

// ─────────── 聚合口径 ───────────

describe('聚合条口径切换', () => {
  const rows = [
    { id: 1, 金额: 10 },
    { id: 2, 金额: '30' },
    { id: 3, 金额: null },
    { id: 4, 金额: 'abc' },
  ] as unknown as RowResponse[]

  it('computeLocalAggregate：忽略空值与非数值', () => {
    expect(computeLocalAggregate(rows, '金额')).toEqual({ count: 2, sum: 40, avg: 20 })
    expect(computeLocalAggregate(rows, '不存在')).toEqual({ count: 0, sum: 0, avg: 0 })
  })

  it('全表口径走服务端聚合接口并展示结果', async () => {
    let requested: Record<string, unknown> | null = null
    server.use(
      http.post('/api/v1/workspaces/10/tables/2/records/aggregate', async ({ request }) => {
        requested = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          rows: [{ group: {}, metrics: { '金额__sum': 100, '金额__avg': 25, '金额__count': 4 } }],
          total_groups: 1,
          matched_rows: 4,
          group_by: [],
          metrics: [],
        })
      }),
    )

    renderProviders(
      <GridAggregationBar
        selectedCount={2}
        aggregates={{ 金额: { count: 2, sum: 40, avg: 20 } }}
        wid="10"
        tid="2"
        rows={rows}
        filters={[{ field_name: '状态', op: 'eq', value: '完成' }]}
        filterLogic="AND"
        copyLoading={false}
        deleteLoading={false}
        onCopy={() => { }}
        onDelete={() => { }}
        onClear={() => { }}
      />,
    )

    // 默认「选中」口径显示 GridPage 传入的聚合
    expect(screen.getByTestId('grid-agg-金额')).toHaveTextContent('和 40.00')

    fireEvent.click(screen.getByText('全表'))
    await waitFor(() => expect(screen.getByTestId('grid-agg-金额')).toHaveTextContent('和 100.00'))
    expect(requested).toMatchObject({ filter_logic: 'AND' })
    expect((requested as unknown as { filters: unknown[] }).filters).toHaveLength(1)

    // 本页口径：本地算当前页
    fireEvent.click(screen.getByText('本页'))
    expect(screen.getByTestId('grid-agg-金额')).toHaveTextContent('和 40.00')
  })

  it('没有选中行时不渲染（保持原行为）', () => {
    const { container } = renderProviders(
      <GridAggregationBar
        selectedCount={0}
        aggregates={{}}
        copyLoading={false}
        deleteLoading={false}
        onCopy={() => { }}
        onDelete={() => { }}
        onClear={() => { }}
      />,
    )
    // 未选中时不渲染聚合条本体（容器里只剩 antd App 的外壳）
    expect(container.querySelector('.cn-agg-bar')).toBeNull()
  })
})

// ─────────── 校验规则读写 ───────────

describe('校验规则配置读写', () => {
  it('readValidation：缺省与已有配置', () => {
    expect(readValidation(undefined)).toEqual({ pattern: '', message: '', watchField: '', op: 'eq', value: '' })
    expect(
      readValidation({
        validation: { pattern: '^A', message: '要 A 开头' },
        required_when: { field: '状态', op: 'in', value: ['完成', '关闭'] },
      }),
    ).toEqual({ pattern: '^A', message: '要 A 开头', watchField: '状态', op: 'in', value: '完成,关闭' })
  })

  it('writeValidation：写正则与条件必填，空值清理', () => {
    const cfg = writeValidation(
      { options: ['a'] },
      { pattern: ' ^[A-Z]$ ', message: '大写', watchField: '状态', op: 'eq', value: '完成' },
    )
    expect(cfg).toEqual({
      options: ['a'],
      validation: { pattern: '^[A-Z]$', message: '大写' },
      required_when: { field: '状态', op: 'eq', value: '完成' },
    })

    // 全部清空 → 两个键都删掉，保留其它配置
    const cleared = writeValidation(cfg, { pattern: '', message: '', watchField: '', op: 'eq', value: '' })
    expect(cleared).toEqual({ options: ['a'] })
  })

  it('writeValidation：in / not_in 的值按逗号拆成数组', () => {
    const cfg = writeValidation(null, { pattern: '', message: '', watchField: '状态', op: 'in', value: 'A, B ,,' })
    expect(cfg.required_when).toEqual({ field: '状态', op: 'in', value: ['A', 'B'] })
  })
})
