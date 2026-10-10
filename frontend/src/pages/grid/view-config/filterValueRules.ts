/**
 * 筛选/排序规则值校验与自动转换 —— 纯函数模块（无副作用）.
 *
 * 背景：视图筛选值由用户自由输入，SQLite 对日期按字符串字典序比较，非零填充
 * 日期（如 2026-9-28）会导致 10 月及之后的日期比较结果错误。本模块在保存前
 * 统一校验并把可兼容输入自动归一为合法值；无法修复的输入返回明确错误信息
 * （含修正方向），由 ViewConfigDialog 渲染 Alert 并阻止保存。
 *
 * 转换语义与后端对齐：
 * - 日期格式清单对齐 field_types/date.py 的 _DATE_PARSE_FORMATS（常用子集）
 * - 布尔真值域对齐 field_types/number.py 的 _BOOLEAN_TRUE_STRINGS
 */

import type { Field } from '@/api'
import { getOpsForField, extractSelectOptions } from '../cells/fieldOps'
import type { FilterRule, SortRule } from './ViewConfigDialog'

// ── 基础归一 ──────────────────────────────────────────

/** 布尔字符串真值域（与后端 _BOOLEAN_TRUE_STRINGS 一致，未匹配字符串视为假） */
const BOOLEAN_TRUE_STRINGS = new Set(['true', 'yes', '1', 'on', '是', '真', '对', 'y', 't', '√'])

/** 全角数字/符号转半角（０-９、．、－、％等 ASCII 对应区段） */
function toHalfWidth(text: string): string {
  let out = ''
  for (const ch of text) {
    const code = ch.charCodeAt(0)
    // 全角区段 FF01-FF5E 与 ASCII 21-7E 一一对应
    out += code >= 0xff01 && code <= 0xff5e ? String.fromCharCode(code - 0xfee0) : ch
  }
  return out
}

/** value 是否为"空值"：undefined / null / 空串（含纯空白）/ 空数组（与后端判空口径一致） */
function isEmptyValue(v: unknown): boolean {
  if (v === undefined || v === null || v === '') return true
  if (typeof v === 'string' && v.trim() === '') return true
  if (Array.isArray(v) && v.length === 0) return true
  return false
}

/**
 * 日期字符串归一为零填充 `YYYY-MM-DD`.
 *
 * 支持 `2026-9-28` / `2026/9/28` / `2026.9.28` / `20260928` / `2026年9月28日`
 * （"日"可省略）。月/日越界或无法识别返回 null。
 */
export function normalizeDateString(input: unknown): string | null {
  if (typeof input !== 'string') return null
  const text = toHalfWidth(input.trim()).replace(/\s+/g, '')
  if (!text) return null
  const m =
    /^(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?$/.exec(text) ??
    /^(\d{4})(\d{2})(\d{2})$/.exec(text)
  if (!m) return null
  const year = Number(m[1])
  const month = Number(m[2])
  const day = m[3] !== undefined ? Number(m[3]) : 1
  // 月 1-12、日 1-31 粗校验 + 真实日历校验（2月30日等由 Date 对象回读比对兜底）
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  const d = new Date(Date.UTC(year, month - 1, day))
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) {
    return null
  }
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${String(year).padStart(4, '0')}-${pad(month)}-${pad(day)}`
}

/**
 * 日期时间字符串归一：日期 + 可选时间。
 *
 * 有时间部分 → `YYYY-MM-DD HH:mm:ss`（秒省略补 00）；无时间部分 → 纯日期
 * `YYYY-MM-DD`（后端对 datetime 字段的纯日期值做整天范围展开）。
 * 时间越界（如 25:00）或格式无法识别返回 null。
 */
export function normalizeDateTimeString(input: unknown): string | null {
  if (typeof input !== 'string') return null
  const text = toHalfWidth(input.trim())
  if (!text) return null
  // 日期与时间以空格或 T 分隔；时间允许 HH:mm / HH:mm:ss（时分秒均兼容单数字，秒可带小数，丢弃小数部分）
  const m = /^(.{1,16}?)[\sT]+(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d+)?)?$/.exec(text)
  if (!m) return normalizeDateString(text) === null ? null : normalizeDateString(text)
  const datePart = normalizeDateString(m[1])
  if (datePart === null) return null
  const hour = Number(m[2])
  const minute = Number(m[3])
  const second = m[4] !== undefined ? Number(m[4]) : 0
  if (hour > 23 || minute > 59 || second > 59) return null
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${datePart} ${pad(hour)}:${pad(minute)}:${pad(second)}`
}

