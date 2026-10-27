/**
 * Critical — 文档图表嵌入全链路（ADR 0048 P2）.
 *
 * 覆盖 P2 的两条关键链路（数据准备走 API，交互走真实浏览器）：
 * 1) 编辑器插入图表：工具栏 → 模板挑选 → 设计器保存 → 正文插入 `{{chart:<id>}}`；
 *    提交后查看态预览经成员 render 端点内联渲染 SVG（I1 唯一渲染器）；
 *    导出 Markdown 得到 zip 归档：正文改写为 `assets/chart-<id>.svg` 且资产随包（D6）；
 * 2) 游客分享页免登录渲染（D9）：无登录态上下文直达公开页，图表经
 *    `/api/v1/documents/share/{token}/charts/{id}/render` 匿名渲染，且不触碰任何工作区鉴权接口。
 *
 * 为什么必须 E2E：插入链路跨三个弹层与光标插入，导出依赖浏览器下载与真实 zip 字节，
 * 游客链路要验证真实路由守卫下不产生鉴权请求 —— jsdom 单测无法覆盖。
 */
import { test, expect } from "../fixtures/auth";
import { inflateRawSync } from "node:zlib";
import fs from "node:fs";
import type { APIRequestContext, Browser, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";

let wid: number;
let token: string;
/** 本轮用例的标题都带时间戳，避免与历史数据同名 */
const stamp = Date.now();

test.describe.configure({ timeout: 150_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

interface ChartItem {
  id: number;
  title: string;
}

/** 解析 zip 局部文件头（Python zipfile 写 seekable 流无 data descriptor，尺寸可信） */
function readZipEntries(buf: Buffer): Map<string, Buffer> {
  const entries = new Map<string, Buffer>();
  let off = 0;
  while (off + 30 <= buf.length && buf.readUInt32LE(off) === 0x04034b50) {
    const method = buf.readUInt16LE(off + 8);
    const compressedSize = buf.readUInt32LE(off + 18);
    const nameLen = buf.readUInt16LE(off + 26);
    const extraLen = buf.readUInt16LE(off + 28);
    const name = buf.subarray(off + 30, off + 30 + nameLen).toString("utf-8");
    const dataStart = off + 30 + nameLen + extraLen;
    const data = buf.subarray(dataStart, dataStart + compressedSize);
    entries.set(name, method === 0 ? Buffer.from(data) : inflateRawSync(data));
    off = dataStart + compressedSize;
  }
  return entries;
}

/**
 * 以无登录态的新浏览器上下文打开公开页，并收集其发出的全部 `/api/` 请求。
 * 显式传空 storageState，避免把登录态带进来（同 document-public-share 口径）。
 */
async function openPublicPage(browser: Browser, shareToken: string) {
  const baseURL = test.info().project.use.baseURL;
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();
  const apiPaths: string[] = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.pathname.startsWith("/api/")) apiPaths.push(url.pathname);
  });
  await page.goto(`/public/share/${shareToken}`);
  return { context, page, apiPaths };
}

