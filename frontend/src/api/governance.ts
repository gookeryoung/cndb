/** 数据治理 API — /api/v1/workspaces/{wid}/tables/{tid}/governance/* */

import api from './client'
import type {
    GovernanceTask, GovernanceTaskStatus,
    GovernanceDetectRequest, GovernanceMergeRequest, GovernanceCleanRequest,
} from './types'

/** 检测报告（后端 task.report JSON 解析结果） */
export interface DetectReport {
    total_rows: number
    duplicate_row_count: number
    group_count: number
    groups: Array<{ member_row_ids: number[]; match_key_values: Record<string, unknown> }>
}

/** 合并报告 */
export interface MergeReport {
    merged_count: number
    skipped: Array<{ group_index: number; reason: string }>
    groups: Array<Record<string, unknown>>
}

/** 清洗报告（preview 与 execute 同构） */
export interface CleanReport {
    mode: 'preview' | 'execute'
    affected: Array<{ action: string; column: string; strategy: string | null; affected_rows: number }>
    samples: Array<Record<string, unknown>>
}

export type GovernanceReport = DetectReport | MergeReport | CleanReport

const base = (wid: number | string, tid: number | string) =>
    `/v1/workspaces/${wid}/tables/${tid}/governance`

export const governanceApi = {
    detect: (wid: number | string, tid: number | string, data: GovernanceDetectRequest) =>
        api.post<GovernanceTask>(`${base(wid, tid)}/detect`, data).then(r => r.data),
    merge: (wid: number | string, tid: number | string, data: GovernanceMergeRequest) =>
        api.post<GovernanceTask>(`${base(wid, tid)}/merge`, data).then(r => r.data),
    clean: (wid: number | string, tid: number | string, data: GovernanceCleanRequest) =>
        api.post<GovernanceTask>(`${base(wid, tid)}/clean`, data).then(r => r.data),
    task: (wid: number | string, tid: number | string, taskId: number | string) =>
        api.get<GovernanceTask>(`${base(wid, tid)}/tasks/${taskId}`).then(r => r.data),
    report: async (wid: number | string, tid: number | string, taskId: number | string): Promise<GovernanceReport | null> => {
        const r = await api.get<{ task_id: number; status: GovernanceTaskStatus; report: GovernanceReport | null }>(
            `${base(wid, tid)}/tasks/${taskId}/report`,
        )
        return r.data.report
    },
}
