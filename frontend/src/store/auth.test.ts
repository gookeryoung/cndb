/** store/auth 单元测试 —— login/register/logout/refresh 与 persist 边界 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'
import { authApi } from '@/api'
import { clearToken, getToken, setToken } from '@/api/client'

// mock 掉 @/api 的 authApi，避免真实网络
vi.mock('@/api', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    me: vi.fn(),
  },
}))

const mockedAuthApi = vi.mocked(authApi)

const fakeUser = { id: 1, username: 'alice', email: 'a@x.com' }
const fakeUserResponse = { ...fakeUser, is_superuser: false, is_active: true, created_at: '' }

beforeEach(() => {
  vi.clearAllMocks()
  clearToken()
  useAuthStore.setState({ user: null, token: null, loading: false })
})

describe('login', () => {
  it('成功后设置 token 与 user，并把 token 写入 localStorage', async () => {
    mockedAuthApi.login.mockResolvedValueOnce({ access_token: 'tok-login' } as never)
    mockedAuthApi.me.mockResolvedValueOnce(fakeUserResponse as never)

    await useAuthStore.getState().login({ login: 'alice', password: 'pw' })

    expect(useAuthStore.getState().token).toBe('tok-login')
    expect(useAuthStore.getState().user).toEqual(fakeUserResponse)
    expect(getToken()).toBe('tok-login')
  })

  it('login 失败时异常向上抛出且不设置状态', async () => {
    mockedAuthApi.login.mockRejectedValueOnce(new Error('密码错误'))
    await expect(useAuthStore.getState().login({ login: 'alice', password: 'bad' })).rejects.toThrow(
      '密码错误',
    )
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
  })
})

describe('register', () => {
  it('成功后自动登录：register + login + me 链式调用', async () => {
    mockedAuthApi.register.mockResolvedValueOnce(fakeUserResponse as never)
    mockedAuthApi.login.mockResolvedValueOnce({ access_token: 'tok-reg' } as never)

    const u = await useAuthStore.getState().register({ username: 'alice', password: 'pw', email: 'a@x.com' })

    expect(u).toEqual(fakeUserResponse)
    expect(mockedAuthApi.login).toHaveBeenCalledWith({ login: 'alice', password: 'pw' })
    expect(useAuthStore.getState().token).toBe('tok-reg')
    expect(useAuthStore.getState().user).toEqual(fakeUserResponse)
  })
})

describe('logout', () => {
  it('清理 token 与 user', async () => {
    setToken('tok-out')
    useAuthStore.setState({ token: 'tok-out', user: fakeUserResponse as never })

    useAuthStore.getState().logout()

    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(getToken()).toBeNull()
  })
})

describe('refresh 三分支', () => {
  it('无 token：直接置 loading=false、user/token 为 null', async () => {
    useAuthStore.setState({ token: null, user: null, loading: true })
    await useAuthStore.getState().refresh()
    const s = useAuthStore.getState()
    expect(s.loading).toBe(false)
    expect(s.user).toBeNull()
    expect(s.token).toBeNull()
    expect(mockedAuthApi.me).not.toHaveBeenCalled()
  })

  it('有 token 且 me 成功：user 就位、loading=false', async () => {
    setToken('tok-ok')
    useAuthStore.setState({ token: 'tok-ok', loading: true })
    mockedAuthApi.me.mockResolvedValueOnce(fakeUserResponse as never)

    await useAuthStore.getState().refresh()

    const s = useAuthStore.getState()
    expect(s.user).toEqual(fakeUserResponse)
    expect(s.loading).toBe(false)
    expect(s.token).toBe('tok-ok')
  })

  it('有 token 但 me 失败：清 token、清 user、loading=false', async () => {
    setToken('tok-bad')
    useAuthStore.setState({ token: 'tok-bad', loading: true })
    mockedAuthApi.me.mockRejectedValueOnce(new Error('401'))

    await useAuthStore.getState().refresh()

    const s = useAuthStore.getState()
    expect(s.user).toBeNull()
    expect(s.token).toBeNull()
    expect(s.loading).toBe(false)
    expect(getToken()).toBeNull()
  })
})

describe('persist 持久化边界', () => {
  it('partialize 仅持久化 token（localStorage 不含 user/loading）', async () => {
    mockedAuthApi.login.mockResolvedValueOnce({ access_token: 'tok-persist' } as never)
    mockedAuthApi.me.mockResolvedValueOnce(fakeUserResponse as never)

    await useAuthStore.getState().login({ login: 'alice', password: 'pw' })

    const raw = localStorage.getItem('cndb_auth')
    expect(raw).toBeTruthy()
    const persisted = JSON.parse(raw!) as { state: { token: string | null } }
    expect(persisted.state.token).toBe('tok-persist')
    expect(persisted.state).not.toHaveProperty('user')
    expect(persisted.state).not.toHaveProperty('loading')
  })

  it('logout 后持久化里的 token 同步为 null', () => {
    setToken('tok-x')
    useAuthStore.setState({ token: 'tok-x' })
    useAuthStore.getState().logout()
    const persisted = JSON.parse(localStorage.getItem('cndb_auth')!) as { state: { token: string | null } }
    expect(persisted.state.token).toBeNull()
  })
})

describe('expired 标志生命周期', () => {
  it('初始 expired=false，login 后仍为 false', async () => {
    expect(useAuthStore.getState().expired).toBe(false)
    mockedAuthApi.login.mockResolvedValueOnce({ access_token: 'tok' } as never)
    mockedAuthApi.me.mockResolvedValueOnce(fakeUserResponse as never)
    await useAuthStore.getState().login({ login: 'a', password: 'b' })
    expect(useAuthStore.getState().expired).toBe(false)
  })

  it('logout 重置 expired 为 false（主动退出 ≠ 过期）', () => {
    useAuthStore.setState({ expired: true })
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().expired).toBe(false)
  })

  it('notifyExpired 清 token + user，并置 expired=true', () => {
    setToken('tok-expired')
    useAuthStore.setState({ token: 'tok-expired', user: fakeUserResponse as never, expired: false })

    useAuthStore.getState().notifyExpired()

    const s = useAuthStore.getState()
    expect(getToken()).toBeNull()
    expect(s.token).toBeNull()
    expect(s.user).toBeNull()
    expect(s.expired).toBe(true)
  })

  it('refresh 失败时置 expired=true', async () => {
    setToken('tok-bad')
    useAuthStore.setState({ token: 'tok-bad', loading: true, expired: false })
    mockedAuthApi.me.mockRejectedValueOnce(new Error('401'))

    await useAuthStore.getState().refresh()

    expect(useAuthStore.getState().expired).toBe(true)
  })
})