/**
 * 数字字符串解析：trim、全角转半角、去千分位逗号后转 number。
 *
 * NaN / Infinity / 空 / 非数字文本返回 null。
 */
export function parseNumberString(input: unknown): number | null {
  if (typeof input === 'number') return Number.isFinite(input) ? input : null
  if (typeof input !== 'string') return null
  const text = toHalfWidth(input.trim()).replace(/,/g, '')
  if (!text || !/^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/.test(text)) return null
  const n = Number(text)
  return Number.isFinite(n) ? n : null
}

/**
 * 布尔值归一：boolean 直通；字符串匹配真值域（大小写不敏感）→ true，
 * 其余非空字符串 → false；number 0/1；其他类型返回 null。
 */
export function normalizeBooleanValue(input: unknown): boolean | null {
  if (typeof input === 'boolean') return input
  if (typeof input === 'string') {
    const t = input.trim()
    if (!t) return null
    return BOOLEAN_TRUE_STRINGS.has(t.toLowerCase())
  }
  if (typeof input === 'number') return input === 1 ? true : input === 0 ? false : null
  return null
}

/**
 * 列表值归一（in / has_any / has_all）：数组直通；字符串按英文逗号拆分；
 * 单值包数组；逐项 trim 并去除空项。
 */
export function splitListValue(input: unknown): unknown[] {
  if (Array.isArray(input)) return input.filter(v => String(v).trim() !== '')
  if (typeof input === 'string') {
    return input.split(',').map(s => s.trim()).filter(s => s !== '')
  }
  if (input === undefined || input === null || input === '') return []
  return [input]
}

// ── 筛选规则校验 ──────────────────────────────────────

export interface FilterCheckResult {
  /** 归一化后的值（仅校验通过时返回；undefined 表示无需值/删除 value） */
  value?: unknown
  /** 校验失败的中文错误信息（含修正方向），通过时为 undefined */
  error?: string
}

/** 数值族字段类型（值编辑器为数字/文本，筛选值须可转数字） */
const NUMERIC_TYPES = new Set(['number', 'float', 'percentage', 'timestamp'])

/**
 * 单条筛选规则校验 + 值自动转换.
 *
 * 校验顺序：字段存在 → 操作符适用 → 值按字段类型分派（空值 / 格式 / 范围 /
 * 选项合法性）。校验通过返回归一化后的 value；失败返回 error。
 */
export function checkFilterRule(rule: FilterRule, field: Field | undefined): FilterCheckResult {
  if (!field) {
    return { error: `字段「${rule.field_name}」已不存在，请删除该条件或重新选择字段` }
  }
  const ft = field.field_type
  const ops = getOpsForField(ft)
  const opDef = ops.find(o => o.op === rule.op)
  if (!opDef) {
    const validOps = ops.map(o => o.label).join('、')
    return { error: `操作符「${rule.op}」不适用于字段「${field.name}」（类型：${ft}），可用：${validOps}` }
  }
  if (opDef.needValue) {
    return { value: undefined } // 无值操作符：删除多余 value，直通
  }

  if (isEmptyValue(rule.value)) {
    return { error: `条件「${field.name} ${opDef.label}」缺少筛选值，请填写或删除该条件` }
  }

  // link 字段 has_any/has_all：逗号分隔 id → 正整数数组
  if (ft === 'link' && (rule.op === 'has_any' || rule.op === 'has_all')) {
    return checkLinkIdsValue(rule.value, field)
  }

  // in 操作符：统一归一为数组后逐项校验（修复单值字符串触发后端 500 的隐患）
  if (rule.op === 'in') {
    return checkInRule(rule, field)
  }

  switch (opDef.valueKind) {
    case 'number':
      return checkNumberValue(rule.value, field)
    case 'date':
      return checkDateValue(rule.value, field, ft)
    case 'boolean': {
      const b = normalizeBooleanValue(rule.value)
      if (b === null) {
        return { error: `条件「${field.name}」的值无法识别为真/假，请改用开关选择` }
      }
      return { value: b }
    }
    case 'select':
      return checkSelectValue(rule.value, field)
    default:
      return checkTextValue(rule.value)
  }
}

