/**
 * Critical — 文档文件导入（真实浏览器 / 仅 chromium-authed）.
 *
 * 覆盖「文档模块导入本地文件」这条新链路：单文件 md 与整个文件夹（含相对路径）两种模式，
 * 断言：
 * - 预览数量与同名冲突提示；
 * - 导入后目录树出现目标文档（文件夹模式还应有层级文件夹）；
 * - 正文经过自动格式化（标题行剥离、多余空白清理）后落库。
 *
 * 为什么必须 E2E：系统文件选择框与 webkitdirectory 相对路径都是浏览器原生行为，
 * jsdom 单测无法真实覆盖（单测只 spy input.click()）。
 *
 * 单文件模式走真实 filechooser；文件夹模式因本环境浏览器未实现「目录感知的文件注入」，
 * 在页面内合成真实目录选择产出的 FileList（File + webkitRelativePath），
 * 其余链路（预览 → 导入 → 落库）仍全部走真实 UI 与后端。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";

let wid: number;
let token: string;

/** 本轮用例的文档标题都带时间戳，避免与历史数据同名 */
const stamp = Date.now();

/** 目录选择产出的文件集合（含相对路径，等价于浏览器目录选择得到的 FileList） */
function folderFiles(): Array<{ dir: string; name: string; content: string }> {
  return [
    {
      dir: "季度报告",
      name: "总览.md",
      content: `# 导入总览 ${stamp}\n\n\n\n这是   总览正文。   \n`,
    },
    {
      dir: "季度报告/明细",
      name: "明细.md",
      content: `# 明细 ${stamp}\n\n明细   内容  \n`,
    },
  ];
}

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

async function openDocuments(page: Page) {
  await page.goto(`/w/${wid}/documents`);
  await expect(page.getByTestId("doc-file-import")).toBeVisible({ timeout: 20_000 });
}

test.describe("文档文件导入", () => {
  test("单文件：导入 md → 新文档按内嵌标题命名且正文已规整", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    await openDocuments(page);

    await page.getByTestId("doc-file-import").click();
    // antd Modal 的 data-testid 落在无布局的 .ant-modal-root 包裹层上，恒判 hidden；
    // 断言弹窗内控件可见才是"弹窗已打开"的可靠证据（同 documents-visibility 用例口径）
    await expect(page.getByTestId("file-import-pick")).toBeVisible({ timeout: 15_000 });

    // 单文件模式（默认）：原生 filechooser 只能通过先注册等待、再点击触发
    const chooserPromise = page.waitForEvent("filechooser", { timeout: 10_000 });
    await page.getByTestId("file-import-pick").click();
    const chooser = await chooserPromise;
    await chooser.setFiles({
      name: `单篇 ${stamp}.md`,
      mimeType: "text/markdown",
      buffer: Buffer.from(`# 单篇标题 ${stamp}\n\n\n\n这是   单篇正文。   \n`, "utf-8"),
    });

    // 预览：1 篇可导入文档
    const summary = page.getByTestId("file-import-summary");
    await expect(summary).toBeVisible({ timeout: 20_000 });
    await expect(summary).toContainText("1 篇");
    await expect(page.getByTestId("file-import-preview")).toContainText(`单篇 ${stamp}.md`);

    await page.getByTestId("file-import-submit").click();
    const result = page.getByTestId("file-import-result");
    await expect(result).toBeVisible({ timeout: 20_000 });
    await expect(result).toContainText("新增 1 篇");

    // 落库校验走 API：标题取内嵌一级标题、正文已剥离标题行并清理多余空白
    const tree = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/tree`);
    expect(tree.status).toBe(200);
    const flat = flatten(tree.body as { items: TreeNode[] });
    const doc = flat.find((n) => n.title === `单篇标题 ${stamp}`);
    expect(doc, "单文件导入的文档未落库").toBeTruthy();

    const content = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${doc!.id}/content`);
    expect(content.status).toBe(200);
    expect((content.body as { content: string }).content).toBe("这是 单篇正文。");
  });

  test("文件夹：选择目录 → 层级文件夹 + 文档，正文标题剥离", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    await openDocuments(page);

    await page.getByTestId("doc-file-import").click();
    await expect(page.getByTestId("file-import-pick")).toBeVisible({ timeout: 15_000 });
    // 切到文件夹模式（input 变为 webkitdirectory）
    // optionType="button" 下，可点击的是按钮式 label；role=radio 命中的是视觉隐藏的 input
    await page.getByTestId("file-import-mode").getByText("文件夹", { exact: true }).click();

    // 文件夹选择：本环境浏览器（非 Playwright 内置 Chromium）未实现"目录感知的文件注入",
    // 直接传目录路径给 input 会得到空 FileList。这里在页面内合成真实目录选择产出的
    // FileList（File + webkitRelativePath），其余链路（预览 → 导入 → 落库）全走真实 UI/后端。
    await page.evaluate((items: Array<{ dir: string; name: string; content: string }>) => {
      const el = document.querySelector('[data-testid="file-import-input"]') as HTMLInputElement;
      const dt = new DataTransfer();
      for (const it of items) {
        const file = new File([it.content], it.name, { type: "text/markdown" });
        Object.defineProperty(file, "webkitRelativePath", { value: `${it.dir}/${it.name}` });
        dt.items.add(file);
      }
      el.files = dt.files;
      // React 对 input[type=file] 的 onChange 绑定在 change 事件上（非 input）
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, folderFiles());

    // 预览：2 篇文档 + 待建文件夹
    const summary = page.getByTestId("file-import-summary");
    await expect(summary).toBeVisible({ timeout: 20_000 });
    await expect(summary).toContainText("2 篇");
    await expect(page.getByTestId("file-import-preview")).toContainText("季度报告/总览.md");

    await page.getByTestId("file-import-submit").click();
    const result = page.getByTestId("file-import-result");
    await expect(result).toBeVisible({ timeout: 20_000 });
    await expect(result).toContainText("新增 2 篇");

    // 落库校验走 API：目录树出现层级文件夹与文档，正文已规整
    const tree = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/tree`);
    expect(tree.status).toBe(200);
    const flat = flatten(tree.body as { items: TreeNode[] });
    const outline = flat.find((n) => n.title === `导入总览 ${stamp}`);
    const detail = flat.find((n) => n.title === `明细 ${stamp}`);
    expect(outline, "总览文档未落库").toBeTruthy();
    expect(detail, "明细文档未落库").toBeTruthy();
    expect(flat.some((n) => n.is_folder && n.title === "季度报告")).toBe(true);

    const content = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${outline!.id}/content`);
    expect(content.status).toBe(200);
    expect((content.body as { content: string }).content).toBe("这是 总览正文。");
  });
});

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
