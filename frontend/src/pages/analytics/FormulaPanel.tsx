/** 公式编辑器 —— 多行公式 + 字段/函数快捷插入 + 本地校验提示 + Ctrl/Cmd+Enter 运行.
 *
 * 排版：每条公式占两行（键名/展示名 + 全宽表达式）。表达式独享一行，
 * 长公式（round(sum([a]) / sum([b]) * 100, 2)）在 400px 配置栏里也能整行读完；
 * 字段 / 函数快捷片段压成 11px 中性 chip，避免彩色标签堆成噪音。
 */

import { useRef } from 'react'
import { Alert, Button, Dropdown, Input, Select, Tag, Tooltip } from 'antd'
import type { InputRef } from 'antd'
import { DeleteOutlined, FunctionOutlined, PlusOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import type { AnalyticsFormula } from '@/api/analytics'
import { AnalyticsBox } from './AnalyticsBox'
import { insertAtCursor, newFormula } from './analyticsModel'

/** 单值函数快捷片段（插入末尾留光标在括号内） */
const SCALAR_FUNCS = ['round(', 'abs(', 'sqrt(', 'pow(', 'ceil(', 'floor(']

/** 窗口函数（按「分区 + 排序」的行序列计算；第一个参数必须是字段引用） */
const SHIFT_FUNCS = ['prev(', 'lag(', 'lead(', 'diff(', 'pct_change(', 'cumsum(', 'rank(']
const ROLLING_FUNCS = ['ma(', 'rolling_sum(', 'rolling_std(']
/** 聚合函数（整列口径，插入时预填首个数值字段） */
const AGG_FUNCS = ['sum', 'avg', 'count', 'min', 'max'] as const
/** 表达式是否含窗口函数（决定是否展示分区 / 排序选择器） */
const WINDOW_CALL_RE = /\b(?:prev|lag|lead|diff|pct_change|cumsum|ma|rolling_sum|rolling_std|rank)\s*\(/i

interface Props {
  /** 数据表可见字段（点击插入 [字段]） */
  tableFields: string[]
  /** 数值字段（用于聚合函数 / 示例片段预填） */
  numericFields: string[]
  formulas: AnalyticsFormula[]
  /** 公式键 / 键名 → 错误信息（本地结构错误 + 后端语法/字段引用错误） */
  errors: Record<string, string>
  onChange: (formulas: AnalyticsFormula[]) => void
  /** Ctrl/Cmd+Enter 触发运行 */
  onRun: () => void
  canRun: boolean
  running: boolean
}

/** 公式编辑区：编辑态由父级持有，本组件只负责输入与快捷插入 */
export function FormulaPanel({
  tableFields,
  numericFields,
  formulas,
  errors,
  onChange,
  onRun,
  canRun,
  running,
}: Props) {
  const exprRefs = useRef<Array<InputRef | null>>([])
  const focusedIndex = useRef(0)
  const lastKeyRef = useRef<HTMLInputElement | null>(null)

  /** 在最近聚焦的公式输入光标处插入片段（并恢复光标位置） */
  const insertSnippet = (snippet: string) => {
    const index = Math.min(focusedIndex.current, formulas.length - 1)
    const target = formulas[index]
    const input = lastKeyRef.current
    const caret = input?.selectionStart ?? target.expr.length
    const next = insertAtCursor(target.expr, snippet, caret)
    onChange(formulas.map((item, i) => (i === index ? { ...item, expr: next.value } : item)))
    // 等 React 回填受控值后再聚焦 + 定位光标
    requestAnimationFrame(() => {
      const el = exprRefs.current[index]?.input as HTMLInputElement | null
      if (!el) return
      el.focus()
      el.setSelectionRange(next.caret, next.caret)
    })
  }

  const patch = (index: number, field: keyof AnalyticsFormula, value: string | boolean | undefined) => {
    onChange(formulas.map((item, i) => (i === index ? { ...item, [field]: value } : item)))
  }

  const exampleMenu = () => {
    const items = []
    if (numericFields.length >= 1) {
      items.push({
        key: 'overall-sum',
        label: `整体求和：sum([${numericFields[0]}])`,
        onClick: () => insertSnippet(`sum([${numericFields[0]}])`),
      })
    }
    if (numericFields.length >= 2) {
      const [a, b] = numericFields
      items.push(
        { key: 'ratio', label: `逐行占比：round([${a}] / [${b}] * 100, 2)`, onClick: () => insertSnippet(`round([${a}] / [${b}] * 100, 2)`) },
        { key: 'overall-ratio', label: `整体占比：round(sum([${a}]) / sum([${b}]) * 100, 2)`, onClick: () => insertSnippet(`round(sum([${a}]) / sum([${b}]) * 100, 2)`) },
      )
    }
    return items
  }

  const errorTexts = Object.entries(errors)

  return (
    <AnalyticsBox
      title="计算模板"
      icon={<FunctionOutlined />}
      className="cn-an-box--formula"
      extra={
        <Tooltip
          title={
            <div style={{ lineHeight: 1.9 }}>
              [字段名] 引用字段值；支持 + - * / ( ) 与后缀 %；
              单值函数：round(x, n) / abs / sqrt / pow(x, y) / ceil / floor；
              整列聚合：sum([字段]) / avg / count / min / max；
              窗口函数（按分区 + 排序）：lag / lead / prev / diff / pct_change / cumsum / rank / ma([字段], n) / rolling_sum / rolling_std；
              例：round([合格数] / [实际产量] * 100, 2) 逐行算合格率；
                  round(pct_change([收盘价]) * 100, 2) 分区内按时间算环比
            </div>
          }
        >
          <QuestionCircleOutlined className="cn-an-box-hint" aria-label="公式语法" />
        </Tooltip>
      }
      footer={
        <>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => onChange([...formulas, newFormula(formulas.length)])}>
            添加公式
          </Button>
          <span className="cn-an-foot-hint">Ctrl / ⌘ + Enter 运行</span>
        </>
      }
    >
      {/* 字段：click 插入 [字段]（保留 data-testid，测试与依赖此容器的交互） */}
      <div className="cn-an-chips" data-testid="analytics-field-chips">
        <span className="cn-an-chips-label">字段</span>
        {tableFields.length === 0 ? (
          <span className="cn-an-muted">选择数据表后显示字段</span>
        ) : (
          tableFields.map(name => (
            <Tag key={name} className="cn-an-chip" onClick={() => insertSnippet(`[${name}]`)}>
              {name}
            </Tag>
          ))
        )}
      </div>

      {/* 函数：单值 / 聚合 / 窗口 / 滚动，全部平铺（搜索成本低于折叠菜单） */}
      <div className="cn-an-chips">
        <span className="cn-an-chips-label">函数</span>
        {SCALAR_FUNCS.map(fn => (
          <Tag key={fn} className="cn-an-chip cn-an-chip--fn" onClick={() => insertSnippet(fn)}>
            {fn.replace('(', '')}
          </Tag>
        ))}
        {AGG_FUNCS.map(fn => (
          <Tag
            key={fn}
            className="cn-an-chip cn-an-chip--agg"
            onClick={() => insertSnippet(`${fn}([${numericFields[0] ?? '字段'}])`)}
          >
            {fn}
          </Tag>
        ))}
        {SHIFT_FUNCS.map(fn => (
          <Tag
            key={fn}
            className="cn-an-chip cn-an-chip--win"
            onClick={() => insertSnippet(`${fn}[${numericFields[0] ?? '字段'}])`)}
          >
            {fn.replace('(', '')}
          </Tag>
        ))}
        {ROLLING_FUNCS.map(fn => (
          <Tag
            key={fn}
            className="cn-an-chip cn-an-chip--win"
            title="滚动窗口需指定长度，如 ma([字段], 3)"
            onClick={() => insertSnippet(`${fn}[${numericFields[0] ?? '字段'}], 3)`)}
          >
            {fn.replace('(', '')}
          </Tag>
        ))}
        <Dropdown menu={{ items: exampleMenu() }} disabled={exampleMenu().length === 0}>
          <Button size="small" type="link" data-testid="analytics-formula-example">
            示例
          </Button>
        </Dropdown>
      </div>

      {formulas.map((formula, i) => {
        const key = formula.key.trim()
        const error = errors[key] || errors[formula.key]
        const isWindow = WINDOW_CALL_RE.test(formula.expr)
        return (
          <div key={i} className="cn-an-frow">
            <div className="cn-an-frow-top">
              <span className="cn-an-frow-no" aria-hidden>{i + 1}</span>
              <Input
                size="small"
                className="cn-an-frow-key"
                placeholder="键名"
                aria-label={`公式键名 ${i + 1}`}
                value={formula.key}
                onChange={e => patch(i, 'key', e.target.value)}
              />
              <Input
                size="small"
                className="cn-an-frow-label"
                placeholder="展示名（可选）"
                aria-label={`公式展示名 ${i + 1}`}
                value={formula.label}
                onChange={e => patch(i, 'label', e.target.value)}
              />
              <Button
                className="cn-an-frow-del"
                type="text"
                danger
                icon={<DeleteOutlined />}
                aria-label="删除公式"
                onClick={() => onChange(formulas.length > 1 ? formulas.filter((_, j) => j !== i) : [newFormula(0)])}
              />
            </div>
            <Input
              size="small"
              className="cn-an-frow-expr"
              data-testid={`analytics-formula-expr-${i}`}
              placeholder="round([合格数] / [实际产量] * 100, 2)"
              aria-label={`公式表达式 ${i + 1}`}
              value={formula.expr}
              status={error ? 'error' : undefined}
              onFocus={e => {
                focusedIndex.current = i
                lastKeyRef.current = e.target as HTMLInputElement
              }}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault()
                  // 阻断冒泡：页面级全局快捷键也监听同键位，避免触发两次
                  e.stopPropagation()
                  if (canRun && !running) onRun()
                }
              }}
              onChange={e => patch(i, 'expr', e.target.value)}
              ref={el => { exprRefs.current[i] = el }}
            />
            {isWindow && (
              <div className="cn-an-frow-win" data-testid={`analytics-formula-window-${i}`}>
                <Select
                  size="small"
                  allowClear
                  placeholder="分区字段"
                  className="cn-an-frow-win-select"
                  aria-label={`公式分区字段 ${i + 1}`}
                  value={formula.partition_by ?? undefined}
                  options={tableFields.map(name => ({ value: name, label: name }))}
                  onChange={value => patch(i, 'partition_by', value ?? undefined)}
                />
                <Select
                  size="small"
                  allowClear
                  placeholder="排序字段"
                  className="cn-an-frow-win-select"
                  aria-label={`公式排序字段 ${i + 1}`}
                  value={formula.order_by ?? undefined}
                  options={tableFields.map(name => ({ value: name, label: name }))}
                  onChange={value => patch(i, 'order_by', value ?? undefined)}
                />
                <Select
                  size="small"
                  className="cn-an-frow-win-dir"
                  aria-label={`公式排序方向 ${i + 1}`}
                  value={formula.order_desc ? 'desc' : 'asc'}
                  options={[
                    { value: 'asc', label: '升序' },
                    { value: 'desc', label: '降序' },
                  ]}
                  onChange={value => patch(i, 'order_desc', value === 'desc')}
                />
                <span className="cn-an-foot-hint">窗口函数先按分区分组、再按排序字段计算</span>
              </div>
            )}
          </div>
        )
      })}

      {errorTexts.length > 0 && (
        <Alert
          type="error"
          showIcon
          data-testid="analytics-formula-error"
          title={errorTexts.map(([key, message]) => `${key || '未命名'}：${message}`).join('；')}
        />
      )}
    </AnalyticsBox>
  )
}