/**
 * in 操作符校验：值归一为数组后按字段类型逐项校验.
 *
 * 带 in 操作符的类型仅有 number/float（数值族，逐项转数字）与
 * select/multiselect（按选项匹配）；无选项配置时退化为文本数组匹配。
 */
function checkInRule(rule: FilterRule, field: Field): FilterCheckResult {
  const items = splitListValue(rule.value)
  if (NUMERIC_TYPES.has(field.field_type)) {
    const nums: number[] = []
    for (const item of items) {
      const n = parseNumberString(item)
      if (n === null) return { error: `条件「${field.name} 属于」的值「${String(item)}」不是合法数字，请用英文逗号分隔多个数值` }
      nums.push(n)
    }
    return { value: nums }
  }
  const options = extractSelectOptions(field.config)
  if (options.length > 0) {
    const resolved: string[] = []
    for (const item of items) {
      const hit = matchSelectOption(item, options)
      if (!hit) return { error: `条件「${field.name} 属于」的值「${String(item)}」不在可选值中，可选：${options.map(o => o.label).join('、')}` }
      resolved.push(hit.value)
    }
    return { value: resolved }
  }
  // 无选项配置的 select：退化为文本数组匹配
  return { value: items.map(v => String(v).trim()) }
}

/** 数字族值校验：转数字 + number/float 的 min/max 范围 + timestamp/percentage 特有值域 */
function checkNumberValue(value: unknown, field: Field): FilterCheckResult {
  // % 后缀（含全角％）视为显式百分比意图，须在数字解析前剥离（解析正则不含 %）
  const isPctSuffix =
    field.field_type === 'percentage' && typeof value === 'string' && toHalfWidth(value.trim()).endsWith('%')
  const n = parseNumberString(isPctSuffix ? toHalfWidth((value as string).trim()).slice(0, -1) : value)
  if (n === null) {
    return { error: `字段「${field.name}」的筛选值「${String(value)}」不是合法数字，请填写数值（如 100 或 3.14）` }
  }
  if (isPctSuffix) {
    return { value: n / 100 }
  }
  if (field.field_type === 'timestamp' && (!Number.isInteger(n) || n < 0)) {
    return { error: `字段「${field.name}」为时间戳类型，筛选值须为非负整数秒（如 1735660800）` }
  }
  if (field.field_type === 'percentage') {
    // 裸数字（无 % 后缀）须为 0~1 比例值（与后端写入侧一致）；% 后缀已在前面提前返回
    if (n < 0 || n > 1) {
      return { error: `字段「${field.name}」为百分比类型，裸数字须在 0~1 之间（比例值），或显式带 %（如 85%）` }
    }
  }
  const cfg = (field.config ?? {}) as { min?: unknown; max?: unknown }
  const min = typeof cfg.min === 'number' ? cfg.min : undefined
  const max = typeof cfg.max === 'number' ? cfg.max : undefined
  if (min !== undefined && n < min) {
    return { error: `筛选值 ${n} 小于字段「${field.name}」的最小值 ${min}` }
  }
  if (max !== undefined && n > max) {
    return { error: `筛选值 ${n} 大于字段「${field.name}」的最大值 ${max}` }
  }
  return { value: n }
}

/** 日期/日期时间值校验：归一为零填充格式 */
function checkDateValue(value: unknown, field: Field, ft: string): FilterCheckResult {
  const normalized = ft === 'datetime' ? normalizeDateTimeString(value) : normalizeDateString(value)
  if (normalized === null) {
    return {
      error: `字段「${field.name}」的筛选值「${String(value)}」无法识别为日期，请使用如 2026-09-28${ft === 'datetime' ? ' 或 2026-09-28 14:30' : ''} 的格式`,
    }
  }
  return { value: normalized }
}

