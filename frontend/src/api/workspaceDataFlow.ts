/** 工作区数据流程 API（需求 0095）. */

import api from './client'
import type { WorkspaceDataFlow } from './types'

export const workspaceDataFlowApi = {
  get: (wid: number | string) =>
    api.get<WorkspaceDataFlow>(`/v1/workspaces/${wid}/data-flow`).then(r => r.data),
}
