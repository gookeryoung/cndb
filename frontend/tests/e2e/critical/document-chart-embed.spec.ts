/**
 * Critical — 文档图表内嵌块全链路（ADR 0052）.
 *
 * 覆盖关键链路（数据准备走 API，交互走真实浏览器）：
 * 1) 编辑器插入图表：工具栏 → 模板挑选 → 设计器保存 → 正文插入自包含的 ```chart 围栏块；
 *    查看态经成员 render-preview 内联渲染 SVG（I1 唯一渲染器），宽度控件改写块字段；
 *    块内「编辑图表」走设计器 editBlock，只回传新定义并按出现序号整块替换；
 * 2) 提交 / 发布后刷新，图表仍按块定义渲染；
 * 3) 导出 Markdown：归档同时含定义块与 `assets/chart-<指纹>.svg` 静态图（D6）；
 * 4) 游客分享页免登录经 `POST .../share/{token}/charts/render-preview` 渲染，不触碰工作区鉴权接口（D10）；
 * 5) 把导出的 `.md` 再导入：块保留、配对静态图被剥离，不出现双份图表（D7）。
 *
 * 为什么必须 E2E：插入链路跨三个弹层与光标插入，导出依赖浏览器下载与真实 zip 字节，
 * 游客链路要验证真实路由守卫下不产生鉴权请求，重导入依赖真实 multipart 上传与导入管线 ——
 * jsdom 单测无法覆盖。
 */