/** select/multiselect 值校验：值（或 label）必须命中选项 */
function checkSelectValue(value: unknown, field: Field): FilterCheckResult {
  const options = extractSelectOptions(field.config)
  if (options.length === 0) {
    return { value: String(value).trim() } // 字段未配置选项时退化为文本匹配
  }
  const hit = matchSelectOption(value, options)
  if (!hit) {
    return { error: `字段「${field.name}」的筛选值「${String(value)}」不在可选值中，可选：${options.map(o => o.label).join('、')}` }
  }
  return { value: hit.value } // label 命中时归一为 option value（与后端行级判定口径一致）
}

/** select 值匹配选项：命中返回 option（value/label 均可匹配），未命中返回 null */
function matchSelectOption(value: unknown, options: Array<{ value: string; label: string }>): { value: string; label: string } | null {
  const s = String(value).trim()
  return options.find(o => o.value === s || o.label === s) ?? null
}

/** 文本族值校验：仅做 trim 清理（contains/starts_with/ends_with 语义不变） */
function checkTextValue(value: unknown): FilterCheckResult {
  return { value: String(value).trim() }
}

/** link 字段 has_any/has_all 值校验：逗号分隔 id → 正整数数组 */
export function checkLinkIdsValue(value: unknown, field: Field): FilterCheckResult {
  const items = splitListValue(value)
  if (items.length === 0) {
    return { error: `条件「${field.name}」缺少关联行 id，请填写（多个用英文逗号分隔）或删除该条件` }
  }
  const ids: number[] = []
  for (const item of items) {
    const n = parseNumberString(item)
    if (n === null || !Number.isInteger(n) || n <= 0) {
      return { error: `条件「${field.name}」的关联 id「${String(item)}」不是正整数，请填写目标行的数字 id` }
    }
    ids.push(n)
  }
  return { value: ids }
}

// ── 排序规则校验 ──────────────────────────────────────

/** 单条排序规则校验：字段存在 + direction 合法。通过返回 null，失败返回错误信息 */
export function checkSortRule(rule: SortRule, fields: Field[]): string | null {
  if (!fields.some(f => f.name === rule.field_name)) {
    return `排序字段「${rule.field_name}」已不存在，请删除该排序或重新选择字段`
  }
  if (rule.direction !== 'asc' && rule.direction !== 'desc') {
    return `排序规则「${rule.field_name}」的方向非法（${String(rule.direction)}），须为 asc 或 desc`
  }
  return null
}

// ── 汇总入口 ──────────────────────────────────────────

export interface DraftError {
  /** 规则在草稿列表中的序号（0 起，用于定位到具体行） */
  index: number
  message: string
}

export interface ValidateDraftResult {
  /** 归一化后的筛选规则（仅当 errors 为空时可直接使用） */
  filters: FilterRule[]
  /** 归一化后的排序规则 */
  sorts: SortRule[]
  /** 全部校验错误；非空即阻止保存 */
  errors: DraftError[]
}

/**
 * 视图配置草稿统一校验 + 归一（筛选 + 排序）.
 *
 * 返回归一化后的 filters/sorts 与错误列表；errors 非空时调用方应阻止保存并
 * 渲染错误信息。筛选规则 field_name 为空的行沿用既有语义静默丢弃（视为未填写）。
 */
export function validateAndNormalizeDraft(
  filters: FilterRule[],
  sorts: SortRule[],
  fields: Field[],
): ValidateDraftResult {
  const errors: DraftError[] = []
  const normalizedFilters: FilterRule[] = []
  filters.forEach((rule, index) => {
    if (!rule.field_name) return // 空规则行：与既有 cleanFilters 语义一致，静默丢弃
    const field = fields.find(f => f.name === rule.field_name)
    const result = checkFilterRule(rule, field)
    if (result.error) {
      errors.push({ index, message: result.error })
      return
    }
    const next: FilterRule = { field_name: rule.field_name, op: rule.op }
    if (result.value !== undefined) next.value = result.value
    normalizedFilters.push(next)
  })

  const normalizedSorts: SortRule[] = []
  sorts.forEach((rule, index) => {
    if (!rule.field_name) return // 空规则行：与既有 cleanSorts 语义一致，静默丢弃
    const error = checkSortRule(rule, fields)
    if (error) {
      errors.push({ index, message: error })
      return
    }
    normalizedSorts.push({ field_name: rule.field_name, direction: rule.direction })
  })

  return { filters: normalizedFilters, sorts: normalizedSorts, errors }
}
