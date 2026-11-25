/** 团队 API — /api/v1/teams/*（ADR 0153 P1） */

import api from './client'
import type {
  Team, TeamCreate, TeamMember, TeamUpdate, TeamWorkspace,
} from './types'

export const teamApi = {
  list: () => api.get<Team[]>('/v1/teams').then(r => r.data),
  create: (data: TeamCreate) => api.post<Team>('/v1/teams', data).then(r => r.data),
  get: (tid: number | string) => api.get<Team>(`/v1/teams/${tid}`).then(r => r.data),
  update: (tid: number | string, data: TeamUpdate) =>
    api.patch<Team>(`/v1/teams/${tid}`, data).then(r => r.data),
  remove: (tid: number | string) => api.delete(`/v1/teams/${tid}`).then(r => r.data),
  members: (tid: number | string) =>
    api.get<TeamMember[]>(`/v1/teams/${tid}/members`).then(r => r.data),
  addMember: (tid: number | string, username: string, role: string) =>
    api.post<TeamMember>(`/v1/teams/${tid}/members`, { username, role }).then(r => r.data),
  updateMember: (tid: number | string, memberId: number | string, role: string) =>
    api.patch<TeamMember>(`/v1/teams/${tid}/members/${memberId}`, { role }).then(r => r.data),
  removeMember: (tid: number | string, memberId: number | string) =>
    api.delete(`/v1/teams/${tid}/members/${memberId}`).then(r => r.data),
  /** 团队下的工作区平铺列表（无树：C1） */
  workspaces: (tid: number | string) =>
    api.get<TeamWorkspace[]>(`/v1/teams/${tid}/workspaces`).then(r => r.data),
}

export default teamApi
