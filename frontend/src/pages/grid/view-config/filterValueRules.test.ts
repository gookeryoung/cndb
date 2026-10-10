/**
 * filterValueRules 单测 —— 筛选/排序规则值校验与自动转换.
 *
 * 覆盖矩阵：合法值 / 边界值（闰年、范围边界、选项边界）/ 异常值（非法格式、
 * 类型不匹配、空值、越界、特殊字符）/ 自动转换（日期零填充、数字解析、
 * 空白清理、布尔归一、label→option value、列表拆分）。
 */

import { describe, expect, it } from 'vitest'
import {
    checkFilterRule,
    checkLinkIdsValue,
    checkSortRule,
    normalizeBooleanValue,
    normalizeDateString,
    normalizeDateTimeString,
    parseNumberString,
    splitListValue,
    validateAndNormalizeDraft,
} from './filterValueRules'
import type { FilterRule, SortRule } from './ViewConfigDialog'
import { makeField } from '@/test/fixtures'

// ── normalizeDateString ──────────────────────────────

describe('normalizeDateString 日期归一', () => {
    it('零填充与非零填充 ISO 均归一为 YYYY-MM-DD', () => {
        expect(normalizeDateString('2026-9-28')).toBe('2026-09-28')
        expect(normalizeDateString('2026-09-28')).toBe('2026-09-28')
        expect(normalizeDateString('2026-1-1')).toBe('2026-01-01')
    })

    it('支持斜杠/点/紧凑/中文分隔', () => {
        expect(normalizeDateString('2026/9/8')).toBe('2026-09-08')
        expect(normalizeDateString('2026.09.28')).toBe('2026-09-28')
        expect(normalizeDateString('20260928')).toBe('2026-09-28')
        expect(normalizeDateString('2026年9月28日')).toBe('2026-09-28')
        expect(normalizeDateString('2026年9月28')).toBe('2026-09-28') // "日"省略
    })

    it('边界：仅年月（缺日）默认 1 日，中文格式须带日', () => {
        expect(normalizeDateString('2026-9')).toBe('2026-09-01')
        expect(normalizeDateString('2026年9月')).toBeNull() // 中文格式"月"后必须跟日
    })

    it('前后空白自动清理', () => {
        expect(normalizeDateString('  2026-9-28  ')).toBe('2026-09-28')
    })

    it('边界：闰年 2 月 29 日合法、平年非法', () => {
        expect(normalizeDateString('2028-2-29')).toBe('2028-02-29')
        expect(normalizeDateString('2026-2-29')).toBeNull()
        expect(normalizeDateString('2026-2-30')).toBeNull()
    })

    it('异常：月/日越界、格式无法识别、空值、非字符串', () => {
        expect(normalizeDateString('2026-13-01')).toBeNull()
        expect(normalizeDateString('2026-0-5')).toBeNull()
        expect(normalizeDateString('2026-9-32')).toBeNull()
        expect(normalizeDateString('abc')).toBeNull()
        expect(normalizeDateString('9/28/2026')).toBeNull() // 美式格式前端不认（后端支持）
        expect(normalizeDateString('')).toBeNull()
        expect(normalizeDateString('   ')).toBeNull()
        expect(normalizeDateString(42)).toBeNull()
        expect(normalizeDateString(null)).toBeNull()
        expect(normalizeDateString(['2026-09-28'])).toBeNull()
    })
})

// ── normalizeDateTimeString ──────────────────────────

