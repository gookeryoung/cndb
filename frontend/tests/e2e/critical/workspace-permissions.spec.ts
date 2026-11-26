/**
 * Critical — 工作区设置页按能力位门控（ADR 0161 D1 / D3 / D6）.
 *
 * 验收链路：
 * 1) owner（含 TRANSFER_OWNERSHIP / DELETE_WORKSPACE / WIDEN_ACCESS）能看到危险操作区与转让 / 删除；
 * 2) 仅有管理面、无数据面的团队管理员（capabilities 含 EDIT_SETTINGS / MANAGE_MEMBERS，
 *    data_role=null）看不到危险操作区，团队归属、编辑权限放宽、可见性放宽均不可操作，
 *    但成员管理入口保留。
 *
 * 为什么必须 E2E：门控依赖真实 `/capabilities` 响应 + 设置页渲染 + AntD 控件禁用态，
 * jsdom 单测覆盖不到真实请求与 Tab 切换后的控件状态。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken } from "../helpers/api";

test.describe.configure({ timeout: 90_000 });

let wid: number;
let token: string;
const stamp = Date.now();

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  const created = await apiCall(request, token, "post", "/workspaces", {
    name: `权限门控回归 ${stamp}`,
    modules: ["tables", "documents", "design"],
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  wid = (created.body as { id: number }).id;
  // 置为 private：团队管理员视角下 member / public 两个放宽选项都应被禁用
  const narrowed = await apiCall(request, token, "patch", `/workspaces/${wid}`, {
    visibility: "private",
    allow_edit: false,
  });
  expect(narrowed.status).toBe(200);
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (wid) await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
});

test.describe("工作区设置页能力位门控", () => {
  test("owner 可见危险操作区（转让 / 删除）", async ({ page }) => {
    await page.goto(`/w/${wid}/settings`);
    await expect(page.getByText("危险操作")).toBeVisible();
    await expect(page.getByRole("button", { name: /转让所有权/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /删除工作区/ })).toBeVisible();
  });

  test("团队管理员（有管理面无数据面）不可见危险操作，且不能放宽暴露", async ({ page }) => {
    // 拦截能力位：模拟团队管理员（后端真实返回同形状，避免依赖第二个账号与团队种子）
    await page.route(new RegExp(`/api/v1/workspaces/${wid}/capabilities`), async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data_role: null,
          team_role: "admin",
          capabilities: ["EDIT_SETTINGS", "MANAGE_MEMBERS"],
          sources: { manage: "team_admin" },
        }),
      });
    });

    await page.goto(`/w/${wid}/settings`);

    await expect(page.getByText("危险操作")).toHaveCount(0);
    await expect(page.getByTestId("ws-settings-team-select")).toHaveClass(/ant-select-disabled/);
    // 可见性放宽选项不可选（private → member/public 被禁用）
    await page.getByTestId("ws-settings-visibility-select").click();
    await expect(page.locator(".ant-select-item-option-disabled")).toHaveCount(2);

    // 权限页：编辑权限由关到开需 WIDEN_ACCESS；成员管理能力保留
    await page.getByText("权限管理").click();
    await expect(page.getByRole("switch").first()).toBeDisabled();
    await expect(page.getByRole("button", { name: /添加成员/ }).first()).toBeVisible();
  });
});
