/** Critical — 评分矩阵（ADR 0136）：固定对象 × 月份在网页内直接录入.
 *
 * 锚点：matrix-score-view / matrix-score-cell / matrix-score-row-header / matrix-score-col-header。
 * 通过 API 建临时工作区 / 表 / 字段 / 矩阵视图，页面录入后刷新校验持久化，最后清理工作区。
 */
import { test, expect } from "../fixtures/auth";
import { apiCall, getAdminToken } from "../helpers/api";
import { settle } from "../fixtures/settle";
import type { APIRequestContext } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

interface Created {
  id: number;
}

async function postId(
  request: APIRequestContext,
  token: string,
  url: string,
  data: unknown,
  method: "post" | "patch" = "post",
): Promise<number> {
  const res = await apiCall(request, token, method, url, data);
  expect(res.status, `${method} ${url}: ${JSON.stringify(res.body)}`).toBeLessThan(300);
  return (res.body as Created).id;
}

test.describe("评分矩阵 — 对象 × 月份直接录入", () => {
  test("新建单元格 / 未来月份列录入并刷新持久化", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");
    const token = await getAdminToken(page.request);

    const wid = await postId(page.request, token, "/workspaces", { name: `E2E评分矩阵-${Date.now()}` });
    let tid = 0;
    try {
      tid = await postId(page.request, token, `/workspaces/${wid}/tables`, { name: "部门绩效评分" });
      for (const [name, field_type, config] of [
        ["部门", "select", { options: ["研发部", "市场部", "财务部"] }],
        ["月份", "date", {}],
        ["得分", "number", {}],
      ] as const) {
        const res = await apiCall(page.request, token, "post", `/workspaces/${wid}/tables/${tid}/fields`, {
          name, field_type, config, order: 99, // 顺序不影响断言；创建后按实际 order 升序
        });
        expect(res.status, JSON.stringify(res.body)).toBeLessThan(300);
      }
      const vid = await postId(page.request, token, `/workspaces/${wid}/tables/${tid}/views`, {
        name: "部门绩效评分矩阵",
        view_type: "matrix",
        visibility: "table",
        view_options: {
          row_field: "部门",
          column_field: "月份",
          date_granularity: "month",
          value_field: "得分",
          period_start: "2026-11",
          period_end: "2026-12",
        },
      });

      await page.goto(`/w/${wid}/tables/${tid}?view=${vid}`);
      await expect(page.getByTestId("matrix-score-view")).toBeVisible({ timeout: 15000 });
      await expect(page.getByTestId("matrix-score-row-header")).toHaveCount(3);
      await expect(page.getByTestId("matrix-score-col-header")).toHaveCount(2);

      const cells = page.getByTestId("matrix-score-cell");
      // 第一行（研发部）× 2026-11 / 2026-12 两列，直接录入；未来月份列没有已有行也能创建
      const first = cells.nth(0).getByRole("spinbutton");
      await first.fill("91");
      await first.press("Enter");
      await expect(page.getByText("已保存").first()).toBeVisible({ timeout: 10000 });

      const future = cells.nth(1).getByRole("spinbutton");
      await future.fill("87");
      await future.press("Enter");
      await expect(page.getByText("已保存").first()).toBeVisible({ timeout: 10000 });

      await page.reload();
      await expect(page.getByTestId("matrix-score-view")).toBeVisible({ timeout: 15000 });
      await settle(page);
      const after = page.getByTestId("matrix-score-cell");
      await expect(after.nth(0).getByRole("spinbutton")).toHaveValue("91");
      await expect(after.nth(1).getByRole("spinbutton")).toHaveValue("87");

      // 服务端确认月份落库为当月 1 日
      const rows = await apiCall(page.request, token, "get", `/workspaces/${wid}/tables/${tid}/records?limit=50`);
      const items = ((rows.body as { items?: Array<Record<string, unknown>> }).items ?? []);
      expect(items).toHaveLength(2);
      expect(new Set(items.map((r) => r["月份"]))).toEqual(new Set(["2026-11-01", "2026-12-01"]));
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}`).catch(() => undefined);
    }
  });
});
