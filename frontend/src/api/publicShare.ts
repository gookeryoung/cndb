/** 公开分享 API（免登录）：仅文档游客只读访问使用. */

import api from './client'

/** 分享元信息：标题 + 是否需要密码 */
export interface PublicShareMeta {
  title: string
  has_password: boolean
}

/** 公开文档载荷（后端白名单，仅这三个字段） */
export interface PublicShareDocument {
  title: string
  updated_at: string
  content?: string
}

const base = (token: string) => `/v1/documents/share/${encodeURIComponent(token)}`

export const publicShareApi = {
  meta: (token: string) => api.get<PublicShareMeta>(`${base(token)}/meta`).then(r => r.data),
  content: (token: string) => api.get<PublicShareDocument>(base(token)).then(r => r.data),
  contentWithPassword: (token: string, password: string) =>
    api.post<PublicShareDocument>(base(token), { password }).then(r => r.data),
  /** 正文站内图片地址（免登录）；拼接 file_key 后可直接用于 <img src> */
  fileUrl: (token: string) => `/api${base(token)}/files`,
}

export default publicShareApi
