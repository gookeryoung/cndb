/** documentSearch 纯函数测试 —— 查找 / 替换. */

import { describe, expect, it } from 'vitest'

import { findMatches, matchOrdinal, nextMatchIndex, replaceAllMatches, replaceMatch } from './documentSearch'

describe('findMatches', () => {
  it('空查询返回空数组', () => {
    expect(findMatches('abc', '')).toEqual([])
  })

  it('默认不区分大小写', () => {
    expect(findMatches('Abc ABC abc', 'abc')).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 7 },
      { start: 8, end: 11 },
    ])
  })

  it('区分大小写时只命中完全一致', () => {
    expect(findMatches('Abc ABC abc', 'ABC', { caseSensitive: true })).toEqual([{ start: 4, end: 7 }])
  })

  it('不产生重叠匹配（aaaa 查 aa 得 2 处）', () => {
    expect(findMatches('aaaa', 'aa')).toEqual([{ start: 0, end: 2 }, { start: 2, end: 4 }])
  })

  it('中文与多字符匹配', () => {
    expect(findMatches('文档管理：文档树与文档编辑', '文档')).toHaveLength(3)
  })
})

describe('nextMatchIndex', () => {
  const matches = findMatches('a b a b a', 'a') // 0, 4, 8

  it('从光标向后找第一个匹配', () => {
    expect(nextMatchIndex(matches, 0)).toBe(0)
    expect(nextMatchIndex(matches, 1)).toBe(1)
    expect(nextMatchIndex(matches, 5)).toBe(2)
  })

  it('向后越界时环绕到第一个', () => {
    expect(nextMatchIndex(matches, 9)).toBe(0)
  })

  it('方向 -1 从光标向前找，越界环绕到最后一个', () => {
    expect(nextMatchIndex(matches, 8, -1)).toBe(1)
    expect(nextMatchIndex(matches, 0, -1)).toBe(2)
  })

  it('无匹配返回 -1', () => {
    expect(nextMatchIndex([], 3)).toBe(-1)
  })
})

describe('replaceMatch', () => {
  it('替换单个匹配并返回替换后光标', () => {
    const [m] = findMatches('前 甲 后', '甲')
    // 「甲」位于偏移 2，替换为「乙丙」后光标落在 4
    expect(replaceMatch('前 甲 后', m!, '乙丙')).toEqual({ value: '前 乙丙 后', caret: 4 })
  })
})

describe('replaceAllMatches', () => {
  it('全部替换并返回处数', () => {
    expect(replaceAllMatches('aXbXc', 'X', '-')).toEqual({ value: 'a-b-c', count: 2 })
  })

  it('替换文本中的 $ 按字面量处理（不解释反向引用）', () => {
    expect(replaceAllMatches('a b a', 'a', '$1')).toEqual({ value: '$1 b $1', count: 2 })
  })

  it('无匹配时原样返回且 count=0', () => {
    expect(replaceAllMatches('abc', 'z', 'y')).toEqual({ value: 'abc', count: 0 })
  })

  it('区分大小写时只替换完全一致的匹配', () => {
    expect(replaceAllMatches('A a', 'A', 'x', { caseSensitive: true })).toEqual({ value: 'x a', count: 1 })
  })

  it('替换为空串即删除匹配', () => {
    expect(replaceAllMatches('甲乙丙', '乙', '')).toEqual({ value: '甲丙', count: 1 })
  })
})

describe('matchOrdinal', () => {
  const matches = findMatches('a b a', 'a')

  it('光标落在匹配内返回其下标', () => {
    expect(matchOrdinal(matches, 0)).toBe(0)
    expect(matchOrdinal(matches, 4)).toBe(1)
  })

  it('光标不在任何匹配内返回 -1', () => {
    expect(matchOrdinal(matches, 2)).toBe(-1)
  })
})
