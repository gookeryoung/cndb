/**
 * Critical — 团队层级的入口与布局（需求 0157）。
 *
 * 覆盖：
 * 1) 首页默认按团队分组展示工作区（chips + 分组标题，平铺无树）；
 * 2) 顶栏切换器按团队分组，团队组「管理」直达团队页；
 * 3) 团队页 `/teams/:tid?section=` 深链 + 刷新保持；
 * 4) 工作区顶栏显示「团队名 › 工作区」面包屑，点击回团队页；
 * 5) 移动端抽屉顶部「团队 → 工作区」两级导航。
 *
 * 用例自建团队与工作区并在结束时清理，避免污染其他 spec 的种子数据。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

const stamp = Date.now();
const TEAM_NAME = `E2E团队-${stamp}`;
const WS_NAME = `E2E团队工作区-${stamp}`;

let token = "";
let teamId = 0;
let wid = 0;

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  const team = await apiCall(request, token, "post", "/teams", {
    name: TEAM_NAME,
    description: "需求 0157 e2e",
  });
  expect(team.status, JSON.stringify(team.body)).toBe(201);
  teamId = (team.body as { id: number }).id;

  const ws = await apiCall(request, token, "post", "/workspaces", {
    name: WS_NAME,
    description: "需求 0157 e2e",
    modules: ["tables", "documents", "design"],
    team_id: teamId,
  });
  expect(ws.status, JSON.stringify(ws.body)).toBe(201);
  wid = (ws.body as { id: number }).id;
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (wid) await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
  if (teamId) await apiCall(request, token, "delete", `/teams/${teamId}`).catch(() => undefined);
});

test("首页默认按团队分组展示工作区，chips 可收窄", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  await page.goto("/w");
  await expect(page.getByTestId("workspace-list")).toBeVisible({ timeout: 20_000 });

  const chips = page.getByTestId("workspace-team-chips");
  await expect(chips).toBeVisible();
  const teamChip = page.getByTestId(`workspace-team-chip-${teamId}`);
  await expect(teamChip).toBeVisible();

  const group = page.getByTestId(`workspace-group-team-${teamId}`);
  await expect(group).toBeVisible();
  await expect(group).toContainText(TEAM_NAME);
  await expect(group).toContainText(WS_NAME);
  // 平铺：没有树节点
  await expect(page.getByRole("tree")).toHaveCount(0);

  await teamChip.click();
  await expect(page.getByTestId("workspace-group-personal")).toHaveCount(0);
});

test("顶栏切换器按团队分组，组头「管理」直达团队页", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  await page.goto("/w");
  await expect(page.getByTestId("ws-switch-btn")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("ws-switch-btn").click();

  const panel = page.getByTestId("scope-switcher-panel");
  await expect(panel).toBeVisible();
  const group = page.getByTestId(`scope-group-team-${teamId}`);
  await expect(group).toContainText(TEAM_NAME);
  await expect(group.getByTestId(`scope-ws-${wid}`)).toBeVisible();

  await page.getByTestId(`scope-manage-team-${teamId}`).click();
  await page.waitForURL(new RegExp(`/teams/${teamId}`));
  await expect(page.getByTestId("team-page")).toBeVisible();
});

test("团队页深链分区：刷新保持 ?section=members", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  await page.goto(`/teams/${teamId}?section=members`);
  await expect(page.getByTestId("team-header")).toContainText(TEAM_NAME, { timeout: 20_000 });
  await expect(page.getByTestId("team-section-members")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("team-section-members")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("tab", { name: /成员/ })).toHaveAttribute("aria-selected", "true");
});

test("工作区顶栏面包屑显示团队并可点回团队页", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  await page.goto(`/w/${wid}/tables`);
  const crumb = page.getByTestId("header-team-crumb");
  await expect(crumb).toContainText(TEAM_NAME, { timeout: 20_000 });
  await crumb.click();
  await page.waitForURL(new RegExp(`/teams/${teamId}`));
  await expect(page.getByTestId("team-header")).toContainText(TEAM_NAME);
});

test("移动端抽屉顶部按团队 → 工作区两级导航", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/w/${wid}/tables`);
  await expect(page.getByTestId("mobile-nav-btn")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("mobile-nav-btn").click();

  const teamNav = page.getByTestId("mobile-team-nav");
  await expect(teamNav).toBeVisible();
  const teamGroup = page.getByTestId(`mobile-team-${teamId}`);
  await expect(teamGroup).toContainText(TEAM_NAME);
  await teamGroup.locator("summary").click();
  await expect(page.getByTestId(`mobile-team-ws-${wid}`)).toBeVisible();
});
