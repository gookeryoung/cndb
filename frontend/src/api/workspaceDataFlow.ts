/** 工作区数据流程 API（需求 0095）. */

import api from './client'
import type { WorkspaceDataFlow } from './types'

export const workspaceDataFlowApi = {
  /** projectId：项目模式下按项目过滤；单项目可省略（后端自动选中） */
  get: (wid: number | string, projectId?: number | string | null) =>
    api
      .get<WorkspaceDataFlow>(`/v1/workspaces/${wid}/data-flow`, {
        params: projectId ? { project_id: projectId } : undefined,
      })
      .then(r => r.data),
}
