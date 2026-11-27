/**
 * Critical — 文档模板整合与文档级排版模板绑定（ADR 0177 P3）。
 *
 * 覆盖：
 * 1) 文档区「内容模板」分区：新建内容模板并绑定内置「公文」排版模板；
 * 2) 「从模板新建」：新文档携带内容模板的 `export_template_ref`；
 * 3) 导出 Word：不显式选模板时按文档绑定解析，真实下载 docx（PK 魔数 + 文件名）。
 *
 * 为什么必须 E2E：绑定跨「模板页 → 文档列表 → 编辑器导出」三处入口，
 * 导出走真实 Content-Disposition / blob 链路，jsdom 单测覆盖不到。
 */
import { readFileSync } from "node:fs";

import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const WORKSPACE_NAME = "科研项目管理";
const DOCX_MAGIC = Buffer.from([0x50, 0x4b, 0x03, 0x04]); // PK\x03\x04

test.describe.configure({ timeout: 120_000 });

let wid: number;
let token: string;
const stamp = Date.now();
const TEMPLATE_NAME = `E2E 绑定模板 ${stamp}`;

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  const listed = await apiCall(request, token, "get", `/workspaces/${wid}/document-content-templates`);
  const items = (listed.body as { items?: Array<{ id: number; name: string }> }).items ?? [];
  for (const item of items) {
    if (item.name === TEMPLATE_NAME) {
      await apiCall(request, token, "delete", `/workspaces/${wid}/document-content-templates/${item.id}`).catch(
        () => undefined,
      );
    }
  }
});

test.describe("文档模板整合与文档级绑定", () => {
  test("内容模板绑定「公文」→ 从模板新建 → 导出 docx 走绑定", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    // ── 模板页：内容模板分区，新建模板并绑定内置「公文」 ──
    await page.goto(`/w/${wid}/documents/templates?kind=content`);
    await expect(page.getByTestId("document-content-templates-page")).toBeVisible({ timeout: 20_000 });

    await page.getByTestId("content-template-create").click();
    await expect(page.getByTestId("content-template-name")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("content-template-name").fill(TEMPLATE_NAME);

    await page.getByTestId("content-template-export-template").click();
    await page.getByText("内置 · 公文", { exact: true }).click();
    await page.getByTestId("content-template-save").click();
    await expect(page.getByText("已保存")).toBeVisible({ timeout: 10_000 });

    // 服务端确实记住了绑定
    const templates = await apiCall(page.request, token, "get", `/workspaces/${wid}/document-content-templates`);
    const template = (
      templates.body as { items?: Array<{ id: number; name: string; export_template_ref: string | null }> }
    ).items?.find(item => item.name === TEMPLATE_NAME);
    expect(template, "内容模板应创建成功").toBeTruthy();
    expect(template!.export_template_ref).toBe("builtin:official");

    // ── 文档列表：「从模板新建」 ──
    await page.goto(`/w/${wid}/documents`);
    await page.getByTestId("doc-create-menu").click();
    await page.getByText("从模板新建").click();
    const picker = page.getByRole("dialog", { name: "从模板新建文档" });
    await expect(picker).toBeVisible({ timeout: 10_000 });
    await picker.getByText(TEMPLATE_NAME, { exact: true }).click();

    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents/\\d+`), { timeout: 20_000 });
    const docId = Number(/\/documents\/(\d+)/.exec(page.url())?.[1]);
    expect(Number.isFinite(docId)).toBe(true);

    const detail = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${docId}`);
    expect((detail.body as { export_template_ref?: string | null }).export_template_ref).toBe("builtin:official");

    try {
      // ── 编辑器：导出 Word 不显式选模板 → 走文档绑定，真实下载 ──
      await expect(page.getByTestId("doc-export-btn")).toBeVisible({ timeout: 20_000 });
      await page.getByTestId("doc-export-btn").click();
      await page.getByText("导出 Word (.docx)", { exact: true }).hover();
      const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
      await page.getByText(/默认模板/).click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/\.docx$/);

      const filePath = await download.path();
      expect(filePath, "下载应落盘到本地路径").toBeTruthy();
      const buf = readFileSync(filePath!);
      expect(buf.length).toBeGreaterThan(0);
      expect(buf.subarray(0, 4).equals(DOCX_MAGIC)).toBe(true);
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(() => undefined);
    }
  });

  // 需求 0185：内置库只读、按分类分组，可作为「从模板新建」来源，可另存为自定义
  test("内置库「科研项目管理」→ 从模板新建 → 另存为（自定义）", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    // ── 模板页：内置库按分类分组，条目带「内置」徽标 ──
    await page.goto(`/w/${wid}/documents/templates?kind=content`);
    await expect(page.getByTestId("document-content-templates-page")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("content-template-category-research-pm")).toContainText("科研项目管理");
    const builtinRow = page.getByTestId("content-template-builtin-research-pm.weekly-report");
    await expect(builtinRow).toContainText("内置");
    await builtinRow.click();
    // 内置只读：只有另存为 / 导出
    await expect(page.getByTestId("content-template-save-as")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("content-template-save")).toHaveCount(0);
    await expect(page.getByTestId("content-template-delete")).toHaveCount(0);
    await expect(page.getByTestId("content-template-preview")).toContainText("本周进展");

    // ── 文档列表：「从模板新建」按内置分类分组 ──
    await page.goto(`/w/${wid}/documents`);
    await page.getByTestId("doc-create-menu").click();
    await page.getByText("从模板新建").click();
    const picker = page.getByRole("dialog", { name: "从模板新建文档" });
    await expect(picker).toBeVisible({ timeout: 10_000 });
    await expect(picker.getByTestId("content-template-picker-category-research-pm")).toContainText(
      "科研项目管理",
    );
    await picker.getByTestId("content-template-option-research-pm.weekly-report").click();

    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents/\\d+`), { timeout: 20_000 });
    const docId = Number(/\/documents\/(\d+)/.exec(page.url())?.[1]);
    expect(Number.isFinite(docId)).toBe(true);

    try {
      // 新建出的文档正文含内置骨架章节
      const content = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${docId}/content`);
      expect(JSON.stringify(content.body)).toContain("本周进展");

      // ── 另存为自定义：出现「（自定义）」条目且可编辑 ──
      await page.goto(`/w/${wid}/documents/templates?kind=content`);
      await page.getByTestId("content-template-builtin-research-pm.weekly-report").click();
      await page.getByTestId("content-template-save-as").click();
      await expect(page.getByTestId("content-template-name")).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId("content-template-name")).toHaveValue("项目周报（自定义）");
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(() => undefined);
      // 清理本用例创建的「（自定义）」条目
      const listed = await apiCall(page.request, token, "get", `/workspaces/${wid}/document-content-templates`);
      const rows = (listed.body as { items?: Array<{ id: number; name: string }> }).items ?? [];
      for (const row of rows) {
        if (row.name.startsWith("项目周报（自定义")) {
          await apiCall(
            page.request,
            token,
            "delete",
            `/workspaces/${wid}/document-content-templates/${row.id}`,
          ).catch(() => undefined);
        }
      }
    }
  });
});

