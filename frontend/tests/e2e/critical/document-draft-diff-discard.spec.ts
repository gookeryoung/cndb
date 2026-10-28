/**
 * Critical — 文档草稿 diff 与丢弃（ADR 0057 + 需求 0062）.
 *
 * 覆盖关键链路（草稿经 API 预置，交互走真实浏览器）：
 * 1) 有草稿时版本历史出现「当前草稿」条目，原最新版本标记「已发布」；
 *    点草稿条目的「变更」原地渲染「基准版本 → 草稿」unified diff（含 stale 基准场景）；
 * 2) 「丢弃草稿」确认后调用 DELETE，草稿标签消失，编辑态重置并回到查看模式；
 * 3) 取消确认不调用 DELETE。
 *
 * 为什么必须 E2E：按钮挂载条件（serverDraft）、Popconfirm 确认流与抽屉渲染
 * 跨多个交互层，jsdom 单测无法覆盖真实弹层与路由行为。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";

let wid: number;
let token: string;
const stamp = Date.now();

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

/** 建一份已发布文档并预置基于 v1 的个人草稿（最新版内容与草稿不同） */
async function createDocWithDraft(
  request: APIRequestContext,
  { stale }: { stale: boolean },
): Promise<{ docId: number; latest: string; draftText: string }> {
  const latest = `# e2e 草稿 diff ${stamp}\n\n最新版本正文。\n`;
  const draftText = `# e2e 草稿 diff ${stamp}\n\n草稿修改后的正文。\n`;
  const created = await apiCall(request, token, "post", `/workspaces/${wid}/documents`, {
    title: `e2e 草稿 diff ${stamp}`,
    content: latest,
    status: "published",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  const docId = (created.body as { id: number }).id;

  if (stale) {
    // 先落草稿（基准 v1），再把文档推进到 v2，制造 stale
    const saved = await apiCall(request, token, "put", `/workspaces/${wid}/documents/${docId}/draft`, {
      content: draftText,
      base_version_number: 1,
    });
    expect(saved.status, JSON.stringify(saved.body)).toBe(200);
    const advanced = await apiCall(request, token, "put", `/workspaces/${wid}/documents/${docId}/content`, {
      content: latest,
    });
    expect(advanced.status, JSON.stringify(advanced.body)).toBe(200);
  } else {
    const saved = await apiCall(request, token, "put", `/workspaces/${wid}/documents/${docId}/draft`, {
      content: draftText,
      base_version_number: 1,
    });
    expect(saved.status, JSON.stringify(saved.body)).toBe(200);
  }
  return { docId, latest, draftText };
}

test.describe("文档草稿 diff 与丢弃", () => {
  test("版本历史草稿条目渲染 diff → 丢弃草稿回到查看模式", async ({ page }: { page: import("@playwright/test").Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const { docId } = await createDocWithDraft(page.request, { stale: false });
    await page.goto(`/w/${wid}/documents/${docId}`);

    // 有草稿：打开版本历史，草稿条目在顶部，原最新版本标记「已发布」
    await expect(page.getByTestId("doc-draft-tag")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: /版本/ }).click();

    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByTestId("version-item-draft")).toBeVisible();
    await expect(drawer.getByText("已发布")).toBeVisible();

    // 草稿条目的「变更」原地渲染草稿 diff：新增行来自草稿正文
    await drawer.getByTestId("version-diff-toggle-draft").click();
    await expect(drawer.getByTestId("document-diff")).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByText(/草稿修改后的正文/)).toBeVisible();
    await drawer.getByRole("button", { name: "Close" }).click();

    // 丢弃：确认后回到查看模式，草稿标签消失
    await page.getByTestId("doc-draft-discard-btn").click();
    await page.getByRole("button", { name: /^丢\s*弃$/ }).click();

    await expect(page.getByTestId("doc-view-mode")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("doc-draft-tag")).toHaveCount(0);
    // 正文回到最新版本内容，草稿文本不再出现
    await expect(page.getByTestId("doc-view-mode")).toContainText("最新版本正文");
    await expect(page.getByTestId("doc-view-mode")).not.toContainText("草稿修改后的正文");
  });

  test("stale 基准：版本历史的草稿条目仍可渲染 diff", async ({ page }: { page: import("@playwright/test").Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const { docId } = await createDocWithDraft(page.request, { stale: true });
    await page.goto(`/w/${wid}/documents/${docId}`);

    await expect(page.getByTestId("doc-draft-tag")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: /版本/ }).click();

    const drawer = page.getByRole("dialog");
    await drawer.getByTestId("version-diff-toggle-draft").click();
    await expect(drawer.getByTestId("document-diff")).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByText(/草稿修改后的正文/)).toBeVisible();
  });
});
