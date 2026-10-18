/**
 * Critical — 图片字段上传交互（真实浏览器 / 仅 chromium-authed）.
 *
 * 回归背景：图片字段编辑区整块曾是 antd `Upload.Dragger` 的「点击即上传」区，
 * 用户想先点一下字段再 `Ctrl+V` 粘贴截图时，系统文件选择框会立刻弹出挡在前面，
 * 必须先取消弹窗才能粘贴。修复后：点击字段只聚焦粘贴区，选文件只走显式
 * 「选择图片」按钮，拖拽入口保留。
 *
 * 为什么必须 E2E：系统文件选择框是浏览器原生行为，jsdom 单测只能 spy
 * `input.click()`；这里用 Playwright 的 `filechooser` 事件做真实断言。
 *
 * 数据准备走 API，断言走 UI；表建在 seed 的「项目管理」工作区，
 * 避免污染 workspace 1（那里有「恰好 9 张表」的并行用例）。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：项目管理（admin 为 OWNER，无其它 e2e 用例依赖该工作区的表清单） */
const WORKSPACE_NAME = "项目管理";
/** 1x1 PNG：上传/粘贴只需后端能识别的图片字节 */
const PNG_1PX =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

let wid: number;
let tid: number;
let rowId: number;
let token: string;

/** 建一张含 text + image 字段的临时表，并建一行供「更新」路径使用. */
test.beforeAll(async ({ request }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);

  const created = await apiCall(request, token, "post", `/workspaces/${wid}/tables`, {
    name: `E2E 图片字段 ${Date.now()}`,
    description: "图片字段点击/粘贴/选文件交互",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  tid = (created.body as { id: number }).id;

  const fields = [
    { name: "姓名", field_type: "text", order: 0 },
    { name: "照片", field_type: "image", order: 1, config: { multiple: true } },
  ];
  for (const field of fields) {
    const res = await apiCall(request, token, "post", `/workspaces/${wid}/tables/${tid}/fields`, field);
    expect([200, 201], JSON.stringify(res.body)).toContain(res.status);
  }

  const row = await apiCall(request, token, "post", `/workspaces/${wid}/tables/${tid}/records`, {
    values: { 姓名: "图片字段-E2E", 照片: [] },
  });
  expect([200, 201], JSON.stringify(row.body)).toContain(row.status);
  rowId = (row.body as { id: number }).id;
});

test.afterAll(async ({ request }) => {
  if (!tid) return;
  // 软删除临时表：e2e 数据每轮重建，这里只保证同轮其它用例看到的表列表干净
  await apiCall(request, token, "delete", `/workspaces/${wid}/tables/${tid}`);
});

/** 打开表 Grid 并等待骨架渲染完成. */
async function openGrid(page: Page) {
  await page.goto(`/w/${wid}/tables/${tid}`);
  await expect(page.getByTestId("add-row-btn")).toBeVisible({ timeout: 20_000 });
}

/** 在页面内合成一次带图片的粘贴事件（真实 Ctrl+V 无法在 headless 中投递剪贴板文件）. */
async function pasteImage(page: Page) {
  await page.evaluate((pngB64: string) => {
    const bin = atob(pngB64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    const file = new File([bytes], "pasted.png", { type: "image/png" });
    const data = new DataTransfer();
    data.items.add(file);
    // useImagePaste 监听 document 级 paste（取 clipboardData.items 里的图片）
    document.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true }));
  }, PNG_1PX);
}

/** 等待图片上传请求成功. */
function waitUpload(page: Page) {
  return page.waitForResponse(
    (r) => r.url().includes("/files") && r.request().method() === "POST" && r.status() === 201,
    { timeout: 20_000 },
  );
}

test.describe("图片字段上传交互", () => {
  test("新增行：点字段不弹文件框、可直接粘贴；选文件走显式按钮", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    await openGrid(page);

    // 激活行内新增 → 图片字段编辑区出现
    await page.getByTestId("add-row-btn").click();
    const newRow = page.locator('[data-row-key="__new__"]');
    await expect(newRow).toHaveCount(1);
    const zone = newRow.getByTestId("image-field");
    await expect(zone).toBeVisible();

    // ── 1) 点击字段（拖拽区文案）只聚焦，不弹系统文件选择框 ──
    // 旧实现：Dragger 默认 openFileDialogOnClick=true，点击会直接唤起 filechooser
    let chooserOpened = false;
    const markChooser = () => {
      chooserOpened = true;
    };
    page.on("filechooser", markChooser);
    try {
      await zone.getByText(/或拖拽到此/).click();
      // 给浏览器一个窗口：若真的唤起原生文件框，filechooser 事件会在此间到达
      await page.waitForTimeout(600);
      expect(chooserOpened, "点击图片字段不应弹出系统文件选择框").toBeFalsy();
      // 点击后字段已聚焦 → 可直接 Ctrl+V
      await expect(zone).toBeFocused();
    } finally {
      page.off("filechooser", markChooser);
    }

    // ── 2) 直接粘贴截图 → 上传成功并出现缩略图 ──
    const pasteUpload = waitUpload(page);
    await pasteImage(page);
    await pasteUpload;
    await expect(zone.locator(".ant-image-img").first()).toBeVisible({ timeout: 20_000 });

    // ── 3) 只有显式「选择图片」按钮才唤起文件选择框；选中后追加第二张 ──
    const [chooser] = await Promise.all([
      page.waitForEvent("filechooser", { timeout: 10_000 }),
      newRow.getByTestId("image-field-pick").click(),
    ]);
    const pickUpload = waitUpload(page);
    await chooser.setFiles({
      name: "picked.png",
      mimeType: "image/png",
      buffer: Buffer.from(PNG_1PX, "base64"),
    });
    await pickUpload;
    await expect(zone.locator(".ant-image-img")).toHaveCount(2, { timeout: 20_000 });

    // 放弃草稿，避免留下半成品行
    await newRow.getByTestId("row-cancel-btn").click();
    await expect(newRow).toHaveCount(0);
  });

  test("整行编辑（更新已有行）：点字段不弹文件框，Ctrl+V 直接上传", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    await openGrid(page);

    const row = page.locator(`[data-row-key="${rowId}"]`);
    await expect(row).toBeVisible({ timeout: 20_000 });
    await row.getByTestId("row-edit-btn").click();

    const zone = row.getByTestId("image-field");
    await expect(zone).toBeVisible();

    // 点击字段不唤起系统文件框（旧实现在这里会弹窗挡住粘贴）
    let chooserOpened = false;
    const markChooser = () => {
      chooserOpened = true;
    };
    page.on("filechooser", markChooser);
    try {
      await zone.getByText(/或拖拽到此/).click();
      await page.waitForTimeout(600);
      expect(chooserOpened, "整行编辑下点击图片字段也不应弹出文件选择框").toBeFalsy();
      await expect(zone).toBeFocused();
    } finally {
      page.off("filechooser", markChooser);
    }

    // 粘贴上传 → 编辑态缩略图出现
    const upload = waitUpload(page);
    await pasteImage(page);
    await upload;
    await expect(zone.locator(".ant-image-img").first()).toBeVisible({ timeout: 20_000 });

    await page.getByTestId("row-cancel-btn").click();
  });
});
