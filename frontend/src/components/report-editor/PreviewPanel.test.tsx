/**
 * PreviewPanel 测试：nunjucks 实时预览渲染、throwOnUndefined 对齐后端
 * StrictUndefined、records_by_table / params 上下文注入.
 */

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import PreviewPanel from './PreviewPanel'
import { renderProviders } from '@/test/render-providers'

describe('PreviewPanel', () => {
  it('基础渲染：records 循环与 length 过滤器', async () => {
    renderProviders(
      <PreviewPanel
        template="共 {{ records | length }} 行\n{% for r in records %}- {{ r.name }}\\n{% endfor %}"
        records={[{ name: '张三' }, { name: '李四' }]}
        tableName="员工表"
      />,
    )

    expect(await screen.findByText(/共 2 行/)).toBeInTheDocument()
    expect(await screen.findByText(/张三/)).toBeInTheDocument()
  })

  it('元信息行显示预览行数上限提示', () => {
    renderProviders(
      <PreviewPanel template="x" records={[{ a: 1 }]} tableName="员工表" />,
    )
    expect(screen.getByText(/预览前 1 行（渲染用全量数据）/)).toBeInTheDocument()
  })

  it('未定义变量显示渲染错误（throwOnUndefined 对齐后端 StrictUndefined）', async () => {
    renderProviders(
      <PreviewPanel template="{{ 不存在的变量 }}" records={[]} tableName="员工表" />,
    )
    // 防抖 300ms 后才更新，findBy* 自带等待
    expect(await screen.findByText('渲染错误')).toBeInTheDocument()
  })

  it('default 过滤器对未定义变量仍然生效', async () => {
    renderProviders(
      <PreviewPanel template="{{ missing | default('备用值') }}" records={[]} tableName="员工表" />,
    )
    expect(await screen.findByText(/备用值/)).toBeInTheDocument()
  })

  it('records_by_table 注入生效（额外表首行取值）', async () => {
    renderProviders(
      <PreviewPanel
        template="{{ records_by_table['项目表'][0].项目名 }}"
        records={[]}
        tableName="员工表"
        recordsByTable={{ 项目表: [{ 项目名: '银河项目' }] }}
      />,
    )
    expect(await screen.findByText(/银河项目/)).toBeInTheDocument()
  })

  it('params 注入生效', async () => {
    renderProviders(
      <PreviewPanel
        template="{{ params.msg }}"
        records={[]}
        tableName="员工表"
        params={{ msg: '你好参数' }}
      />,
    )
    expect(await screen.findByText(/你好参数/)).toBeInTheDocument()
  })

  it('模板为空时显示占位提示', () => {
    renderProviders(<PreviewPanel template="  " records={[]} tableName="员工表" />)
    expect(screen.getByText(/在左侧编辑器输入模板后/)).toBeInTheDocument()
  })
})