import { test, expect } from "../fixtures/auth";
import { inflateRawSync } from "node:zlib";
import fs from "node:fs";
import type { APIRequestContext, Browser, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";
/** 与工具栏模板挑选的 key 对应（图表块 `template` 字段 / 前端嵌入块 testid） */
const TEMPLATE_KEY = "stacked-bar-horizontal";

let wid: number;
let token: string;
/** 本轮用例的标题都带时间戳，避免与历史数据同名 */
const stamp = Date.now();

test.describe.configure({ timeout: 180_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

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

test.describe("文档图表内嵌块", () => {
  test("插入块 → 调宽 / 编辑 → 导出含定义块与资产 → 游客免登录渲染 → 重导入去重", async ({
    page,
    browser,
  }: {
    page: Page;
    browser: Browser;
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const chartTitle = `e2e 图表 ${stamp}`;
    const editedTitle = `${chartTitle} 改`;
    const docTitle = `图表嵌入 ${stamp}`;
    let importedDocId: number | null = null;
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
      // ADR 0058：多级列表 — 0070 新增「结构构成」模板后手风琴默认展开首个分类，
      // 本用例模板在「横向对比」分类下，需先展开再选模板项
      await page.locator(".cn-insert-chart-modal").getByText("横向对比", { exact: true }).click({ timeout: 20_000 });
      await page
        .getByTestId(`chart-template-item-${TEMPLATE_KEY}`)
        .click({ timeout: 20_000 });
      const pick = page.getByTestId(`chart-template-pick-${TEMPLATE_KEY}`);
      await expect(pick).toBeVisible({ timeout: 20_000 });
      await pick.click();

      const save = page.getByTestId("chart-designer-save");
      await expect(save).toBeVisible({ timeout: 20_000 });
      await expect(save).toBeEnabled();

      // 设计器实时预览占内容区 ≥ 55%（ADR 0051 C1）
      const preview = page.getByTestId("chart-designer-preview");
      await expect(preview).toBeVisible();
      // 口径是「弹窗内容区」而非 .ant-modal-content 含 padding 的总宽（ADR 0051 D3）。
      // 弹窗有 zoom-in 动画，两次 boundingBox 会落在不同帧上导致比值抖动，
      // 故在同一次 evaluate 里原子取两个矩形。
      const previewRatio = () =>
        page.evaluate(() => {
          const previewEl = document.querySelector<HTMLElement>('[data-testid="chart-designer-preview"]');
          const bodyEl = document.querySelector<HTMLElement>('[data-testid="chart-designer-body"]');
          if (!previewEl || !bodyEl) return 0;
          const bodyWidth = bodyEl.getBoundingClientRect().width;
          return bodyWidth > 0 ? previewEl.getBoundingClientRect().width / bodyWidth : 0;
        });
      await expect.poll(previewRatio, { timeout: 10_000 }).toBeGreaterThanOrEqual(0.55);

      await page.getByTestId("chart-designer-title").fill(chartTitle);
      await save.click();
      await expect(page.getByText(/图表已创建并插入/).first()).toBeVisible({ timeout: 20_000 });

      // 2) 查看态：正文块按定义渲染；宽度控件改写块字段（ADR 0052 D8）
      // 实时预览（CodeMirror）不渲染嵌入块，宽度 / 编辑控件只在查看模式出现。
      await page.getByTestId("doc-mode-switch").getByText("查看", { exact: true }).click();
      const embed = page.getByTestId(`chart-embed-${TEMPLATE_KEY}`);
      await expect(embed).toHaveAttribute("data-width", "50", { timeout: 20_000 });
      // 调宽到 25% 再验证写回（新插入默认即 50，见 chartBlock.ts DEFAULT_CHART_WIDTH）
      await page.getByTestId("chart-embed-width-0").click();
      await page.getByTestId("chart-embed-width-0-preset-25").click();
      await expect(embed).toHaveAttribute("data-width", "25");

      // 2.1) 块内「编辑图表」：设计器 editBlock 只回传定义，不写素材库（D9）
      await page.getByTestId("chart-embed-edit-0").click();
      await expect(page.getByTestId("chart-designer-title")).toHaveValue(chartTitle, { timeout: 20_000 });
      await page.getByTestId("chart-designer-title").fill(editedTitle);
      await page.getByTestId("chart-designer-save").click();
      await expect(page.getByText("图表已更新").first()).toBeVisible({ timeout: 20_000 });
      // editBlock 只回传定义（D9），宽度不在设计器内改动 —— 调宽后的 25 应保留
      await expect(embed).toHaveAttribute("data-width", "25");

      // 3) 回编辑模式提交：正文落为自包含块（模板 + 标题 + 宽度都在块内），旧占位符不再出现
      await page.getByTestId("doc-mode-switch").getByText("编辑", { exact: true }).click();
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
        const content = (contentResp.body as { content: string }).content;
        expect(content).toContain("```chart");
        expect(content).toContain(`"template": "${TEMPLATE_KEY}"`);
        expect(content).toContain(`"title": "${editedTitle}"`);
        expect(content).toContain('"width": 25');
        expect(content).not.toContain("{{chart:");
      }).toPass({ timeout: 15_000 });

      // 提交只生成新版本；草稿要显式发布（显式发布入口，见 publishMut）
      await page.getByTestId("doc-publish-toggle").click();
      await expect(async () => {
        const docResp = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${docId}`);
        expect(docResp.status, JSON.stringify(docResp.body)).toBe(200);
        expect((docResp.body as { status: string }).status).toBe("published");
      }).toPass({ timeout: 15_000 });

      // 4) 查看态预览：成员 render-preview 产物内联渲染（I1 唯一渲染器）
      await page.getByTestId("doc-mode-switch").getByText("查看", { exact: true }).click();
      const svg = page.getByTestId("chart-embed-svg");
      await expect(svg).toBeVisible({ timeout: 20_000 });
      await expect(svg.locator("svg")).toHaveCount(1);
      await expect(embed).toHaveAttribute("data-width", "25");

      // 4.1) 刷新后宽度仍生效（宽度已随块落库）
      await page.reload();
      await page.getByTestId("doc-mode-switch").getByText("查看", { exact: true }).click();
      await expect(page.getByTestId("chart-embed-svg")).toBeVisible({ timeout: 20_000 });
      await expect(embed).toHaveAttribute("data-width", "25");

      // 4.2) 查看态点击图表放大预览（ADR 0060）：弹层复用同一份 SVG，关闭后回到正文
      await page.getByTestId("chart-embed-svg").click();
      const zoomPreview = page.getByTestId("chart-embed-preview-svg");
      await expect(zoomPreview).toBeVisible({ timeout: 20_000 });
      await expect(zoomPreview.locator("svg")).toHaveCount(1);
      await page.locator(".ant-modal-close").click(); // antd 6 + zhCN：关闭钮 aria-label 随本地化为「关闭」，按类名定位
      await expect(zoomPreview).toBeHidden({ timeout: 20_000 });
      await expect(page.getByTestId("chart-embed-svg")).toBeVisible();

      // 5) 导出 Markdown（D6）：zip 归档同时含定义块与指纹命名的静态资产
      const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
      await page.getByTestId("doc-export-btn").click();
      await page.getByRole("menuitem", { name: "导出 Markdown (.md)" }).click();
      const download = await downloadPromise;
      const zipBytes = fs.readFileSync(await download.path());
      const entries = readZipEntries(zipBytes);
      const assetEntry = [...entries.entries()].find(([name]) =>
        /^assets\/chart-[0-9a-f]{12}\.svg$/.test(name),
      );
      expect(assetEntry, "归档应含 assets/chart-<指纹>.svg").toBeTruthy();
      expect(assetEntry![1].subarray(0, 4).toString(), "资产应为 SVG 文本").toContain("<svg");
      const mdName = [...entries.keys()].find((name) => name.endsWith(".md"));
      expect(mdName, "归档应含 .md 正文").toBeTruthy();
      const mdText = entries.get(mdName!)!.toString("utf-8");
      expect(mdText).toContain("```chart");
      expect(mdText).toContain(`"template": "${TEMPLATE_KEY}"`);
      expect(mdText).toContain(`](assets/${assetEntry![0].replace(/^assets\//, "")})`);
      expect(mdText).not.toContain("{{chart:");

      // 6) 游客分享（D10）：匿名上下文直达公开页，图表经分享 render-preview 渲染
      const shareResp = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents/${docId}/share`, {
        permission: "viewer",
      });
      expect(shareResp.status, JSON.stringify(shareResp.body)).toBe(201);
      const shareToken = (shareResp.body as { token: string }).token;

      const view = await openPublicPage(browser, shareToken);
      try {
        await expect(view.page.getByTestId("public-share-page")).toBeVisible({ timeout: 20_000 });
        const guestEmbed = view.page.getByTestId(`chart-embed-${TEMPLATE_KEY}`);
        await expect(guestEmbed).toBeVisible({ timeout: 20_000 });
        await expect(guestEmbed.getByTestId("chart-embed-svg").locator("svg")).toHaveCount(1);

        expect(
          view.apiPaths.some(
            (p) => p === `/api/v1/documents/share/${shareToken}/charts/render-preview`,
          ),
          "游客页应走免登录图表渲染端点",
        ).toBe(true);
        expect(
          view.apiPaths.filter((p) => p.startsWith("/api/v1/workspaces/")),
          "游客页不得请求任何工作区鉴权接口",
        ).toEqual([]);

        // 游客页同样支持点击放大（ADR 0060 I3 模式无关）
        await guestEmbed.getByTestId("chart-embed-svg").click();
        await expect(view.page.getByTestId("chart-embed-preview-svg").locator("svg")).toHaveCount(1);
        await view.page.locator(".ant-modal-close").click(); // antd 6 + zhCN：同上
        await expect(view.page.getByTestId("chart-embed-preview-svg")).toBeHidden({ timeout: 20_000 });
      } finally {
        await view.context.close();
      }

      // 7) 重导入导出的 .md（D7）：块保留、配对静态图剥离，不出现双份
      // 图表块按光标位置插入（用例未移动光标 → 落在正文最前），导出后首个非空行是块
      // 而非 H1，故重导入标题取自**文件名**而非一级标题；这里按文件名定位新文档。
      const importFileName = `重导入 ${stamp}.md`;
      const importedTitle = importFileName.replace(/\.md$/, "");
      const importResp = await page.request.post(
        `/api/v1/workspaces/${wid}/documents/import/files`,
        {
          headers: { Authorization: `Bearer ${token}` },
          multipart: {
            files: {
              name: importFileName,
              mimeType: "text/markdown",
              buffer: Buffer.from(mdText, "utf-8"),
            },
            status: "draft",
          },
        },
      );
      expect(importResp.status(), await importResp.text()).toBe(200);

      const tree = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/tree`);
      expect(tree.status).toBe(200);
      const importedDoc = flatten(tree.body as { items: TreeNode[] }).find(
        (n) => !n.is_folder && n.id !== docId && n.title.startsWith(importedTitle),
      );
      expect(importedDoc, "重导入的文档未落库").toBeTruthy();
      importedDocId = importedDoc!.id;

      const importedContent = await apiCall(
        page.request,
        token,
        "get",
        `/workspaces/${wid}/documents/${importedDocId}/content`,
      );
      expect(importedContent.status).toBe(200);
      const importedText = (importedContent.body as { content: string }).content;
      expect(importedText.match(/```chart/g) ?? []).toHaveLength(1);
      expect(importedText).not.toContain("](assets/chart-");
      expect(importedText).not.toContain("{{chart:");
    } finally {
      if (importedDocId !== null) {
        await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${importedDocId}`).catch(
          () => undefined,
        );
      }
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(
        () => undefined,
      );
      const chartsResp = await apiCall(page.request, token, "get", `/workspaces/${wid}/charts`);
      const items = (chartsResp.body as { items: ChartItem[] }).items ?? [];
      const mine = items.find((c) => c.title === chartTitle);
      if (mine) {
        await apiCall(page.request, token, "delete", `/workspaces/${wid}/charts/${mine.id}`).catch(
          () => undefined,
        );
      }
    }
  });
});

interface ChartItem {
  id: number;
  title: string;
}

interface TreeNode {
  id: number;
  title: string;
  is_folder: boolean;
  children?: TreeNode[];
}

function flatten(nodes: { items: TreeNode[] }): TreeNode[] {
  const out: TreeNode[] = [];
  const walk = (list: TreeNode[]) => {
    for (const node of list) {
      out.push(node);
      if (node.children?.length) walk(node.children);
    }
  };
  walk(nodes.items ?? []);
  return out;
}
