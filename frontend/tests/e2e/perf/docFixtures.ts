/** 性能用例共用的种子文档导航（ADR 0116 C1 / C6）.
 *
 * 种子工作区根目录只有草稿，已发布文档都在文件夹里；草稿默认进编辑态，会在打开时
 * 加载编辑器 chunk。这里先按 tree API 找到「已发布文档 + 其父文件夹」，再用
 * `?parent=&status=published` 深链进入，保证用例测的是查看态。
 */

import type { Page } from '@playwright/test'

interface TreeDoc {
  id: number
  status?: string
  parent_id?: number | null
}

export async function publishedDocUrl(page: Page, wid: number): Promise<string> {
  const hit = await page.evaluate(async (workspaceId) => {
    const token = localStorage.getItem('cndb_access_token') ?? ''
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents/tree`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return null
    const body = (await res.json()) as { items?: TreeDoc[] }
    const tree = body.items ?? []
    return (
      tree.find((node) => node.status === "published" && node.parent_id != null) ??
      tree.find((node) => node.status === "published") ??
      null
    )
  }, wid)
  if (!hit) throw new Error("种子数据没有已发布文档，无法验证查看态")
  const parent = hit.parent_id != null ? `&parent=${hit.parent_id}` : ""
  return `/w/${wid}/documents?status=published${parent}`
}