test.describe("文档图表嵌入", () => {
  test("插入图表 → 提交 → 预览渲染；导出含图表资产；游客免登录渲染", async ({
    page,
    browser,
  }: {
    page: Page;
    browser: Browser;
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const chartTitle = `e2e 图表 ${stamp}`;
    const docTitle = `图表嵌入 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n图表占位将插入到这里。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    try {
      // 1) 草稿默认编辑态：工具栏 → 插入图表 → 挑模板 → 设计器保存
      await page.goto(`/w/${wid}/documents/${docId}`);
      await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
      await page.getByTestId("md-toolbar-chart").click();
      const pick = page.getByTestId("chart-template-pick-stacked-bar-horizontal");
      await expect(pick).toBeVisible({ timeout: 20_000 });
      await pick.click();

      const save = page.getByTestId("chart-designer-save");
      await expect(save).toBeVisible({ timeout: 20_000 });
      await expect(save).toBeEnabled();
      await page.getByTestId("chart-designer-title").fill(chartTitle);
      await save.click();
      await expect(page.getByText("图表已创建并插入").first()).toBeVisible({ timeout: 20_000 });

      // 2) 经 API 找到新实例 id（列表即真相，不依赖前端状态）
      const chartsResp = await apiCall(page.request, token, "get", `/workspaces/${wid}/charts`);
      expect(chartsResp.status, JSON.stringify(chartsResp.body)).toBe(200);
      const chart = ((chartsResp.body as { items: ChartItem[] }).items).find(
        (c) => c.title === chartTitle,
      );
      expect(chart, "新建图表未出现在实例列表").toBeTruthy();
      const chartId = chart!.id;

      // 3) 提交修改：等弹窗关闭（成功/失败都会关）后，正文含 {{chart:id}} 落为新版本
      await expect(page.getByTestId("doc-submit-btn")).toBeEnabled({ timeout: 20_000 });
      await page.getByTestId("doc-submit-btn").click();
      await page.getByRole("button", { name: "确认提交" }).click();
      await expect(page.getByRole("dialog")).toBeHidden({ timeout: 20_000 });

      await expect(async () => {
        const contentResp = await apiCall(
          page.request,
          token,
          "get",
          `/workspaces/${wid}/documents/${docId}/content`,
        );
        expect((contentResp.body as { content: string }).content).toContain(`{{chart:${chartId}}}`);
      }).toPass({ timeout: 15_000 });
      // 提交只生成新版本；草稿要显式发布（显式发布入口，见 publishMut）
      await page.getByTestId("doc-publish-toggle").click();
      await expect(async () => {
        const docResp = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${docId}`);
        expect(docResp.status, JSON.stringify(docResp.body)).toBe(200);
        expect((docResp.body as { status: string }).status).toBe("published");
      }).toPass({ timeout: 15_000 });

      // 4) 查看态预览：成员 render 端点产物内联渲染（I1 唯一渲染器）
      await page.getByTestId("doc-mode-switch").getByText("查看", { exact: true }).click();
      const embed = page.getByTestId(`chart-embed-svg-${chartId}`);
      await expect(embed).toBeVisible({ timeout: 20_000 });
      await expect(embed.locator("svg")).toHaveCount(1);

      // 5) 导出 Markdown（D6）：zip 归档，正文改写为 assets/ 引用且资产随包
      const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
      await page.getByTestId("doc-export-btn").click();
      await page.getByRole("menuitem", { name: "导出 Markdown (.md)" }).click();
      const download = await downloadPromise;
      const zipBytes = fs.readFileSync(await download.path());
      const entries = readZipEntries(zipBytes);
      const assetName = `assets/chart-${chartId}.svg`;
      const asset = [...entries.entries()].find(([name]) => name === assetName);
      expect(asset, `归档应含 ${assetName}`).toBeTruthy();
      expect(asset![1].subarray(0, 4).toString(), "资产应为 SVG 文本").toContain("<svg");
      const mdName = [...entries.keys()].find((name) => name.endsWith(".md"));
      expect(mdName, "归档应含 .md 正文").toBeTruthy();
      const mdText = entries.get(mdName!)!.toString("utf-8");
      expect(mdText).toContain(`](assets/chart-${chartId}.svg)`);
      expect(mdText).not.toContain("{{chart:");

      // 6) 游客分享（D9）：匿名上下文直达公开页，图表经分享端点渲染
      const shareResp = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents/${docId}/share`, {
        permission: "viewer",
      });
      expect(shareResp.status, JSON.stringify(shareResp.body)).toBe(201);
      const shareToken = (shareResp.body as { token: string }).token;

      const view = await openPublicPage(browser, shareToken);
      try {
        await expect(view.page.getByTestId("public-share-page")).toBeVisible({ timeout: 20_000 });
        const guestEmbed = view.page.getByTestId(`chart-embed-svg-${chartId}`);
        await expect(guestEmbed).toBeVisible({ timeout: 20_000 });
        await expect(guestEmbed.locator("svg")).toHaveCount(1);

        expect(
          view.apiPaths.some((p) => p === `/api/v1/documents/share/${shareToken}/charts/${chartId}/render`),
          "游客页应走免登录图表渲染端点",
        ).toBe(true);
        expect(
          view.apiPaths.filter((p) => p.startsWith("/api/v1/workspaces/")),
          "游客页不得请求任何工作区鉴权接口",
        ).toEqual([]);
      } finally {
        await view.context.close();
      }
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(
        () => undefined,
      );
      const chartsResp = await apiCall(page.request, token, "get", `/workspaces/${wid}/charts`);
      const items = (chartsResp.body as { items: ChartItem[] }).items ?? [];
      const mine = items.find((c) => c.title === `e2e 图表 ${stamp}`);
      if (mine) {
        await apiCall(page.request, token, "delete", `/workspaces/${wid}/charts/${mine.id}`).catch(
          () => undefined,
        );
      }
    }
  });
});
