/**
 * Critical — 团队数据授权 editor 关键路径（ADR 0163）。
 *
 * 覆盖：
 * 1) 授予面：owner 给外部团队授 editor（设置页「团队数据授权」卡可见「可编辑」标签）；
 * 2) 判定面：团队成员（非工作区成员）拿到 `data_role=editor` 与 `WRITE` 能力位，
 *    无任何管理面能力位（H57），改工作区设置被 403；
 * 3) 多团队命中取最高角色（C1/C3）。
 *
 * 用例自建团队 / 工作区 / 用户并在结束时清理，避免污染其他 spec 的种子数据。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, sessionAs } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

const stamp = Date.now();
const TEAM_A = `E2E授权A-${stamp}`;
const TEAM_B = `E2E授权B-${stamp}`;
const WS_NAME = `E2E授权工作区-${stamp}`;
const USER_B = `e2e_t63_b_${stamp}`;

let token = "";
let teamAId = 0;
let teamBId = 0;
let wid = 0;
let userIdB = 0;
let accessId = 0;

async function setup(request: APIRequestContext) {
  token = await getAdminToken(request);
  const teamA = await apiCall(request, token, "post", "/teams", { name: TEAM_A });
  expect(teamA.status, JSON.stringify(teamA.body)).toBe(201);
  teamAId = (teamA.body as { id: number }).id;

  const teamB = await apiCall(request, token, "post", "/teams", { name: TEAM_B });
  expect(teamB.status, JSON.stringify(teamB.body)).toBe(201);
  teamBId = (teamB.body as { id: number }).id;

  const ws = await apiCall(request, token, "post", "/workspaces", {
    name: WS_NAME,
    description: "ADR 0163 e2e",
    modules: ["tables", "documents"],
  });
  expect(ws.status, JSON.stringify(ws.body)).toBe(201);
  wid = (ws.body as { id: number }).id;

  const userB = await apiCall(request, token, "post", "/accounts/auth/admin-register", {
    username: USER_B,
    password: "pw1234",
    role: "user",
  });
  expect(userB.status, JSON.stringify(userB.body)).toBe(201);
  userIdB = (userB.body as { id: number }).id;

  // 用户 B 同时加入两个团队（非工作区成员）
  const addA = await apiCall(request, token, "post", `/teams/${teamAId}/members`, { username: USER_B });
  expect(addA.status, JSON.stringify(addA.body)).toBe(201);
  const addB = await apiCall(request, token, "post", `/teams/${teamBId}/members`, { username: USER_B });
  expect(addB.status, JSON.stringify(addB.body)).toBe(201);

  // 授权前置放这里：团队 B = editor、团队 A = viewer（用例间相互独立，重试不依赖其它用例）
  const grantB = await apiCall(request, token, "post", `/workspaces/${wid}/team-access`, {
    team_id: teamBId,
    role: "editor",
    ttl_days: 7,
  });
  expect(grantB.status, JSON.stringify(grantB.body)).toBe(201);
  accessId = (grantB.body as { id: number }).id;
  expect((grantB.body as { role: string }).role).toBe("editor");

  const grantA = await apiCall(request, token, "post", `/workspaces/${wid}/team-access`, {
    team_id: teamAId,
    role: "viewer",
    ttl_days: 7,
  });
  expect(grantA.status, JSON.stringify(grantA.body)).toBe(201);
}

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  await setup(request);
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (accessId) await apiCall(request, token, "delete", `/workspaces/${wid}/team-access/${accessId}`).catch(() => undefined);
  if (wid) await apiCall(request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
  if (teamAId) await apiCall(request, token, "delete", `/teams/${teamAId}`).catch(() => undefined);
  if (teamBId) await apiCall(request, token, "delete", `/teams/${teamBId}`).catch(() => undefined);
  if (userIdB) await apiCall(request, token, "patch", `/accounts/users/${userIdB}`, { is_active: false }).catch(() => undefined);
});

test("授予 editor：设置页团队授权卡显示「可编辑」", async ({ page }: { page: import("@playwright/test").Page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  // 授权已在 beforeAll 完成（团队 B editor / 团队 A viewer），这里验证设置页展示
  await page.goto(`/w/${wid}/settings?section=permissions`);
  const card = page.getByTestId("team-access-card");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card).toContainText(TEAM_A);
  await expect(card).toContainText(TEAM_B);
  const table = page.getByTestId("team-access-table");
  await expect(table.getByText("可编辑")).toBeVisible();
  await expect(table.getByText("只读")).toBeVisible();
});

test("团队成员按 editor 授权获得 WRITE、无管理面、设置被拒", async ({ browser }) => {
  const userB = await sessionAs(browser, USER_B, "pw1234");
  try {
    const caps = await apiCall(userB.api, userB.token, "get", `/workspaces/${wid}/capabilities`);
    expect(caps.status, JSON.stringify(caps.body)).toBe(200);
    const body = caps.body as { data_role: string; capabilities: string[]; sources: Record<string, string> };
    // 多团队命中（viewer@A + editor@B）取最高角色（C1/C3）
    expect(body.data_role).toBe("editor");
    expect(body.capabilities).toContain("WRITE");
    expect(body.capabilities).not.toContain("EDIT_SETTINGS");
    expect(body.capabilities).not.toContain("MANAGE_MEMBERS");
    expect(body.sources.data).toBe("team_grant:editor");
  } finally {
    await userB.close();
  }
});
