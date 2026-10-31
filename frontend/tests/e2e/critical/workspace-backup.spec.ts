/** P1 Critical — 工作区全量备份/恢复（ADR 0075）.
 *
 * 覆盖：归档导出下载；归档导入为新工作区；覆盖恢复危险确认流。
 * 归档文件通过 API 导出构造，UI 流程验证前端入口与交互门禁。
 * 仅 chromium-authed 项目（需要 admin 登录态，admin 是自建工作区的 owner）。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, apiCall } from "../helpers/api";
import { mkdtempSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";

const ANON = ["setup", "chromium-anon"];

/** 唯一后缀，避免并行分片撞名 */
const uniq = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;

test.describe("工作区备份归档（v9）", () => {
  const createdWsIds: number[] = [];
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "cndb-e2e-backup-"));

  test.afterEach(async ({ request }) => {
    const token = await getAdminToken(request);
    for (const wid of createdWsIds.splice(0)) {
      await apiCall(request, token, "delete", `/workspaces/${wid}`);
    }
  });

  /** 通过 API 创建工作区并返回 id */
  async function createWorkspace(request: any, name: string): Promise<number> {
    const token = await getAdminToken(request);
    const resp = await apiCall(request, token, "post", "/workspaces", { name });
    expect(resp.status).toBe(201);
    const wid = (resp.body as { id: number }).id;
    createdWsIds.push(wid);
    return wid;
  }

  /** 通过 API 导出全量归档，写入临时文件并返回路径 */
  async function exportArchive(request: any, wid: number): Promise<string> {
    const token = await getAdminToken(request);
    const resp = await request.get(`/api/v1/workspaces/${wid}/export/archive`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const file = path.join(tmpDir, `ws-${wid}-${uniq}.tar.gz`);
    writeFileSync(file, await resp.body());
    return file;
  }

  test("归档导出：备份对话框下载 .tar.gz", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const name = `e2e归档导出-${uniq}`;
    const wid = await createWorkspace(request, name);

    await page.goto("/w");
    await page.getByLabel(`展开「${name}」`).click();
    await page.getByTestId(`backup-btn-${wid}`).click();
    await expect(page.getByText("备份工作区")).toBeVisible();

    const downloadPromise = page.waitForEvent("download");
    await page.getByText("下载全量归档（.tar.gz）").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.tar\.gz$/);
  });

  test("归档导入：从全量归档创建新工作区", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const name = `e2e归档导入源-${uniq}`;
    const wid = await createWorkspace(request, name);
    const archivePath = await exportArchive(request, wid);

    await page.goto("/w");
    await page.getByRole("button", { name: "导入工作区" }).click();
    await page.setInputFiles('input[type="file"]', archivePath);
    await page.getByRole("button", { name: "开始导入" }).click();

    await expect(page.getByText(`已导入工作区「${name}」`)).toBeVisible({ timeout: 30000 });
    // 导入成功后新工作区应出现在列表（清理 by name 兜底，防 id 未收录）
    const token = await getAdminToken(request);
    const list = await apiCall(request, token, "get", "/workspaces");
    const imported = (list.body as Array<{ id: number; name: string }>).find(
      (w) => w.name === name,
    );
    if (imported && !createdWsIds.includes(imported.id)) createdWsIds.push(imported.id);
    expect(imported).toBeTruthy();
    void wid;
  });

  test("覆盖恢复：危险确认流（勾选 + 输入工作区名）", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const name = `e2e覆盖恢复-${uniq}`;
    const wid = await createWorkspace(request, name);
    const archivePath = await exportArchive(request, wid);

    await page.goto("/w");
    await page.getByLabel(`展开「${name}」`).click();
    await page.getByTestId(`backup-btn-${wid}`).click();
    await expect(page.getByText("危险操作：覆盖恢复")).toBeVisible();

    // 未完成双重确认时按钮禁用
    const restoreBtn = page.getByRole("button", { name: "覆盖恢复本工作区" });
    await expect(restoreBtn).toBeDisabled();

    // 选择归档 + 勾选 + 输入工作区名 → 按钮解禁
    await page.locator(".ant-modal input[type='file']").setInputFiles(archivePath);
    await page.getByRole("checkbox").check();
    await page.getByPlaceholder(/输入工作区名称/).fill(name);
    await expect(restoreBtn).toBeEnabled();

    await restoreBtn.click();
    await expect(page.getByText(/恢复完成：/)).toBeVisible({ timeout: 30000 });
  });
});
