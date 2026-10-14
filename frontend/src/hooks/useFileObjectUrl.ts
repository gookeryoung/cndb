/** 工作区附件「带鉴权」URL —— 经 axios 取 blob 再转 object URL.
 *
 * 背景：附件预览/下载端点 `GET /api/v1/workspaces/{wid}/files/{file_key}`
 * 要求 `Authorization: Bearer <jwt>`，而浏览器对 `<img src>` / `<a href>`
 * 发出的请求无法携带自定义请求头。认证开启（AUTH_ENABLED 且非 LOCAL_MODE）
 * 时，直接拼 URL 会得到 403，浏览器表现为「图片裂开」。
 *
 * 解决：统一改为用 axios（拦截器自动附 token）拉取 blob，再交给 `<img>`/`<a>`。
 * 与页面里既有的「下载类接口 responseType:'blob'」模式一致。
 *
 * 缓存：file_key 是不可变 uuid，同一 (wid, file_key, inline) 只请求一次；
 * 解析出的 object URL 会话内复用（避免虚拟滚动反复挂载/卸载时重复拉取）。
 * 失败不缓存，允许后续重试。
 */

import { useEffect, useState } from 'react'
import api from '@/api/client'

export type FileId = number | string | undefined | null

const _urlCache = new Map<string, string>()
const _inflight = new Map<string, Promise<string>>()

function _cacheKey(wid: number | string, fileKey: string, inline: boolean): string {
  return `${wid}:${fileKey}:${inline ? 'i' : 'd'}`
}

function _load(wid: number | string, fileKey: string, inline: boolean): Promise<string> {
  const key = _cacheKey(wid, fileKey, inline)
  const cached = _urlCache.get(key)
  if (cached) return Promise.resolve(cached)
  const running = _inflight.get(key)
  if (running) return running

  const pending = api
    .get(`/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}`, {
      params: inline ? { inline: true } : undefined,
      responseType: 'blob',
    })
    .then((res) => {
      const url = URL.createObjectURL(res.data as Blob)
      _urlCache.set(key, url)
      return url
    })
    .finally(() => {
      _inflight.delete(key)
    })
  _inflight.set(key, pending)
  return pending
}

/** 取附件的 object URL；未就绪/失败时 `url` 为 undefined. */
export function useFileObjectUrl(
  wid: FileId,
  fileKey: string | undefined | null,
  inline = true,
): { url: string | undefined; error: boolean } {
  const enabled = wid !== undefined && wid !== null && !!fileKey
  const key = enabled ? _cacheKey(wid as number | string, fileKey as string, inline) : ''

  const [url, setUrl] = useState<string | undefined>(() => (key ? _urlCache.get(key) : undefined))
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!key || wid === undefined || wid === null || !fileKey) {
      setUrl(undefined)
      setError(false)
      return
    }
    const cached = _urlCache.get(key)
    if (cached) {
      setUrl(cached)
      setError(false)
      return
    }
    let alive = true
    setError(false)
    _load(wid, fileKey, inline).then(
      (objectUrl) => {
        if (alive) setUrl(objectUrl)
      },
      () => {
        if (alive) setError(true)
      },
    )
    return () => {
      alive = false
    }
  }, [key, wid, fileKey, inline])

  return { url, error }
}

/** 清空缓存并释放 object URL —— 供测试用例与登出/切换工作区时复用. */
export function resetFileObjectUrls(): void {
  for (const url of _urlCache.values()) {
    try {
      URL.revokeObjectURL(url)
    } catch {
      /* 测试环境可能未实现 revokeObjectURL，忽略 */
    }
  }
  _urlCache.clear()
  _inflight.clear()
}
