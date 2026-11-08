/** Critical — antd v6 弃用告警清零断言（ADR 0074 C7 / D6）.
 *
 * 遍历关键页面收集控制台告警，断言不出现 antd legacy / deprecated 警告。
 * List → Listy 迁移完成后本断言无白名单（原 `[antd: List]` 白名单已随迁移移除）。
 */
import { test, expect } from "../fixtures/auth";
import { getTableId, getWorkspaceId } from "../helpers/api";

test("关键页面无 antd 弃用告警", async ({ page, request }) => {
  const warnings: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "warning") warnings.push(msg.text());
  });

  // 旧「科研项目管理」示例工作区已并入模板示例，改用稳定的销售示例工作区
  const wid = await getWorkspaceId(request, "某企业销售管理");
  const tid = await getTableId(request, wid, "电商销售");

  await page.goto(`/w/${wid}/tables/${tid}`);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({
    timeout: 10_000,
  });

  await page.goto(`/w/${wid}/documents`);
  await expect(page.locator(".cn-app-header")).toBeVisible();

  await page.goto(`/w/${wid}/analytics`);
  await expect(page.locator(".cn-app-header")).toBeVisible();

  await page.goto("/settings");
  await expect(page.locator(".cn-app-header")).toBeVisible();

  const deprecated = warnings.filter((w) => /antd/i.test(w) && /deprecated|弃用/i.test(w));
  expect(deprecated).toEqual([]);
});
