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

  // ── selectattr / rejectattr Jinja2 三参数（测试名）语义 —— 员工名册过滤场景 ──

  /** 员工名册式数据：是否在职 为 是/否 文本 */
  const EMP_ROWS = [
    { 姓名: '张三', 部门: '技术部', 是否在职: '是', 薪资: 15000 },
    { 姓名: '赵六', 部门: '财务部', 是否在职: '否', 薪资: 13000 },
    { 姓名: '钱七', 部门: '技术部', 是否在职: '是', 薪资: 18000 },
  ]

  it('rejectattr(attr, equalto, 值) 按测试名排除（Jinja2 三参数形式）', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set shown = records | rejectattr('是否在职', 'equalto', '否') | list %}[{{ shown | length }}]{% for r in shown %}{{ r.姓名 }}{% endfor %}"
        records={EMP_ROWS}
      />,
    )

    expect(await screen.findByText('[2]张三钱七', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('selectattr(attr, equalto, 值) 按测试名筛选（Jinja2 三参数形式）', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set left = records | selectattr('是否在职', 'equalto', '否') | list %}[{{ left | length }}]{% for r in left %}{{ r.姓名 }}{% endfor %}"
        records={EMP_ROWS}
      />,
    )

    expect(await screen.findByText('[1]赵六', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('selectattr/rejectattr 单参数真值形式保持可用', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set withDept = records | selectattr('部门') | list %}[{{ withDept | length }}]{% set noDept = records | rejectattr('部门') | list %}[{{ noDept | length }}]"
        records={[{ 姓名: '甲', 部门: '技术部' }, { 姓名: '乙' }]}
      />,
    )

    expect(await screen.findByText('[1][1]', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('数值比较测试（gt）与字符串测试（startswith）可用', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set hi = records | selectattr('薪资', 'gt', 14000) | list %}[{{ hi | length }}]{% set tech = records | selectattr('部门', 'startswith', '技') | list %}[{{ tech | length }}]"
        records={EMP_ROWS}
      />,
    )

    expect(await screen.findByText('[2][2]', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('员工名册模板概览统计与后端渲染一致（员工总数非 0）', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set status = params.get('在职状态', '在职') %}{% if status == '离职' %}{% set shown = records | rejectattr('是否在职', 'equalto', '是') | list %}{% elif status == '全部' %}{% set shown = records %}{% else %}{% set shown = records | rejectattr('是否在职', 'equalto', '否') | list %}{% endif %}员工总数 {{ shown | length }} ｜ 离职人数 {{ shown | selectattr('是否在职', 'equalto', '是') | rejectattr('是否在职', 'equalto', '是') | list | length }}"
        records={EMP_ROWS}
        params={{}}
      />,
    )

    // 修复前 Nunjucks 不支持三参数测试名 → shown 为空 → 统计显示 0
    expect(await screen.findByText('员工总数 2 ｜ 离职人数 0', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('params.get(key, default) — key 存在返回值', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set status = params.get('在职状态', '在职') %}状态:{{ status }}"
        records={[]}
        params={{ '在职状态': '离职' }}
      />,
    )
    expect(await screen.findByText('状态:离职', {}, FIND_OPTS)).toBeInTheDocument()
  })

  it('params.get(key, default) — key 缺失回退默认值', async () => {
    renderProviders(
      <PreviewPanel
        template="{% set status = params.get('在职状态', '在职') %}状态:{{ status }}"
        records={[]}
        params={{}}
      />,
    )
    expect(await screen.findByText('状态:在职', {}, FIND_OPTS)).toBeInTheDocument()
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
