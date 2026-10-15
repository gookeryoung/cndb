/** 实时事件 → React Query 缓存失效桥.
 *
 * A4 统一事件的 `action` 前缀映射到需要失效的 queryKey 前缀：收到别人的写入事件后，
 * 当前页面的列表/详情会自动刷新，无需手动 F5 —— 这是"实时协作"里最实用的一层。
 *
 * 纯函数实现，便于单测；不含 React 依赖。
 */

/** action 前缀 → queryKey 前缀列表（顺序即失效顺序，互不影响） */
const ACTION_TO_QUERY_KEYS: Array<[string, string[][]]> = [
  ['record.', [['table-records'], ['row-audit'], ['table-views']]],
  ['document.', [['documents'], ['document'], ['document-tree'], ['document-recent']]],
  ['user.', [['admin-users'], ['admin-user-audit']]],
  ['issue.', [['issues'], ['document-issues']]],
  ['change_request.', [['change-requests']]],
  ['import.', [['import-tasks']]],
  ['workspace.', [['workspaces'], ['workspace-members']]],
  // 认证类事件（登录/登出/改密）不涉及列表缓存，主动失效反而会造成无谓请求
  ['auth.', []],
]

/** 返回某事件动作需要失效的 queryKey 前缀（可能为空数组） */
export function queryKeysForAction(action: string): string[][] {
  const hit = ACTION_TO_QUERY_KEYS.find(([prefix]) => action === prefix || action.startsWith(prefix))
  return hit ? hit[1] : []
}

/** 该动作是否值得刷新界面（用于决定是否弹轻提示） */
export function isRefreshableAction(action: string): boolean {
  return queryKeysForAction(action).length > 0
}

export const EVENT_REFRESH_PREFIXES = ACTION_TO_QUERY_KEYS
