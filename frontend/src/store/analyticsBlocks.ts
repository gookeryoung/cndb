/** 数据分析页区块启用状态 store — localStorage 持久化.
 *
 * 控制分析页三段带状区块（可视化 / 分组汇总 / 计算模板）是否渲染，
 * 按「用户 + 本机」记忆：状态以用户 id 为键存储，同一浏览器内不同
 * 账号各自记忆；未登录（拿不到用户 id）时落到 'anon' 键。
 *
 * 与 `@/store/docSettings` 同模式：zustand persist + 消费者按字段订阅。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 区块键：图表（可视化）、汇总（分组汇总）、公式（计算模板） */
export type AnalyticsBlockKey = 'chart' | 'summary' | 'formula'
export type AnalyticsBlocks = Record<AnalyticsBlockKey, boolean>

/** 默认仅启用可视化区块 */
export const DEFAULT_ANALYTICS_BLOCKS: AnalyticsBlocks = {
  chart: true,
  summary: false,
  formula: false,
}

interface AnalyticsBlocksState {
  /** 用户 id（字符串）→ 区块启用状态；未记录的用户回落到默认值 */
  byUser: Record<string, AnalyticsBlocks>
  /** 更新指定用户的区块开关（部分字段合并并持久化） */
  setBlocks: (userId: string, patch: Partial<AnalyticsBlocks>) => void
}

export const useAnalyticsBlocksStore = create<AnalyticsBlocksState>()(
  persist(
    (set) => ({
      byUser: {},

      setBlocks: (userId, patch) =>
        set((state) => ({
          byUser: {
            ...state.byUser,
            [userId]: { ...DEFAULT_ANALYTICS_BLOCKS, ...state.byUser[userId], ...patch },
          },
        })),
    }),
    {
      name: 'cndb_analytics_blocks',
      partialize: (state) => ({ byUser: state.byUser }),
    },
  ),
)
