/**
 * PreviewPanel 组件测试 —— 报告模板实时预览（前端 nunjucks 渲染）.
 *
 * 覆盖：空模板 Empty / 变量与 table_name 渲染 / records 循环 / params /
 * 语法错误 Alert / 空输出占位 / loading Spin / 行数 meta。渲染有 300ms 防抖，断言用带超时的 findBy。
 */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import PreviewPanel from './PreviewPanel'
import { renderProviders } from '@/test/render-providers'

const FIND_OPTS = { timeout: 2000 } as const

describe('PreviewPanel 实时预览', () => {
  it('空模板显示 Empty 引导文案', () => {
    renderProviders(<PreviewPanel template="   " records={[]} />)

    expect(screen.getByText('实时预览')).toBeInTheDocument()
    expect(screen.getByText('在左侧编辑器输入模板后，这里会显示渲染结果')).toBeInTheDocument()
  })

  it('渲染变量与 table_name', async () => {
    renderProviders(<PreviewPanel template="Hello {{ table_name }}!" records={[]} tableName="客户表" />)

    expect(await screen.findByText('Hello 客户表!', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('records 循环渲染行数据', async () => {
    const rows = [{ name: '张三' }, { name: '李四' }]
    renderProviders(
      <PreviewPanel template="{% for r in records %}[{{ r.name }}]{% endfor %}" records={rows} />,
    )

    expect(await screen.findByText('[张三][李四]', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('params 参与渲染', async () => {
    renderProviders(
      <PreviewPanel template="{{ params.title }}" records={[]} params={{ title: '周报' }} />,
    )

    expect(await screen.findByText('周报', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('generated_at 生成日期参与渲染（与后端上下文一致）', async () => {
    renderProviders(
      <PreviewPanel template="生成于 {{ generated_at }}" records={[]} />,
    )

    expect(await screen.findByText(/生成于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/, {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('records_by_table 参与渲染', async () => {
    renderProviders(
      <PreviewPanel
        template="{{ records_by_table.订单 | length }} 单"
        records={[]}
        recordsByTable={{ 订单: [{ id: 1 }, { id: 2 }] }}
      />,
    )

    expect(await screen.findByText('2 单', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('模板语法错误显示渲染错误 Alert', async () => {
    renderProviders(<PreviewPanel template="{% if %}bad" records={[]} />)

    expect(await screen.findByText('渲染错误', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('渲染输出为空时显示 (空输出) 占位', async () => {
    renderProviders(<PreviewPanel template="{{ '' }}" records={[]} />)

    expect(await screen.findByText('(空输出)', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('loading 时渲染 Spin；有 tableName 时 meta 显示行数', async () => {
    renderProviders(
      <PreviewPanel template="" records={[{ a: 1 }, { a: 2 }]} tableName="客户表" loading />,
    )

    expect(document.querySelector('.ant-spin-spinning')).not.toBeNull()
  })

  it('非 loading 且有 tableName 时显示"表名 · 行数"meta', async () => {
    renderProviders(<PreviewPanel template="" records={[{ a: 1 }, { a: 2 }]} tableName="客户表" />)

    expect(await screen.findByText(/客户表 · 2 行/, {}, FIND_OPTS)).toBeInTheDocument()
  })
})
