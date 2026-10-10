/** 系统信息 API — /api/v1/system/*（登录即可，普通用户可访问） */

import api from './client'

/** 系统基本信息（不含数据库路径等管理敏感字段，对应后端 SystemAbout schema） */
export interface SystemAbout {
  app_name: string
  app_version: string
  auth_enabled: boolean
  timezone: string
  server_time: string
}

export const systemApi = {
  /** 获取系统基本信息（应用名/版本/鉴权开关/时区/服务器时间） */
  about: () => api.get<SystemAbout>('/v1/system/about').then(r => r.data),
}
