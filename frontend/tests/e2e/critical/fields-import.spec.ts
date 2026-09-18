/** Critical — 从其他表引入字段（schema-level 克隆）E2E.
 *
 * 流程：API 建两张表，src 带若干字段 → dst 通过 API /fields/import 引入 →
 *  UI 进入 GridPage 确认 dst 拥有被引入的字段且能正常存储数据.
 */
import { test, expect } from "../fixtures/auth";
import type { APIResponse } from "@playwright/test";

const AUTHS = ["chromium-authed"];

/** 获取 admin token */
async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  return (await resp.json()).access_token;
}

/** 新建工作区 */
async function createWorkspace(request: any, name: string): Promise<number> {
  const token = await getToken(request);
  const resp: APIResponse = await request.post("/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${token}` },
    data: { name },
  });
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()).id;
}

/** 新建数据表（可选带 import_from_table_id 建表即引入字段） */
async function createTable(
  request: any,
  wid: number,
  name: string,
  opts: { import_from_table_id?: number; import_all_fields?: boolean } = {},
): Promise<number> {
  const token = await getToken(request);
  const body: any = { name, ...opts };
  const resp: APIResponse = await request.post(`/api/v1/workspaces/${wid}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()).id;
}

/** 新建字段 */
async function createField(
  request: any,
  wid: number,
  tid: number,
  name: string,
  fieldType: string,
  config: any = {},
): Promise<number> {
  const token = await getToken(request);
  const resp: APIResponse = await request.post(`/api/v1/workspaces/${wid}/tables/${tid}/fields`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { name, field_type: fieldType, config, order: 0 },
  });
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()).id;
}

/** 从其他表引入字段 */
async function importFields(
  request: any,
  wid: number,
  tid: number,
  sourceTableId: number,
  opts: { import_all_fields?: boolean; field_names?: string[]; skip_conflicts?: boolean } = {},
) {
  const token = await getToken(request);
  const resp: APIResponse = await request.post(`/api/v1/workspaces/${wid}/tables/${tid}/fields/import`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { source_table_id: sourceTableId, ...opts },
  });
  return resp;
}

/** 在 GridPage 中确认指定列头存在 */
async function gotoGridAndVerifyColumns(page: any, wid: number, tableName: string, expectedCols: string[]) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.getByRole("menuitem", { name: new RegExp(tableName) }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

  for (const col of expectedCols) {
    await expect(page.locator(`.ant-table-thead`, { hasText: col })).toBeVisible({ timeout: 5000 });
  }
}

for (const auth of AUTHS) {
  test.describe(`字段引入 E2E — ${auth}`, () => {
    test("API 建表 + import_all_fields 引入源表全部字段 → UI 验证", async ({ page, request }) => {
      const wid = await createWorkspace(request, `import-all-${Date.now()}`);

      // 源表 + 3 个字段
      const srcTid = await createTable(request, wid, "SourceAll");
      await createField(request, wid, srcTid, "src_name", "text");
      await createField(request, wid, srcTid, "src_score", "number");
      await createField(request, wid, srcTid, "src_done", "boolean");

      // 目标表：建表时直接从源表引入全部字段
      const dstTid = await createTable(request, wid, "DestAll", {
        import_from_table_id: srcTid,
        import_all_fields: true,
      });

      // UI 验证 —— 进入目标表，三列都应该存在
      await gotoGridAndVerifyColumns(page, wid, "DestAll", ["src_name", "src_score", "src_done"]);
    });

    test("API 从现有表按字段名引入 → UI 验证", async ({ page, request }) => {
      const wid = await createWorkspace(request, `import-names-${Date.now()}`);

      // 源表
      const srcTid = await createTable(request, wid, "SourceNames");
      await createField(request, wid, srcTid, "keep_a", "text");
      await createField(request, wid, srcTid, "skip_b", "number");
      await createField(request, wid, srcTid, "keep_c", "email");

      // 目标表先只建，然后调 /fields/import 按名字引入 keep_a + keep_c
      const dstTid = await createTable(request, wid, "DestNames");
      const resp = await importFields(request, wid, dstTid, srcTid, {
        field_names: ["keep_a", "keep_c"],
      });
      expect(resp.status()).toBe(201);
      const body = await resp.json();
      expect(body.created.length).toBe(2);
      expect(body.total_source_count).toBe(2);

      // UI 验证
      await gotoGridAndVerifyColumns(page, wid, "DestNames", ["keep_a", "keep_c"]);
    });

    test("同名冲突：skip_conflicts=true 跳过 → 非冲突字段正常引入", async ({ page, request }) => {
      const wid = await createWorkspace(request, `import-skip-${Date.now()}`);

      const srcTid = await createTable(request, wid, "SourceSkip");
      await createField(request, wid, srcTid, "dup_name", "text");
      await createField(request, wid, srcTid, "unique_col", "number");

      const dstTid = await createTable(request, wid, "DestSkip");
      // 目标表先有一个 dup_name
      await createField(request, wid, dstTid, "dup_name", "text");

      const resp = await importFields(request, wid, dstTid, srcTid, {
        import_all_fields: true,
        skip_conflicts: true,
      });
      expect(resp.status()).toBe(201);
      const body = await resp.json();
      expect(body.created.length).toBe(1);
      expect(body.skipped.length).toBe(1);
      expect(body.skipped[0]).toContain("dup_name");

      await gotoGridAndVerifyColumns(page, wid, "DestSkip", ["dup_name", "unique_col"]);
    });

  });
}