describe('normalizeDateTimeString 日期时间归一', () => {
    it('日期 + HH:mm / HH:mm:ss 归一为固定格式', () => {
        expect(normalizeDateTimeString('2026-9-28 9:5')).toBe('2026-09-28 09:05:00')
        expect(normalizeDateTimeString('2026-09-28 14:30:00')).toBe('2026-09-28 14:30:00')
        expect(normalizeDateTimeString('2026/9/28 8:00:15')).toBe('2026-09-28 08:00:15')
    })

    it('支持 T 分隔与秒小数（小数丢弃）', () => {
        expect(normalizeDateTimeString('2026-09-28T14:30')).toBe('2026-09-28 14:30:00')
        expect(normalizeDateTimeString('2026-09-28 10:00:00.5')).toBe('2026-09-28 10:00:00')
    })

    it('纯日期委托给日期归一（后端做整天范围展开）', () => {
        expect(normalizeDateTimeString('2026-9-28')).toBe('2026-09-28')
    })

    it('异常：时间越界、日期部分非法、空值、非字符串', () => {
        expect(normalizeDateTimeString('2026-09-28 25:00')).toBeNull()
        expect(normalizeDateTimeString('2026-09-28 12:60')).toBeNull()
        expect(normalizeDateTimeString('2026-09-28 10:00:61')).toBeNull()
        expect(normalizeDateTimeString('abc 10:00')).toBeNull()
        expect(normalizeDateTimeString('2026-13-01 10:00')).toBeNull()
        expect(normalizeDateTimeString('abc')).toBeNull() // 无时间部分且日期非法
        expect(normalizeDateTimeString('')).toBeNull()
        expect(normalizeDateTimeString(42)).toBeNull()
        expect(normalizeDateTimeString(null)).toBeNull()
    })
})

// ── parseNumberString ────────────────────────────────

describe('parseNumberString 数字解析', () => {
    it('数字类型直通（有限值）', () => {
        expect(parseNumberString(42)).toBe(42)
        expect(parseNumberString(3.14)).toBe(3.14)
        expect(parseNumberString(-7)).toBe(-7)
        expect(parseNumberString(0)).toBe(0)
    })

    it('字符串：千分位、全角、正负号、小数、科学计数法', () => {
        expect(parseNumberString('1,234')).toBe(1234)
        expect(parseNumberString('１２３')).toBe(123)
        expect(parseNumberString('+5')).toBe(5)
        expect(parseNumberString('-2.5')).toBe(-2.5)
        expect(parseNumberString('1e3')).toBe(1000)
        expect(parseNumberString(' 7 ')).toBe(7)
    })

    it('异常：NaN/Infinity/空/非数字文本/其他类型', () => {
        expect(parseNumberString(NaN)).toBeNull()
        expect(parseNumberString(Infinity)).toBeNull()
        expect(parseNumberString('1e999')).toBeNull() // 解析后溢出为 Infinity
        expect(parseNumberString('abc')).toBeNull()
        expect(parseNumberString('1.2.3')).toBeNull()
        expect(parseNumberString('')).toBeNull()
        expect(parseNumberString('   ')).toBeNull()
        expect(parseNumberString(true)).toBeNull()
        expect(parseNumberString(null)).toBeNull()
        expect(parseNumberString([1])).toBeNull()
    })
})

// ── normalizeBooleanValue ────────────────────────────

describe('normalizeBooleanValue 布尔归一', () => {
    it('boolean 直通', () => {
        expect(normalizeBooleanValue(true)).toBe(true)
        expect(normalizeBooleanValue(false)).toBe(false)
    })

    it('真值域字符串（与后端值域一致，大小写不敏感）', () => {
        for (const s of ['是', 'true', 'TRUE', 'Yes', '1', 'on', 'y', 't', '√', '真', '对']) {
            expect(normalizeBooleanValue(s)).toBe(true)
        }
    })

    it('非真值字符串返回 false', () => {
        expect(normalizeBooleanValue('否')).toBe(false)
        expect(normalizeBooleanValue('false')).toBe(false)
        expect(normalizeBooleanValue('0')).toBe(false)
        expect(normalizeBooleanValue('随便')).toBe(false)
    })

    it('number：0/1 映射布尔，其余 null', () => {
        expect(normalizeBooleanValue(1)).toBe(true)
        expect(normalizeBooleanValue(0)).toBe(false)
        expect(normalizeBooleanValue(2)).toBeNull()
    })

    it('异常：空串/空白/其他类型返回 null', () => {
        expect(normalizeBooleanValue('')).toBeNull()
        expect(normalizeBooleanValue('   ')).toBeNull()
        expect(normalizeBooleanValue(null)).toBeNull()
        expect(normalizeBooleanValue(['是'])).toBeNull()
    })
})

