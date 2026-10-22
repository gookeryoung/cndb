/** 推荐提示词预设校验：8 组齐全、字段合法、占位符符合后端模板语法.
 *
 * 占位符规则对齐 `src/cndb/plugins/datasource/providers/template.py`：
 * `{name}` 是占位符（缺变量即保存失败），`{{` / `}}` 是字面花括号。
 * 预设里只允许 `{today}`，否则任务保存时会因「模板变量缺失」被后端 400。
 */

import { describe, expect, it } from 'vitest'
import { LLM_PROMPT_PRESETS } from './llmPromptPresets'

/** 与后端 render_text 同口径：返回文本里所有**未转义**的占位符名 */
function collectPlaceholders(text: string): string[] {
  const names: string[] = []
  let index = 0
  while (index < text.length) {
    const char = text[index]
    if (char === '{') {
      if (text.startsWith('{{', index)) {
        index += 2
        continue
      }
      const close = text.indexOf('}', index + 1)
      if (close < 0) throw new Error(`模板占位符未闭合: ${text.slice(index, index + 40)}`)
      names.push(text.slice(index + 1, close).trim())
      index = close + 1
      continue
    }
    if (char === '}') {
      if (text.startsWith('}}', index)) {
        index += 2
        continue
      }
      throw new Error(`模板出现未转义的 '}': ${text.slice(index, index + 40)}`)
    }
    index += 1
  }
  return names
}

const REQUIRED_NAMES = [
  '每日新闻摘要',
  '城市天气预报',
  '股票 / 基金行情快照',
  '电商竞品价格监控',
  '行业政策公告跟踪',
  '商业航天新闻动态',
  '美食推荐做法',
  '国际形势发展动态',
]

describe('LLM_PROMPT_PRESETS', () => {
  it('提供 8 组场景且 id 唯一', () => {
    expect(LLM_PROMPT_PRESETS).toHaveLength(8)
    expect(new Set(LLM_PROMPT_PRESETS.map(p => p.id)).size).toBe(8)
    expect(LLM_PROMPT_PRESETS.map(p => p.name)).toEqual(REQUIRED_NAMES)
  })

  it('每组都有名称 / 说明 / 建议字段 / 建议幂等键 / 提示词', () => {
    for (const preset of LLM_PROMPT_PRESETS) {
      expect(preset.id.trim()).not.toBe('')
      expect(preset.name.trim()).not.toBe('')
      expect(preset.description.trim()).not.toBe('')
      expect(preset.target_fields.length).toBeGreaterThan(0)
      expect(preset.match_keys.length).toBeGreaterThan(0)
      expect(preset.prompt.trim()).not.toBe('')
    }
  })

  it('字段名用中文（或英文 snake_case），不含空格与标点；幂等键是建议字段的子集', () => {
    // 中文字段是默认口径（2026-10-23），英文 snake_case 仍兼容；两者都不允许空格 / 标点
    const validName = /^[\u4e00-\u9fa5A-Za-z0-9_]+$/
    for (const preset of LLM_PROMPT_PRESETS) {
      for (const field of preset.target_fields) {
        expect(field, `${preset.name} 的字段 ${field}`).toMatch(validName)
      }
      for (const key of preset.match_keys) {
        expect(key, `${preset.name} 的幂等键 ${key}`).toMatch(validName)
        expect(preset.target_fields, `${preset.name} 的幂等键 ${key} 应在建议字段里`).toContain(key)
      }
      // 提示词里要逐字段点名，模型才知道输出什么
      for (const field of preset.target_fields) {
        expect(preset.prompt, `${preset.name} 未在提示词里说明字段 ${field}`).toContain(field)
      }
    }
  })

  it('字段说明为中文口径：8 组预设默认使用中文字段名', () => {
    for (const preset of LLM_PROMPT_PRESETS) {
      expect(preset.prompt, `${preset.name} 缺少中文字段口径说明`).toContain('字段名用中文')
      // 至少一半字段是中文，避免悄悄退回英文命名
      const chineseFields = preset.target_fields.filter(field => /[\u4e00-\u9fa5]/.test(field))
      expect(chineseFields.length, `${preset.name} 中文字段过少`).toBeGreaterThanOrEqual(
        Math.ceil(preset.target_fields.length / 2),
      )
    }
  })

  it('提示词强制 JSON 输出并说明 rows 包裹形式', () => {
    for (const preset of LLM_PROMPT_PRESETS) {
      expect(preset.prompt).toContain('JSON')
      // `{{` / `}}` 是后端模板转义，运行时会还原成 {"rows": ...}
      expect(preset.prompt).toContain('{{"rows"')
      expect(preset.prompt).toContain('行对象数组')
      expect(preset.prompt).toContain('不要输出 Markdown 代码围栏')
    }
  })

  it('提示词占位符合法：只用 {today}，花括号均正确转义', () => {
    for (const preset of LLM_PROMPT_PRESETS) {
      const names = collectPlaceholders(preset.prompt)
      expect(names, `${preset.name} 出现了未预期的占位符`).toEqual(['today'])
      expect(preset.prompt).toContain('{today}')
    }
  })

  it('每日新闻摘要基于已有公开信息输出，不因无法联网返回空数组', () => {
    const news = LLM_PROMPT_PRESETS.find(preset => preset.id === 'daily_news')
    expect(news).toBeDefined()
    expect(news?.prompt).toContain('基于你已掌握的近期公开信息')
    expect(news?.prompt).toContain('不要因为无法联网就返回空数组')
    expect(news?.prompt).toContain('综合整理')
    // url 无法确认时留空，不编造链接
    expect(news?.prompt).toContain('空字符串')
  })

  it('美食推荐做法限制输出规模，避免长文本被 max_tokens 截断', () => {
    const food = LLM_PROMPT_PRESETS.find(preset => preset.id === 'food_recipes')
    expect(food).toBeDefined()
    expect(food?.prompt).toContain('每类 2 道，共 8 道')
    expect(food?.prompt).toContain('每步不超过 60 字')
    expect(food?.prompt).toContain('避免输出过长被截断')
  })

  it('实时数据类预设统一要求标注综合整理 / 留空且不返回空数组', () => {
    const realtimeIds = [
      'market_snapshot',
      'ecommerce_price',
      'policy_tracker',
      'commercial_aerospace',
      'global_affairs',
    ]
    for (const id of realtimeIds) {
      const preset = LLM_PROMPT_PRESETS.find(item => item.id === id)
      expect(preset, `缺少预设 ${id}`).toBeDefined()
      expect(preset?.prompt, `${preset?.name} 未加实时数据真实性约束`).toContain('综合整理')
      expect(preset?.prompt, `${preset?.name} 未要求避免空数组`).toContain('不要返回空数组')
    }
  })
})
