/** P2 Critical — 复用模块库跨工作区引用（ADR 0118）.
 *
 * 走完整链路：工作区 A 发布公开模块 v1/v2 → 工作区 B 引用锁定 v1 并编译 →
 * 依赖面板提示升级并一键升级到 v2 → A 归档模块后 B 既有设计仍可打开编译 →
 * B 备份归档导入为新工作区，lib: 引用随 vendor 快照离线可编译。
 * 模块发布 / 归档 / 归档导入走 API 构造，UI 验证编辑器编译与升级交互。
 * 仅 chromium-authed 项目（需要 admin 登录态，admin 是自建工作区的 owner）。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, apiCall } from "../helpers/api";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";

const ANON = ["setup", "chromium-anon"];

/** 唯一后缀，避免并行分片撞名 */
const uniq = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;

const PART_V1 = "param dw = 10\ncyl(d = dw, h = 2)";
const PART_V2 = "param dw = 12\ncyl(d = dw, h = 4)";

test.describe("复用模块库跨工作区（ADR 0118）", () => {
  const createdWsIds: number[] = [];
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "cndb-e2e-design-library-"));

  test.afterEach(async ({ request }) => {
    const token = await getAdminToken(request);
    for (const wid of createdWsIds.splice(0)) {
      await apiCall(request, token, "delete", `/workspaces/${wid}`);
    }
  });

  async function createWorkspace(request: any, name: string): Promise<number> {
    const token = await getAdminToken(request);
    const resp = await apiCall(request, token, "post", "/workspaces", { name });
    expect(resp.status).toBe(201);
    const wid = (resp.body as { id: number }).id;
    createdWsIds.push(wid);
    return wid;
  }

  async function createDesign(
    request: any,
    wid: number,
    body: { title: string; kind: string; content: string },
  ): Promise<number> {
    const token = await getAdminToken(request);
    const resp = await apiCall(request, token, "post", `/workspaces/${wid}/designs`, body);
    expect(resp.status).toBe(201);
    return (resp.body as { id: number }).id;
  }

  test("发布 → 跨工作区锁定引用 → 一键升级 → 归档仍可用 → 备份导入离线可编译", async ({
    page,
    request,
  }) => {
    test.setTimeout(240_000);
    const moduleName = `E2E标准轮毂-${uniq}`;

    // ── A：发布公开模块 v1 ──
    const wsA = await createWorkspace(request, `e2e模块库A-${uniq}`);
    const partA = await createDesign(request, wsA, {
      title: `轮毂源-${uniq}`,
      kind: "part",
      content: PART_V1,
    });
    const token = await getAdminToken(request);
    const publish1 = await apiCall(request, token, "post", `/workspaces/${wsA}/designs/${partA}/publish`, {
      visibility: "public",
      name: moduleName,
    });
    expect(publish1.status).toBe(200);
    const moduleKey = (publish1.body as { module_key: string }).module_key;
    expect((publish1.body as { version_number: number }).version_number).toBe(1);

    // ── B：引用锁定 v1，编辑器编译通过 ──
    const wsB = await createWorkspace(request, `e2e模块库B-${uniq}`);
    const asmB = await createDesign(request, wsB, {
      title: `引用小车-${uniq}`,
      kind: "assembly",
      content: `use "lib:${moduleKey}@1"() as wheel\n`,
    });
    await page.goto(`/w/${wsB}/design/${asmB}`);
    await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 30_000 });

    // ── A：发布 v2；B 锁定版本不漂移 ──
    const putResp = await apiCall(request, token, "put", `/workspaces/${wsA}/designs/${partA}/content`, {
      content: PART_V2,
    });
    expect(putResp.status).toBe(200);
    const publish2 = await apiCall(request, token, "post", `/workspaces/${wsA}/designs/${partA}/publish`, {
      visibility: "public",
      comment: "e2e v2",
    });
    expect(publish2.status).toBe(200);
    expect((publish2.body as { version_number: number }).version_number).toBe(2);

    // ── B：依赖面板列出库引用并一键升级到 v2 ──
    const modulesResp = await apiCall(request, token, "get", `/workspaces/${wsB}/design-library/modules`);
    expect(modulesResp.status).toBe(200);
    const modules = modulesResp.body as Array<{ id: number; module_key: string; latest_version: number }>;
    const target = modules.find((m) => m.module_key === moduleKey);
    expect(target).toBeTruthy();
    expect(target!.latest_version).toBe(2);

    await page.reload();
    await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("design-library-refs-btn").click();
    const upgradeBtn = page.getByTestId(`design-library-upgrade-${target!.id}`);
    await expect(upgradeBtn).toBeVisible({ timeout: 15_000 });
    await upgradeBtn.click();
    // 升级改写源码为 @2 并重新编译通过
    await expect(page.locator(".cm-content")).toContainText(`lib:${moduleKey}@2`, { timeout: 30_000 });
    await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 30_000 });

    // ── A：归档模块；B 既有引用继续可编译 ──
    const patchResp = await apiCall(request, token, "patch", `/workspaces/${wsA}/design-library/modules/${target!.id}`, {
      is_archived: true,
    });
    expect(patchResp.status).toBe(200);
    await page.reload();
    await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 30_000 });

    // ── B：备份归档导入为新工作区，lib: 引用随 vendor 离线可编译 ──
    const exportResp = await request.get(`/api/v1/workspaces/${wsB}/export/archive?include_secrets=false`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(exportResp.status()).toBe(200);
    const archivePath = path.join(tmpDir, `ws-b-${uniq}.tar.gz`);
    writeFileSync(archivePath, await exportResp.body());
    const importedName = `e2e模块库B导入-${uniq}`;
    const importResp = await request.post("/api/v1/workspaces/import/archive", {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: {
          name: "backup.tar.gz",
          mimeType: "application/gzip",
          buffer: readFileSync(archivePath),
        },
        name: importedName,
      },
    });
    expect(importResp.status()).toBe(201);
    const importedWs = ((await importResp.json()) as { workspace: { id: number } }).workspace.id;
    createdWsIds.push(importedWs);
    const listResp = await apiCall(request, token, "get", `/workspaces/${importedWs}/designs`);
    const importedAsm = (listResp.body as Array<{ id: number; title: string }>).find(
      (d) => d.title === `引用小车-${uniq}`,
    );
    expect(importedAsm).toBeTruthy();
    await page.goto(`/w/${importedWs}/design/${importedAsm!.id}`);
    await expect(page.getByTestId("design-compile-ok")).toBeVisible({ timeout: 30_000 });
  });
});
