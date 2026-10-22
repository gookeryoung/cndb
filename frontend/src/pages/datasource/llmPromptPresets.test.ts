/** 推荐提示词预设校验：5 组齐全、字段合法、占位符符合后端模板语法.
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

const REQUIRED_NAMES = ['每日新闻摘要', '城市天气预报', '股票 / 基金行情快照', '电商竞品价格监控', '行业政策公告跟踪']

describe('LLM_PROMPT_PRESETS', () => {
  it('提供 5 组场景且 id 唯一', () => {
    expect(LLM_PROMPT_PRESETS).toHaveLength(5)
    expect(new Set(LLM_PROMPT_PRESETS.map(p => p.id)).size).toBe(5)
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

  it('字段名使用英文 snake_case，幂等键是建议字段的子集', () => {
    const snakeCase = /^[a-z][a-z0-9_]*$/
    for (const preset of LLM_PROMPT_PRESETS) {
      for (const field of preset.target_fields) {
        expect(field, `${preset.name} 的字段 ${field}`).toMatch(snakeCase)
      }
      for (const key of preset.match_keys) {
        expect(key, `${preset.name} 的幂等键 ${key}`).toMatch(snakeCase)
        expect(preset.target_fields, `${preset.name} 的幂等键 ${key} 应在建议字段里`).toContain(key)
      }
      // 提示词里要逐字段点名，模型才知道输出什么
      for (const field of preset.target_fields) {
        expect(preset.prompt, `${preset.name} 未在提示词里说明字段 ${field}`).toContain(field)
      }
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
})
