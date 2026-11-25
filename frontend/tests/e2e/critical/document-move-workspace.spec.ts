/**
 * Critical — 文档跨工作区移动（ADR 0155）。
 *
 * 覆盖：
 * 1) 文档页「更多 → 移动到工作区」→ 选目标工作区 → 确认 → 落在目标工作区文档页；
 * 2) 源工作区列表不再出现该文档；
 * 3) 列表页多选两篇 → 批量「移动到工作区」→ 目标工作区出现两篇；
 * 4) 移动时选「表格快照」引用修复（ADR 0156）：失效的双链与数据表引用被改写为注释 / 静态表格。
 *
 * 为什么必须 E2E：跨工作区移动涉及真实权限、文件搬迁与页面跳转，
 * jsdom 单测只能验证请求载荷。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const SOURCE_WS = "科研项目管理";
const TARGET_WS = "某企业销售管理";
const stamp = Date.now();

test.describe.configure({ timeout: 120_000 });

let sourceId: number;
let targetId: number;
let token: string;

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  sourceId = await getWorkspaceId(request, SOURCE_WS);
  targetId = await getWorkspaceId(request, TARGET_WS);
});

async function createDoc(request: APIRequestContext, title: string): Promise<number> {
  const created = await apiCall(request, token, "post", `/workspaces/${sourceId}/documents`, {
    title,
    content: `# ${title}\n\n跨工作区移动 e2e 正文。\n`,
    status: "published",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  return (created.body as { id: number }).id;
}

test("单篇：文档页移动到目标工作区并跳转", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  const docId = await createDoc(page.request, `移动单篇 ${stamp}`);
  await page.goto(`/w/${sourceId}/documents/${docId}`);
  await expect(page.getByTestId("doc-move-workspace")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("doc-move-workspace").click();
  const modal = page.getByTestId("move-document-body");
  await expect(modal).toBeVisible({ timeout: 10_000 });
  await modal.getByTestId("move-document-target").click();
  await page.getByText(new RegExp(`^${TARGET_WS}（剩余`)).click();
  await page.getByRole("dialog").getByRole("button", { name: /^移\s*动$/ }).click();

  // 跳转到目标工作区的同一篇文档
  await expect(page).toHaveURL(new RegExp(`/w/${targetId}/documents/${docId}`), { timeout: 20_000 });
  // 源工作区列表不再包含（接口层面校验更稳）
  const listed = await apiCall(page.request, token, "get", `/workspaces/${sourceId}/documents`);
  expect(
    (listed.body as { items: Array<{ id: number }> }).items.some(item => item.id === docId),
  ).toBe(false);
});

test("移动时修复引用：双链注释 + 数据表快照（ADR 0156）", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  // 源工作区建一张表，正文同时引用「留在源工作区的文档」与该表
  const tables = await apiCall(page.request, token, "get", `/workspaces/${sourceId}/tables`);
  const tableId = (tables.body as Array<{ id: number }>)[0].id;
  const title = `移动修复 ${stamp}`;
  const created = await apiCall(page.request, token, "post", `/workspaces/${sourceId}/documents`, {
    title,
    content: `# ${title}

见 [[立项申请书]]

{{table:${tableId}}}
`,
    status: "published",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  const docId = (created.body as { id: number }).id;

  await page.goto(`/w/${sourceId}/documents/${docId}`);
  await expect(page.getByTestId("doc-move-workspace")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("doc-move-workspace").click();
  const modal = page.getByTestId("move-document-body");
  await expect(modal).toBeVisible({ timeout: 10_000 });
  await modal.getByTestId("move-document-target").click();
  await page.getByText(new RegExp(`^${TARGET_WS}（剩余`)).click();
  await modal.getByTestId("move-document-repair-strategy").click();
  await page.getByText("表格快照（数据表落为静态表格）").click();
  await page.getByRole("dialog").getByRole("button", { name: /^移\s*动$/ }).click();

  await expect(page).toHaveURL(new RegExp(`/w/${targetId}/documents/${docId}`), { timeout: 20_000 });
  const content = await apiCall(page.request, token, "get", `/workspaces/${targetId}/documents/${docId}/content`);
  const body = (content.body as { content: string }).content;
  // 双链被注释、表格引用落为静态表格
  expect(body).toContain("（已移至「");
  expect(body).toContain("|");
  expect(body).not.toContain("{{table:");
});

test("批量：列表页多选两篇移动到目标工作区", async ({ page }) => {
  test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
  const first = await createDoc(page.request, `移动批量A ${stamp}`);
  const second = await createDoc(page.request, `移动批量B ${stamp}`);

  await page.goto(`/w/${sourceId}/documents`);
  await expect(page.getByTestId(`doc-select-${first}`)).toBeVisible({ timeout: 20_000 });
  await page.getByTestId(`doc-select-${first}`).click();
  await page.getByTestId(`doc-select-${second}`).click();
  await page.getByTestId("doc-batch-move-workspace").click();

  const modal = page.getByTestId("move-document-body");
  await expect(modal).toBeVisible({ timeout: 10_000 });
  await modal.getByTestId("move-document-target").click();
  await page.getByText(new RegExp(`^${TARGET_WS}（剩余`)).click();
  await page.getByRole("dialog").getByRole("button", { name: /^移\s*动$/ }).click();

  await expect.poll(async () => {
    const listed = await apiCall(page.request, token, "get", `/workspaces/${targetId}/documents`);
    const ids = (listed.body as { items: Array<{ id: number }> }).items.map(item => item.id);
    return [first, second].every(id => ids.includes(id));
  }, { timeout: 30_000 }).toBe(true);
});
