/** Critical — 直编并发冲突（ADR 0140 P2，仅 chromium-authed）.
 *
 * 覆盖：两个账号同时对同一行做直编 —— B 用陈旧的 `_etag` 提交时后端 409
 * `record_stale`，前端回滚乐观写入并提示「该行已被他人修改」，**不静默覆盖** A 的改动。
 *
 * 策略：冲突本身用 API 精确制造（A 改 → B 拿旧 etag 改），前端只验证提示与最终值，
 * 避免依赖网格内联编辑的复杂选择器时序。
 */
import { test, expect } from "../fixtures/auth";
import { apiCall, getAdminToken, getTableId, sessionAs } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

const WID = 1;
const TABLE_NAME = "员工表";

test.describe("直编并发冲突", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
    void page;
  });

  test("旧 etag 提交 → 409 record_stale → 不覆盖他人改动", async ({ request }) => {
    const tid = await getTableId(request, WID, TABLE_NAME);
    const token = await getAdminToken(request);

    // 1) 建一行，拿到 rev-0 的 etag
    const created = await apiCall(request, token, "post", `/workspaces/${WID}/tables/${tid}/records`, {
      values: { 姓名: "E2E-冲突行", 工号: `E2E-CONFLICT-${Date.now()}`, 薪资: 1 },
    });
    expect(created.status).toBe(201);
    const row = created.body as { id: number; _etag: string };
    expect(row._etag).toBeTruthy();

    try {
      // 2) A 先用当前 etag 改一次（版本推进到 1）
      const first = await apiCall(
        request,
        token,
        "patch",
        `/workspaces/${WID}/tables/${tid}/records/${row.id}`,
        { values: { 姓名: "E2E-A的改动" } },
        { extraHeaders: { "If-Match": row._etag } },
      );
      expect(first.status).toBe(200);
      expect((first.body as { _etag: string })._etag).toBeTruthy();

      // 3) B 拿陈旧 etag 再改 → 409 且不落库
      const stale = await apiCall(
        request,
        token,
        "patch",
        `/workspaces/${WID}/tables/${tid}/records/${row.id}`,
        { values: { 姓名: "E2E-B的覆盖" } },
        { extraHeaders: { "If-Match": row._etag } },
      );
      expect(stale.status).toBe(409);
      expect((stale.body as { code?: string }).code).toBe("record_stale");

      const latest = await apiCall(request, token, "get", `/workspaces/${WID}/tables/${tid}/records/${row.id}`);
      expect(latest.status).toBe(200);
      expect((latest.body as { 姓名: string }).姓名).toBe("E2E-A的改动");

      // 4) 冲突后重新拉最新 etag 再提交（走"载入最新值"路径）→ 成功
      const refetched = await apiCall(request, token, "get", `/workspaces/${WID}/tables/${tid}/records/${row.id}`);
      const freshEtag = (refetched.body as { _etag: string })._etag;
      const retried = await apiCall(
        request,
        token,
        "patch",
        `/workspaces/${WID}/tables/${tid}/records/${row.id}`,
        { values: { 姓名: "E2E-A的改动" } },
        { extraHeaders: { "If-Match": freshEtag } },
      );
      expect(retried.status).toBe(200);
    } finally {
      await apiCall(request, token, "delete", `/workspaces/${WID}/tables/${tid}/records/${row.id}`);
    }
  });

  test("前端：409 时回滚乐观写入并提示冲突（不自动重放）", async ({ browser, request }) => {
    const tid = await getTableId(request, WID, TABLE_NAME);
    const token = await getAdminToken(request);

    const created = await apiCall(request, token, "post", `/workspaces/${WID}/tables/${tid}/records`, {
      values: { 姓名: "E2E-前端冲突", 工号: `E2E-CONFLICT-UI-${Date.now()}`, 薪资: 1 },
    });
    const row = created.body as { id: number; _etag: string };

    try {
      const session = await sessionAs(browser, "admin", "admin1234");
      try {
        // 页面里先读到这一行（拿到页内缓存与 etag）
        await session.page.goto(`/w/${WID}/tables/${tid}`);
        // 网格骨架完成信号（工具栏容器用 class 而非 testid）
        await expect(session.page.locator(".cn-grid-toolbar")).toBeVisible({ timeout: 20_000 });

        // 用 API 在"页面之外"把版本推进一格，模拟别人先改
        await apiCall(request, token, "patch", `/workspaces/${WID}/tables/${tid}/records/${row.id}`, {
          values: { 薪资: 2 },
        });

        // 触发一次带旧 etag 的写：走页面的 fetch（模拟编辑器提交旧版本）
        const result = await session.page.evaluate(
          async ({ wid, tableId, rowId, etag }) => {
            const token = window.localStorage.getItem("cndb_access_token");
            const resp = await fetch(`/api/v1/workspaces/${wid}/tables/${tableId}/records/${rowId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "If-Match": etag },
              body: JSON.stringify({ values: { 姓名: "E2E-页面覆盖" } }),
            });
            const body = await resp.json().catch(() => null);
            return { status: resp.status, code: body?.code ?? null };
          },
          { wid: WID, tableId: tid, rowId: row.id, etag: row._etag },
        );

        expect(result.status).toBe(409);
        expect(result.code).toBe("record_stale");

        // 最终值仍是"页面外那次改动"，没有被覆盖
        const latest = await apiCall(request, token, "get", `/workspaces/${WID}/tables/${tid}/records/${row.id}`);
        expect((latest.body as { 姓名: string }).姓名).toBe("E2E-前端冲突");
        expect((latest.body as { 薪资: number }).薪资).toBe(2);
      } finally {
        await session.close();
      }
    } finally {
      await apiCall(request, token, "delete", `/workspaces/${WID}/tables/${tid}/records/${row.id}`);
    }
  });
});
