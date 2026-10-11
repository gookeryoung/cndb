/** 审批流 API — /api/v1/workspaces/{wid}/workflows|approvals（审批流配置 + 审批实例动作） */

import api from './client'
import type {
  ApprovalInstance,
  ApprovalStatus,
  WorkflowDefinition,
  WorkflowListItem,
  WorkflowPayload,
} from './types'

export type ApprovalScope = 'pending_for_me' | 'mine'

export const workflowApi = {
    /** 审批流定义列表 */
    list: (wid: number | string) =>
        api.get<WorkflowListItem[]>(`/v1/workspaces/${wid}/workflows`).then(r => r.data),
    get: (wid: number | string, workflowId: number | string) =>
        api.get<WorkflowDefinition>(`/v1/workspaces/${wid}/workflows/${workflowId}`).then(r => r.data),
    create: (wid: number | string, data: WorkflowPayload) =>
        api.post<WorkflowDefinition>(`/v1/workspaces/${wid}/workflows`, data).then(r => r.data),
    update: (wid: number | string, workflowId: number | string, data: WorkflowPayload) =>
        api.patch<WorkflowDefinition>(`/v1/workspaces/${wid}/workflows/${workflowId}`, data).then(r => r.data),
    remove: (wid: number | string, workflowId: number | string) =>
        api.delete(`/v1/workspaces/${wid}/workflows/${workflowId}`).then(r => r.data),
}

export const approvalApi = {
    /** 审批实例列表：scope=pending_for_me 待我审批 / mine 我提交的 */
    list: (wid: number | string, scope: ApprovalScope, formId?: number | string) =>
        api.get<ApprovalInstance[]>(`/v1/workspaces/${wid}/approvals`, {
            params: { scope, ...(formId !== undefined ? { form_id: formId } : {}) },
        }).then(r => r.data),
    approve: (wid: number | string, instanceId: number | string, comment = '') =>
        api.post<ApprovalInstance>(`/v1/workspaces/${wid}/approvals/${instanceId}/approve`, { comment }).then(r => r.data),
    reject: (wid: number | string, instanceId: number | string, comment = '') =>
        api.post<ApprovalInstance>(`/v1/workspaces/${wid}/approvals/${instanceId}/reject`, { comment }).then(r => r.data),
}

export const APPROVAL_STATUS_TEXT: Record<ApprovalStatus, string> = {
    pending: '待审批',
    approved: '已通过',
    rejected: '已驳回',
}
