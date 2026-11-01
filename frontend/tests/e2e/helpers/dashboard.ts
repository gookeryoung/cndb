/** E2E dashboard 共享辅助（ADR 0077）：seed 定位、画布视图 CRUD 与直达链接.
 *
 * 导出与只读分享用例需要在隔离视图上操作（避免并发改写 seed「销售画布」），
 * 这里收敛「建/删视图」「构造深链」「打开画布并等待就绪」三件事。
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { apiCall } from "./api";

export const DASHBOARD_WS_NAME = "某企业销售管理";
export const DASHBOARD_TABLE_NAME = "电商销售";

export interface DashboardViewItem {
  id: number;
  name: string;
  view_type: string;
  visibility?: string;
  view_options: Record<string, unknown> | null;
}

/** 统一的空查询口径（与 normalizeQuery 默认值一致） */
export function emptyQuery(): Record<string, unknown> {
  return { filters: [], filter_logic: "AND", sortings: [] };
}

/** 列表读取失败直接抛出，避免用例在空视图列表上做无意义断言 */
export async function listViews(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
): Promise<DashboardViewItem[]> {
  const res = await apiCall(request, token, "get", `/workspaces/${wid}/tables/${tid}/views`);
  if (res.status !== 200) throw new Error(`读取视图失败：${res.status}`);
  return res.body as DashboardViewItem[];
}

/** 创建 dashboard 视图（默认 private 档），返回落库后的视图 */
export async function createDashboardView(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  name: string,
  viewOptions: Record<string, unknown>,
): Promise<DashboardViewItem> {
  const res = await apiCall(request, token, "post", `/workspaces/${wid}/tables/${tid}/views`, {
    name,
    view_type: "dashboard",
    view_options: viewOptions,
  });
  if (res.status !== 201) throw new Error(`创建视图失败：${res.status} ${JSON.stringify(res.body)}`);
  return res.body as DashboardViewItem;
}

/** 删除视图；404 视为已清理（并发 / 重试用例） */
export async function deleteView(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  vid: number,
): Promise<void> {
  const res = await apiCall(request, token, "delete", `/workspaces/${wid}/tables/${tid}/views/${vid}`);
  if (res.status !== 204 && res.status !== 404) throw new Error(`删除视图失败：${res.status}`);
}

/** 一键分享给指定成员（viewer），供只读链接用例设置前置权限 */
export async function shareViewWithMember(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  vid: number,
  userId: number,
): Promise<void> {
  const res = await apiCall(request, token, "post", `/workspaces/${wid}/tables/${tid}/views/${vid}/visibility`, {
    visibility: "shared",
    members: [{ user_id: userId, role: "viewer" }],
  });
  if (res.status !== 200) throw new Error(`设置共享失败：${res.status} ${JSON.stringify(res.body)}`);
}

/** 画布直达链接（`present` 与 `copyDashboardShareLink` 同构） */
export function dashboardDeepLink(
  wid: number,
  tid: number,
  vid: number,
  opts: { present?: boolean } = {},
): string {
  const params = new URLSearchParams({ view: String(vid), mode: "dashboard" });
  if (opts.present) params.set("present", "1");
  return `/w/${wid}/tables/${tid}?${params.toString()}`;
}

/** 打开画布并等待画布主体渲染完成 */
export async function openDashboard(
  page: Page,
  wid: number,
  tid: number,
  vid: number,
  opts: { present?: boolean } = {},
): Promise<void> {
  await page.goto(dashboardDeepLink(wid, tid, vid, opts));
  await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 10_000 });
}
