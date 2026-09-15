/** 认证接口 —— 对齐后端 /v1/accounts/auth/* + /v1/wechat-auth/login. */
import { request } from './client'

export const authApi = {
  /** 账号密码登录（复用后端已有接口）. */
  login: (login: string, password: string) =>
    request<{ access_token: string; token_type: string }>({
      url: '/v1/accounts/auth/login',
      method: 'POST',
      data: { login, password },
    }),

  /** 微信一键登录 —— 调后端 wechat-auth/login. */
  wechatLogin: (code: string, nickname?: string, avatar_url?: string) =>
    request<{
      access_token: string
      token_type: string
      user: { id: number; username: string; nickname: string; role: string; is_superuser: boolean }
    }>({
      url: '/v1/wechat-auth/login',
      method: 'POST',
      data: { code, nickname, avatar_url },
    }),

  /** 注册新账号. */
  register: (data: {
    username: string
    email?: string | null
    password: string
    nickname?: string
  }) =>
    request<{ id: number; username: string }>({
      url: '/v1/accounts/auth/register',
      method: 'POST',
      data,
    }),

  /** 获取当前用户信息. */
  me: () =>
    request<{
      id: number; username: string; nickname: string; role: string
      is_superuser: boolean; email: string | null
    }>({
      url: '/v1/accounts/auth/me',
    }),
}
