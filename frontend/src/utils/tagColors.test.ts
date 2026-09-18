/** tagColors 单元测试 —— hash 稳定性、语义推荐、三路径 resolve、缓存重置 */
import { beforeEach, describe, expect, it } from 'vitest'
import {
  __resetTagColorCache,
  ANTD_COLOR_NAMES,
  getTagColor,
  getTagColorName,
  resolveTagColor,
  suggestColorForLabel,
} from './tagColors'

beforeEach(() => {
  __resetTagColorCache()
})

describe('getTagColorName hash 稳定性', () => {
  it('同值多次调用返回同一颜色', () => {
    const first = getTagColorName('客户A')
    expect(getTagColorName('客户A')).toBe(first)
    expect(getTagColorName('客户A')).toBe(first)
  })

  it('返回值属于 13 种主推基础色（不含 inverse/status）', () => {
    const primary = ['blue', 'green', 'orange', 'purple', 'red', 'cyan', 'gold', 'magenta', 'yellow', 'volcano', 'geekblue', 'lime', 'pink']
    for (const v of ['a', 'b', 'c', '标签1', '标签2', 123]) {
      expect(primary).toContain(getTagColorName(v))
    }
  })

  it('空值回退 blue（主推色系首位）', () => {
    expect(getTagColorName('')).toBe('blue')
    expect(getTagColorName('   ')).toBe('blue')
  })

  it('不同值可能得到不同颜色（hash 有区分度）', () => {
    const colors = new Set(['x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', 'x8'].map(getTagColorName))
    expect(colors.size).toBeGreaterThan(1)
  })

  it('getTagColor 与 getTagColorName 等价（旧 API 兼容）', () => {
    expect(getTagColor('v')).toBe(getTagColorName('v'))
  })
})

describe('suggestColorForLabel 语义推荐', () => {
  it.each([
    ['紧急', 'red'],
    ['已完成', 'green'],
    ['进行中', 'processing'],
    ['高优先级', 'orange'],
  ])('%s 推荐 %s', (label, expected) => {
    expect(suggestColorForLabel(label)).toBe(expected)
  })

  it('"低风险" 同时命中"低"(blue)与"低风险"(green)同分规则，先出现的 blue 胜出', () => {
    expect(suggestColorForLabel('低风险')).toBe('blue')
  })

  it('"优先级 1" 命中含"优先"的 orange 规则（red 规则仅匹配"最高优先级"）', () => {
    expect(suggestColorForLabel('优先级 1')).toBe('orange')
  })

  it('数字等级映射（"等级 1" 红 → "等级 5" 绿）', () => {
    expect(suggestColorForLabel('等级 1')).toBe('red')
    expect(suggestColorForLabel('等级 5')).toBe('green')
  })

  it('带数字但无等级语境且文本超长时不走数字等级映射', () => {
    // hasCtx=false 且 text.length>10 → 数字路径不生效（避开"是/无/中"等单字关键词）
    expect(suggestColorForLabel('甲乙丙丁戊己庚辛壬癸99')).toBeNull()
  })

  it('带等级语境但数字超出映射表时返回 null', () => {
    // hasCtx=true 且 text.length>10，数字 999 不在 1-5 映射表内
    expect(suggestColorForLabel('前缀等级后缀很长没有关键词999')).toBeNull()
  })

  it('字母等级映射（A 绿 → F 红）', () => {
    expect(suggestColorForLabel('A 级')).toBe('green')
    expect(suggestColorForLabel('F')).toBe('red')
  })

  it('无匹配返回 null', () => {
    expect(suggestColorForLabel('甲乙丙丁戊己')).toBeNull()
  })

  it('空标签返回 null', () => {
    expect(suggestColorForLabel('')).toBeNull()
  })

  it('大小写与首尾空白不敏感', () => {
    expect(suggestColorForLabel('  URGENT  ')).toBe('red')
  })
})

describe('resolveTagColor 三路径优先级', () => {
  it('路径 1：options 中已存 color 优先于语义推荐', () => {
    const options = [{ label: '紧急', value: 'urgent', color: 'purple' }]
    // 语义上"紧急"是 red，但已存颜色 purple 优先
    expect(resolveTagColor('紧急', options)).toBe('purple')
  })

  it('路径 1：options 中无 color 字段时不命中，继续走后续路径', () => {
    const options = [{ label: '未分类', value: 'misc' }]
    // 无已存色、无语义 → fallback 调色板
    expect(resolveTagColor('未分类', options, 0)).toBe('blue')
  })

  it('路径 1：string[] 形式的 options 命中同值即跳出（该路径不返回色名）', () => {
    // 纯字符串选项无 color 可取，跳出循环后走语义/调色板路径
    const options = ['紧急', '其他']
    expect(resolveTagColor('紧急', options)).toBe('red')
  })

  it('路径 2：无已存色时语义推荐生效', () => {
    expect(resolveTagColor('紧急', undefined)).toBe('red')
  })

  it('路径 3：语义未命中按 options 长度选分级调色板循环', () => {
    const unmatched = '玄学词' // 不含语义关键词、不含数字
    // 5 个选项 → 核心 5 色板，index 循环
    const opts5 = ['a', 'b', 'c', 'd', 'e']
    expect(resolveTagColor(unmatched, opts5, 0)).toBe('blue')
    expect(resolveTagColor(unmatched, opts5, 5)).toBe('blue') // 5 % 5 循环回首色
    expect(resolveTagColor(unmatched, opts5, 3)).toBe('purple')
    // 8 个选项 → 扩展 8 色板
    const opts8 = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    expect(resolveTagColor(unmatched, opts8, 6)).toBe('gold')
    // 13 个选项 → 完整 13 色板
    const opts13 = Array.from({ length: 13 }, (_, i) => `o${i}`)
    expect(resolveTagColor(unmatched, opts13, 12)).toBe('pink')
  })

  it('无 options 时按 0 长度走核心色板', () => {
    expect(resolveTagColor('玄学词')).toBe('blue')
  })

  it('空值返回 default', () => {
    expect(resolveTagColor('')).toBe('default')
    expect(resolveTagColor('   ')).toBe('default')
  })
})

describe('__resetTagColorCache 缓存重置', () => {
  it('重置后语义缓存失效但推荐结果稳定（纯函数性质）', () => {
    expect(suggestColorForLabel('紧急')).toBe('red')
    __resetTagColorCache()
    expect(suggestColorForLabel('紧急')).toBe('red')
  })

  it('重置后 hash 缓存失效但配色稳定（同值同色）', () => {
    const before = getTagColorName('稳定值')
    __resetTagColorCache()
    expect(getTagColorName('稳定值')).toBe(before)
  })
})

describe('ANTD_COLOR_NAMES 导出完整性', () => {
  it('共 31 项（13 基础 + 13 inverse + 5 status）', () => {
    expect(ANTD_COLOR_NAMES).toHaveLength(31)
  })

  it('包含全部 status 色与 inverse 变体', () => {
    for (const c of ['success', 'processing', 'error', 'default', 'warning', 'blue-inverse', 'gold-inverse']) {
      expect(ANTD_COLOR_NAMES).toContain(c)
    }
  })
})