// ── splitListValue ───────────────────────────────────

describe('splitListValue 列表归一', () => {
    it('数组直通并去空项', () => {
        expect(splitListValue(['a', ' b ', ''])).toEqual(['a', ' b '])
    })

    it('字符串按英文逗号拆分、逐项 trim、去空', () => {
        expect(splitListValue('a, b , c')).toEqual(['a', 'b', 'c'])
        expect(splitListValue('a,,b,')).toEqual(['a', 'b'])
    })

    it('单值包数组', () => {
        expect(splitListValue('a')).toEqual(['a'])
        expect(splitListValue(42)).toEqual([42])
    })

    it('空值返回空数组', () => {
        expect(splitListValue('')).toEqual([])
        expect(splitListValue(null)).toEqual([])
        expect(splitListValue(undefined)).toEqual([])
        expect(splitListValue([])).toEqual([])
    })
})

// ── checkFilterRule ──────────────────────────────────

const TEXT_FIELD = makeField({ id: 1, name: '姓名', field_type: 'text' })
const SELECT_FIELD = makeField({ id: 2, name: '状态', field_type: 'select', config: { options: ['高', '中'] } })
const NUMBER_FIELD = makeField({ id: 3, name: '年龄', field_type: 'number' })
const NUMBER_RANGE_FIELD = makeField({ id: 4, name: '评分', field_type: 'number', config: { min: 0, max: 10 } })
const FLOAT_FIELD = makeField({ id: 5, name: '工时', field_type: 'float' })
const PCT_FIELD = makeField({ id: 6, name: '进度', field_type: 'percentage' })
const TS_FIELD = makeField({ id: 7, name: '时间戳', field_type: 'timestamp' })
const DATE_FIELD = makeField({ id: 8, name: '完成日期', field_type: 'date' })
const DT_FIELD = makeField({ id: 9, name: '创建时间', field_type: 'datetime' })
const BOOL_FIELD = makeField({ id: 10, name: '是否完成', field_type: 'boolean' })
const LINK_FIELD = makeField({ id: 11, name: '关联行', field_type: 'link' })

