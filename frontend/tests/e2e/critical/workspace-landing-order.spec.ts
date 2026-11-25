/**
 * Critical — 进入工作区的默认落地页顺序可按用户自定义（需求 0161）.
 *
 * 验收链路：同一工作区（数据表 + 文档 + 设计）下，
 * 1) 默认偏好时 `/w/:wid` 落 `/tables`（存量行为不变）；
 * 2) 偏好改为「文档 → 数据表 → 设计」后，`/w/:wid` 落 `/documents`；
 * 3) 只返回两个模块的全序时后端补尾成三模块完整排列（归一化口径）。
 *
 * 为什么必须 E2E：落地段判定在真实路由 + 真实偏好接口 + 个人设置写入链路上，
 * jsdom 单测覆盖不到“刷新后偏好仍生效”的持久化语义。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken } from "../helpers/api";

test.describe.configure({ timeout: 90_000 });

let wid: number;
let token: string;
const stamp = Date.now();
/** 默认落地顺序：afterAll 必须复位，避免污染其他用例的落地断言 */
const DEFAULT_ORDER = ["tables", "documents", "design"];

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  const created = await apiCall(request, token, "post", "/workspaces", {
    name: `落地页顺序回归 ${stamp}`,
    modules: ["tables", "documents", "design"],
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  wid = (created.body as { id: number }).id;
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  await apiCall(request, token, "put", "/accounts/preferences/landing-order", {
    landing_order: DEFAULT_ORDER,
  }).catch(() => undefined);
  if (wid) await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
});

test.describe("进入工作区的默认落地页顺序", () => {
  test("默认数据表优先，改为文档优先后落地文档页", async ({ page, request }) => {
    // 先复位默认，避免上一条失败用例遗留顺序
    await apiCall(request, token, "put", "/accounts/preferences/landing-order", {
      landing_order: DEFAULT_ORDER,
    });

    await page.goto(`/w/${wid}`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/tables`));

    const put = await apiCall(request, token, "put", "/accounts/preferences/landing-order", {
      landing_order: ["documents", "tables", "design"],
    });
    expect(put.status).toBe(200);
    expect((put.body as { landing_order: string[] }).landing_order).toEqual([
      "documents",
      "tables",
      "design",
    ]);

    // 刷新后偏好仍生效（per-user 持久化，不是本地内存）
    await page.reload();
    await page.goto(`/w/${wid}`);
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents`));
  });

  test("偏好缺项时归一为三模块完整排列（尾补默认序）", async ({ request }) => {
    const put = await apiCall(request, token, "put", "/accounts/preferences/landing-order", {
      landing_order: ["documents"],
    });
    expect(put.status).toBe(200);
    expect((put.body as { landing_order: string[] }).landing_order).toEqual([
      "documents",
      "tables",
      "design",
    ]);

    // 复位，避免影响后续用例
    await apiCall(request, token, "put", "/accounts/preferences/landing-order", {
      landing_order: DEFAULT_ORDER,
    });
  });
});
