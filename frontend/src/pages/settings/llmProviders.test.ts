/** 大模型服务商预设测试 —— 反查与数据完整性（个人设置 → 大模型） */

import { describe, expect, it } from 'vitest'
import { CUSTOM_PROVIDER_ID, LLM_PROVIDERS, findProviderByBaseUrl } from './llmProviders'

describe('大模型服务商预设', () => {
  it('每个服务商都有唯一 id、https 地址与至少一个模型', () => {
    const ids = new Set(LLM_PROVIDERS.map(provider => provider.id))
    expect(ids.size).toBe(LLM_PROVIDERS.length)
    expect(ids.has(CUSTOM_PROVIDER_ID)).toBe(false)

    for (const provider of LLM_PROVIDERS) {
      expect(provider.baseUrl.startsWith('https://')).toBe(true)
      // 地址只到 base_url，不带补全路径，避免和前端自动补 /chat/completions 重复
      expect(provider.baseUrl).not.toContain('/chat/completions')
      expect(provider.baseUrl.endsWith('/')).toBe(false)
      expect(provider.models.length).toBeGreaterThan(0)
      expect(provider.models[0]).toBeTruthy()
    }
  })

  it('按地址反查服务商：忽略末尾斜杠、大小写与空白', () => {
    expect(findProviderByBaseUrl('https://api.deepseek.com')?.id).toBe('deepseek')
    expect(findProviderByBaseUrl('https://api.deepseek.com/')?.id).toBe('deepseek')
    expect(findProviderByBaseUrl('  HTTPS://API.DeepSeek.com//  ')?.id).toBe('deepseek')
    expect(findProviderByBaseUrl('https://dashscope.aliyuncs.com/compatible-mode/v1')?.id).toBe('dashscope')
  })

  it('未命中预设（自定义地址 / 空值）返回 null', () => {
    expect(findProviderByBaseUrl('')).toBeNull()
    expect(findProviderByBaseUrl('   ')).toBeNull()
    expect(findProviderByBaseUrl('https://llm.internal.example.com/v1')).toBeNull()
    // 只到域名层级不算命中，避免把自建网关误判成官方地址
    expect(findProviderByBaseUrl('https://api.deepseek.com/v1')).toBeNull()
  })
})