describe('checkFilterRule 单条规则校验', () => {
    it('字段不存在 → 明确错误', () => {
        const r = checkFilterRule({ field_name: '幽灵字段', op: 'contains', value: 'x' }, undefined)
        expect(r.error).toContain('幽灵字段')
        expect(r.error).toContain('已不存在')
    })

    it('操作符不适用 → 错误并列出可用操作符', () => {
        const r = checkFilterRule({ field_name: '姓名', op: '>', value: 'x' }, TEXT_FIELD)
        expect(r.error).toContain('不适用于')
        expect(r.error).toContain('姓名')
    })

    it('无值操作符 → 删除多余 value 直通', () => {
        const r = checkFilterRule({ field_name: '姓名', op: 'is_empty', value: '多余' }, TEXT_FIELD)
        expect(r.error).toBeUndefined()
        expect(r.value).toBeUndefined()
    })

    it('空值各形态 → 错误提示填写或删除', () => {
        for (const v of [undefined, null, '', '   ', []]) {
            const r = checkFilterRule({ field_name: '姓名', op: 'contains', value: v }, TEXT_FIELD)
            expect(r.error).toContain('缺少筛选值')
        }
    })

    it('文本族：trim 清理且保留输入内容', () => {
        const r = checkFilterRule({ field_name: '姓名', op: 'contains', value: '  张三  ' }, TEXT_FIELD)
        expect(r.value).toBe('张三')
    })

    describe('数值族', () => {
        it('数字与数字字符串归一', () => {
            expect(checkFilterRule({ field_name: '年龄', op: '>', value: 18 }, NUMBER_FIELD).value).toBe(18)
            expect(checkFilterRule({ field_name: '年龄', op: '>', value: '18' }, NUMBER_FIELD).value).toBe(18)
            expect(checkFilterRule({ field_name: '年龄', op: 'in', value: '1, 2,3' }, NUMBER_FIELD).value).toEqual([1, 2, 3])
            // in 中含非法数字项 → 逐项校验报错
            expect(checkFilterRule({ field_name: '年龄', op: 'in', value: '1,abc' }, NUMBER_FIELD).error).toContain('不是合法数字')
        })

        it('非法数字 → 错误含修正方向', () => {
            const r = checkFilterRule({ field_name: '年龄', op: '>', value: 'abc' }, NUMBER_FIELD)
            expect(r.error).toContain('不是合法数字')
            expect(r.error).toContain('数值')
        })

        it('min/max 范围校验（边界值合法）', () => {
            expect(checkFilterRule({ field_name: '评分', op: '=', value: 0 }, NUMBER_RANGE_FIELD).value).toBe(0)
            expect(checkFilterRule({ field_name: '评分', op: '=', value: 10 }, NUMBER_RANGE_FIELD).value).toBe(10)
            const low = checkFilterRule({ field_name: '评分', op: '>', value: -1 }, NUMBER_RANGE_FIELD)
            expect(low.error).toContain('最小值 0')
            const high = checkFilterRule({ field_name: '评分', op: '>', value: 11 }, NUMBER_RANGE_FIELD)
            expect(high.error).toContain('最大值 10')
        })

        it('小数字段字符串归一', () => {
            expect(checkFilterRule({ field_name: '工时', op: '>=', value: '1,234.5' }, FLOAT_FIELD).value).toBe(1234.5)
            expect(checkFilterRule({ field_name: '工时', op: '>=', value: 'abc' }, FLOAT_FIELD).error).toContain('不是合法数字')
        })

        it('百分比：% 后缀转比例值，裸数字须 0~1，非法报错', () => {
            expect(checkFilterRule({ field_name: '进度', op: '>=', value: '85%' }, PCT_FIELD).value).toBe(0.85)
            expect(checkFilterRule({ field_name: '进度', op: '>=', value: '85％' }, PCT_FIELD).value).toBe(0.85)
            expect(checkFilterRule({ field_name: '进度', op: '>=', value: 0.5 }, PCT_FIELD).value).toBe(0.5)
            expect(checkFilterRule({ field_name: '进度', op: '>=', value: 85 }, PCT_FIELD).error).toContain('0~1')
            expect(checkFilterRule({ field_name: '进度', op: '>=', value: 'abc%' }, PCT_FIELD).error).toContain('不是合法数字')
        })

        it('时间戳：非负整数秒，负数/小数报错', () => {
            expect(checkFilterRule({ field_name: '时间戳', op: '=', value: 1735660800 }, TS_FIELD).value).toBe(1735660800)
            expect(checkFilterRule({ field_name: '时间戳', op: '=', value: -1 }, TS_FIELD).error).toContain('非负整数秒')
            expect(checkFilterRule({ field_name: '时间戳', op: '=', value: 1.5 }, TS_FIELD).error).toContain('非负整数秒')
        })
    })

    describe('日期/日期时间', () => {
        it('非零填充日期自动归一（核心场景：字符串字典序比较修复）', () => {
            expect(checkFilterRule({ field_name: '完成日期', op: '>=', value: '2026-9-28' }, DATE_FIELD).value).toBe('2026-09-28')
        })

        it('非法日期 → 错误含格式示例', () => {
            const r = checkFilterRule({ field_name: '完成日期', op: '>=', value: '9月28号' }, DATE_FIELD)
            expect(r.error).toContain('无法识别为日期')
            expect(r.error).toContain('2026-09-28')
        })

        it('日期时间带时间部分归一为完整格式', () => {
            expect(checkFilterRule({ field_name: '创建时间', op: '=', value: '2026-9-28 9:5' }, DT_FIELD).value).toBe('2026-09-28 09:05:00')
            const r = checkFilterRule({ field_name: '创建时间', op: '=', value: '2026-09-28 25:00' }, DT_FIELD)
            expect(r.error).toContain('无法识别为日期')
        })
    })

    describe('布尔', () => {
        it('开关值直通，字符串真值域归一', () => {
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: true }, BOOL_FIELD).value).toBe(true)
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: '是' }, BOOL_FIELD).value).toBe(true)
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: '否' }, BOOL_FIELD).value).toBe(false)
        })

        it('null 值 → 缺值错误（空值口径统一）', () => {
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: null }, BOOL_FIELD).error).toContain('缺少筛选值')
        })

        it('字符串 "0" 归一为 false（假值直通分支）', () => {
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: '0' }, BOOL_FIELD).value).toBe(false)
        })

        it('非空但无法识别为布尔的值（数组）→ 错误', () => {
            expect(checkFilterRule({ field_name: '是否完成', op: '=', value: ['是'] }, BOOL_FIELD).error).toContain('无法识别为真/假')
        })
    })

    describe('select / multiselect', () => {
        it('选项 value 命中直通，label 命中归一为 value', () => {
            expect(checkFilterRule({ field_name: '状态', op: '=', value: '高' }, SELECT_FIELD).value).toBe('高')
            // options 为 list[str] 形态时 value=label，未配置选项时退化为文本匹配
            const noOpts = makeField({ id: 12, name: '自由状态', field_type: 'select' })
            expect(checkFilterRule({ field_name: '自由状态', op: '=', value: '任意' }, noOpts).value).toBe('任意')
        })

        it('值不在可选值中 → 错误列出可选值', () => {
            const r = checkFilterRule({ field_name: '状态', op: '=', value: '不存在' }, SELECT_FIELD)
            expect(r.error).toContain('不在可选值中')
            expect(r.error).toContain('高、中')
        })

        it('in 操作符：单值包数组、逐项校验', () => {
            expect(checkFilterRule({ field_name: '状态', op: 'in', value: '高' }, SELECT_FIELD).value).toEqual(['高'])
            expect(checkFilterRule({ field_name: '状态', op: 'in', value: '高,中' }, SELECT_FIELD).value).toEqual(['高', '中'])
            const r = checkFilterRule({ field_name: '状态', op: 'in', value: '高,垃圾' }, SELECT_FIELD)
            expect(r.error).toContain('不在可选值中')
        })

        it('无选项配置的 select：in 退化为文本数组', () => {
            const noOpts = makeField({ id: 14, name: '自由状态', field_type: 'select' })
            expect(checkFilterRule({ field_name: '自由状态', op: 'in', value: 'a, b' }, noOpts).value).toEqual(['a', 'b'])
        })

        it('multiselect contains 走选项校验', () => {
            const msField = makeField({ id: 13, name: '标签', field_type: 'multiselect', config: { options: ['a', 'b'] } })
            expect(checkFilterRule({ field_name: '标签', op: 'contains', value: 'a' }, msField).value).toBe('a')
            expect(checkFilterRule({ field_name: '标签', op: 'contains', value: 'z' }, msField).error).toContain('不在可选值中')
        })

        it('文本字段不支持 in（操作符表约束）→ 错误', () => {
            const r = checkFilterRule({ field_name: '姓名', op: 'in', value: ' a , b ' }, TEXT_FIELD)
            expect(r.error).toContain('不适用于')
        })

        describe('link 关联字段', () => {
            it('has_any/has_all：逗号分隔 id 转正整数数组', () => {
                expect(checkFilterRule({ field_name: '关联行', op: 'has_any', value: '1, 2' }, LINK_FIELD).value).toEqual([1, 2])
                expect(checkFilterRule({ field_name: '关联行', op: 'has_all', value: '3' }, LINK_FIELD).value).toEqual([3])
            })

            it('非正整数 id → 错误', () => {
                expect(checkFilterRule({ field_name: '关联行', op: 'has_any', value: 'abc' }, LINK_FIELD).error).toContain('正整数')
                expect(checkFilterRule({ field_name: '关联行', op: 'has_any', value: '0' }, LINK_FIELD).error).toContain('正整数')
                expect(checkFilterRule({ field_name: '关联行', op: 'has_any', value: '' }, LINK_FIELD).error).not.toBeUndefined()
            })

            it('无值操作符（is_empty/is_not_empty）直通', () => {
                const r = checkFilterRule({ field_name: '关联行', op: 'is_empty' }, LINK_FIELD)
                expect(r.error).toBeUndefined()
            })
        })

        it('checkLinkIdsValue 独立导出可用', () => {
            expect(checkLinkIdsValue('1,2', LINK_FIELD).value).toEqual([1, 2])
            expect(checkLinkIdsValue('x', LINK_FIELD).error).toContain('正整数')
            // 仅逗号/空白：归一后为空 → 提示填写 id
            expect(checkLinkIdsValue(' , ', LINK_FIELD).error).toContain('缺少关联行 id')
        })
    })

    // ── checkSortRule ────────────────────────────────────

    describe('checkSortRule 排序规则校验', () => {
        const fields = [TEXT_FIELD, DATE_FIELD]

        it('合法规则返回 null', () => {
            expect(checkSortRule({ field_name: '姓名', direction: 'asc' }, fields)).toBeNull()
            expect(checkSortRule({ field_name: '完成日期', direction: 'desc' }, fields)).toBeNull()
        })

        it('字段不存在 → 错误', () => {
            expect(checkSortRule({ field_name: '幽灵', direction: 'asc' }, fields)).toContain('已不存在')
        })

        it('direction 非法 → 错误', () => {
            expect(checkSortRule({ field_name: '姓名', direction: 'up' as unknown as 'asc' }, fields)).toContain('asc 或 desc')
        })
    })

    // ── validateAndNormalizeDraft ────────────────────────

    describe('validateAndNormalizeDraft 汇总校验', () => {
        const fields = [TEXT_FIELD, DATE_FIELD, NUMBER_FIELD, SELECT_FIELD]

        it('空规则行静默丢弃（筛选与排序），合法规则归一后写回', () => {
            const filters: FilterRule[] = [
                { field_name: '', op: 'contains' },
                { field_name: '完成日期', op: '>=', value: '2026-9-28' },
            ]
            const sorts: SortRule[] = [
                { field_name: '', direction: 'asc' },
                { field_name: '完成日期', direction: 'desc' },
            ]
            const result = validateAndNormalizeDraft(filters, sorts, fields)
            expect(result.errors).toEqual([])
            expect(result.filters).toEqual([{ field_name: '完成日期', op: '>=', value: '2026-09-28' }])
            expect(result.sorts).toEqual([{ field_name: '完成日期', direction: 'desc' }])
        })

        it('错误收集带规则序号（多条错误全部列出）', () => {
            const result = validateAndNormalizeDraft(
                [
                    { field_name: '完成日期', op: '>=', value: '垃圾日期' },
                    { field_name: '年龄', op: '>', value: 'abc' },
                ],
                [],
                fields,
            )
            expect(result.errors).toHaveLength(2)
            expect(result.errors[0]).toMatchObject({ index: 0 })
            expect(result.errors[0].message).toContain('完成日期')
            expect(result.errors[1]).toMatchObject({ index: 1 })
            expect(result.errors[1].message).toContain('年龄')
        })

        it('排序规则错误同样收集', () => {
            const result = validateAndNormalizeDraft([], [{ field_name: '幽灵', direction: 'asc' }], fields)
            expect(result.errors).toHaveLength(1)
            expect(result.errors[0].message).toContain('幽灵')
        })

        it('全部合法时不产生错误且值已归一（含数字字符串与空白清理）', () => {
            const result = validateAndNormalizeDraft(
                [
                    { field_name: '姓名', op: 'contains', value: '  张  ' },
                    { field_name: '年龄', op: '>=', value: '18' },
                    { field_name: '状态', op: '=', value: '高' },
                ],
                [{ field_name: '姓名', direction: 'asc' }],
                fields,
            )
            expect(result.errors).toEqual([])
            expect(result.filters).toEqual([
                { field_name: '姓名', op: 'contains', value: '张' },
                { field_name: '年龄', op: '>=', value: 18 },
                { field_name: '状态', op: '=', value: '高' },
            ])
        })

        it('无值操作符保存时删除 value 键', () => {
            const result = validateAndNormalizeDraft([{ field_name: '姓名', op: 'is_empty', value: '多余' }], [], fields)
            expect(result.errors).toEqual([])
            expect(result.filters).toEqual([{ field_name: '姓名', op: 'is_empty' }])
        })
    })
})
