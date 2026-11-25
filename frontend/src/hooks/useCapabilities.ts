/** 工作区能力位 Hook（ADR 0153 P0）.
 *
 * 前端门控的唯一数据源：替代散落的 `current_user_role === 'owner' | 'editor'` 判断。
 * 判定语义（含团队层与可见性）全部在后端 `resolve_capabilities`，前端只消费结果，
 * 不在客户端重算「谁能做什么」——避免后端收紧后前端仍放行（I6 单一判定）。
 *
 * 用法：
 * ```tsx
 * const { can, dataRole, isLoading } = useCapabilities(wid)
 * const canEdit = can('EDIT_SETTINGS')
 * ```
 *
 * 加载期与失败一律返回「无能力」（fail-closed），不按角色猜。
 */

import { useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { workspaceApi } from '@/api'
import type { WorkspaceCapabilities, WorkspaceCapability, WorkspaceRole } from '@/api'

export interface UseCapabilitiesResult {
  /** 能力位载荷；未加载 / 失败时为 null */
  capabilities: WorkspaceCapabilities | null
  /** 数据面角色（非成员为 null） */
  dataRole: WorkspaceRole | null
  /** 团队角色（P0 恒为 null） */
  teamRole: string | null
  /** 权限来源归因（可展示「你为什么能做什么」） */
  sources: Record<string, string>
  /** 是否拥有某能力位（加载期 / 失败一律 false） */
  can: (capability: WorkspaceCapability) => boolean
  isLoading: boolean
}

export function useCapabilities(wid: string | number | null | undefined): UseCapabilitiesResult {
  const { data, isLoading } = useQuery<WorkspaceCapabilities>({
    queryKey: ['workspace-capabilities', wid],
    queryFn: () => workspaceApi.capabilities(wid as string | number),
    enabled: !!wid,
    // 能力位随成员变更而变，但变更会失效工作区列表缓存；页面内不宜长期缓存
    staleTime: 30_000,
  })

  const can = useCallback(
    (capability: WorkspaceCapability) => !!data?.capabilities?.includes(capability),
    [data],
  )

  return {
    capabilities: data ?? null,
    dataRole: data?.data_role ?? null,
    teamRole: data?.team_role ?? null,
    sources: data?.sources ?? {},
    can,
    isLoading,
  }
}

export default useCapabilities
