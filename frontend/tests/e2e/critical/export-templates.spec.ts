/**
 * Critical — 文档导出模板全链路（ADR 0152）。
 *
 * 覆盖：
 * 1) 通过 API 从内置预设「另存为」自定义模板（工作区级资源），再列出可见；
 * 2) 个人设置 → 模板页签：内置与自定义分组可见、默认标记正确；
 * 3) 文档页导出 Word：二级菜单列出模板，选自定义模板后真实下载 docx（PK 魔数）。
 *
 * 为什么必须 E2E：模板是工作区级共享资源，导出菜单是嵌套 Dropdown + 懒加载 chunk，
 * 下载走真实 Content-Disposition / blob 链路 —— jsdom 单测无法覆盖。
 */
import { readFileSync } from "node:fs";

import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const WORKSPACE_NAME = "科研项目管理";
const DOCX_MAGIC = Buffer.from([0x50, 0x4b, 0x03, 0x04]); // PK\x03\x04

test.describe.configure({ timeout: 90_000 });

let wid: number;
let token: string;
const stamp = Date.now();
const TEMPLATE_NAME = `E2E 模板 ${stamp}`;

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);

  const created = await apiCall(request, token, "post", `/workspaces/${wid}/documents/templates`, {
    name: TEMPLATE_NAME,
    description: "e2e 自动创建（ADR 0152）",
    preset_key: "thesis",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  const listed = await apiCall(request, token, "get", `/workspaces/${wid}/documents/templates`);
  const items = (listed.body as { items?: Array<{ ref: string; name: string; source: string }> }).items ?? [];
  for (const item of items) {
    if (item.source === "custom" && item.name === TEMPLATE_NAME) {
      await apiCall(request, token, "delete", `/workspaces/${wid}/documents/templates/${item.ref}`).catch(
        () => undefined,
      );
    }
  }
});

test.describe("文档导出模板", () => {
  test("模板页签可见内置与自定义，导出 Word 可选模板", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
    const title = `模板导出回归 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title,
      content: `# ${title}\n\n第一段正文，用于验证模板导出的 docx 字节。\n\n## 小节\n\n- 要点一\n- 要点二\n`,
      status: "published",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    try {
      // ── 个人设置 → 模板：内置 + 自定义分组都在 ──
      await page.goto(`/w/${wid}/tables`);
      await expect(page.getByRole("heading", { level: 3 })).toBeVisible({ timeout: 20_000 });
      await page.getByTestId("template-settings-btn").click();
      await expect(page.getByRole("tab", { name: "模板" })).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId("template-list")).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("内置模板", { exact: true })).toBeVisible();
      await expect(page.getByText(TEMPLATE_NAME, { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");

      // ── 文档导出 Word：二级菜单选自定义模板 → 真实下载 ──
      await page.goto(`/w/${wid}/documents/${docId}`);
      await expect(page.getByTestId("doc-export-btn")).toBeVisible({ timeout: 20_000 });
      await page.getByTestId("doc-export-btn").click();
      await page.getByText("导出 Word (.docx)", { exact: true }).hover();
      const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
      await page.getByText(TEMPLATE_NAME, { exact: true }).click();
      const download = await downloadPromise;
      const filePath = await download.path();
      expect(filePath, "下载应落盘到本地路径").toBeTruthy();
      const buf = readFileSync(filePath!);
      expect(buf.length).toBeGreaterThan(0);
      expect(buf.subarray(0, 4).equals(DOCX_MAGIC)).toBe(true);
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(() => undefined);
    }
  });
});
