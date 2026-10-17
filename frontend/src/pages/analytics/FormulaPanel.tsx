/** 公式编辑器卡片 —— 多行公式 + 字段/函数快捷插入 + 本地校验提示 + Ctrl/Cmd+Enter 运行. */

import { useRef } from 'react'
import { Alert, Button, Card, Dropdown, Input, Tag, Tooltip, Typography } from 'antd'
import type { InputRef } from 'antd'
import { DeleteOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { AnalyticsFormula } from '@/api/analytics'
import { insertAtCursor, newFormula } from './analyticsModel'

const { Text } = Typography

/** 单值函数快捷片段（插入末尾留光标在括号内） */
const SCALAR_FUNCS = ['round(', 'abs(', 'sqrt(', 'pow(', 'ceil(', 'floor(']

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

/** 公式编辑卡片：编辑态由父级持有，本组件只负责输入与快捷插入 */
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

  const patch = (index: number, field: keyof AnalyticsFormula, value: string) => {
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
    <Card
      size="small"
      title="自定义计算模板"
      extra={
        <Tooltip
          title={
            <div style={{ lineHeight: 1.9 }}>
              [字段名] 引用字段值；支持 + - * / ( ) 与后缀 %；
              单值函数：round(x, n) / abs / sqrt / pow(x, y) / ceil / floor；
              整列聚合：sum([字段]) / avg / count / min / max；
              例：round([合格数] / [实际产量] * 100, 2) 逐行算合格率；
              Ctrl / Cmd + Enter 直接运行分析
            </div>
          }
        >
          <Text type="secondary" style={{ fontSize: 12, cursor: 'help' }}>公式语法</Text>
        </Tooltip>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {tableFields.length > 0 && (
          <div data-testid="analytics-field-chips" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>点击插入字段：</Text>
            {tableFields.map(name => (
              <Tag
                key={name}
                color="blue"
                style={{ cursor: 'pointer', marginInlineEnd: 0 }}
                onClick={() => insertSnippet(`[${name}]`)}
              >
                {name}
              </Tag>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>快捷函数：</Text>
          {SCALAR_FUNCS.map(fn => (
            <Tag key={fn} style={{ cursor: 'pointer', marginInlineEnd: 0 }} onClick={() => insertSnippet(fn)}>
              {fn.replace('(', '')}
            </Tag>
          ))}
          {(['sum', 'avg', 'count', 'min', 'max'] as const).map(fn => (
            <Tag
              key={fn}
              color="purple"
              style={{ cursor: 'pointer', marginInlineEnd: 0 }}
              onClick={() => insertSnippet(`${fn}([${numericFields[0] ?? '字段'}])`)}
            >
              {fn}
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
          return (
            <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
              <Input
                style={{ width: 110 }}
                placeholder="键名"
                aria-label={`公式键名 ${i + 1}`}
                value={formula.key}
                onChange={e => patch(i, 'key', e.target.value)}
              />
              <Input
                style={{ width: 110 }}
                placeholder="展示名"
                aria-label={`公式展示名 ${i + 1}`}
                value={formula.label}
                onChange={e => patch(i, 'label', e.target.value)}
              />
              <Input
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
                    if (canRun && !running) onRun()
                  }
                }}
                onChange={e => patch(i, 'expr', e.target.value)}
                ref={el => { exprRefs.current[i] = el }}
              />
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                aria-label="删除公式"
                onClick={() => onChange(formulas.length > 1 ? formulas.filter((_, j) => j !== i) : [newFormula(0)])}
              />
            </div>
          )
        })}

        {errorTexts.length > 0 && (
          <Alert
            type="error"
            showIcon
            data-testid="analytics-formula-error"
            message={errorTexts.map(([key, message]) => `${key || '未命名'}：${message}`).join('；')}
          />
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => onChange([...formulas, newFormula(formulas.length)])}
          >
            添加公式
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ThunderboltOutlined /> Ctrl / Cmd + Enter 运行
          </Text>
        </div>
      </div>
    </Card>
  )
}
