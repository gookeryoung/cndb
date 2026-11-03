/**
 * Critical — 文档文件导入（真实浏览器 / 仅 chromium-authed）.
 *
 * 覆盖「文档模块导入本地文件」两条链路（需求 0088 后：单文件 + 压缩包，文件夹方式已移除）：
 * - 单文件 md：预览数量 → 导入 → 正文自动格式化（标题行剥离、多余空白清理）落库；
 * - 压缩包 zip：包内路径还原层级文件夹与文档，正文原样保留（标题不剥离）。
 *
 * 为什么必须 E2E：系统文件选择框是浏览器原生行为，jsdom 单测无法真实覆盖（单测只 spy input.click()）。
 * 两种模式都走真实 filechooser；zip 在用例内手写构造（store 不压缩，
 * 与 document-chart-embed 手写 zip 解析同思路，避免新增依赖）。
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

  test("压缩包：上传 zip → 层级文件夹 + 文档，正文原样保留", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    await openDocuments(page);

    await page.getByTestId("doc-file-import").click();
    await expect(page.getByTestId("file-import-pick")).toBeVisible({ timeout: 15_000 });
    // 切到压缩包模式（需求 0088：文件夹方式移除，改为上传 zip 按包内路径还原层级）
    await page.getByTestId("file-import-mode").getByText("压缩包", { exact: true }).click();
    await expect(page.getByTestId("vault-import-pick")).toBeVisible({ timeout: 10_000 });

    // 造包：唯一外层目录会被剥掉（Obsidian 打包习惯，见 services/obsidian.py _common_root），
    // 内层「季度报告」还原为层级文件夹；无 front-matter → 标题取文件名、正文原样保留
    const zip = buildZip([
      {
        path: `导出 ${stamp}/季度报告/总览 ${stamp}.md`,
        content: `# 导入总览 ${stamp}\n\n\n\n这是   总览正文。   \n`,
      },
      {
        path: `导出 ${stamp}/季度报告/明细 ${stamp}.md`,
        content: `# 明细 ${stamp}\n\n明细   内容  \n`,
      },
    ]);

    const chooserPromise = page.waitForEvent("filechooser", { timeout: 10_000 });
    await page.getByTestId("vault-import-pick").click();
    const chooser = await chooserPromise;
    await chooser.setFiles({
      name: `层级文档 ${stamp}.zip`,
      mimeType: "application/zip",
      buffer: zip,
    });

    // 预览：2 篇笔记 + 待建文件夹
    const summary = page.getByTestId("vault-import-summary");
    await expect(summary).toBeVisible({ timeout: 20_000 });
    await expect(summary).toContainText("2 篇");
    await expect(page.getByTestId("vault-import-preview")).toContainText(`季度报告/总览 ${stamp}.md`);

    await page.getByTestId("vault-import-submit").click();
    const result = page.getByTestId("vault-import-result");
    await expect(result).toBeVisible({ timeout: 20_000 });
    await expect(result).toContainText("新增 2 篇");

    // 落库校验走 API：目录树出现层级文件夹与文档；压缩包链路正文原样保留（不剥标题行）
    const tree = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/tree`);
    expect(tree.status).toBe(200);
    const flat = flatten(tree.body as { items: TreeNode[] });
    const overview = flat.find((n) => n.title === `总览 ${stamp}`);
    const detail = flat.find((n) => n.title === `明细 ${stamp}`);
    expect(overview, "总览文档未落库").toBeTruthy();
    expect(detail, "明细文档未落库").toBeTruthy();
    expect(flat.some((n) => n.is_folder && n.title === "季度报告")).toBe(true);

    const content = await apiCall(page.request, token, "get", `/workspaces/${wid}/documents/${overview!.id}/content`);
    expect(content.status).toBe(200);
    expect((content.body as { content: string }).content).toBe(
      `# 导入总览 ${stamp}\n\n\n\n这是   总览正文。   \n`,
    );
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

// ── 手写 store zip 构造（仅文件条目，无目录条目 / 无压缩），供压缩包导入用例使用 ──

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function buildZip(files: Array<{ path: string; content: string }>): Buffer {
  const chunks: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.path, "utf8");
    const data = Buffer.from(file.content, "utf8");
    const crc = crc32(data);
    // 本地文件头：store（method=0）+ UTF-8 文件名标志（bit 11）
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    chunks.push(local, name, data);
    // 中央目录项
    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0);
    entry.writeUInt16LE(20, 4);
    entry.writeUInt16LE(20, 6);
    entry.writeUInt16LE(0x0800, 8);
    entry.writeUInt32LE(crc, 16);
    entry.writeUInt32LE(data.length, 20);
    entry.writeUInt32LE(data.length, 24);
    entry.writeUInt16LE(name.length, 28);
    entry.writeUInt32LE(offset, 42);
    central.push(entry, name);
    offset += 30 + name.length + data.length;
  }
  const centralBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(files.length, 8);
  eocd.writeUInt16LE(files.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...chunks, centralBuf, eocd]);
}
