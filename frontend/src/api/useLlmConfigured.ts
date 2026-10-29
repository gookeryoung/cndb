/** 全局共享的「大模型是否已配置」hook — 需求 0069.
 *
 * 复用 `LlmConfigPanel` 的 `['llm-config']` queryKey 与缓存：设置页保存 / 清除 Key
 * 后缓存即时更新，各页面 AI 入口随 `configured` 即时出现或消失，无需整页刷新。
 *
 * 语义：仅当接口返回 `configured === true` 才算已配置；查询加载中按未配置处理
 * （先隐藏、加载完成后再显示），接口失败同样按未配置处理（AI 入口隐藏属安全降级）。
 */

import { useQuery } from '@tanstack/react-query'

import { llmApi } from './llm'

export function useLlmConfigured(): boolean {
  const query = useQuery({
    queryKey: ['llm-config'],
    queryFn: llmApi.get,
    staleTime: 300_000,
    retry: false,
  })
  return query.data?.configured === true
}
