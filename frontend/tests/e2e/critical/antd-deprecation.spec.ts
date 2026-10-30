/** Critical — antd v6 弃用告警清零断言（ADR 0074 C7 / D6）.
 *
 * 遍历关键页面收集控制台告警，断言不出现 antd legacy / deprecated 警告。
 * 白名单（已登记的遗留项）：`[antd: List]` —— List 组件自 antd 6.6 起整体废弃
 * （推荐 Listy），涉及文档列表等 7 处调用点与 `.cn-doc-list` CSS 耦合，迁移单列
 * 后续项（见 ADR 0074 交接），不在本次属性级清零范围内。
 */
import { test, expect } from "../fixtures/auth";
import { getTableId, getWorkspaceId } from "../helpers/api";

test("关键页面无 antd 弃用告警（List 白名单除外）", async ({ page, request }) => {
  const warnings: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "warning") warnings.push(msg.text());
  });

  const wid = await getWorkspaceId(request, "科研项目管理");
  const tid = await getTableId(request, wid, "科研项目");

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
  // 已登记遗留项：List 组件整体废弃（迁移 Listy 为后续项）
  const unregistered = deprecated.filter((w) => !/\[antd: List\]/.test(w));
  expect(unregistered).toEqual([]);
});
