/** 工作区成员名映射 — 问题/修改申请页展示评论作者、事件 actor、提交人.
 *
 * 数据源 workspaceApi.members（queryKey ['workspace-members', wid]）；
 * nickname 优先，回退 username；查不到显示「用户 {id}」。
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import type { ID } from '@/api'

export function useMemberNameMap(wid: string) {
  const { data: members = [] } = useQuery({
    queryKey: ['workspace-members', wid],
    queryFn: () => workspaceApi.members(wid),
    enabled: !!wid,
  })

  return useMemo(() => {
    const map = new Map<string, string>()
    members.forEach((m) => {
      if (m.user) map.set(String(m.user.id), m.user.nickname || m.user.username)
    })
    return map
  }, [members])
}

/** 按 id 取显示名；id 为 null 显示 fallback（默认「系统」） */
export function memberDisplayName(
  map: Map<string, string>,
  id: ID | null | undefined,
  fallback = '系统',
): string {
  if (id === null || id === undefined) return fallback
  return map.get(String(id)) ?? `用户 ${id}`
}
