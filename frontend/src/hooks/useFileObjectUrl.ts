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

function _cacheKey(wid: number | string, fileKey: string, inline: boolean, thumb: number): string {
  return `${wid}:${fileKey}:${inline ? 'i' : 'd'}:t${thumb}`
}

function _load(wid: number | string, fileKey: string, inline: boolean, thumb: number): Promise<string> {
  const key = _cacheKey(wid, fileKey, inline, thumb)
  const cached = _urlCache.get(key)
  if (cached) return Promise.resolve(cached)
  const running = _inflight.get(key)
  if (running) return running

  const params: Record<string, unknown> = {}
  if (inline) params.inline = true
  if (thumb) params.thumb = thumb
  const pending = api
    .get(`/v1/workspaces/${wid}/files/${encodeURIComponent(fileKey)}`, {
      params: Object.keys(params).length > 0 ? params : undefined,
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

/** 取附件的 object URL；未就绪/失败时 `url` 为 undefined.
 *
 * ``options.thumb``：请求服务端缩略图（最长边 N，32-1024），用于列表/瓦片；
 * ``options.enabled=false``：暂不请求（预览打开时再懒加载原图）。
 */
export function useFileObjectUrl(
  wid: FileId,
  fileKey: string | undefined | null,
  inline = true,
  options?: { thumb?: number; enabled?: boolean },
): { url: string | undefined; error: boolean } {
  const thumb = options?.thumb ?? 0
  const enabled = options?.enabled !== false && wid !== undefined && wid !== null && !!fileKey
  const key = enabled ? _cacheKey(wid as number | string, fileKey as string, inline, thumb) : ''

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
    _load(wid, fileKey, inline, thumb).then(
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
  }, [key, wid, fileKey, inline, thumb])

  return { url, error }
}

/** 以 Promise 方式取附件 object URL —— 供非 React 渲染场景复用（如编辑器图片 widget）.
 *
 * 与 hook 共享同一份缓存与去重表：编辑器里先渲染过的图片，预览侧命中缓存不重复请求。
 */
export function loadFileObjectUrl(
  wid: number | string,
  fileKey: string,
  inline = true,
  thumb = 0,
): Promise<string> {
  return _load(wid, fileKey, inline, thumb)
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
